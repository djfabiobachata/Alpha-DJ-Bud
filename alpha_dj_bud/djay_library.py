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
import time

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


class Track:
    __slots__ = ("id", "title", "artist", "bpm", "key", "duration",
                 "comments", "genre", "key_source")

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
        self.playlists = playlists

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
        return Track(uid, title, artist, float(bpm) if bpm else None, key,
                     item.get("duration") or tid.get("duration"),
                     item.get("comments"), genre, key_source)

    # -- playlists ---------------------------------------------------------
    def tree(self):
        """Folders and playlists as a nested list (for the dropdown)."""
        def node(uid, depth):
            p = self.playlists.get(uid)
            if not p:
                return []
            out = [{"id": uid, "name": p["name"], "type": "folder" if p["type"] == TYPE_FOLDER else "playlist",
                    "depth": depth, "count": len(self.tracks_in(uid))}]
            for c in p["children"]:
                out.extend(node(c, depth + 1))
            return out

        roots = [p for p in self.playlists.values()
                 if p["parent"] in (None, ROOT_UUID) or p["parent"] not in self.playlists]
        # the invisible root folder ("Playlist" with no parent) holds the top level
        result = []
        seen = set()
        for r in roots:
            if r["parent"] is None and r["type"] == TYPE_FOLDER and r["children"]:
                for c in r["children"]:
                    if c not in seen:
                        seen.add(c)
                        result.extend(node(c, 0))
        for r in sorted(roots, key=lambda p: p["name"].lower()):
            if r["id"] in seen or (r["parent"] is None and r["type"] == TYPE_FOLDER):
                continue
            seen.add(r["id"])
            result.extend(node(r["id"], 0))
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
                        "tracks": [t for t, _ in seq if t]})
        out.sort(key=lambda s: s["start"] or 0)
        return out

    def now_playing(self, max_age_hours=12):
        h = self.history(since_unix=time.time() - max_age_hours * 3600, limit=50)
        return h[-1] if h else None

    def get(self, track_id):
        return self.tracks.get(track_id)
