"""The page's data: home, cars (with search), one car, tracks, sessions, screenshots, and the phone screen pass-through,
on the simulated driver. Checks what the page relies on, and that the doors that need the admin stay shut without them."""
import json, os, shutil, sys, tempfile, threading, urllib.error, urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [ROOT, os.path.join(ROOT, "tests")]
tmp = tempfile.mkdtemp(); os.environ["GT7C_DATA"] = tmp; os.environ["GT7C_ADMIN_PASSWORD"] = "test-password"
import sim
from gt7copilot import api, capture as CAP, checks, cli, settings as CFG
from gt7copilot.collector import Collector
from gt7copilot.packet import decrypt, parse
from gt7copilot.server import Hub, serve
from gt7copilot.store import Store

res = []
def ok(name, cond):
    print(("PASS " if cond else "FAIL ") + name); res.append(bool(cond))

st = Store(tmp)
SHEET = dict(pp=550.2, tyres=dict(front="Sports Soft", rear="Sports Soft"),
             suspension=dict(anti_roll_bar=[4, 6], damping_compression_pct=[30, 32], damping_expansion_pct=[40, 42], natural_frequency_hz=[2.1, 2.3],
                             negative_camber_deg=[2.0, 1.5], toe_deg=[-0.05, 0.2], ride_height_mm=[90, 95]),
             differential=dict(initial_torque=[None, 10], acceleration_sensitivity=[None, 20], braking_sensitivity=[None, 15]), brake_balance=-1)
def drive(car, laps):
    c = Collector(st, log=lambda m: None); wall = 1000.0
    for pkt in sim.packets(laps, car=car):
        row, meta = parse(decrypt(pkt)); wall += 1 / 60; c.feed(row, meta, wall)
    return c
drive(3265, [{}, {}, {"understeer": 1.6}, {"understeer": 1.6}])
cli.run(st, ["tune-set", "3265", SHEET])
col = drive(3265, [{}, {"slow": {1: 0.9}}, {}, {}])
drive(2156, [{"slow": {0: 0.9}}, {"slow": {0: 0.9}}, {"slow": {0: 0.9}}])

o = api.overview()
ok("home: totals", o["totals"]["laps"] == 11 and o["totals"]["cars"] == 2 and o["totals"]["tracks"] == 1 and o["totals"]["km"] > 0)
ok("home: most driven car first", o["cars"][0]["code"] == 3265 and o["cars"][0]["laps"] == 8)
ok("home: next step is for the last car driven", o["next"]["car_code"] == 2156)
ok("home: one best per car and track", len(o["records"]) == 2)
cs = api.cars()
ok("cars: only the driver's own without a search", {c["code"] for c in cs["cars"]} == {3265, 2156} and cs["total_in_game"] > 400)
found = api.cars("86 gr.b")["cars"]
ok("cars: search covers the whole game, driven first", found and found[0]["code"] == 3265 and found[0]["laps"] == 8)
ok("cars: undriven cars are found too", any(c["laps"] == 0 for c in api.cars("911")["cars"]))
c = api.car(3265)
ok("car: settings laid out as the game does", c["sheet"]["view"][0]["section"] == "Tires" and c["sheet"]["pp"] == 550.2)
ok("car: suggested tune from the latest session with enough laps", c["suggested"]["based_on"]["laps"] >= 3 and c["suggested"]["advice"]["ready"] and not c["suggested"]["sheet_newer"])
first = st.q("SELECT id FROM sessions WHERE car=3265 ORDER BY id LIMIT 1")[0]["id"]
ok("car: an older session can be picked, and is marked as older than the sheet", api.car(3265, first)["suggested"]["sheet_newer"])
ok("car: bests and sessions", c["bests"][0]["laps"] == 8 and len(c["sessions"]) == 2 and c["sessions"][0]["record"] in (True, False))
ok("car: never driven", api.car(1905)["laps"] == 0 and api.car(1905)["suggested"]["advice"] is None)
t = api.track(1)
ok("track: cars ranked by best lap", [x["best_ms"] for x in t["cars"]] == sorted(x["best_ms"] for x in t["cars"]) and t["cars"][0]["gap_s"] == 0)
ok("track: fastest car, its tune and its corners", t["recommended"]["car_code"] == t["cars"][0]["code"] and t["recommended"]["corners"] and len(t["sessions"]) == 3)
ok("sessions: filter by car", len(api.sessions(car=2156)) == 1 and len(api.sessions()) == 3)

