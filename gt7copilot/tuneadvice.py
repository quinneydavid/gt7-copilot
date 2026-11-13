"""From what the car did (handling + lap summaries) to what to change on the settings sheet.
Rules only, no language model: each rule is a symptom, the evidence for it, the usual fixes in order, and the settings on
the current sheet that are known to cause it. With a sheet on file the fixes carry numbers (from -> to); without one they
carry directions. One change at a time: the first fix of the first item is the one to try."""
from . import sheet as S

MIN_LAPS = 3
ENDS = dict(front=0, rear=1)


def _avg(sums, *path):
    vals = []
    for s in sums:
        x = s
        for k in path:
            x = x.get(k) if isinstance(x, dict) else None
        if isinstance(x, (int, float)):
            vals.append(x)
    return sum(vals) / len(vals) if vals else 0.0


def _get(sh, path, end=None):
    x = sh
    for k in path.split("."):
        x = x.get(k) if isinstance(x, dict) else None
    if end is not None:
        x = x[ENDS[end]] if isinstance(x, list) and len(x) == 2 else None
    return x if isinstance(x, (int, float)) else None


def _fix(sh, path, end, delta, why):
    """One proposed change. delta is a number, or ('pct', n) for a relative step (downforce)."""
    name = S.label(path) + (f" › {end}" if end else "")
    cur = _get(sh, path, end) if sh else None
    pct = isinstance(delta, tuple)
    step = delta[1] if pct else delta
    out = dict(setting=name, game_setting=S.game_label(path, end), path=path, end=end, direction="raise" if step > 0 else "lower", why=why,
               step=f"{abs(step)} %" if pct else abs(step))
    if sh and cur is None and S.part_for(path):          # a sheet is on file and this setting is not on it: the part is missing
        out["needs_part"] = S.part_for(path)
    if cur is not None:
        new = cur * (1 + step / 100) if pct else cur + step
        lo, hi = S.LIMITS.get(path, (None, None))
        if lo is not None:
            new = min(hi, max(lo, new))
        new = round(new) if pct or float(step).is_integer() else round(new, 2)
        if new == cur:
            return None                                   # already at the limit
        out.update(now=cur, to=new)
    return out


def _suspects(sh, checks):
    """checks: (path, end, test, text). Settings on the sheet that are known to cause this symptom."""
    out = []
    for path, end, test, text in checks:
        v = _get(sh, path, end)
        if v is not None and test(v):
            out.append(dict(setting=S.label(path) + (f" › {end}" if end else ""), game_setting=S.game_label(path, end), now=v, why=text))
    return out


def _split_fix(sh, rearward, why):
    """Front/Rear Torque Distribution on a 4WD with the centre differential: '45:55' -> '40:60'."""
    try:
        f, r = (int(x) for x in str(sh["differential"]["front_rear_torque_split"]).split(":"))
    except Exception:
        return None
    nf = max(5, min(50, f - rearward))
    if nf == f:
        return None
    return dict(setting="differential › front rear torque split", game_setting=S.game_label("differential.front_rear_torque_split"),
                path="differential.front_rear_torque_split", end=None,
                direction="more to the rear" if rearward > 0 else "more to the front", why=why, step=abs(rearward), now=f"{f}:{r}", to=f"{nf}:{100 - nf}")


