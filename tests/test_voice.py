"""Voice control: the wake word, the commands and their answers, on a simulated race; and the earpiece's door for speech."""
import io, json, os, shutil, sys, tempfile, urllib.error, urllib.request, wave
tmp = tempfile.mkdtemp()
os.environ.update(GT7C_DATA=tmp, GT7C_TOKEN="agent-token", GT7C_EARPIECE_TOKEN="ear-token", GT7C_VOICE_ON="1",
                  GT7C_WHISPER_URL="http://127.0.0.1:9/v1/audio/transcriptions", GT7C_SCREENSHOTS_ON="1", GT7C_PHONE_ON="1",
                  GT7C_GRAB_URL="http://127.0.0.1:9", GT7C_LLM_URL="http://127.0.0.1:9/v1", GT7C_VISION_MODEL="test")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [ROOT, os.path.join(ROOT, "tests")]
import sim
from gt7copilot import server, voice as V
from gt7copilot.collector import Collector
from gt7copilot.copilot import Copilot
from gt7copilot.packet import decrypt, parse
from gt7copilot.store import Store

st = Store(tmp); col = Collector(st, log=lambda m: None); said = []
co = Copilot(lambda text, ttl, kind: said.append((kind, text)), log=lambda m: None); col.listeners.append(co)
hub = server.Hub()
say = lambda text, ttl, kind: (said.append((kind, text)), hub.publish(dict(type="say", text=text, kind=kind)))
vo = V.Voice(col, co, say, hub, log=lambda m: None, store=st)
wall = 1000.0
for pkt in sim.packets([{}, {}, {"slow": {2: 0.9}}, {}], total_laps=9, fuel=20.0, fuel_per_lap=2.5):
    row, meta = parse(decrypt(pkt)); wall += 1 / 60; col.feed(row, meta, wall)
col.live = True
hub.publish(dict(type="say", text="Turn two. Brake twenty metres later.", kind="corner"))

ok = lambda cond, what: (print(("ok   " if cond else "FAIL ") + what), cond or sys.exit(1))
h = lambda t: vo.handle(t)
ok(h("how is the fuel")["command"] is None and h("That was a good lap")["command"] is None and h("I think that was fine")["reply"] is None, "words without the name are not commands")
ok(h("Thank you.")["command"] is None, "noise that Whisper turns into words is ignored")
for name in ("Copilot,", "Co-pilot", "Hey copilot", "co pilot,", "OK Copilot"):
    ok(h(f"{name} how is the fuel?")["command"] == "fuel", f"'{name}' is heard as the name")
r = h("Copilot, fuel"); print("     ", r["reply"]); ok(r["reply"].startswith("Fuel ") and "a lap" in r["reply"] and "to go" in r["reply"], "fuel: level, rate, laps left, laps to go")
r = h("Copilot tyres"); print("     ", r["reply"]); ok(r["command"] == "tyres" and "Front left" in r["reply"], "tyres: four temperatures")
r = h("Copilot what's my best lap"); print("     ", r["reply"]); ok(r["command"] == "best" and "Best this session" in r["reply"], "best lap")
r = h("Copilot how was that lap"); print("     ", r["reply"]); ok(r["command"] == "last" and r["reply"].startswith("Last lap"), "last lap")
r = h("Copilot, which lap are we on"); print("     ", r["reply"]); ok(r["command"] == "lap" and " of nine" in r["reply"], "which lap")
r = h("Copilot repeat that"); ok(r["reply"] == "Turn two. Brake twenty metres later.", "repeat says the last call again (not its own answers)")
r = h("Copilot, be quiet"); ok(r["command"] == "quiet" and co.enabled is False, "quiet mutes the copilot")
r = h("Copilot talk"); ok(r["command"] == "talk" and co.enabled is True, "talk brings it back")
r = h("Copilot what to change for the car"); print("     ", r["reply"]); ok(r["command"] == "advice" and r["reply"], "what to change: advice for the car")

