"""Real macOS file drag out of the Alpha DJ Bud window (pywebview / Cocoa).

How it works:
  1. when you press the mouse on a suggestion, the page calls arm(track) and
     Python prepares the track's audio file;
  2. a native event monitor watches the window's own mouse events; on the
     first real "mouse dragged" event it starts a macOS dragging session with
     that very event, carrying the file (like dragging it from the Finder);
  3. releasing the mouse disarms it.
Starting the session from the genuine event, on the main thread, avoids the
timing problems of starting it from the page.
"""
import os
import sys
import threading
import time


def _log(*a):
    print("[drag]", *a, file=sys.stderr, flush=True)

_lock = threading.Lock()
_pending = {"path": None, "armed_at": 0.0, "down": None}
_installed = {"done": False, "monitor": None, "source": None, "error": None}

ARM_TIMEOUT = 8.0   # seconds an armed drag stays valid
MIN_DISTANCE = 3.0  # points the mouse must move before the drag starts


def arm(path):
    with _lock:
        _pending["path"] = path
        _pending["armed_at"] = time.time()


def disarm():
    with _lock:
        _pending["path"] = None


def install_error():
    return _installed["error"]


def is_installed():
    return _installed["done"]


def _make_source():
    import objc
    from AppKit import NSDragOperationCopy
    from Foundation import NSObject

    class AlphaDragSource(NSObject, protocols=[objc.protocolNamed("NSDraggingSource")]):
        def draggingSession_sourceOperationMaskForDraggingContext_(self, session, context):
            return NSDragOperationCopy

        def ignoreModifierKeysForDraggingSession_(self, session):
            return True

        def draggingSession_endedAtPoint_operation_(self, session, point, operation):
            _release_view()

    return AlphaDragSource.alloc().init()


_last = {"view": None, "event": None}


def _release_view():
    """The drag session swallows the mouse-up, so the web view would think the
    button is still pressed. Send it a mouse-up so the next drag works."""
    view, ev = _last["view"], _last["event"]
    _last["view"] = _last["event"] = None
    if view is None or ev is None:
        return
    try:
        from AppKit import NSEvent, NSEventTypeLeftMouseUp
        up = NSEvent.mouseEventWithType_location_modifierFlags_timestamp_windowNumber_context_eventNumber_clickCount_pressure_(
            NSEventTypeLeftMouseUp, ev.locationInWindow(), 0, ev.timestamp(),
            ev.windowNumber(), None, 0, 1, 0.0)
        view.mouseUp_(up)
    except Exception as e:
        _installed["error"] = str(e)
    with _lock:
        _pending["path"] = None
        _pending["down"] = None


def _start_session(event, path):
    from AppKit import NSDraggingItem, NSMakeRect, NSURL, NSWorkspace
    window = event.window()
    if window is None:
        return False
    view = window.contentView().hitTest_(event.locationInWindow()) or window.contentView()
    url = NSURL.fileURLWithPath_(path)
    item = NSDraggingItem.alloc().initWithPasteboardWriter_(url)
    icon = NSWorkspace.sharedWorkspace().iconForFile_(path)
    p = view.convertPoint_fromView_(event.locationInWindow(), None)
    item.setDraggingFrame_contents_(NSMakeRect(p.x - 24, p.y - 24, 48, 48), icon)
    _last["view"], _last["event"] = view, event
    view.beginDraggingSessionWithItems_event_source_([item], event, _installed["source"])
    return True


def _install_on_main_thread(done):
    try:
        from AppKit import (NSEvent, NSEventMaskLeftMouseDown, NSEventMaskLeftMouseDragged,
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
                elif t == NSEventTypeLeftMouseUp:
                    with _lock:
                        _pending["path"] = None
                        _pending["down"] = None
                elif t == NSEventTypeLeftMouseDragged:
                    with _lock:
                        path = _pending["path"]
                        fresh = time.time() - _pending["armed_at"] < ARM_TIMEOUT
                        down = _pending["down"]
                    if path and fresh:
                        loc = event.locationInWindow()
                        if down and abs(loc.x - down[0]) + abs(loc.y - down[1]) < MIN_DISTANCE:
                            return event
                        with _lock:
                            _pending["path"] = None
                        if os.path.exists(path) and _start_session(event, path):
                            _log("started:", path)
                            return None  # the drag session owns this event now
                        _log("not started:", path)
            except Exception as e:  # never break the window's mouse handling
                _installed["error"] = str(e)
                _log("error:", e)
            return event

        mask = NSEventMaskLeftMouseDown | NSEventMaskLeftMouseDragged | NSEventMaskLeftMouseUp
        _installed["monitor"] = NSEvent.addLocalMonitorForEventsMatchingMask_handler_(mask, handler)
        _installed["done"] = True
        _log("monitor installed")
    except Exception as e:
        _installed["error"] = str(e)
        _log("install failed:", e)
    finally:
        done.set()


def install(timeout=3.0):
    """Install the event monitor (call once the native window exists)."""
    if _installed["done"]:
        return True
    from PyObjCTools import AppHelper
    done = threading.Event()
    AppHelper.callAfter(_install_on_main_thread, done)
    done.wait(timeout)
    return _installed["done"]
