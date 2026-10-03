#!/bin/bash
# Creates /Applications/AIQuota.app — a tiny headless launcher that (re)starts
# both the menu bar app and the desktop widget. Spotlight-searchable as
# "AIQuota", so users who quit the menu bar app can always get it back.
#
# Usage: bash make_launcher.sh [install_dir]   (default: ~/.ai-quota-bar)

set -e

INSTALL_DIR="${1:-$HOME/.ai-quota-bar}"
APP="/Applications/AIQuota.app"

mkdir -p "$APP/Contents/MacOS"

cat > "$APP/Contents/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key>
    <string>AIQuota</string>
    <key>CFBundleDisplayName</key>
    <string>AIQuota</string>
    <key>CFBundleIdentifier</key>
    <string>com.aiquotabar.launcher</string>
    <key>CFBundleExecutable</key>
    <string>AIQuota</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleShortVersionString</key>
    <string>1.0</string>
    <key>LSUIElement</key>
    <true/>
</dict>
</plist>
EOF

cat > "$APP/Contents/MacOS/AIQuota" <<EOF
#!/bin/bash
# AIQuota launcher — (re)starts the menu bar app and refreshes the widget.
INSTALL_DIR="$INSTALL_DIR"
PLIST="\$HOME/Library/LaunchAgents/com.aiquotabar.plist"
DOMAIN="gui/\$(id -u)"

# Menu bar app: kickstart -k restarts it if running, starts it if not.
if launchctl print "\$DOMAIN/com.aiquotabar" &>/dev/null; then
    launchctl kickstart -k "\$DOMAIN/com.aiquotabar"
elif [ -f "\$PLIST" ]; then
    launchctl bootstrap "\$DOMAIN" "\$PLIST" 2>/dev/null || true
    launchctl kickstart "\$DOMAIN/com.aiquotabar" 2>/dev/null || true
else
    # No LaunchAgent (manual install) — run the app directly.
    pkill -f "\$INSTALL_DIR/aiquotabar.py" 2>/dev/null || true
    sleep 1
    nohup "\$INSTALL_DIR/.venv/bin/python3" "\$INSTALL_DIR/aiquotabar.py" &>/dev/null &
fi

# Desktop widget: reload timelines. -n forces a new instance so the arg
# reaches it even if a host window is already open; it exits headlessly.
if [ -d "/Applications/AIQuotaBarHost.app" ]; then
    open -n -g -a AIQuotaBarHost --args --reload-widget
fi
EOF

chmod +x "$APP/Contents/MacOS/AIQuota"

# Make Spotlight pick it up right away instead of on its next index pass.
LSREGISTER=/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister
"$LSREGISTER" -f "$APP" 2>/dev/null || true

echo "  ✓  Launcher installed: $APP"
