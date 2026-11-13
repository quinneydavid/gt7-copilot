import json, os, shutil, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [ROOT, os.path.join(ROOT, "tests")]
import sim
from gt7copilot import analysis as A
from gt7copilot.collector import Collector
from gt7copilot.packet import decrypt, parse
from gt7copilot.store import Store

tmp = tempfile.mkdtemp(); st = Store(tmp); c = Collector(st)
laps = [{}, {}, {"early_brake": {1: 30}}, {"slow": {2: 0.9}}, {"wheelspin": True}]
wall = 1000.0
for pkt in sim.packets(laps):
    row, meta = parse(decrypt(pkt)); wall += 1 / 60; c.feed(row, meta, wall)
tr = st.tracks()[0]
print("track", round(tr["length"]), "m corners", [(k["n"], round(k["start"]), round(k["apex"]), round(k["end"]), k["dir"], k["radius"]) for k in tr["corners"]])
rows = st.q("SELECT * FROM laps ORDER BY id"); ref = st.best_lap(tr["id"], 3265)
print("best lap", ref["lap_no"], A.fmt_time(ref["time_ms"]))
for r in rows:
    an = json.loads(r["analysis"]); adv = [A.advise(z, zr) for z, zr in zip(an["zones"], ref["analysis"]["zones"])]
    print("lap", r["lap_no"], A.fmt_time(r["time_ms"]), "zone-sum", round(sum(z["time"] for z in an["zones"]), 2),
          "spin_r", an["summary"]["spin_r_s"], "advice", [a for a in adv if a])
print("zone sample", ref["analysis"]["zones"][1]); print("summary", {k: v for k, v in ref["analysis"]["summary"].items() if not isinstance(v, dict)})
shutil.rmtree(tmp)
