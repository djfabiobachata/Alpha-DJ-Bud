"""Local HTTP server + background monitor of djay Pro."""
import json
import mimetypes
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, urlparse

from . import __version__, recommender
from .djay_library import DjayLibrary, find_database
from .learning import Brain

GENRES = [
    {"id": "bachata", "name": "Bachata"},
    {"id": "salsa", "name": "Salsa"},
    {"id": "zouk", "name": "Zouk"},
]
# names are translated by the UI (event.<id>)
EVENTS = [{"id": "bachata"}, {"id": "salsa"}, {"id": "zouk"}, {"id": "mista"}]
LANGUAGES = ["en", "it", "es"]
MIXED_GENRES = ["bachata", "salsa"]  # mixed nights: Bachata + Salsa (no Zouk)
WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")


def app_home():
    env = os.environ.get("ALPHA_DJ_BUD_HOME")
    if env:
        return os.path.expanduser(env)
    if sys.platform == "darwin":
        return os.path.expanduser("~/Library/Application Support/Alpha DJ Bud")
    return os.path.expanduser("~/.alpha-dj-bud")


class AppState:
    def __init__(self, db_path=None):
        self.home = app_home()
        os.makedirs(self.home, exist_ok=True)
        self.settings_path = os.path.join(self.home, "settings.json")
        self.lock = threading.RLock()
        self.settings = {
            "event": "bachata",
            "genre": "bachata",
            "playlistByGenre": {},
            "options": dict(recommender.DEFAULTS),
            "keyFromComments": False,
            "autoGenre": True,
            "autoUpdateCheck": True,
            "dbPath": db_path,
            "compact": False,
            "language": "en",
        }
        self._load_settings()
        if db_path:
            self.settings["dbPath"] = db_path
        self.brain = Brain(os.path.join(self.home, "brain.json"))
        self.library = None
        self.version = 0
        self.np_source = False
        self.update = {"available": False, "latest": None, "error": None, "checkedAt": None,
                       "installing": False}
        self.window = None  # pywebview window, if any
        self.music = {"ok": False, "error": None, "tracks": 0}
        self.new_set(save=False)
        self._open_library()
        threading.Thread(target=self.music_loop, daemon=True).start()
        self.files = {"ok": False, "tracks": 0, "scanning": False}
        self._files_wake = threading.Event()
        threading.Thread(target=self.files_loop, daemon=True).start()

    # -- settings ----------------------------------------------------------
    def _load_settings(self):
        try:
            with open(self.settings_path, encoding="utf-8") as f:
                saved = json.load(f)
            opts = dict(recommender.DEFAULTS)
            opts.update(saved.get("options") or {})
            self.settings.update(saved)
            self.settings["options"] = opts
        except (OSError, ValueError):
            pass

    def save_settings(self):
        tmp = self.settings_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.settings, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.settings_path)

    def _open_library(self):
        path = find_database(self.settings.get("dbPath"))
        if path:
            self.library = DjayLibrary(path, self.settings.get("keyFromComments"))
            self.library.refresh(force=True)
        else:
            self.library = None

    # -- set / session -------------------------------------------------------
    def new_set(self, save=True):
        with self.lock:
            self.set_start = time.time()
            self.set_id = "set:%d" % int(self.set_start)
            self.played = []          # track ids in this set
            self.hidden = set()
            self.current_id = None
            self.current_source = None
            self.current_deck = None
            self.last_history_time = 0
            self._history_checked = False
            self._np_last = None
            self.np_unmatched = None
            self.shown = []
            self.version += 1

    def end_set(self):
        with self.lock:
            summary = {"tracks": len(self.played), "genre": self.settings["genre"]}
            if len(self.played) >= 2:
                self.brain.end_set(self.settings["genre"])
            self.new_set()
            return summary

    def pool(self, genre=None):
        genre = genre or self.settings["genre"]
        pid = self.settings["playlistByGenre"].get(genre)
        if not self.library or not pid:
            return []
        return self.library.tracks_in(pid)

    def set_current(self, track_id, source, learn=True, deck=None):
        """Make `track_id` the playing track and learn from the transition."""
        with self.lock:
            if not self.library:
                return
            new = self.library.get(track_id)
            if deck is not None:
                self.current_deck = deck
            if new is None or track_id == self.current_id:
                return
            if self.settings.get("autoGenre"):
                self._maybe_switch_genre(track_id)
            prev = self.library.get(self.current_id) if self.current_id else None
            if learn:
                self.brain.observe(self.settings["genre"], prev, new, self.shown, set_id=self.set_id)
            self.current_id = track_id
            self.current_source = source
            self.played.append(track_id)
            self.version += 1

    def _maybe_switch_genre(self, track_id):
        allowed = MIXED_GENRES if self.settings["event"] == "mista" else [self.settings["event"]]
        cur = self.settings["genre"]
        if track_id in set(self.pool(cur)):
            return
        for g in allowed:
            if g != cur and track_id in set(self.pool(g)):
                self.settings["genre"] = g
                self.save_settings()
                return

    # -- background monitor ----------------------------------------------------
    def poll(self):
        if self.library is None:
            self._open_library()
            if self.library is None:
                return
        changed = self.library.refresh()
        np_active = self._poll_now_playing()
        if np_active:
            if changed:
                self.version += 1
            return
        if not changed and self._history_checked:
            return
        self._history_checked = True
        try:
            hist = self.library.history(since_unix=self.set_start - 6 * 3600, limit=30)
        except Exception as e:
            self.library.error = "cannot read djay history: %s" % e
            return
        fresh = [h for h in hist if h["time"] > self.last_history_time]
        if fresh:
            self.last_history_time = fresh[-1]["time"]
            before = [h for h in fresh if h["time"] < self.set_start]
            during = [h for h in fresh if h["time"] >= self.set_start]
            if before and not during and self.current_id is None:
                # track that was already playing when the set started
                self.set_current(before[-1]["track_id"], "djay", learn=False, deck=before[-1]["deck"])
            for h in during:
                self.set_current(h["track_id"], "djay", deck=h["deck"])
        if changed:
            self.version += 1

    # -- Apple Music library -------------------------------------------------
    def load_music(self):
        from . import music_library
        try:
            data = music_library.load()
            self.music = {"ok": True, "error": None, "tracks": len(data["tracks"]),
                          "playlists": len(data["playlists"])}
            if self.library:
                with self.lock:
                    self.library.set_apple_music(data)
        except music_library.MusicLibraryError as e:
            self.music = {"ok": False, "error": str(e), "tracks": 0}
        except Exception as e:
            self.music = {"ok": False, "error": "failed: %s" % e, "tracks": 0}
        self.version += 1

    def music_loop(self, every=600):
        while True:
            if self.library is not None:
                self.load_music()
                if str(self.music.get("error") or "").startswith("notMac"):
                    return
            time.sleep(every if self.music.get("ok") else 60)

    # -- folders on the Mac -------------------------------------------------------
    def scan_folders(self):
        from . import local_files
        folders = list(self.settings.get("folders") or [])
        self.files = dict(self.files, scanning=True)
        self.version += 1
        try:
            data = local_files.scan(folders, os.path.join(self.home, "files-cache.json"))
            self.files = {"ok": True, "tracks": len(data["files"]), "folders": len(folders), "scanning": False}
            if self.library:
                with self.lock:
                    self.library.set_local_files(data if folders else None)
        except Exception as e:
            self.files = {"ok": False, "error": str(e), "tracks": 0, "scanning": False}
        self.version += 1

    def files_loop(self, every=600):
        while True:
            if self.library is not None and self.settings.get("folders"):
                self.scan_folders()
            self._files_wake.wait(every)
            self._files_wake.clear()

    # -- updates -------------------------------------------------------------
    def check_update(self):
        from . import updater
        try:
            info = updater.check()
            self.update.update({"available": info["available"], "latest": info["latest"],
                                "notes": info["notes"], "url": info["url"], "error": None,
                                "checkedAt": time.time()})
            self._update_info = info
        except updater.UpdateError as e:
            self.update.update({"error": e.code, "checkedAt": time.time()})
        except Exception as e:
            self.update.update({"error": "network", "detail": str(e), "checkedAt": time.time()})
        self.update["installedApp"] = bool(updater.installed_app_dir(self.home))
        self.version += 1
        return dict(self.update)

    def update_loop(self, first_delay=5, every=6 * 3600):
        time.sleep(first_delay)
        while True:
            if self.settings.get("autoUpdateCheck", True):
                self.check_update()
            time.sleep(every)

    def install_update(self):
        from . import updater
        self.update["installing"] = True
        try:
            v = updater.install(self.home, getattr(self, "_update_info", None))
        except updater.UpdateError as e:
            self.update["installing"] = False
            return {"ok": False, "code": e.code, "detail": e.detail}
        except Exception as e:
            self.update["installing"] = False
            return {"ok": False, "code": "failed", "detail": str(e)}
        threading.Timer(1.0, updater.restart, args=(self.home,)).start()
        return {"ok": True, "version": v}

    def _poll_now_playing(self):
        """djay writes NowPlaying.txt with the track on air. When it exists and
        is recent, it is the source of truth (history only as fallback)."""
        mtime, info = self.library.read_now_playing()
        if mtime is None or time.time() - mtime > 12 * 3600:
            self.np_source = False
            return False
        self.np_source = True
        key = (info.get("title"), info.get("artist"))
        if key == self._np_last:
            return True
        self._np_last = key
        tid = self.library.match_now_playing(info, set(self.pool()))
        if tid:
            deck = None
            try:
                for h in reversed(self.library.history(limit=20)):
                    if h["track_id"] == tid:
                        deck = h["deck"]
                        break
            except Exception:
                pass
            learn = mtime >= self.set_start or self.current_id is not None
            self.set_current(tid, "djay", learn=learn, deck=deck)
        else:
            print("now playing not in library:", key, file=sys.stderr)
            self.np_unmatched = {"title": info.get("title"), "artist": info.get("artist")}
            self.version += 1
        return True

    def monitor(self, interval=1.5):
        while True:
            try:
                self.poll()
            except Exception as e:  # never let the thread die
                print("monitor:", e, file=sys.stderr)
            time.sleep(interval)

    # -- views -------------------------------------------------------------
    def snapshot(self):
        with self.lock:
            lib = self.library
            genre = self.settings["genre"]
            current = lib.get(self.current_id) if (lib and self.current_id) else None
            pool = self.pool()
            suggestions, stats = ([], {})
            if lib and current:
                suggestions, stats = recommender.recommend(
                    lib, current, pool, self.played, self.brain, genre,
                    self.settings["options"], self.hidden, self.set_id)
            self.shown = [s["id"] for s in suggestions]
            for item in suggestions:
                fp = lib.file_path(item["id"]) if lib.has_file(item["id"]) else None
                item["hasFile"] = bool(fp)
                item["fileUrl"] = ("file://" + quote(fp)) if fp else None
            played = [lib.get(t).to_dict() for t in self.played[-12:] if lib and lib.get(t)]
            cur = current.to_dict() if current else None
            if cur:
                cur["source"] = self.current_source
                cur["deck"] = self.current_deck if self.current_source == "djay" else None
                cur["inPool"] = self.current_id in set(pool)
            return {
                "app": {"name": "Alpha DJ Bud", "version": __version__},
                "version": self.version,
                "events": EVENTS,
                "genres": GENRES,
                "mixedGenres": MIXED_GENRES,
                "event": self.settings["event"],
                "genre": genre,
                "playlistByGenre": self.settings["playlistByGenre"],
                "playlists": lib.tree() if lib else [],
                "poolSize": len(pool),
                "current": cur,
                "played": played,
                "suggestions": suggestions,
                "filterStats": stats,
                "brain": self.brain.stats(genre),
                "options": self.settings["options"],
                "bpmTolerance": dict(recommender.DEFAULTS["bpmToleranceByGenre"],
                                     **(self.settings["options"].get("bpmToleranceByGenre") or {})).get(genre),
                "keyFromComments": self.settings["keyFromComments"],
                "language": self.settings.get("language", "en"),
                "languages": LANGUAGES,
                "autoGenre": self.settings["autoGenre"],
                "update": self.update,
                "nowPlayingFile": self.np_source,
                "music": self.music,
                "files": self.files,
                "folders": self.settings.get("folders") or [],
                "nowPlayingUnmatched": self.np_unmatched,
                "autoUpdateCheck": self.settings.get("autoUpdateCheck", True),
                "compact": self.settings["compact"],
                "hasWindow": self.window is not None,
                "db": {
                    "path": lib.path if lib else None,
                    "ok": bool(lib) and not lib.error,
                    "error": (lib.error if lib else "notFound"),
                    "tracks": len(lib.tracks) if lib else 0,
                },
            }

    def search(self, q, everywhere=False):
        lib = self.library
        if not lib:
            return []
        q = (q or "").lower().strip()
        ids = list(lib.tracks) if everywhere else self.pool()
        out = []
        for tid in ids:
            t = lib.get(tid)
            if t and (not q or q in t.title.lower() or q in t.artist.lower()):
                out.append(t.to_dict())
            if len(out) >= 60:
                break
        return out

    # -- actions -------------------------------------------------------------
    def action(self, name, body):
        s = self.settings
        if name == "update-check":     # network: don't hold the lock
            return self.check_update()
        if name == "update-install":
            return self.install_update()
        with self.lock:
            if name == "event":
                s["event"] = body["event"]
                if body["event"] != "mista":
                    s["genre"] = body["event"]
                elif s["genre"] not in MIXED_GENRES:
                    s["genre"] = MIXED_GENRES[0]
            elif name == "genre":
                g = body["genre"]
                s["genre"] = g
                # clicking a genre outside the current night switches the night too
                if s["event"] == "mista" and g not in MIXED_GENRES:
                    s["event"] = g
                elif s["event"] != "mista" and s["event"] != g:
                    s["event"] = "mista" if (g in MIXED_GENRES and s["event"] in MIXED_GENRES) else g
            elif name == "playlist":
                s["playlistByGenre"][body.get("genre") or s["genre"]] = body["id"]
            elif name == "current":
                self.set_current(body["id"], "manual")
            elif name == "hide":
                self.hidden.add(body["id"])
            elif name == "like":
                self.brain.feedback(s["genre"], body["id"], int(body.get("value", 1)))
            elif name == "options":
                for k, v in (body.get("options") or {}).items():
                    if k in recommender.DEFAULTS:
                        s["options"][k] = v
                if body.get("language") in LANGUAGES:
                    s["language"] = body["language"]
                for k in ("keyFromComments", "autoGenre", "autoUpdateCheck"):
                    if k in body:
                        s[k] = bool(body[k])
                if "keyFromComments" in body and self.library:
                    self.library.key_from_comments = s["keyFromComments"]
                    self.library.refresh(force=True)
                if "dbPath" in body:
                    s["dbPath"] = body["dbPath"] or None
                    self._open_library()
            elif name == "folders":
                folders = list(s.get("folders") or [])
                add, rem = body.get("add"), body.get("remove")
                if add:
                    add = os.path.expanduser(add.strip())
                    if not os.path.isdir(add):
                        return {"ok": False, "code": "notFolder"}
                    if add not in folders:
                        folders.append(add)
                if rem in folders:
                    folders.remove(rem)
                s["folders"] = folders
                if not folders and self.library:
                    self.library.set_local_files(None)
                self._files_wake.set()
            elif name == "newset":
                self.new_set()
            elif name == "endset":
                result = self.end_set()
                self.save_settings()
                return result
            elif name == "import-history":
                if not self.library:
                    return {"imported": 0}
                n = self.brain.import_sessions(s["genre"], self.library.history_sessions(),
                                               self.library, self.pool())
                self.version += 1
                return {"imported": n}
            elif name == "window":
                self.remember_window()
                s["compact"] = bool(body.get("compact"))
                self.apply_window()
            else:
                raise KeyError(name)
            self.version += 1
            self.save_settings()
            return {"ok": True}

    def track_file(self, track_id):
        return self.library.file_path(track_id) if self.library else None

    def native_drag(self, track_id):
        """Arm a real macOS file drag (pywebview window only): the drag itself
        starts on the next native 'mouse dragged' event (see native_drag.py)."""
        path = self.track_file(track_id)
        if not path:
            return {"ok": False, "code": "noFile"}
        if not os.path.exists(path):
            return {"ok": False, "code": "missing", "path": path}
        from . import native_drag
        try:
            if not native_drag.is_installed() and not native_drag.install():
                return {"ok": False, "code": "failed", "detail": native_drag.install_error() or "not installed"}
            native_drag.arm(path)
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "code": "failed", "detail": str(e)}

    # -- window position / size (one frame for the normal window, one for MINI) --
    DEFAULT_FRAMES = {"normal": (1080, 760), "mini": (300, 480)}

    def window_mode(self):
        return "mini" if self.settings.get("compact") else "normal"

    def window_frame(self, mode, screens=None):
        """Saved frame for `mode`, kept on a visible screen; None = default."""
        f = (self.settings.get("windowFrames") or {}).get(mode)
        w, h = self.DEFAULT_FRAMES[mode]
        if not f:
            return {"x": None, "y": None, "w": w, "h": h}
        w, h = max(240, int(f.get("w", w))), max(260, int(f.get("h", h)))
        x, y = f.get("x"), f.get("y")
        if screens and x is not None and y is not None:
            on = [sc for sc in screens
                  if sc["x"] <= x + 40 <= sc["x"] + sc["w"] and sc["y"] <= y + 20 <= sc["y"] + sc["h"]]
            if not on:
                x = y = None  # that screen is gone: let the system place it
            else:
                sc = on[0]
                w, h = min(w, sc["w"]), min(h, sc["h"])
                x = min(max(x, sc["x"]), sc["x"] + sc["w"] - w)
                y = min(max(y, sc["y"]), sc["y"] + sc["h"] - h)
        return {"x": x, "y": y, "w": w, "h": h}

    def _screens(self):
        try:
            import webview
            return [{"x": sc.x, "y": sc.y, "w": sc.width, "h": sc.height} for sc in webview.screens]
        except Exception:
            return None

    def remember_window(self, *_):
        """Called when the window moves or is resized by the DJ."""
        w = self.window
        if w is None or time.time() < getattr(self, "_ignore_window_until", 0):
            return
        try:
            frame = {"x": int(w.x), "y": int(w.y), "w": int(w.width), "h": int(w.height)}
        except Exception:
            return
        self.settings.setdefault("windowFrames", {})[self.window_mode()] = frame
        self._frames_dirty = time.time()

    def save_frames_loop(self):
        while True:
            time.sleep(1.0)
            t = getattr(self, "_frames_dirty", 0)
            if t and time.time() - t > 0.8:
                self._frames_dirty = 0
                try:
                    self.save_settings()
                except Exception:
                    pass

    def apply_window(self):
        w = self.window
        if w is None:
            return
        try:
            mode = self.window_mode()
            f = self.window_frame(mode, self._screens())
            self._ignore_window_until = time.time() + 1.0
            w.on_top = mode == "mini"
            w.resize(f["w"], f["h"])
            if f["x"] is not None:
                w.move(f["x"], f["y"])
        except Exception as e:
            print("window:", e, file=sys.stderr)


