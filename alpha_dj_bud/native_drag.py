"""Real macOS file drag out of the Alpha DJ Bud window onto djay (pywebview / Cocoa).

Arming: the page sends the position of each draggable suggestion (set_rows).
A native event monitor sees the mouse-down even when the window is not
active (the DJ comes from djay, so the first click only activates the window
and never reaches the page) and arms the drag for the row under the mouse.
On the first real "mouse dragged" event it starts a macOS drag.

djay (App Store) is picky about what it accepts. Finder drags work, so we
offer the file like the Finder does, and we cycle through three methods:
when djay rejects a drop (operation none), the next drag uses the next
method; the method that works is remembered.
  1. "url"     NSURL on the pasteboard (sandbox access for djay), all operations
  2. "files"   classic NSView.dragFile (file-name list, Finder style)
  3. "promise" NSFilePromiseProvider with the audio type: djay receives a copy
"""
import json
import os
import shutil
import sys
import threading
import time

_lock = threading.Lock()
_pending = {"path": None, "armed_at": 0.0, "down": None}
_rows = {"items": [], "resolver": None}
_installed = {"done": False, "monitor": None, "source": None, "error": None,
              "window": None, "promise_delegate": None}
_status = {"armed": None, "started": None, "method": None, "error": None,
           "dragged_events": 0, "result": None}
_last = {"view": None, "event": None, "method": None, "path": None}
_methods = ["url", "files", "promise"]
_state = {"method": "url", "file": None}

ARM_TIMEOUT = 8.0
MIN_DISTANCE = 3.0
NONE, COPY, LINK, GENERIC, MOVE = 0, 1, 2, 4, 16


def _log(*a):
    print("[drag]", *a, file=sys.stderr, flush=True)


# -- configuration / state --------------------------------------------------
def configure(home, resolver):
    """resolver(track_id) -> file path. Remembers the working method in home."""
    _rows["resolver"] = resolver
    _state["file"] = os.path.join(home, "drag-method.json")
    try:
        with open(_state["file"]) as f:
            m = json.load(f).get("method")
        if m in _methods:
            _state["method"] = m
    except (OSError, ValueError):
        pass


def _save_method():
    if not _state["file"]:
        return
    try:
        with open(_state["file"], "w") as f:
            json.dump({"method": _state["method"]}, f)
    except OSError:
        pass


def set_rows(rows):
    """rows: [{'id','x','y','w','h'}] in CSS pixels of the page viewport."""
    with _lock:
        _rows["items"] = [r for r in rows or [] if isinstance(r, dict) and r.get("id")]


def arm(path):
    with _lock:
        _pending["path"] = path
        _pending["armed_at"] = time.time()
        _status.update({"armed": path, "started": None, "error": None,
                        "dragged_events": 0, "result": None})
    _log("armed:", path)


def status():
    with _lock:
        return dict(_status, monitor=_installed["done"], install_error=_installed["error"],
                    current_method=_state["method"])


# -- drag source ---------------------------------------------------------------
def _make_source():
    import objc
    from Foundation import NSObject

    every = COPY | LINK | GENERIC | MOVE

    class AlphaDragSource(NSObject, protocols=[objc.protocolNamed("NSDraggingSource")]):
        def draggingSession_sourceOperationMaskForDraggingContext_(self, session, context):
            return every

        def ignoreModifierKeysForDraggingSession_(self, session):
            return True

        def draggingSession_endedAtPoint_operation_(self, session, point, operation):
            _ended(operation)

        # legacy dragFile:
        def draggingSourceOperationMaskForLocal_(self, is_local):
            return every

        def draggedImage_endedAt_operation_(self, image, point, operation):
            _ended(operation)

    return AlphaDragSource.alloc().init()


