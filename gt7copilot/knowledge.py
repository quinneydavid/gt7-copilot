"""Known datapoints for tuning, in one shape the agent can filter instead of reading guides.
Three stores, one view:
  data/knowledge.json   ships with the app: sourced statements from tuning guides (built by tools/build_knowledge.py)
  table datapoints      added later by the agent or the driver (same row shape, source required), kept in the database
  data/carspecs.csv     per car: drivetrain, power, weight, stock PP, class (decides which rows apply to a car)
Plus what the driver's own laps proved: experiments() pairs each settings change on a car with what the laps did next."""
import csv, functools, json, os, time
from . import sheet as S

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KINDS = ("baseline", "fix", "effect", "example")
SYMPTOMS = ("entry_oversteer", "front_lock", "understeer", "exit_oversteer", "one_wheel_spin", "exit_understeer", "gearing_short",
            "gearing_long", "rear_tyres_hot")
DRIVETRAINS = ("FF", "FR", "MR", "RR", "4WD")
SCHEMA = "CREATE TABLE IF NOT EXISTS datapoints(id INTEGER PRIMARY KEY, added REAL, row TEXT)"


@functools.lru_cache(None)
def _specs():
    out = {}
    try:
        for r in csv.DictReader(open(os.path.join(BASE, "data/carspecs.csv"), encoding="utf-8")):
            num = lambda k: float(r[k]) if r[k] else None
            out[int(r["code"])] = dict(code=int(r["code"]), name=r["name"], maker=r["maker"], drivetrain=r["drivetrain"] or None,
                                       aspiration=r["aspiration"], power_hp=num("power_hp"), torque_kgfm=num("torque_kgfm"),
                                       weight_kg=num("weight_kg"), pp_stock=num("pp_stock"), car_class=r["car_class"])
    except OSError:
        pass
    return out


@functools.lru_cache(None)
def _stockpp():
    out = {}
    try:
        for r in csv.DictReader(open(os.path.join(BASE, "data/stockpp.csv"), encoding="utf-8")):
            out.setdefault(int(r["ID"]), {})[r["Tyre"]] = float(r["PP"])
    except OSError:
        pass
    return out


def spec(code, tyres=False):
    """What is known about a car before any tuning. None for a car the official list does not have."""
    s = _specs().get(int(code))
    if s and tyres:
        s = dict(s, pp_stock_by_tyre=_stockpp().get(int(code)))      # CH..RS = comfort/sports/racing hard-medium-soft, IM, W, D
    return s


@functools.lru_cache(None)
def _seed():
    try:
        return json.load(open(os.path.join(BASE, "data/knowledge.json"), encoding="utf-8"))["rows"]
    except OSError:
        return []


def _paths():
    out = set()
    def walk(d, p=""):
        for k, v in d.items():
            out.add(p + k)
            if isinstance(v, dict):
                walk(v, p + k + ".")
    walk(S.TEMPLATE)
    return out


def check(row):
    """Reasons a new datapoint is not acceptable. Empty list = fine."""
    bad = []
    if row.get("kind") not in KINDS:
        bad.append(f"kind must be one of {', '.join(KINDS)}")
    if not (row.get("text") or "").strip():
        bad.append("text is required (the statement, one line)")
    src = row.get("source") or {}
    if not isinstance(src, dict) or not (src.get("title") and (src.get("url") or src.get("author"))):
        bad.append("source is required: {title, url} or {title, author} (who says so)")
    if row.get("setting") and row["setting"] not in _paths():
        bad.append(f"setting '{row['setting']}' is not a settings-sheet path (gt7copilot sheet-template)")
    if row.get("kind") != "example" and not row.get("setting"):
        bad.append("setting is required (except for kind example)")
    if row.get("end") not in (None, "front", "rear"):
        bad.append("end is front, rear or null")
    if row.get("symptom") not in (None,) + SYMPTOMS:
        bad.append(f"symptom must be one of {', '.join(SYMPTOMS)}")
    if row.get("direction") not in (None, "raise", "lower"):
        bad.append("direction is raise, lower or null")
    if any(d not in DRIVETRAINS for d in row.get("drivetrain") or []):
        bad.append(f"drivetrain is a list from {', '.join(DRIVETRAINS)}, or null for any")
    if row.get("kind") == "fix" and not (row.get("symptom") and row.get("direction")):
        bad.append("a fix needs a symptom and a direction")
    if row.get("sheet"):
        bad += S.problems(row["sheet"])
    return bad


def add(st, row):
    bad = check(row)
    if bad:
        return dict(error="not filed", problems=bad)
    st.db.execute(SCHEMA)
    i = st.x("INSERT INTO datapoints(added,row) VALUES(?,?)", time.time(), json.dumps({k: v for k, v in row.items() if k != "id"}))
    return dict(ok=True, id=f"u{i}")


def remove(st, rid):
    if not str(rid).startswith("u"):
        return dict(error="only added datapoints (ids starting with u) can be removed; the shipped ones are edited in tools/build_knowledge.py")
    st.db.execute(SCHEMA)
    st.x("DELETE FROM datapoints WHERE id=?", int(str(rid)[1:]))
    return dict(ok=True)


def rows(st=None):
    out = [dict(r, origin="shipped") for r in _seed()]
    if st is not None:
        st.db.execute(SCHEMA)
        out += [dict(json.loads(r["row"]), id=f"u{r['id']}", origin="added", added=time.strftime("%Y-%m-%d", time.localtime(r["added"])))
                for r in st.q("SELECT * FROM datapoints ORDER BY id")]
    return out


