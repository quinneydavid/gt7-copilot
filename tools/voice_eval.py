#!/usr/bin/env python3
"""Measures how well the model routes what a driver says (ask.route): about a hundred sentences with the intent each
should get, plus open-microphone cases (room talk must be ignored, race talk answered). Run it after changing the
ROUTE prompt or the model, against the real model:

    GT7C_LLM_KEY=... python3 tools/voice_eval.py . MODEL [http://localhost:11434/v1]

The first argument is the project folder, MODEL the model's name at that OpenAI-compatible address.

It prints the sentences that went wrong, the share that went right and the time per sentence."""
import os, sys, time, tempfile, shutil, json
if len(sys.argv) < 3: sys.exit(__doc__)
src = sys.argv[1]; model = sys.argv[2]
tmp = tempfile.mkdtemp()
if os.path.exists(os.path.join(src, "data", "copilot.db")): shutil.copy(os.path.join(src, "data", "copilot.db"), tmp)
os.environ.update(GT7C_DATA=tmp, GT7C_ASK_ON="1", GT7C_SCREENSHOTS_ON="1", GT7C_LLM_URL=(sys.argv[3] if len(sys.argv) > 3 else "http://localhost:11434/v1"), GT7C_VISION_MODEL=model, GT7C_ASK_MODEL=model)
sys.path.insert(0, src)
from gt7copilot import ask as ASK
now = dict(lap=4, total_laps=10, fuel=58.0, fuel_per_lap=9.6, laps_of_fuel_left=6.0, laps_to_go_including_this=7, fuel_needed_per_lap_to_finish=8.3, gap_to_best_lap_s=0.8,
           fuel_verdict="Lean. Target 8.3 a lap to finish without a stop. You are using 9.6.", speed_kmh=187, automatic_calls="on",
           tyre_temps_c=dict(front_left=82, front_right=79, rear_left=88, rear_right=85), best_lap_this_session=132300)
live = dict(live=True, car=3265, track=dict(id=1, name="Willow Springs: Big Willow"), lap=4, total_laps=10, now=dict(kmh=187), laps=[])
C = """
chat|what's my top speed
chat|how fast am I going
chat|am I faster than last lap
last_lap|what was my last lap
last_lap|last lap time
gap,chat|what's the gap
chat,fuel|how many laps until I need to pit
chat,fuel,fuel_map|when should I pit
chat,fuel|do I need to pit
says_pit|I'm pitting this lap
says_pit|box box
says_pit|I'm going to box next lap
says_pit|pitting now for fuel and tyres
says_pit|I will fuel on lap eight
chat,fuel|how much fuel should I take
fuel|how's the fuel
fuel,chat|is the fuel going to last
fuel,chat|can I make it without stopping
fuel_map|what fuel map should I use
fuel_map|recommended fuel mix
says_fuel_map|switching to lean
says_fuel_map|I'm staying rich
chat|I've gone to fuel map three
chat|are my tyres okay
tyres,chat|are the fronts overheating
tyres|how are the tyre temps
chat|which tyres should I fit at the stop
chat|should I go to hards or mediums
chat|my tyres are gone
chat|the rears are shot
chat,car_advice|the car is understeering what should I change
chat,car_advice|I have a lot of oversteer on exit
chat,car_advice|why is the rear so loose
chat|it keeps snapping on me in turn three
chat,losing_time|what should I do in turn five
chat|where should I brake for turn one
losing_time|which corner am I worst at
losing_time|where am I losing time
chat,best_lap|what's a good lap time here
best_lap,chat|what's the lap record
chat|what position am I in
chat|who's behind me
chat|there's a car right behind me
chat|I just spun
chat|I went off at turn four
chat|I got a penalty
chat|yellow flag
chat|it's getting dark
chat|the track is drying
chat|it stopped raining
chat|hey actually it is raining what should I do
chat|what's the weather doing
chat,lap_count|how many laps have I done
lap_count|what lap is it
lap_count|how many laps left
chat,lap_count|how long is left in the race
chat|what's the time
chat|set a timer for ten minutes
says_pit,chat|remind me to pit on lap eight
quiet|be quiet please copilot
quiet|stop talking for a bit
chat,quiet|talk less please
chat|stop telling me about turn seven
chat|you're too loud
repeat,chat|say that again slower
repeat|what did you say
chat,repeat|what did you mean by that
chat,nothing|never mind
chat|thanks copilot
chat|good job
chat|that was a terrible lap
chat|what car am I in
track|what track is this
chat|is this car any good
read_setting|what's the brake balance
read_setting|what should I set the rear differential at
read_setting|read me the suspension
chat,car_advice|should I move the brake balance forward
chat|I moved the brake balance two clicks to the rear
chat|I changed the rear anti-roll bar to four
screenshot|take a screenshot
screenshots_all|read my screenshots
chat|did you get the screenshot
chat|what did the screenshot say
car_advice|what should I change on the car
car_advice,chat|what would you change first
read_changes|read me the settings changes
chat|tell me a joke
chat|play some music
chat|how are you
chat|what can you do
chat|what's your name
chat|I'm tired
chat|I need a break
chat|let's do one more race
chat|that guy just hit me
hello|can you hear me
hello|radio check
chat|how's my speed
chat|should I race my car or clean the house
chat|which of my cars is fastest at Big Willow
chat|what car do you recommend we take on this track next
"""
OPEN_NOTHING = ["Rex get down", "I'll be there in a minute", "dinner is ready", "oh my god", "I'll close the door so it doesn't rattle there", "love you dude",
                "okay I'll leave it open for a bit so Rex can walk around", "whoa what are you doing", "no no no come on", "thank you very much"]
rows = [l.split("|", 1) for l in C.strip().splitlines()]
bad = 0; times = []; fails = 0
for want, u in rows:
    t0 = time.time(); r = ASK.route(u, [], live, now, named=True); times.append(time.time() - t0)
    if r is None: fails += 1; print("  NO JSON ::", u); continue
    if r["intent"] not in want.split(","):
        bad += 1; print(f"  want {want:22} got {r['intent']:14} :: {u}  | {str(r.get('say'))[:60]}")
print(f"named: {len(rows) - bad - fails} of {len(rows)} right, {fails} unusable; median {sorted(times)[len(times)//2]:.2f}s, slowest {max(times):.2f}s")
b2 = 0
for u in OPEN_NOTHING:
    r = ASK.route(u, [], live, now, named=False)
    if not r or r["intent"] != "nothing": b2 += 1; print(f"  open mic, should be nothing: got {r and r['intent']} :: {u} | {r and str(r.get('say'))[:50]}")
b3 = 0
for u in ["I just spun", "it's raining now", "the rears are shot", "how's the fuel", "what should I do in turn five", "box box", "I got a penalty", "that guy just hit me"]:
    r = ASK.route(u, [], live, now, named=False)
    if not r or r["intent"] == "nothing": b3 += 1; print(f"  open mic, should be answered: got {r and r['intent']} :: {u}")
print(f"open mic: {len(OPEN_NOTHING) - b2} of {len(OPEN_NOTHING)} room-talk ignored, {8 - b3} of 8 race-talk answered")
# arguments
for u in ["I'm going to box next lap", "I will pit in two laps for tyres", "what's the rear anti-roll bar", "front camber", "I'm staying rich"]:
    r = ASK.route(u, [], live, now, named=True); print("  args:", u, "->", {k: r.get(k) for k in ("intent", "lap", "why", "setting", "end", "map")} if r else None)
