"""Settings in the app: defaults from the environment, the admin password, write-only secrets, the on/off answers of every
optional part, and reading an uploaded screenshot with a stand-in vision model."""
import json, os, shutil, stat, sys, tempfile, threading, urllib.error, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
tmp = tempfile.mkdtemp()
for k in [k for k in os.environ if k.startswith("GT7C_")]:
    del os.environ[k]
os.environ.update(GT7C_DATA=tmp, GT7C_PS5="192.0.2.10", GT7C_MAX_CALLS="5", GT7C_GRAB_TOKEN_FILE=os.path.join(tmp, "shared", "grab-token"))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [ROOT, os.path.join(ROOT, "tests")]
from gt7copilot import capture as CAP, checks, cli, library as L, server, settings as CFG, voice as V
from gt7copilot.collector import Collector
from gt7copilot.copilot import Copilot
from gt7copilot.store import Store

ok = lambda cond, what: (print(("ok   " if cond else "FAIL ") + what), cond or sys.exit(1))

# ---- the store -----------------------------------------------------------------------------------------------------------
ok(CFG.get("ps5") == "192.0.2.10" and CFG.get("max_calls") == 5, "the environment gives the first values")
ok(CFG.get("voice_on") is False and CFG.get("screenshots_on") is False and CFG.get("agent_on") is False and CFG.get("earpiece_on") is False,
   "every optional part starts switched off")
tok = CFG.get("grab_token"); ok(len(tok) > 20 and open(os.environ["GT7C_GRAB_TOKEN_FILE"]).read() == tok, "the phone token is made once, in the shared file")
f = CFG.features()
ok(f["console"]["ready"] and f["screenshots"]["why"] == "Screenshots are turned off in Settings." and f["agent_door"]["why"] == "The agent door is turned off in Settings.",
   "features says what is off, in a sentence")
CFG.save(dict(ps5="192.0.2.20", max_calls=3))
ok(CFG.get("ps5") == "192.0.2.20" and stat.S_IMODE(os.stat(CFG.FILE).st_mode) == 0o600, "saved values win and the file is owner-only")
CFG.reload(); ok(CFG.get("max_calls") == 3, "values survive a restart")
for bad in (dict(max_calls=99), dict(llm_url="ollama:11434"), dict(heartbeat="Z"), dict(nonsense=1), dict(wake_names=" , ")):
    try: CFG.save(bad); ok(False, f"refuses {bad}")
    except ValueError: pass
ok(True, "values that make no sense are refused")
CFG.save(dict(llm_key="sk-secret", screenshots_on=True)); CFG.save(dict(llm_key=""))
ok(CFG.get("llm_key") == "sk-secret", "an empty secret field keeps the secret")
ok("sk-secret" not in json.dumps(CFG.view()) and any(r.get("set") for g in CFG.view() for r in g["rows"] if r["key"] == "llm_key"), "the view shows a secret only as set")
CFG.save(dict(clear=["llm_key"])); ok(CFG.get("llm_key") == "", "a secret can be cleared")
ok(CFG.why_not("screenshots").startswith("Not set in Settings: Vision model address"), "on but not configured names what is missing")
V.CFG.save(dict(wake_names="jarvis, jarvus"))
vo = V.Voice(Collector(Store(), lambda m: None), Copilot(lambda *a: None, log=lambda m: None), lambda *a: None, server.Hub(), lambda m: None, Store())
ok(vo.handle("Jarvus, help")["command"] == "help", "the wake name follows Settings at once")
vo.open_until = 0                       # not inside the conversation the answer opened: there a sentence needs no name at all
ok(vo.handle("Copilot, help")["command"] is None, "...and the old name is no longer one")

# ---- over HTTP -----------------------------------------------------------------------------------------------------------
PORT = 18771; URL = f"http://127.0.0.1:{PORT}"
hub = server.Hub(); col = vo.col
server.serve(PORT, hub, lambda: dict(live=False), lambda *a: None, lambda on: None, hear=vo.hear, hear_text=vo.hear_text, shot=vo.shot,
             tests=dict(vision=lambda body: checks.vision(), phone=lambda body: checks.phone(), whisper=lambda body: checks.whisper()))
