"""Fake libraries of VirtualDJ, Serato, Traktor and rekordbox, written in each
software's own format, for the tests."""
import os
import sqlite3
import struct
from urllib.parse import quote

# (file name, title, artist, bpm, camelot, musical key)
SONGS = [
    ("01 Propuesta.mp3", "Propuesta Indecente", "Romeo Santos", 128.0, "3A", "Bbm"),
    ("02 Darte.mp3", "Darte un Beso", "Prince Royce", 129.0, "3B", "Db"),
    ("03 Obsesion.mp3", "Obsesión", "Aventura", 125.0, "2A", "Ebm"),
    ("04 Bachata Rosa.mp3", "Bachata Rosa", "Juan Luis Guerra", 127.0, "9A", "Em"),
    ("05 Idilio.mp3", "Idilio", "Willie Colón", 180.0, "8A", "Am"),
]


def audio(root):
    d = os.path.join(root, "Music")
    os.makedirs(d, exist_ok=True)
    paths = []
    for name, *_ in SONGS:
        p = os.path.join(d, name)
        with open(p, "wb") as f:
            f.write(b"ID3fake")
        paths.append(p)
    return paths


def _x(s):
    from xml.sax.saxutils import quoteattr
    return quoteattr(s)


# -- VirtualDJ ------------------------------------------------------------------
def virtualdj(root, now=1764000000):
    paths = audio(root)
    home = os.path.join(root, "VirtualDJ")
    for sub in ("MyLists/Bachata", "Playlists", "History"):
        os.makedirs(os.path.join(home, sub), exist_ok=True)
    songs = []
    for p, (_, title, artist, bpm, _cam, mus) in zip(paths, SONGS):
        songs.append('<Song FilePath=%s FileSize="7">\n <Tags Author=%s Title=%s Flag="1" />\n'
                     ' <Infos SongLength="210.5" />\n <Scan Version="801" Bpm="%f" Key=%s />\n</Song>'
                     % (_x(p), _x(artist), _x(title), 60.0 / bpm, _x(mus)))
    with open(os.path.join(home, "database.xml"), "w", encoding="utf-8") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n<VirtualDJ_Database Version="2024">\n'
                + "\n".join(songs) + "\n</VirtualDJ_Database>\n")
    with open(os.path.join(home, "MyLists", "Bachata", "Sensual.vdjfolder"), "w") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n<VirtualFolder>\n'
                + "".join('<song path=%s idx="%d" />\n' % (_x(p), i) for i, p in enumerate(paths[:4]))
                + "</VirtualFolder>\n")
    with open(os.path.join(home, "Playlists", "Salsa.m3u"), "w") as f:
        f.write("#EXTM3U\n" + paths[4] + "\n")
    hist = os.path.join(home, "History", "2026-11-23.m3u")
    with open(hist, "w") as f:
        for i, p in enumerate(paths[2:4]):
            _, title, artist, *_ = SONGS[2 + i]
            f.write("#EXTVDJ:<time>22:0%d</time><lastplaytime>%d</lastplaytime><artist>%s</artist>"
                    "<title>%s</title>\n%s\n" % (i, now + 60 * i, artist, title, p))
    return home, paths


def virtualdj_play(home, path, title, artist, when):
    with open(os.path.join(home, "History", "2026-11-23.m3u"), "a") as f:
        f.write("#EXTVDJ:<lastplaytime>%d</lastplaytime><artist>%s</artist><title>%s</title>\n%s\n"
                % (when, artist, title, path))


# -- Serato -----------------------------------------------------------------------
def _chunk(tag, payload):
    return tag.encode("latin-1") + struct.pack(">I", len(payload)) + payload


def _u16(s):
    return s.encode("utf-16-be")


def _field(fid, payload):
    return struct.pack(">II", fid, len(payload)) + payload


def serato(root, now=1764000000):
    paths = audio(root)
    home = os.path.join(root, "Music", "_Serato_")
    os.makedirs(os.path.join(home, "Subcrates"), exist_ok=True)
    os.makedirs(os.path.join(home, "History", "Sessions"), exist_ok=True)
    rel = [p.lstrip("/") for p in paths]          # relative to the drive root ("/")
    db = _chunk("vrsn", _u16("2.0/Serato Scratch LIVE Database"))
    for r, (_, title, artist, bpm, cam, _mus) in zip(rel, SONGS):
        fields = (_chunk("ttyp", _u16("mp3")) + _chunk("pfil", _u16(r)) + _chunk("tsng", _u16(title))
                  + _chunk("tart", _u16(artist)) + _chunk("tbpm", _u16("%.2f" % bpm))
                  + _chunk("tkey", _u16(cam)) + _chunk("tlen", _u16("03:30.00")))
        db += _chunk("otrk", fields)
    with open(os.path.join(home, "database V2"), "wb") as f:
        f.write(db)

    def crate(name, items):
        data = _chunk("vrsn", _u16("1.0/Serato ScratchLive Crate"))
        for r in items:
            data += _chunk("otrk", _chunk("ptrk", _u16(r)))
        with open(os.path.join(home, "Subcrates", name + ".crate"), "wb") as f:
            f.write(data)

    crate("Bachata%%Sensual", rel[:4])
    crate("Salsa", rel[4:])
    serato_session(home, [(paths[2], SONGS[2], now), (paths[3], SONGS[3], now + 60)])
    return home, paths


