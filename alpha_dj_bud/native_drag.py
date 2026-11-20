"""Real macOS file drag out of the Alpha DJ Bud window (pywebview / Cocoa).

How it works:
  1. when you press the mouse on a suggestion, the page calls arm(track) and
     Python prepares the track's audio file;
  2. a native event monitor watches the window's own mouse events; on the
     first real "mouse dragged" event it starts a macOS file drag with that
     very event (like dragging the file from the Finder);
  3. releasing the mouse disarms it.

Two ways of starting the drag are tried, so djay gets the file in the form it
expects: the modern dragging session (file URL + legacy file-name list), and
if that fails, the classic NSView.dragFile (the Finder-style drag).

status() tells the page what happened, so a failed drag shows a reason.
"""
import os
import sys
import threading
import time

_lock = threading.Lock()
_pending = {"path": None, "armed_at": 0.0, "down": None}
_installed = {"done": False, "monitor": None, "source": None, "error": None}
_status = {"armed": None, "started": None, "method": None, "error": None, "dragged_events": 0}
_last = {"view": None, "event": None}

ARM_TIMEOUT = 8.0   # seconds an armed drag stays valid
MIN_DISTANCE = 3.0  # points the mouse must move before the drag starts


def _log(*a):
    print("[drag]", *a, file=sys.stderr, flush=True)


def arm(path):
    with _lock:
        _pending["path"] = path
        _pending["armed_at"] = time.time()
        _status.update({"armed": path, "started": None, "method": None, "error": None,
                        "dragged_events": 0})
    _log("armed:", path)


def status():
    with _lock:
        return dict(_status, monitor=_installed["done"], install_error=_installed["error"])


def install_error():
    return _installed["error"]


def is_installed():
    return _installed["done"]


def _make_source():
    import objc
    from AppKit import NSDragOperationCopy, NSDragOperationGeneric
    from Foundation import NSObject

    class AlphaDragSource(NSObject, protocols=[objc.protocolNamed("NSDraggingSource")]):
        def draggingSession_sourceOperationMaskForDraggingContext_(self, session, context):
            return NSDragOperationCopy | NSDragOperationGeneric

        def ignoreModifierKeysForDraggingSession_(self, session):
            return True

        def draggingSession_endedAtPoint_operation_(self, session, point, operation):
            _log("ended, operation =", operation)
            _release_view()

        # legacy dragFile: callback
        def draggingSourceOperationMaskForLocal_(self, is_local):
            return NSDragOperationCopy | NSDragOperationGeneric

    return AlphaDragSource.alloc().init()


def _release_view():
    """The drag swallows the mouse-up, so the web view would think the button
    is still pressed. Send it a mouse-up so the next drag works."""
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


def _session_drag(view, event, path):
    from AppKit import NSDraggingItem, NSMakeRect, NSPasteboardItem, NSURL, NSWorkspace
    url = NSURL.fileURLWithPath_(path)
    data = NSPasteboardItem.alloc().init()
    data.setString_forType_(url.absoluteString(), "public.file-url")
    data.setString_forType_(path, "public.utf8-plain-text")
    item = NSDraggingItem.alloc().initWithPasteboardWriter_(data)
    icon = NSWorkspace.sharedWorkspace().iconForFile_(path)
    p = view.convertPoint_fromView_(event.locationInWindow(), None)
    item.setDraggingFrame_contents_(NSMakeRect(p.x - 24, p.y - 24, 48, 48), icon)
    session = view.beginDraggingSessionWithItems_event_source_([item], event, _installed["source"])
    if session is None:
        raise RuntimeError("no dragging session")
    try:  # also offer the legacy file list that older drop targets read
        pb = session.draggingPasteboard()
        pb.addTypes_owner_(["NSFilenamesPboardType"], None)
        pb.setPropertyList_forType_([path], "NSFilenamesPboardType")
    except Exception as e:
        _log("legacy type not added:", e)
    return "session"


def _legacy_drag(view, event, path):
    from AppKit import NSMakeRect
    p = view.convertPoint_fromView_(event.locationInWindow(), None)
    ok = view.dragFile_fromRect_slideBack_event_(path, NSMakeRect(p.x - 24, p.y - 24, 48, 48), True, event)
    if not ok:
        raise RuntimeError("dragFile refused")
    return "dragFile"


def _start(event, path):
    window = event.window()
    if window is None:
        raise RuntimeError("event has no window")
    view = window.contentView().hitTest_(event.locationInWindow()) or window.contentView()
    _last["view"], _last["event"] = view, event
    errors = []
    for fn in (_session_drag, _legacy_drag):
        try:
            return fn(view, event, path)
        except Exception as e:
            errors.append("%s: %s" % (fn.__name__, e))
    raise RuntimeError("; ".join(errors))


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
                            return None  # the drag owns this event now
                        except Exception as e:
                            _status["error"] = str(e)
                            _log("not started:", e)
            except Exception as e:  # never break the window's mouse handling
                _status["error"] = str(e)
                _log("handler error:", e)
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
