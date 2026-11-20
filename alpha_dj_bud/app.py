"""Entry point: starts the local server and opens the Alpha DJ Bud window.

Window priority:
  1. pywebview (native macOS window, can stay on top of djay in compact mode)
  2. Google Chrome / Edge / Brave in "app" mode (small chromeless window)
  3. default browser
"""
import argparse
import os
import shutil
import subprocess
import sys
import time
import webbrowser

from .server import AppState, start_server

CHROME_APPS = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
]


def _open_chrome_app(url, compact):
    w, h = (360, 560) if compact else (1080, 760)
    for exe in CHROME_APPS + [shutil.which("google-chrome") or ""]:
        if exe and os.path.exists(exe):
            profile = os.path.join(os.path.expanduser("~"), ".alpha-dj-bud-browser")
            subprocess.Popen([exe, "--app=" + url, "--window-size=%d,%d" % (w, h),
                              "--user-data-dir=" + profile, "--no-first-run"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
    return False


ASSETS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")


def brand_macos_process():
    """Show 'Alpha DJ Bud' and its icon instead of 'Python' in the menu bar
    and Dock. Must run before the window is created."""
    if sys.platform != "darwin":
        return
    try:
        from AppKit import NSApplication, NSImage
        from Foundation import NSBundle
        info = NSBundle.mainBundle().infoDictionary()
        if info is not None:
            info["CFBundleName"] = "Alpha DJ Bud"
            info["CFBundleDisplayName"] = "Alpha DJ Bud"
        app = NSApplication.sharedApplication()
        icon = os.path.join(ASSETS, "AppIcon.icns")
        if os.path.exists(icon):
            img = NSImage.alloc().initWithContentsOfFile_(icon)
            if img is not None:
                app.setApplicationIconImage_(img)
    except Exception as e:  # cosmetic only
        print("branding:", e)


class JsApi:
    """Functions the page can call through window.pywebview.api (native window)."""

    def __init__(self, state):
        self._state = state

    def drag_track(self, track_id):
        return self._state.native_drag(track_id)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Alpha DJ Bud")
    ap.add_argument("--db", help="path to MediaLibrary.db (optional)")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--browser", action="store_true", help="open in the browser instead of the native window")
    ap.add_argument("--no-window", action="store_true", help="start the server only")
    args = ap.parse_args(argv)

    state = AppState(args.db)
    try:
        httpd = start_server(state, args.port)
    except OSError:
        httpd = start_server(state, 0)  # port busy: pick a free one
    url = "http://127.0.0.1:%d/" % httpd.server_address[1]
    print("Alpha DJ Bud running at", url)
    if state.library:
        print("djay library:", state.library.path)
    else:
        print("WARNING: djay library not found")

    if args.no_window:
        _wait()
        return

    if not args.browser:
        try:
            import webview  # pywebview
            brand_macos_process()
            compact = state.settings.get("compact")
            w, h = (360, 560) if compact else (1080, 760)
            state.window = webview.create_window(
                "Alpha DJ Bud", url, width=w, height=h, min_size=(320, 420), js_api=JsApi(state),
                on_top=bool(compact), background_color="#0b0b0f")
            def _after_start():
                try:
                    from . import native_drag
                    native_drag.install()
                except Exception as e:
                    print("drag:", e)
            webview.start(_after_start)
            return
        except ImportError:
            print("pywebview not installed: using the browser in app mode.")
        except Exception as e:
            print("Native window not available (%s): using the browser." % e)

    if not _open_chrome_app(url, state.settings.get("compact")):
        webbrowser.open(url)
    _wait()


def _wait():
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main(sys.argv[1:])
