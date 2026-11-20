"""Local preference learning ("Bud brain").

Everything stays on the Mac, in a JSON file. For each genre the brain counts:
  * transitions you actually made (track A -> track B)
  * how often each track gets played in your sets
  * which Camelot relations and BPM directions you prefer
  * suggestions you were shown and never picked (soft penalty)
  * thumbs up / thumbs down you give in the app
From these it produces a 0..1 preference score that the recommender blends
with the harmonic/BPM score. The more sets you play, the more weight it gets.
"""
import hashlib
import json
import math
import time
import os
import tempfile
import threading

from . import camelot

BRAIN_VERSION = 1


def _empty_genre():
    return {
        "pairs": {},        # "a>b": count
        "plays": {},        # track_id: count
        "relations": {},    # relation label: count
        "bpm_dir": {"up": 0, "same": 0, "down": 0},
        "ignored": {},      # track_id: score (decays when played)
        "likes": {},        # track_id: +n / -n
        "followed": 0,      # transitions that came from a suggestion
        "transitions": 0,
        "sets": 0,
        "imported_sessions": [],
        "log": [],          # recent transitions [from, to, unix time, set id]
        "shownAfter": {},   # from_id: [unix time, set id, [top-5 ids shown]]
    }

LOG_MAX = 4000
DAY = 86400.0


