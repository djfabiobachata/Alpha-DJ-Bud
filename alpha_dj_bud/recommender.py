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

    out, extra = [], []   # extra: outside the tolerance, only for the up/down picks
    reach = max(tol, MAX_BPM_STEP)
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
        outside = abs(d) > tol + 0.05
        if outside and (abs(d) > reach + 0.05 or abs(d) < MIN_BPM_STEP - 0.05):
            stats["bpm"] += 1
            continue
        mine = artists.artist_set(t.artist, t.title)
        if any(artists.shares_artist(mine, b) for b in blocked_artists):
            stats["artist"] += 1
            continue

        key_s = camelot.RELATION_BASE_SCORE[rel]
        # BPM closeness counts less than the key: the whole ± range stays useful
        bpm_s = 1.0 - 0.5 * min(1.0, abs(d) / max(tol, abs(d), 0.5))
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
        (extra if outside else out).append(item)

    out.sort(key=lambda x: (-x["score"], abs(x["bpmDelta"]), x["title"].lower()))
    # one track per artist at the top; the artist's other tracks follow later
    first, later, seen = [], [], []
    enough = max(int(opts["limit"]), 5)
    for i, item in enumerate(out):
        if len(first) >= enough:
            # the visible list is complete: the rest only feeds the up/down
            # picks, which don't depend on this order (keeps big libraries fast)
            later.extend(out[i:])
            break
        mine = artists.artist_set(item["artist"], item["title"])
        if mine and any(artists.shares_artist(mine, a) for a in seen):
            later.append(item)
        else:
            first.append(item)
            if mine:
                seen.append(mine)
    out = first + later
    if extra:
        stats["bpm"] += len(extra)
    out = _bpm_picks(out, extra)
    limit = int(opts["limit"])
    head = out[:limit]
    # an up/down pick always shows, even when the list is short or long
    for x in out[limit:]:
        if x.get("bpmTag"):
            head.insert(min(len(head), 5), x)
    return head[: max(limit, len(head))], stats


MIN_BPM_STEP = 4.0   # an up / down pick moves the BPM by at least 4 BPM...
MAX_BPM_STEP = 10.0  # ...and at most 10 BPM, in every genre (not the genre's tolerance)


def _bpm_picks(items, extra=()):
    """Keep the 3 best suggestions on top, then the track to go UP (4th) and
    to go DOWN (5th) in BPM. These two ignore the genre's BPM tolerance: they
    are chosen between 4 and 10 BPM away, the closest to 4 first (4, then 5,
    ...), best score on a tie, among the tracks not already in the top 3."""
    top, rest = items[:3], items[3:]
    pool = rest + list(extra)

    def pick(sign):
        c = [x for x in pool if MIN_BPM_STEP - 0.05 <= sign * x["bpmDelta"] <= MAX_BPM_STEP + 0.05]
        c.sort(key=lambda x: (round(abs(x["bpmDelta"])), -x["score"]))
        return c[0] if c else None

    picks = []
    for x, tag in ((pick(1), "up"), (pick(-1), "down")):
        if x is not None:
            x["bpmTag"] = tag
            picks.append(x)
    return top + picks + [x for x in rest if x not in picks]