def serato_session(home, entries, name="1.session"):
    data = _chunk("vrsn", _u16("1.0/Serato Scratch LIVE Review"))
    for i, (p, song, when) in enumerate(entries):
        adat = (_field(1, struct.pack(">I", i + 1)) + _field(2, _u16(p + "\x00"))
                + _field(6, _u16(song[1] + "\x00")) + _field(7, _u16(song[2] + "\x00"))
                + _field(31, struct.pack(">I", i % 2 + 1)) + _field(53, struct.pack(">I", when)))
        data += _chunk("oent", _chunk("adat", adat))
    with open(os.path.join(home, "History", "Sessions", name), "wb") as f:
        f.write(data)


# -- Traktor --------------------------------------------------------------------------
TRAKTOR_KEY = {"Bbm": 22, "Db": 1, "Ebm": 15, "Em": 16, "Am": 21}


def traktor(root):
    paths = audio(root)
    home = os.path.join(root, "Documents", "Native Instruments", "Traktor 3.11.1")
    os.makedirs(os.path.join(home, "History"), exist_ok=True)

    def loc(p):
        d, f = os.path.split(p)
        return "/:" + "/:".join(d.strip("/").split("/")) + "/:", f

    entries, keys = [], []
    for p, (_, title, artist, bpm, _cam, mus) in zip(paths, SONGS):
        d, f = loc(p)
        keys.append("Macintosh HD" + d + f)
        entries.append('<ENTRY TITLE=%s ARTIST=%s><LOCATION DIR=%s FILE=%s VOLUME="Macintosh HD" VOLUMEID="x"/>'
                       '<INFO PLAYTIME="210" KEY=%s/><TEMPO BPM="%.6f" BPM_QUALITY="100"/>'
                       '<MUSICAL_KEY VALUE="%d"/></ENTRY>'
                       % (_x(title), _x(artist), _x(d), _x(f), _x(mus), bpm, TRAKTOR_KEY[mus]))

    def plist(name, items):
        return ('<NODE TYPE="PLAYLIST" NAME=%s><PLAYLIST ENTRIES="%d" TYPE="LIST" UUID="u">' % (_x(name), len(items))
                + "".join('<ENTRY><PRIMARYKEY TYPE="TRACK" KEY=%s/></ENTRY>' % _x(k) for k in items)
                + "</PLAYLIST></NODE>")

    nml = ('<?xml version="1.0" encoding="UTF-8" standalone="no" ?><NML VERSION="19"><HEAD COMPANY="www.native-instruments.com" PROGRAM="Traktor"/>'
           '<COLLECTION ENTRIES="%d">%s</COLLECTION><PLAYLISTS><NODE TYPE="FOLDER" NAME="$ROOT"><SUBNODES COUNT="3">'
           '<NODE TYPE="FOLDER" NAME="Bachata"><SUBNODES COUNT="1">%s</SUBNODES></NODE>%s%s'
           '</SUBNODES></NODE></PLAYLISTS></NML>'
           % (len(entries), "".join(entries), plist("Sensual", keys[:4]), plist("Salsa", keys[4:]),
              plist("_LOOPS", [])))
    coll = os.path.join(home, "collection.nml")
    with open(coll, "w", encoding="utf-8") as f:
        f.write(nml)
    return coll, paths


def ogg_page(payload, serial=7, bos=False, seq=0):
    segs = []
    n = len(payload)
    while n >= 255:
        segs.append(255)
        n -= 255
    segs.append(n)
    return (b"OggS" + bytes([0, 0x02 if bos else 0]) + struct.pack("<qIII", 0, serial, seq, 0)
            + bytes([len(segs)]) + bytes(segs) + payload)


def vorbis_comment(title, artist):
    vendor = b"Traktor"
    tags = [("TITLE=" + title).encode(), ("ARTIST=" + artist).encode()]
    return (b"\x03vorbis" + struct.pack("<I", len(vendor)) + vendor + struct.pack("<I", len(tags))
            + b"".join(struct.pack("<I", len(t)) + t for t in tags) + b"\x01")


def traktor_broadcast(title, artist, serial=7):
    ident = b"\x01vorbis" + b"\x00" * 23
    return ogg_page(ident, serial, bos=True) + ogg_page(vorbis_comment(title, artist), serial, seq=1) \
        + ogg_page(b"\x05vorbis" + b"\x00" * 300, serial, seq=2)