# every picture that is read is kept, with what it showed and what was done with it
CAP.read = lambda image: dict(screen="other", summary="A replay screen")
kept = []
try: CAP.take(col, st, lambda m: None, checks._png(), kept)
except RuntimeError: pass
sh = api.shots()
ok("screenshots: a picture that was not filed is kept too", len(kept) == 1 and sh["all"] == 1 and sh["shots"][0]["kind"] == "other" and os.path.exists(api.shot_file(kept[0])[0]))
api.shot_set(kept[0], car=3265, cover=True)
ok("screenshots: a picture can become the car's picture", api.car(3265)["picture"] == f"/shots/{kept[0]}" and api.shots(car=3265)["total"] == 1)

# over http: the page, the pictures, and the phone's screen for the admin only
class Phone(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        body = f"phone says {self.path} cookie={self.headers.get('Cookie')}".encode()
        self.send_response(200); self.send_header("Content-Type", "text/plain"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
ph = HTTPServer(("127.0.0.1", 18792), Phone); threading.Thread(target=ph.serve_forever, daemon=True).start()
serve(18791, Hub(), lambda: dict(col.state()), lambda *x: None, lambda on: None)
B = "http://127.0.0.1:18791"
def http(path, data=None, cookie=None):
    req = urllib.request.Request(B + path, data=None if data is None else json.dumps(data).encode(), headers={"X-GT7C": "1", "Content-Type": "application/json", **({"Cookie": cookie} if cookie else {})})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.read(), r.headers
    except urllib.error.HTTPError as e:
        return e.code, e.read(), e.headers
ok("http: page and data", http("/")[0] == 200 and json.loads(http("/api/overview")[1])["totals"]["laps"] == 11 and json.loads(http("/api/car?code=3265")[1])["code"] == 3265)
ok("http: a kept picture is served", http(f"/shots/{kept[0]}")[1][:4] == b"\x89PNG" and http("/shots/999")[0] == 404)
ok("http: deleting a picture needs the admin", http("/api/admin/shot-delete", dict(id=kept[0]))[0] == 401)
ok("phone: off until it is set up", json.loads(http("/api/phone")[1])["on"] is False)
CFG.save(dict(phone_on=True, phone_view_url="http://127.0.0.1:18792", phone_view_password="s3cret"))
ok("phone: the screen is not shown to a visitor", http("/phone/vnc.html")[0] == 401 and "src" not in json.loads(http("/api/phone")[1]))
cookie = http("/api/admin/login", dict(password="test-password"))[2]["Set-Cookie"].split(";")[0]
p = json.loads(http("/api/phone", cookie=cookie)[1])
ok("phone: the admin gets the screen, password filled in", p["src"].startswith("/phone/vnc.html?") and p["src"].endswith("#password=s3cret"))
code, body, _ = http("/phone/app/ui.js?v=1", cookie=cookie)
ok("phone: files are passed through, without the admin's cookie", code == 200 and body == b"phone says /app/ui.js?v=1 cookie=None")
ok("phone: no way out of the phone's address", http("/phone/../api/settings", cookie=cookie)[0] in (400, 404))
ok("track: naming needs the admin", http("/api/admin/track-name", dict(id=1, name="Test Ring"))[0] == 401
   and http("/api/admin/track-name", dict(id=1, name="Test Ring"), cookie)[0] == 200 and api.track(1)["name"] == "Test Ring")
ok("track: the page can rename it without the admin", http("/api/track-name", dict(id=1, name="My Ring"))[0] == 200 and api.track(1)["name"] == "My Ring"
   and http("/api/track-name", dict(id=999, name="x"))[0] == 404)
ok("track: an empty name takes the name away", http("/api/track-name", dict(id=1, name=""))[0] == 200 and not api.track(1)["named"])
http("/api/track-name", dict(id=1, name="Test Ring"))
ok("screenshots: the admin can delete one", http("/api/admin/shot-delete", dict(id=kept[0]), cookie)[0] == 200 and api.shots()["all"] == 0 and api.car(3265)["picture"] is None)
# an installation with a sign-in in front of the page: its visitors are the admin, the earpiece and the agent door are not
from gt7copilot import server
def settings_seen(headers=None):
    req = urllib.request.Request(B + "/api/settings", headers=headers or {})
    return json.load(urllib.request.urlopen(req, timeout=5))
server.TRUST_DOOR = True
seen = settings_seen()
ok("door: with a sign-in in front, the page is the admin without a password", seen["signed_in"] is True and "groups" in seen and seen["door"] is True)
ok("door: a request with an agent token is not the admin", settings_seen({"Authorization": "Bearer x"})["signed_in"] is False)
server.TRUST_DOOR = False
ok("door: off again, the password is needed", settings_seen()["signed_in"] is False)
shutil.rmtree(tmp); print("pages: all passed" if all(res) else "FAILURES"); sys.exit(0 if all(res) else 1)
