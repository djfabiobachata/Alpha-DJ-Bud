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


_pip_tried = {"done": False}


def _import_itlibrary():
    """Import Apple's iTunesLibrary bridge; install it once if it's missing."""
    try:
        from iTunesLibrary import ITLibrary
        return ITLibrary
    except ImportError:
        if _pip_tried["done"]:
            raise
        _pip_tried["done"] = True
        import subprocess
        subprocess.run([sys.executable, "-m", "pip", "install", "--quiet",
                        "pyobjc-framework-iTunesLibrary"], capture_output=True, timeout=600)
        import importlib
        importlib.invalidate_caches()
        from iTunesLibrary import ITLibrary
        return ITLibrary


def load():
    """Return {'tracks': {pid: {...}}, 'playlists': [{...}], 'method': ...}.
    First Apple's iTunesLibrary framework; if that fails, ask the Music app
    itself (JavaScript for Automation)."""
    if sys.platform != "darwin":
        raise MusicLibraryError("notMac")
    errors = []
    try:
        data = _load_itlibrary()
        if data["tracks"]:
            data["method"] = "iTunesLibrary"
            return data
        errors.append("iTunesLibrary: empty library")
    except Exception as e:
        errors.append("iTunesLibrary: %s" % e)
    try:
        data = _load_via_music_app()
        data["method"] = "Music app"
        return data
    except Exception as e:
        errors.append("Music app: %s" % e)
    raise MusicLibraryError(" | ".join(errors))


def _load_itlibrary():
    try:
        ITLibrary = _import_itlibrary()
    except ImportError as e:
        raise MusicLibraryError("component missing (%s)" % e)
    lib, err = ITLibrary.alloc().initWithAPIVersion_error_("1.0", None)
    if lib is None:
        raise MusicLibraryError("no access (%s)" % (err.localizedDescription() if err is not None else "?"))

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


_JXA = r"""
function run() {
  var Music = Application('Music');
  var out = {tracks: [], playlists: []};
  var lib = Music.libraryPlaylists[0];
  var ft = lib.fileTracks;
  var n = ft.length;
  if (n > 0) {
    var pid = ft.persistentID(), name = ft.name(), artist = ft.artist(), bpm = ft.bpm(),
        com = ft.comment(), dur = ft.duration(), genre = ft.genre(), loc = [];
    try {                      // fast: all locations in one request
      loc = ft.location().map(function (l) { return l ? l.toString() : null; });
    } catch (e) {              // a missing file breaks the batch: one by one
      loc = [];
      for (var i = 0; i < n; i++) {
        var p = null;
        try { var l = ft[i].location(); p = l ? l.toString() : null; } catch (e2) {}
        loc.push(p);
      }
    }
    for (var i = 0; i < n; i++)
      out.tracks.push([pid[i], name[i], artist[i], bpm[i], com[i], dur[i], genre[i], loc[i]]);
  }
  var pls = Music.userPlaylists();
  for (var j = 0; j < pls.length; j++) {
    var pl = pls[j], parent = null, kind = 'none', ids = [];
    try { parent = pl.parent().persistentID(); } catch (e) {}
    try { kind = pl.specialKind(); } catch (e) {}
    try { ids = pl.tracks.persistentID(); } catch (e) {}
    out.playlists.push([pl.persistentID(), parent, pl.name(), kind, ids]);
  }
  return JSON.stringify(out);
}
"""


def _load_via_music_app(timeout=240):
    """Ask the Music app for its library (macOS asks once to allow it)."""
    import json
    import subprocess
    r = subprocess.run(["/usr/bin/osascript", "-l", "JavaScript", "-e", _JXA],
                       capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise MusicLibraryError((r.stderr or "osascript failed").strip()[-300:])
    raw = json.loads(r.stdout)
    hexid = lambda h: int(h, 16) if h else None
    tracks = {}
    for pid, name, artist, bpm, com, dur, genre, loc in raw["tracks"]:
        p = hexid(pid)
        if p is None:
            continue
        tracks[p] = {"pid": p, "title": name or "", "artist": artist or "",
                     "bpm": float(bpm) if bpm else None, "comments": com or "",
                     "duration": float(dur) if dur else None, "genre": genre or "",
                     "path": loc or None}
    playlists = []
    for pid, parent, name, kind, ids in raw["playlists"]:
        folder = kind == "folder"
        special = kind not in ("none", "folder")
        items = [hexid(i) for i in ids or []]
        items = [i for i in items if i in tracks]
        if special and not items:
            continue
        playlists.append({"pid": hexid(pid), "parent": hexid(parent), "name": name or "",
                          "folder": folder, "special": special, "items": items})
    return {"tracks": tracks, "playlists": playlists}
