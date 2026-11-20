"""Artist name normalisation, so that 'Romeo Santos', 'Romeo Santos ft. Usher'
and 'Prince Royce x Romeo Santos' are all recognised as sharing an artist."""
import re
import unicodedata

_SEPARATORS = re.compile(
    r"\s*(?:,|&|\+|/|;|\bfeat\.?|\bft\.?|\bfeaturing\b|\bwith\b|\bcon\b|\bvs\.?|\bx\b|\by\b|\band\b|\be\b)\s*",
    re.I)
_FEAT_IN_TITLE = re.compile(r"[\(\[]\s*(?:feat\.?|ft\.?|featuring|con|with)\s+([^\)\]]+)[\)\]]", re.I)
_NOISE = re.compile(r"\b(official|oficial|music|records|vevo|topic|tv)\b", re.I)


def _plain(s):
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = re.sub(r"[^\w\s]", " ", s.lower())
    s = _NOISE.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()


def artist_set(artist, title=""):
    """Return the set of normalised individual artist names of a track."""
    names = set()
    for part in _SEPARATORS.split(artist or ""):
        p = _plain(part)
        if len(p) >= 2:
            names.add(p)
    for m in _FEAT_IN_TITLE.finditer(title or ""):
        for part in _SEPARATORS.split(m.group(1)):
            p = _plain(part)
            if len(p) >= 2:
                names.add(p)
    return names


def shares_artist(a, b):
    """True if the two artist sets have a performer in common."""
    if not a or not b:
        return False
    if a & b:
        return True
    for x in a:
        for y in b:
            short, long_ = (x, y) if len(x) <= len(y) else (y, x)
            if len(short) >= 5 and re.search(r"\b%s\b" % re.escape(short), long_):
                return True
    return False
