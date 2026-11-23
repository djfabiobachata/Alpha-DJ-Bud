"""Read-only access to the Serato DJ (Lite / Pro) library (macOS).

Serato keeps its library in ~/Music/_Serato_ (and in /Volumes/<drive>/_Serato_
for the tracks of each external drive):
  database V2               every track: path, tags, BPM and key
  Subcrates/*.crate         crates; 'Bachata%%Sensual.crate' = crate 'Sensual'
                            inside crate 'Bachata'
  History/Sessions/*.session  one file per session, written while you play:
                            the newest entry is the track on air
All files use the same simple binary layout: a 4-letter tag, a 4-byte length
and the data; text is UTF-16 (big endian). Paths in the database and crates are
relative to the root of their drive.
"""
import glob
import os
import struct

from . import camelot
from .library_base import BaseLibrary, file_id, file_mtime, to_float, _duration, _norm_path

HOME = "~/Music/_Serato_"


def find_home(explicit=None):
    p = os.path.expanduser(explicit or HOME)
    if os.path.basename(p) == "database V2":
        p = os.path.dirname(p)
    return p if os.path.isfile(os.path.join(p, "database V2")) else None


def chunks(data):
    """Yield (tag, payload) of a Serato tag-length-value buffer."""
    i, n = 0, len(data)
    while i + 8 <= n:
        tag = data[i:i + 4].decode("latin-1")
        size = struct.unpack(">I", data[i + 4:i + 8])[0]
        yield tag, data[i + 8:i + 8 + size]
        i += 8 + size


def text(b):
    return b.decode("utf-16-be", errors="replace").rstrip("\x00")


def read_records(path, record):
    """Fields of every `record` ('otrk', 'oent'...) of a Serato file."""
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError:
        return []
    out = []
    for tag, payload in chunks(data):
        if tag == record:
            out.append({t: v for t, v in chunks(payload)})
    return out


def session_entries(path):
    """Entries of a History/Sessions/*.session file. The fields of an entry
    are numbered: 2 = file path, 6 = title, 7 = artist, 31 = deck,
    53 = start time (unix), 45 = seconds played."""
    out = []
    for rec in read_records(path, "oent"):
        adat = rec.get("adat")
        if not adat:
            continue
        f = {}
        i = 0
        while i + 8 <= len(adat):
            fid, size = struct.unpack(">II", adat[i:i + 8])
            f[fid] = adat[i + 8:i + 8 + size]
            i += 8 + size

        def num(k):
            v = f.get(k)
            return struct.unpack(">I", v[:4])[0] if v and len(v) >= 4 else None

        deck = num(31)
        out.append({"path": text(f[2]) if 2 in f else None,
                    "title": text(f[6]) if 6 in f else None,
                    "artist": text(f[7]) if 7 in f else None,
                    "deck": deck - 1 if deck else None,   # Serato counts decks from 1
                    "time": num(53), "played": num(45)})
    out.sort(key=lambda e: e["time"] or 0)
    return out


class SeratoLibrary(BaseLibrary):
    SOFTWARE = "serato"
    ALL_ID = "serato:all"

    def __init__(self, path, key_from_comments=False):
        super().__init__(path, key_from_comments)   # path = the _Serato_ folder
        self._order = []

    def _homes(self):
        """(serato folder, drive root) pairs: the Mac's and each drive's."""
        homes = [(self.path, "/")]
        for d in sorted(glob.glob("/Volumes/*/_Serato_")):
            if os.path.isfile(os.path.join(d, "database V2")) and os.path.realpath(d) != os.path.realpath(self.path):
                homes.append((d, os.path.dirname(d)))
        return homes

    def _crates(self):
        files = []
        for home, root in self._homes():
            files += [(f, root) for f in glob.glob(os.path.join(home, "Subcrates", "*.crate"))]
        return files

    def source_mtime(self):
        return file_mtime(*([os.path.join(h, "database V2") for h, _ in self._homes()]
                            + [f for f, _ in self._crates()]))

    @staticmethod
    def _abs(rel, root):
        rel = rel or ""
        if rel.startswith("/"):
            return rel
        return os.path.join(root, rel)

    def _read(self):
        for home, root in self._homes():
            for r in read_records(os.path.join(home, "database V2"), "otrk"):
                if "pfil" not in r:
                    continue
                path = self._abs(text(r["pfil"]), root)
                g = lambda k: text(r[k]) if k in r else ""   # noqa: E731
                self.add_file_track(path, g("tsng"), g("tart"), to_float(g("tbpm")),
                                    camelot.parse(g("tkey")), _duration(g("tlen")),
                                    g("tcom"), g("tgen"))
        self._order = []
        crates = sorted(self._crates(), key=lambda c: os.path.basename(c[0]).lower())
        for path, root in crates:
            parts = os.path.basename(path)[:-len(".crate")].split("%%")
            ids = []
            for r in read_records(path, "otrk"):
                if "ptrk" in r:
                    tid = file_id(_norm_path(self._abs(text(r["ptrk"]), root)))
                    if tid in self.tracks:
                        ids.append(tid)
            parent = None
            for depth in range(len(parts)):
                pid = "serato:" + "%%".join(parts[:depth + 1])
                last = depth == len(parts) - 1
                if pid not in self.playlists and parent is None:
                    self._order.append(pid)
                self.add_playlist(pid, parts[depth], parent, ids if last else (), folder=not last)
                parent = pid

    def own_roots(self):
        return [p for p in self._order if p in self.playlists]

    # -- history / now playing ----------------------------------------------------
    def _sessions(self):
        files = glob.glob(os.path.join(self.path, "History", "Sessions", "*.session"))
        return sorted(files, key=file_mtime)

    def read_now_playing(self):
        files = self._sessions()
        if not files:
            return None, None
        entries = [e for e in session_entries(files[-1]) if e["path"] or e["title"]]
        if not entries:
            return None, None
        last = entries[-1]
        return file_mtime(files[-1]), {"title": last["title"], "artist": last["artist"],
                                       "path": last["path"], "deck": last["deck"]}

    def history(self, since_unix=None, limit=200):
        out = []
        for f in self._sessions()[-2:]:
            for e in session_entries(f):
                tid = self.match_now_playing(e)
                t = e["time"] or file_mtime(f)
                if tid and not (since_unix and t < since_unix):
                    out.append({"track_id": tid, "title": e["title"], "artist": e["artist"],
                                "deck": e["deck"], "session": f, "time": t})
        out.sort(key=lambda x: x["time"])
        return out[-limit:]

    def history_sessions(self):
        out = []
        for f in self._sessions():
            ids, times = [], []
            for e in session_entries(f):
                tid = self.match_now_playing(e)
                if tid:
                    ids.append(tid)
                    times.append(e["time"] or 0)
            if ids:
                out.append({"id": f, "start": times[0] or file_mtime(f), "tracks": ids, "times": times})
        return out