def _tyres(sums, hs, sh, pitted):
    """A compound change, when the laps say so: short of grip everywhere, overheating, or stopping anyway."""
    cur = S.compound(((sh or {}).get("tyres") or {}).get("rear") or ((sh or {}).get("tyres") or {}).get("front"))
    slide = _avg(hs, "understeer", "mid") + _avg(hs, "understeer", "exit") + _avg(hs, "oversteer", "mid") + _avg(hs, "oversteer", "exit")
    hot = max((max(s["tyre_avg"].values()) for s in sums if s.get("tyre_avg")), default=0)     # lap averages: peaks spike in every slide
    def item(score, problem, evidence, to, direction, why):
        fx = dict(setting="tyres", game_setting="Tires: Front and Rear", path="tyres", end=None, direction=direction, why=why, step=1)
        if cur and to:
            fx.update(now=cur, to=to)
        elif cur:
            return None                                   # already the softest / hardest of its family
        return dict(key="tyres", score=round(score, 2), problem=problem, evidence=evidence, fixes=[fx], suspect_settings=[])
    if hot >= 105:
        return item(1.5, "The tyres are overheating", [f"a tyre averaging {hot:.0f} °C over a lap"], S.softer(cur, -1), "one compound harder",
                    "a harder compound takes the heat; it also lasts longer")
    if pitted and slide >= 4.0:
        return item(2.0, "You stop for fuel anyway, and the car is short of grip", [f"a pit stop in this race", f"sliding in and out of corners {slide:.1f} s per lap"],
                    S.softer(cur), "one compound softer", "more grip for the same number of stops: fit new ones at the fuel stop")
    if slide >= 8.0 and hot < 95:
        return item(1.0, "The car is short of grip everywhere", [f"sliding in and out of corners {slide:.1f} s per lap", f"tyres only reach {hot:.0f} °C"],
                    S.softer(cur), "one compound softer", "a softer compound grips more and warms up faster; it wears sooner")
    return None