class Brain:
    def __init__(self, path):
        self.path = path
        self.lock = threading.RLock()
        self.data = {"version": BRAIN_VERSION, "genres": {}}
        self._load()

    # -- persistence ---------------------------------------------------------
    def _load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                d = json.load(f)
            if isinstance(d, dict) and "genres" in d:
                self.data = d
                for gd in d["genres"].values():  # migrate old relation labels
                    rels = gd.get("relations") or {}
                    for old, new in camelot.LEGACY_RELATIONS.items():
                        if old in rels:
                            rels[new] = rels.get(new, 0) + rels.pop(old)
        except (OSError, ValueError):
            pass

    def save(self):
        with self.lock:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=os.path.dirname(self.path), suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False)
            os.replace(tmp, self.path)

    def g(self, genre):
        with self.lock:
            gd = self.data["genres"].setdefault(genre, _empty_genre())
            for k, v in _empty_genre().items():
                gd.setdefault(k, v)
            return gd

    # -- learning ------------------------------------------------------------
    def observe(self, genre, prev, new, shown=None, save=True, when=None, set_id=None):
        """Record that `new` (Track) was played after `prev` (Track or None).
        `shown` is the list of suggested track ids visible at that moment."""
        when = when or time.time()
        with self.lock:
            gd = self.g(genre)
            gd["log"].append([prev.id if prev else None, new.id, when, set_id])
            if len(gd["log"]) > LOG_MAX:
                del gd["log"][: len(gd["log"]) - LOG_MAX]
            if prev is not None and shown:
                gd["shownAfter"][prev.id] = [when, set_id, list(shown[:5])]
            gd["plays"][new.id] = gd["plays"].get(new.id, 0) + 1
            if new.id in gd["ignored"]:
                gd["ignored"][new.id] = gd["ignored"][new.id] * 0.5
            if prev is not None and prev.id != new.id:
                k = "%s>%s" % (prev.id, new.id)
                gd["pairs"][k] = gd["pairs"].get(k, 0) + 1
                gd["transitions"] += 1
                rel = camelot.relation(prev.key, new.key)
                if rel:
                    gd["relations"][rel] = gd["relations"].get(rel, 0) + 1
                if prev.bpm and new.bpm:
                    d = new.bpm - prev.bpm
                    bucket = "up" if d > 0.75 else "down" if d < -0.75 else "same"
                    gd["bpm_dir"][bucket] += 1
                if shown:
                    if new.id in shown:
                        gd["followed"] += 1
                    for tid in shown[:5]:
                        if tid != new.id:
                            gd["ignored"][tid] = gd["ignored"].get(tid, 0) + 1
            if save:
                self.save()

    def feedback(self, genre, track_id, value):
        with self.lock:
            gd = self.g(genre)
            gd["likes"][track_id] = max(-3, min(3, gd["likes"].get(track_id, 0) + value))
            self.save()

    def end_set(self, genre):
        with self.lock:
            self.g(genre)["sets"] += 1
            self.save()

    def import_sessions(self, genre, sessions, library, pool_ids):
        """Learn from djay history sessions whose tracks are mostly in the pool."""
        pool = set(pool_ids)
        added = 0
        with self.lock:
            gd = self.g(genre)
            done = set(gd["imported_sessions"])
            for s in sessions:
                if s["id"] in done or len(s["tracks"]) < 2:
                    continue
                in_pool = sum(1 for t in s["tracks"] if t in pool)
                if in_pool / len(s["tracks"]) < 0.6:
                    continue
                prev = None
                times = s.get("times") or [None] * len(s["tracks"])
                for tid, when in zip(s["tracks"], times):
                    t = library.get(tid)
                    if t is None:
                        prev = None
                        continue
                    self.observe(genre, prev, t, save=False, when=when, set_id="djay:" + s["id"])
                    prev = t
                gd["imported_sessions"].append(s["id"])
                added += 1
            self.save()
        return added

    # -- scoring -------------------------------------------------------------
    def confidence(self, genre):
        """0..1: how much the learned score should count."""
        return min(1.0, self.g(genre)["transitions"] / 40.0)

    def score(self, genre, current, cand, rel):
        """Learned preference for playing `cand` after `current` (0..1) and
        a list of reason codes (translated by the UI)."""
        gd = self.g(genre)
        reasons = []
        s = 0.0
        pair = gd["pairs"].get("%s>%s" % (current.id, cand.id), 0) if current else 0
        if pair:
            reasons.append({"code": "pair", "n": pair})
        s += 0.35 * (1 - math.exp(-pair))

        plays = gd["plays"].get(cand.id, 0)
        maxp = max(gd["plays"].values()) if gd["plays"] else 0
        if maxp:
            s += 0.2 * math.log1p(plays) / math.log1p(maxp)
            if plays >= 3 and plays >= 0.5 * maxp:
                reasons.append({"code": "topPlayed"})

        rels = gd["relations"]
        if rel and rels:
            s += 0.15 * rels.get(rel, 0) / max(rels.values())

        if current and current.bpm and cand.bpm:
            dirs = gd["bpm_dir"]
            tot = sum(dirs.values())
            if tot:
                d = cand.bpm - current.bpm
                bucket = "up" if d > 0.75 else "down" if d < -0.75 else "same"
                s += 0.15 * dirs[bucket] / max(dirs.values())

        like = gd["likes"].get(cand.id, 0)
        s += 0.15 * (like / 3.0)
        if like > 0:
            reasons.append({"code": "liked"})
        ign = gd["ignored"].get(cand.id, 0)
        s -= min(0.25, 0.03 * ign)
        return max(0.0, min(1.0, s)), reasons

    def freshness(self, genre, current, set_id, now=None):
        """Penalties (0..1) for candidates that were recently used after
        `current` in OTHER sets, so the same hit doesn't always get the same
        follow-ups night after night. Returns {track_id: penalty}."""
        now = now or time.time()
        gd = self.g(genre)
        pen = {}

        def add(tid, v):
            pen[tid] = min(1.0, pen.get(tid, 0.0) + v)

        horizon = now - 21 * DAY
        for a, b, t, sid in reversed(gd["log"]):
            if t < horizon:
                break
            if sid == set_id:
                continue
            days = (now - t) / DAY
            if a == current.id:            # you went current -> b recently
                add(b, 1.0 * math.exp(-days / 5))
            else:                          # b was played in a recent set
                add(b, 0.25 * math.exp(-days / 3))
        sa = gd["shownAfter"].get(current.id)
        if sa and sa[1] != set_id and sa[0] >= horizon:
            days = (now - sa[0]) / DAY
            for tid in sa[2]:
                add(tid, 0.5 * math.exp(-days / 5))
        return pen

    @staticmethod
    def jitter(set_id, a, b):
        """Stable pseudo-random 0..1 per (set, current, candidate): the list
        doesn't jump around during a set, but changes from night to night."""
        h = hashlib.md5(("%s|%s|%s" % (set_id, a, b)).encode()).digest()
        return int.from_bytes(h[:4], "big") / 2 ** 32

    def stats(self, genre):
        gd = self.g(genre)
        t = gd["transitions"]
        return {
            "transitions": t,
            "sets": gd["sets"],
            "followedPct": round(100.0 * gd["followed"] / t) if t else 0,
            "tracksKnown": len(gd["plays"]),
            "confidence": round(self.confidence(genre) * 100),
            "favouriteRelation": max(gd["relations"], key=gd["relations"].get) if gd["relations"] else None,
        }