# a setting asked for by name: read from the sheet on file
import copy, time as _t
from gt7copilot import library as L, sheet as SH
r = h("Copilot, what should I set the rear differential at?"); print("     ", r["reply"]); ok(r["command"] == "setting" and "No settings sheet on file" in r["reply"], "a setting without a sheet on file: says so")
sh = copy.deepcopy(SH.TEMPLATE)
sh["suspension"].update(ride_height_mm=[120, 120], anti_roll_bar=[6, 5], negative_camber_deg=[2.5, 1.5], toe_deg=[0.0, 0.2])
sh["differential"].update(initial_torque=[5, 10], acceleration_sensitivity=[10, 15], braking_sensitivity=[5, 30]); sh["brake_balance"] = -1
st.x("INSERT INTO tunes(car,created,source,sheet,note) VALUES(?,?,?,?,?)", col.car, _t.time(), "test", json.dumps(sh), "")
col.tune = L.current_tune(st, col.car)
r = h("Copilot, what should I set the rear differential at?"); print("     ", r["reply"])
ok(r["command"] == "setting" and "Initial Torque, 10" in r["reply"] and "Acceleration Sensitivity, 15" in r["reply"] and "Braking Sensitivity, 30" in r["reply"] and r["reply"].startswith("Rear. ") and "front" not in r["reply"].lower(), "the rear differential: its three values, rear only")
r = h("Copilot what's the anti-roll bar"); print("     ", r["reply"]); ok("Anti-Roll Bar, front 6, rear 5" in r["reply"], "a pair without an end named: both ends")
r = h("Copilot, front camber?"); print("     ", r["reply"]); ok("Negative Camber Angle, 2.5" in r["reply"] and "1.5" not in r["reply"], "front camber: one value")
r = h("Copilot what is the brake balance"); print("     ", r["reply"]); ok(r["command"] == "setting" and "-1" in r["reply"], "brake balance")
r = h("Copilot, what's the downforce"); ok(r["command"] == "setting" and "not on the sheet" in r["reply"], "a setting the sheet does not have: says so")
r = h("Copilot, read me out the settings"); print("     ", r["reply"]); ok(r["command"] == "advice", "read me the settings: the changes, all of them")
ok(h("Copilot tyre temps")["command"] == "tyres" and h("Copilot fuel")["command"] == "fuel", "the other commands still win their words")

# sentences from a real race (12 Nov 2026) that were not understood
for phrase in ("Go pilot, I'm staying lean.", "No pilots. fuel", "Right, Copilot, we're going to start racing.", "Copilots, fuel"):
    ok(h(phrase)["command"] is not None, f"heard as the name: {phrase}")
ok(h("Thank you.")["command"] is None and h("Turn seven. Exit turn two.")["command"] is None and h("The pilot said no")["command"] is None, "noise and the copilot's own calls are still not commands")
for phrase in ("But stay there, Coppola.", "Hi Pilot."):                 # 12 Nov evening: the name written wrongly, nothing asked
    ok(h(phrase)["command"] in (None, "hello", "unknown"), f"no false command from: {phrase}")
ok(h("Coppola, fuel")["command"] == "fuel" and h("Hi pilot, fuel")["command"] == "fuel" and h("Pilot, tyres")["command"] == "tyres", "Coppola / Hi pilot / Pilot are heard as the name")
r = h("Copilot, can you hear me?"); ok(r["command"] == "hello" and r["reply"] == "Yes. I hear you.", "can you hear me: yes")
vo._hello_at = 0
ok(h("Co-pilot are you there")["reply"] == "Yes. I hear you." and h("Copilot")["reply"] == "Yes?" and h("Copilot.")["reply"] is None, "are you there: yes; the name alone: Yes?, once in twenty seconds")
ok(h("The pilot said no")["command"] is None and h("A pilot project")["command"] is None, "'pilot' inside a sentence is not the name")
# the name by its sound, and a conversation without repeating it
from gt7copilot import voice as V2
ok(all(V2.sounds_like_name(x) for x in ("kaupala", "coppola can you hear me", "copala fuel", "go pilot", "hi pilot how is the fuel", "koppelet tyres")), "Kaupala, Coppola, Copala ... sound like the name")
ok(not any(V2.sounds_like_name(x) for x in ("couple of laps left", "the pilot said no", "people are here", "complete the lap", "capital idea", "thank you", "cool", "hello there")), "ordinary words do not")
vo.open_until = 0; vo._hello_at = 0; col.live = False
ok(h("can you hear me")["command"] is None, "not driving, no name: not for the copilot")
r = h("Kaupala."); ok(r["command"] == "hello" and r["reply"] == "Yes?", "the name alone, however it was written: Yes?")
r = h("can you hear me"); ok(r["reply"] == "Yes. I hear you.", "...and the next sentence needs no name")
r = h("how is the fuel"); ok(r["command"] == "fuel", "the conversation stays open after an answer")
vo.open_until = 0
ok(h("how is the fuel")["command"] is None, "after a pause the name is needed again")
r = h("Kaupala, can you hear me?"); ok(r["reply"] == "Yes. I hear you.", "name by sound and question in one sentence")
vo.open_until = 0; col.live = True

