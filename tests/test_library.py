"""Tune library end to end on the simulated driver: file tunes, drive, check the session is linked and the copilot says so."""
import json, os, shutil, sys, tempfile, threading, urllib.request
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [ROOT, os.path.join(ROOT, "tests")]
os.environ["GT7C_TOKEN"] = "t0ken"
import sim
from gt7copilot import cli, library as L, sheet as S
from gt7copilot.collector import Collector
from gt7copilot.copilot import Copilot
from gt7copilot.packet import decrypt, parse
from gt7copilot.server import Hub, serve
from gt7copilot.store import Store

CAR = 3265; GEARS = [3.082, 2.102, 1.546, 1.192, 0.962, 0.814]          # what the simulated car reports
mk = lambda gears, arb: dict(pp=550.2, tyres=dict(front="Sports Soft", rear="Sports Soft"),
                             suspension=dict(anti_roll_bar=[arb, 6], damping_compression_pct=[30, 32], damping_expansion_pct=[40, 42],
                                             natural_frequency_hz=[2.1, 2.3], negative_camber_deg=[2.0, 1.5], toe_deg=[-0.05, 0.2],
                                             ride_height_mm=[90, 95]),
                             differential=dict(initial_torque=[None, 10], acceleration_sensitivity=[None, 20], braking_sensitivity=[None, 15]),
                             transmission=dict(gears=gears, final_gear=4.1), brake_balance=-1)
tmp = tempfile.mkdtemp(); st = Store(tmp); ok = lambda name, cond: print(("PASS " if cond else "FAIL ") + name) or cond
a = cli.run(st, ["lib-add", str(CAR), dict(title="Test grip", author="Tester A", url="https://example.invalid/a", sheet=mk(GEARS, 4))])
b = cli.run(st, ["lib-add", str(CAR), dict(title="Test loose", author="Tester B", sheet=mk([2.9, 2.0, 1.5, 1.2, 1.0, 0.85], 3))])
res = [ok("two tunes filed", a["id"] != b["id"] and not a["check"]),
       ok("re-add replaces", cli.run(st, ["lib-add", str(CAR), dict(title="Test grip", author="Tester A", url="https://example.invalid/a", sheet=mk(GEARS, 4))])["replaced"]),
       ok("source required", "error" in (lambda: (cli.main(["lib-add", str(CAR), "/nonexistent.json"]), dict(error=1))[1])()),
       ok("misread caught", bool(S.problems(dict(suspension=dict(anti_roll_bar=[14, 6])))))]
said = []; c = Collector(st, log=lambda m: None); co = Copilot(lambda text, ttl, kind: said.append((kind, text)), log=lambda m: None); c.listeners.append(co)
wall = 1000.0
for pkt in sim.packets([{}, {}, {}], car=CAR):
    row, meta = parse(decrypt(pkt)); wall += 1 / 60; c.feed(row, meta, wall)
se = st.q("SELECT * FROM sessions")[0]
res += [ok("session linked by gearbox", se["library_id"] == a["id"]),
        ok("copilot names the tune", ("tune", "You are on the Test grip tune by Tester A.") in said),
        ok("results from laps", L.results(st, a["id"])[0]["laps"] == 3 and not L.results(st, b["id"]))]
mine = mk(GEARS, 4); mine["suspension"]["anti_roll_bar"] = [5, 6]
t = cli.run(st, ["tune-set", str(CAR), mine, "after", "photo"])
res.append(ok("changed sheet not linked", t["library_tune"] is None))
shown = cli.run(st, ["lib-show", str(a["id"])])
res.append(ok("diff vs own sheet", shown["differs_from_your_sheet"] == [dict(setting="suspension › anti roll bar › front", mine=5, theirs=4)]))
res.append(ok("as-published sheet linked", cli.run(st, ["tune-set", str(CAR), mk(GEARS, 4)])["library_tune"] == a["id"]))
cli.run(st, ["lib-verdict", str(a["id"]), "good", "stable"]); res.append(ok("verdict", cli.run(st, ["lib-list", str(CAR)])[1]["status"] == "proven"))
res.append(ok("debrief lists library", len(cli.run(st, ["debrief"])["library"]) == 2))
# over the network, as an agent will use it
import gt7copilot.store as ZS; ZS.ROOT = tmp
serve(18766, Hub(), lambda: dict(c.state()), lambda *x: None, lambda on: None)
def post(argv, token):
    req = urllib.request.Request("http://127.0.0.1:18766/api/cli", json.dumps(dict(argv=argv)).encode(), {"Authorization": "Bearer " + token})
    try: return json.load(urllib.request.urlopen(req, timeout=5))
    except urllib.error.HTTPError as e: return dict(http=e.code)
res += [ok("network: token needed", post(["lib-list"], "wrong") == dict(http=401)),
        ok("network: lib-list", len(post(["lib-list", str(CAR)], "t0ken")) == 2),
        ok("page data", json.load(urllib.request.urlopen("http://127.0.0.1:18766/api/library"))[0]["tunes"][0]["title"] in ("Test grip", "Test loose"))]
shutil.rmtree(tmp); print("ALL PASS" if all(res) else "FAILURES"); sys.exit(0 if all(res) else 1)
