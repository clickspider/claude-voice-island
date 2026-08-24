#!/bin/bash
# Build ~/Applications/Claude Voice Island.app, a launcher that runs this
# checkout's venv. Re-run any time; it replaces the bundle.
#
# The bundle exists for one reason beyond convenience: macOS attaches microphone
# permission to an app identity. Launching through a bundle means you grant
# access once to "Claude Voice Island" instead of granting it to a Python
# interpreter and losing it whenever that path changes.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP="$HOME/Applications/Claude Voice Island.app"
BINARY="Claude Voice Island"

if [ ! -x "$ROOT/venv/bin/python" ]; then
    echo "No venv found. Run ./scripts/setup.sh first." >&2
    exit 1
fi

if [ ! -f "$ROOT/icon.icns" ]; then
    echo "Generating the icon"
    "$ROOT/venv/bin/python" "$ROOT/scripts/make_icon.py" "$ROOT"
fi

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key><string>Claude Voice Island</string>
    <key>CFBundleDisplayName</key><string>Claude Voice Island</string>
    <key>CFBundleIdentifier</key><string>com.danielfrey.claudevoiceisland</string>
    <key>CFBundleVersion</key><string>1.0.0</string>
    <key>CFBundleShortVersionString</key><string>1.0.0</string>
    <key>CFBundlePackageType</key><string>APPL</string>
    <key>CFBundleExecutable</key><string>${BINARY}</string>
    <key>CFBundleIconFile</key><string>icon</string>
    <key>LSUIElement</key><true/>
    <key>NSHighResolutionCapable</key><true/>
    <key>LSMinimumSystemVersion</key><string>13.0</string>
    <key>NSMicrophoneUsageDescription</key>
    <string>Claude Voice Island records your voice while you hold to talk.</string>
</dict>
</plist>
PLIST

# The launcher hard-codes this checkout, so moving the folder means rebuilding.
cat > "$APP/Contents/MacOS/${BINARY}" <<LAUNCHER
#!/bin/bash
cd "${ROOT}" || exit 1
exec "${ROOT}/venv/bin/python" -m voiceisland
LAUNCHER
chmod +x "$APP/Contents/MacOS/${BINARY}"

cp "$ROOT/icon.icns" "$APP/Contents/Resources/icon.icns"

# Register it so it shows up in Spotlight and Launchpad right away.
LSREGISTER="/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister"
[ -x "$LSREGISTER" ] && "$LSREGISTER" -f "$APP" 2>/dev/null || true

echo "Built: $APP"
