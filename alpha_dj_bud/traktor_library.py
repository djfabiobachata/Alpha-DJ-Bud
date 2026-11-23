"""Read-only access to the Traktor Pro library (macOS).

Traktor keeps everything in ~/Documents/Native Instruments/Traktor <version>/:
  collection.nml           XML with every track (TEMPO BPM, MUSICAL_KEY) and
                           every playlist / folder. Traktor saves it when it
                           closes (and when you choose File > Save Collection).
  History/history_*.nml    the tracks played in each session.

Traktor doesn't write the track on air anywhere while you play. What it can do
is "Broadcasting" (Preferences > Broadcasting): it sends the mix with the title
and artist of the track on air to an Icecast server. Alpha DJ Bud listens as a
tiny Icecast server on this Mac (localhost, port 8000 by default): it reads only
the title / artist and throws the audio away.
"""
import glob
import os
import socket
import struct
import threading
import time
import xml.etree.ElementTree as ET

from . import camelot
from .library_base import BaseLibrary, file_mtime, to_float

HOME_GLOB = "~/Documents/Native Instruments/Traktor*"
BROADCAST_PORT = 8000


def find_collection(explicit=None):
    if explicit:
        p = os.path.expanduser(explicit)
        if os.path.isdir(p):
            p = os.path.join(p, "collection.nml")
        return p if os.path.isfile(p) else None
    found = []
    for d in glob.glob(os.path.expanduser(HOME_GLOB)):
        for name in ("collection.nml", "Collection.nml"):
            p = os.path.join(d, name)
            if os.path.isfile(p):
                found.append(p)
                break
    return max(found, key=file_mtime) if found else None


def location_path(loc):
    """Full path of a LOCATION element (VOLUME + DIR with '/:' separators + FILE)."""
    if loc is None:
        return None, None
    vol, d, f = loc.get("VOLUME") or "", loc.get("DIR") or "", loc.get("FILE") or ""
    if not f:
        return None, None
    rel = d.replace("/:", "/") + f
    if not rel.startswith("/"):
        rel = "/" + rel
    key = vol + d + f                      # how playlists point at the track
    drive = "/Volumes/" + vol if vol else None
    if drive and os.path.isdir(drive) and os.path.realpath(drive) != "/":
        return drive + rel, key            # external drive (mounted)
    if os.path.exists(rel) or not drive or rel.startswith("/Users/"):
        return rel, key                    # the Mac's own disk
    return drive + rel, key                # drive not mounted right now


def parse_history(path):
    """Tracks of a history_*.nml, in play order: [{'path','title','artist','time','deck'}]."""
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, OSError):
        return []
    out = []
    for e in root.iter("ENTRY"):
        loc = e.find("LOCATION")
        if loc is None:
            continue
        p, _ = location_path(loc)
        ext = e.find("EXTENDEDDATA")
        t = None
        deck = None
        if ext is not None:
            t = _traktor_time(ext.get("STARTDATE"), ext.get("STARTTIME"))
            deck = ext.get("DECK")
        out.append({"path": p, "title": e.get("TITLE"), "artist": e.get("ARTIST"),
                    "time": t, "deck": int(deck) if deck and deck.isdigit() else None})
    return out


def _traktor_time(date, secs):
    """STARTDATE is packed (year << 16 | month << 8 | day), STARTTIME seconds of the day."""
    try:
        d = int(date)
        y, m, day = d >> 16, (d >> 8) & 0xFF, d & 0xFF
        return time.mktime((y, m, day, 0, 0, 0, 0, 0, -1)) + float(secs or 0)
    except (TypeError, ValueError, OverflowError):
        return None