def advise(sums, sh=None, meta=None, pitted=None):
    """sums: lap summaries of the timed laps of one session. -> dict(ready, items, parts, notes)."""
    pitted = any(s.get("pit") for s in sums) if pitted is None else pitted
    sums = [s for s in sums if not s.get("pit")]          # a pit lap says nothing about the car
    hs = [s["handling"] for s in sums if s.get("handling")]
    notes = []
    if len(sums) < MIN_LAPS:
        return dict(ready=False, items=[], notes=[f"Needs {MIN_LAPS} timed laps; this session has {len(sums)}."])
    if not hs:
        return dict(ready=False, items=[], notes=["These laps were recorded before handling analysis existed. Drive a new session."])
    if not sh:
        notes.append("No settings sheet on file for this car, so changes are directions only. File a photo of the settings screen for numbers.")
    if not any(h.get("steering") for h in hs):
        notes.append("No steering data in these laps, so understeer is judged from tyre temperatures only.")
    notes.append("Camber, toe and downforce cannot be measured from telemetry; where they are listed it is because the sheet value is a known cause.")
    H = lambda *p: _avg(hs, *p)
    A = lambda *p: _avg(sums, *p)
    n = len(sums)
    spins = {k: sum(h["spins"][k] for h in hs) for k in ("braking", "power", "coasting")}
    drive = "front" if A("spin_f_s") > 2 * A("spin_r_s") + 0.1 else "rear"         # which axle puts the power down
    if sh and _get(sh, "differential.initial_torque", "rear") is None and _get(sh, "differential.initial_torque", "front") is not None:
        drive = "front"
    if (meta or {}).get("drivetrain") in ("FF", "FR", "MR", "RR"):                 # the car list knows the layout; 4WD stays measured
        drive = "front" if meta["drivetrain"] == "FF" else "rear"
    f = lambda *a: _fix(sh, *a)
    items = []

    def add(key, score, problem, evidence, fixes, suspects=()):
        if score > 0:
            items.append(dict(key=key, score=round(score, 2), problem=problem, evidence=evidence,
                              fixes=[x for x in fixes if x], suspect_settings=_suspects(sh, suspects) if sh else []))

    # --- unstable into corners / spinning under braking -----------------------------------------------------------
    e_over, lock_r = H("oversteer", "entry"), A("lock_r_s")
    sc = e_over + 6.0 * spins["braking"] / n + (lock_r if lock_r > 0.3 else 0)
    add("entry_oversteer", sc if (e_over > 0.3 or spins["braking"]) else 0, "The rear comes round under braking",
        [f"{spins['braking']} spin{'s' if spins['braking'] != 1 else ''} under braking in {n} laps"] * bool(spins["braking"])
        + [f"rear sliding on corner entry {e_over:.1f} s per lap"] * (e_over > 0.3) + [f"rear wheels locking {lock_r:.1f} s per lap"] * (lock_r > 0.3),
        [f("brake_balance", None, -1, "more of the braking on the front wheels"),
         f("differential.braking_sensitivity", drive, 5, "the differential holds the car straighter off the throttle"),
         f("suspension.toe_deg", "rear", 0.05, "rear toe-in steadies the rear"),
         f("suspension.anti_roll_bar", "rear", -1, "a softer rear bar gives the rear more grip"),
         f("aero.downforce", "rear", ("pct", 8), "more rear grip at speed")],
        [("brake_balance", None, lambda v: v > 0, "brake balance is set towards the rear"),
         ("suspension.toe_deg", "rear", lambda v: v < 0, "rear toe-out makes the rear nervous"),
         ("differential.braking_sensitivity", drive, lambda v: v <= 10, "very little differential lock under braking"),
         ("suspension.negative_camber_deg", "rear", lambda v: v > 3.5, "a lot of rear camber leaves little tyre on the road in a straight line"),
         ("suspension.negative_camber_deg", "front", lambda v: v > 4.5, "a lot of front camber shortens braking grip and upsets the car")])
    # --- front locking ---------------------------------------------------------------------------------------------
    lock_f = A("lock_f_s")
    add("front_lock", lock_f if lock_f > 0.4 and lock_f > 2 * lock_r else 0, "The front wheels lock under braking",
        [f"front wheels locking {lock_f:.1f} s per lap (rear {lock_r:.1f} s)"],
        [f("brake_balance", None, 1, "less of the braking on the front wheels")],
        [("brake_balance", None, lambda v: v <= -3, "brake balance is far towards the front"),
         ("suspension.negative_camber_deg", "front", lambda v: v > 4.0, "a lot of front camber reduces braking grip")])
    # --- understeer mid-corner -------------------------------------------------------------------------------------
    u_mid = H("understeer", "entry") + H("understeer", "mid"); tfr = A("tyre_front_minus_rear")
    sc = u_mid + (0.5 if tfr > 10 else 0)
    add("understeer", sc if (u_mid > 0.4 or (tfr > 12 and not any(h.get("steering") for h in hs))) else 0, "The car will not turn in (understeer)",
        [f"needing much more steering than the corner should take for {u_mid:.1f} s per lap"] * (u_mid > 0.4)
        + [f"front tyres {tfr:.0f} °C hotter than the rears"] * (tfr > 10),
        [f("suspension.anti_roll_bar", "front", -1, "a softer front bar gives the front more grip"),
         f("suspension.anti_roll_bar", "rear", 1, "a stiffer rear bar helps the car rotate"),
         f("suspension.natural_frequency_hz", "front", -0.1, "softer front springs, more front grip"),
         f("differential.initial_torque", drive, -5, "a freer differential lets the car turn"),
         f("aero.downforce", "front", ("pct", 8), "more front grip at speed")],
        [("suspension.negative_camber_deg", "front", lambda v: v < 1.0, "very little front camber for cornering"),
         ("differential.initial_torque", drive, lambda v: v >= 30, "a tight differential pushes the car straight on"),
         ("suspension.toe_deg", "front", lambda v: v > 0.1, "front toe-in dulls turn-in")]
        + ([("suspension.anti_roll_bar", "front", lambda v: v >= (_get(sh, "suspension.anti_roll_bar", "rear") or 99) + 3, "front bar much stiffer than the rear")] if sh else []))
    # --- power oversteer / wheelspin on exit -----------------------------------------------------------------------
    x_over, spin_d = H("oversteer", "exit"), A(f"spin_{drive[0]}_s")
    one = H(f"one_wheel_spin_{drive}_s")
    both = max(0.0, spin_d - one)
    sc = (x_over + 6.0 * spins["power"] / n + 0.5 * both) if drive == "rear" else 0
    add("exit_oversteer", sc if (x_over > 0.3 or spins["power"] or both > 1.0) and drive == "rear" else 0, "The rear steps out on the power",
        [f"{spins['power']} spin{'s' if spins['power'] != 1 else ''} on the throttle in {n} laps"] * bool(spins["power"])
        + [f"rear sliding on corner exit {x_over:.1f} s per lap"] * (x_over > 0.3) + [f"both rear wheels spinning {both:.1f} s per lap"] * (both > 1.0),
        [f("differential.acceleration_sensitivity", "rear", -5, "a looser differential on the power is less snappy"),
         f("suspension.anti_roll_bar", "rear", -1, "a softer rear bar gives the rear more grip"),
         f("suspension.toe_deg", "rear", 0.05, "rear toe-in steadies the rear on the power"),
         f("suspension.natural_frequency_hz", "rear", -0.1, "softer rear springs help traction")],
        [("differential.acceleration_sensitivity", "rear", lambda v: v >= 40, "a strongly locking differential snaps the rear round"),
         ("suspension.toe_deg", "rear", lambda v: v < 0, "rear toe-out makes the rear nervous on the power"),
         ("suspension.negative_camber_deg", "rear", lambda v: v > 3.0, "a lot of rear camber costs traction")])
    # --- one driven wheel spinning ---------------------------------------------------------------------------------
    add("one_wheel_spin", one if one > 0.5 else 0, f"One {drive} wheel spins up out of corners",
        [f"the inside {drive} wheel spinning on its own {one:.1f} s per lap"],
        [f("differential.acceleration_sensitivity", drive, 5, "more lock on the power shares the drive between both wheels"),
         f("differential.initial_torque", drive, 5, "more preload does the same at low load")],
        [("differential.acceleration_sensitivity", drive, lambda v: v <= 10, "the differential is almost open on the power")])
    # --- understeer on the power -----------------------------------------------------------------------------------
    u_exit = H("understeer", "exit")
    add("exit_understeer", u_exit if u_exit > 0.5 else 0, "The car pushes wide on the power",
        [f"needing extra steering on corner exit {u_exit:.1f} s per lap"],
        [f("differential.acceleration_sensitivity", drive, -5, "a looser differential lets the car keep turning on the power"),
         f("suspension.anti_roll_bar", "rear", 1, "a stiffer rear bar helps the car rotate"),
         (meta or {}).get("drivetrain") == "4WD" and sh and _split_fix(sh, 5, "more of the drive to the rear wheels pulls the nose in on the power")],
        [("differential.acceleration_sensitivity", drive, lambda v: v >= 40, "a strongly locking differential pushes the car wide")])
    # --- gearing ---------------------------------------------------------------------------------------------------
    lim = H("gearing", "limiter_top_gear_s")
    add("gearing_short", lim if lim > 0.5 else 0, "Top gear runs out before the end of the straight",
        [f"on the rev limiter in top gear {lim:.1f} s per lap"],
        [f("transmission.top_speed_kmh", None, 10, "a longer final gear: stop hitting the limiter")])
    alert = (meta or {}).get("rpm_alert") or [0, 0]
    rmax, pct, ft = H("gearing", "rpm_max_top_gear"), H("gearing", "top_gear_pct"), H("gearing", "full_throttle_top_gear_s")
    unused = alert[0] > 0 and lim == 0 and (pct < 1.0 or (ft > 1.0 and rmax < 0.85 * alert[0]))
    add("gearing_long", 0.4 if unused else 0, "The gearing is too long for this track",
        [f"top gear used {pct:.0f} % of the lap, reaching {rmax:.0f} rpm (shift lights start at {alert[0]})"],
        [f("transmission.top_speed_kmh", None, -10, "a shorter final gear: better acceleration everywhere")])
    # --- tyres -----------------------------------------------------------------------------------------------------
    if tfr < -12 and not any(i["key"] in ("exit_oversteer", "entry_oversteer") for i in items):
        add("rear_tyres_hot", 0.3, "The rear tyres run much hotter than the fronts", [f"rears {-tfr:.0f} °C hotter than the fronts"],
            [f("differential.acceleration_sensitivity", drive, -5, "less sliding on the power keeps the rears cooler"),
             f("suspension.anti_roll_bar", "rear", -1, "a softer rear bar works the rear tyres less")])
    ty = _tyres(sums, hs, sh, pitted)
    if ty:
        items.append(ty)
    items.sort(key=lambda i: -i["score"])
    for i in items:
        i["suspect_settings"] = [x for x in i["suspect_settings"] if x["why"]]
    parts = []                                            # hardware to add before the proposed changes can be made
    for i in items[:4]:
        for fx in i["fixes"]:
            if fx.get("needs_part") and fx["needs_part"] not in [p["part"] for p in parts]:
                parts.append(dict(part=fx["needs_part"], unlocks=fx["game_setting"], for_problem=i["problem"]))
            if fx["setting"] == "tyres" and fx.get("to"):
                parts.append(dict(part=f"Tires: {fx['to']}", unlocks="Tires: Front and Rear", for_problem=i["problem"]))
    if not items:
        notes.insert(0, "Nothing in the car's behaviour stands out. The time is in the driving, not the settings.")
    # One sheet to drive next: the first usable change for each problem, most important problem first. A setting is
    # only moved once; a later problem that wants it moved the other way falls back to its next fix.
    rec = {}
    for i in items[:4]:
        for fx in i["fixes"]:
            if "to" not in fx or fx.get("needs_part") or not fx.get("path"):
                continue
            k = (fx["path"], fx.get("end"))
            if k in rec:
                if rec[k]["to"] == fx["to"]:
                    break                                 # already covered by a more important problem
                continue
            rec[k] = dict(path=fx["path"], end=fx.get("end"), game_setting=fx["game_setting"], now=fx["now"], to=fx["to"],
                          problem=i["problem"], why=fx["why"])
            break
    for k, r in rec.items():                              # one reason per setting: every problem this change helps
        probs, whys = [r["problem"]], [r["why"]]
        for i in items[:4]:
            for fx in i["fixes"]:
                if (fx.get("path"), fx.get("end")) == k and fx.get("to") == r["to"]:
                    if i["problem"] not in probs: probs.append(i["problem"])
                    if fx["why"] not in whys: whys.append(fx["why"])
        r["problems"] = probs
        r["reason"] = "; ".join(p[0].lower() + p[1:] if n else p for n, p in enumerate(probs)) + ". " + "; ".join(whys).capitalize() + "."
    order = [r[0] for _, _, _, rows in S.LAYOUT for r in rows]
    recommended = sorted(rec.values(), key=lambda r: (order.index(r["path"]) if r["path"] in order else 99, r["end"] == "rear"))
    return dict(ready=True, laps=n, drive=drive, items=items[:4], parts=parts, recommended=recommended, notes=notes)


def spoken(item):
    """One short line for the copilot, in the words of the game's settings screen."""
    fx = item["fixes"][0] if item["fixes"] else None
    if not fx:
        return item["problem"] + "."
    name = fx.get("game_setting", fx["setting"]).replace(": ", ", ").replace("(", "").replace(")", "")
    if fx.get("needs_part"):
        return f"{item['problem']}. Fit the {fx['needs_part']}, then {fx['direction']} {name}."
    if "to" in fx:
        return f"{item['problem']}. {name}: {fx['now']} to {fx['to']}."
    return f"{item['problem']}. {name}: {fx['direction']}."
