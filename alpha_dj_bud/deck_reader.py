"""Read the BPM a track is actually playing at in the DJ software (macOS
Accessibility). Written for djay; also tried on the other software, which show
the deck title and BPM the same way when their window exposes its texts.

djay shows, for each loaded deck, the track title and its current BPM (it
follows the tempo fader, SYNC and pitch). Every DJ uses a different layout,
so nothing here depends on positions or on a particular layout:

  1. collect every text and button of djay's window (except the track list);
  2. find the element showing the playing track's title (also when djay
     shortens it with "…");
  3. take the BPM value closest to that title on screen. djay shows deck BPMs
     with a decimal ("126.0"); whole numbers are only used as a last resort.

Read-only: nothing in djay is touched. Needs the Accessibility permission
for Alpha DJ Bud (System Settings > Privacy & Security > Accessibility).
"""
import math
import re
import sys
import time
import unicodedata

_DEC = re.compile(r"(?<![\d.,])(\d{2,3}[.,]\d{1,2})(?![\d])")
_INT = re.compile(r"^\s*(\d{2,3})\s*(?:bpm)?\s*$", re.I)
REFIND_EVERY = 10.0
SKIP_ROLES = ("AXTable", "AXOutline", "AXList", "AXBrowser")  # the library


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


def title_matches(text, want):
    """True if a djay text shows the title `want` (normalised)."""
    raw = str(text or "").strip()
    cut = raw.endswith(("…", "...")) or raw.endswith("..")
    t = norm(raw)
    if not t or not want:
        return False
    if t == want:
        return True
    if cut and len(t) >= 5 and want.startswith(t):
        return True
    return len(want) >= 4 and (t.startswith(want + " ") or t.endswith(" " + want))


def bpm_values(text):
    """BPM-like numbers in a text: (value, has_decimal)."""
    out = []
    for m in _DEC.finditer(str(text or "")):
        v = float(m.group(1).replace(",", "."))
        if 50 <= v <= 250:
            out.append((v, True))
    if not out:
        m = _INT.match(str(text or ""))
        if m and 50 <= int(m.group(1)) <= 250:
            out.append((float(m.group(1)), False))
    return out


def pick_bpm(items, title, expected=None):
    """items: [{'text': str, 'frame': (x, y, w, h)}]. Returns (bpm, frame of the
    title, info) for the playing track `title`, or (None, None, info)."""
    want = norm(title)
    titles = [it for it in items if title_matches(it["text"], want)]
    if not titles:
        return None, None, "title not found"
    best = None
    for t in titles:
        tx, ty, tw, th = t["frame"]
        for it in items:
            for v, dec in bpm_values(it["text"]):
                if expected and not (0.5 * expected <= v <= 2.0 * expected):
                    continue
                x, y, w, h = it["frame"]
                # gap between the two boxes (0 if they touch or overlap)
                dx = max(0.0, x - (tx + tw), tx - (x + w))
                dy = max(0.0, y - (ty + th), ty - (y + h))
                d = math.hypot(dx, dy)
                key = (0 if dec else 1, d)
                if best is None or key < best[0]:
                    best = (key, v, t["frame"])
    if best is None:
        return None, titles[0]["frame"], "title found, no BPM near it"
    return best[1], best[2], "ok"


class DeckReader:
    def __init__(self, bundles=("com.algoriddim.djay",)):
        self.bundles = tuple(b.lower() for b in bundles)
        self.AS = None
        self.found_at = 0.0
        self.elements = []   # [(element, attribute, frame)]
        self.window = None
        self.info = ""

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
            if (a.bundleIdentifier() or "").lower().startswith(self.bundles):
                pid = a.processIdentifier()
                break
        if not pid:
            raise DeckReaderError("notRunning")
        app = self.AS.AXUIElementCreateApplication(pid)
        windows = list(self.get(app, "AXWindows") or [])
        if not windows:
            raise DeckReaderError("notRunning")
        win = max(windows, key=lambda w: (self._frame(w) or (0, 0, 0, 0))[2])
        self.window = self._frame(win)
        elements, queue, seen = [], [win], 0
        while queue and seen < 8000:
            el = queue.pop(0)
            seen += 1
            role = self.get(el, "AXRole")
            if role in SKIP_ROLES:
                continue
            if role in ("AXStaticText", "AXTextField"):
                f = self._frame(el)
                if f:
                    elements.append((el, "AXValue", f))
            elif role in ("AXButton", "AXPopUpButton", "AXMenuButton"):
                f = self._frame(el)
                if f:
                    elements.append((el, "AXTitle", f))
                    elements.append((el, "AXDescription", f))
            queue.extend(self.get(el, "AXChildren") or [])
        self.elements = elements
        self.found_at = time.time()

    def _items(self):
        out = []
        for el, attr, f in self.elements:
            v = self.get(el, attr)
            if v:
                out.append({"text": str(v), "frame": f})
        return out

    def live_bpm(self, title, expected=None):
        """(deck index 0/1 or None, current BPM or None) for the deck playing `title`."""
        if not self.elements or time.time() - self.found_at > REFIND_EVERY:
            self._find()
        bpm, frame, info = pick_bpm(self._items(), title, expected)
        if bpm is None and time.time() - self.found_at > 1.5:
            self._find()  # a track was just loaded or the layout changed
            bpm, frame, info = pick_bpm(self._items(), title, expected)
        self.info = info
        deck = None
        if frame and self.window:
            wx, _, ww, _ = self.window
            deck = 0 if frame[0] + frame[2] / 2 < wx + ww / 2 else 1
        return deck, bpm
