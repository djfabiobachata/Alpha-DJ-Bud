"""What every DJ software library has in common.

A reader for one DJ software (djay, VirtualDJ, Serato, Traktor, rekordbox)
subclasses `BaseLibrary` and fills `self.tracks`, `self.locations` and its own
`self.playlists` in `_read()`. The base adds the virtual "all tracks" entry,
the Apple Music library and the folders on the Mac, the dropdown tree, file
paths for dragging and now-playing matching. Read-only: Alpha DJ Bud never
writes to a DJ software's files.
"""
import hashlib
import os
import re
import sys
import unicodedata
from urllib.parse import quote, unquote, urlparse

from . import camelot

TYPE_FOLDER = 0
TYPE_PLAYLIST = 1


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
        # title / artist exactly as the DJ software shows them (the names are
        # historical: they're used for every software, not only djay)
        self.djay_title = self.title
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


# -- small helpers shared by the readers --------------------------------------
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


def to_float(v):
    try:
        f = float(str(v).replace(",", "."))
    except (TypeError, ValueError):
        return None
    return f if f > 0 else None


def file_id(path):
    """Track id for a file on disk: the same for every software and for the
    folders on the Mac, so learning follows the file."""
    return "f:" + hashlib.md5(path.encode("utf-8")).hexdigest()[:20]


def _norm_text(s):
    s = unicodedata.normalize("NFKD", str(s or ""))
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def _norm_path(p):
    return unicodedata.normalize("NFC", p or "")


def _duration(text):
    if isinstance(text, (int, float)):
        return float(text)
    m = re.match(r"^\s*(?:(\d+):)?(\d+):(\d{2})(?:[.,]\d+)?\s*$", text or "")
    if not m:
        return to_float(text)
    h, mnt, sec = m.groups()
    return int(h or 0) * 3600 + int(mnt) * 60 + int(sec)


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


def file_mtime(*paths):
    m = 0
    for p in paths:
        try:
            m = max(m, os.path.getmtime(p))
        except OSError:
            pass
    return m