# from the race of 12 Nov, 22:20: sentences that went to the wrong command
vo.open_until = 0; col.live = True; co.enabled = True
for phrase in ("I'll talk to you.", "Yeah, I'm talking. How's my speed, co-pilot?", "Why are you staying talking again?"):
    ok(h(phrase)["command"] != "talk", f"not the 'talk' command: {phrase}")
ok(h("How's my speed, co-pilot?")["command"] in ("unknown", "chat"), "the name at the end of the sentence counts")
co.enabled = False; ok(h("Copilot, talk")["command"] == "talk" and co.enabled, "'talk' still brings a muted copilot back")
ok(h("Copilot, be quiet")["command"] == "quiet" and h("copilot it is very quiet out here today")["command"] != "quiet", "'be quiet' mutes; a sentence with the word does not")
co.enabled = True; vo.open_until = 0; col.live = False
ok(h("Pollock, can you hear me?")["reply"] == "Yes. I hear you." and h("Hi Paulo, how is the fuel?")["command"] == "fuel", "an unknown name, a comma and a fixed command: taken as the name")
vo.open_until = 0
ok(h("Rex, come here")["command"] is None and h("Okay, I'll leave it open for a bit")["command"] is None, "...but talk to someone else is not")
vo.open_until = 0; col.live = True

# while driving, no name is needed (when Settings say so); noise and the copilot's own calls are still not commands
from gt7copilot import settings as CFG2, ask as ASK
CFG2.save(dict(voice_open_live=True)); col.live = True
ok(h("how is the fuel")["command"] == "fuel" and h("fuel")["command"] == "fuel" and h("what's my best lap")["command"] == "best", "driving: commands work without the name")
ok(all(h(x)["command"] is None for x in ("Thank you.", "Bye.", "Peace.", "nice", "I'm hungry.", "you")), "driving: what noise is heard as stays ignored")
hub.publish(dict(type="say", text="Turn seven. Exit ten kilometres an hour faster.", kind="corner"))
ok(h("Turn seven. Exit ten kilometres an hour faster")["command"] is None and h("Turn 7, exit 10 km an hour faster.")["command"] is None, "driving: the copilot's own call coming back is ignored")
asked = []
ASK.radio = lambda text, hist, live, now: (asked.append((text, hist, now)), "It is twenty past nine.")[1]
r = h("What time is it?"); ok(r["command"] == "chat" and r["reply"] == "It is twenty past nine." and asked[-1][2] and "fuel" in asked[-1][2], "driving: an open question is answered by the model, with the car's state")
r = h("Copilot, is this car faster than my Ferrari?"); ok(r["command"] == "chat" and asked[-1][1] and asked[-1][1][-1][0] == "What time is it?", "with the name too, and it knows what was just said")
r = h("Hey, what car do you recommend we take on this track next?"); ok(r["command"] == "chat", "driving: 'hey, what car do you recommend on this track' goes to the model")
ASK.why_not = lambda: None
r = h("Copilot, which of my cars is the fastest at Big Willow?"); ok(r["command"] == "chat", "a longer question that only mentions a command's word goes to the model")
ok(h("Copilot, what's my best lap")["command"] == "best" and h("how is the fuel")["command"] == "fuel", "short requests stay with the fixed commands")
vo.open_until = 0
n = len(asked); ok(h("the weather was lovely on Sunday")["command"] is None and len(asked) == n, "driving: a sentence that asks nothing is not sent to the model")
vo.open_until = 0; vo.told = []
r = h("Copilot, it's raining on the track."); ok(r["command"] == "chat" and vo.told and "raining" in vo.told[-1][1], "something the driver tells is answered and kept")
r = h("It's raining very hard now."); ok(r["command"] == "chat" and "told_by_driver" in asked[-1][2] and len(asked[-1][2]["told_by_driver"]) == 2, "in the conversation a statement needs no name, and the model gets what was told")
vo.told = []
r = h("Copilot, hey, actually it is raining. What should I do?"); ok(r["command"] == "chat" and vo.told and "raining" in vo.told[-1][1], "a statement with a question behind it is answered and kept")
r = h("what tyres should I be on?"); ok(r["command"] == "chat", "'what tyres should I be on' is a question, not the temperature read-out")
ok(h("Copilot, tyres")["command"] == "tyres" and h("Copilot, how are the tyres")["command"] == "tyres" and h("Copilot, how is the fuel")["command"] == "fuel", "short read-outs stay fixed")
# with a model, the model says what a sentence means; the app answers with its own figures
routes = []
def fake_route(text, hist, live, now, named):
    routes.append((text, named, now))
    t = text.lower()
    if "tired" in t: return dict(intent="chat", say="Take a break after this one.", told=True)
    if "dinner" in t: return dict(intent="nothing", say=None)
    if "box next lap" in t: return dict(intent="says_pit", lap=(now or {}).get("lap", 0) + 1, why="fuel")
    if "rear anti-roll" in t: return dict(intent="read_setting", setting="anti_roll_bar", end="rear")
    if "fuel going to last" in t: return dict(intent="fuel")
    if "what fuel map" in t: return dict(intent="chat", say="No idea.")
    if "set the rear differential" in t: return dict(intent="chat", say="No idea.")
    if "got the screenshot" in t: return dict(intent="chat", say="Yes, the sheet is filed.")
    if "broken" in t: return None
    return dict(intent="chat", say="(model)")
