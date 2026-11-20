"""Real macOS file drag out of the Alpha DJ Bud window (pywebview / Cocoa).

The page asks for a drag when you press on a suggestion and move the mouse;
this module starts a native dragging session carrying the track's audio file,
exactly like dragging it from the Finder, so it can be dropped on a djay deck.
"""
import os
import threading

_source = None


def _find_webview(view):
    if view is None:
        return None
    if "WKWebView" in view.className():
        return view
    for sub in view.subviews() or []:
        found = _find_webview(sub)
        if found is not None:
            return found
    return None


def _ns_window(window):
    native = getattr(window, "native", None)
    if native is None:
        return None
    if hasattr(native, "contentView"):
        return native
    return getattr(native, "window", None)


def _make_source():
    global _source
    if _source is not None:
        return _source
    import objc
    from AppKit import NSDragOperationCopy
    from Foundation import NSObject

    class AlphaDragSource(NSObject, protocols=[objc.protocolNamed("NSDraggingSource")]):
        def draggingSession_sourceOperationMaskForDraggingContext_(self, session, context):
            return NSDragOperationCopy

    _source = AlphaDragSource.alloc().init()
    return _source


def _drag_on_main_thread(window, path, done):
    try:
        from AppKit import (NSApp, NSDraggingItem, NSEventTypeLeftMouseDown,
                            NSEventTypeLeftMouseDragged, NSMakeRect, NSURL, NSWorkspace)
        ns_window = _ns_window(window)
        if ns_window is None:
            raise RuntimeError("no native window")
        view = _find_webview(ns_window.contentView()) or ns_window.contentView()
        event = NSApp.currentEvent()
        if event is None or event.type() not in (NSEventTypeLeftMouseDown, NSEventTypeLeftMouseDragged):
            raise RuntimeError("mouse released")
        url = NSURL.fileURLWithPath_(path)
        item = NSDraggingItem.alloc().initWithPasteboardWriter_(url)
        icon = NSWorkspace.sharedWorkspace().iconForFile_(path)
        p = view.convertPoint_fromView_(event.locationInWindow(), None)
        item.setDraggingFrame_contents_(NSMakeRect(p.x - 24, p.y - 24, 48, 48), icon)
        view.beginDraggingSessionWithItems_event_source_([item], event, _make_source())
        done["ok"] = True
    except Exception as e:  # reported back to the page
        done["error"] = str(e)
    finally:
        done["event"].set()


def start_file_drag(window, path, timeout=1.5):
    if window is None:
        raise RuntimeError("native window not available")
    if not os.path.exists(path):
        raise RuntimeError("file not found: %s" % path)
    from PyObjCTools import AppHelper
    done = {"event": threading.Event()}
    AppHelper.callAfter(_drag_on_main_thread, window, path, done)
    done["event"].wait(timeout)
    if "error" in done:
        raise RuntimeError(done["error"])
    return True
