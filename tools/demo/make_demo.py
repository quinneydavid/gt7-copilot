#!/usr/bin/env python3
"""Fill a new data folder with made-up driving, for the README pictures and for looking around without a console.

  python3 tools/demo/make_demo.py /tmp/gt7c-demo
  GT7C_DATA=/tmp/gt7c-demo GT7C_PORT=8765 python3 -m gt7copilot.daemon      # then open http://127.0.0.1:8765

Everything goes in through the app's own code: the simulated car's packets through the collector, the settings sheets
and library tunes through the command line's functions. Six sessions over the last week, two cars, three layouts.
The clock is moved while it runs, so the sessions are dated over the last days. Nothing here is real driving."""
import copy, os, sys, time

if len(sys.argv) != 2 or sys.argv[1].startswith("-"):
    sys.exit(__doc__)
DATA = os.path.abspath(sys.argv[1])
if os.path.exists(os.path.join(DATA, "copilot.db")):
    sys.exit(f"{DATA} already holds a copilot database. Give a new folder.")
os.makedirs(DATA, exist_ok=True)
os.environ["GT7C_DATA"] = DATA                       # before the app is imported: it reads the folder once
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path[:0] = [ROOT, os.path.dirname(os.path.abspath(__file__))]
import sim                                           # noqa: E402
from gt7copilot import cli                           # noqa: E402
from gt7copilot.collector import Collector           # noqa: E402
from gt7copilot.packet import decrypt, parse         # noqa: E402
from gt7copilot.store import Store                   # noqa: E402

GR86, GT3RS = 3481, 3539
TSUKUBA, BRANDS, SUZUKA = "Tsukuba Circuit", "Brands Hatch Indy Circuit", "Suzuka Circuit"

# The sheet on the GR86, in the shape `gt7copilot sheet-template` gives. The gearbox is the one the simulated car reports.
SHEET = dict(
    pp=549.62, power_hp=262, weight_kg=1180, tyres=dict(front="Sports: Soft", rear="Sports: Soft"),
    suspension=dict(ride_height_mm=[105, 110], anti_roll_bar=[7, 4], damping_compression_pct=[32, 30], damping_expansion_pct=[42, 40],
                    natural_frequency_hz=[2.30, 2.40], negative_camber_deg=[2.2, 1.6], toe_deg=[0.0, 0.20]),
    differential=dict(initial_torque=[None, 10], acceleration_sensitivity=[None, 40], braking_sensitivity=[None, 20]),
    ecu_output_pct=100, ballast_kg=0, ballast_position=0, power_restrictor_pct=100,
    transmission=dict(type="Fully Customizable: Racing", top_speed_kmh=230, gears=list(sim.GEARS), final_gear=4.1),
    brake_balance=-2,
    hardware=dict(suspension="Fully Customizable Suspension", differential="Fully Customizable LSD", ecu="Full Control Computer",
                  air_cleaner="Racing", muffler="Racing", exhaust_manifold="Racing", brake_system="Racing (Slotted Discs)", brake_pads="Racing",
                  brake_balance="Brake Controller", clutch_flywheel="Semi-Racing", weight_reduction_1="Fitted", weight_reduction_2="Fitted"))
LOOSER = copy.deepcopy(SHEET); LOOSER["differential"]["acceleration_sensitivity"] = [None, 35]
FAST = copy.deepcopy(SHEET)
FAST.update(pp=599.4, power_hp=318, weight_kg=1120, tyres=dict(front="Racing: Hard", rear="Racing: Hard"), brake_balance=-1,
            transmission=dict(type="Fully Customizable: Racing", top_speed_kmh=260, gears=[2.92, 2.05, 1.58, 1.26, 1.04, 0.88], final_gear=3.9))
FAST["suspension"].update(ride_height_mm=[95, 100], anti_roll_bar=[5, 5], natural_frequency_hz=[2.60, 2.75])
RS = dict(pp=699.8, power_hp=532, weight_kg=1400, tyres=dict(front="Racing: Medium", rear="Racing: Medium"),
          suspension=dict(ride_height_mm=[85, 95], anti_roll_bar=[5, 6], damping_compression_pct=[35, 38], damping_expansion_pct=[45, 48],
                          natural_frequency_hz=[2.90, 3.20], negative_camber_deg=[3.0, 2.0], toe_deg=[0.0, 0.25]),
          differential=dict(initial_torque=[None, 15], acceleration_sensitivity=[None, 25], braking_sensitivity=[None, 30]),
          aero=dict(downforce=[230, 420]), brake_balance=0)
