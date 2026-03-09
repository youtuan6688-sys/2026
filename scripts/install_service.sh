#!/bin/bash
# Install HappyCode Knowledge System as a macOS launchd service

PLIST_NAME="com.happycode.knowledge"
PLIST_PATH="$HOME/Library/LaunchAgents/${PLIST_NAME}.plist"
PROJECT_DIR="/Users/tuanyou/Happycode2026"
PYTHON="${PROJECT_DIR}/.venv/bin/python"

echo "Creating launchd plist at: ${PLIST_PATH}"

cat > "${PLIST_PATH}" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${PLIST_NAME}</string>
    <key>ProgramArguments</key>
    <array>
        <string>${PYTHON}</string>
        <string>-m</string>
        <string>src.main</string>
    </array>
    <key>WorkingDirectory</key>
    <string>${PROJECT_DIR}</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>${PROJECT_DIR}/logs/service.log</string>
    <key>StandardErrorPath</key>
    <string>${PROJECT_DIR}/logs/service.err</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
    </dict>
</dict>
</plist>
EOF

echo "Loading service..."
launchctl unload "${PLIST_PATH}" 2>/dev/null
launchctl load "${PLIST_PATH}"

echo ""
echo "Done! Service installed."
echo ""
echo "Useful commands:"
echo "  Start:   launchctl load ${PLIST_PATH}"
echo "  Stop:    launchctl unload ${PLIST_PATH}"
echo "  Status:  launchctl list | grep happycode"
echo "  Logs:    tail -f ${PROJECT_DIR}/logs/service.log"
echo "  Errors:  tail -f ${PROJECT_DIR}/logs/service.err"
