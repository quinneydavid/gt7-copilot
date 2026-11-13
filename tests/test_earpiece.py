"""The earpiece against a real local server: the token rules, the installer downloads, calls played, status on the page.
The Windows parts (audio device, Bluetooth, SimHub) are replaced by a stand-in; they can only be tested on the PC.
The Mac parts run here against a stand-in sound library and stand-in system tools; they have not run on a real Mac."""
import io, json, os, stat, subprocess, sys, tempfile, threading, time, types, urllib.error, urllib.request, wave
tmp = tempfile.mkdtemp()
os.environ.update(GT7C_DATA=tmp, GT7C_TOKEN="agent-token", GT7C_EARPIECE_TOKEN="ear-token", GT7C_EARPIECE_HOME=tmp, GT7C_ADMIN_PASSWORD="test-password")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [ROOT, os.path.join(ROOT, "tests")]
sys.path.insert(0, os.path.join(ROOT, "earpiece"))
from gt7copilot import server
from gt7copilot.tts import CACHE
import earpiece as E

PORT = 18765; URL = f"http://127.0.0.1:{PORT}"
live = {"live": False}
hub = server.Hub()
server.serve(PORT, hub, lambda: dict(live=live["live"]), lambda *a: None, lambda on: None)
os.makedirs(CACHE, exist_ok=True)
buf = io.BytesIO()
with wave.open(buf, "wb") as w: w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000); w.writeframes(b"\0\0" * 2400)
open(os.path.join(CACHE, "abc.wav"), "wb").write(buf.getvalue())


def get(path, headers=None, method="GET", body=None):
    req = urllib.request.Request(URL + path, headers=headers or {}, method=method, data=body)
    try:
        with urllib.request.urlopen(req, timeout=5) as r: return r.status, r.read(200_000 if path != "/events" else 20)
    except urllib.error.HTTPError as e: return e.code, e.read()

ok = lambda cond, what: (print(("ok   " if cond else "FAIL ") + what), cond or sys.exit(1))
EAR = {"X-GT7C-Earpiece": "ear-token"}

# token rules
ok(get("/events", {"X-GT7C-Earpiece": "wrong"})[0] == 401, "wrong earpiece token is refused")
ok(get("/api/state", EAR)[0] == 403, "earpiece token cannot read the rest of the page API")
ok(get("/api/say?text=hi", EAR)[0] == 403, "earpiece token cannot make the copilot speak")
ok(get("/api/cli", EAR, "POST", b"{}")[0] == 404, "earpiece token cannot use the agent door")
ok(get("/api/cli", {"Authorization": "Bearer ear-token"}, "POST", b'{"argv":["tracks"]}')[0] == 401, "earpiece token is not the agent token")
ok(get("/api/earpiece", {"X-GT7C-Earpiece": "agent-token"}, "POST", b"{}")[0] == 401, "agent token cannot report as the earpiece")
ok(get("/api/earpiece", None, "POST", b"{}")[0] == 401, "status report needs the token")
ok(get("/audio/abc.wav", EAR)[0] == 200 and get("/earpiece/earpiece.py", EAR)[0] == 200, "earpiece may fetch clips and its own program")
SITE = {"Host": "copilot.example", "X-Forwarded-Proto": "https", "X-Forwarded-Host": "copilot.example"}
st, body = get("/earpiece/setup.ps1", SITE)
ok(st == 401 and b"ear-token" not in body and get("/earpiece/setup-mac.sh", SITE)[0] == 401 and get("/earpiece/setup.ps1", dict(SITE, **EAR))[0] == 403,
   "the installer (it holds the token) is not handed out without the admin's sign-in")
req = urllib.request.Request(URL + "/api/admin/login", data=b'{"password":"test-password"}', headers={"X-GT7C": "1"})
ADMIN = {"Cookie": urllib.request.urlopen(req, timeout=5).headers["Set-Cookie"].split(";")[0]}
for bad in ({"X-Forwarded-Host": "x';calc;'"}, {"X-Forwarded-Host": "a b"}, {"X-Forwarded-Host": "copilot.example/$(id)"}, {"X-Forwarded-Proto": "https';x='"}):
    ok(get("/earpiece/setup.ps1", dict(SITE, **ADMIN, **bad))[0] == 400, f"an address that would break out of the script is refused: {list(bad.values())[0]}")
