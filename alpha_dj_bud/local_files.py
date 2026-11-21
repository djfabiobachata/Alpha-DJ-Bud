"""Folders on the Mac as a source (djay's "Finder / My files" and USB drives).

The DJ chooses one or more folders; every sub-folder with audio files becomes a
playlist. Title, artist, BPM and key come from the file tags (via mutagen, when
installed) or from the file name ("12A - 126 - Artist - Title.mp3").
Results are cached by file modification time, so rescans are quick.
"""
import hashlib
import json
import os
import re

from . import camelot

AUDIO_EXT = {".mp3", ".m4a", ".aac", ".wav", ".aif", ".aiff", ".flac", ".ogg", ".alac", ".mp4", ".opus"}
MAX_FILES = 30000
_NAME = re.compile(r"^\s*(?:(1[0-2]|0?[1-9])\s*([ABab])\s*[-_ ]+\s*)?(?:(\d{2,3}(?:[.,]\d)?)\s*[-_ ]+\s*)?"
                   r"(?:\d{1,2}\s*[-_. ]+\s*)?(?:(.+?)\s+[-–]\s+)?(.+?)\s*$")


def folder_id(path):
    return "fs:" + hashlib.md5(path.encode("utf-8")).hexdigest()[:16]


def _first(v):
    if isinstance(v, (list, tuple)):
        v = v[0] if v else None
    if v is None:
        return None
    if hasattr(v, "text"):  # mutagen ID3 frames
        return _first(v.text)
    return str(v)


def _from_name(path):
    base = os.path.splitext(os.path.basename(path))[0]
    m = _NAME.match(base)
    key = bpm = artist = None
    title = base
    if m:
        if m.group(1):
            key = "%d%s" % (int(m.group(1)), m.group(2).upper())
        if m.group(3):
            v = float(m.group(3).replace(",", "."))
            bpm = v if 60 <= v <= 240 else None
        artist, title = m.group(4), m.group(5) or base
    return {"title": title, "artist": artist or "", "bpm": bpm, "key": key, "comments": "", "duration": None}


def read_tags(path):
    """Metadata of one audio file (tags first, file name as fallback)."""
    meta = _from_name(path)
    try:
        import mutagen
    except ImportError:
        return meta
    try:
        f = mutagen.File(path)
    except Exception:
        f = None
    if f is None:
        return meta
    tags = f.tags or {}

    def get(*names):
        for n in names:
            try:
                if n in tags:
                    v = _first(tags[n])
                    if v:
                        return v.strip()
            except Exception:
                continue
        return None

    title = get("TIT2", "\xa9nam", "title", "TITLE")
    artist = get("TPE1", "\xa9ART", "artist", "ARTIST")
    bpm = get("TBPM", "tmpo", "bpm", "BPM")
    key = get("TKEY", "----:com.apple.iTunes:initialkey", "initialkey", "INITIALKEY", "key")
    comment = None
    for k in list(getattr(tags, "keys", lambda: [])()):
        if str(k).startswith("COMM") or k in ("\xa9cmt", "comment", "COMMENT"):
            comment = _first(tags[k])
            if comment:
                break
    if title:
        meta["title"] = title
    if artist:
        meta["artist"] = artist
    try:
        if bpm and 50 <= float(str(bpm).replace(",", ".")) <= 250:
            meta["bpm"] = float(str(bpm).replace(",", "."))
    except ValueError:
        pass
    k = camelot.parse(key) if key else None
    if not k and comment:
        k = camelot.parse(comment)
    meta["key"] = k or meta["key"]
    meta["comments"] = comment or ""
    try:
        meta["duration"] = float(f.info.length)
    except Exception:
        pass
    return meta


def scan(folders, cache_path=None):
    """Scan folders. Returns {'files': {path: meta}, 'folders': [tree nodes]}."""
    cache = {}
    if cache_path:
        try:
            with open(cache_path, encoding="utf-8") as fh:
                cache = json.load(fh)
        except (OSError, ValueError):
            cache = {}
    files, new_cache, roots, count = {}, {}, [], 0

    def walk(d):
        nonlocal count
        node = {"id": folder_id(d), "path": d, "name": os.path.basename(d.rstrip("/")) or d,
                "files": [], "children": []}
        try:
            entries = sorted(os.scandir(d), key=lambda e: e.name.lower())
        except OSError:
            return None
        for e in entries:
            if e.name.startswith("."):
                continue
            try:
                if e.is_dir(follow_symlinks=False):
                    child = walk(e.path)
                    if child:
                        node["children"].append(child)
                elif os.path.splitext(e.name)[1].lower() in AUDIO_EXT and count < MAX_FILES:
                    mtime = e.stat().st_mtime
                    c = cache.get(e.path)
                    meta = c["meta"] if c and c.get("mtime") == mtime else read_tags(e.path)
                    new_cache[e.path] = {"mtime": mtime, "meta": meta}
                    files[e.path] = meta
                    node["files"].append(e.path)
                    count += 1
            except OSError:
                continue
        return node if node["files"] or node["children"] else None

    for root in folders:
        root = os.path.expanduser(root)
        if os.path.isdir(root):
            n = walk(root)
            roots.append(n or {"id": folder_id(root), "path": root,
                               "name": os.path.basename(root.rstrip("/")) or root,
                               "files": [], "children": []})
    if cache_path:
        try:
            tmp = cache_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(new_cache, fh)
            os.replace(tmp, cache_path)
        except OSError:
            pass
    return {"files": files, "folders": roots}
