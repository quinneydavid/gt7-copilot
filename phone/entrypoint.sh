#!/bin/bash
# First start: download the Android tools and build the phone into /data (about 7 GB). Every start: screen, web view, phone.
set -u
SDK=$ANDROID_SDK_ROOT; SM=$SDK/cmdline-tools/latest/bin/sdkmanager
mkdir -p "$SDK" "$ANDROID_AVD_HOME" "$HOME"
[ -e /dev/kvm ] || { echo "no /dev/kvm in the container: the phone would crawl. Stopping."; exit 1; }
if [ ! -x "$SM" ]; then
  echo "== command-line tools"; cd /tmp && curl -fsSLO "https://dl.google.com/android/repository/$CLT_ZIP" && unzip -q "$CLT_ZIP" \
    && mkdir -p "$SDK/cmdline-tools" && mv cmdline-tools "$SDK/cmdline-tools/latest" && rm -f "$CLT_ZIP" || exit 1
fi
AVD=${AVD:-phone}
if [ ! -f "$SDK/${IMAGE_PKG//;//}/system.img" ] || [ ! -x "$SDK/emulator/emulator" ]; then
  [ "${ANDROID_LICENSES:-}" = accept ] || { echo "The Android SDK and system image come from Google under their own licence terms"; echo "(https://developer.android.com/studio/terms). Set ANDROID_LICENSES=accept in .env to accept them and download."; exit 1; }
  echo "== Android packages (about 4 GB)"; yes | "$SM" --sdk_root="$SDK" --licenses >/dev/null 2>&1
  "$SM" --sdk_root="$SDK" platform-tools emulator "$IMAGE_PKG" 2>&1 | grep -v '^\[' | tail -3
fi
if [ ! -d "$ANDROID_AVD_HOME/$AVD.avd" ]; then
  echo "== phone"; echo no | "$SDK/cmdline-tools/latest/bin/avdmanager" create avd -n "$AVD" -k "$IMAGE_PKG" -d pixel_6 2>&1 | tail -1
  C=$ANDROID_AVD_HOME/$AVD.avd/config.ini
  sed -i -E '/^(hw\.keyboard|hw\.lcd\.(width|height|density)|hw\.ramSize|disk\.dataPartition\.size|hw\.gpu\.(enabled|mode))\s*=/d' "$C"
  printf 'hw.keyboard=yes\nhw.lcd.width=720\nhw.lcd.height=1600\nhw.lcd.density=320\nhw.ramSize=4096\ndisk.dataPartition.size=8G\nhw.gpu.enabled=yes\nhw.gpu.mode=swiftshader_indirect\n' >> "$C"
fi
rm -f /tmp/.X0-lock; rm -rf "$ANDROID_AVD_HOME/$AVD.avd"/*.lock 2>/dev/null
Xvfb :0 -screen 0 ${SCREEN:-540x870x24} -nolisten tcp & sleep 1
openbox >/dev/null 2>&1 &
# The web view's password: VNC_PASSWORD, or one made here on first start and kept in the shared volume, where the
# copilot's Settings tab shows it to the signed-in admin.
if [ -z "${VNC_PASSWORD:-}" ]; then
  PWF=${VNC_PASSWORD_FILE:-/data/vnc-password}
  [ -s "$PWF" ] || { mkdir -p "$(dirname "$PWF")"; head -c 9 /dev/urandom | base64 | tr -d '/+=' | head -c 8 > "$PWF"; chmod 644 "$PWF"; }
  VNC_PASSWORD=$(cat "$PWF"); echo "== web view password: in $PWF (shown on the copilot's Settings tab)"
fi
x11vnc -display :0 -forever -shared -rfbport 5900 -passwd "$VNC_PASSWORD" -noxdamage -quiet -bg -o /tmp/x11vnc.log
websockify --web /usr/share/novnc 6080 localhost:5900 >/tmp/novnc.log 2>&1 &
"$SDK/platform-tools/adb" start-server >/dev/null 2>&1
( for i in $(seq 1 90); do sleep 2; w=$(xdotool search --name "Android Emulator" 2>/dev/null | head -1); [ -n "$w" ] && xdotool windowmove "$w" 0 0 && break; done ) &
# once it has booted: never let the screen sleep (a sleeping phone is a black web view), wake it
( for i in $(seq 1 120); do sleep 3; [ "$("$SDK/platform-tools/adb" shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')" = 1 ] && break; done
  "$SDK/platform-tools/adb" shell "cmd battery set ac 1; cmd battery set status 2; settings put global stay_on_while_plugged_in 7; settings put system screen_off_timeout 2147483647; svc power stayon true; input keyevent KEYCODE_WAKEUP" >/dev/null 2>&1 ) &
{ [ -n "${GRAB_TOKEN:-}" ] || [ -n "${GRAB_TOKEN_FILE:-}" ]; } && python3 -u /grabber.py &
echo "== starting the phone"
exec "$SDK/emulator/emulator" -avd "$AVD" -no-snapshot -no-boot-anim -no-audio -gpu "${EMU_GPU:-swiftshader_indirect}" -accel on \
     -cores "${PHONE_CORES:-4}" -memory 4096 -no-metrics ${EMU_ARGS:-}
