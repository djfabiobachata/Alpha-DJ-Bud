"""Read-only access to the rekordbox 6 / 7 library (macOS).

rekordbox keeps its library in ~/Library/Pioneer/rekordbox/master.db, an SQLite
database encrypted with SQLCipher (the same published key on every computer).
Tables used:
  djmdContent      tracks (FolderPath, Title, BPM x 100, KeyID, ArtistID...)
  djmdArtist / djmdGenre / djmdKey   names
  djmdPlaylist / djmdSongPlaylist     playlists and folders
  djmdHistory / djmdSongHistory       the history: rekordbox adds the track
                                       on air while you play
Opening it needs SQLCipher: Bud installs it on first use (sqlcipher3-wheels,
or pyrekordbox as second choice). If that isn't possible, export the
collection as XML from rekordbox (File > Export Collection in xml format) and
pick that file in Bud's settings: playlists work, the track on air doesn't.
"""
import datetime
import os
import sqlite3
import sys
import xml.etree.ElementTree as ET
from urllib.parse import unquote, urlparse

from . import camelot
from .library_base import BaseLibrary, file_mtime, to_float

DB = "~/Library/Pioneer/rekordbox/master.db"
# published SQLCipher key of rekordbox 6/7 master.db (the same for everyone)
DB_KEY = "402fd482c38817c35ffa8ffb8c7d93143b749e7d315df7a81732a1ff43608497"

ATTR_PLAYLIST, ATTR_FOLDER, ATTR_SMART = 0, 1, 4


def find_database(explicit=None):
    p = os.path.expanduser(explicit or DB)
    if os.path.isdir(p):
        p = os.path.join(p, "master.db")
    return p if os.path.isfile(p) else None


class RekordboxError(Exception):
    pass


_pip_tried = set()


def _pip(package):
    if package in _pip_tried:
        return False
    _pip_tried.add(package)
    import subprocess
    r = subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", package],
                       capture_output=True, timeout=900)
    import importlib
    importlib.invalidate_caches()
    return r.returncode == 0


def _check(con):
    con.execute("SELECT count(*) FROM sqlite_master").fetchone()
    con.execute("SELECT count(*) FROM djmdContent").fetchone()
    return con


def open_master_db(path):
    """DB-API connection to master.db (read-only). Plain SQLite first (tests,
    unencrypted copies), then SQLCipher with the published key, then pyrekordbox."""
    errors = []
    try:
        uri = "file:%s?mode=ro" % path.replace("?", "%3f").replace("#", "%23")
        return _check(sqlite3.connect(uri, uri=True, timeout=2, check_same_thread=False))
    except sqlite3.Error as e:
        errors.append("sqlite: %s" % e)
    for attempt in range(2):
        try:
            import sqlcipher3
        except ImportError:
            if attempt == 0 and _pip("sqlcipher3-wheels"):
                continue
            errors.append("sqlcipher3 not available")
            break
        try:
            con = sqlcipher3.connect("file:%s?mode=ro" % path, uri=True, check_same_thread=False)
            con.execute("PRAGMA key = '%s'" % DB_KEY)
            return _check(con)
        except Exception as e:
            errors.append("sqlcipher: %s" % e)
        break
    for attempt in range(2):
        try:
            from pyrekordbox import Rekordbox6Database
        except ImportError:
            if attempt == 0 and _pip("pyrekordbox"):
                continue
            errors.append("pyrekordbox not available")
            break
        try:
            db = Rekordbox6Database(path=path)
            return _check(db.engine.raw_connection())
        except Exception as e:
            errors.append("pyrekordbox: %s" % e)
        break
    raise RekordboxError("; ".join(errors))


def _unix(text):
    """'2024-05-01 22:13:05.123 +00:00' -> unix time."""
    if not text:
        return None
    s = str(text).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S.%f %z", "%Y-%m-%d %H:%M:%S %z", "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            d = datetime.datetime.strptime(s, fmt)
            if d.tzinfo is None:
                d = d.replace(tzinfo=datetime.timezone.utc)
            return d.timestamp()
        except ValueError:
            continue
    return None


