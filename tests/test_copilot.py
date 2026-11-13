import os, shutil, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [ROOT, os.path.join(ROOT, "tests")]
import sim
from gt7copilot.collector import Collector
from gt7copilot.copilot import Copilot
from gt7copilot.packet import decrypt, parse
from gt7copilot.store import Store

tmp = tempfile.mkdtemp(); c = Collector(Store(tmp), log=lambda m: None); said = []
state = {"lap": 0}
co = Copilot(lambda text, ttl, kind: said.append((state["lap"], kind, round(ttl, 1), text)), log=lambda m: None); c.listeners.append(co)
import gt7copilot.copilot as ZC; ZC.LEAD = float(os.environ.get("LEAD", 6))
laps = [{}, {}, {"early_brake": {1: 30}}, {}, {"slow": {2: 0.9}}, {"slow": {2: 0.95}}, {}, {}]
hot = lambda lap: (112, 111, 90, 91) if lap >= 6 else (70, 70, 72, 72)
wall = 1000.0
for pkt in sim.packets(laps, total_laps=12, fuel=20.0, fuel_per_lap=2.5, tyre=hot):
    row, meta = parse(decrypt(pkt)); state["lap"] = meta["lap"]; wall += 1 / 60; c.feed(row, meta, wall)
for s in said: print(s)
shutil.rmtree(tmp)

# ---- real-lap lessons (11 Nov 2026): incidents get a caution, absurd numbers are never quoted, corners are judged
# against the best attempt at each corner, a rolling-start opening lap is a fair lap
from gt7copilot import analysis as A, speech as S
ref = dict(n=7, time=11.3, min_speed=147.6, brake_s=2072.0, throttle_s=2116.0, exit_speed=173.0)
spin = dict(n=7, time=16.4, min_speed=45.4, throttle_s=2056.0, exit_speed=115.5)
adv = A.advise(spin, ref)
assert adv["cause"] == "incident" and S.pre_corner(adv) == "Turn seven. Careful. You lost five point one seconds here last lap.", S.pre_corner(adv)
far = dict(n=8, time=22.4, min_speed=175.0, brake_s=2742.0, throttle_s=3264.0, exit_speed=182.0)
adv = A.advise(far, dict(n=8, time=21.6, min_speed=180.5, brake_s=3066.0, throttle_s=3264.0, exit_speed=182.7))
assert "metres" not in adv and adv["cause"] in ("apex_slow", "time"), adv          # 324 m is not a braking tip
near = A.advise(dict(n=1, time=11.9, min_speed=138.0, brake_s=196.0), dict(n=1, time=11.6, min_speed=138.3, brake_s=216.0))
assert near["cause"] == "brake_early" and near["metres"] == 20, near
bz = A.best_zones([[dict(n=1, time=12.2), dict(n=2, time=15.1)], [dict(n=1, time=10.4), None], [None, dict(n=2, time=14.7)]])
assert [z["time"] for z in bz] == [10.4, 14.7], bz
bz = A.best_zones([[dict(n=2, time=14.38, min_speed=164.0)], [dict(n=2, time=14.38, min_speed=155.0)], [dict(n=2, time=14.40, min_speed=159.0)], [dict(n=2, time=15.5, min_speed=140.0)]])
assert bz[0]["min_speed"] == 159.0, bz                       # the middle of the three fastest, not the one freak pass
adv = A.advise(dict(n=2, time=15.2, min_speed=138.0), bz[0])
assert adv["cause"] == "apex_slow" and adv["kmh"] == 10 and adv["target"] == 148, adv      # one reachable step
assert S.pre_corner(adv) == "Turn two. Ten kilometres an hour faster at the apex. Target one hundred and forty eight.", S.pre_corner(adv)
assert S.verdict(2, 0.21, 0.0) == "Turn two. Still two tenths down." and S.verdict(3, 0.0, 0.0) == "Turn three. Matched your best."
print("real-lap rules: ok")
assert S.pre_corner(dict(n=2, cause="apex_slow", kmh=4, ref_min_speed=147.0, loss=0.2)) == "Turn two. Four kilometres an hour faster at the apex. Target one hundred and forty seven."
assert S.pre_corner(dict(n=5, cause="exit_slow", kmh=13, loss=0.2)) == "Turn five. Exit thirteen kilometres an hour faster."
print("units spoken: ok")

# ---- end of race: one summary of what to change
tmp2 = tempfile.mkdtemp(); c2 = Collector(Store(tmp2), log=lambda m: None); said2 = []
co2 = Copilot(lambda text, ttl, kind: said2.append((kind, text)), log=lambda m: None); c2.listeners.append(co2)
wall = 5000.0
for pkt in sim.packets([{}, {}, {"slow": {2: 0.9}}, {"early_brake": {1: 30}}, {"slow": {2: 0.9}}, {}], total_laps=5):
    row, meta = parse(decrypt(pkt)); wall += 1 / 60; c2.feed(row, meta, wall)
wrap = [t for k, t in said2 if k == "summary"]
print("summary:", wrap)
assert len(wrap) == 1 and wrap[0].startswith("Race done. Best lap") and "Driving. Most time lost at turn" in wrap[0] and "settings sheet" in wrap[0], wrap
shutil.rmtree(tmp2)
print("race summary: ok")

# ---- race strategy: lean when it gets you home, pit when it cannot, rich when there is fuel to spare
def race(laps, **kw):
    t = tempfile.mkdtemp(); cc = Collector(Store(t), log=lambda m: None); out = []
    cp = Copilot(lambda text, ttl, kind: out.append((kind, text)), log=lambda m: None); cc.listeners.append(cp); w = 9000.0
    for pkt in sim.packets(laps, **kw):
        row, meta = parse(decrypt(pkt)); w += 1 / 60; cc.feed(row, meta, w)
    shutil.rmtree(t); return out
fuel = [t for k, t in race([{}] * 4, total_laps=9, fuel=20.0, fuel_per_lap=2.5) if k == "fuel"]
print("lean:", fuel)
assert fuel[0].startswith("Fuel is short by one lap. Go lean now to finish without a stop. Target two point") and "You are using two point five" in fuel[0], fuel
assert fuel[1].startswith("Still over on fuel."), fuel
fuel = [t for k, t in race([{}] * 3, total_laps=12, fuel=20.0, fuel_per_lap=2.5) if k == "fuel"]
print("pit:", fuel)
assert fuel[0].startswith("Saving will not cover it. Stay rich and push. Pit in") and all("Pit" in f for f in fuel) and len(fuel) >= 2, fuel
fuel = [t for k, t in race([{}] * 8, total_laps=12, fuel=20.0, fuel_per_lap=2.5) if k == "fuel"]
print("countdown:", fuel)
assert any(f.startswith("Pit next lap for fuel.") for f in fuel) and any(f.startswith("Pit this lap for fuel.") for f in fuel) and "Pit now. Pit this lap for fuel." in fuel, fuel
assert S.one_dp(12.44) == "twelve point four" and S.one_dp(10.0) == "ten"
print("fuel strategy: ok")