def make_handler(state):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, body, ctype="application/json; charset=utf-8"):
            if not isinstance(body, (bytes, bytearray)):
                body = json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            u = urlparse(self.path)
            if u.path == "/api/state":
                return self._send(200, state.snapshot())
            if u.path == "/api/search":
                q = parse_qs(u.query)
                return self._send(200, state.search(q.get("q", [""])[0], q.get("all", ["0"])[0] == "1"))
            if u.path == "/api/fileurl":
                tid = parse_qs(u.query).get("id", [""])[0]
                p = state.track_file(tid)
                return self._send(200, {"path": p, "exists": bool(p and os.path.exists(p))})
            if u.path == "/api/file":
                tid = parse_qs(u.query).get("id", [""])[0]
                p = state.track_file(tid)
                if not p or not os.path.isfile(p):
                    return self._send(404, {"error": "file not found"})
                ctype = mimetypes.guess_type(p)[0] or "application/octet-stream"
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(os.path.getsize(p)))
                self.end_headers()
                with open(p, "rb") as f:
                    while True:
                        chunk = f.read(1 << 16)
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                return
            path = "index.html" if u.path in ("", "/") else u.path.lstrip("/")
            full = os.path.normpath(os.path.join(WEB_DIR, path))
            if not full.startswith(WEB_DIR) or not os.path.isfile(full):
                return self._send(404, {"error": "not found"})
            with open(full, "rb") as f:
                data = f.read()
            ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
            if ctype.startswith("text/") or ctype.endswith("javascript"):
                ctype += "; charset=utf-8"
            self._send(200, data, ctype)

        def do_POST(self):
            u = urlparse(self.path)
            if not u.path.startswith("/api/"):
                return self._send(404, {"error": "not found"})
            n = int(self.headers.get("Content-Length") or 0)
            try:
                body = json.loads(self.rfile.read(n) or b"{}")
                return self._send(200, state.action(u.path[5:], body))
            except KeyError as e:
                return self._send(400, {"error": "unknown action or missing data: %s" % e})
            except Exception as e:
                return self._send(500, {"error": str(e)})

    return Handler


def start_server(state, port=0):
    httpd = ThreadingHTTPServer(("127.0.0.1", port), make_handler(state))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    threading.Thread(target=state.monitor, daemon=True).start()
    threading.Thread(target=state.update_loop, daemon=True).start()
    return httpd
