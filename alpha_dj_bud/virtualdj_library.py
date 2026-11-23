"""Read-only access to the VirtualDJ library (macOS).

VirtualDJ keeps its home folder in ~/Library/Application Support/VirtualDJ
(older versions: ~/Documents/VirtualDJ) with:
  database.xml          every track: tags, analysed BPM (seconds per beat) and key
  MyLists/*.vdjfolder   playlists (VirtualDJ 2024+), sub-folders become folders
  Playlists/*.m3u       playlists of older versions
  History/*.m3u         one file per day, written while you play: the last
                        entry is the track on air
External drives have their own /Volumes/<drive>/VirtualDJ/database.xml.
"""
import glob
import os
import re
import xml.etree.ElementTree as ET
from html import unescape
from urllib.parse import unquote, urlparse

from . import camelot
from .library_base import BaseLibrary, file_id, file_mtime, to_float, _norm_path

HOME_CANDIDATES = ["~/Library/Application Support/VirtualDJ", "~/Documents/VirtualDJ"]
AUDIO_EXT = (".mp3", ".m4a", ".aac", ".wav", ".aif", ".aiff", ".flac", ".ogg", ".alac", ".mp4")


def find_home(explicit=None):
    if explicit:
        p = os.path.expanduser(explicit)
        if os.path.isfile(p):
            p = os.path.dirname(p)
        return p if os.path.isfile(os.path.join(p, "database.xml")) else None
    found = [os.path.expanduser(c) for c in HOME_CANDIDATES]
    found = [p for p in found if os.path.isfile(os.path.join(p, "database.xml"))]
    if not found:
        return None
    return max(found, key=lambda p: file_mtime(os.path.join(p, "database.xml")))


def vdj_bpm(v):
    """VirtualDJ stores the beat length in seconds (0.4688 = 128 BPM)."""
    f = to_float(v)
    if not f:
        return None
    bpm = 60.0 / f if f < 10 else f
    return round(bpm, 2) if 40 <= bpm <= 300 else None


_EXTVDJ = re.compile(r"<(\w+)>(.*?)</\1>")


def parse_m3u(path):
    """Entries of a VirtualDJ .m3u: [{'path', 'title', 'artist', 'time'}]."""
    out, meta = [], {}
    base = os.path.dirname(path)
    try:
        with open(path, encoding="utf-8-sig", errors="replace") as f:
            lines = f.read().splitlines()
    except OSError:
        return out
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if line.startswith("#EXTVDJ:"):
            meta = {k: unescape(v) for k, v in _EXTVDJ.findall(line[8:])}
            continue
        if line.startswith("#"):
            continue
        p = line
        if p.startswith("file://"):
            p = unquote(urlparse(p).path)
        elif not os.path.isabs(p) and "://" not in p:
            p = os.path.normpath(os.path.join(base, p))
        out.append({"path": p, "title": meta.get("title"), "artist": meta.get("artist"),
                    "time": to_float(meta.get("lastplaytime"))})
        meta = {}
    return out


