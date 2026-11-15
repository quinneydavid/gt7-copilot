"""Reading the new PS5 captures in one go: every capture not read before, one sheet per car, a car that is new is added,
events noted, nothing read twice. The virtual phone and the vision model are stand-ins."""
import json, os, sys, tempfile, time, types
tmp = tempfile.mkdtemp()
os.environ.update(GT7C_DATA=tmp, GT7C_SCREENSHOTS_ON="1", GT7C_PHONE_ON="1", GT7C_GRAB_URL="http://127.0.0.1:9",
                  GT7C_LLM_URL="http://127.0.0.1:9/v1", GT7C_VISION_MODEL="test", GT7C_VOICE_ON="1", GT7C_WHISPER_URL="http://127.0.0.1:9/x")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from gt7copilot import api, capture as CAP, library as L, voice as V
from gt7copilot.store import Store

ok = lambda cond, what: (print(("ok   " if cond else "FAIL ") + what), cond or sys.exit(1))
st = Store(tmp); col = types.SimpleNamespace(car=None, track=None, tune=None, live=False, session_laps=[], meta={})

def page1(car, arb=(6, 5)):
    return dict(screen="car_settings_1", car=car, summary=f"Car Settings of the {car}", sheet=dict(
        pp=717.35, power=766, power_unit="HP", weight=1180, weight_unit="kg", tyres=dict(front="Racing: Medium", rear="Racing: Medium"),
        suspension=dict(ride_height_mm=[120, 120], anti_roll_bar=list(arb), damping_compression_pct=[35, 35], damping_expansion_pct=[45, 45],
                        natural_frequency_hz=[2.6, 2.6], negative_camber_deg=[2.5, 1.5], toe_deg=[0.0, 0.2], toe_direction=["none", "in"]),
        differential=dict(initial_torque=[5, 10], acceleration_sensitivity=[10, 15], braking_sensitivity=[5, 30], front_rear_torque_split="45:55"),
        aero=dict(downforce=[150, 250]), transmission=dict(type="Fully Customizable", top_speed=290, top_speed_unit="km/h"), hardware={}))
page2 = lambda car: dict(screen="car_settings_2", car=car, summary="Car Settings, page 2", sheet=dict(brake_balance=-1, hardware=dict(muffler="Racing Muffler")))
A, B = "86 Gr.B Rally Car", "Nissan 180SX Type X '96"
# the PlayStation App's list, newest first: (capture id, what the vision model reads on it)
app = [("c5", page2(A)), ("c4", page1(A)), ("c3", dict(screen="event", car=None, summary="Race details", event=dict(name="World Rally Challenge", track="Willow Springs: Big Willow", laps=10, fuel_rate=8))),
       ("c2", page1("Some Unknown Prototype")), ("c1", dict(screen="other", car=None, summary="A replay"))]