ASK.route = fake_route; vo.open_until = 0; vo.told = []; col.live = True
r = h("I'm so tired today"); ok(r["command"] == "chat" and "break" in r["reply"] and vo.told and "tired" in vo.told[-1][1], "'I'm tired' is small talk the model answers and remembers, not a tyre stop")
vo.open_until = 0
ok(h("dinner is ready in five")["command"] is None, "the model may say a sentence without the name is not for the copilot")
ok(h("Copilot, dinner is ready in five")["reply"] == "Say again?", "...with the name it never stays silent")
r = h("Copilot, I'm going to box next lap"); ok(r["command"] == "pit_plan" and ("lap" in r["reply"]), "a pit plan the model understood goes to the app's pit logic")
r = h("Copilot, what's the rear anti-roll bar at?"); ok(r["command"] == "setting" and "Anti-Roll Bar" in r["reply"], "a setting the model named is read from the sheet")
r = h("Copilot, is the fuel going to last?"); ok(r["command"] == "fuel" and r["reply"].startswith("Fuel "), "a read-out intent gives the app's own figures")
ok(h("Copilot, what fuel map should I use?")["command"] == "fuel_map" and h("Copilot, what should I set the rear differential at?")["command"] == "setting", "where the app has the exact answer, it wins over the model's own words")
ok(h("Copilot, did you get the screenshot?")["command"] == "chat" and not vo.busy, "a question about screenshots does not fetch one")
ok(h("Copilot, how is the broken thing doing today")["command"] in ("unknown", "chat"), "a model that returns nothing usable falls back to the rules")
ok(h("fuel")["command"] == "fuel" and not any(t == "fuel" for t, _, _ in routes), "one or two words stay with the instant rules")
del ASK.route
ASK.radio = lambda *a: None
ok(h("Copilot, sing me a song")["reply"] == "Say again?" and h("can you sing me a song")["reply"] is None, "the model has nothing to say: 'Say again?' with the name, silence without")
col.live = False; vo.open_until = 0
ok(h("how is the fuel")["command"] is None, "not driving: the name is needed again")
col.live = True; CFG2.save(dict(voice_open_live=False)); vo.open_until = 0
ok(h("how is the fuel")["command"] is None, "switched off in Settings: the name is needed while driving")
r = h("Copilot, let's race."); print("     ", r["reply"]); ok(r["command"] == "start" and "Good luck" in r["reply"], "let's race: acknowledged")
r = h("Co-pilot, recommended fuel mix."); print("     ", r["reply"]); ok(r["command"] == "fuel_map" and r["reply"].split(".")[0] in ("Rich", "Lean", "Hold what you have", "Rich, and stop"), "recommended fuel mix: which map")
r = h("Copilot, I'm staying rich."); print("     ", r["reply"]); ok(r["command"] == "driver_map" and co.driver_map == "rich" and r["reply"].startswith("Copy. Rich."), "I'm staying rich: noted, with what it means")
r = h("Co-pilot, fuel is rich."); ok(r["command"] == "driver_map", "fuel is rich: the same")
r = h("Go pilot, I'm staying lean."); print("     ", r["reply"]); ok(r["command"] == "driver_map" and co.driver_map == "lean", "I'm staying lean: noted")
r = h("Copilot, should I go lean or rich?"); ok(r["command"] == "fuel_map", "a question about lean or rich is answered, not noted")
r = h("Co-pilot, I will fuel on that 8."); print("     ", r["reply"]); ok(r["command"] == "pit_plan" and ("lap eight" in r["reply"]), "I will fuel on lap 8: the plan is noted or corrected")
r = h("Copilot, I will fuel on the last lap."); print("     ", r["reply"]); ok(r["command"] == "pit_plan" and "gains nothing" in r["reply"], "fuelling on the last lap: told it gains nothing")
r = h("Co-pilot, I will need to pit for tyres."); print("     ", r["reply"]); ok(r["command"] == "pit_plan" and "tyres" in r["reply"], "pit for tyres: noted, asks for the lap")
r = h("Copilot, I'm going to pit in two laps"); print("     ", r["reply"]); ok(r["command"] == "pit_plan", "pit in two laps")
r = h("Copilot, how's the track?"); print("     ", r["reply"]); ok(r["command"] == "track" and "corners" in r["reply"], "how's the track: what is known about it")
ok(h("Copilot, fuel")["command"] == "fuel" and h("Copilot tyres")["command"] == "tyres" and h("Copilot how many laps left")["command"] == "lap", "plain questions are unchanged")
r = h("Copilot where am I losing time"); print("     ", r["reply"]); ok(r["command"] == "corners", "where the time goes")
V.CAP.take = lambda col, store, log, image=None, kept=None: "Sheet filed for the test car."
r = h("Copilot, take a screenshot"); ok(r["command"] == "captures" and r["reply"].startswith("Fetching the screenshot"), "take a screenshot starts the fetch")
import time; time.sleep(0.3); ok(("voice", "Sheet filed for the test car.") in said, "...and the result is spoken when it is done")
ok(h("Copilot sing me a song")["reply"] == "Say again?", "an unknown command asks again")

