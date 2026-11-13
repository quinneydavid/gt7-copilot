#!/usr/bin/env python3
"""gt7copilot: read and file what the collector knows. Output is JSON so an agent can use it directly.
  gt7copilot status                      live state of the collector / copilot
  gt7copilot sessions [N]                last N sessions
  gt7copilot laps [SESSION]              laps of a session (default: latest)
  gt7copilot debrief [SESSION]           everything needed for a post-session debrief (includes library tunes for the car)
  gt7copilot advice [SESSION]            what the car's behaviour says to change on the settings sheet (also inside debrief)
  gt7copilot tracks | gt7copilot track-name ID "Name"
  gt7copilot car [CODE] | gt7copilot car-find "911 gt3"     car name for a code / codes for a name
  gt7copilot sheet-template              the shape every settings sheet must have
  gt7copilot tune-show [CAR]             settings sheets filed for a car (what is on it now, and before)
  gt7copilot tune-set CAR FILE.json [--lib ID] [note]   file the sheet that is on the car (--lib: it is that library tune)
  gt7copilot lib-list [CAR] | gt7copilot lib-show ID          known-good tunes on file
  gt7copilot lib-add CAR FILE.json       file a tune: {title, author, url, pp, tyres, purpose, track, game_version, published, notes, sheet}
  gt7copilot lib-verdict ID good|bad|clear [note]       the driver's verdict after driving it
  gt7copilot lib-rm ID
  gt7copilot brief [CAR]                 ONE call before advising on a car: specs, sheet on it, baselines for its layout, library tunes,
                                   what earlier changes did, latest advice from the laps
  gt7copilot know [--car CODE] [--drivetrain FR] [--setting toe] [--symptom KEY] [--kind baseline|fix|effect|example]
                                   known tuning datapoints, each with its source (--car picks the rows for that car's layout)
  gt7copilot know-add FILE.json          file a datapoint: {kind, setting, end, drivetrain, symptom, direction, value, text, tradeoff, scope, source{title,url}}
  gt7copilot know-rm ID                  remove an added datapoint
  gt7copilot experiments [CAR]           the driver's own changes on a car and what the laps did afterwards
  gt7copilot features              which optional parts are on and usable (voice control, screenshots and their routes, phone, earpiece, agent door)
  gt7copilot shot                  fetch the newest PS5 capture through the virtual phone, read it and file it (about half a minute)
  gt7copilot shots-new [back]      read every PS5 capture not read before and file what they show (one sheet per car, events);
                                   back = look through the whole list, not only the ones since the last read. Runs in the background:
  gt7copilot shots-job             how far that is, and its result when done
  gt7copilot shot-file IMAGE       read a picture of a settings or event screen (JPEG, PNG, WebP) and file it
  gt7copilot ask "what should I change next?"   the page's chat: answered by the model from the driver's laps and settings
  gt7copilot say "text"                  speak through the copilot page
  gt7copilot hear "copilot, fuel"           what a spoken command would do and answer (voice control, typed)
Set GT7C_URL (and GT7C_TOKEN) to run against the collector over the network instead of a local database.
The token is the agent token from the Settings tab; the agent door must be switched on there."""
import base64, csv, json, os, re, statistics, sys, time, urllib.error, urllib.parse, urllib.request
from collections import Counter
from . import analysis as A, knowledge as K, library as L, settings as CFG, sheet as S, tuneadvice as TA
from .store import Store

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
URL = f"http://127.0.0.1:{os.environ.get('GT7C_PORT', '8765')}"
REMOTE = os.environ.get("GT7C_URL", "").rstrip("/")
FILE_ARG = {"tune-set": 1, "lib-add": 1, "know-add": 0}       # commands whose argument at this position is a JSON file


def car_name(code):
    sp = K.spec(code)
    if sp:
        return sp["name"]
    try:
        makers = {r["ID"]: r["Name"] for r in csv.DictReader(open(os.path.join(BASE, "data/maker.csv"), encoding="utf-8"))}
        for r in csv.DictReader(open(os.path.join(BASE, "data/cars.csv"), encoding="utf-8")):
            if r["ID"] == str(code):
                return f"{makers.get(r['Maker'], '')} {r['ShortName']}".strip()
    except OSError:
        pass
    return f"car {code}"