st, body = get("/earpiece/setup.ps1", dict(SITE, **ADMIN))
ok(st == 200 and b"'https://copilot.example'" in body and b"'ear-token'" in body and b"__GT7C" not in body, "installer comes with address and token filled in")
ok(json.loads(get("/api/state")[1])["earpiece"] is None, "page: no earpiece before it reports")


class FakePC:
    def __init__(self): self.connected = False; self.simhub = False; self.played = []; self.connects = 0; self.started = 0
    def airpod(self): return self.connected, "AirPods (test)"
    def connect(self): self.connects += 1; self.connected = True; return True
    def set_volume(self, level): self.volume = level; return (0.0, True)
    def play(self, wav): self.played.append(len(wav)); return self.connected
    def simhub_running(self): return self.simhub
    def start_simhub(self): self.started += 1; self.simhub = True; return True
    def simhub_detail(self): return self.detail

pc = FakePC(); pc.detail = {"game": "GranTurismo7", "data": False}
ep = E.Earpiece(dict(E.DEFAULTS, url=URL, token="ear-token", connect_when="live"), pc)
ep.ensure_simhub(); ok(pc.started == 1, "SimHub started when it was not running")
for f in (ep.listen, ep.speak): threading.Thread(target=f, daemon=True).start()
rep = ep.tick()
ok(rep["airpod"] is False and pc.connects == 0, "idle: AirPod left alone (no connect while GT7 is not live)")
s = json.loads(get("/api/state")[1])["earpiece"]
ok(s and s["airpod"] is False and s["simhub"] is True and s["version"] == E.VERSION, "page shows the earpiece report")
ok(s["simhub_api"] is True and s["simhub_game"] == "GranTurismo7" and s["simhub_data"] is False, "page shows what SimHub says: its game and whether data arrives")

live["live"] = True; pc.simhub = False
t0 = time.time()
while not ep.live and time.time() - t0 < 6: time.sleep(0.1)
ok(ep.live, "earpiece hears that GT7 went live")
ok(pc.started == 2, "SimHub started again when GT7 goes live")
ep.tick(); ok(pc.connects == 1 and pc.connected, "live: asks Windows to connect the AirPod")
ep.tick(); ok(pc.connects == 1, "connected: no more connect requests")
ok(getattr(pc, "volume", None) == 0.6, "AirPod volume set and unmuted when it connects")

hub.publish(dict(type="say", text="Turn one. Brake later.", kind="corner", url="/audio/abc.wav", deadline=time.time() + 5))
t0 = time.time()
while not pc.played and time.time() - t0 < 5: time.sleep(0.05)
ok(len(pc.played) == 1 and ep.played == 1, "a call is fetched and played")
hub.publish(dict(type="say", text="old", kind="corner", url="/audio/abc.wav", deadline=time.time() - 10))
time.sleep(1.5); ok(len(pc.played) == 1 and ep.skipped == 1, "a call past its deadline is dropped")
ok(json.loads(get("/api/state")[1])["earpiece"]["airpod"] is True, "page shows AirPod connected")
server.EARPIECE_STALE = 0.1; time.sleep(0.3)
ok(json.loads(get("/api/state")[1])["earpiece"] is None, "page: earpiece shown as not running when reports stop")

server.EARPIECE_STALE = 30; ep.diag_at = 0; ep.tick()
d = json.loads(get("/api/state")[1])
ok(d["earpiece_diag"] and "gt7copilot earpiece" in d["earpiece_diag"]["text"], "the earpiece's full picture of the PC reaches the server")
ok("diag" not in d["earpiece"], "the picture stays out of the live stream")

# ---- the Mac: the platform layer on a stand-in sound library --------------------------------------------------------
class FakeStream:
    def __init__(self, **kw): self.kw = kw; self.active = False
    def start(self): self.active = True
    def abort(self): self.active = False
    def close(self): pass
sd = types.ModuleType("sounddevice"); sd.devices = [dict(name="MacBook Pro Speakers", max_output_channels=2, max_input_channels=0),
                                                    dict(name="MacBook Pro Microphone", max_output_channels=0, max_input_channels=1)]
