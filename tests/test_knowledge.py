"""Known datapoints: car specs, filtering by layout, filing rules, and experiments (a settings change + what the laps did)."""
import json, os, sys, tempfile, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [ROOT, os.path.join(ROOT, "tests")]
from gt7copilot import cli, knowledge as K, sheet as S
from gt7copilot.store import Store

ok = lambda name, cond: print(("PASS " if cond else "FAIL ") + name) or cond
st = Store(tempfile.mkdtemp())
CIVIC, RSR, S180 = 204, 3311, 24
res = [ok("specs: layout, weight, PP", (K.spec(S180)["drivetrain"], K.spec(S180)["weight_kg"], K.spec(S180)["pp_stock"]) == ("FR", 1220.0, 462.57)),
       ok("specs: PP per tyre", K.spec(S180, tyres=True)["pp_stock_by_tyre"]["SH"] > 300),
       ok("car command carries specs", cli.run(st, ["car", str(CIVIC)])["drivetrain"] == "FF"),
       ok("every shipped row passes its own rules", all(not K.check(r) for r in K.rows())),
       ok("every shipped row has a source link", all(r["source"].get("url") for r in K.rows()))]
ff = cli.run(st, ["know", "--car", str(CIVIC), "--kind", "baseline", "--setting", "natural_frequency"])
mr = cli.run(st, ["know", "--car", str(RSR), "--kind", "baseline", "--setting", "natural_frequency"])
rear = lambda d: [r["value"] for r in d["rows"] if r.get("end") == "rear"]
res += [ok("layout picks the baseline (FF rear 50-60%)", ff["layout"] == "FF" and rear(ff) == ["50-60%"]),
        ok("layout picks the baseline (MR rear min)", mr["layout"] == "MR" and rear(mr) == ["min"]),
        ok("a row about this very car comes first", cli.run(st, ["know", "--car", str(CIVIC)])["rows"][0].get("car") == CIVIC),
        ok("fixes by symptom", {r["setting"] for r in cli.run(st, ["know", "--symptom", "entry_oversteer"])["rows"]} >=
           {"differential.braking_sensitivity", "suspension.anti_roll_bar", "suspension.damping_compression_pct"}),
        ok("MR-only fix hidden from FF", not any(r["id"] == "k010" for r in cli.run(st, ["know", "--car", str(CIVIC), "--symptom", "entry_oversteer"])["rows"])),
        ok("unknown option refused", cli.main(["know", "--colour", "red"]) == 1)]
bad = cli.run(st, ["know-add", dict(kind="fix", setting="suspension.wings", text="x")])
good = cli.run(st, ["know-add", dict(kind="fix", setting="suspension.toe_deg", end="rear", symptom="exit_oversteer", direction="raise",
                                     text="Rear toe-in to 0.30 calmed the car on exit.", source=dict(title="Own laps", author="driver"))])
res += [ok("no source / bad setting refused", "error" in bad and len(bad["problems"]) >= 3),
        ok("added datapoint is found", good.get("id") == "u1" and any(r["id"] == "u1" for r in cli.run(st, ["know", "--symptom", "exit_oversteer"])["rows"])),
        ok("shipped rows cannot be removed", "error" in cli.run(st, ["know-rm", "k001"])),
        ok("added row removed", cli.run(st, ["know-rm", "u1"]).get("ok") and not any(r["id"] == "u1" for r in K.rows(st)))]

# experiments: two sheets, one setting apart, laps on the same track before and after
mk = lambda arb: dict(suspension=dict(anti_roll_bar=[arb, 5], toe_deg=[0.0, 0.2], ride_height_mm=[85, 85]), brake_balance=0)
tr = st.x("INSERT INTO tracks(name,length,ref,corners,created) VALUES('Test Ring',3000,'[]','[]',0)")
def drive(tune, times):
    se = st.x("INSERT INTO sessions(started,car,total_laps,meta) VALUES(?,?,0,'{}')", time.time(), CIVIC)
    st.x("UPDATE sessions SET tune_id=? WHERE id=?", tune, se)
    for n, ms in enumerate(times):
        st.x("INSERT INTO laps(session_id,lap_no,time_ms,car,track_id,first,fuel_start,fuel_end,frames) VALUES(?,?,?,?,?,0,0,0,0)", se, n + 1, ms, CIVIC, tr)
cli.run(st, ["tune-set", str(CIVIC), mk(6)]); t1 = st.q("SELECT MAX(id) i FROM tunes")[0]["i"]; drive(t1, [61000, 60500])
cli.run(st, ["tune-set", str(CIVIC), mk(4), "softer", "front", "bar"]); t2 = st.q("SELECT MAX(id) i FROM tunes")[0]["i"]; drive(t2, [60200, 60100])
ex = cli.run(st, ["experiments", str(CIVIC)])
ch = ex["changes"][0]
res += [ok("experiment: the change", ch["changed"] == [dict(setting="suspension › anti roll bar › front", before=6, after=4)] and ch["clean_test"]),
        ok("experiment: the outcome", ch["outcome"][0]["best_change_s"] == -0.4 and ch["outcome"][0]["track"] == "Test Ring")]
b = cli.run(st, ["brief", str(CIVIC)])
nf = [x for x in b["baselines_for_this_layout"] if x["setting"].startswith("suspension › anti roll") or "natural frequency" in x["setting"]]
res += [ok("brief: one answer has it all", b["car"]["drivetrain"] == "FF" and b["sheet_on_car"]["sheet"] == mk(4) and len(b["experiments"]) == 1
           and b["examples"][0]["car_name"].startswith("Honda Civic") and nf and "how_to_use" in b),
        ok("brief: sheet value next to baseline", [x["on_your_sheet"] for x in b["baselines_for_this_layout"] if x["setting"] == "suspension › ride height mm"] == [[85, 85]]),
        ok("brief for a car with nothing on file", cli.run(st, ["brief", str(RSR)])["sheet_on_car"] is None),
        ok("brief is JSON", bool(json.dumps(b)))]
print("ALL PASS" if all(res) else "FAILURES"); sys.exit(0 if all(res) else 1)
