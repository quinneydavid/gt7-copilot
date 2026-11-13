"""Read-only data for the dashboard page. Everything here is written by the collector or by the agent (gt7copilot CLI).

The page is organised around three things the driver looks for: a car, a session, a track. Each has a list call that stays
small however much has been driven (one aggregate query, no lap analysis read) and a detail call that does the heavy work
for one item only."""
import json, time
import numpy as np
from . import analysis as A, knowledge as K, library as L, sheet as S, tuneadvice as TA
from .cli import car_find, car_name, debrief, ts
from .packet import C
from .store import Store

LAPS = "l.time_ms>0"                                            # a lap that counts: it has a time


def _track_names(st):
    return {t["id"]: dict(id=t["id"], name=t["name"] or f"Track {t['id']}", named=bool(t["name"]), length=t["length"])
            for t in st.q("SELECT id, name, length FROM tracks")}


def _day(t):
    return t and time.strftime("%Y-%m-%d", time.localtime(t))


def _spec(code):
    sp = K.spec(code) or {}
    return dict(drivetrain=sp.get("drivetrain"), car_class=sp.get("car_class") or None, pp_stock=sp.get("pp_stock"),
                power_hp=sp.get("power_hp"), weight_kg=sp.get("weight_kg"), maker=sp.get("maker"), aspiration=sp.get("aspiration") or None)


def _bests(st):
    """{(car, track): fastest time} over every lap, flying laps preferred (the same rule as Store.best_lap)."""
    out = {}
    for r in st.q("SELECT car, track_id, MIN(CASE WHEN first=0 THEN time_ms END) a, MIN(time_ms) b FROM laps WHERE time_ms>0 AND track_id IS NOT NULL GROUP BY car, track_id"):
        out[(r["car"], r["track_id"])] = r["a"] or r["b"]
    return out


# ---- sessions -----------------------------------------------------------------------------------------------------------
def sessions(limit=300, car=None, track=None):
    """Sessions with at least one timed lap, newest first, optionally for one car and/or one track."""
    st = Store(); tracks = _track_names(st); bests = _bests(st)
    where, args = [], []
    if car is not None:
        where.append("s.car=?"); args.append(int(car))
    if track is not None:
        where.append("s.track_id=?"); args.append(int(track))
    rows = st.q(f"""SELECT s.id, s.started, s.car, s.track_id, s.total_laps, s.library_id, COUNT(l.id) n, SUM(l.time_ms) ms,
                           MIN(CASE WHEN l.first=0 THEN l.time_ms END) a, MIN(l.time_ms) b
                    FROM sessions s JOIN laps l ON l.session_id=s.id AND {LAPS}
                    {'WHERE ' + ' AND '.join(where) if where else ''} GROUP BY s.id ORDER BY s.id DESC LIMIT ?""", *args, int(limit))
    out = []
    for s in rows:
        t = tracks.get(s["track_id"]); best = s["a"] or s["b"]
        out.append(dict(id=s["id"], started=ts(s["started"]), day=_day(s["started"]), car=car_name(s["car"]), car_code=s["car"], laps=s["n"],
                        track=t and (t["name"] if t["named"] else f"{t['name']} ({t['length'] / 1000:.2f} km)"), track_id=s["track_id"],
                        best=A.fmt_time(best), best_ms=best, minutes=round(s["ms"] / 60000),
                        km=round(s["n"] * t["length"] / 1000, 1) if t else None,
                        record=bool(t) and bests.get((s["car"], s["track_id"])) == best))
    return out


def session(sid):
    st = Store()
    d = debrief(st, sid)
    d["lap_ids"] = {l["lap_no"]: l["id"] for l in st.q("SELECT id, lap_no FROM laps WHERE session_id=?", sid)}
    se = st.q("SELECT track_id, car FROM sessions WHERE id=?", sid)[0]
    tr = st.track(se["track_id"]) if se["track_id"] else None
    if tr:
        d["map"] = _map(tr)
        best = st.best_lap(tr["id"], se["car"])
        d["reference_lap_id"] = best and best["id"]
    return d


