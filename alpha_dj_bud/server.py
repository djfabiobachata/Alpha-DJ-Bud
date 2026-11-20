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
        self.update = {"available": False, "latest": None, "error": None, "checkedAt": None,
                       "installing": False}
        self.window = None  # pywebview window, if any
        self.new_set(save=False)
        self._open_library()

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
                "keyFromComments": self.settings["keyFromComments"],
                "language": self.settings.get("language", "en"),
                "languages": LANGUAGES,
                "autoGenre": self.settings["autoGenre"],
                "update": self.update,
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
                s["genre"] = body["genre"]
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

    def apply_window(self):
        w = self.window
        if w is None:
            return
        try:
            if self.settings["compact"]:
                w.resize(360, 560)
                w.on_top = True
            else:
                w.resize(1080, 760)
                w.on_top = False
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
