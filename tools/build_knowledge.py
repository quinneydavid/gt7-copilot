#!/usr/bin/env python3
"""Writes data/knowledge.json: the tuning datapoints that ship with GT7 Copilot. Edit the rows here, run this, commit both.
Every row is one checkable statement from a named source. Nothing is filled in from memory or guesswork.

Row fields (see gt7copilot/knowledge.py):
  kind       baseline = where to start | fix = what to change for a symptom | effect = what a setting does | example = a real car's values
  setting    settings-sheet path (gt7copilot sheet-template), end = front | rear | None (both / not paired)
  drivetrain list of FF FR MR RR 4WD, or None = any
  symptom    one of gt7copilot.knowledge.SYMPTOMS (same keys as the tune advice), or None
  direction  raise | lower | None;  value = number, or position in the car's own range: "min", "max", "20-40%" (unit "range")
  text       the statement, one line;  tradeoff = what it costs, if the source says
  scope      conditions the source attaches (tyres, car type)
"""
import json, os

DGNF = dict(title="DG Edge: Understanding Natural Frequency in Gran Turismo 7", url="https://dg-edge.com/articles/guides-tuning/understanding-natural-frequency-in-gran-turismo-7/407")
DGLSD = dict(title="DG Edge: Understanding Limited Slip Differential (LSD) in Gran Turismo 7", url="https://www.dg-edge.com/articles/guides-tuning/understanding-limited-slip-differential-lsd-in-gran-turismo-7/408")
DGDMP = dict(title="DG Edge: Understanding Damper Ratios in Gran Turismo 7", url="https://dg-edge.com/articles/guides-tuning/understanding-damper-ratios-in-gran-turismo-7/405")
DGARB = dict(title="DG Edge: Understanding Anti-Roll Bars (ARBs)", url="https://dg-edge.com/articles/guides-tuning/understanding-anti-roll-bars-arbs/406")
CDA = dict(title="Coach Dave Academy: Gran Turismo 7 tuning explained", url="https://coachdaveacademy.com/tutorials/gran-turismo-7-tuning-explained")
TRX = dict(title="Traxion: Gran Turismo 7 front-wheel drive setup guide", url="https://traxion.gg/gran-turismo-7-front-wheel-drive-setup-guide-2/")

NF, ARB = "suspension.natural_frequency_hz", "suspension.anti_roll_bar"
CMP, EXP = "suspension.damping_compression_pct", "suspension.damping_expansion_pct"
TOE, RH = "suspension.toe_deg", "suspension.ride_height_mm"
LI, LA, LB = "differential.initial_torque", "differential.acceleration_sensitivity", "differential.braking_sensitivity"
DF, BB = "aero.downforce", "brake_balance"
RACING = "racing tyres"
R = []


def row(kind, setting, text, src, end=None, dt=None, symptom=None, direction=None, value=None, unit=None, tradeoff=None, scope=None, **more):
    R.append(dict(kind=kind, setting=setting, end=end, drivetrain=dt, symptom=symptom, direction=direction, value=value, unit=unit,
                  text=text, tradeoff=tradeoff, scope=scope, source=src, **more))