class TraktorLibrary(BaseLibrary):
    SOFTWARE = "traktor"
    ALL_ID = "traktor:all"

    def __init__(self, path, key_from_comments=False, broadcast_port=BROADCAST_PORT):
        super().__init__(path, key_from_comments)    # path = collection.nml
        self._order = []
        self.broadcast = BroadcastReceiver(broadcast_port) if broadcast_port else None

    def close(self):
        if self.broadcast:
            self.broadcast.stop()

    def _read(self):
        root = ET.parse(self.path).getroot()
        by_key = {}
        coll = root.find("COLLECTION")
        for e in (coll.findall("ENTRY") if coll is not None else []):
            p, key = location_path(e.find("LOCATION"))
            if not p:
                continue
            info = e.find("INFO")
            info = info.attrib if info is not None else {}
            tempo = e.find("TEMPO")
            mk = e.find("MUSICAL_KEY")
            k = camelot.from_traktor_index(mk.get("VALUE")) if mk is not None else None
            k = k or camelot.parse(info.get("KEY"))
            dur = to_float(info.get("PLAYTIME_FLOAT")) or to_float(info.get("PLAYTIME"))
            tid = self.add_file_track(p, e.get("TITLE") or "", e.get("ARTIST") or "",
                                      to_float(tempo.get("BPM")) if tempo is not None else None,
                                      k, dur, info.get("COMMENT"), info.get("GENRE"))
            by_key[key] = tid
        self._order = []
        pls = root.find("PLAYLISTS")
        top = pls.find("NODE") if pls is not None else None   # the invisible $ROOT folder
        if top is not None:
            self._read_node(top, None, by_key, "traktor:")

    def _read_node(self, node, parent, by_key, prefix):
        sub = node.find("SUBNODES")
        for child in (sub.findall("NODE") if sub is not None else []):
            name = child.get("NAME") or "Playlist"
            pid = prefix + name
            typ = child.get("TYPE")
            if typ == "FOLDER":
                self.add_playlist(pid, name, parent, folder=True)
                self._read_node(child, pid, by_key, pid + "/")
            elif typ == "PLAYLIST":
                pl = child.find("PLAYLIST")
                ids = []
                for e in (pl.findall("ENTRY") if pl is not None else []):
                    pk = e.find("PRIMARYKEY")
                    if pk is not None and pk.get("KEY") in by_key:
                        ids.append(by_key[pk.get("KEY")])
                if name.startswith("_") and parent is None and name.lower() in ("_loops", "_recordings"):
                    continue
                self.add_playlist(pid, name, parent, ids)
            else:
                continue
            if parent is None:
                self._order.append(pid)

    def own_roots(self):
        return [p for p in self._order if p in self.playlists]

    # -- history / now playing ----------------------------------------------------
    def _history_files(self):
        files = glob.glob(os.path.join(os.path.dirname(self.path), "History", "*.nml"))
        return sorted(files, key=file_mtime)

    def read_now_playing(self):
        live = self.broadcast.now() if self.broadcast else None
        hist = self._history_files()
        hist_t = file_mtime(hist[-1]) if hist else 0
        if live and live[0] >= hist_t - 1:
            return live
        if hist:
            entries = parse_history(hist[-1])
            if entries:
                e = entries[-1]
                return hist_t, {"title": e["title"], "artist": e["artist"], "path": e["path"],
                                "deck": e["deck"]}
        return None, None

    def history(self, since_unix=None, limit=200):
        out = []
        for f in self._history_files()[-2:]:
            for e in parse_history(f):
                tid = self.match_now_playing(e)
                t = e["time"] or file_mtime(f)
                if tid and not (since_unix and t < since_unix):
                    out.append({"track_id": tid, "title": e["title"], "artist": e["artist"],
                                "deck": e["deck"], "session": f, "time": t})
        out.sort(key=lambda x: x["time"])
        return out[-limit:]

    def history_sessions(self):
        out = []
        for f in self._history_files():
            ids, times = [], []
            for e in parse_history(f):
                tid = self.match_now_playing(e)
                if tid:
                    ids.append(tid)
                    times.append(e["time"] or 0)
            if ids:
                out.append({"id": f, "start": times[0] or file_mtime(f), "tracks": ids, "times": times})
        return out