jar = {}
def call(path, body=None, headers=None, raw=None):
    h = {"X-GT7C": "1", "Content-Type": "application/json", **({"Cookie": "gt7c_admin=" + jar["c"]} if jar.get("c") else {}), **(headers or {})}
    data = raw if raw is not None else (None if body is None else json.dumps(body).encode())
    try:
        with urllib.request.urlopen(urllib.request.Request(URL + path, data=data, headers=h, method="POST" if data is not None else "GET"), timeout=20) as r:
            c = r.headers.get("Set-Cookie")
            if c: jar["c"] = c.split(";")[0].split("=", 1)[1]
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")

st, d = call("/api/settings"); ok(st == 200 and d["admin_set"] is False and "groups" not in d, "before sign-in the page gets no settings, only what is on")
ok(call("/api/settings", dict(ps5="192.0.2.30"))[0] == 401 and CFG.get("ps5") == "192.0.2.20", "nothing can be changed without signing in")
ok(call("/api/admin/setup", dict(password="short"))[0] == 400, "a short password is refused")
st, d = call("/api/admin/setup", dict(password="correct horse")); ok(st == 200 and d["signed_in"] and jar.get("c"), "the first visit sets the admin password and signs in")
ok(call("/api/admin/setup", dict(password="another one"))[0] == 409, "the password cannot be set a second time that way")
saved = json.load(open(CFG.FILE)); ok("correct horse" not in json.dumps(saved) and saved["admin"]["hash"], "only a salted hash is stored")
st, d = call("/api/settings"); ok(d["signed_in"] and d["groups"][0]["rows"][0]["value"] == "192.0.2.20", "signed in, the settings are shown")
st, d = call("/api/settings", dict(ps5="192.0.2.30"), headers={"X-GT7C": "0"}); ok(st == 400, "a request without the page's own header is refused")
st, d = call("/api/settings", dict(generate=["agent_token"], agent_on=True))
agent = d["new_tokens"]["agent_token"]; ok(st == 200 and len(agent) > 20 and agent not in json.dumps(d["groups"]), "a generated token is shown once, to the page that asked")
st, d = call("/api/settings"); ok(agent not in json.dumps(d), "...and never again")
good, c = jar["c"], None
jar["c"] = ""; ok(call("/api/admin/login", dict(password="wrong"))[0] == 401 and call("/api/admin/login", dict(password="correct horse"))[0] == 200, "sign-in checks the password")
for n in range(10): CFG.check_password("wrong", "192.0.2.66")
try: CFG.check_password("correct horse", "192.0.2.66"); ok(False, "lockout")
except ValueError: ok(CFG.check_password("correct horse", "192.0.2.67"), "ten wrong passwords lock out the address they came from, and nobody else")
call("/api/admin/logout", {}); ok(call("/api/settings", dict(ps5="x"))[0] == 401, "signing out ends the session")
call("/api/admin/login", dict(password="correct horse"))

# ---- on / off answers ---------------------------------------------------------------------------------------------------
def agent_call(argv, token=agent):
    try:
        with urllib.request.urlopen(urllib.request.Request(URL + "/api/cli", json.dumps(dict(argv=argv)).encode(), {"Authorization": "Bearer " + token}), timeout=20) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")
ok(agent_call(["tracks"])[0] == 200 and agent_call(["tracks"], "nope")[0] == 401, "the agent door opens with its token")
for argv in (["tune-set", "24", CFG.FILE], ["lib-add", "24", CFG.FILE], ["know-add", CFG.FILE], ["shot-file", CFG.FILE], ["tune-set", "24"]):
    st, d = agent_call(argv); ok(st == 400 and d["error"] == "send the JSON, not a path", f"the agent door reads no file of this machine: {argv[0]} with a path is refused")
ok(agent_call(["tune-show", "24"]) == (200, []) and "admin" in json.load(open(CFG.FILE)), "...so the settings file (hash, keys, tokens) cannot be filed as a sheet and read back")
def raw_post(path, headers):
    try:
        with urllib.request.urlopen(urllib.request.Request(URL + path, data=b"", headers=headers, method="POST"), timeout=10) as r: return r.status
    except urllib.error.HTTPError as e: return e.code
ok(raw_post("/api/say?text=hi", {}) == 400 and raw_post("/api/enable?on=0", {}) == 400 and raw_post("/api/screenshot", {}) == 400 and raw_post("/api/screenshots/read", {}) == 400,
   "what changes or starts something is refused without the page's own header (a form on another site cannot send it)")
