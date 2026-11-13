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
ok(vo.handle("Copilot take a screenshot")["command"] == "captures", "'take a screenshot' is still the single newest capture")
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
