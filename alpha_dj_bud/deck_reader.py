"""Read the BPM a track is actually playing at in djay (macOS Accessibility).

djay shows, for each deck, the track title and the current BPM (the BPM
button in the mixer, which follows the tempo fader, SYNC and pitch). We
find the deck whose title matches the playing track and read its BPM, so
suggestions follow the tempo you set while mixing.

Read-only: nothing in djay is touched. Needs the Accessibility permission
for Alpha DJ Bud (System Settings > Privacy & Security > Accessibility).
"""
import re
import sys
import time
import unicodedata

_NUM = re.compile(r"^\s*(\d{2,3}(?:[.,]\d{1,2})?)\s*$")
_PCT = re.compile(r"^\s*([+-]?\d+(?:[.,]\d+)?)\s*%\s*$")
REFIND_EVERY = 15.0


class DeckReaderError(Exception):
    """`code`: notMac, noPyobjc, noPermission, notRunning."""

    def __init__(self, code, detail=""):
        super().__init__(code)
        self.code = code
        self.detail = detail


def norm(s):
    s = unicodedata.normalize("NFKD", str(s or ""))
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def parse_bpm(text):
    m = _NUM.match(str(text or ""))
    if not m:
        return None
    v = float(m.group(1).replace(",", "."))
    return v if 50 <= v <= 250 else None


def pick_deck_bpm(decks, title):
    """decks: [{'texts': [...], 'bpms': [...], 'pitch': ...}] -> (deck index, bpm) for
    the deck showing `title`, or (None, None)."""
    want = norm(title)
    if not want:
        return None, None
    for i, d in enumerate(decks):
        texts = [norm(t) for t in d["texts"]]
        if any(t == want or (len(want) > 3 and t.startswith(want)) for t in texts):
            bpm = next((b for b in d["bpms"] if b), None)
            return i, bpm
    return None, None


class DeckReader:
    def __init__(self):
        self.AS = None
        self.found_at = 0.0
        self.decks = []  # [{'texts': [els], 'bpms': [els], 'pct': [els]}] left -> right

    def _imports(self):
        if sys.platform != "darwin":
            raise DeckReaderError("notMac")
        if self.AS is None:
            try:
                import ApplicationServices as AS
                from AppKit import NSWorkspace
            except ImportError as e:
                raise DeckReaderError("noPyobjc", str(e))
            self.AS, self.NSWorkspace = AS, NSWorkspace

    def get(self, el, attr):
        err, val = self.AS.AXUIElementCopyAttributeValue(el, attr, None)
        return val if err == 0 else None

    def _frame(self, el):
        pos, size = self.get(el, "AXPosition"), self.get(el, "AXSize")
        try:
            _, p = self.AS.AXValueGetValue(pos, self.AS.kAXValueCGPointType, None)
            _, s = self.AS.AXValueGetValue(size, self.AS.kAXValueCGSizeType, None)
            return (p.x, p.y, s.width, s.height)
        except Exception:
            return None

    def permission(self, prompt=False):
        self._imports()
        if prompt:
            return bool(self.AS.AXIsProcessTrustedWithOptions({self.AS.kAXTrustedCheckOptionPrompt: True}))
        return bool(self.AS.AXIsProcessTrusted())

    def _find(self):
        self._imports()
        if not self.permission():
            raise DeckReaderError("noPermission")
        pid = None
        for a in self.NSWorkspace.sharedWorkspace().runningApplications():
            if (a.bundleIdentifier() or "").startswith("com.algoriddim.djay"):
                pid = a.processIdentifier()
                break
        if not pid:
            raise DeckReaderError("notRunning")
        app = self.AS.AXUIElementCreateApplication(pid)
        windows = list(self.get(app, "AXWindows") or [])
        if not windows:
            raise DeckReaderError("notRunning")
        win = max(windows, key=lambda w: (self._frame(w) or (0, 0, 0, 0))[2])
        wx, wy, ww, wh = self._frame(win) or (0, 0, 1, 1)
        cx = wx + ww / 2
        halves = [{"texts": [], "bpms": [], "pct": []}, {"texts": [], "bpms": [], "pct": []}]
        queue, seen = [win], 0
        while queue and seen < 5000:
            el = queue.pop(0)
            seen += 1
            role = self.get(el, "AXRole")
            if role in ("AXStaticText", "AXButton"):
                f = self._frame(el)
                if f and f[1] - wy < wh * 0.6:  # decks are above the library
                    side = halves[0 if f[0] + f[2] / 2 < cx else 1]
                    if role == "AXStaticText":
                        side["texts"].append((f[1], el))
                    else:
                        side["bpms"].append((f[1], el))
            if role not in ("AXTable", "AXOutline"):  # skip the library list
                queue.extend(self.get(el, "AXChildren") or [])
        for h in halves:
            h["texts"] = [e for _, e in sorted(h["texts"], key=lambda x: x[0])]
            h["bpms"] = [e for _, e in sorted(h["bpms"], key=lambda x: x[0])]
        self.decks = halves
        self.found_at = time.time()

    def read(self):
        """[{'texts': [str], 'bpms': [float], 'pitch': float|None}] for deck 1 and 2."""
        if not self.decks or time.time() - self.found_at > REFIND_EVERY:
            self._find()
        out = []
        for h in self.decks:
            texts = [str(self.get(e, "AXValue") or "") for e in h["texts"]]
            titles = [str(self.get(e, "AXTitle") or "") for e in h["bpms"]]
            out.append({
                "texts": [t for t in texts if t],
                "bpms": [b for b in (parse_bpm(t) for t in titles) if b],
                "pitch": next((float(m.group(1).replace(",", ".")) for m in
                               (_PCT.match(t) for t in titles) if m), None),
            })
        return out

    def live_bpm(self, title):
        """(deck index, current BPM) of the deck playing `title`."""
        decks = self.read()
        i, bpm = pick_deck_bpm(decks, title)
        if i is None and time.time() - self.found_at > 2:
            self._find()  # layout may have changed: rescan once
            decks = self.read()
            i, bpm = pick_deck_bpm(decks, title)
        return i, bpm