def car_find(text):
    words = text.lower().split(); out = []
    makers = {r["ID"]: r["Name"] for r in csv.DictReader(open(os.path.join(BASE, "data/maker.csv"), encoding="utf-8"))}
    for r in csv.DictReader(open(os.path.join(BASE, "data/cars.csv"), encoding="utf-8")):
        name = f"{makers.get(r['Maker'], '')} {r['ShortName']}".strip()
        if all(re.search(r'(?<![a-z0-9])' + re.escape(w), name.lower()) for w in words):
            sp = K.spec(r["ID"]) or {}
            out.append(dict(code=int(r["ID"]), name=name, drivetrain=sp.get("drivetrain"), pp_stock=sp.get("pp_stock"), car_class=sp.get("car_class")))
    return out


def ts(t):
    return t and time.strftime("%Y-%m-%d %H:%M", time.localtime(t))


def debrief(st, sid):
    se = st.q("SELECT * FROM sessions WHERE id=?", sid)[0]
    laps = st.q("SELECT * FROM laps WHERE session_id=? ORDER BY lap_no", sid)
    for l in laps:
        l["analysis"] = json.loads(l["analysis"] or "null")
    tr = st.track(se["track_id"]) if se["track_id"] else None
    out = dict(session=sid, started=ts(se["started"]), car=dict(code=se["car"], name=car_name(se["car"])),
               setup_from_telemetry=json.loads(se["meta"] or "{}"),
               track=tr and dict(id=tr["id"], name=tr["name"] or f"unnamed track {tr['id']}", length_m=round(tr["length"]),
                                 corners=len(tr["corners"])),
               laps=[dict(lap=l["lap_no"], time=A.fmt_time(l["time_ms"]), ms=l["time_ms"], first_lap=bool(l["first"]),
                          fuel_used=round(l["fuel_start"] - l["fuel_end"], 2)) for l in laps])
    timed = [l for l in laps if l["time_ms"] > 0 and not l["first"]] or [l for l in laps if l["time_ms"] > 0]
    if not timed:
        return out
    best = min(timed, key=lambda l: l["time_ms"])
    times = [l["time_ms"] for l in timed]
    out["best"] = dict(lap=best["lap_no"], time=A.fmt_time(best["time_ms"]))
    out["consistency"] = dict(laps=len(times), median=A.fmt_time(int(statistics.median(times))),
                              spread_s=round((max(times) - min(times)) / 1000, 2),
                              stdev_s=round(statistics.pstdev(times) / 1000, 2) if len(times) > 1 else 0)
    alltime = tr and st.best_lap(tr["id"], se["car"])
    if alltime:
        out["all_time_best"] = dict(time=A.fmt_time(alltime["time_ms"]), this_session=alltime["session_id"] == sid)
    ref = (alltime or best).get("analysis") or best["analysis"]
    if tr and ref:
        ideal = 0.0
        corners = []
        for k, c in enumerate(tr["corners"]):
            zs = [l["analysis"]["zones"][k] for l in timed if l["analysis"] and l["analysis"]["zones"][k]]
            if not zs or not ref["zones"][k]:
                continue
            ideal += min(z["time"] for z in zs)
            adv = [A.advise(z, ref["zones"][k]) for z in zs]
            causes = Counter(a["cause"] for a in adv if a)
            loss = [z["time"] - ref["zones"][k]["time"] for z in zs]
            corners.append(dict(turn=c["n"], radius_m=c["radius"], reference=ref["zones"][k],
                                avg_loss_s=round(sum(loss) / len(loss), 3), worst_loss_s=round(max(loss), 3),
                                laps_losing=sum(1 for a in adv if a), main_causes=dict(causes),
                                wheelspin_s=round(sum(z.get("spin_r", 0) + z.get("spin_f", 0) for z in zs) / len(zs), 2),
                                lockup_s=round(sum(z.get("lock_f", 0) + z.get("lock_r", 0) for z in zs) / len(zs), 2)))
        out["corners"] = sorted(corners, key=lambda c: -c["avg_loss_s"])
        out["ideal_lap"] = A.fmt_time(int(ideal * 1000))
    sums = [l["analysis"]["summary"] for l in timed if l["analysis"]]
    if sums:
        avg = lambda key: round(sum(s[key] for s in sums) / len(sums), 2)
        out["car_behaviour"] = dict(
            per_lap_avg={k: avg(k) for k in ("spin_f_s", "spin_r_s", "lock_f_s", "lock_r_s", "limiter_s", "tcs_s", "asm_s",
                                             "fuel_used", "full_throttle_pct", "braking_pct", "coasting_pct",
                                             "tyre_front_minus_rear", "max_speed")},
            tyre_avg_first_lap=sums[0]["tyre_avg"], tyre_avg_last_lap=sums[-1]["tyre_avg"], tyre_max=sums[-1]["tyre_max"],
            susp_min=sums[-1]["susp_min"], susp_max=sums[-1]["susp_max"], upshift_rpm_avg=sums[-1].get("upshift_rpm_avg"))
        out["pace_trend_s"] = [round((l["time_ms"] - best["time_ms"]) / 1000, 2) for l in timed]
    mine0 = L.current_tune(st, se["car"])
    out["tune_advice"] = advice_for(st, se["car"], [l["analysis"]["summary"] for l in timed if l["analysis"]], mine0 and mine0["sheet"],
                                    json.loads(se["meta"] or "{}"))
    tune = st.q("SELECT * FROM tunes WHERE car=? ORDER BY id DESC LIMIT 1", se["car"])
    out["tune_on_file"] = tune and dict(saved=ts(tune[0]["created"]), note=tune[0]["note"], sheet=json.loads(tune[0]["sheet"]))
    mine = L.current_tune(st, se["car"])
    out["library_tune_this_session"] = se.get("library_id")
    out["library"] = [dict(L.view(st, r, mine), sheet=None) for r in L.rows(st, se["car"])]      # gt7copilot lib-show ID for a full sheet
    return out


