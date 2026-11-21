"""Next-track recommendation: harmonic + tempo rules, artist rule, learning."""
from . import artists, camelot

DEFAULTS = {
    "bpmTolerance": 4.0,       # ± BPM (fallback)
    "bpmToleranceByGenre": {"bachata": 4.0, "salsa": 6.0, "zouk": 10.0},
    "halfDouble": False,       # also accept half/double tempo matches
    "artistWindow": 1,         # no shared artist with the last N tracks
    "avoidReplays": True,      # skip tracks already played in this set
    "includeTritone": True,    # +6 rule (3A -> 9A / 9B)
    "limit": 15,
    "variety": 50,             # 0 = always the best match, 100 = maximum rotation
}


def bpm_delta(a, b, half_double=False):
    """Signed BPM difference b - a, with optional half/double tempo matching."""
    best = b - a
    if half_double:
        for alt in (b * 2, b / 2):
            if abs(alt - a) < abs(best):
                best = alt - a
    return best


def recommend(library, current, pool_ids, played_ids, brain, genre, settings, hidden=(), set_id=None):
    """Return (suggestions, stats). Each suggestion is a dict for the UI."""
    opts = dict(DEFAULTS)
    opts.update(settings or {})
    by_genre = dict(DEFAULTS["bpmToleranceByGenre"])
    by_genre.update(opts.get("bpmToleranceByGenre") or {})
    tol = float(by_genre.get(genre, opts["bpmTolerance"]))
    stats = {"pool": len(pool_ids), "noData": 0, "key": 0, "bpm": 0, "artist": 0, "played": 0}
    if current is None:
        return [], stats

    recent = [library.get(t) for t in played_ids[-int(opts["artistWindow"]):]] if opts["artistWindow"] else []
    blocked_artists = [artists.artist_set(current.artist, current.title)]
    blocked_artists += [artists.artist_set(t.artist, t.title) for t in recent if t]
    played = set(played_ids)
    hidden = set(hidden)
    conf = brain.confidence(genre) if brain else 0.0
    w_learn = 0.35 * conf
    variety = max(0.0, min(1.0, float(opts.get("variety", 50)) / 100.0))
    fresh = brain.freshness(genre, current, set_id) if (brain and variety) else {}

    out = []
    for tid in pool_ids:
        if tid == current.id or tid in hidden:
            continue
        t = library.get(tid)
        if t is None:
            continue
        if opts["avoidReplays"] and tid in played:
            stats["played"] += 1
            continue
        if not t.key or not t.bpm or not current.key or not current.bpm:
            stats["noData"] += 1
            continue
        rel = camelot.relation(current.key, t.key)
        if rel is None or (rel == camelot.REL_TRITONE and not opts["includeTritone"]):
            stats["key"] += 1
            continue
        d = bpm_delta(current.bpm, t.bpm, opts["halfDouble"])
        if abs(d) > tol + 0.05:
            stats["bpm"] += 1
            continue
        mine = artists.artist_set(t.artist, t.title)
        if any(artists.shares_artist(mine, b) for b in blocked_artists):
            stats["artist"] += 1
            continue

        key_s = camelot.RELATION_BASE_SCORE[rel]
        # BPM closeness counts less than the key: the whole ± range stays useful
        bpm_s = 1.0 - 0.5 * min(1.0, abs(d) / max(tol, 0.5))
        learned, reasons = brain.score(genre, current, t, rel) if brain else (0.5, [])
        score = (1 - w_learn) * (0.75 * key_s + 0.25 * bpm_s) + w_learn * learned
        if variety:
            jit = brain.jitter(set_id, current.id, tid) if brain else 0.5
            score = score * (1 - 0.25 * variety) + 0.25 * variety * jit
            score -= 0.35 * variety * fresh.get(tid, 0.0)
            score = max(0.0, min(1.0, score))
        item = t.to_dict()
        item.update({
            "relation": rel,
            "bpmDelta": round(d, 1),
            "score": round(score * 100),
            "reasons": reasons,
        })
        out.append(item)

    out.sort(key=lambda x: (-x["score"], abs(x["bpmDelta"]), x["title"].lower()))
    # one track per artist at the top; the artist's other tracks follow later
    first, later, seen = [], [], []
    for item in out:
        mine = artists.artist_set(item["artist"], item["title"])
        if mine and any(artists.shares_artist(mine, a) for a in seen):
            later.append(item)
        else:
            first.append(item)
            if mine:
                seen.append(mine)
    out = first + later
    out = _bpm_picks(out, tol)
    return out[: int(opts["limit"])], stats


def _bpm_picks(items, tol):
    """Keep the 3 best suggestions on top, then put the best track to go UP
    (position 4) and the best to go DOWN (position 5) in BPM, chosen among
    the others, so the list also covers the whole BPM range."""
    step = max(1.0, 0.4 * tol)
    top, rest = items[:3], items[3:]
    up = next((x for x in rest if x["bpmDelta"] >= step), None)
    down = next((x for x in rest if x["bpmDelta"] <= -step), None)
    picks = []
    for x, tag in ((up, "up"), (down, "down")):
        if x is not None:
            x["bpmTag"] = tag
            picks.append(x)
    return top + picks + [x for x in rest if x not in picks]