def _make_promise_delegate():
    import objc
    from Foundation import NSObject

    class AlphaPromiseDelegate(NSObject, protocols=[objc.protocolNamed("NSFilePromiseProviderDelegate")]):
        def filePromiseProvider_fileNameForType_(self, provider, file_type):
            return os.path.basename(_last["path"] or "track")

        def filePromiseProvider_writePromiseToURL_completionHandler_(self, provider, url, handler):
            try:
                shutil.copyfile(_last["path"], url.path())
                handler(None)
            except Exception as e:
                _log("promise write failed:", e)
                from Foundation import NSError
                handler(NSError.errorWithDomain_code_userInfo_("AlphaDJBud", 1, None))

    return AlphaPromiseDelegate.alloc().init()


def _ended(operation):
    method = _last["method"]
    ok = operation != NONE
    _status["result"] = "accepted" if ok else "rejected"
    _log("ended: method=%s operation=%s" % (method, operation))
    if method:
        if ok:
            _state["method"] = method
            _save_method()
        elif method == _state["method"]:
            i = _methods.index(method)
            _state["method"] = _methods[(i + 1) % len(_methods)]
            _save_method()
            _log("djay rejected the drop, next time trying:", _state["method"])
    _release_view()


def _release_view():
    """The drag swallows the mouse-up; tell the web view the button is up."""
    view, ev = _last["view"], _last["event"]
    _last["view"] = _last["event"] = None
    with _lock:
        _pending["path"] = None
        _pending["down"] = None
    if view is None or ev is None:
        return
    try:
        from AppKit import NSEvent, NSEventTypeLeftMouseUp
        up = NSEvent.mouseEventWithType_location_modifierFlags_timestamp_windowNumber_context_eventNumber_clickCount_pressure_(
            NSEventTypeLeftMouseUp, ev.locationInWindow(), 0, ev.timestamp(),
            ev.windowNumber(), None, 0, 1, 0.0)
        view.mouseUp_(up)
    except Exception as e:
        _log("release error:", e)


# -- the three methods -----------------------------------------------------------
def _frame(view, event, path):
    from AppKit import NSMakeRect, NSWorkspace
    p = view.convertPoint_fromView_(event.locationInWindow(), None)
    return NSMakeRect(p.x - 24, p.y - 24, 48, 48), NSWorkspace.sharedWorkspace().iconForFile_(path)


def _drag_url(view, event, path):
    from AppKit import NSDraggingItem, NSURL
    item = NSDraggingItem.alloc().initWithPasteboardWriter_(NSURL.fileURLWithPath_(path))
    rect, icon = _frame(view, event, path)
    item.setDraggingFrame_contents_(rect, icon)
    if view.beginDraggingSessionWithItems_event_source_([item], event, _installed["source"]) is None:
        raise RuntimeError("no dragging session")


def _drag_files(view, event, path):
    rect, _icon = _frame(view, event, path)
    if not view.dragFile_fromRect_slideBack_event_(path, rect, True, event):
        raise RuntimeError("dragFile refused")


def _drag_promise(view, event, path):
    from AppKit import NSDraggingItem, NSFilePromiseProvider
    uti = "public.audio"
    try:
        from UniformTypeIdentifiers import UTType
        t = UTType.typeWithFilenameExtension_(os.path.splitext(path)[1].lstrip("."))
        if t is not None:
            uti = t.identifier()
    except Exception:
        pass
    if _installed["promise_delegate"] is None:
        _installed["promise_delegate"] = _make_promise_delegate()
    provider = NSFilePromiseProvider.alloc().initWithFileType_delegate_(uti, _installed["promise_delegate"])
    item = NSDraggingItem.alloc().initWithPasteboardWriter_(provider)
    rect, icon = _frame(view, event, path)
    item.setDraggingFrame_contents_(rect, icon)
    if view.beginDraggingSessionWithItems_event_source_([item], event, _installed["source"]) is None:
        raise RuntimeError("no dragging session")


_FUNCS = {"url": _drag_url, "files": _drag_files, "promise": _drag_promise}