# the earpiece's door
PORT = 18766; URL = f"http://127.0.0.1:{PORT}"
V.transcribe = lambda wav: "Copilot, fuel" if len(wav) > 100 else ""
server.serve(PORT, hub, lambda: dict(live=True), say, lambda on: None, hear=vo.hear, hear_text=vo.hear_text)
b = io.BytesIO()
with wave.open(b, "wb") as w: w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000); w.writeframes(b"\0\0" * 16000)
def post(headers):
    try:
        with urllib.request.urlopen(urllib.request.Request(URL + "/api/hear", data=b.getvalue(), headers=headers), timeout=5) as r: return r.status, json.load(r)
    except urllib.error.HTTPError as e: return e.code, {}
ok(post({})[0] == 401 and post({"X-GT7C-Earpiece": "wrong"})[0] == 401, "speech is only accepted with the earpiece token")
code, out = post({"X-GT7C-Earpiece": "ear-token"}); ok(code == 200 and out["command"] == "fuel" and out["reply"].startswith("Fuel "), "speech from the earpiece is transcribed, understood and answered")
typed = lambda headers, method="POST": urllib.request.Request(URL + "/api/heartext?text=copilot%20tyres", data=b"" if method == "POST" else None, headers=headers, method=method)
out = json.load(urllib.request.urlopen(typed({"X-GT7C": "1"}))); ok(out["command"] == "tyres", "typed commands work the same way")
def refused(req):
    try: urllib.request.urlopen(req); return 200
    except urllib.error.HTTPError as e: return e.code
ok(refused(typed({})) == 400 and refused(typed({}, "GET")) == 405, "...but not from another site's page: POST with the page's own header only")
shutil.rmtree(tmp); print("voice: all passed")
