"""Read-only access to the djay Pro (macOS) media library.

djay keeps its library in a YapDatabase SQLite file
(~/Music/djay/djay Media Library.djayMediaLibrary/MediaLibrary.db) whose rows
are serialized with the proprietary TSAF format. The database runs in WAL mode,
so it can be read safely while djay is open. Alpha DJ Bud never writes to it.
"""
import datetime
import glob
import os
import re
import sqlite3
import sys
import time
from urllib.parse import quote, unquote, urlparse

from . import camelot, tsaf

DEFAULT_DB_CANDIDATES = [
    "~/Music/djay/djay Media Library.djayMediaLibrary/MediaLibrary.db",
    "~/Library/Containers/com.algoriddim.djay-iphone-free/Data/Music/djay/"
    "djay Media Library.djayMediaLibrary/MediaLibrary.db",
    "~/Library/Containers/*algoriddim*/Data/Music/djay/"
    "djay Media Library.djayMediaLibrary/MediaLibrary.db",
]

APPLE_EPOCH = datetime.datetime(2001, 1, 1, tzinfo=datetime.timezone.utc)
ROOT_UUID = "mediaItemPlaylist-root"
TYPE_FOLDER = 0
TYPE_PLAYLIST = 1


def find_database(explicit=None):
    """Return the path of djay's MediaLibrary.db, or None."""
    if explicit:
        p = os.path.expanduser(explicit)
        if os.path.isdir(p):
            p = os.path.join(p, "MediaLibrary.db")
        return p if os.path.exists(p) else None
    found = []
    for pattern in DEFAULT_DB_CANDIDATES:
        found.extend(glob.glob(os.path.expanduser(pattern)))
    if not found:
        return None
    return max(found, key=_db_mtime)


def _db_mtime(path):
    m = 0
    for suffix in ("", "-wal"):
        try:
            m = max(m, os.path.getmtime(path + suffix))
        except OSError:
            pass
    return m


def apple_time_to_unix(t):
    if t is None:
        return None
    return t + 978307200.0


_SPLIT_TITLE = re.compile(r"^\s*(.+?)\s+[-–—]\s+(.+)$")
_BPM_IN_TEXT = re.compile(r"(?<!\d)(\d{2,3}(?:[.,]\d)?)\s*bpm(?![a-z])|(?<![a-z])bpm[\s_:]*(\d{2,3})(?!\d)", re.I)


def bpm_from_text(*texts):
    for t in texts:
        m = _BPM_IN_TEXT.search(t or "")
        if m:
            v = float((m.group(1) or m.group(2)).replace(",", "."))
            if 50 <= v <= 250:
                return v
    return None


def _resolve_macos(loc):
    if sys.platform != "darwin":
        return None
    try:
        from Foundation import NSURL, NSData
    except ImportError:
        return None
    for u in loc["uris"]:
        if "/.file/id=" in u:
            try:
                url = NSURL.URLWithString_(u)
                fp = url.filePathURL() if url is not None else None
                if fp is not None and fp.path():
                    return str(fp.path())
            except Exception:
                pass
    if loc.get("bookmark"):
        try:
            data = NSData.dataWithBytes_length_(loc["bookmark"], len(loc["bookmark"]))
            # 1<<8 = without UI, 1<<9 = without mounting
            url, _stale, _err = NSURL.URLByResolvingBookmarkData_options_relativeToURL_bookmarkDataIsStale_error_(
                data, (1 << 8) | (1 << 9), None, None, None)
            if url is not None and url.path():
                return str(url.path())
        except Exception:
            pass
    return None


def _norm_text(s):
    import unicodedata
    s = unicodedata.normalize("NFKD", str(s or ""))
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def _duration(text):
    m = re.match(r"^\s*(?:(\d+):)?(\d+):(\d{2})\s*$", text or "")
    if not m:
        return None
    h, mnt, sec = m.groups()
    return int(h or 0) * 3600 + int(mnt) * 60 + int(sec)


