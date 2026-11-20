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


def main(argv=None):
    ap = argparse.ArgumentParser(description="Alpha DJ Bud")
    ap.add_argument("--db", help="percorso di MediaLibrary.db (facoltativo)")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--browser", action="store_true", help="apri nel browser invece della finestra nativa")
    ap.add_argument("--no-window", action="store_true", help="avvia solo il server")
    args = ap.parse_args(argv)

    state = AppState(args.db)
    try:
        httpd = start_server(state, args.port)
    except OSError:
        httpd = start_server(state, 0)  # port busy: pick a free one
    url = "http://127.0.0.1:%d/" % httpd.server_address[1]
    print("Alpha DJ Bud attivo su", url)
    if state.library:
        print("Libreria djay:", state.library.path)
    else:
        print("ATTENZIONE: libreria djay non trovata")

    if args.no_window:
        _wait()
        return

    if not args.browser:
        try:
            import webview  # pywebview
            compact = state.settings.get("compact")
            w, h = (360, 560) if compact else (1080, 760)
            state.window = webview.create_window(
                "Alpha DJ Bud", url, width=w, height=h, min_size=(320, 420),
                on_top=bool(compact), background_color="#0b0b0f")
            webview.start()
            return
        except ImportError:
            print("pywebview non installato: uso il browser in modalità app.")
        except Exception as e:
            print("Finestra nativa non disponibile (%s): uso il browser." % e)

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