ok(raw_post("/api/say?text=hi", {"X-GT7C": "1"}) == 200 and raw_post("/api/say?text=hi", {"Authorization": "Bearer " + agent}) == 200
   and raw_post("/api/say?text=hi", {"Authorization": "Bearer nope"}) == 400, "the page's header or the agent token opens it")
try: urllib.request.urlopen(URL + "/api/say?text=hi"); ok(False, "GET say")
except urllib.error.HTTPError as e: ok(e.code == 405, "...and a plain link (GET) never does")
st, d = agent_call(["features"]); ok(d["agent_door"]["ready"] and not d["screenshots"]["ready"], "an agent can ask what is switched on")
call("/api/settings", dict(agent_on=False)); st, d = agent_call(["tracks"])
ok(st == 403 and "turned off in Settings" in d["error"], "switched off, the agent door says so")
ok(call("/api/screenshot", raw=b"\xff\xd8\xff rest")[1]["reply"].startswith("Not set in Settings: Vision model address"), "an upload without a vision model says what is missing")
call("/api/settings", dict(screenshots_on=False))
st, d = call("/api/screenshot", raw=b"\xff\xd8\xff rest"); ok(st == 409 and d["reply"] == "Screenshots are turned off in Settings.", "switched off, an upload says so")
ok(vo.handle("jarvis take a screenshot")["reply"] == "Screenshots are turned off in Settings.", "...and so does the voice")
admin = lambda path: urllib.request.Request(URL + path, headers={"Cookie": "gt7c_admin=" + jar["c"]})
try: urllib.request.urlopen(admin("/earpiece/setup.ps1")); ok(False, "installer off")
except urllib.error.HTTPError as e: ok(e.code == 404 and "turned off in Settings" in e.read().decode(), "switched off, the earpiece installer says so")
st, d = call("/api/settings", dict(earpiece_on=True, generate=["earpiece_token"])); ear = d["new_tokens"]["earpiece_token"]
try: urllib.request.urlopen(URL + "/earpiece/setup.ps1"); ok(False, "installer without sign-in")
except urllib.error.HTTPError as e: ok(e.code == 401 and ear not in e.read().decode(), "the installer holds the token: without the admin's sign-in it is not handed out")
body = urllib.request.urlopen(admin("/earpiece/setup.ps1")).read().decode(); ok(ear in body and "'0' -eq '1'" in body, "switched on, the installer carries the token and the voice control state")
def hear(tok):
    try:
        with urllib.request.urlopen(urllib.request.Request(URL + "/api/hear", data=b"RIFF" + b"\0" * 400, headers={"X-GT7C-Earpiece": tok}), timeout=10) as r: return r.status, json.load(r)
    except urllib.error.HTTPError as e: return e.code, json.loads(e.read() or b"{}")
st, d = hear(ear); ok(st == 409 and d["error"] == "Voice control is turned off in Settings.", "speech arriving while voice control is off is refused with the reason")
call("/api/settings", dict(earpiece_on=False)); ok(hear(ear)[0] == 401, "switched off, the earpiece token stops working")

# ---- an uploaded screenshot, read by a stand-in vision model ---------------------------------------------------------
asked = []
PAGE1 = dict(screen="car_settings_1", car="Nissan 180SX Type X '96", summary="Car settings page 1", sheet=dict(
    pp=462.57, power=203, power_unit="HP", weight=1220, weight_unit="kg", tyres=dict(front="Sports: Hard", rear="Sports: Hard"),
    suspension=dict(ride_height_mm=[110, 110], anti_roll_bar=[4, 5], damping_compression_pct=[30, 30], damping_expansion_pct=[40, 40],
                    natural_frequency_hz=[2.1, 2.2], negative_camber_deg=[1.5, 1.0], toe_deg=[0.0, 0.2], toe_direction=["none", "in"]),
    differential=dict(initial_torque=[None, 10], acceleration_sensitivity=[None, 20], braking_sensitivity=[None, 15]), aero=dict(downforce=[0, 0])))