class Track:
    __slots__ = ("id", "title", "artist", "bpm", "key", "duration",
                 "comments", "genre", "key_source", "djay_title", "djay_artist")

    def __init__(self, id, title, artist, bpm, key, duration, comments=None,
                 genre=None, key_source="djay"):
        self.id = id
        self.title = title or ""
        self.artist = artist or ""
        self.bpm = bpm
        self.key = key
        self.duration = duration
        self.comments = comments or ""
        self.genre = genre or ""
        self.key_source = key_source
        self.djay_title = self.title  # title exactly as shown in djay
        self.djay_artist = self.artist

    def to_dict(self):
        return {
            "id": self.id,
            "title": self.title,
            "artist": self.artist,
            "bpm": round(self.bpm, 1) if self.bpm else None,
            "key": self.key,
            "musicalKey": camelot.CAMELOT_TO_MUSICAL.get(self.key) if self.key else None,
            "duration": round(self.duration) if self.duration else None,
            "genre": self.genre,
        }


class DjayLibrary:
    """Snapshot of the djay library. Call `refresh()` to reload when the file
    changes; `now_playing()` is cheap and reads only the history."""

    def __init__(self, path, key_from_comments=False):
        self.path = path
        self.key_from_comments = key_from_comments
        self.tracks = {}
        self.playlists = {}
        self.loaded_mtime = 0
        self.error = None
        self._history_cache = {}
        self.locations = {}
        self._path_cache = {}
        self.apple_music = None   # data from music_library.load(), merged on each load
        self.local_files = None   # data from local_files.scan(), merged on each load

    # -- low level -------------------------------------------------------
    def _connect(self):
        uri = "file:%s?mode=ro" % self.path.replace("?", "%3f").replace("#", "%23")
        con = sqlite3.connect(uri, uri=True, timeout=2)
        con.execute("PRAGMA query_only = 1")
        return con

    @staticmethod
    def _collection(con, name):
        out = {}
        for key, data in con.execute(
                "SELECT key, data FROM database2 WHERE collection = ?", (name,)):
            try:
                obj = tsaf.decode(data)
            except Exception:
                continue
            if isinstance(obj, dict):
                out[key] = obj
        return out

    # -- loading -----------------------------------------------------------
    def needs_refresh(self):
        return _db_mtime(self.path) > self.loaded_mtime

    def refresh(self, force=False):
        if not force and not self.needs_refresh():
            return False
        mtime = _db_mtime(self.path)
        try:
            con = self._connect()
            try:
                self._load(con)
            finally:
                con.close()
            self.error = None
        except Exception as e:  # keep previous snapshot
            self.error = "cannot read the djay library: %s" % e
            return False
        self.loaded_mtime = mtime
        return True

    def _load(self, con):
        items = self._collection(con, "mediaItems")
        analyzed = self._collection(con, "mediaItemAnalyzedData")
        artists = {k: v.get("name") for k, v in self._collection(con, "mediaArtists").items()}
        genres = {k: v.get("name") for k, v in self._collection(con, "mediaGenres").items()}
        manual_bpm = self._manual_bpms(con)

        tracks = {}
        for uid in set(items) | set(analyzed):
            tracks[uid] = self._make_track(uid, items.get(uid), analyzed.get(uid),
                                           artists, genres, manual_bpm.get(uid))
        self.tracks = tracks
        self.locations = {}
        self._path_cache = {}
        for uid, loc in self._collection(con, "localMediaItemLocations").items():
            self.locations[uid] = {
                "uris": [str(u) for u in (loc.get("sourceURIs") or [])],
                "bookmark": loc.get("urlBookmarkData") if isinstance(loc.get("urlBookmarkData"), bytes) else None,
            }

        playlist_items = self._collection(con, "mediaItemPlaylistItems")
        raw = self._collection(con, "mediaItemPlaylists")
        playlists = {}
        for uid, p in raw.items():
            entries = []
            for item_uuid in p.get("itemUUIDs") or []:
                pi = playlist_items.get(item_uuid)
                if pi and pi.get("mediaItemUUID") in tracks:
                    entries.append(pi["mediaItemUUID"])
            playlists[uid] = {
                "id": uid,
                "name": p.get("name") or "Untitled",
                "type": p.get("type", TYPE_PLAYLIST),
                "parent": p.get("parentUUID"),
                "children": list(p.get("childUUIDs") or []),
                "tracks": entries,
            }
        playlists["djay:all"] = {"id": "djay:all", "name": "djay", "label": "pl.djayAll",
                                 "type": TYPE_PLAYLIST, "parent": "virtual", "children": [],
                                 "tracks": [t for t in items if t in tracks]}
        self.playlists = playlists
        self._merge_apple_music()
        self._merge_local_files()

    def _manual_bpms(self, con):
        out = {}
        try:
            rows = con.execute(
                "SELECT d.key, u.manualBPM FROM secondaryIndex_mediaItemUserDataIndex u "
                "JOIN database2 d ON d.rowid = u.rowid WHERE u.manualBPM > 0")
            for key, bpm in rows:
                out[key] = bpm
        except sqlite3.Error:
            pass
        return out

    def _make_track(self, uid, item, analyzed, artists, genres, manual_bpm):
        item = item or {}
        analyzed = analyzed or {}
        tid = item.get("titleID") or {}
        if not tid:
            tids = analyzed.get("titleIDs") or []
            tid = tids[0] if tids and isinstance(tids[0], dict) else {}
        title = item.get("title") or tid.get("title") or ""
        djay_title = title
        artist = item.get("artist") or tid.get("artist")
        if not artist and item.get("artistUUIDs"):
            names = [artists.get(a) for a in item["artistUUIDs"] if artists.get(a)]
            artist = ", ".join(names)
        if not artist:
            m = _SPLIT_TITLE.match(title)
            if m:
                artist, title = m.group(1), m.group(2)
        bpm = manual_bpm or analyzed.get("manualBPM") or analyzed.get("bpm") or item.get("bpm")
        if not bpm:
            bpm = bpm_from_text(item.get("title") or tid.get("title"), item.get("comments"))
        key = camelot.from_djay_index(analyzed.get("keySignatureIndex"))
        if key is None:
            key = camelot.from_djay_index(item.get("musicalKeySignatureIndex"))
        key_source = "djay"
        comment_key = camelot.parse(item.get("comments"))
        if comment_key and (self.key_from_comments or key is None):
            key, key_source = comment_key, "commenti"
        genre = ", ".join(genres.get(g, "") for g in item.get("genreUUIDs") or [] if genres.get(g))
        t = Track(uid, title, artist, float(bpm) if bpm else None, key,
                  item.get("duration") or tid.get("duration"),
                  item.get("comments"), genre, key_source)
        t.djay_title = djay_title
        t.djay_artist = item.get("artist") or tid.get("artist") or ""
        return t

    # -- playlists ---------------------------------------------------------
    # -- Apple Music (the "Music" source in djay) ------------------------------
    def set_apple_music(self, data):
        self.apple_music = data
        self.refresh(force=True)

    def _merge_apple_music(self):
        am = self.apple_music
        if not am:
            return
        from .music_library import key_bpm_from_text
        pid_map = {}
        for uid, loc in self.locations.items():
            for u in loc["uris"]:
                if u.startswith("com.apple.iTunes:"):
                    try:
                        pid_map[int(u.split(":", 1)[1])] = uid
                    except ValueError:
                        pass
        by_name = {}
        for uid, t in self.tracks.items():
            by_name.setdefault((_norm_text(t.djay_title), _norm_text(t.djay_artist or t.artist)), uid)

        def fill(t, d):
            if not t.key or not t.bpm:
                k, b = key_bpm_from_text(d["comments"], d["title"],
                                         os.path.basename(d["path"] or ""))
                t.key = t.key or k
                t.bpm = t.bpm or d["bpm"] or b or bpm_from_text(d["title"])

        def add_file(uid, d):
            if d["path"] and not any(u.startswith("file:") for u in self.locations.get(uid, {}).get("uris", [])):
                loc = self.locations.setdefault(uid, {"uris": [], "bookmark": None})
                loc["uris"].append("file://" + quote(d["path"]))

        ids = {}
        for pid, d in am["tracks"].items():
            uid = pid_map.get(pid)
            if uid not in self.tracks:
                uid = by_name.get((_norm_text(d["title"]), _norm_text(d["artist"])))
            if uid in self.tracks:
                fill(self.tracks[uid], d)
                add_file(uid, d)
                ids[pid] = uid
                continue
            tid = "am:%d" % pid
            key, bpm = key_bpm_from_text(d["comments"], d["title"], os.path.basename(d["path"] or ""))
            bpm = d["bpm"] or bpm or bpm_from_text(d["title"], d["comments"])
            t = Track(tid, d["title"], d["artist"], bpm, key, d["duration"], d["comments"],
                      d["genre"], "music")
            t.djay_title, t.djay_artist = d["title"], d["artist"]
            self.tracks[tid] = t
            add_file(tid, d)
            ids[pid] = tid

        root = "am:root"
        self.playlists[root] = {"id": root, "name": "Apple Music (Musica)", "type": TYPE_FOLDER,
                                "parent": "am", "children": [], "tracks": []}
        all_ids = list(dict.fromkeys(ids.values()))
        self.playlists["am:all"] = {"id": "am:all", "name": "Musica", "label": "pl.musicAll",
                                    "type": TYPE_PLAYLIST, "parent": root, "children": [],
                                    "tracks": all_ids}
        self.playlists[root]["children"].append("am:all")
        for pl in am["playlists"]:
            pid = "am:pl:%d" % pl["pid"]
            parent = "am:pl:%d" % pl["parent"] if pl["parent"] else root
            self.playlists[pid] = {"id": pid, "name": pl["name"] or "Playlist",
                                   "type": TYPE_FOLDER if pl["folder"] else TYPE_PLAYLIST,
                                   "parent": parent, "children": [],
                                   "tracks": [ids[i] for i in pl["items"] if i in ids]}
        for pid, p in list(self.playlists.items()):
            if pid.startswith("am:pl:"):
                par = self.playlists.get(p["parent"]) or self.playlists[root]
                par["children"].append(pid)

    # -- folders on the Mac (Finder / USB) ---------------------------------------
    def set_local_files(self, data):
        self.local_files = data
        self.refresh(force=True)

    def _merge_local_files(self):
        data = self.local_files
        if not data:
            return
        import hashlib
        by_path = {}
        for uid, loc in self.locations.items():
            for u in loc["uris"]:
                if u.startswith("file:") and "/.file/id=" not in u:
                    by_path[unquote(urlparse(u).path)] = uid
        by_name = {}
        for uid, t in self.tracks.items():
            by_name.setdefault((_norm_text(t.djay_title), _norm_text(t.djay_artist or t.artist)), uid)

        ids = {}
        for path, m in data["files"].items():
            uid = by_path.get(path)
            if uid not in self.tracks:
                uid = by_name.get((_norm_text(m["title"]), _norm_text(m["artist"])))
            if uid in self.tracks:
                t = self.tracks[uid]
                t.key = t.key or m.get("key")
                t.bpm = t.bpm or m.get("bpm")
                if not any(u.startswith("file:") for u in self.locations.get(uid, {}).get("uris", [])):
                    self.locations.setdefault(uid, {"uris": [], "bookmark": None})["uris"].append(
                        "file://" + quote(path))
                ids[path] = uid
                continue
            tid = "f:" + hashlib.md5(path.encode("utf-8")).hexdigest()[:20]
            t = Track(tid, m["title"], m["artist"], m.get("bpm"), m.get("key"), m.get("duration"),
                      m.get("comments"), "", "file")
            t.djay_title, t.djay_artist = m["title"], m["artist"]
            self.tracks[tid] = t
            self.locations[tid] = {"uris": ["file://" + quote(path)], "bookmark": None}
            ids[path] = tid

        def add(node, parent):
            pid = node["id"]
            self.playlists[pid] = {
                "id": pid, "name": node["name"], "parent": parent,
                "type": TYPE_FOLDER if node["children"] else TYPE_PLAYLIST,
                "children": [c["id"] for c in node["children"]],
                "tracks": [ids[f] for f in node["files"] if f in ids],
            }
            for c in node["children"]:
                add(c, pid)

        for root in data["folders"]:
            add(root, "fs")
        self._fs_roots = [r["id"] for r in data["folders"]]

    def tree(self):
        """Folders and playlists for the dropdown, grouped by source:
        'djay' (djay's own library) and 'music' (Apple's Music app)."""
        def node(uid, depth, group):
            p = self.playlists.get(uid)
            if not p:
                return []
            out = [{"id": uid, "name": p["name"], "label": p.get("label"), "group": group,
                    "type": "folder" if p["type"] == TYPE_FOLDER else "playlist",
                    "depth": depth, "count": len(self.tracks_in(uid))}]
            for c in p["children"]:
                out.extend(node(c, depth + 1, group))
            return out

        result = []
        if "djay:all" in self.playlists:
            result.extend(node("djay:all", 0, "djay"))
        djay = {k: p for k, p in self.playlists.items() if not k.startswith(("am:", "djay:", "fs:"))}
        roots = [p for p in djay.values()
                 if p["parent"] in (None, ROOT_UUID) or p["parent"] not in djay]
        seen = set()
        # the invisible root folder ("Playlist" with no parent) holds the top level
        for r in roots:
            if r["parent"] is None and r["type"] == TYPE_FOLDER and r["children"]:
                for c in r["children"]:
                    if c not in seen:
                        seen.add(c)
                        result.extend(node(c, 0, "djay"))
        for r in sorted(roots, key=lambda p: p["name"].lower()):
            if r["id"] in seen or (r["parent"] is None and r["type"] == TYPE_FOLDER):
                continue
            seen.add(r["id"])
            result.extend(node(r["id"], 0, "djay"))
        root = self.playlists.get("am:root")
        if root:
            for c in root["children"]:
                result.extend(node(c, 0, "music"))
        for r in getattr(self, "_fs_roots", []) if self.local_files else []:
            result.extend(node(r, 0, "files"))
        return result

    def tracks_in(self, uid, _seen=None):
        """All track ids in a playlist or (recursively) a folder."""
        _seen = _seen or set()
        if uid in _seen:
            return []
        _seen.add(uid)
        p = self.playlists.get(uid)
        if not p:
            return []
        ids = list(p["tracks"])
        for c in p["children"]:
            ids.extend(self.tracks_in(c, _seen))
        out, dup = [], set()
        for i in ids:
            if i not in dup:
                dup.add(i)
                out.append(i)
        return out

    # -- history / now playing ----------------------------------------------
    def history(self, since_unix=None, limit=200):
        """Recent history items, newest last: dicts with track_id, deck, time."""
        con = self._connect()
        try:
            cache = self._history_cache
            keys = [k for (k,) in con.execute(
                "SELECT key FROM database2 WHERE collection = 'historySessionItems'")]
            for k in keys:
                if k not in cache:
                    row = con.execute("SELECT data FROM database2 WHERE collection = "
                                      "'historySessionItems' AND key = ?", (k,)).fetchone()
                    try:
                        cache[k] = tsaf.decode(row[0]) if row else None
                    except Exception:
                        cache[k] = None
        finally:
            con.close()
        out = []
        for it in (cache.get(k) for k in keys):
            if not isinstance(it, dict):
                continue
            tid = it.get("titleID") or {}
            t = apple_time_to_unix(it.get("startTime"))
            if t is None or (since_unix and t < since_unix):
                continue
            out.append({
                "track_id": tid.get("uuid"),
                "title": tid.get("title"),
                "artist": tid.get("artist"),
                "deck": it.get("deckNumber"),
                "session": it.get("sessionUUID"),
                "time": t,
            })
        out.sort(key=lambda x: x["time"])
        return out[-limit:]

    def history_sessions(self):
        con = self._connect()
        try:
            sessions = self._collection(con, "historySessions")
            items = self._collection(con, "historySessionItems")
        finally:
            con.close()
        out = []
        for uid, s in sessions.items():
            seq = []
            for iu in s.get("itemUUIDs") or []:
                it = items.get(iu)
                if it:
                    seq.append(((it.get("titleID") or {}).get("uuid"),
                                apple_time_to_unix(it.get("startTime")) or 0))
            seq.sort(key=lambda x: x[1])
            out.append({"id": uid, "start": apple_time_to_unix(s.get("startDate")),
                        "tracks": [t for t, _ in seq if t],
                        "times": [w for t, w in seq if t]})
        out.sort(key=lambda s: s["start"] or 0)
        return out

    def now_playing(self, max_age_hours=12):
        h = self.history(since_unix=time.time() - max_age_hours * 3600, limit=50)
        return h[-1] if h else None

    def has_file(self, track_id):
        loc = self.locations.get(track_id)
        return bool(loc and (loc["bookmark"] or any(u.startswith("file:") for u in loc["uris"])))

    def file_path(self, track_id):
        """Local path of the track's audio file, or None (streaming / unknown).
        Plain file:// URLs are decoded directly; on macOS, file-reference URLs
        (file:///.file/id=...) and djay's bookmarks are resolved with Foundation."""
        if track_id in self._path_cache:
            cached = self._path_cache[track_id]
            if cached is None or os.path.exists(cached):
                return cached
        path = self._file_path(track_id)
        self._path_cache[track_id] = path
        return path

    def _file_path(self, track_id):
        loc = self.locations.get(track_id)
        if not loc:
            return None
        plain = [u for u in loc["uris"] if u.startswith("file:") and "/.file/id=" not in u]
        for u in plain:
            path = unquote(urlparse(u).path)
            if os.path.exists(path):
                return path
        resolved = _resolve_macos(loc)
        if resolved:
            return resolved
        if plain:  # e.g. external drive not mounted: still return the path
            return unquote(urlparse(plain[0]).path)
        return None

    # -- NowPlaying.txt (written by djay for the track on air) ----------------
    def now_playing_path(self):
        return os.path.join(os.path.dirname(self.path), "NowPlaying.txt")

    def read_now_playing(self):
        """Return (mtime, {'title','artist','album','time'}) or (None, None)."""
        p = self.now_playing_path()
        try:
            mtime = os.path.getmtime(p)
            with open(p, encoding="utf-8", errors="replace") as f:
                text = f.read()
        except OSError:
            return None, None
        info = {}
        for line in text.splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                info[k.strip().lower()] = v.strip()
        return mtime, info

    def match_now_playing(self, info, prefer=()):
        """Find the library track for NowPlaying.txt's title/artist."""
        if not info or not info.get("title"):
            return None
        want_t = _norm_text(info.get("title"))
        want_a = _norm_text(info.get("artist"))
        want_len = _duration(info.get("time"))
        best, best_score = None, -1
        for tid, t in self.tracks.items():
            if _norm_text(t.djay_title) != want_t and _norm_text(t.title) != want_t:
                continue
            score = 1
            a = _norm_text(t.djay_artist or t.artist)
            if want_a and a and (a == want_a or a in want_a or want_a in a):
                score += 4
            if want_len and t.duration and abs(t.duration - want_len) <= 2:
                score += 2
            if tid in prefer:
                score += 3
            if self.has_file(tid):
                score += 1
            if score > best_score:
                best, best_score = tid, score
        return best

    def get(self, track_id):
        return self.tracks.get(track_id)
