"""Load a track onto a djay Pro deck (macOS only).

djay has no public API, so this does what a DJ would do by hand, through the
macOS Accessibility API:
  1. write the track title into djay's library search field,
  2. select the matching row in the search results,
  3. send djay's own shortcut: Cmd+Left = Deck 1, Cmd+Right = Deck 2.
Tested on djay Pro 5 for Mac. The app that runs Alpha DJ Bud needs permission
in System Settings > Privacy & Security > Accessibility.
"""
import re
import sys
import time
import unicodedata

KEY_LEFT, KEY_RIGHT = 123, 124


class LoadError(Exception):
    """`code` is translated by the UI (load.<code>)."""

    def __init__(self, code, detail=""):
        super().__init__(code)
        self.code = code
        self.detail = detail


def _norm(s):
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def _ax():
    if sys.platform != "darwin":
        raise LoadError("notMac")
    try:
        import ApplicationServices as AS  # pyobjc-framework-ApplicationServices
        import Quartz
        from AppKit import NSWorkspace
    except ImportError as e:
        raise LoadError("noPyobjc", str(e))
    return AS, Quartz, NSWorkspace


def accessibility_ok(prompt=False):
    try:
        AS, _, _ = _ax()
    except LoadError:
        return False
    if prompt:
        return bool(AS.AXIsProcessTrustedWithOptions({AS.kAXTrustedCheckOptionPrompt: True}))
    return bool(AS.AXIsProcessTrusted())


def _djay_pid(NSWorkspace):
    for app in NSWorkspace.sharedWorkspace().runningApplications():
        bid = app.bundleIdentifier() or ""
        if bid.startswith("com.algoriddim.djay"):
            return app.processIdentifier()
    return None


class _Tree:
    def __init__(self, AS, pid):
        self.AS = AS
        self.app = AS.AXUIElementCreateApplication(pid)

    def get(self, el, attr):
        err, val = self.AS.AXUIElementCopyAttributeValue(el, attr, None)
        return val if err == 0 else None

    def set(self, el, attr, value):
        return self.AS.AXUIElementSetAttributeValue(el, attr, value) == 0

    def walk(self, root=None, limit=8000):
        """Breadth-first walk of the accessibility tree."""
        queue = [root] if root is not None else list(self.get(self.app, "AXWindows") or [])
        seen = 0
        while queue and seen < limit:
            el = queue.pop(0)
            seen += 1
            yield el
            queue.extend(self.get(el, "AXChildren") or [])

    def texts(self, el, depth=3):
        out = []
        stack = [(el, 0)]
        while stack:
            e, d = stack.pop()
            if self.get(e, "AXRole") == "AXStaticText":
                v = self.get(e, "AXValue")
                if v:
                    out.append(str(v))
            if d < depth:
                stack.extend((c, d + 1) for c in (self.get(e, "AXChildren") or []))
        return out


def load_track(title, artist, deck, timeout=2.5):
    """Search `title` in djay and load the best match onto deck 1 or 2."""
    if deck not in (1, 2):
        raise LoadError("badDeck")
    AS, Quartz, NSWorkspace = _ax()
    if not accessibility_ok(prompt=True):
        raise LoadError("noPermission")
    pid = _djay_pid(NSWorkspace)
    if not pid:
        raise LoadError("notRunning")
    tree = _Tree(AS, pid)

    fields = [e for e in tree.walk() if tree.get(e, "AXSubrole") == "AXSearchField"]
    if not fields:
        raise LoadError("noSearch")
    field = fields[0]
    tree.set(field, "AXFocused", True)
    tree.set(field, "AXValue", title)
    AS.AXUIElementPerformAction(field, "AXConfirm")

    want, want_artist = _norm(title), _norm(artist)
    row = None
    deadline = time.time() + timeout
    while time.time() < deadline and row is None:
        time.sleep(0.25)
        best = 0
        for el in tree.walk():
            if tree.get(el, "AXRole") != "AXRow":
                continue
            texts = [_norm(t) for t in tree.texts(el)]
            if want not in texts and not any(t.endswith(want) for t in texts if t):
                continue
            score = 2 if want in texts else 1
            if want_artist and any(want_artist in t for t in texts):
                score += 1
            if score > best:
                best, row = score, el
    if row is None:
        raise LoadError("notFound")

    table = tree.get(row, "AXParent")
    if table is not None:
        tree.set(table, "AXSelectedRows", [row])
        tree.set(table, "AXFocused", True)
    tree.set(row, "AXSelected", True)
    time.sleep(0.1)

    key = KEY_LEFT if deck == 1 else KEY_RIGHT
    for down in (True, False):
        ev = Quartz.CGEventCreateKeyboardEvent(None, key, down)
        Quartz.CGEventSetFlags(ev, Quartz.kCGEventFlagMaskCommand)
        Quartz.CGEventPostToPid(pid, ev)
        time.sleep(0.03)
    return True
