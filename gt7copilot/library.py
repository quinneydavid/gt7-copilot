"""The tune library: known-good setups per car, each with where it came from and how it went when it was driven.
Entries are filed by the agent (gt7copilot lib-add); the collector links sessions to the tune that was on the car."""
import json, time
from . import analysis as A, sheet as S

FIELDS = ("title", "author", "url", "pp", "tyres", "purpose", "track", "game_version", "published", "notes")


def add(st, car, entry):
    """entry: dict with FIELDS + 'sheet'. A second add with the same car + url + title replaces the first."""
    sh = entry.get("sheet") or {}
    if not entry.get("title") or not sh:
        raise ValueError("a library tune needs at least a title and a sheet")
    if not entry.get("url") and not entry.get("author"):
        raise ValueError("say where the tune came from: url or author")
    row = {k: entry.get(k) for k in FIELDS}
    row["pp"] = row["pp"] if row["pp"] is not None else sh.get("pp")
    t = sh.get("tyres") or {}
    row["tyres"] = row["tyres"] or " / ".join(dict.fromkeys(x for x in (t.get("front"), t.get("rear")) if x)) or None
    old = st.q("SELECT id FROM library WHERE car=? AND title=? AND IFNULL(url,'')=?", car, row["title"], row["url"] or "")
    if old:
        st.x(f"UPDATE library SET {', '.join(k + '=?' for k in FIELDS)}, sheet=? WHERE id=?", *row.values(), json.dumps(sh), old[0]["id"])
        lid = old[0]["id"]
    else:
        lid = st.x(f"INSERT INTO library(car, {', '.join(FIELDS)}, sheet, added) VALUES(?,{','.join('?' * len(FIELDS))},?,?)",
                   car, *row.values(), json.dumps(sh), time.time())
    return dict(ok=True, id=lid, replaced=bool(old), check=S.problems(sh))


def rows(st, car=None):
    out = st.q("SELECT * FROM library WHERE car=? ORDER BY id DESC", car) if car is not None else st.q("SELECT * FROM library ORDER BY car, id DESC")
    for r in out:
        r["sheet"] = json.loads(r["sheet"])
    return out


def results(st, lib_id):
    """The driver's laps with this tune on the car: best per track."""
    tracks = {t["id"]: t["name"] or f"Track {t['id']}" for t in st.q("SELECT id, name FROM tracks")}
    return [dict(track=tracks.get(r["track_id"], "-"), best=A.fmt_time(r["ms"]), laps=r["n"], sessions=r["s"])
            for r in st.q("""SELECT l.track_id, MIN(l.time_ms) ms, COUNT(*) n, COUNT(DISTINCT l.session_id) s FROM laps l
                             JOIN sessions s ON s.id = l.session_id
                             WHERE s.library_id=? AND l.time_ms>0 AND l.first=0 AND l.track_id IS NOT NULL GROUP BY l.track_id""", lib_id)]


def current_tune(st, car):
    """The settings sheet last filed for this car (what should be on it now)."""
    r = st.q("SELECT * FROM tunes WHERE car=? ORDER BY id DESC LIMIT 1", car)
    if r:
        r[0]["sheet"] = json.loads(r[0]["sheet"])
    return r[0] if r else None


def link_for_sheet(st, car, sh):
    """If a filed sheet is a library tune as published (nothing differs over 8+ shared settings), return that tune's id."""
    for r in rows(st, car):
        if S.compared(sh, r["sheet"]) >= 8 and not S.diff(sh, r["sheet"]):
            return r["id"]
    return None


def on_car(st, car, gear_ratios):
    """Which tune is on the car right now -> (own sheet or None, library tune or None).
    The library tune comes from the filed sheet if it is linked, otherwise from the gearbox the car reports - but only when
    exactly one library tune has that gearbox (stock gearboxes are the same in every tune, so they prove nothing)."""
    mine = current_tune(st, car); lib = rows(st, car)
    by_id = {r["id"]: r for r in lib}
    if mine and mine.get("library_id") in by_id and (not gear_ratios or not (by_id[mine["library_id"]]["sheet"].get("transmission") or {}).get("gears")
                                                      or S.gears_match(gear_ratios, by_id[mine["library_id"]]["sheet"])):
        return mine, by_id[mine["library_id"]]
    hits = [r for r in lib if S.gears_match(gear_ratios, r["sheet"])]
    boxes = {tuple((r["sheet"].get("transmission") or {}).get("gears") or []) for r in lib}
    return mine, hits[0] if len(hits) == 1 and len(boxes) > 1 else None


def view(st, r, mine=None):
    """A library row as the page and the agent see it."""
    res = results(st, r["id"])
    status = {"good": "proven", "bad": "did not suit"}.get(r["verdict"]) or ("driven" if res else "untested")
    out = dict(id=r["id"], car=r["car"], status=status, verdict_note=r["verdict_note"], sheet=r["sheet"], results=res,
               added=time.strftime("%Y-%m-%d", time.localtime(r["added"])), **{k: r[k] for k in FIELDS})
    if mine:
        out["differs_from_your_sheet"] = S.diff(mine["sheet"], r["sheet"])
        out["settings_compared"] = S.compared(mine["sheet"], r["sheet"])
        out["on_car"] = mine.get("library_id") == r["id"]
    return out