SOURCE = "Example Tuning Notes"                      # not a real publisher: the links go to example.com

# How the car behaves on each sheet, in seconds per lap (see sim.DRIVER). The first sheet spins its rear wheels out of slow corners.
TIGHT = dict(wheelspin=2.4, exit_slide=1.4, understeer=0.8, front_lock=0.9)
LOOSE = dict(wheelspin=0.7, exit_slide=0.0, understeer=0.8, front_lock=0.9, pace=1.0015)
CALM = dict(wheelspin=0.5, understeer=0.2, front_lock=0.2)

real_time = time.time
clock = [0.0]
time.time = lambda: clock[0]                         # the app stamps what it stores with the time: here that is the story's time
st = Store(DATA)


def at(days_ago, hour, minute=0):
    """Move the clock to that time of day, so many days before today."""
    lt = time.localtime(real_time() - days_ago * 86400)
    clock[0] = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, hour, minute, 0, 0, 0, -1))


def session(track, car, laps, driver, race=False):
    col = Collector(st, log=lambda m: None)
    for pkt in sim.packets(track, car, laps, driver, race):
        row, meta = parse(decrypt(pkt)); clock[0] += 1 / 60; col.feed(row, meta, clock[0])
    best = min(l["time_ms"] for l in col.session_laps)
    print(f"  session {col.session}: {sim.CARS[car]['name']}, {track}, {len(col.session_laps)} laps, best {best / 1000:.3f} s", flush=True)


def file(cmd, *args):
    out = cli.run(st, [cmd, *args])
    if not out or out.get("error") or out.get("check"):
        sys.exit(f"{cmd} was not taken: {out}")
    return out


def main():
    print(f"Filling {DATA}")
    at(6, 19, 40)
    grip = file("lib-add", str(GR86), dict(title="Tsukuba 550 PP grip setup", author=SOURCE, url="https://example.com/gt7/gr86-tsukuba-550",
                                           purpose="Time trial, short circuits", track=TSUKUBA, published=time.strftime("%Y-%m-%d", time.localtime(clock[0] - 50 * 86400)),
                                           notes="A stiff front bar and rear toe-in for a steady car. A base for any short circuit.", sheet=SHEET))["id"]
    file("lib-add", str(GR86), dict(title="600 PP fast-circuit setup", author=SOURCE, url="https://example.com/gt7/gr86-600",
                                    purpose="Races of ten laps or more", notes="Needs the racing tyres and the stage 3 weight reduction.", sheet=FAST))
    at(6, 19, 50); file("tune-set", str(GR86), SHEET)
    at(6, 20, 5); session(TSUKUBA, GR86, 9, dict(TIGHT, seed=3, weak={0: (20, 6), 5: (12, 5)}, late={2: (14, 5)}, off={6: 2}))
    at(5, 21, 10); session(BRANDS, GR86, 12, dict(TIGHT, seed=5, weak={1: (16, 6)}, late={3: (12, 5)}), race=True)
    at(3, 19, 35); file("tune-set", str(GR86), LOOSER, "Looser on the power after the wheelspin at Tsukuba")
    at(3, 19, 50); session(TSUKUBA, GR86, 11, dict(LOOSE, seed=5, learn=0.02, weak={0: (15, 6), 5: (9, 4)}, late={2: (9, 4)}))
    at(3, 20, 20); file("lib-verdict", str(grip), "good", "Steady on the brakes. Spun its wheels out of the hairpins until the differential was loosened.")
    at(2, 20, 25)
    file("lib-add", str(GT3RS), dict(title="700 PP Suzuka setup", author=SOURCE, url="https://example.com/gt7/911-gt3-rs-suzuka-700",
                                     purpose="Sport mode races", track=SUZUKA, notes="High rear downforce for the esses.", sheet=RS))
    at(2, 20, 30); session(SUZUKA, GT3RS, 8, dict(CALM, seed=11, weak={3: (18, 6), 9: (14, 5)}, late={6: (12, 5)}))
    at(1, 20, 40); session(BRANDS, GT3RS, 10, dict(CALM, seed=13, weak={1: (14, 5)}, off={4: 3}))
    at(1, 21, 15); session(BRANDS, GR86, 8, dict(LOOSE, seed=17, learn=0.015, weak={1: (12, 5)}, late={3: (8, 4)}))
    time.time = real_time
    print("Done. Start the copilot on it:\n  GT7C_DATA=" + DATA + " python3 -m gt7copilot.daemon")


if __name__ == "__main__":
    main()
