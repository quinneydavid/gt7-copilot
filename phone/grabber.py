#!/usr/bin/env python3
"""Fetches a PS5 capture out of the PlayStation App on the virtual phone, by driving the app the way a finger would.

  POST /grab?index=1      header X-GT7C-Grab: <token>      -> the newest screenshot as image/jpeg (index=2: the one before)
       &mode=fresh        restart the app first, so the list is certainly current;  &mode=stay  use the list as it stands
  GET  /healthz           how the phone is (started, app installed, unlocked), no token

Steps: if the app is already on its captures list, pull the list down to reload it; otherwise restart the app, open
Library > Captures and wait for the list. Then open the index-th screenshot, tap the download button,
take the file from "/sdcard/Pictures/PS App", close the viewer. The list is read through its accessibility labels
("Screenshot. Gran Turismo 7. 1 of 6."); the buttons inside the full-screen viewer have no labels, so those are tapped by
position (proven 12 Nov 2026 on PS App 26.10, 720x1600). 423 = the phone is on its lock screen (someone has to unlock it in the web view)."""
import hmac, json, os, re, subprocess, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

ADB = os.environ.get("ADB", "/data/sdk/platform-tools/adb")
def _token():
    """GRAB_TOKEN, or the file the copilot container wrote into the shared volume (compose: no hand-copying)."""
    t = os.environ.get("GRAB_TOKEN", "")
    path = os.environ.get("GRAB_TOKEN_FILE", "")
    for _ in range(60):
        if t or not path:
            break
        try: t = open(path).read().strip()
        except OSError: time.sleep(2)
    return t


TOKEN = _token()
FRESH = os.environ.get("GRAB_FRESH", "") == "1"     # 1 = restart the app for every fetch (the old way)
PKG, DIR, MARK = "com.scee.psxandroid", "/sdcard/Pictures/PS App", "/sdcard/.gt7copilot_mark"
lock = threading.Lock()


class Fail(Exception):
    def __init__(self, code, msg): super().__init__(msg); self.code = code


def sh(cmd, timeout=25, raw=False):
    r = subprocess.run([ADB, "exec-out" if raw else "shell", cmd], capture_output=True, timeout=timeout)
    return r.stdout if raw else r.stdout.decode(errors="replace")


