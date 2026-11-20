"""Camelot Wheel helpers and harmonic-mixing rules used by Alpha DJ Bud."""
import re

# djay stores the key as an index 0..23 (major/relative-minor pairs going round
# the circle of fifths in chromatic order). Verified against Mixed In Key
# comments in a real djay library.
DJAY_KEY_INDEX_TO_CAMELOT = [
    "8B", "8A",    # C,  Am
    "3B", "3A",    # Db, Bbm
    "10B", "10A",  # D,  Bm
    "5B", "5A",    # Eb, Cm
    "12B", "12A",  # E,  C#m
    "7B", "7A",    # F,  Dm
    "2B", "2A",    # Gb, Ebm
    "9B", "9A",    # G,  Em
    "4B", "4A",    # Ab, Fm
    "11B", "11A",  # A,  F#m
    "6B", "6A",    # Bb, Gm
    "1B", "1A",    # B,  G#m
]

CAMELOT_TO_MUSICAL = {
    "1A": "G#m", "2A": "Ebm", "3A": "Bbm", "4A": "Fm", "5A": "Cm", "6A": "Gm",
    "7A": "Dm", "8A": "Am", "9A": "Em", "10A": "Bm", "11A": "F#m", "12A": "C#m",
    "1B": "B", "2B": "F#", "3B": "Db", "4B": "Ab", "5B": "Eb", "6B": "Bb",
    "7B": "F", "8B": "C", "9B": "G", "10B": "D", "11B": "A", "12B": "E",
}

_MUSICAL_TO_CAMELOT = {}
for _cam, _mus in CAMELOT_TO_MUSICAL.items():
    _MUSICAL_TO_CAMELOT[_mus.lower()] = _cam
_ENHARMONIC = {"c#": "db", "d#": "eb", "gb": "f#", "g#": "ab", "a#": "bb",
               "db": "c#", "eb": "d#", "ab": "g#", "bb": "a#", "f#": "gb"}

_CAMELOT_RE = re.compile(r"^\s*(1[0-2]|0?[1-9])\s*([ABab])\b")

# Relation labels, best first. Used for display and for learning.
REL_SAME = "stessa key"
REL_RELATIVE = "relativa A/B"
REL_UP = "+1"
REL_DOWN = "-1"
REL_TRITONE = "+6"


def from_djay_index(idx):
    if idx is None:
        return None
    try:
        idx = int(idx)
    except (TypeError, ValueError):
        return None
    if 0 <= idx < 24:
        return DJAY_KEY_INDEX_TO_CAMELOT[idx]
    return None


def parse(text):
    """Parse '3A', '03a', 'Bbm', 'A#m', 'C' ... into a Camelot code, else None."""
    if not text:
        return None
    m = _CAMELOT_RE.match(str(text))
    if m:
        return "%d%s" % (int(m.group(1)), m.group(2).upper())
    t = str(text).strip().replace("♭", "b").replace("♯", "#")
    t = re.sub(r"\s*(min(or)?|moll)$", "m", t, flags=re.I)
    t = re.sub(r"\s*(maj(or)?|dur)$", "", t, flags=re.I)
    t = t.lower()
    if t in _MUSICAL_TO_CAMELOT:
        return _MUSICAL_TO_CAMELOT[t]
    minor = t.endswith("m")
    root = t[:-1] if minor else t
    alt = _ENHARMONIC.get(root)
    if alt and (alt + ("m" if minor else "")) in _MUSICAL_TO_CAMELOT:
        return _MUSICAL_TO_CAMELOT[alt + ("m" if minor else "")]
    return None


def split(code):
    return int(code[:-1]), code[-1]


def _wrap(n):
    return (n - 1) % 12 + 1


def relation(current, candidate):
    """Return the relation label if `candidate` is a compatible key for `current`
    according to Alpha DJ Bud rules, else None.

    Rules (example with 3A playing):
      3A (same), 3B (relative), 2A / 4A (±1 same letter),
      9A / 9B (±6 on the wheel, both letters).
    """
    if not current or not candidate:
        return None
    n1, l1 = split(current)
    n2, l2 = split(candidate)
    if n1 == n2 and l1 == l2:
        return REL_SAME
    if n1 == n2:
        return REL_RELATIVE
    if l1 == l2 and n2 == _wrap(n1 + 1):
        return REL_UP
    if l1 == l2 and n2 == _wrap(n1 - 1):
        return REL_DOWN
    if n2 == _wrap(n1 + 6):
        return REL_TRITONE
    return None


def compatible_keys(current):
    """All Camelot codes compatible with `current`, in preference order."""
    if not current:
        return []
    n, l = split(current)
    other = "B" if l == "A" else "A"
    t = _wrap(n + 6)
    return ["%d%s" % (n, l), "%d%s" % (n, other), "%d%s" % (_wrap(n - 1), l),
            "%d%s" % (_wrap(n + 1), l), "%d%s" % (t, l), "%d%s" % (t, other)]


# Base score for each relation (0..1). Learning adjusts on top of this.
RELATION_BASE_SCORE = {
    REL_SAME: 1.0,
    REL_RELATIVE: 0.85,
    REL_UP: 0.85,
    REL_DOWN: 0.8,
    REL_TRITONE: 0.6,
}
