"""Builds a small fake djay MediaLibrary.db (TSAF-encoded) for tests and demos."""
import os
import sqlite3
import struct
import time

HEADER = b"TSAF\x03\x00\x03\x00\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"


class _W:
    def __init__(self):
        self.b = bytearray(HEADER)

    def pad(self, n):
        while len(self.b) % n:
            self.b.append(0)

    def s(self, text):
        self.b.append(0x08)
        self.b += text.encode("utf-8") + b"\x00"

    def v(self, val):
        if val is None:
            self.b.append(0x01)
        elif isinstance(val, bool):
            self.b.append(0x0D if val else 0x0E)
        elif isinstance(val, dict):
            self.b.append(0x2B)
            self.s(val["_class"])
            for k, x in val.items():
                if k == "_class":
                    continue
                self.v(x)
                self.s(k)
            self.b.append(0x00)
        elif isinstance(val, str):
            self.s(val)
        elif isinstance(val, int):
            if 0 <= val < 256:
                self.b.append(0x0F)
                self.b.append(val)
            else:
                self.b.append(0x11)
                self.pad(4)
                self.b += struct.pack("<i", val)
        elif isinstance(val, float):
            self.b.append(0x13)
            self.pad(4)
            self.b += struct.pack("<f", val)
        elif isinstance(val, Date):
            self.b.append(0x30)
            self.pad(8)
            self.b += struct.pack("<d", val.t)
        elif isinstance(val, list):
            self.b.append(0x0C)
            self.pad(4)
            self.b += struct.pack("<I", len(val))
            for x in val:
                self.v(x)
        else:
            raise TypeError(val)


class Date:
    def __init__(self, unix):
        self.t = unix - 978307200.0


def encode(obj):
    w = _W()
    w.v(obj)
    return bytes(w.b)


# Camelot -> djay key index
CAM_TO_IDX = {c: i for i, c in enumerate([
    "8B", "8A", "3B", "3A", "10B", "10A", "5B", "5A", "12B", "12A", "7B", "7A",
    "2B", "2A", "9B", "9A", "4B", "4A", "11B", "11A", "6B", "6A", "1B", "1A"])}

TRACKS = [
    # id, title, artist, bpm, camelot
    ("t01", "Propuesta Indecente", "Romeo Santos", 128.0, "3A"),
    ("t02", "Eres Mía", "Romeo Santos", 126.0, "3A"),          # same artist -> excluded
    ("t03", "Darte un Beso", "Prince Royce", 129.0, "3B"),     # relative
    ("t04", "Corazón Sin Cara", "Prince Royce", 131.0, "4A"),  # +1
    ("t05", "Obsesión", "Aventura", 125.0, "2A"),              # -1
    ("t06", "Bachata Rosa", "Juan Luis Guerra", 127.0, "9A"),  # +6
    ("t07", "Me Enamoré", "Grupo Extra", 128.5, "9B"),         # +6 other letter
    ("t08", "La Bachata", "Manuel Turizo", 128.0, "5A"),       # key not allowed
    ("t09", "Te Extraño", "Xtreme", 140.0, "3A"),              # bpm too far
    ("t10", "Odio", "Romeo Santos & Drake", 128.0, "3B"),      # shares artist
    ("t11", "Sin Analisi", "Mystery", None, None),             # no data
    ("t12", "Ella y Yo", "Aventura feat. Don Omar", 132.0, "3A"),  # +4 bpm, ok
    ("s01", "Idilio", "Willie Colón", 180.0, "8A"),            # salsa folder
]


