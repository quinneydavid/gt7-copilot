#!/bin/bash
# GT7 Copilot earpiece - installer for a Mac. Downloaded from the copilot page (address and token already filled in).
# Run it in Terminal as the user who drives:
#     bash ~/Downloads/gt7copilot-earpiece-setup-mac.sh
# It puts the earpiece in ~/Library/Application Support/GT7Copilot and runs it as a LaunchAgent of this user
# (from sign-in, restarted if it stops). A LaunchAgent, not a system daemon: on a Mac the sound devices and the
# microphone permission belong to the signed-in user.
# Run it again any time to update. Remove:   bash gt7copilot-earpiece-setup-mac.sh uninstall
# Written from the documentation; not yet run on a real Mac.
set -euo pipefail

URL='__GT7C_URL__'
TOKEN='__GT7C_TOKEN__'
VOICE_DEFAULT='__GT7C_VOICE__'          # 1 = Voice control is on at the server (new installs only)
LABEL='com.gt7copilot.earpiece'
DIR="$HOME/Library/Application Support/GT7Copilot"
LOGS="$HOME/Library/Logs/GT7Copilot"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
CFG="$DIR/earpiece.json"
DOMAIN="gui/$(id -u)"

[ "$(uname -s)" = Darwin ] || { echo "This installer is for macOS. On Windows use the PowerShell installer from the same page."; exit 1; }
[ "$(id -u)" != 0 ] || { echo "Run this as the user who drives, without sudo."; exit 1; }

if [ "${1:-}" = uninstall ]; then
    launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
    rm -f "$PLIST"
    rm -rf "$DIR" "$LOGS"
    echo "DONE: the earpiece is removed."
    exit 0
fi

echo '== 1. Python'
PY=''
for c in /opt/homebrew/bin/python3 /usr/local/bin/python3 /Library/Frameworks/Python.framework/Versions/Current/bin/python3; do
    if [ -x "$c" ]; then PY="$c"; break; fi
done
# /usr/bin/python3 is only real once Apple's command line tools are installed; without them it opens an install dialog.
if [ -z "$PY" ] && xcode-select -p >/dev/null 2>&1 && [ -x /usr/bin/python3 ]; then PY=/usr/bin/python3; fi
if [ -z "$PY" ]; then
    echo "Python 3 is not installed. Install it with one of these, then run this again:"
    echo "    brew install python          (with Homebrew)"
    echo "    https://www.python.org/downloads/macos/   (the installer from python.org)"
    exit 1
fi
echo "using $PY ($("$PY" -c 'import sys; print(sys.version.split()[0])'))"

echo '== 2. earpiece program'
mkdir -p "$DIR" "$LOGS" "$HOME/Library/LaunchAgents"
[ -x "$DIR/venv/bin/python" ] || "$PY" -m venv "$DIR/venv"
"$DIR/venv/bin/python" -m pip install --quiet --disable-pip-version-check --upgrade sounddevice numpy
curl -fsS -H "X-GT7C-Earpiece: $TOKEN" -o "$DIR/earpiece.py.new" "$URL/earpiece/earpiece.py"
mv "$DIR/earpiece.py.new" "$DIR/earpiece.py"

echo '== 3. settings'
# Address and token are replaced; the device name and the other choices of an earlier install are kept.
DEVICE=$("$DIR/venv/bin/python" - "$CFG" <<'PY'
import json, sys
try: print(json.load(open(sys.argv[1], encoding="utf-8")).get("device") or "AirPods")
except Exception: print("AirPods")
PY
)
if [ -t 0 ]; then
    read -r -p "Name of the earbud or speaker as macOS shows it under Sound (part of the name is enough) [$DEVICE]: " ANS || true
    [ -z "${ANS:-}" ] || DEVICE="$ANS"
fi
GT7C_SETUP_URL="$URL" GT7C_SETUP_TOKEN="$TOKEN" GT7C_SETUP_DEVICE="$DEVICE" GT7C_SETUP_VOICE="$VOICE_DEFAULT" "$DIR/venv/bin/python" - "$CFG" <<'PY'
import json, os, sys
path = sys.argv[1]
try: old = json.load(open(path, encoding="utf-8"))
except Exception: old = {}
cfg = dict(url=os.environ["GT7C_SETUP_URL"], token=os.environ["GT7C_SETUP_TOKEN"], device=os.environ["GT7C_SETUP_DEVICE"],
           volume=None, voice=old.get("voice", os.environ["GT7C_SETUP_VOICE"] == "1"),
           connect_when=old.get("connect_when", "always"), start_simhub=False)
fd = os.open(path + ".tmp", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
with os.fdopen(fd, "w", encoding="utf-8") as f:
    json.dump(cfg, f, indent=1)
os.replace(path + ".tmp", path)
PY

echo '== 4. LaunchAgent (from sign-in)'
cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>$LABEL</string>
    <key>ProgramArguments</key>
    <array>
        <string>$DIR/venv/bin/python</string>
        <string>$DIR/earpiece.py</string>
        <string>run</string>
    </array>
    <key>WorkingDirectory</key><string>$DIR</string>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key><true/>
    <key>ThrottleInterval</key><integer>10</integer>
    <key>LimitLoadToSessionType</key><string>Aqua</string>
    <key>ProcessType</key><string>Interactive</string>
    <key>StandardOutPath</key><string>/dev/null</string>
    <key>StandardErrorPath</key><string>$LOGS/launchd.log</string>
</dict>
</plist>
PLIST
launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
launchctl bootstrap "$DOMAIN" "$PLIST"
launchctl kickstart -k "$DOMAIN/$LABEL" >/dev/null 2>&1 || true

echo ''
echo "DONE: the earpiece runs as the LaunchAgent $LABEL and starts at every sign-in."
echo "Log: $LOGS/earpiece.log"
echo 'The copilot page (Live tab) shows an "Earpiece" tile within 10 seconds: device connected or not.'
echo "Check what it sees:  \"$DIR/venv/bin/python\" \"$DIR/earpiece.py\" doctor"
echo 'Voice control: macOS asks once whether Python may use the microphone. Without that permission the earpiece'
echo 'still plays the calls. The answer is under System Settings > Privacy & Security > Microphone.'
echo 'Optional: "brew install blueutil" lets the earpiece ask Bluetooth to connect the earbud by itself.'