class RekordboxLibrary(BaseLibrary):
    SOFTWARE = "rekordbox"
    ALL_ID = "rekordbox:all"

    def __init__(self, path, key_from_comments=False):
        super().__init__(path, key_from_comments)   # path = master.db
        self._con = None
        self._ids = {}          # rekordbox content ID -> track id
        self._order = []

    def source_mtime(self):
        return file_mtime(self.path, self.path + "-wal")

    def close(self):
        if self._con is not None:
            try:
                self._con.close()
            except Exception:
                pass
            self._con = None

    def _query(self, sql, args=()):
        for attempt in range(2):
            if self._con is None:
                self._con = open_master_db(self.path)
            try:
                cur = self._con.cursor()
                cur.execute(sql, args)
                return cur.fetchall()
            except Exception:
                self.close()
                if attempt:
                    raise
        return []

    def _cols(self, table):
        return {r[1] for r in self._query("PRAGMA table_info(%s)" % table)}

    def _alive(self, table, alias=""):
        return " AND %srb_local_deleted = 0" % alias if "rb_local_deleted" in self._cols(table) else ""

    def _read(self):
        names = {}
        for table in ("djmdArtist", "djmdGenre", "djmdKey"):
            col = "ScaleName" if table == "djmdKey" else "Name"
            names[table] = {str(i): n for i, n in self._query("SELECT ID, %s FROM %s" % (col, table))}
        rows = self._query(
            "SELECT ID, FolderPath, Title, ArtistID, GenreID, KeyID, BPM, Length, Commnt "
            "FROM djmdContent WHERE 1=1" + self._alive("djmdContent"))
        self._ids = {}
        for cid, path, title, aid, gid, kid, bpm, length, cmt in rows:
            if not path:
                continue
            bpm = to_float(bpm)
            if bpm and bpm > 1000:
                bpm = bpm / 100.0           # stored as BPM x 100
            key = camelot.parse(names["djmdKey"].get(str(kid)))
            tid = self.add_file_track(path, title or "", names["djmdArtist"].get(str(aid), ""),
                                      bpm, key, to_float(length), cmt,
                                      names["djmdGenre"].get(str(gid), ""))
            self._ids[str(cid)] = tid
        lists = self._query("SELECT ID, Name, Attribute, ParentID, Seq FROM djmdPlaylist WHERE 1=1"
                            + self._alive("djmdPlaylist") + " ORDER BY Seq")
        items = {}
        for pl, cid, _no in self._query(
                "SELECT PlaylistID, ContentID, TrackNo FROM djmdSongPlaylist WHERE 1=1"
                + self._alive("djmdSongPlaylist") + " ORDER BY PlaylistID, TrackNo"):
            t = self._ids.get(str(cid))
            if t:
                items.setdefault(str(pl), []).append(t)
        known = {str(r[0]) for r in lists}
        self._order = []
        pending = list(lists)
        for _ in range(12):                     # parents before children
            later = []
            for pid, name, attr, parent, _seq in pending:
                parent = str(parent) if parent is not None else "root"
                if attr == ATTR_SMART:
                    continue
                own = "rekordbox:%s" % pid
                par = "rekordbox:%s" % parent if parent in known else None
                if par and par not in self.playlists:
                    later.append((pid, name, attr, parent, _seq))
                    continue
                self.add_playlist(own, name, par, items.get(str(pid), ()), folder=attr == ATTR_FOLDER)
                if par is None:
                    self._order.append(own)
            if not later:
                break
            pending = later

    def own_roots(self):
        return [p for p in self._order if p in self.playlists]

    # -- history / now playing ----------------------------------------------------
    def _history_rows(self, where="", args=(), limit=None):
        sql = ("SELECT s.HistoryID, s.ContentID, s.created_at FROM djmdSongHistory s WHERE 1=1"
               + self._alive("djmdSongHistory", "s.") + where
               + " ORDER BY s.created_at, s.TrackNo")
        rows = self._query(sql, args)
        return rows[-limit:] if limit else rows

    def read_now_playing(self):
        try:
            rows = self._history_rows(limit=1)
        except Exception:
            return None, None
        if not rows:
            return None, None
        hid, cid, created = rows[-1]
        tid = self._ids.get(str(cid))
        t = self.tracks.get(tid)
        when = _unix(created) or self.source_mtime()
        return when, {"track_id": tid, "title": t.title if t else None,
                      "artist": t.artist if t else None}

    def history(self, since_unix=None, limit=200):
        out = []
        for hid, cid, created in self._history_rows(limit=limit):
            tid = self._ids.get(str(cid))
            t = _unix(created)
            if tid and t and not (since_unix and t < since_unix):
                out.append({"track_id": tid, "title": None, "artist": None, "deck": None,
                            "session": str(hid), "time": t})
        return out

    def history_sessions(self):
        sessions = {}
        for hid, cid, created in self._history_rows():
            tid = self._ids.get(str(cid))
            if tid:
                s = sessions.setdefault(str(hid), {"id": str(hid), "start": None, "tracks": [], "times": []})
                s["tracks"].append(tid)
                s["times"].append(_unix(created) or 0)
        for s in sessions.values():
            s["start"] = s["times"][0] if s["times"] else None
        return sorted(sessions.values(), key=lambda s: s["start"] or 0)


class RekordboxXmlLibrary(BaseLibrary):
    """rekordbox collection exported as XML (File > Export Collection in xml format)."""
    SOFTWARE = "rekordbox"
    ALL_ID = "rekordbox:all"

    def __init__(self, path, key_from_comments=False):
        super().__init__(path, key_from_comments)
        self._order = []

    def _read(self):
        root = ET.parse(self.path).getroot()
        ids = {}
        coll = root.find("COLLECTION")
        for t in (coll.findall("TRACK") if coll is not None else []):
            loc = t.get("Location") or ""
            if not loc.startswith("file:"):
                continue
            path = unquote(urlparse(loc).path)
            ids[t.get("TrackID")] = self.add_file_track(
                path, t.get("Name") or "", t.get("Artist") or "", to_float(t.get("AverageBpm")),
                camelot.parse(t.get("Tonality")), to_float(t.get("TotalTime")),
                t.get("Comments"), t.get("Genre"))
        self._order = []
        pls = root.find("PLAYLISTS")
        top = pls.find("NODE") if pls is not None else None   # ROOT folder
        if top is not None:
            self._node(top, None, ids, "rekordbox:")

    def _node(self, node, parent, ids, prefix):
        for child in node.findall("NODE"):
            name = child.get("Name") or "Playlist"
            pid = prefix + name
            if child.get("Type") == "0":
                self.add_playlist(pid, name, parent, folder=True)
                self._node(child, pid, ids, pid + "/")
            else:
                tracks = [ids.get(t.get("Key")) for t in child.findall("TRACK")]
                self.add_playlist(pid, name, parent, [t for t in tracks if t])
            if parent is None:
                self._order.append(pid)

    def own_roots(self):
        return [p for p in self._order if p in self.playlists]


def open_library(path, key_from_comments=False):
    if path.lower().endswith(".xml"):
        return RekordboxXmlLibrary(path, key_from_comments)
    return RekordboxLibrary(path, key_from_comments)