# -- Traktor "Broadcasting" receiver -------------------------------------------------
class BroadcastReceiver:
    """A minimal Icecast source endpoint: Traktor connects, Bud answers OK and
    reads the Ogg Vorbis comment headers (TITLE / ARTIST) Traktor sends at
    every track change. Audio is discarded."""

    def __init__(self, port=BROADCAST_PORT, host="127.0.0.1"):
        self.port = port
        self.host = host
        self.status = {"listening": False, "connected": False, "error": None}
        self._now = None
        self._stop = False
        self._sock = None
        threading.Thread(target=self._serve, daemon=True).start()

    def now(self):
        return self._now

    def stop(self):
        self._stop = True
        try:
            if self._sock:
                self._sock.close()
        except OSError:
            pass

    def _serve(self):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((self.host, self.port))
            s.listen(2)
            s.settimeout(1.0)
            self._sock = s
            self.status["listening"] = True
        except OSError as e:
            self.status["error"] = "port %d busy: %s" % (self.port, e)
            return
        while not self._stop:
            try:
                conn, _ = s.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            threading.Thread(target=self._client, args=(conn,), daemon=True).start()

    def _client(self, conn):
        conn.settimeout(30)
        try:
            head = b""
            while b"\r\n\r\n" not in head and len(head) < 16384:
                b = conn.recv(4096)
                if not b:
                    return
                head += b
            req, _, rest = head.partition(b"\r\n\r\n")
            first = req.split(b"\r\n", 1)[0].upper()
            if not (first.startswith(b"SOURCE") or first.startswith(b"PUT")):
                conn.sendall(b"HTTP/1.0 404 Not Found\r\n\r\n")
                return
            conn.sendall(b"HTTP/1.0 200 OK\r\nServer: Icecast 2.4.0\r\n\r\n")
            self.status["connected"] = True
            parser = OggCommentParser(self._on_comment)
            parser.feed(rest)
            while not self._stop:
                b = conn.recv(65536)
                if not b:
                    break
                parser.feed(b)
        except (OSError, socket.timeout):
            pass
        finally:
            self.status["connected"] = False
            try:
                conn.close()
            except OSError:
                pass

    def _on_comment(self, tags):
        title = tags.get("title")
        if title:
            self._now = (time.time(), {"title": title, "artist": tags.get("artist") or ""})


class OggCommentParser:
    """Feed raw Ogg bytes; calls on_comment({'title':..,'artist':..}) for every
    Vorbis comment header (one per track in Traktor's broadcast)."""

    def __init__(self, on_comment):
        self.buf = b""
        self.packets = {}
        self.on_comment = on_comment

    def feed(self, data):
        self.buf += data
        while True:
            i = self.buf.find(b"OggS")
            if i < 0:
                self.buf = self.buf[-3:]
                return
            if i:
                self.buf = self.buf[i:]
            if len(self.buf) < 27:
                return
            nseg = self.buf[26]
            if len(self.buf) < 27 + nseg:
                return
            lacing = self.buf[27:27 + nseg]
            size = sum(lacing)
            end = 27 + nseg + size
            if len(self.buf) < end:
                if len(self.buf) > 1 << 20:     # garbage: resync
                    self.buf = self.buf[4:]
                    continue
                return
            serial = struct.unpack("<I", self.buf[14:18])[0]
            if self.buf[5] & 0x02:              # beginning of a new stream (= new track)
                self.packets[serial] = b""
            body = self.buf[27 + nseg:end]
            self.buf = self.buf[end:]
            pos = 0
            cur = self.packets.get(serial, b"")
            for lv in lacing:
                cur += body[pos:pos + lv]
                pos += lv
                if lv < 255:
                    self._packet(cur)
                    cur = b""
            self.packets[serial] = cur[-(1 << 16):]

    def _packet(self, p):
        if not p.startswith(b"\x03vorbis"):
            return
        try:
            i = 7
            vlen = struct.unpack("<I", p[i:i + 4])[0]
            i += 4 + vlen
            n = struct.unpack("<I", p[i:i + 4])[0]
            i += 4
            tags = {}
            for _ in range(min(n, 200)):
                ln = struct.unpack("<I", p[i:i + 4])[0]
                i += 4
                kv = p[i:i + ln].decode("utf-8", errors="replace")
                i += ln
                k, _, v = kv.partition("=")
                tags.setdefault(k.lower(), v)
            self.on_comment(tags)
        except (struct.error, IndexError):
            pass