class BaseLibrary:
    SOFTWARE = "app"
    ALL_ID = "app:all"          # virtual entry with every track of the software
    ALL_LABEL = "pl.appAll"

    def __init__(self, path, key_from_comments=False):
        self.path = path
        self.key_from_comments = key_from_comments
        self.tracks = {}
        self.playlists = {}
        self.loaded_mtime = 0
        self.error = None
        self.locations = {}
        self._path_cache = {}
        self.apple_music = None   # data from music_library.load(), merged on each load
        self.local_files = None   # data from local_files.scan(), merged on each load
        self._fs_roots = []

    # -- to implement ----------------------------------------------------------
    def source_mtime(self):
        """Newest modification time of the software's library files."""
        return file_mtime(self.path)

    def _read(self):
        """Fill self.tracks, self.locations and the software's playlists."""
        raise NotImplementedError

    def own_roots(self):
        """Top-level playlists / folders of the software, in display order."""
        own = {k: p for k, p in self.playlists.items() if self._is_own(k)}
        return [k for k, p in own.items() if p["parent"] not in own]

    def history(self, since_unix=None, limit=200):
        """Recent tracks played, newest last: dicts with track_id, deck, time."""
        return []

    def history_sessions(self):
        """Past sets: [{'id', 'start', 'tracks': [ids], 'times': [unix]}]."""
        return []

    def read_now_playing(self):
        """(mtime, {'title', 'artist', 'path'?, 'track_id'?, 'deck'?}) or (None, None)."""
        return None, None

    def close(self):
        pass

    # -- helpers for the readers -------------------------------------------------
    def add_file_track(self, path, title, artist, bpm=None, key=None, duration=None,
                       comments=None, genre=None, key_source=None, shown_title=None,
                       shown_artist=None):
        """Add (or return) the track for an audio file; returns its id."""
        path = _norm_path(path)
        tid = file_id(path)
        if tid in self.tracks:
            return tid
        if not title:
            base = os.path.splitext(os.path.basename(path))[0]
            m = _SPLIT_TITLE.match(base)
            if m and not artist:
                artist, title = m.group(1), m.group(2)
            else:
                title = base
        cmt_key = camelot.parse(comments) if comments else None
        if cmt_key and (self.key_from_comments or key is None):
            key, key_source = cmt_key, "commenti"
        if not bpm:
            bpm = bpm_from_text(title, comments)
        t = Track(tid, title, artist, bpm, key, duration, comments, genre,
                  key_source or self.SOFTWARE)
        t.djay_title = shown_title if shown_title is not None else t.title
        t.djay_artist = shown_artist if shown_artist is not None else t.artist
        self.tracks[tid] = t
        self.locations[tid] = {"uris": ["file://" + quote(path)], "bookmark": None}
        return tid

    def add_playlist(self, pid, name, parent=None, tracks=(), folder=False):
        p = self.playlists.get(pid)
        if p is None:
            p = self.playlists[pid] = {"id": pid, "name": name or "Playlist", "parent": parent,
                                       "type": TYPE_FOLDER if folder else TYPE_PLAYLIST,
                                       "children": [], "tracks": []}
            par = self.playlists.get(parent) if parent else None
            if par is not None and pid not in par["children"]:
                par["children"].append(pid)
                par["type"] = TYPE_FOLDER
        p["tracks"].extend(t for t in tracks if t in self.tracks)
        if folder:
            p["type"] = TYPE_FOLDER
        return p

    def _is_own(self, pid):
        return not pid.startswith(("am:", "fs:")) and pid != self.ALL_ID

    # -- loading -------------------------------------------------------------------
    def needs_refresh(self):
        return self.source_mtime() > self.loaded_mtime

    def refresh(self, force=False):
        if not force and not self.needs_refresh():
            return False
        mtime = self.source_mtime()
        old = (self.tracks, self.playlists, self.locations)
        try:
            self.tracks, self.playlists, self.locations = {}, {}, {}
            self._path_cache = {}
            self._read()
            own = list(self.tracks)
            self.playlists[self.ALL_ID] = {"id": self.ALL_ID, "name": self.SOFTWARE,
                                           "label": self.ALL_LABEL, "type": TYPE_PLAYLIST,
                                           "parent": "virtual", "children": [], "tracks": own}
            self._merge_apple_music()
            self._merge_local_files()
            self.error = None
        except Exception as e:  # keep the previous snapshot
            self.tracks, self.playlists, self.locations = old
            self.error = "cannot read the library: %s" % e
            return False
        self.loaded_mtime = mtime
        return True

    # -- Apple Music --------------------------------------------------------------
    def apple_music_ids(self):
        """{Music app persistent id: own track id} known to the software."""
        return {}

    def set_apple_music(self, data):
        self.apple_music = data
        self.refresh(force=True)

    def _by_path(self):
        out = {}
        for uid, loc in self.locations.items():
            for u in loc["uris"]:
                if u.startswith("file:") and "/.file/id=" not in u:
                    out[_norm_path(unquote(urlparse(u).path))] = uid
        return out

    def _merge_apple_music(self):
        am = self.apple_music
        if not am:
            return
        from .music_library import key_bpm_from_text
        pid_map = self.apple_music_ids()
        by_path = self._by_path()
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
            if uid not in self.tracks and d.get("path"):
                uid = by_path.get(_norm_path(d["path"]))
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
        by_path = self._by_path()
        by_name = {}
        for uid, t in self.tracks.items():
            by_name.setdefault((_norm_text(t.djay_title), _norm_text(t.djay_artist or t.artist)), uid)

        ids = {}
        for path, m in data["files"].items():
            uid = by_path.get(_norm_path(path))
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
            tid = file_id(_norm_path(path))
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

    # -- dropdown ------------------------------------------------------------------
    def tree(self):
        """Folders and playlists for the dropdown, grouped by source: 'app' (the
        DJ software), 'music' (Apple's Music app) and 'files' (Mac folders)."""
        def node(uid, depth, group, seen):
            p = self.playlists.get(uid)
            if not p or uid in seen:
                return []
            seen.add(uid)
            out = [{"id": uid, "name": p["name"], "label": p.get("label"), "group": group,
                    "type": "folder" if p["type"] == TYPE_FOLDER else "playlist",
                    "depth": depth, "count": len(self.tracks_in(uid))}]
            for c in p["children"]:
                out.extend(node(c, depth + 1, group, seen))
            return out

        seen = set()
        result = []
        if self.ALL_ID in self.playlists:
            result.extend(node(self.ALL_ID, 0, "app", seen))
        for r in self.own_roots():
            result.extend(node(r, 0, "app", seen))
        root = self.playlists.get("am:root")
        if root:
            for c in root["children"]:
                result.extend(node(c, 0, "music", seen))
        for r in self._fs_roots if self.local_files else []:
            result.extend(node(r, 0, "files", seen))
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

    # -- audio files ---------------------------------------------------------------
    def has_file(self, track_id):
        loc = self.locations.get(track_id)
        return bool(loc and (loc["bookmark"] or any(u.startswith("file:") for u in loc["uris"])))

    def file_path(self, track_id):
        """Local path of the track's audio file, or None (streaming / unknown)."""
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

    # -- now playing ---------------------------------------------------------------
    def match_now_playing(self, info, prefer=()):
        """Find the library track for what the software says is on air."""
        if not info:
            return None
        if info.get("track_id") in self.tracks:
            return info["track_id"]
        if info.get("path"):
            tid = file_id(_norm_path(info["path"]))
            if tid in self.tracks:
                return tid
            tid = self._by_path().get(_norm_path(info["path"]))
            if tid:
                return tid
        if not info.get("title"):
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
