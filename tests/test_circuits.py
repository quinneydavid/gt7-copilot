"""Naming a track from where the car drives: laps laid over the known outlines (data/circuits.json)."""
import math, os, sys, tempfile
os.environ["GT7C_DATA"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
from gt7copilot import circuits as CI
from gt7copilot.collector import name_tracks
from gt7copilot.store import Store

ok = lambda cond, what: (print(("ok   " if cond else "FAIL ") + what), cond or sys.exit(1))
grid, circuits = CI.load()
by = {c["id"]: c for c in circuits}
ok(len(circuits) >= 80 and grid == 16, f"the outlines are there ({len(circuits)} layouts)")

def drive(cid, reverse=False, share=1.0, wobble=3.0):
    """A line through an outline's squares, a point every 4 m, a few metres off the centre of each square."""
    cells = by[cid]["cells"][::-1] if reverse else by[cid]["cells"]
    loop = max(abs(cells[0][0] - cells[-1][0]), abs(cells[0][1] - cells[-1][1])) <= 20       # not a point-to-point course
    cells = cells[:max(2, int(len(cells) * share))] + ([cells[0]] if share == 1.0 and loop else [])
    sgn = lambda v: 1 if v >= 0 else -1
    mid = [(kx * 16 + sgn(kx) * 8 + wobble * math.sin(i), kz * 16 + sgn(kz) * 8 + wobble * math.cos(i)) for i, (kx, kz) in enumerate(cells)]
    pts = []
    for a, b in zip(mid, mid[1:]):
        n = max(1, int(math.hypot(b[0] - a[0], b[1] - a[1]) / 4))
        pts += [(a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n) for k in range(n)]
    return pts, sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(pts, pts[1:]))

BW = "WillowSpringsInternationalRacewayBigWillow"
pts, _ = drive(BW); got = CI.name_lap(pts, by[BW]["length"]); print("     ", got)
ok(got and got["name"] == "Willow Springs International Raceway: Big Willow" and not got["reverse"], "a lap of Big Willow is named, layout included")
ok(CI.name_lap(pts, 3920)["id"] == BW, "...also with the length the copilot measured in a real race (3920 m)")
wrong = 0
for c in circuits:                                        # every outline, driven both ways, is named as itself
    for rev in (False, True):
        p, _ = drive(c["id"], rev); g = CI.name_lap(p, c["length"])
        same = g and (g["id"] == c["id"] or by[g["id"]]["set"] == c["set"])        # two entries for one ribbon of tarmac count as the same
        good = same and (g["reverse"] == rev or "lockwise" in c["name"] or by[g["id"]]["set"] == c["set"] and g["id"] != c["id"])
        if not good:
            wrong += 1; print("      not itself:", c["id"], "reverse" if rev else "", "->", g and g["name"])
ok(wrong == 0, f"all {len(circuits)} layouts are told apart, forwards and reversed")
p, _ = drive("AutodromeLagoMaggioreEast", reverse=True)
ok(CI.name_lap(p, by["AutodromeLagoMaggioreEast"]["length"])["name"] == "Autodrome Lago Maggiore - East (Reverse)", "a lap against the outline's order is the reverse layout")
ok(CI.name_lap([(x + 5000, z) for x, z in pts], by[BW]["length"]) is None, "a lap that lies on no outline gets no name")
ok(CI.name_lap(pts, by[BW]["length"] * 1.3) is None, "a lap of the wrong length gets no name")
part, driven = drive(BW, share=0.25)
ok(CI.guess(part, driven) == "Willow Springs International Raceway", "a quarter of a lap gives the track, without the layout")
ok(CI.guess(part[:40], 160.0) is None, "the first metres give no guess")

st = Store(os.environ["GT7C_DATA"])
ref = np.array([(x, 0.0, z) for x, z in pts[::1]])
tid = st.add_track(ref, by[BW]["length"], [], None)
tid2 = st.add_track(np.array([(x + 9000, 0.0, z) for x, z in pts]), 3900.0, [], None)
logs = []; n = name_tracks(st, logs.append)
t = st.track(tid)
ok(n == 1 and t["name"].endswith("Big Willow") and t["name_src"] == "outline" and st.track(tid2)["name"] is None, "tracks already driven are named at start, unknown ones are left alone")
st.x("UPDATE tracks SET name='My name', name_src='you' WHERE id=?", tid); name_tracks(st, logs.append)
ok(st.track(tid)["name"] == "My name", "a name that is already there is never replaced")
print("circuits: all passed")