def build(path, with_history=True, audio_dir=None):
    if os.path.exists(path):
        os.remove(path)
    con = sqlite3.connect(path)
    con.execute('CREATE TABLE "database2" ("rowid" INTEGER PRIMARY KEY, "collection" CHAR NOT NULL, '
                '"key" CHAR NOT NULL, "data" BLOB, "metadata" BLOB)')
    con.execute('CREATE TABLE "secondaryIndex_mediaItemUserDataIndex" ("rowid" INTEGER PRIMARY KEY, '
                '"tags" TEXT, "manualBPM" REAL)')

    def put(col, key, obj):
        con.execute("INSERT INTO database2 (collection, key, data) VALUES (?,?,?)", (col, key, encode(obj)))

    for tid, title, artist, bpm, cam in TRACKS:
        tid_obj = {"_class": "ADCMediaItemTitleID", "uuid": tid, "title": title, "artist": artist, "duration": 200.0}
        put("mediaItems", tid, {"_class": "ADCMediaItem", "uuid": tid, "titleID": tid_obj,
                                "title": title, "contentType": "public.mp3", "duration": 200.0})
        ad = {"_class": "ADCMediaItemAnalyzedData", "uuid": tid, "titleIDs": [tid_obj]}
        if bpm:
            ad["bpm"] = bpm
        if cam:
            ad["keySignatureIndex"] = CAM_TO_IDX[cam]
        put("mediaItemAnalyzedData", tid, ad)
        if audio_dir and tid != "t11":  # t11 = streaming track, no local file
            from urllib.parse import quote
            f = os.path.join(audio_dir, "%s - %s.mp3" % (artist, title))
            with open(f, "wb") as fh:
                fh.write(b"ID3fake")
            put("localMediaItemLocations", tid, {"_class": "ADCMediaItemLocation", "uuid": tid,
                                                  "sourceURIs": ["file://" + quote(f)]})

    def playlist(uid, name, parent, items=None, children=None):
        o = {"_class": "ADCMediaItemPlaylist", "uuid": uid, "name": name}
        if parent:
            o["parentUUID"] = parent
        o["type"] = 0 if children is not None else 1
        if items:
            refs = []
            for i, t in enumerate(items):
                ref = "%s-item-%d" % (uid, i)
                put("mediaItemPlaylistItems", ref, {"_class": "ADCMediaItemPlaylistItem", "uuid": ref,
                                                    "playlistUUID": uid, "mediaItemUUID": t})
                refs.append(ref)
            o["itemUUIDs"] = refs
        if children is not None:
            o["childUUIDs"] = children
        put("mediaItemPlaylists", uid, o)

    bachata = [t[0] for t in TRACKS if t[0].startswith("t")]
    playlist("root", "Playlist", None, children=["F-BACHATA", "F-SALSA"])
    playlist("F-BACHATA", "Bachata", "mediaItemPlaylist-root", children=["P-B1", "P-B2"])
    playlist("P-B1", "Bachata Sensual", "F-BACHATA", items=bachata[:6])
    playlist("P-B2", "Bachata Classica", "F-BACHATA", items=bachata[6:])
    playlist("F-SALSA", "Salsa", "mediaItemPlaylist-root", children=["P-S1"])
    playlist("P-S1", "Salsa Dura", "F-SALSA", items=["s01"])

    if with_history:
        now = time.time()
        sess = {"_class": "ADCHistorySession", "uuid": "S1", "deviceName": "Test",
                "startDate": Date(now - 600), "itemUUIDs": ["H1", "H2"]}
        put("historySessions", "S1", sess)
        for hid, tid, ago, deck in (("H1", "t05", 400, 0), ("H2", "t01", 60, 1)):
            title = next(t for t in TRACKS if t[0] == tid)
            put("historySessionItems", hid, {
                "_class": "ADCHistorySessionItem", "uuid": hid, "sessionUUID": "S1",
                "titleID": {"_class": "ADCMediaItemTitleID", "uuid": tid, "title": title[1],
                            "artist": title[2], "duration": 200.0},
                "deckNumber": deck, "startTime": Date(now - ago), "originSourceID": "file"})
    con.commit()
    con.close()
    return path


def add_history(path, hid, tid, deck=0):
    con = sqlite3.connect(path)
    title = next(t for t in TRACKS if t[0] == tid)
    con.execute("INSERT INTO database2 (collection, key, data) VALUES (?,?,?)", (
        "historySessionItems", hid, encode({
            "_class": "ADCHistorySessionItem", "uuid": hid, "sessionUUID": "S1",
            "titleID": {"_class": "ADCMediaItemTitleID", "uuid": tid, "title": title[1],
                        "artist": title[2], "duration": 200.0},
            "deckNumber": deck, "startTime": Date(time.time()), "originSourceID": "file"})))
    con.commit()
    con.close()


if __name__ == "__main__":
    import sys
    print(build(sys.argv[1] if len(sys.argv) > 1 else "demo.db"))
