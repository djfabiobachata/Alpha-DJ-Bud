"""Apple's Music app library (the "Music" source in djay), macOS only.

Read through Apple's iTunesLibrary framework (pyobjc-framework-iTunesLibrary).
The first time, macOS asks to allow access to "Media & Apple Music".
Returns plain Python data so merging it into the djay library is cheap.
"""
import re
import sys
from urllib.parse import unquote, urlparse

from . import camelot

_KEY_BPM_PREFIX = re.compile(r"^\s*(1[0-2]|0?[1-9])\s*([ABab])\s*[-_ ]+\s*(\d{2,3}(?:[.,]\d)?)\b")


class MusicLibraryError(Exception):
    pass


def key_bpm_from_text(*texts):
    """Camelot key and BPM written by tools like Mixed In Key in comments,
    titles or file names, e.g. '12A - 126 - Es Evidente' or '12A - Energy 6'."""
    key = bpm = None
    for t in texts:
        if not t:
            continue
        m = _KEY_BPM_PREFIX.match(t)
        if m:
            key = key or "%d%s" % (int(m.group(1)), m.group(2).upper())
            v = float(m.group(3).replace(",", "."))
            if 60 <= v <= 240:
                bpm = bpm or v
        if key is None:
            key = camelot.parse(t)
    return key, bpm


def _pid(num):
    try:
        return int(num) & 0xFFFFFFFFFFFFFFFF
    except (TypeError, ValueError):
        return None


def load():
    """Return {'tracks': {pid: {...}}, 'playlists': [{...}]} from the Music app."""
    if sys.platform != "darwin":
        raise MusicLibraryError("notMac")
    try:
        from iTunesLibrary import ITLibrary
    except ImportError as e:
        raise MusicLibraryError("noFramework: %s" % e)
    lib, err = ITLibrary.alloc().initWithAPIVersion_error_("1.0", None)
    if lib is None:
        raise MusicLibraryError("noAccess: %s" % err)

    tracks = {}
    for it in lib.allMediaItems() or []:
        try:
            if int(it.mediaKind()) != 2:  # songs only (no podcasts, videos, audiobooks)
                continue
            pid = _pid(it.persistentID())
            if pid is None:
                continue
            loc = it.location()
            path = unquote(urlparse(str(loc.absoluteString())).path) if loc is not None else None
            artist = it.artist().name() if it.artist() is not None else ""
            tracks[pid] = {
                "pid": pid,
                "title": str(it.title() or ""),
                "artist": str(artist or ""),
                "bpm": float(it.beatsPerMinute() or 0) or None,
                "comments": str(it.comments() or ""),
                "duration": (it.totalTime() or 0) / 1000.0 or None,
                "genre": str(it.genre() or ""),
                "path": path,
            }
        except Exception:
            continue

    playlists = []
    for pl in lib.allPlaylists() or []:
        try:
            if pl.isMaster() or not pl.isVisible():
                continue  # the whole library is offered separately as "Musica"
            kind = int(pl.kind())  # 3 = folder
            items = [_pid(i.persistentID()) for i in (pl.items() or [])]
            special = int(pl.distinguishedKind()) != 0  # e.g. "Purchased" / "Acquisti"
            if special and not any(i in tracks for i in items):
                continue  # podcasts, movies, TV shows...
            playlists.append({
                "pid": _pid(pl.persistentID()),
                "parent": _pid(pl.parentID()) if pl.parentID() is not None else None,
                "name": str(pl.name() or ""),
                "folder": kind == 3,
                "special": special,
                "items": [i for i in items if i in tracks],
            })
        except Exception:
            continue
    return {"tracks": tracks, "playlists": playlists}
