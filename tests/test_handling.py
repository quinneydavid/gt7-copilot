"""Handling analysis + tune advice on the simulated driver: each fault put into the car must come out as the right advice."""
import json, os, shutil, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [ROOT, os.path.join(ROOT, "tests")]
import sim
from gt7copilot import cli, tuneadvice as T
from gt7copilot.collector import Collector
from gt7copilot.packet import decrypt, parse
from gt7copilot.store import Store

SHEET = dict(tyres=dict(front="Racing Hard", rear="Racing Hard"),
             suspension=dict(anti_roll_bar=[5, 5], natural_frequency_hz=[2.2, 2.4], negative_camber_deg=[2.5, 1.5], toe_deg=[0.0, -0.1]),
             differential=dict(initial_torque=[None, 10], acceleration_sensitivity=[None, 20], braking_sensitivity=[None, 5]),
             aero=dict(downforce=[100, 200]), transmission=dict(top_speed_kmh=250), brake_balance=2)
ok = lambda name, cond: print(("PASS " if cond else "FAIL ") + name) or cond
res = []

def drive(fault, sheet=None, laps=5, show=False):
    tmp = tempfile.mkdtemp(); st = Store(tmp); c = Collector(st, log=lambda m: None)
    if sheet:
        cli.run(st, ["tune-set", "3265", sheet])
    wall = 1000.0
    lead = dict(no_steer=True) if fault.get("no_steer") else {}     # the opening lap counts now (it starts at speed): keep it steering-less too
    for pkt in sim.packets([lead] + [fault] * laps):
        row, meta = parse(decrypt(pkt)); wall += 1 / 60; c.feed(row, meta, wall)
    d = cli.run(st, ["debrief"]); shutil.rmtree(tmp)
    if show:
        print(json.dumps(d["tune_advice"], indent=1)[:1800])
    return d["tune_advice"]

a = drive({})
res.append(ok("clean laps: nothing to fix", a["ready"] and not a["items"]))
a = drive(dict(brake_spin=1, rear_lock=True), SHEET, show=True)
top = a["items"][0]
res += [ok("spins under braking found", top["key"] == "entry_oversteer"),
        ok("first fix = brake balance 2 -> 1", top["fixes"][0]["setting"] == "brake balance" and top["fixes"][0]["now"] == 2 and top["fixes"][0]["to"] == 1),
        ok("sheet suspects named", {x["setting"] for x in top["suspect_settings"]} == {"brake balance", "suspension › toe deg › rear", "differential › braking sensitivity › rear"})]
a = drive(dict(entry_slide=True))
res += [ok("entry slide without sheet: direction only", a["items"][0]["key"] == "entry_oversteer" and "to" not in a["items"][0]["fixes"][0])]
a = drive(dict(understeer=1.8), SHEET)
res.append(ok("understeer found from steering", a["items"][0]["key"] == "understeer" and a["items"][0]["fixes"][0]["to"] == 4))
a = drive(dict(understeer=1.8, no_steer=True), SHEET)
res.append(ok("no steering data: understeer not claimed, note given", not a["items"] and any("No steering data" in x for x in a["notes"])))
a = drive(dict(inside_spin=True), SHEET)
res.append(ok("one-wheel spin -> more diff lock", a["items"][0]["key"] == "one_wheel_spin" and a["items"][0]["fixes"][0]["to"] == 25))
a = drive(dict(limiter=True), SHEET)
res.append(ok("limiter -> longer gearing", a["items"][0]["key"] == "gearing_short" and a["items"][0]["fixes"][0]["to"] == 260))
a = drive({}, laps=1)
res.append(ok("too few laps: not ready", not a["ready"]))
print("ALL PASS" if all(res) else "FAILURES"); sys.exit(0 if all(res) else 1)

# ---- the game's own words, parts to fit, tyres
from gt7copilot import sheet as SH, tuneadvice as TA2
assert SH.game_label("suspension.anti_roll_bar", "rear") == "Suspension: Anti-Roll Bar (Rear)" and SH.game_label("brake_balance") == "Brakes: Front/Rear Balance"
assert SH.compound("Racing Medium") == "Racing: Medium" and SH.softer("RM") == "Racing: Soft" and SH.softer("Racing: Soft") is None and SH.softer("Racing Hard", -1) is None
fx = TA2._fix(dict(suspension=dict(anti_roll_bar=[None, None]), brake_balance=None), "brake_balance", None, -1, "x")
assert fx["needs_part"] == "Brake Controller" and fx["game_setting"] == "Brakes: Front/Rear Balance", fx
assert TA2._split_fix(dict(differential=dict(front_rear_torque_split="45:55")), 5, "x")["to"] == "40:60"
print("PASS game wording, parts, tyres helpers")
sh2 = dict(suspension=dict(anti_roll_bar=[6, 5]), differential=dict(acceleration_sensitivity=[10, 15]), brake_balance=-1, tyres=dict(front="Racing Medium", rear="Racing Medium"))
v = SH.view(sh2, [dict(path="suspension.anti_roll_bar", end="front", to=5, problem="p"), dict(path="tyres", end=None, to="Racing: Soft", problem="t")])
assert [x["section"] for x in v] == ["Tires", "Suspension", "Differential Gear", "Brakes"], v
assert v[1]["rows"][0]["cells"][0] == dict(end="front", value="5", was="6", why="p") and v[0]["rows"][0]["cells"][1]["value"] == "Racing: Soft"
print("PASS sheet view in the game's order")