sd.played = []; sd.inits = 0
sd.query_devices = lambda: list(sd.devices)
sd._terminate = lambda: None
sd._initialize = lambda: setattr(sd, "inits", sd.inits + 1)
sd.play = lambda pcm, rate, device=None, blocking=False: sd.played.append((pcm.shape, rate, device))
sd.InputStream = FakeStream
sys.modules["sounddevice"] = sd
tools = {"paired": [dict(name="AirPods Pro", address="aa-bb-cc-dd-ee-ff", connected=False)], "calls": []}
def fake_run(cmd, **kw):
    tools["calls"].append(cmd)
    if "--paired" in cmd: return types.SimpleNamespace(returncode=0, stdout=json.dumps(tools["paired"]), stderr="")
    sd.devices += [dict(name="AirPods Pro", max_output_channels=2, max_input_channels=0), dict(name="AirPods Pro", max_output_channels=0, max_input_channels=1)]
    return types.SimpleNamespace(returncode=0, stdout="", stderr="")
mac = E.MacPC(dict(E.DEFAULTS, device="AirPods"), run=fake_run, which=lambda n: None)
mac._blueutil = lambda: None
ok(mac.airpod() == (False, None) and mac.connect() is False and not tools["calls"], "Mac without blueutil: the device is reported away and connecting is left to macOS")
mac._blueutil = lambda: "/opt/homebrew/bin/blueutil"
ok(mac.airpod() == (False, "AirPods Pro"), "Mac with blueutil: a paired device that is away is found by name")
ok(any(n == "AirPods Pro" and not a for n, a, _ in mac.endpoints()), "...and listed as not connected")
ok(mac.play(buf.getvalue()) is False, "nothing is played while the device is away")
ok(mac.connect() is True and tools["calls"][-1] == ["/opt/homebrew/bin/blueutil", "--connect", "aa-bb-cc-dd-ee-ff"], "connect asks blueutil for the paired device's address")
ok(mac.airpod() == (True, "AirPods Pro"), "once macOS has it, the device counts as connected")
ok(mac.play(buf.getvalue()) is True and sd.played[-1] == ((2400, 2), 24000, 2), "a call is played into that device, mono doubled to stereo, at the clip's own rate")
got = []
ok(mac.mic_start(got.append) is True and mac.mic.kw["device"] == 3 and mac.mic.kw["samplerate"] == 16000 and mac.mic_alive(), "the microphone of the same device is opened at 16 kHz")
n = sd.inits; mac.play(buf.getvalue()); ok(sd.inits == n, "the device list is not re-read while the microphone is open (that would close it)")
mac.mic_stop(); ok(not mac.mic_alive(), "the microphone can be closed")
ok(mac.simhub_running() is None and mac.start_simhub() is False and mac.set_volume(0.6) is None, "SimHub and the volume are not applicable on a Mac")
ep2 = E.Earpiece(dict(E.DEFAULTS, url=URL, token="ear-token", voice=False, connect_when="always", start_simhub=True), mac)
ep2.ensure_simhub(); rep = ep2.tick()
ok(rep["airpod"] is True and rep["simhub"] is None and rep["device"] == "AirPods Pro", "the earpiece runs on the Mac layer and reports to the server")
E.MAC = True
text = E.doctor(dict(E.DEFAULTS, device="AirPods", url=URL, token="ear-token"), mac, server=False)
E.MAC = False
ok("blueutil found" in text and "microphones (2)" in text and "SimHub" not in text and "name matches" in text, "doctor on a Mac lists devices and microphones, without SimHub")
ok(E.pid_alive(os.getpid()) and not E.pid_alive(2 ** 22 + 12345), "the listener's check on its parent needs no extra library")