class Model(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_POST(self):
        req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        asked.append((self.path, self.headers.get("Authorization"), req))
        text = "OK" if "single word OK" in req["messages"][0]["content"][0]["text"] else "Here it is:\n" + json.dumps(PAGE1)
        b = json.dumps(dict(choices=[dict(message=dict(content=text))])).encode()
        self.send_response(200); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
m = ThreadingHTTPServer(("127.0.0.1", 18772), Model); threading.Thread(target=m.serve_forever, daemon=True).start()
call("/api/settings", dict(screenshots_on=True, llm_url="http://127.0.0.1:18772/v1/", llm_key="k1", vision_model="seer"))
st, d = call("/api/settings/test", dict(what="vision")); ok(d["ok"] and "OK" in d["note"], "the Test button asks the vision model with a picture")
ok(asked[-1][0] == "/v1/chat/completions" and asked[-1][1] == "Bearer k1" and asked[-1][2]["model"] == "seer"
   and asked[-1][2]["messages"][0]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,"), "...at the saved address, with the key and the model")
st, d = call("/api/settings/test", dict(what="phone")); ok(not d["ok"] and "virtual phone is turned off" in d["note"], "the phone test says the phone is off")
st, d = call("/api/screenshot", raw=b"this is not a picture"); ok(st == 409 and "not a picture" in d["reply"], "a file that is not a picture is refused")
st, d = call("/api/screenshot", raw=b"\x89PNG\r\n\x1a\n" + b"x" * 64); print("     ", d["reply"])
ok(st == 200 and d["ok"] and d["reply"].startswith("Sheet filed for the Nissan 180SX"), "an uploaded settings screen is read and the sheet filed for the car it names")
ok(asked[-1][2]["messages"][0]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,"), "the picture goes to the model with its real type")
car = cli.car_find("180SX Type X")[0]["code"]; t = L.current_tune(Store(), car)
ok(t and t["sheet"]["suspension"]["anti_roll_bar"] == [4, 5] and t["sheet"]["suspension"]["toe_deg"] == [0, 0.2] and t["sheet"]["weight_kg"] == 1220, "the filed sheet holds what was read")
st, d = call("/api/screenshot", raw=b"\xff\xd8\xff" + b"x" * 64); ok(d["reply"].startswith("Same sheet as before"), "the same screen again changes nothing")
PAGE1["sheet"]["suspension"]["anti_roll_bar"] = [14, 5]
st, d = call("/api/screenshot", raw=b"\xff\xd8\xff" + b"x" * 64); ok(st == 409 and "could not read that sheet cleanly" in d["reply"], "a value the game does not allow is not filed")
st, d = call("/api/screenshot?source=phone", raw=b""); ok(st == 409 and "virtual phone is turned off" in d["reply"], "fetching from the phone says the phone is off")
call("/api/settings", dict(agent_on=True)); PAGE1["sheet"]["suspension"]["anti_roll_bar"] = [3, 5]
cli.URL = URL; pic = os.path.join(tmp, "shot.png"); open(pic, "wb").write(b"\x89PNG\r\n\x1a\n" + b"y" * 64)
import base64
st, d = agent_call(["shot-file", dict(image_b64=base64.b64encode(open(pic, "rb").read()).decode())]); print("     ", d.get("reply"))
ok(st == 200 and d["ok"] and "1 change" in d["reply"], "an agent can hand in a picture through the agent door")
import subprocess
client = [sys.executable, os.path.join(ROOT, "agent-skill", "gt7copilot")]
r = subprocess.run(client + ["features"], capture_output=True, text=True, env=dict(os.environ, GT7C_URL=URL, GT7C_TOKEN=agent, HOME=tmp))
ok(r.returncode == 0 and json.loads(r.stdout)["screenshots"]["ready"] is True, "the agents' own client reaches the door with nothing but Python")
r = subprocess.run(client + ["shot-file", pic], capture_output=True, text=True, env=dict(os.environ, GT7C_URL=URL, GT7C_TOKEN=agent, HOME=tmp))
ok(json.loads(r.stdout)["reply"].startswith("Same sheet as before"), "...and hands in a picture file")
r = subprocess.run(client + ["tracks"], capture_output=True, text=True, env=dict(os.environ, GT7C_URL=URL, GT7C_TOKEN="old", HOME=tmp))
ok(r.returncode == 1 and "token" in json.loads(r.stdout)["error"], "...and reports a wrong token")
m.shutdown(); shutil.rmtree(tmp); print("settings: all passed")