# ---- natural frequency (springs): starting points by layout ------------------------------------------------------------------
row("baseline", NF, "Front springs at the softest setting the car allows.", DGNF, "front", ["FF", "FR", "MR", "4WD"], value="min", unit="range", scope=RACING)
row("baseline", NF, "Rear at 50-60 % of the car's range, for maximum rotation.", DGNF, "rear", ["FF", "4WD"], value="50-60%", unit="range", scope=RACING)
row("baseline", NF, "Rear at the softest setting for traction, or 20-40 % of the range for rotation.", DGNF, "rear", ["FR"], value="min or 20-40%", unit="range", scope=RACING)
row("baseline", NF, "Rear at the softest setting too, to prevent oversteer into corners. Raise the rear only once the car is stable on entry.", DGNF, "rear", ["MR"], value="min", unit="range", scope=RACING)
row("baseline", NF, "As a default, run the rear slightly stiffer than the front; match overall stiffness to the downforce level and tyre compound.", CDA)
row("effect", NF, "Front softer than rear improves rotation, stability and predictability in most cars.", DGNF)
row("effect", NF, "Soft front with a stiff rear rotates in every phase of the corner.", DGNF, "rear", direction="raise", tradeoff="can turn into oversteer if overdone; suits cars that are stable on the throttle")
row("effect", NF, "Soft front and soft rear is a stable platform with good traction out of corners.", DGNF, "rear", direction="lower", tradeoff="gives up some rotation; suits cars that rotate well but snap on the throttle")
row("effect", NF, "Stiff front with a soft rear is not advised: it kills rotation. Correct oversteer with anti-roll bars and dampers instead.", DGNF, "front", direction="raise")
row("fix", NF, "Soften the rear springs for more rear grip.", DGNF, "rear", ["MR"], "entry_oversteer", "lower")
# ---- differential ----------------------------------------------------------------------------------------------------------
row("baseline", LI, "Start with initial torque low.", DGLSD, value="low")
row("baseline", LA, "Start with acceleration sensitivity in the middle of the range.", DGLSD, value="mid")
row("baseline", LB, "Start with braking sensitivity low.", DGLSD, value="low")
row("baseline", LA, "Set it as high as you are comfortable with, for predictable rotation on the power.", CDA)
row("baseline", LB, "Set it as low as you can manage, to avoid understeer into corners.", CDA)
row("effect", LI, "Preload: how much force it takes before the differential starts to work. Higher = it changes between open and locked sooner.", DGLSD)
row("effect", LA, "A fully locked differential is snappy and breaks traction easily; in front-wheel-drive cars it causes understeer.", DGLSD, direction="raise")
row("effect", LA, "A fully open differential is stable and does not snap.", DGLSD, direction="lower", tradeoff="less drive out of corners; the inside wheel spins")
row("fix", LA, "The car is too snappy on the power: lower acceleration sensitivity.", DGLSD, symptom="exit_oversteer", direction="lower")
row("fix", LA, "The inside wheel spins: raise acceleration sensitivity.", DGLSD, symptom="one_wheel_spin", direction="raise")
row("fix", LB, "The car oversteers into corners: raise braking sensitivity.", DGLSD, symptom="entry_oversteer", direction="raise")
row("fix", LB, "The car understeers into corners: lower braking sensitivity.", CDA, symptom="understeer", direction="lower")
row("example", None, "Porsche 911 RSR: initial 5, acceleration 15, braking sensitivity high. Very stable into corners.", DGLSD, dt=["MR"], car=3311,
    car_name="Porsche 911 RSR (991) '17", sheet=dict(differential=dict(initial_torque=[None, 5], acceleration_sensitivity=[None, 15])))
row("example", None, "Aston Martin V12 Vantage GT3: initial low, acceleration 35, braking sensitivity low. The car is tail-happy, so more lock on the power.", DGLSD, dt=["FR"],
    car=2131, car_name="Aston Martin V12 Vantage GT3 '12", sheet=dict(differential=dict(acceleration_sensitivity=[None, 35])))
# ---- dampers ---------------------------------------------------------------------------------------------------------------
for sym, setting, end, d, cost in (
        ("entry_oversteer", CMP, "front", "raise", "less rotation"), ("entry_oversteer", EXP, "rear", "lower", None),
        ("understeer", CMP, "front", "lower", None), ("understeer", EXP, "rear", "raise", None),
        ("exit_understeer", CMP, "rear", "raise", "less rear traction"), ("exit_understeer", EXP, "front", "raise", None),
        ("exit_oversteer", CMP, "rear", "lower", "less rotation out of the corner"), ("exit_oversteer", EXP, "front", "lower", "less rotation out of the corner")):
    what = "compression" if setting == CMP else "expansion (rebound)"
    phase = dict(entry_oversteer="Oversteer into the corner", understeer="Understeer into the corner", exit_understeer="Understeer out of the corner",
                 exit_oversteer="Oversteer out of the corner")[sym]
    row("fix", setting, f"{phase}: {d} {end} {what}.", DGDMP, end, symptom=sym, direction=d, tradeoff=cost)