# ---- the Mac installer: downloaded with address and token, then run for real with the system tools replaced ------------
st, body = get("/earpiece/setup-mac.sh", dict(ADMIN, **{"Host": "copilot.example", "X-Forwarded-Proto": "https"}))
ok(st == 200 and b"URL='https://copilot.example'" in body and b"TOKEN='ear-token'" in body and b"__GT7C" not in body, "the Mac installer comes with address and token filled in")
home = os.path.join(tmp, "machome"); fake = os.path.join(tmp, "fakebin"); os.makedirs(fake); os.makedirs(home)
script = os.path.join(tmp, "setup-mac.sh"); open(script, "wb").write(body.replace(b"https://copilot.example", URL.encode()))
ok(subprocess.run(["bash", "-n", script]).returncode == 0, "it is valid shell")
def tool(name, text):
    p = os.path.join(fake, name); open(p, "w").write("#!/bin/sh\n" + text + "\n"); os.chmod(p, 0o755)
tool("uname", "echo Darwin")
tool("xcode-select", "exit 0")
tool("launchctl", f'echo "$@" >> "{tmp}/launchctl.log"')
real_curl = "/usr/bin/curl"
app = os.path.join(home, "Library", "Application Support", "GT7Copilot")
os.makedirs(os.path.join(app, "venv", "bin"))
vpy = os.path.join(app, "venv", "bin", "python")            # a venv that exists already: no download of packages in a test
open(vpy, "w").write(f'#!/bin/sh\nif [ "$1" = -m ] && [ "$2" = pip ]; then exit 0; fi\nexec "{sys.executable}" "$@"\n'); os.chmod(vpy, 0o755)
env = dict(os.environ, HOME=home, PATH=fake + os.pathsep + os.environ["PATH"])
if os.path.exists(real_curl) and os.path.exists("/usr/bin/python3"):
    r = subprocess.run(["bash", script], env=env, capture_output=True, text=True, stdin=subprocess.DEVNULL)
    ok(r.returncode == 0 and "DONE" in r.stdout, "the installer runs through" + ("" if r.returncode == 0 else ": " + r.stdout[-300:] + r.stderr[-300:]))
    cfg = json.load(open(os.path.join(app, "earpiece.json")))
    ok(cfg["url"] == URL and cfg["token"] == "ear-token" and cfg["device"] == "AirPods" and cfg["voice"] is False and cfg["start_simhub"] is False,
       "it writes the settings: address, token, device, voice as on the server")
    ok(stat.S_IMODE(os.stat(os.path.join(app, "earpiece.json")).st_mode) == 0o600, "the settings file (it holds the token) is owner-only")
    ok(open(os.path.join(app, "earpiece.py")).read() == open(os.path.join(ROOT, "earpiece", "earpiece.py")).read(), "it fetches the program from the server with the token")
    plist = open(os.path.join(home, "Library", "LaunchAgents", "com.gt7copilot.earpiece.plist")).read()
    import xml.dom.minidom; xml.dom.minidom.parseString(plist)
    ok(f"<string>{vpy}</string>" in plist and "<key>KeepAlive</key><true/>" in plist and "<string>Aqua</string>" in plist and "Library/Logs/GT7Copilot" in plist,
       "the LaunchAgent runs the program from the user's session and keeps it alive")
    calls = open(os.path.join(tmp, "launchctl.log")).read()
    ok(f"bootstrap gui/{os.getuid()} " in calls and "bootout" in calls, "launchd is told to load it for this user")
    cfg["device"] = "Beats"; cfg["voice"] = True; json.dump(cfg, open(os.path.join(app, "earpiece.json"), "w"))
    subprocess.run(["bash", script], env=env, capture_output=True, text=True, stdin=subprocess.DEVNULL)
    cfg = json.load(open(os.path.join(app, "earpiece.json")))
    ok(cfg["device"] == "Beats" and cfg["voice"] is True, "running it again updates the program and keeps the device and voice choices")
    r = subprocess.run(["bash", script, "uninstall"], env=env, capture_output=True, text=True)
    ok(r.returncode == 0 and not os.path.exists(app) and not os.path.exists(os.path.join(home, "Library", "LaunchAgents", "com.gt7copilot.earpiece.plist")), "uninstall removes the program and the LaunchAgent")
    tool("uname", "echo Linux")
    ok(subprocess.run(["bash", script], env=env, capture_output=True, text=True).returncode == 1, "on another system it stops with a sentence")
else:
    print("skip the installer run: no curl or /usr/bin/python3 here")
print("earpiece: all passed")