# a small JPEG: an EXIF note holding the time of the download (different every time), then the picture data
downloads = [0]
def pic(cid):
    downloads[0] += 1
    note = b"Exif\x00\x00 2026:11:12 10:%02d:%02d" % (downloads[0] // 60 % 60, downloads[0] % 60)
    return b"\xff\xd8" + b"\xff\xe1" + (len(note) + 2).to_bytes(2, "big") + note + b"\xff\xdb\x00\x04\x01\x02" + b"\xff\xda\x00\x02" + cid.encode() * 20 + b"\xff\xd9"
body = lambda image: image[image.index(b"\xff\xda"):]
grabs = []
def grab(index=1, mode=""):
    grabs.append(index)
    if index > len(app):
        raise CAP.GrabError("There is no screenshot in the PlayStation App.", 404)
    return pic(app[index - 1][0]), "download-%d.jpg" % downloads[0]           # the app names a download after its time
CAP.grab = grab
CAP.read = lambda image: next(seen for cid, seen in app if body(pic(cid)) == body(image))
ok(pic("c1") != pic("c1") and CAP.digest(pic("c1")) == CAP.digest(pic("c1")) and CAP.digest(pic("c1")) != CAP.digest(pic("c2")), "the same capture downloaded twice differs only in its notes, and is recognised")

steps = []
out = CAP.take_new(col, st, log=lambda m: None, progress=steps.append); print("     ", out["reply"])
code = CAP.match_car(A)
ok(code and api.car_name(code).endswith("86 Gr.B Rally Car"), "the car named on the screen is found in the game's car list")
ok(out["read"] == 5 and len(out["shots"]) == 5 and out["cars"] == [code], "five new captures read, one car filed")
t = L.current_tune(st, code)
ok(t and t["sheet"]["suspension"]["anti_roll_bar"] == [6, 5] and t["sheet"]["brake_balance"] == -1 and t["sheet"]["hardware"].get("muffler") == "Racing Muffler", "its sheet has both pages")
ok(any(c["code"] == code and c["sheet_on_file"] for c in api.cars()["cars"]), "a car never driven is now on the Cars page")
ok("Event noted" in out["reply"] and "do not know which car" in out["reply"] and out["ok"], "the event is noted; the unknown car is named as not filed")
rows = {f"c{6 - n}": r for n, r in enumerate(st.q("SELECT * FROM shots ORDER BY id"), 1)}        # kept newest first: c5, c4, c3, c2, c1
ok(rows["c5"]["ok"] == 1 and rows["c5"]["car"] == code and rows["c2"]["ok"] == 0 and rows["c1"]["ok"] == 0 and rows["c3"]["ok"] == 1, "each kept picture carries its own result")
ok(any("Fetching capture 1" in s for s in steps) and any("Reading capture 5" in s for s in steps), "progress is told step by step")

grabs.clear(); out = CAP.take_new(col, st, log=lambda m: None)
ok(out["read"] == 0 and "No new screenshots" in out["reply"] and grabs == [1], "pressed again: nothing new, and only the newest was fetched")

app.insert(0, ("c6", page1(A, arb=(5, 5)))); grabs.clear()
out = CAP.take_new(col, st, log=lambda m: None); print("     ", out["reply"])
ok(out["read"] == 1 and grabs == [1, 2] and "1 change" in out["reply"] and L.current_tune(st, code)["sheet"]["suspension"]["anti_roll_bar"] == [5, 5], "one new capture: only that one is read, the change is filed")
ok(L.current_tune(st, code)["sheet"]["brake_balance"] == -1, "...on top of the sheet on file")

st.x("DELETE FROM shots WHERE id=?", rows["c3"]["id"]); grabs.clear()
out = CAP.take_new(col, st, log=lambda m: None)
ok(out["read"] == 0, "a capture behind ones already read is not reached by the normal read")
out = CAP.take_new(col, st, log=lambda m: None, back=True); print("     ", out["reply"])
ok(out["read"] == 1 and "Event noted" in out["reply"], "looking back reads the one that was skipped, and nothing else")

# the background job the page follows, and the spoken command
said = []; vo = V.Voice(col, types.SimpleNamespace(enabled=True), lambda text, ttl, kind: said.append(text), types.SimpleNamespace(recent=[]), log=lambda m: None, store=st)
app.insert(0, ("c7", page2(A)))
r = vo.handle("Copilot, read my screenshots"); ok(r["command"] == "captures_new" and vo.job["running"], "'read my screenshots' starts the job")
ok(vo.read_new()["ok"] is False, "a second start while it runs is refused")
t0 = time.time()
while vo.job["running"] and time.time() - t0 < 5: time.sleep(0.05)
ok(vo.job["result"] and vo.job["result"]["read"] == 1 and said and "Read 1 new screenshot" in said[-1], "the job ends with its result, and says it")
app.insert(0, ("c8", page2(A))); app.insert(0, ("c9", page1(A, arb=(6, 6)))); said.clear()
r = vo.handle("Copilot take a screenshot"); ok(r["command"] == "captures" and vo.job["running"], "'take a screenshot' starts the same job")
t0 = time.time()
while vo.job["running"] and time.time() - t0 < 5: time.sleep(0.05)
ok(vo.job["result"] and vo.job["result"]["read"] == 2 and "Read 2 new screenshots" in said[-1], "two captures taken, 'screenshot' reads both (14 Nov)")
print("shots: all passed")

# a value the reader leaves out keeps what is on file (seen 12 Nov: a differential read as nulls blanked the sheet)
half = page1(A, arb=(5, 5)); half["sheet"]["differential"]["initial_torque"] = [None, None]; half["sheet"]["differential"]["braking_sensitivity"] = [None, 25]
sh2 = CAP.to_sheet([half], L.current_tune(st, code)["sheet"])
ok(sh2["differential"]["initial_torque"] == [5, 10] and sh2["differential"]["braking_sensitivity"] == [5, 25], "values the reader left out keep what is on file")
print("shots: all passed (again)")

# a rear-driven car shows 0 for the front differential: that is "no differential there", not a misread (Ferrari 308, 12 Nov)
mr = page1("Ferrari 308 GTB '75"); mr["sheet"]["differential"].update(initial_torque=[0, 8], acceleration_sensitivity=[0, 5], braking_sensitivity=[0, 5], front_rear_torque_split="0 : 100")
from gt7copilot import sheet as SH
sh3 = CAP.to_sheet([mr])
ok(sh3["differential"]["initial_torque"] == [None, 8] and not SH.problems(sh3) and sh3["differential"]["front_rear_torque_split"] == "0:100", "a 0 at the undriven end is filed as no value, and the sheet passes the checks")
fcode = CAP.match_car("Ferrari 308 GTB '75"); ok(fcode and "308 GTB" in api.car_name(fcode), "the Ferrari is found by the name on its screen")

# ---- 15 Nov: one odd value never throws the page away; what is filed says what the screenshot says ----
from gt7copilot import tuneadvice as TA
focus = CAP.match_car("Focus Gr.B Rally Car"); ok(bool(focus), "the Focus Gr.B is found by its name")
fp = page1("Focus Gr.B Rally Car"); fp["sheet"]["suspension"]["damping_expansion_pct"] = [65, 65]
r = CAP.file_sheet(col, st, focus, [fp], "test", lambda *a: None, [1])
t = L.current_tune(st, focus)
ok(r.startswith("Sheet filed") and "Please check" not in r and t["sheet"]["suspension"]["damping_expansion_pct"] == [65, 65],
   "the Focus's real damping expansion of 65 is filed, with no flag (the old 30 to 50 limit refused the whole page)")
odd = page1("Focus Gr.B Rally Car", arb=(14, 5)); odd["sheet"]["suspension"]["damping_expansion_pct"] = [65, 65]
r = CAP.file_sheet(col, st, focus, [odd], "test", lambda *a: None, [2]); t = L.current_tune(st, focus)
ok("Please check: Suspension: Anti-Roll Bar (Front) read as 14" in r and t["sheet"]["differential"]["acceleration_sensitivity"] == [10, 15],
   "one value outside the usual range: the page is filed, that value named for checking")
try:
    CAP.file_sheet(col, st, focus, [dict(screen="car_settings_1", car="Focus", sheet={})], "test", lambda *a: None); blank = False
except RuntimeError as e:
    blank = "could not read any settings" in str(e)
ok(blank and L.current_tune(st, focus)["id"] == t["id"], "a page read as nothing is not filed (14 Nov: a blank sheet replaced the real one)")
# toe direction: same size, other icon -> the old direction is kept, and that disagreement is named
CAP.check_values(col, st, focus, {"suspension.anti_roll_bar.front": 4})
flip = page1("Focus Gr.B Rally Car"); flip["sheet"]["suspension"]["damping_expansion_pct"] = [65, 65]; flip["sheet"]["suspension"]["toe_direction"] = ["none", "out"]
r = CAP.file_sheet(col, st, focus, [flip], "test", lambda *a: None)
ok("Toe Angle (Rear): the screenshot shows out, the sheet keeps in" in r, "where the filed sheet and the screenshot disagree (toe direction), it is named, never silent")
lk = api.needs_look(st, focus, L.current_tune(st, focus)); ok(lk and lk["doubts"][-1]["read"] == -0.2, "...and the car page asks about it")
# advice never moves a value the wrong way when it is already outside the usual range
TA.S.LIMITS["test.x"] = (30, 50)
up = TA._fix(dict(test=dict(x=[65, 65])), "test.x", "front", 5, "test"); down = TA._fix(dict(test=dict(x=[65, 65])), "test.x", "front", -5, "test")
ok(up is None and down["to"] == 60, "a value already above the usual range is never 'raised' down to it, and a lower step works")
# the copilot on track quotes the newest sheet, also one filed during the session
from gt7copilot.collector import Collector
cc = Collector(st, log=lambda *a: None); cc.car = focus; cc.tune = None
ok(cc.tune and cc.tune["id"] == L.current_tune(st, focus)["id"], "the collector always hands out the newest sheet on file")
CAP.check_values(None, st, focus, {"suspension.anti_roll_bar.rear": 6})
ok(cc.tune["sheet"]["suspension"]["anti_roll_bar"][1] == 6, "...so a sheet filed mid-session is what the voice quotes next")
print("shots: 15 Nov checks passed")

# ---- 15 Nov: several screenshots of one car across the game's settings sheets: only pages of the same sheet combine,
# the newest screenshot's sheet is the one on the car ----
P = "Porsche 911 GT3 RS (992) '22"
pc = CAP.match_car(P); ok(bool(pc), "the Porsche is found by its name")
def sp1(slot, arb): p = page1(P, arb=arb); p["settings_sheet"] = slot; return p
def sp2(slot, bb): p = page2(P); p["settings_sheet"] = slot; p["sheet"]["brake_balance"] = bb; return p
nopage = page2(P); nopage["sheet"]["brake_balance"] = 3                         # page 2 that does not show its sheet number
# newest first, as the PlayStation App lists them: sheet 1 again (changed), sheet 2 both pages, sheet 1 both pages
app[:0] = [("p6", sp1(1, (7, 7))), ("p5", sp2(2, -2)), ("p4", sp1(2, (2, 2))), ("p3", nopage), ("p2", sp1(1, (4, 4))), ("p1", sp1(1, (3, 3)))]
out = CAP.take_new(col, st, log=lambda m: None); print("     ", out["reply"])
t = L.current_tune(st, pc)
ok(t["slot"] == 1 and t["sheet"]["suspension"]["anti_roll_bar"] == [7, 7], "the newest screenshot's sheet (sheet 1, its newest page 1) is the one on the car")
s2 = st.q("SELECT sheet FROM tunes WHERE car=? AND slot=2 ORDER BY id DESC LIMIT 1", pc)
ok(s2 and json.loads(s2[0]["sheet"])["brake_balance"] == -2 and json.loads(s2[0]["sheet"])["suspension"]["anti_roll_bar"] == [2, 2], "sheet 2 is filed as its own sheet, its two pages together")
ok(t["sheet"]["brake_balance"] == 3, "a page 2 without a sheet number joins the sheet shot just before it (sheet 1)")
ok(t["sheet"]["brake_balance"] != -2, "...the brake balance of sheet 2 never leaks into sheet 1")
print("shots: settings sheets passed")