row("effect", CMP, "Too much damping at one end causes chatter and a lack of grip at the other end; keep compression and expansion in balance.", DGDMP)
row("effect", EXP, "For racing, expansion (rebound) is set higher than compression.", TRX)
# ---- anti-roll bars --------------------------------------------------------------------------------------------------------
row("effect", ARB, "Scale 1-10, a higher number is stiffer.", DGARB)
row("fix", ARB, "Understeer into or through the corner: soften the front bar.", DGARB, "front", symptom="understeer", direction="lower", tradeoff="too far and the car turns unstable")
row("fix", ARB, "Understeer into or through the corner: stiffen the rear bar.", DGARB, "rear", symptom="understeer", direction="raise", tradeoff="too far and the car turns unstable")
row("fix", ARB, "Oversteer into or through the corner: stiffen the front bar.", DGARB, "front", symptom="entry_oversteer", direction="raise", tradeoff="too far causes understeer")
row("fix", ARB, "Oversteer into or through the corner: soften the rear bar.", DGARB, "rear", symptom="entry_oversteer", direction="lower", tradeoff="too far causes understeer")
row("fix", ARB, "Not enough rear traction out of corners: soften the rear bar (and stiffen the front).", DGARB, "rear", symptom="exit_oversteer", direction="lower", tradeoff="too far causes understeer")
# ---- toe, ride height ------------------------------------------------------------------------------------------------------
row("effect", TOE, "Toe-out helps the first part of turn-in.", CDA, "front", direction="lower", tradeoff="slower in long, settled corners")
row("effect", TOE, "Toe-in steadies a rear-wheel-drive car under braking and on the power. Rear toe changes are clearly felt.", CDA, "rear", ["FR", "MR", "RR"], direction="raise")
row("effect", TOE, "The further from zero, the more the tyres scrub: more tyre wear, less straight-line speed.", CDA)
row("fix", TOE, "Poor turn-in: consider front toe-out.", CDA, "front", symptom="understeer", direction="lower")
row("effect", RH, "Ride height has the most drastic effect on handling of any setting.", CDA)
row("effect", RH, "Rear higher than front (positive rake) gives sharper cornering; rear lower than front raises top speed.", CDA)
row("baseline", RH, "As low as the car goes without bottoming out, for most tarmac racing.", TRX, value="min", unit="range")
# ---- downforce, brakes, ballast, gears --------------------------------------------------------------------------------------
row("baseline", DF, "Set downforce first: most cornering grip comes from it. Front at maximum for turn-in.", CDA, "front", value="max", unit="range")
row("baseline", DF, "Then adjust the rear wing for high-speed balance.", CDA, "rear")
row("fix", DF, "Poor turn-in: maximum front downforce.", CDA, "front", symptom="understeer", direction="raise")
row("fix", DF, "Top speed suffers from drag: lower front and rear together.", CDA, symptom="gearing_long", direction="lower")
row("effect", BB, "Towards the front: more stability and stopping power. Towards the rear: better trail braking and rotation, easier on the front tyres.", CDA)
row("effect", "ballast_kg", "Avoid ballast where possible and run the car as light as allowed. If it is needed, where it sits changes the weight balance a lot. Set ballast before suspension.", CDA)
row("baseline", "transmission.gears", "A long first gear, a short top gear, and gaps that narrow as you go up. Peaky engines need closer ratios.", CDA)
row("effect", "tyres", "The tyre compound decides how stiff the suspension and how much downforce the car should run.", CDA)
# ---- one complete worked example -------------------------------------------------------------------------------------------
row("example", None, "Honda Civic Type R (EK) '98 at Brands Hatch Indy, time trial: the author's final values. Stiff-front/soft-rear springs (3.20/1.46 Hz) were 'horrible'; "
    "braking sensitivity at 5 caused oversteer into corners; rear ballast gave no lap time.", TRX, dt=["FF"], car=204, car_name="Honda Civic Type R (EK) '98", track="Brands Hatch Indy Circuit",
    sheet=dict(suspension=dict(ride_height_mm=[85, 85], natural_frequency_hz=[2.05, 2.05], anti_roll_bar=[6, 1], negative_camber_deg=[5.0, None], toe_deg=[0.14, -0.10]),
               differential=dict(initial_torque=[20, None], acceleration_sensitivity=[40, None])))
row("effect", ARB, "On a front-wheel-drive car a softer front and stiffer rear bar encourages rotation; the softest front with the stiffest rear was a few tenths slower.", TRX, dt=["FF"])
row("effect", TOE, "On a front-wheel-drive car a little rear toe-out helps the rear steer the car through the corner.", TRX, "rear", ["FF"], direction="lower")

for i, r in enumerate(R, 1):
    r["id"] = f"k{i:03d}"
out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data/knowledge.json")
json.dump(dict(reviewed="2026-11-11", rows=R), open(out, "w"), indent=1, ensure_ascii=False)
print(len(R), "rows ->", out)
