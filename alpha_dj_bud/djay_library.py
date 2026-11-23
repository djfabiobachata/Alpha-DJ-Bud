"""Read-only access to the djay Pro (macOS) media library.

djay keeps its library in a YapDatabase SQLite file
(~/Music/djay/djay Media Library.djayMediaLibrary/MediaLibrary.db) whose rows
are serialized with the proprietary TSAF format. The database runs in WAL mode,
so it can be read safely while djay is open. Alpha DJ Bud never writes to it.
"""
import datetime
import glob
import os
import sqlite3

from . import camelot, tsaf
from .library_base import (TYPE_FOLDER, TYPE_PLAYLIST, BaseLibrary, Track,  # noqa: F401
                           _duration, _norm_text, _resolve_macos, bpm_from_text, _SPLIT_TITLE)

DEFAULT_DB_CANDIDATES = [
    "~/Music/djay/djay Media Library.djayMediaLibrary/MediaLibrary.db",
    "~/Library/Containers/com.algoriddim.djay-iphone-free/Data/Music/djay/"
    "djay Media Library.djayMediaLibrary/MediaLibrary.db",
    "~/Library/Containers/*algoriddim*/Data/Music/djay/"
    "djay Media Library.djayMediaLibrary/MediaLibrary.db",
]

APPLE_EPOCH = datetime.datetime(2001, 1, 1, tzinfo=datetime.timezone.utc)
ROOT_UUID = "mediaItemPlaylist-root"


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


class DjayLibrary(BaseLibrary):
    """Snapshot of the djay library. Call `refresh()` to reload when the file
    changes."""
    SOFTWARE = "djay"
    ALL_ID = "djay:all"
    ALL_LABEL = "pl.djayAll"

    def __init__(self, path, key_from_comments=False):
        super().__init__(path, key_from_comments)
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

    def source_mtime(self):
        return _db_mtime(self.path)

    def _read(self):
        con = self._connect()
        try:
            self._load(con)
        finally:
            con.close()

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
        self.tracks.update(tracks)
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
        self.playlists.update(playlists)

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

    # -- Apple Music (the "Music" source in djay) ------------------------------
    def own_roots(self):
        djay = {k: p for k, p in self.playlists.items() if self._is_own(k)}
        roots = [p for p in djay.values()
                 if p["parent"] in (None, ROOT_UUID) or p["parent"] not in djay]
        out, seen = [], set()
        # the invisible root folder ("Playlist" with no parent) holds the top level
        for r in roots:
            if r["parent"] is None and r["type"] == TYPE_FOLDER and r["children"]:
                for c in r["children"]:
                    if c not in seen:
                        seen.add(c)
                        out.append(c)
        for r in sorted(roots, key=lambda p: p["name"].lower()):
            if r["id"] in seen or (r["parent"] is None and r["type"] == TYPE_FOLDER):
                continue
            seen.add(r["id"])
            out.append(r["id"])
        return out

    def apple_music_ids(self):
        pid_map = {}
        for uid, loc in self.locations.items():
            for u in loc["uris"]:
                if u.startswith("com.apple.iTunes:"):
                    try:
                        pid_map[int(u.split(":", 1)[1])] = uid
                    except ValueError:
                        pass
        return pid_map

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