# -- rekordbox ----------------------------------------------------------------------
def rekordbox(root, now_text="2026-11-23 22:01:00.000 +00:00"):
    """An unencrypted master.db with the same tables (the real one is SQLCipher)."""
    paths = audio(root)
    d = os.path.join(root, "Library", "Pioneer", "rekordbox")
    os.makedirs(d, exist_ok=True)
    db = os.path.join(d, "master.db")
    con = sqlite3.connect(db)
    con.executescript("""
    CREATE TABLE djmdContent (ID VARCHAR(255) PRIMARY KEY, FolderPath VARCHAR, Title VARCHAR, ArtistID VARCHAR,
      GenreID VARCHAR, KeyID VARCHAR, BPM INTEGER, Length INTEGER, Commnt TEXT, rb_local_deleted INTEGER DEFAULT 0);
    CREATE TABLE djmdArtist (ID VARCHAR PRIMARY KEY, Name VARCHAR);
    CREATE TABLE djmdGenre (ID VARCHAR PRIMARY KEY, Name VARCHAR);
    CREATE TABLE djmdKey (ID VARCHAR PRIMARY KEY, ScaleName VARCHAR);
    CREATE TABLE djmdPlaylist (ID VARCHAR PRIMARY KEY, Seq INTEGER, Name VARCHAR, Attribute INTEGER, ParentID VARCHAR,
      rb_local_deleted INTEGER DEFAULT 0);
    CREATE TABLE djmdSongPlaylist (ID VARCHAR PRIMARY KEY, PlaylistID VARCHAR, ContentID VARCHAR, TrackNo INTEGER,
      rb_local_deleted INTEGER DEFAULT 0);
    CREATE TABLE djmdHistory (ID VARCHAR PRIMARY KEY, Name VARCHAR, DateCreated VARCHAR, rb_local_deleted INTEGER DEFAULT 0);
    CREATE TABLE djmdSongHistory (ID VARCHAR PRIMARY KEY, HistoryID VARCHAR, ContentID VARCHAR, TrackNo INTEGER,
      created_at TEXT, rb_local_deleted INTEGER DEFAULT 0);
    """)
    for i, (p, (_, title, artist, bpm, _cam, mus)) in enumerate(zip(paths, SONGS)):
        cid = str(1000 + i)
        con.execute("INSERT INTO djmdArtist VALUES (?,?)", (str(i), artist))
        con.execute("INSERT INTO djmdKey VALUES (?,?)", ("k%d" % i, mus))
        con.execute("INSERT INTO djmdContent VALUES (?,?,?,?,?,?,?,?,?,0)",
                    (cid, p, title, str(i), None, "k%d" % i, int(bpm * 100), 210, ""))
    con.execute("INSERT INTO djmdContent VALUES ('999','/gone.mp3','Deleted','0',NULL,NULL,12000,200,'',1)")
    con.execute("INSERT INTO djmdPlaylist VALUES ('10',1,'Bachata',1,'root',0)")
    con.execute("INSERT INTO djmdPlaylist VALUES ('11',1,'Sensual',0,'10',0)")
    con.execute("INSERT INTO djmdPlaylist VALUES ('12',2,'Salsa',0,'root',0)")
    con.execute("INSERT INTO djmdPlaylist VALUES ('13',3,'Smart',4,'root',0)")
    for i in range(4):
        con.execute("INSERT INTO djmdSongPlaylist VALUES (?,?,?,?,0)", ("s%d" % i, "11", str(1000 + i), i + 1))
    con.execute("INSERT INTO djmdSongPlaylist VALUES ('s9','12','1004',1,0)")
    con.execute("INSERT INTO djmdHistory VALUES ('h1','2026-11-23','2026-11-23',0)")
    con.execute("INSERT INTO djmdSongHistory VALUES ('x1','h1','1002',1,'2026-11-23 22:00:00.000 +00:00',0)")
    con.execute("INSERT INTO djmdSongHistory VALUES ('x2','h1','1003',2,?,0)", (now_text,))
    con.commit()
    con.close()
    return db, paths


def rekordbox_play(db, cid, when_text, n):
    con = sqlite3.connect(db)
    con.execute("INSERT INTO djmdSongHistory VALUES (?,?,?,?,?,0)", ("y%d" % n, "h1", cid, 10 + n, when_text))
    con.commit()
    con.close()


def rekordbox_xml(root):
    paths = audio(root)
    tracks = "".join('<TRACK TrackID="%d" Name=%s Artist=%s AverageBpm="%.2f" Tonality=%s TotalTime="210" Location=%s/>'
                     % (i + 1, _x(s[1]), _x(s[2]), s[3], _x(s[5]), _x("file://localhost" + quote(p)))
                     for i, (p, s) in enumerate(zip(paths, SONGS)))
    xml = ('<?xml version="1.0" encoding="UTF-8"?><DJ_PLAYLISTS Version="1.0.0"><COLLECTION Entries="5">%s</COLLECTION>'
           '<PLAYLISTS><NODE Type="0" Name="ROOT" Count="1"><NODE Type="0" Name="Bachata" Count="1">'
           '<NODE Name="Sensual" Type="1" KeyType="0" Entries="2"><TRACK Key="1"/><TRACK Key="2"/></NODE>'
           '</NODE></NODE></PLAYLISTS></DJ_PLAYLISTS>' % tracks)
    p = os.path.join(root, "rekordbox.xml")
    with open(p, "w", encoding="utf-8") as f:
        f.write(xml)
    return p, paths