def advice_for(st, car, sums, sh, meta):
    """Tune advice with the car's layout taken into account and the known datapoints for each problem attached."""
    sp = K.spec(car) or {}
    adv = TA.advise(sums, sh, dict(meta or {}, drivetrain=sp.get("drivetrain")))
    for i in adv.get("items", []):
        i["known"] = K.for_symptom(st, i["key"], car)
    if sh:                                               # the whole sheet as the game shows it, proposed changes marked
        adv["sheet_view"] = S.view(sh, adv.get("recommended") or [])
    return adv


def brief(st, car):
    """Everything on file about one car, so the agent can advise from one answer."""
    mine = L.current_tune(st, car); sh = mine and mine["sheet"]
    last = st.q("""SELECT s.id FROM sessions s WHERE s.car=? AND EXISTS(SELECT 1 FROM laps l WHERE l.session_id=s.id AND l.time_ms>0)
                   ORDER BY s.id DESC LIMIT 1""", car)
    d = debrief(st, last[0]["id"]) if last else None
    return dict(car=K.spec(car, tyres=True) or dict(code=car, name=car_name(car), note="not in the official car list: no layout or stock figures"),
                sheet_on_car=mine and dict(filed=ts(mine["created"]), note=mine["note"], library_tune=mine["library_id"], sheet=sh, check=S.problems(sh)),
                baselines_for_this_layout=K.baseline_check(st, car, sh),
                examples=[dict(K.short(r), car_name=r.get("car_name"), sheet=r.get("sheet")) for r in K.find(st, car=car, kind="example")],
                library=[dict(L.view(st, r, mine), sheet=None) for r in L.rows(st, car)],
                experiments=K.experiments(st, car, TA.advise)["changes"],
                latest_session=d and dict(session=d["session"], started=d["started"], track=d.get("track"), best=d.get("best"),
                                          tune_advice=d.get("tune_advice")),
                how_to_use="Order of trust: experiments (the driver's own laps) > library tunes with status proven > tune_advice from the driver's laps > "
                           "baselines and examples (guides, starting points only). Change one setting at a time; file the new sheet with tune-set.")


def flags(rest, names):
    """--name value pairs -> dict (unknown flags raise)."""
    out = {}
    it = iter(rest)
    for x in it:
        if not x.startswith("--") or x[2:] not in names:
            raise ValueError(f"unknown option {x}; options are " + ", ".join("--" + n for n in names))
        out[x[2:]] = next(it)
    return out


