"""The DJ software Alpha DJ Bud can follow, and how to open each library."""
import os

SOFTWARE = {
    "djay": {
        "name": "djay Pro",
        "bundles": ("com.algoriddim.djay",),
        "hint": "~/Music/djay/djay Media Library.djayMediaLibrary",
    },
    "virtualdj": {
        "name": "VirtualDJ",
        "bundles": ("com.atomixproductions.virtualdj",),
        "hint": "~/Library/Application Support/VirtualDJ",
    },
    "rekordbox": {
        "name": "rekordbox",
        "bundles": ("com.pioneerdj.rekordboxdj", "com.pioneer.rekordbox"),
        "hint": "~/Library/Pioneer/rekordbox/master.db  (or an exported rekordbox.xml)",
    },
    "serato": {
        "name": "Serato DJ",
        "bundles": ("com.serato.",),
        "hint": "~/Music/_Serato_",
    },
    "traktor": {
        "name": "Traktor Pro",
        "bundles": ("com.native-instruments.traktor", "com.native-instruments.Traktor"),
        "hint": "~/Documents/Native Instruments/Traktor 3.x.x/collection.nml",
    },
}

ORDER = ["djay", "virtualdj", "rekordbox", "serato", "traktor"]


def name(sw):
    return SOFTWARE.get(sw, SOFTWARE["djay"])["name"]


def bundles(sw):
    return SOFTWARE.get(sw, SOFTWARE["djay"])["bundles"]


def find(sw, explicit=None):
    """Path of the software's library on this Mac, or None."""
    if sw == "virtualdj":
        from .virtualdj_library import find_home
        return find_home(explicit)
    if sw == "serato":
        from .serato_library import find_home
        return find_home(explicit)
    if sw == "traktor":
        from .traktor_library import find_collection
        return find_collection(explicit)
    if sw == "rekordbox":
        from .rekordbox_library import find_database
        if explicit and os.path.expanduser(explicit).lower().endswith(".xml"):
            p = os.path.expanduser(explicit)
            return p if os.path.isfile(p) else None
        return find_database(explicit)
    from .djay_library import find_database
    return find_database(explicit)


def open_library(sw, path, key_from_comments=False, broadcast_port=None):
    if sw == "virtualdj":
        from .virtualdj_library import VirtualDJLibrary
        return VirtualDJLibrary(path, key_from_comments)
    if sw == "serato":
        from .serato_library import SeratoLibrary
        return SeratoLibrary(path, key_from_comments)
    if sw == "traktor":
        from .traktor_library import TraktorLibrary, BROADCAST_PORT
        return TraktorLibrary(path, key_from_comments, broadcast_port or BROADCAST_PORT)
    if sw == "rekordbox":
        from .rekordbox_library import open_library as rb
        return rb(path, key_from_comments)
    from .djay_library import DjayLibrary
    return DjayLibrary(path, key_from_comments)