def _map(tr, points=400):
    ref = tr["ref"]; step = max(1, len(ref) // points)
    return dict(points=np.round(ref[::step][:, [0, 2]], 1).tolist(), step_m=A.STEP * step,
                corners=[dict(n=c["n"], x=round(float(ref[int(c["apex"] / A.STEP)][0]), 1),
                              z=round(float(ref[int(c["apex"] / A.STEP)][2]), 1), start=c["start"], end=c["end"], apex=c["apex"])
                         for c in tr["corners"]])


def trace(lap_id, bin_m=6.0):
    """Speed / throttle / brake / elapsed time by distance along the track, for charts."""
    st = Store()
    lap = st.q("SELECT * FROM laps WHERE id=?", lap_id)
    if not lap or not lap[0]["track_id"]:
        return dict(error="lap or track not found")
    tr = st.track(lap[0]["track_id"]); fr = st.load_frames(lap_id)
    s = np.maximum.accumulate(A.project(fr, tr["ref"])); t = A.lap_time_axis(fr)
    grid = np.arange(0, tr["length"], bin_m)
    f = lambda col, k=1.0: np.round(np.interp(grid, s, fr[:, C[col]] * k), 2).tolist()
    return dict(lap_id=lap_id, lap=lap[0]["lap_no"], time=A.fmt_time(lap[0]["time_ms"]), dist=grid.tolist(), speed=f("speed", 3.6),
                thr=f("thr", 100), brk=f("brk", 100), gear=np.round(np.interp(grid, s, fr[:, C["gear"]])).tolist(),
                t=np.round(np.interp(grid, s, t), 3).tolist())


# ---- cars ---------------------------------------------------------------------------------------------------------------
def _car_rows(st):
    """One row per car that has been driven or has something on file: totals from the laps, nothing heavy."""
    rows = {r["car"]: r for r in st.q(f"""SELECT l.car, COUNT(*) laps, SUM(l.time_ms) ms, COUNT(DISTINCT l.session_id) sessions,
                                                 COUNT(DISTINCT l.track_id) tracks, MIN(l.started) first, MAX(l.started) last,
                                                 SUM(IFNULL(t.length, 0)) m
                                          FROM laps l LEFT JOIN tracks t ON t.id=l.track_id WHERE {LAPS} GROUP BY l.car""")}
    sheets = {r["car"]: r["n"] for r in st.q("SELECT car, COUNT(*) n FROM tunes GROUP BY car")}
    lib = {r["car"]: r["n"] for r in st.q("SELECT car, COUNT(*) n FROM library GROUP BY car")}
    out = []
    for code in sorted(set(rows) | set(sheets) | set(lib)):
        r = rows.get(code) or {}
        out.append(dict(code=code, name=car_name(code), laps=r.get("laps", 0), sessions=r.get("sessions", 0), tracks=r.get("tracks", 0),
                        minutes=round((r.get("ms") or 0) / 60000), km=round((r.get("m") or 0) / 1000, 1),
                        first_driven=ts(r.get("first")), last_driven=ts(r.get("last")), last=r.get("last") or 0,
                        sheet_on_file=code in sheets, library_tunes=lib.get(code, 0), **_spec(code)))
    return out


def cars(q=""):
    """The driver's cars (driven, or with a sheet or a tune on file), most recently driven first. With a search text: every
    car in the game whose name has those words, the driver's own first."""
    st = Store(); mine = _car_rows(st)
    q = (q or "").strip()
    if not q:
        return dict(query="", cars=sorted(mine, key=lambda c: (-c["last"], c["name"])), total_in_game=len(K._specs()))
    by_code = {c["code"]: c for c in mine}
    found = []
    for f in car_find(q)[:60]:
        found.append(by_code.get(f["code"]) or dict(code=f["code"], name=car_name(f["code"]), laps=0, sessions=0, tracks=0, minutes=0, km=0,
                                                    first_driven=None, last_driven=None, last=0, sheet_on_file=False, library_tunes=0,
                                                    **_spec(f["code"])))
    found.sort(key=lambda c: (-c["laps"], -c["library_tunes"], c["name"]))
    return dict(query=q, cars=found, total_in_game=len(K._specs()))


def suggested(st, car, sid=None):
    """The suggested tune for a car: its sheet on file with the changes the laps ask for. Worked out from one session (the
    latest with enough timed laps, or the one asked for), because problems belong to a track and a day."""
    tracks = _track_names(st)
    cands = st.q(f"""SELECT s.id, s.started, s.track_id, s.tune_id, COUNT(l.id) n FROM sessions s
                     JOIN laps l ON l.session_id=s.id AND {LAPS} AND l.first=0 AND l.analysis IS NOT NULL
                     WHERE s.car=? GROUP BY s.id HAVING n>=? ORDER BY s.id DESC LIMIT 20""", car, TA.MIN_LAPS)
    choices = [dict(session=c["id"], started=ts(c["started"]), track=(tracks.get(c["track_id"]) or {}).get("name") or "unknown track", laps=c["n"])
               for c in cands]
    if not cands:
        return dict(advice=None, choices=[], note=f"Drive {TA.MIN_LAPS} timed laps in one session in this car. The suggested tune is worked out from how the car behaves.")
    pick = next((c for c in cands if c["id"] == sid), cands[0])
    adv = debrief(st, pick["id"]).get("tune_advice")
    mine = L.current_tune(st, car)
    return dict(advice=adv, choices=choices, based_on=next(c for c in choices if c["session"] == pick["id"]),
                sheet_newer=bool(mine and pick["tune_id"] != mine["id"] and mine["created"] > pick["started"]))


def car(code, sid=None):
    """Everything about one car on one page: figures, where it was driven, what is on it, what to change, tunes on file."""
    st = Store(); code = int(code); tracks = _track_names(st)
    row = next((c for c in _car_rows(st) if c["code"] == code), None) or dict(code=code, name=car_name(code), laps=0, sessions=0, tracks=0,
                                                                              minutes=0, km=0, first_driven=None, last_driven=None, **_spec(code))
    row.pop("last", None)
    bests = []
    for b in st.q(f"""SELECT l.track_id, MIN(CASE WHEN l.first=0 THEN l.time_ms END) a, MIN(l.time_ms) b, COUNT(*) n,
                             COUNT(DISTINCT l.session_id) s, MAX(l.started) last FROM laps l
                      WHERE l.car=? AND {LAPS} AND l.track_id IS NOT NULL GROUP BY l.track_id ORDER BY last DESC""", code):
        ms = b["a"] or b["b"]
        when = st.q("SELECT session_id, started FROM laps WHERE car=? AND track_id=? AND time_ms=? ORDER BY id LIMIT 1", code, b["track_id"], ms)
        bests.append(dict(track_id=b["track_id"], track=(tracks.get(b["track_id"]) or {}).get("name", "-"), best=A.fmt_time(ms), best_ms=ms,
                          laps=b["n"], sessions=b["s"], set_on=_day(when[0]["started"]) if when else None, session=when[0]["session_id"] if when else None))
    tunes = st.q("SELECT * FROM tunes WHERE car=? ORDER BY id DESC LIMIT 30", code)
    for t in tunes:
        t["sheet"] = json.loads(t["sheet"])
    mine = tunes[0] if tunes else None
    lib_rows = L.rows(st, code); by_id = {r["id"]: r for r in lib_rows}
    history = []
    for cur, prev in zip(tunes, tunes[1:] + [None]):
        ch = S.diff(cur["sheet"], prev["sheet"]) if prev else None
        history.append(dict(id=cur["id"], saved=ts(cur["created"]), note=cur["note"], source=cur["source"],
                            library_tune=(by_id.get(cur["library_id"]) or {}).get("title"),
                            changes=ch and [dict(setting=c["setting"], before=c["theirs"], after=c["mine"]) for c in ch]))
    meta = st.q("SELECT meta FROM sessions WHERE car=? ORDER BY id DESC LIMIT 1", code)
    library = []
    for r in lib_rows:
        v = L.view(st, r, mine); v["sheet_view"] = S.view(r["sheet"]); v.pop("sheet", None)
        library.append(v)
    rank = ["proven", "driven", "untested", "did not suit"]
    library.sort(key=lambda t: (not t.get("on_car"), rank.index(t["status"])))
    try:
        experiments = K.experiments(st, code, TA.advise)["changes"]
    except Exception:
        experiments = []
    try:
        shots = st.q("SELECT COUNT(*) n FROM shots WHERE car=?", code)[0]["n"]
    except Exception:
        shots = 0
    return dict(row, picture=_cover(st, code), spec=K.spec(code, tyres=True), bests=bests, sessions=sessions(limit=200, car=code),
                sheet=mine and dict(saved=ts(mine["created"]), note=mine["note"], source=mine["source"], view=S.view(mine["sheet"]),
                                    check=S.problems(mine["sheet"]), library_tune=(by_id.get(mine["library_id"]) or {}).get("title"),
                                    pp=mine["sheet"].get("pp"), power_hp=mine["sheet"].get("power_hp"), weight_kg=mine["sheet"].get("weight_kg")),
                history=history, suggested=suggested(st, code, sid), library=library, experiments=experiments, screenshots=shots,
                telemetry=json.loads(meta[0]["meta"] or "{}") if meta else {})


# ---- tracks -------------------------------------------------------------------------------------------------------------
def tracks():
    st = Store(); out = []
    for t in st.tracks():
        agg = st.q(f"SELECT COUNT(*) n, COUNT(DISTINCT l.session_id) s, MAX(l.started) last, SUM(l.time_ms) ms FROM laps l WHERE l.track_id=? AND {LAPS}", t["id"])[0]
        per = st.q(f"""SELECT l.car, MIN(CASE WHEN l.first=0 THEN l.time_ms END) a, MIN(l.time_ms) b, COUNT(*) n, MAX(l.started) last
                       FROM laps l WHERE l.track_id=? AND {LAPS} GROUP BY l.car""", t["id"])
        cars_ = sorted([dict(code=p["car"], name=car_name(p["car"]), best_ms=p["a"] or p["b"], best=A.fmt_time(p["a"] or p["b"]), laps=p["n"],
                             last_driven=_day(p["last"])) for p in per], key=lambda c: c["best_ms"])
        out.append(dict(id=t["id"], name=t["name"] or f"Track {t['id']}", named=bool(t["name"]), length_m=round(t["length"]), corners=len(t["corners"]),
                        laps=agg["n"], sessions=agg["s"], minutes=round((agg["ms"] or 0) / 60000), last_driven=ts(agg["last"]), last=agg["last"] or 0,
                        km=round(agg["n"] * t["length"] / 1000, 1), cars=cars_, map=_map(t, 220)))
    return sorted(out, key=lambda t: -t["last"])


def track(tid):
    """One track: the outline with its corners, every car driven here ranked by its best lap, the car and tune that were
    fastest, where the time goes in that car, and every session here."""
    st = Store(); tid = int(tid); tr = st.track(tid)
    if not tr:
        return dict(error="no such track")
    base = next(t for t in tracks() if t["id"] == tid)
    lib = {r["id"]: r for r in st.q("SELECT id, title, author FROM library")}
    board = []
    for c in base["cars"]:
        w = st.q("""SELECT l.session_id, l.started, s.tune_id, s.library_id FROM laps l JOIN sessions s ON s.id=l.session_id
                    WHERE l.car=? AND l.track_id=? AND l.time_ms=? ORDER BY l.id LIMIT 1""", c["code"], tid, c["best_ms"])
        w = w[0] if w else {}
        tune = None
        if w.get("library_id") in lib:
            tune = dict(kind="library", title=lib[w["library_id"]]["title"], author=lib[w["library_id"]]["author"])
        elif w.get("tune_id"):
            t = st.q("SELECT created, note FROM tunes WHERE id=?", w["tune_id"])
            tune = t and dict(kind="sheet", title="Your settings sheet", saved=ts(t[0]["created"]))
        board.append(dict(c, session=w.get("session_id"), set_on=_day(w.get("started")), tune=tune or None, **_spec(c["code"])))
    for i, c in enumerate(board):
        c["gap_s"] = round((c["best_ms"] - board[0]["best_ms"]) / 1000, 3) if i else 0
    rec = None
    if board:
        top = board[0]; sg = suggested_here(st, top["code"], tid); adv = (sg or {}).get("advice") or {}
        rec = dict(car_code=top["code"], car=top["name"], best=top["best"], set_on=top["set_on"], tune=top["tune"], cars_compared=len(board),
                   sheet_on_file=bool(L.current_tune(st, top["code"])), based_on=(sg or {}).get("based_on"), ready=bool(adv.get("ready")),
                   changes=[dict(setting=r["game_setting"], now=r["now"], to=r["to"], reason=r.get("reason")) for r in (adv.get("recommended") or [])],
                   problems=[i["problem"] for i in adv.get("items", [])], corners=(sg or {}).get("corners") or [], ideal_lap=(sg or {}).get("ideal_lap"))
    events = []
    try:
        for e in st.q("SELECT seen, data FROM events WHERE track_id=? ORDER BY id DESC LIMIT 5", tid):
            events.append(dict(seen=ts(e["seen"]), **{k: v for k, v in json.loads(e["data"] or "{}").items() if k in ("name", "laps", "cars", "fuel_rate", "tyre_wear_rate", "track")}))
    except Exception:
        pass
    return dict(base, map=_map(tr), cars=board, recommended=rec, sessions=sessions(limit=200, track=tid), events=events)


def suggested_here(st, car, tid):
    """The latest session of this car on this track with enough laps: its tune advice and where the time went."""
    r = st.q(f"""SELECT s.id FROM sessions s JOIN laps l ON l.session_id=s.id AND {LAPS} AND l.first=0 AND l.analysis IS NOT NULL
                 WHERE s.car=? AND s.track_id=? GROUP BY s.id HAVING COUNT(l.id)>=? ORDER BY s.id DESC LIMIT 1""", car, tid, TA.MIN_LAPS)
    if not r:
        return None
    d = debrief(st, r[0]["id"])
    return dict(advice=d.get("tune_advice"), corners=d.get("corners"), ideal_lap=d.get("ideal_lap"),
                based_on=dict(session=r[0]["id"], started=d["started"], laps=(d.get("consistency") or {}).get("laps")))


# ---- home ---------------------------------------------------------------------------------------------------------------
def overview():
    """The first page: how much has been driven, in what, where, and what to do next."""
    st = Store(); tracks_ = _track_names(st)
    cars_ = [c for c in _car_rows(st) if c["laps"]]
    tot = st.q(f"""SELECT COUNT(*) laps, SUM(l.time_ms) ms, COUNT(DISTINCT l.session_id) sessions, COUNT(DISTINCT l.track_id) tracks,
                          SUM(IFNULL(t.length, 0)) m, MIN(l.started) first FROM laps l LEFT JOIN tracks t ON t.id=l.track_id WHERE {LAPS}""")[0]
    per_track = st.q(f"SELECT l.track_id, COUNT(*) n, SUM(l.time_ms) ms FROM laps l WHERE {LAPS} AND l.track_id IS NOT NULL GROUP BY l.track_id ORDER BY n DESC LIMIT 6")
    records = []
    for (code, tid), ms in _bests(st).items():
        w = st.q("SELECT session_id, started FROM laps WHERE car=? AND track_id=? AND time_ms=? ORDER BY id LIMIT 1", code, tid, ms)
        records.append(dict(car=car_name(code), car_code=code, track=(tracks_.get(tid) or {}).get("name", "-"), track_id=tid, best=A.fmt_time(ms),
                            set_on=_day(w[0]["started"]) if w else None, at=w[0]["started"] if w else 0, session=w[0]["session_id"] if w else None))
    records.sort(key=lambda r: -r["at"])
    days = st.q(f"SELECT date(l.started, 'unixepoch', 'localtime') day, COUNT(*) laps, SUM(l.time_ms) ms FROM laps l WHERE {LAPS} GROUP BY day ORDER BY day DESC LIMIT 30")
    nxt = None
    if cars_:
        last = max(cars_, key=lambda c: c["last"])
        sg = suggested(st, last["code"]); adv = sg.get("advice") or {}
        nxt = dict(car_code=last["code"], car=last["name"], ready=bool(adv.get("ready")), based_on=sg.get("based_on"), note=sg.get("note"),
                   sheet_on_file=last["sheet_on_file"],
                   changes=[dict(setting=r["game_setting"], now=r["now"], to=r["to"], reason=r.get("reason")) for r in (adv.get("recommended") or [])],
                   problems=[i["problem"] for i in adv.get("items", [])])
    for c in cars_:
        c.pop("last", None)
    return dict(totals=dict(laps=tot["laps"], sessions=tot["sessions"], tracks=tot["tracks"], cars=len(cars_), minutes=round((tot["ms"] or 0) / 60000),
                            km=round((tot["m"] or 0) / 1000, 1), since=_day(tot["first"])),
                cars=sorted(cars_, key=lambda c: -c["laps"])[:8],
                tracks=[dict(id=p["track_id"], name=(tracks_.get(p["track_id"]) or {}).get("name", "-"), laps=p["n"], minutes=round(p["ms"] / 60000),
                             km=round(p["n"] * (tracks_.get(p["track_id"]) or {}).get("length", 0) / 1000, 1)) for p in per_track],
                recent=sessions(limit=6), records=records[:10], days=list(reversed(days)), next=nxt)


# ---- screenshots --------------------------------------------------------------------------------------------------------
SHOT_KINDS = dict(car_settings_1="Car settings, page 1", car_settings_2="Car settings, page 2", event="Event", other="Other")
SHOT_GROUPS = dict(settings=("car_settings_1", "car_settings_2"), event=("event",), other=("other",))


def shots(car=None, group=None, limit=60, offset=0):
    """Every picture that was read, newest first: what it showed, which car, how it came in, what was done with it."""
    st = Store(); where, args = [], []
    if car is not None:
        where.append("car=?"); args.append(int(car))
    if group == "failed":
        where.append("IFNULL(ok,0)=0")
    elif group in SHOT_GROUPS:
        where.append(f"IFNULL(kind,'other') IN ({','.join('?' * len(SHOT_GROUPS[group]))})"); args += SHOT_GROUPS[group]
    w = "WHERE " + " AND ".join(where) if where else ""
    rows = st.q(f"SELECT * FROM shots {w} ORDER BY id DESC LIMIT ? OFFSET ?", *args, int(limit), int(offset))
    counts = {r["k"]: r["n"] for r in st.q("SELECT IFNULL(kind,'other') k, COUNT(*) n FROM shots GROUP BY k")}
    return dict(total=st.q(f"SELECT COUNT(*) n FROM shots {w}", *args)[0]["n"], all=sum(counts.values()),
                counts=dict({g: sum(counts.get(k, 0) for k in ks) for g, ks in SHOT_GROUPS.items()},
                            failed=st.q("SELECT COUNT(*) n FROM shots WHERE IFNULL(ok,0)=0")[0]["n"]),
                shots=[dict(id=r["id"], at=r["at"], when=ts(r["at"]), kind=r["kind"] or "other", kind_label=SHOT_KINDS.get(r["kind"], "Other"),
                            car_code=r["car"], car=r["car"] and car_name(r["car"]), summary=r["summary"], route=r["route"], ok=bool(r["ok"]),
                            reply=r["reply"], cover=bool(r["cover"]), url=f"/shots/{r['id']}", bytes=r["bytes"]) for r in rows])


def shot_file(shot_id):
    """-> (path, mime) of a kept picture, or None."""
    st = Store(); r = st.q("SELECT mime FROM shots WHERE id=?", int(shot_id))
    return (st.shot_path(int(shot_id), r[0]["mime"]), r[0]["mime"] or "image/jpeg") if r else None


def shot_set(shot_id, car=None, cover=None):
    """Say which car a picture shows, and/or make it that car's picture on the Cars pages."""
    st = Store(); r = st.q("SELECT car FROM shots WHERE id=?", int(shot_id))
    if not r:
        raise ValueError("No such screenshot.")
    if car is not None:
        st.x("UPDATE shots SET car=? WHERE id=?", int(car) or None, int(shot_id))
    code = int(car) if car else r[0]["car"]
    if cover is not None:
        if cover and not code:
            raise ValueError("Say which car the picture shows first.")
        if cover:
            st.x("UPDATE shots SET cover=NULL WHERE car=?", code)
        st.x("UPDATE shots SET cover=? WHERE id=?", 1 if cover else None, int(shot_id))
    return dict(ok=True)


def _cover(st, code):
    r = st.q("SELECT id FROM shots WHERE car=? AND cover=1 ORDER BY id DESC LIMIT 1", code)
    return f"/shots/{r[0]['id']}" if r else None


# ---- kept for older pages and agents ---------------------------------------------------------------------------------------
def garage():
    st = Store(); out = []
    tracks = {t["id"]: t for t in st.tracks()}
    for c in st.q("SELECT car, COUNT(*) n, MAX(started) last FROM sessions GROUP BY car ORDER BY last DESC"):
        nlaps = st.q("SELECT COUNT(*) n FROM laps WHERE car=? AND time_ms>0", c["car"])[0]["n"]
        if not nlaps:
            continue
        meta = st.q("SELECT meta FROM sessions WHERE car=? ORDER BY id DESC LIMIT 1", c["car"])[0]["meta"]
        bests = [dict(track=(tracks[b["track_id"]]["name"] or f"Track {b['track_id']}") if b["track_id"] in tracks else "-",
                      best=A.fmt_time(b["ms"]), laps=b["n"])
                 for b in st.q("SELECT track_id, MIN(time_ms) ms, COUNT(*) n FROM laps WHERE car=? AND time_ms>0 AND track_id IS NOT NULL GROUP BY track_id", c["car"])]
        tunes = [dict(saved=ts(t["created"]), note=t["note"], source=t["source"], sheet=json.loads(t["sheet"]))
                 for t in st.q("SELECT * FROM tunes WHERE car=? ORDER BY id DESC LIMIT 8", c["car"])]
        out.append(dict(code=c["car"], name=car_name(c["car"]), sessions=c["n"], laps=nlaps, last_driven=ts(c["last"]),
                        telemetry=json.loads(meta or "{}"), bests=bests, tunes=tunes))
    return out


def library():
    """Library tunes grouped by car, each compared with the sheet on file for that car."""
    st = Store(); cars = {}
    for r in L.rows(st):
        c = cars.setdefault(r["car"], dict(code=r["car"], name=car_name(r["car"]), mine=L.current_tune(st, r["car"]), tunes=[]))
        c["tunes"].append(L.view(st, r, c["mine"]))
    driven = [x["car"] for x in st.q("SELECT car, MAX(started) m FROM sessions GROUP BY car ORDER BY m DESC")]
    out = sorted(cars.values(), key=lambda c: (driven.index(c["code"]) if c["code"] in driven else 999, c["name"]))
    rank = ["proven", "driven", "untested", "did not suit"]
    for c in out:
        c["sheet_on_file"] = bool(c.pop("mine"))
        c["tunes"].sort(key=lambda t: (not t.get("on_car"), rank.index(t["status"])))
    return out
