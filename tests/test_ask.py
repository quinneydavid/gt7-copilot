"""Ask: the facts the model is given for a question, and the doors around it. The model itself is a stand-in."""
import json, os, shutil, sys, tempfile, urllib.error, urllib.request
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [ROOT, os.path.join(ROOT, "tests")]
tmp = tempfile.mkdtemp(); os.environ["GT7C_DATA"] = tmp
import sim
from gt7copilot import ask as ASK, cli, settings as CFG
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
cli.run(st, ["tune-set", "3265", SHEET])
drive(3265, [{}, {"understeer": 1.6, "entry_slide": True}, {"understeer": 1.6, "entry_slide": True}, {"understeer": 1.6}])
drive(2156, [{"slow": {0: 0.9}}, {"slow": {0: 0.9}}, {"slow": {0: 0.9}}])
st.x("UPDATE tracks SET name='Test Ring' WHERE id=1")

ok("off until switched on", "error" in ASK.answer("What should I change?") and ASK.why_not())
CFG.save(dict(ask_on=True))
ok("needs a model", "Not set" in ASK.why_not())
CFG.save(dict(llm_url="http://127.0.0.1:1/v1", vision_model="test-model"))
ok("ready with the address and a model", ASK.why_not() is None)

f = ASK.facts("What should I change on the car next?")
ok("totals and cars driven", f["driving"]["totals"]["laps"] == 7 and len(f["driving"]["cars"]) == 2)
ok("no car named: the car of the latest session", [c["car"] for c in f["cars"]] == [cli.car_name(2156)])
f = ASK.facts("what should I change on the 86?")
c = f["cars"][0]
ok("a car named in the question is found", c["car"] == cli.car_name(3265) and c["settings_on_car"]["sheet"]["suspension"]["anti_roll_bar"] == [4, 6])
ok("its suggested changes carry numbers", c["suggested_changes"]["change"] and all(x["now"] is not None and x["to"] is not None for x in c["suggested_changes"]["change"]))
f = ASK.facts("anything", where=dict(car=3265, track=1))
ok("the page's car and track are used", f["cars"][0]["car"] == cli.car_name(3265) and f["tracks"][0]["track"] == "Test Ring" and len(f["tracks"][0]["cars_ranked"]) == 2)
ok("the latest session is described", f["session"]["laps"] and f["session"]["which"] == "the latest session")
f = ASK.facts("what does the rear anti-roll bar do?")
ok("guide rows for a setting named in the question, with sources", f["guides"]["rows"] and all(r["source"] for r in f["guides"]["rows"]))
ok("a car with no sheet says so", "No settings sheet" in ASK.facts("x", where=dict(car=2156))["cars"][0]["settings_note"])
ok("facts stay inside the limit", len(ASK._shrink(ASK.facts("camber toe diff on the 86 at Test Ring", where=dict(session=1)))) <= ASK.MAX_FACTS * 2)

seen = []
out = ASK.answer("Which car have I driven most?", [dict(q="earlier q", a="earlier a")], model=lambda p: seen.append(p) or "**The 86.** Four laps.")
ok("the answer comes back without markdown", out == dict(answer="The 86. Four laps."))
ok("the prompt holds the facts, the earlier turn and the question", '"driving"' in seen[0] and "earlier q" in seen[0] and seen[0].rstrip().endswith("Which car have I driven most?"))
ok("a model that cannot be reached is an error, not a crash", "error" in ASK.answer("Which car have I driven most?"))
ok("an empty question is refused", "error" in ASK.answer(" "))

ok("a request for a screenshot is told from a question", all(ASK.wants_shot(x) for x in ("take a screenshot", "Grab the screenshot please", "screenshot", "read the settings screen"))
   and not any(ASK.wants_shot(x) for x in ("How do I take a screenshot?", "What did the last screenshot say?", "What should I change?")))
class Box:
    def submit(self, image, route, name="", speak=True):
        return dict(ok=True, reply="Sheet filed for the test car.", shots=[7]) if route == "phone" and image is None else dict(ok=False, reply="wrong call")
ok("it fetches through the phone and says what was read", ASK.shot(Box()) == dict(answer="Sheet filed for the test car.", shots=[7]) and "error" in ASK.shot(None))
serve(18793, Hub(), lambda: dict(live=False), lambda *x: None, lambda on: None)
def post(body, headers):
    req = urllib.request.Request("http://127.0.0.1:18793/api/ask", json.dumps(body).encode(), headers)
    try: return json.load(urllib.request.urlopen(req, timeout=10))
    except urllib.error.HTTPError as e: return dict(http=e.code)
ok("http: another site cannot ask", post(dict(q="hello there"), {}) == dict(http=400))
ok("http: the page can", "error" in post(dict(q="hello there", h=[], where=dict(car=3265)), {"X-GT7C": "1"}))
ok("http: status for the page", json.load(urllib.request.urlopen("http://127.0.0.1:18793/api/ask"))["ready"] is True)
# the radio: a spoken question that is not a fixed command
seen2 = []
r = ASK.radio("what time is it?", [("how is the fuel", "Fine.")], None, dict(fuel=41.5, lap=3), model=lambda p: seen2.append(p) or "It is **nine** o'clock.")
ok("radio: a short answer to say, without markup", r == "It is nine o'clock.")
ok("radio: the model is told the time, the car's state and what was just said", "41.5" in seen2[0] and "EARLIER, DRIVER: how is the fuel" in seen2[0] and __import__("time").strftime("%Y") in seen2[0])
ok("radio: the model may say it was not a question, then nothing is said", ASK.radio("thank you very much", model=lambda p: "NOTHING.") is None)
ok("radio: a model that fails says nothing", ASK.radio("what time is it?") is None)
shutil.rmtree(tmp); print("ask: all passed" if all(res) else "FAILURES"); sys.exit(0 if all(res) else 1)
