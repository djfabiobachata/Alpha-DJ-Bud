"""Watch djay Pro's mixer (macOS Accessibility) to know which deck is ON AIR.

djay's window exposes its mixer controls as accessibility sliders: one tall
volume (line) fader per deck in the middle of the window, and the
"Crossfader". A deck is audible when its line fader is up and the crossfader
lets it through. When a deck goes from silent to audible (you raise its
fader), it becomes the playing deck. Pre-listening with the fader at zero
never changes anything.

The track loaded on each deck is read from the deck header text in djay's
window when possible (matched against the library), otherwise from djay's
history (which records the deck number).

Needs: pyobjc-framework-ApplicationServices and permission in
System Settings > Privacy & Security > Accessibility.
"""
import re
import sys
import time
import unicodedata

AUDIBLE = 0.18       # effective gain above which a deck counts as audible
REFIND_EVERY = 20.0  # seconds between full rescans of djay's window


def _norm(s):
    s = unicodedata.normalize("NFKD", str(s or ""))
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


class DeckMonitorError(Exception):
    """`code`: notMac, noPyobjc, noPermission, notRunning, noMixer."""

    def __init__(self, code, detail=""):
        super().__init__(code)
        self.code = code
        self.detail = detail


class DeckMonitor:
    def __init__(self):
        self.AS = None
        self.pid = None
        self.app = None
        self.faders = []        # [(element, deck_index)] left -> right
        self.crossfader = None
        self.headers = {0: [], 1: []}   # static texts in each deck header
        self.found_at = 0.0
        self.audible = {0: False, 1: False}
        self.on_air = None
        self.last = {}

    # -- accessibility helpers -----------------------------------------------
    def _imports(self):
        if sys.platform != "darwin":
            raise DeckMonitorError("notMac")
        if self.AS is None:
            try:
                import ApplicationServices as AS
                from AppKit import NSWorkspace
            except ImportError as e:
                raise DeckMonitorError("noPyobjc", str(e))
            self.AS, self.NSWorkspace = AS, NSWorkspace

    def get(self, el, attr):
        err, val = self.AS.AXUIElementCopyAttributeValue(el, attr, None)
        return val if err == 0 else None

    def _frame(self, el):
        pos, size = self.get(el, "AXPosition"), self.get(el, "AXSize")
        if pos is None or size is None:
            return None
        try:
            ok1, p = self.AS.AXValueGetValue(pos, self.AS.kAXValueCGPointType, None)
            ok2, s = self.AS.AXValueGetValue(size, self.AS.kAXValueCGSizeType, None)
            return (p.x, p.y, s.width, s.height)
        except Exception:
            return None

    def _num(self, el, attr):
        v = self.get(el, attr)
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    def _norm_value(self, el):
        v, lo, hi = self._num(el, "AXValue"), self._num(el, "AXMinValue"), self._num(el, "AXMaxValue")
        if v is None:
            return None
        if lo is None or hi is None or hi <= lo:
            lo, hi = (0.0, 1.0) if v <= 1.0 else (0.0, 100.0)
        return max(0.0, min(1.0, (v - lo) / (hi - lo)))

    # -- discovery -----------------------------------------------------------
    def permission(self, prompt=False):
        self._imports()
        if prompt:
            return bool(self.AS.AXIsProcessTrustedWithOptions({self.AS.kAXTrustedCheckOptionPrompt: True}))
        return bool(self.AS.AXIsProcessTrusted())

    def _find(self):
        self._imports()
        if not self.permission():
            raise DeckMonitorError("noPermission")
        pid = None
        for a in self.NSWorkspace.sharedWorkspace().runningApplications():
            if (a.bundleIdentifier() or "").startswith("com.algoriddim.djay"):
                pid = a.processIdentifier()
                break
        if not pid:
            raise DeckMonitorError("notRunning")
        self.pid = pid
        self.app = self.AS.AXUIElementCreateApplication(pid)
        windows = list(self.get(self.app, "AXWindows") or [])
        if not windows:
            raise DeckMonitorError("notRunning")
        win = max(windows, key=lambda w: (self._frame(w) or (0, 0, 0, 0))[2])
        wf = self._frame(win) or (0, 0, 1, 1)
        wx, wy, ww, wh = wf
        sliders, texts = [], []
        queue, seen = [win], 0
        while queue and seen < 6000:
            el = queue.pop(0)
            seen += 1
            role = self.get(el, "AXRole")
            if role == "AXSlider":
                f = self._frame(el)
                if f:
                    sliders.append((el, f, str(self.get(el, "AXTitle") or self.get(el, "AXDescription") or "")))
            elif role == "AXStaticText":
                f = self._frame(el)
                if f and f[1] - wy < wh * 0.2:   # deck headers sit at the top
                    texts.append((el, f))
            queue.extend(self.get(el, "AXChildren") or [])

        cx = wx + ww / 2
        xf = [s for s in sliders if "crossfader" in s[2].lower()]
        if not xf:  # widest horizontal slider near the centre
            horiz = [s for s in sliders if s[1][2] > 2 * s[1][3] and abs(s[1][0] + s[1][2] / 2 - cx) < ww * 0.15]
            xf = sorted(horiz, key=lambda s: -s[1][2])[:1]
        self.crossfader = xf[0][0] if xf else None

        # line faders: tall sliders (height ≥ 1.6 × width), the pair nearest the centre
        tall = [s for s in sliders if s[1][3] >= 1.6 * s[1][2] and s[1][3] > 60]
        left = sorted([s for s in tall if s[1][0] + s[1][2] / 2 < cx], key=lambda s: cx - s[1][0])
        right = sorted([s for s in tall if s[1][0] + s[1][2] / 2 >= cx], key=lambda s: s[1][0] - cx)
        if not left or not right:
            raise DeckMonitorError("noMixer")
        self.faders = [(left[0][0], 0), (right[0][0], 1)]
        self.headers = {0: [t[0] for t in texts if t[1][0] + t[1][2] / 2 < cx],
                        1: [t[0] for t in texts if t[1][0] + t[1][2] / 2 >= cx]}
        self.found_at = time.time()

    # -- polling ---------------------------------------------------------------
    def read(self):
        """Return {'gains': {0: g, 1: g}, 'titles': {0: [...], 1: [...]}}."""
        if not self.faders or time.time() - self.found_at > REFIND_EVERY:
            self._find()
        vols = {}
        for el, deck in self.faders:
            v = self._norm_value(el)
            if v is None:  # stale element: rescan once
                self._find()
                return self.read()
            vols[deck] = v
        x = self._norm_value(self.crossfader) if self.crossfader is not None else 0.5
        x = 0.5 if x is None else x
        gains = {0: vols[0] * min(1.0, 2 * (1 - x)), 1: vols[1] * min(1.0, 2 * x)}
        titles = {d: [str(self.get(t, "AXValue") or "") for t in els] for d, els in self.headers.items()}
        self.last = {"volumes": vols, "crossfader": x, "gains": gains}
        return {"gains": gains, "titles": titles}

    def step(self):
        """Poll once. Returns the deck index that just went ON AIR, or None."""
        r = self.read()
        changed = None
        for d in (0, 1):
            now = r["gains"][d] > AUDIBLE
            if now and not self.audible[d]:
                changed = d
            self.audible[d] = now
        if changed is None and self.on_air is not None and not self.audible[self.on_air]:
            others = [d for d in (0, 1) if self.audible[d]]
            if others:
                changed = others[0]
        if changed is not None:
            self.on_air = changed
        self.titles = r["titles"]
        return changed


def match_title(library, texts, prefer=()):
    """Find the library track whose djay title appears in the deck header."""
    wanted = [_norm(t) for t in texts if t and len(t) > 1]
    if not wanted or library is None:
        return None
    best = None
    for tid, tr in library.tracks.items():
        n = _norm(getattr(tr, "djay_title", tr.title))
        if n and n in wanted:
            if tid in prefer:
                return tid
            best = best or tid
    return best
