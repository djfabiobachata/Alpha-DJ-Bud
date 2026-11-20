#!/bin/bash
# Alpha DJ Bud installer for macOS.
# Creates "Alpha DJ Bud.app" (with its own name and icon) in your Applications folder.
# Run it again to update the app after downloading a new version.
set -e
SRC="$(cd "$(dirname "$0")" && pwd)"
SUPPORT="$HOME/Library/Application Support/Alpha DJ Bud"
APP="$HOME/Applications/Alpha DJ Bud.app"

echo "== Alpha DJ Bud installer =="
if ! /usr/bin/python3 -c "import sys" >/dev/null 2>&1 && ! command -v python3 >/dev/null 2>&1; then
  osascript -e 'display dialog "Python 3 is required. Open Terminal and run: xcode-select --install — then run this installer again." buttons {"OK"}'
  exit 1
fi
PY_SYS="$(command -v python3 || echo /usr/bin/python3)"

mkdir -p "$SUPPORT"
echo "1/4 Copying the app…"
rm -rf "$SUPPORT/app"
mkdir -p "$SUPPORT/app"
cp -R "$SRC/alpha_dj_bud" "$SRC/assets" "$SRC/requirements.txt" "$SUPPORT/app/"

echo "2/4 Preparing Python (first time can take a minute, internet needed)…"
if [ ! -x "$SUPPORT/venv/bin/python3" ]; then
  "$PY_SYS" -m venv "$SUPPORT/venv"
fi
"$SUPPORT/venv/bin/python3" -m pip install --quiet --upgrade pip || true
"$SUPPORT/venv/bin/python3" -m pip install --quiet -r "$SUPPORT/app/requirements.txt" \
  || echo "   (some components could not be installed: the app will open in the browser)"

echo "3/4 Creating Alpha DJ Bud.app…"
mkdir -p "$HOME/Applications"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp "$SRC/assets/AppIcon.icns" "$APP/Contents/Resources/AppIcon.icns"
VERSION="$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$SRC/alpha_dj_bud/__init__.py")"
cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>Alpha DJ Bud</string>
  <key>CFBundleDisplayName</key><string>Alpha DJ Bud</string>
  <key>CFBundleIdentifier</key><string>com.alphadjbud.app</string>
  <key>CFBundleVersion</key><string>$VERSION</string>
  <key>CFBundleShortVersionString</key><string>$VERSION</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleExecutable</key><string>AlphaDJBud</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>LSMinimumSystemVersion</key><string>11.0</string>
  <key>NSHighResolutionCapable</key><true/>
</dict></plist>
PLIST
cat > "$APP/Contents/MacOS/AlphaDJBud" <<'LAUNCH'
#!/bin/bash
S="$HOME/Library/Application Support/Alpha DJ Bud"
cd "$S/app" || exit 1
PY="$S/venv/bin/python3"
[ -x "$PY" ] || PY="$(command -v python3)"
exec "$PY" -m alpha_dj_bud.app >> "$S/alpha-dj-bud.log" 2>&1
LAUNCH
chmod +x "$APP/Contents/MacOS/AlphaDJBud"
touch "$APP"

echo "4/4 Done! Alpha DJ Bud is in your Applications folder (~/Applications)."
echo "    Tip: drag it to the Dock to keep it handy."
open "$APP"