def nodes():
    """[(label, cx, cy)] for everything on screen that has a label."""
    x = sh("uiautomator dump /sdcard/ui.xml >/dev/null 2>&1; cat /sdcard/ui.xml")
    out = []
    for n in re.findall(r"<node [^>]*?>", x):
        g = lambda k: (re.search(k + r'="([^"]*)"', n) or [0, ""])[1]
        label = g(" text") or g("content-desc"); b = re.findall(r"\d+", g("bounds"))
        if label and len(b) == 4:
            out.append((label.replace("&#10;", " "), (int(b[0]) + int(b[2])) // 2, (int(b[1]) + int(b[3])) // 2))
    return out


def tap(x, y): sh(f"input tap {int(x)} {int(y)}")


def tap_label(ns, exact):
    for label, x, y in ns:
        if label == exact:
            tap(x, y); return True
    return False


def grab(index, mode=""):
    """mode: "" = reload the list if the app is on it, else restart the app; "fresh" = always restart the app (the list is
    then certainly the current one); "stay" = use the list as it stands (the next capture of a batch)."""
    if "isKeyguardShowing=true" in sh("dumpsys window | grep isKeyguardShowing"):
        raise Fail(423, "the phone is on its lock screen")
    w, h = (int(v) for v in re.search(r"(\d+)x(\d+)", sh("wm size")).groups())
    tile = re.compile(r"^Screenshot\. (.*)\. (\d+) of (\d+)\.$")

    def wait_for(test, secs, what):
        """Poll the screen until test(labels) is true. Never tap again while waiting: re-tapping a tab restarts its
        loading and the list then never arrives (12 Nov 2026)."""
        end = time.time() + secs
        while time.time() < end:
            ns = nodes()
            if test([l for l, _, _ in ns]):
                return ns
            time.sleep(1.5)
        raise Fail(504, f"the PlayStation App did not show {what} in {secs} s")

    listed = lambda ls: any(tile.match(l) for l in ls) or any(l.startswith("Your captures from") for l in ls)
    ns = None
    ns0 = nodes() if mode != "fresh" and not FRESH and PKG in sh("dumpsys window | grep mCurrentFocus") else []
    on_list = listed([l for l, _, _ in ns0])
    if on_list and mode == "stay":
        ns = ns0
    elif on_list:
        # The app is already on its captures list (where the last fetch left it): pull the list down to reload it
        # instead of restarting the app and walking through its tabs again.
        sh(f"input swipe {w // 2} {int(h * 0.30)} {w // 2} {int(h * 0.72)} 350"); time.sleep(2.5)
        try:
            ns = wait_for(listed, 20, "the reloaded captures list")
        except Fail:
            ns = None                                     # it did not come back: start over the long way
    how = ("as it stood" if mode == "stay" else "reload") if ns else "restart"
    if ns is None:
        sh(f"am force-stop {PKG}"); time.sleep(1)         # a fresh start: the list it loads is the current one
        sh(f"am start -n {PKG}/.activity.TopActivity")
        ns = wait_for(lambda ls: "Library" in ls, 40, "its tabs")
        if any(l in ("Sign In", "Create Account") for l, _, _ in ns):
            raise Fail(401, "the PlayStation App is signed out")
        tap_label(ns, "Library")
        tap_label(wait_for(lambda ls: "Captures" in ls, 25, "the Library page"), "Captures")
        ns = wait_for(listed, 45, "the captures list")
    print(f"grab: captures list by {how}", flush=True)
    # The tiles carry their place in the list ("3 of 15"). One further down than the screen shows is reached by
    # scrolling the list; a tile is only tapped when it is clear of the bars at the top and bottom of the screen.
    found = None
    for attempt in range(10):
        shots = {int(m.group(2)): (l, x, y) for l, x, y in ns for m in [tile.match(l)] if m}
        if not shots:
            raise Fail(404, "no screenshot in the app")
        total = int(tile.match(next(iter(shots.values()))[0]).group(3))
        if index > total:
            raise Fail(404, f"only {total} screenshot(s) in the app")
        if index in shots and h * 0.22 < shots[index][2] < h * 0.84:
            found = shots[index]; break
        up = index not in shots and index < min(shots) or index in shots and shots[index][2] <= h * 0.22
        a, b = (0.40, 0.70) if up else (0.70, 0.40)                       # drag the list down to go back up, up to go on
        sh(f"input swipe {w // 2} {int(h * a)} {w // 2} {int(h * b)} 500"); time.sleep(1.5)
        ns = nodes()
    if not found:
        raise Fail(504, f"screenshot {index} of {total} could not be brought onto the screen")
    label, x, y = found
    sh(f"date +%s > {MARK}; sleep 1"); tap(x, y); time.sleep(3)
    new = ""
    for attempt in range(4):
        tap(w * 0.883, h * 0.9425)                        # the download button, bottom right of the viewer
        for _ in range(8):
            time.sleep(1)
            new = sh(f"find '{DIR}' -type f -newer {MARK} 2>/dev/null | head -1").strip()
            if new:
                break
            if "GrantPermissionsActivity" in sh("dumpsys window | grep mCurrentFocus"):
                allow = [(lx, ly) for l, lx, ly in nodes() if l == "Allow all"]
                if allow: tap(*allow[0])
        if new:
            break
        tap(w * 0.5, h * 0.19); time.sleep(1.2)           # the controls were hidden: this shows them
    time.sleep(1.5)
    data = sh(f"cat '{new}'", raw=True) if new else b""
    sh("input keyevent 4"); time.sleep(1)
    if new:
        sh(f"rm -f '{new}'")
    if not data.startswith(b"\xff\xd8"):
        raise Fail(502, "the download did not produce a picture")
    return data, os.path.basename(new), label, total


def health():
    """How the phone is, in one sentence, for the copilot's Settings page. Asks adb only; taps nothing."""
    try:
        if sh("getprop sys.boot_completed", timeout=8).strip() != "1":
            return dict(ok=False, note="The virtual phone is still starting.")
        if not sh(f"pm path {PKG}", timeout=8).strip():
            return dict(ok=False, note="The PlayStation App is not installed on the virtual phone. Open the phone's web view, install it from the Play Store and sign in.")
        if "isKeyguardShowing=true" in sh("dumpsys window | grep isKeyguardShowing", timeout=8):
            return dict(ok=False, note="The virtual phone is on its lock screen. Unlock it in the web view.")
    except Exception as e:
        return dict(ok=False, note=f"The virtual phone does not answer ({type(e).__name__}).")
    return dict(ok=True, note="The virtual phone is running and the PlayStation App is installed.")


class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def _json(self, code, obj):
        b = json.dumps(obj).encode(); self.send_response(code); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

    def do_GET(self):
        self._json(200, health()) if self.path == "/healthz" else self._json(404, {})

    def do_POST(self):
        u = urlparse(self.path)
        if u.path != "/grab":
            return self._json(404, {})
        if not TOKEN or not hmac.compare_digest(self.headers.get("X-GT7C-Grab", ""), TOKEN):
            return self._json(401, dict(error="bad or missing token"))
        if not lock.acquire(blocking=False):
            return self._json(409, dict(error="already fetching a capture"))
        t0 = time.time()
        try:
            data, name, label, total = grab(max(1, min(30, int(parse_qs(u.query).get("index", ["1"])[0]))), parse_qs(u.query).get("mode", [""])[0])
            self.send_response(200); self.send_header("Content-Type", "image/jpeg"); self.send_header("Content-Length", str(len(data)))
            self.send_header("X-Capture-Id", name); self.send_header("X-Capture-Label", label.encode("ascii", "ignore").decode())
            self.send_header("X-Capture-Count", str(total)); self.end_headers(); self.wfile.write(data)
            print(f"grab: {label} -> {name} {len(data)} bytes in {time.time() - t0:.0f} s", flush=True)
        except Fail as e:
            print(f"grab failed: {e}", flush=True); self._json(e.code, dict(error=str(e)))
        except Exception as e:
            print(f"grab failed: {e!r}", flush=True); self._json(500, dict(error=f"{type(e).__name__}: {e}"))
        finally:
            lock.release()


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", int(os.environ.get("GRAB_PORT", "6081"))), H).serve_forever()