def find(st=None, car=None, drivetrain=None, setting=None, symptom=None, kind=None, end=None):
    """Datapoints that apply. car (a code) narrows by its drivetrain and puts rows about that very car first.
    setting matches a path or any part of it ('toe', 'differential')."""
    dt = drivetrain or ((spec(car) or {}).get("drivetrain") if car is not None else None)
    out = []
    for r in rows(st):
        if kind and r["kind"] != kind:
            continue
        if symptom and r.get("symptom") != symptom:
            continue
        if setting and setting not in (r.get("setting") or "") and not (r["kind"] == "example" and setting in json.dumps(r.get("sheet") or {})):
            continue
        if end and r.get("end") not in (None, end):
            continue
        if dt and r.get("drivetrain") and dt not in r["drivetrain"]:
            continue
        out.append(r)
    exact = lambda r: 0 if car is not None and r.get("car") == int(car) else 1
    specific = lambda r: 0 if r.get("drivetrain") else 1          # rows written for this layout before general ones
    return sorted(out, key=lambda r: (exact(r), KINDS.index(r["kind"]), specific(r)))


def short(r):
    """A datapoint as one line plus where it comes from (for lists inside other answers)."""
    return dict(id=r["id"], kind=r["kind"], text=r["text"], tradeoff=r.get("tradeoff"), scope=r.get("scope"),
                applies_to=r.get("drivetrain") or "any layout", source=(r.get("source") or {}).get("title"))


def for_symptom(st, key, car=None):
    return [short(r) for r in find(st, car=car, symptom=key, kind="fix")]


def experiments(st, car, tune_advice=None):
    """What the driver's own changes did. Each settings sheet filed for the car, oldest first, with the laps driven on it; from the
    second sheet on, what was changed and how best lap and problems moved on tracks driven before and after.
    tune_advice(summaries, sheet, meta) -> advice dict (passed in to avoid a circular import)."""
    tunes = st.q("SELECT * FROM tunes WHERE car=? ORDER BY id", car)
    tracks = {t["id"]: t["name"] or f"Track {t['id']}" for t in st.q("SELECT id, name FROM tracks")}
    steps = []
    for t in tunes:
        sh = json.loads(t["sheet"]); per = {}
        for l in st.q("""SELECT l.track_id, l.time_ms, l.analysis, s.meta FROM laps l JOIN sessions s ON s.id=l.session_id
                         WHERE s.tune_id=? AND l.time_ms>0 AND l.first=0 AND l.track_id IS NOT NULL""", t["id"]):
            p = per.setdefault(l["track_id"], dict(times=[], sums=[], meta=json.loads(l["meta"] or "{}")))
            p["times"].append(l["time_ms"])
            a = json.loads(l["analysis"] or "null")
            if a and a.get("summary"):
                p["sums"].append(a["summary"])
        res = {}
        for tid, p in per.items():
            adv = tune_advice(p["sums"], sh, p["meta"]) if tune_advice and p["sums"] else None
            res[tid] = dict(track=tracks.get(tid, "-"), laps=len(p["times"]), best_ms=min(p["times"]),
                            problems={i["key"]: i["score"] for i in (adv or {}).get("items", [])} if adv and adv.get("ready") else None)
        steps.append(dict(tune=t["id"], filed=time.strftime("%Y-%m-%d %H:%M", time.localtime(t["created"])), note=t["note"], sheet=sh, results=res))
    out = []
    for prev, cur in zip(steps, steps[1:]):
        changed = S.diff(cur["sheet"], prev["sheet"])
        outcome = []
        for tid in cur["results"]:
            if tid not in prev["results"]:
                continue
            a, b = prev["results"][tid], cur["results"][tid]
            o = dict(track=b["track"], best_before_s=a["best_ms"] / 1000, best_after_s=b["best_ms"] / 1000,
                     best_change_s=round((b["best_ms"] - a["best_ms"]) / 1000, 3), laps_before=a["laps"], laps_after=b["laps"])
            if a["problems"] is not None and b["problems"] is not None:
                keys = sorted(set(a["problems"]) | set(b["problems"]))
                o["problems"] = {k: dict(before=a["problems"].get(k, 0), after=b["problems"].get(k, 0)) for k in keys}
            outcome.append(o)
        out.append(dict(from_tune=prev["tune"], to_tune=cur["tune"], filed=cur["filed"], note=cur["note"],
                        changed=[dict(setting=c["setting"], before=c["theirs"], after=c["mine"]) for c in changed],
                        clean_test=len(changed) == 1, outcome=outcome or None))
    return dict(car=car, sheets_filed=len(steps), changes=out,
                reading="best_change_s below zero = faster after the change. clean_test = exactly one setting changed, so the outcome "
                        "can be credited to it. outcome null = no track driven both before and after.")


def baseline_check(st, car, sh):
    """Baselines that apply to this car next to what its sheet has. Positions in a range ('min', '50-60%') cannot be turned
    into numbers without the car's own range, which only the game shows, so those are listed for the agent to judge."""
    out = []
    for r in find(st, car=car, kind="baseline"):
        now = None
        if sh and r.get("setting"):
            x = sh
            for k in r["setting"].split("."):
                x = x.get(k) if isinstance(x, dict) else None
            if isinstance(x, list) and len(x) == 2 and r.get("end"):
                x = x[0 if r["end"] == "front" else 1]
            now = x if isinstance(x, (int, float, str)) or (isinstance(x, list) and x) else None
        out.append(dict(short(r), setting=S.label(r["setting"]) + (f" › {r['end']}" if r.get("end") else ""), suggested=r.get("value"),
                        on_your_sheet=now))
    return out