def _start(event, path):
    window = event.window()
    if window is None:
        raise RuntimeError("event has no window")
    view = window.contentView().hitTest_(event.locationInWindow()) or window.contentView()
    _last.update({"view": view, "event": event, "path": path})
    first = _state["method"]
    order = [first] + [m for m in _methods if m != first]
    errors = []
    for m in order:
        try:
            _last["method"] = m
            _FUNCS[m](view, event, path)
            return m
        except Exception as e:
            errors.append("%s: %s" % (m, e))
    raise RuntimeError("; ".join(errors))


# -- event monitor -----------------------------------------------------------------
def row_at_point(x, y):
    """Track id of the suggestion at page coordinates (x, y)."""
    with _lock:
        rows = list(_rows["items"])
    for r in rows:
        if r["x"] <= x <= r["x"] + r["w"] and r["y"] <= y <= r["y"] + r["h"]:
            return r["id"]
    return None


def _row_at(event):
    try:
        window = event.window()
        if window is None or (_installed["window"] is not None and window != _installed["window"]):
            return None
        h = window.contentView().frame().size.height
        p = event.locationInWindow()
        return row_at_point(p.x, h - p.y)  # page origin is top-left
    except Exception as e:
        _log("row lookup failed:", e)
    return None


def _install_on_main_thread(done):
    try:
        from AppKit import (NSApp, NSEvent, NSEventMaskLeftMouseDown, NSEventMaskLeftMouseDragged,
                            NSEventMaskLeftMouseUp, NSEventTypeLeftMouseDown,
                            NSEventTypeLeftMouseDragged, NSEventTypeLeftMouseUp)
        _installed["source"] = _make_source()

        def handler(event):
            try:
                t = event.type()
                if t == NSEventTypeLeftMouseDown:
                    loc = event.locationInWindow()
                    with _lock:
                        _pending["down"] = (loc.x, loc.y)
                    tid = _row_at(event)
                    if tid and _rows["resolver"]:
                        path = _rows["resolver"](tid)
                        if path:
                            arm(path)
                elif t == NSEventTypeLeftMouseUp:
                    with _lock:
                        _pending["path"] = None
                        _pending["down"] = None
                elif t == NSEventTypeLeftMouseDragged:
                    with _lock:
                        _status["dragged_events"] += 1
                        path = _pending["path"]
                        fresh = time.time() - _pending["armed_at"] < ARM_TIMEOUT
                        down = _pending["down"]
                    if path and fresh:
                        loc = event.locationInWindow()
                        if down and abs(loc.x - down[0]) + abs(loc.y - down[1]) < MIN_DISTANCE:
                            return event
                        with _lock:
                            _pending["path"] = None
                        if not os.path.exists(path):
                            _status["error"] = "file not found"
                            return event
                        try:
                            method = _start(event, path)
                            _status.update({"started": path, "method": method})
                            _log("started (%s):" % method, path)
                            return None
                        except Exception as e:
                            _status["error"] = str(e)
                            _log("not started:", e)
            except Exception as e:
                _status["error"] = str(e)
                _log("handler error:", e)
            return event

        mask = NSEventMaskLeftMouseDown | NSEventMaskLeftMouseDragged | NSEventMaskLeftMouseUp
        _installed["monitor"] = NSEvent.addLocalMonitorForEventsMatchingMask_handler_(mask, handler)
        wins = [w for w in (NSApp.windows() or []) if w.isVisible()]
        _installed["window"] = wins[0] if len(wins) == 1 else None
        _installed["done"] = True
        _log("monitor installed, method:", _state["method"])
    except Exception as e:
        _installed["error"] = str(e)
        _log("install failed:", e)
    finally:
        done.set()


def install(timeout=3.0):
    if _installed["done"]:
        return True
    from PyObjCTools import AppHelper
    done = threading.Event()
    AppHelper.callAfter(_install_on_main_thread, done)
    done.wait(timeout)
    return _installed["done"]