class VirtualDJLibrary(BaseLibrary):
    SOFTWARE = "virtualdj"
    ALL_ID = "virtualdj:all"

    def __init__(self, path, key_from_comments=False):
        super().__init__(path, key_from_comments)   # path = VirtualDJ home folder
        self._order = []

    def _databases(self):
        dbs = [os.path.join(self.path, "database.xml")]
        dbs += sorted(glob.glob("/Volumes/*/VirtualDJ/database.xml"))
        return [d for d in dbs if os.path.isfile(d)]

    def _list_files(self):
        files = []
        for sub, ext in (("MyLists", ".vdjfolder"), ("Playlists", ".m3u"), ("Playlists", ".m3u8")):
            root = os.path.join(self.path, sub)
            for dirpath, _dirs, names in os.walk(root):
                files += [os.path.join(dirpath, n) for n in names if n.lower().endswith(ext)]
        return files

    def source_mtime(self):
        return file_mtime(*(self._databases() + self._list_files()))

    # -- library ---------------------------------------------------------------
    def _read(self):
        for db in self._databases():
            self._read_database(db)
        self._order = []
        self._read_lists("MyLists", (".vdjfolder",))
        self._read_lists("Playlists", (".m3u", ".m3u8"))

    def _read_database(self, db):
        for _ev, el in ET.iterparse(db, events=("end",)):
            if el.tag != "Song":
                continue
            path = el.get("FilePath") or ""
            tags = el.find("Tags")
            tags = tags.attrib if tags is not None else {}
            scan = el.find("Scan")
            scan = scan.attrib if scan is not None else {}
            infos = el.find("Infos")
            infos = infos.attrib if infos is not None else {}
            cmt = el.findtext("Comment") or ""
            el.clear()
            if not path:
                continue
            title = tags.get("Title") or ""
            if tags.get("Remix"):
                title = "%s (%s)" % (title, tags["Remix"]) if title else tags["Remix"]
            bpm = vdj_bpm(scan.get("Bpm")) or vdj_bpm(tags.get("Bpm"))
            key = camelot.parse(tags.get("Key")) or camelot.parse(scan.get("Key"))
            duration = to_float(infos.get("SongLength"))
            if "://" in path:   # streaming (netsearch://...): no file to drag
                tid = "vdj:" + file_id(path)[2:]
                if tid not in self.tracks:
                    from .library_base import Track
                    t = Track(tid, title, tags.get("Author"), bpm, key, duration, cmt,
                              tags.get("Genre"), "virtualdj")
                    self.tracks[tid] = t
                continue
            self.add_file_track(path, title, tags.get("Author") or "", bpm, key, duration,
                                cmt, tags.get("Genre"))

    def _track_for(self, entry):
        p = entry["path"]
        if "://" in p:
            tid = "vdj:" + file_id(p)[2:]
            return tid if tid in self.tracks else None
        tid = file_id(_norm_path(p))
        if tid in self.tracks:
            return tid
        if os.path.exists(p):   # in a list but not in database.xml yet
            return self.add_file_track(p, entry.get("title"), entry.get("artist") or "")
        return None

    def _read_lists(self, sub, exts):
        root = os.path.join(self.path, sub)
        if not os.path.isdir(root):
            return
        for dirpath, dirs, names in os.walk(root):
            dirs.sort(key=str.lower)
            rel = os.path.relpath(dirpath, root)
            parent = None if rel == "." else "vdj:%s:%s" % (sub, rel)
            if parent:
                gp = os.path.dirname(rel)
                self.add_playlist(parent, os.path.basename(rel),
                                  "vdj:%s:%s" % (sub, gp) if gp else None, folder=True)
                if not gp:
                    self._order.append(parent)
            for n in sorted(names, key=str.lower):
                if not n.lower().endswith(exts):
                    continue
                full = os.path.join(dirpath, n)
                entries = self._read_vdjfolder(full) if n.lower().endswith(".vdjfolder") else parse_m3u(full)
                if entries is None:     # filter folder, not a list of songs
                    continue
                ids = [t for t in (self._track_for(e) for e in entries) if t]
                pid = "vdj:%s:%s" % (sub, os.path.relpath(full, root))
                self.add_playlist(pid, os.path.splitext(n)[0], parent, ids)
                if not parent:
                    self._order.append(pid)

    @staticmethod
    def _read_vdjfolder(path):
        try:
            root = ET.parse(path).getroot()
        except (ET.ParseError, OSError):
            return None
        songs = root.findall(".//song")
        if not songs and (root.get("filter") or root.get("Filter")):
            return None
        return [{"path": s.get("path") or "", "title": s.get("title"), "artist": s.get("artist")}
                for s in songs if s.get("path")]

    def own_roots(self):
        return [p for p in self._order if p in self.playlists]

    # -- history / now playing ----------------------------------------------------
    def _history_files(self):
        h = os.path.join(self.path, "History")
        files = glob.glob(os.path.join(h, "*.m3u")) + glob.glob(os.path.join(h, "*", "*", "*.m3u"))
        return sorted(files, key=lambda f: file_mtime(f))

    def read_now_playing(self):
        files = glob.glob(os.path.join(self.path, "History", "*.m3u"))
        if not files:
            return None, None
        newest = max(files, key=file_mtime)
        entries = parse_m3u(newest)
        if not entries:
            return None, None
        last = entries[-1]
        return file_mtime(newest), {"title": last["title"], "artist": last["artist"],
                                    "path": last["path"]}

    def history(self, since_unix=None, limit=200):
        out = []
        for f in self._history_files()[-2:]:
            for e in parse_m3u(f):
                tid = self.match_now_playing(e)
                t = e["time"] or file_mtime(f)
                if tid and not (since_unix and t < since_unix):
                    out.append({"track_id": tid, "title": e["title"], "artist": e["artist"],
                                "deck": None, "session": f, "time": t})
        out.sort(key=lambda x: x["time"])
        return out[-limit:]

    def history_sessions(self):
        out = []
        for f in self._history_files():
            entries = parse_m3u(f)
            ids, times = [], []
            for e in entries:
                tid = self.match_now_playing(e)
                if tid:
                    ids.append(tid)
                    times.append(e["time"] or 0)
            if ids:
                out.append({"id": f, "start": times[0] or file_mtime(f), "tracks": ids, "times": times})
        return out