def run(st, a):
    """Run one command against a store. File arguments may be a path or the already-parsed JSON."""
    cmd, rest = a[0], a[1:]
    load = lambda x: x if isinstance(x, dict) else json.load(open(x))
    post = lambda path: urllib.request.Request(URL + path, data=b"", method="POST", headers={"X-GT7C": "1"})      # the header: server.H._own
    latest = lambda: (st.q("SELECT id FROM sessions ORDER BY id DESC LIMIT 1") or [{"id": None}])[0]["id"]
    latest_car = lambda: (st.q("SELECT car FROM sessions ORDER BY id DESC LIMIT 1") or [{"car": 0}])[0]["car"]
    if cmd == "status":
        try:
            return json.load(urllib.request.urlopen(URL + "/api/state", timeout=3))
        except OSError as e:
            return dict(error=f"collector not reachable: {e}")
    if cmd == "sessions":
        return [dict(s, started=ts(s["started"]), ended=ts(s["ended"]), car_name=car_name(s["car"]), meta=None,
                     laps=st.q("SELECT COUNT(*) n FROM laps WHERE session_id=?", s["id"])[0]["n"])
                for s in st.q("SELECT * FROM sessions ORDER BY id DESC LIMIT ?", int(rest[0]) if rest else 10)]
    if cmd == "laps":
        sid = int(rest[0]) if rest else latest()
        return [dict(lap=l["lap_no"], id=l["id"], time=A.fmt_time(l["time_ms"]), first_lap=bool(l["first"]), track=l["track_id"])
                for l in st.q("SELECT * FROM laps WHERE session_id=? ORDER BY lap_no", sid)]
    if cmd == "debrief":
        sid = int(rest[0]) if rest else latest()
        return debrief(st, sid) if sid else dict(error="no sessions recorded yet")
    if cmd == "advice":
        sid = int(rest[0]) if rest else latest()
        return debrief(st, sid).get("tune_advice", dict(ready=False, items=[], notes=["No timed laps in that session."])) if sid else dict(error="no sessions recorded yet")
    if cmd == "tracks":
        return [dict(id=t["id"], name=t["name"], length_m=round(t["length"]), corners=len(t["corners"]), created=ts(t["created"]))
                for t in st.tracks()]
    if cmd == "track-name":
        st.x("UPDATE tracks SET name=?, name_src='you' WHERE id=?", rest[1], int(rest[0]))
        return dict(ok=True)
    if cmd == "car":
        code = int(rest[0]) if rest else latest_car()
        return K.spec(code, tyres=True) or dict(code=code, name=car_name(code))
    if cmd == "car-find":
        return car_find(" ".join(rest))
    if cmd == "sheet-template":
        return dict(template=S.TEMPLATE, hardware_keys=S.HARDWARE_KEYS, rules="hardware = what is fitted, in the game's own words, one entry per key in hardware_keys (the selectors on page 1 and all of page 2; '--' = cannot be fitted). Pairs are [front, rear]. Toe: negative = out, positive = in. null = not on the sheet. "
                                               "transmission.gears = ratios from 1st up. Tyres by full name, e.g. 'Racing Hard'.")
    if cmd == "tune-set":
        car, sheet, extra = int(rest[0]), load(rest[1]), list(rest[2:])
        lib = int(extra.pop(extra.index("--lib") + 1)) if "--lib" in extra else None
        extra = [x for x in extra if x != "--lib"]
        lib = lib or L.link_for_sheet(st, car, sheet)
        st.x("INSERT INTO tunes(car,created,source,sheet,note,library_id) VALUES(?,?,?,?,?,?)", car, time.time(), "agent",
             json.dumps(sheet), " ".join(extra) or None, lib)
        return dict(ok=True, library_tune=lib, check=S.problems(sheet))
    if cmd == "tune-show":
        code = int(rest[0]) if rest else latest_car()
        return [dict(saved=ts(t["created"]), note=t["note"], library_tune=t["library_id"], sheet=json.loads(t["sheet"]))
                for t in st.q("SELECT * FROM tunes WHERE car=? ORDER BY id DESC LIMIT 5", code)]
    if cmd == "lib-add":
        return L.add(st, int(rest[0]), load(rest[1]))
    if cmd == "lib-list":
        car = int(rest[0]) if rest else None
        mine = L.current_tune(st, car) if car is not None else None
        return [dict(L.view(st, r, mine), sheet=None, car_name=car_name(r["car"])) for r in L.rows(st, car)]
    if cmd == "lib-show":
        r = [x for x in L.rows(st) if x["id"] == int(rest[0])]
        return dict(L.view(st, r[0], L.current_tune(st, r[0]["car"])), car_name=car_name(r[0]["car"])) if r else dict(error="no such tune")
    if cmd == "lib-verdict":
        if rest[1] not in ("good", "bad", "clear"):
            return dict(error="verdict is good, bad or clear")
        st.x("UPDATE library SET verdict=?, verdict_note=? WHERE id=?", None if rest[1] == "clear" else rest[1], " ".join(rest[2:]) or None, int(rest[0]))
        return dict(ok=True)
    if cmd == "lib-rm":
        st.x("DELETE FROM library WHERE id=?", int(rest[0]))
        st.x("UPDATE sessions SET library_id=NULL WHERE library_id=?", int(rest[0]))
        st.x("UPDATE tunes SET library_id=NULL WHERE library_id=?", int(rest[0]))
        return dict(ok=True)
    if cmd == "brief":
        return brief(st, int(rest[0]) if rest else latest_car())
    if cmd == "know":
        f = flags(rest, ("car", "drivetrain", "setting", "symptom", "kind", "end"))
        if "car" in f:
            f["car"] = int(f["car"])
        found = K.find(st, **f)
        return dict(count=len(found), layout=(K.spec(f["car"]) or {}).get("drivetrain") if "car" in f else f.get("drivetrain"), rows=found)
    if cmd == "know-add":
        return K.add(st, load(rest[0]))
    if cmd == "know-rm":
        return K.remove(st, rest[0])
    if cmd == "experiments":
        return K.experiments(st, int(rest[0]) if rest else latest_car(), TA.advise)
    if cmd == "features":
        CFG.reload()
        from . import inbox as INBOX
        return dict(CFG.features(), screenshot_routes={r: dict(on=INBOX.why_not(r) is None, why=INBOX.why_not(r)) for r in INBOX.ROUTES})
    if cmd in ("shot", "shot-file"):                 # done by the running collector: it knows the car on track
        image = b""
        if cmd == "shot-file":
            src = rest[0]
            image = base64.b64decode(src["image_b64"]) if isinstance(src, dict) else open(src, "rb").read()
        req = urllib.request.Request(URL + "/api/screenshot" + ("?source=phone" if cmd == "shot" else ""), data=image, method="POST",
                                     headers={"Content-Type": "application/octet-stream", "X-GT7C": "1"})
        try:
            return json.load(urllib.request.urlopen(req, timeout=200))
        except urllib.error.HTTPError as e:
            return json.loads(e.read() or b"{}") or dict(ok=False, reply=f"HTTP {e.code}")
    if cmd in ("shots-new", "shots-job"):            # every capture not read before, in the background; shots-job follows it
        back = "?back=1" if rest and rest[0] in ("back", "--back", "all") else ""
        req = urllib.request.Request(URL + ("/api/screenshots/read" + back if cmd == "shots-new" else "/api/screenshots/job"),
                                     data=b"" if cmd == "shots-new" else None, method="POST" if cmd == "shots-new" else "GET", headers={"X-GT7C": "1"})
        try:
            return json.load(urllib.request.urlopen(req, timeout=30))
        except urllib.error.HTTPError as e:
            return json.loads(e.read() or b"{}") or dict(ok=False, reply=f"HTTP {e.code}")
    if cmd == "ask":                                 # the page's chat, from the command line or an agent
        from . import ask as ASK
        return ASK.answer(" ".join(rest))
    if cmd == "hear":
        return json.load(urllib.request.urlopen(post("/api/heartext?text=" + urllib.parse.quote(" ".join(rest))), timeout=10))
    if cmd == "say":
        urllib.request.urlopen(post("/api/say?text=" + urllib.parse.quote(" ".join(rest))), timeout=5)
        return dict(ok=True)
    return None


def main(argv=None):
    a = list(argv or sys.argv[1:]) or ["status"]
    if a[0] in ("-h", "--help", "help"):
        print(__doc__); return 0
    try:
        if REMOTE:
            if a[0] in FILE_ARG and len(a) > FILE_ARG[a[0]] + 1:
                a[FILE_ARG[a[0]] + 1] = json.load(open(a[FILE_ARG[a[0]] + 1]))
            if a[0] == "shot-file" and len(a) > 1:
                a[1] = dict(image_b64=base64.b64encode(open(a[1], "rb").read()).decode())
            req = urllib.request.Request(REMOTE + "/api/cli", json.dumps(dict(argv=a)).encode(),
                                         {"Content-Type": "application/json", "Authorization": "Bearer " + os.environ.get("GT7C_TOKEN", "")})
            try:
                out = json.load(urllib.request.urlopen(req, timeout=240 if a[0] in ("shot", "shot-file") else 30))
            except urllib.error.HTTPError as e:
                out = json.loads(e.read() or b"{}") or dict(error=f"HTTP {e.code}")
        else:
            out = run(Store(), a)
    except (IndexError, ValueError, KeyError, OSError) as e:
        out = dict(error=f"{type(e).__name__}: {e}", usage="gt7copilot help")
    if out is None:
        print(__doc__); return 2
    print(json.dumps(out, indent=1, default=str))
    return 1 if isinstance(out, dict) and out.get("error") else 0


if __name__ == "__main__":
    sys.exit(main())
