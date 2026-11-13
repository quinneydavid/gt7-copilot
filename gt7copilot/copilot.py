"""Live copilot: decides what to say and when, from the frame stream and the reference lap. No language model here."""
import math, os, time
from collections import Counter
import numpy as np
from . import analysis as A, settings as CFG, speech as S, tuneadvice as TA
from .packet import C

LEAD = 6.0          # start speaking this many seconds before the braking point
TOO_LATE = 2.0      # ...but not if the braking point is closer than this
QUIET_GAP = 2.0     # no verdict if the next corner call starts within this many seconds
# corner calls per lap (biggest losses first) come from Settings: max_calls
MIN_LOSS = 0.10     # ...and nothing under this many seconds
LEAN_MAX = 0.25     # a leaner fuel map + lifting can save about this share per lap (GUESS, calibrate on real races);
                    # a bigger shortfall than that means a stop, and then saving fuel is pointless
BB_EVERY = 3        # laps between brake balance calls
HOT = 100.0         # tyre temperature (deg C) that earns a warning (calibrate on real laps)


class Copilot:
    def __init__(self, say, log=print):
        self.say, self.log = say, log       # say(text, ttl_seconds, kind)
        self.enabled = True
        self.on_session(None)

    driver_map = None; pit_plan = None; fuel_plan = None      # before the first session

    def on_session(self, c):
        self.idx = 0; self.s = []; self.announced = set(); self.judged = set(); self.advised = {}
        self.fuel_warned = None; self.tyre_warned_lap = -99; self.lap_seen = None
        self.t = []; self.pid0 = None; self.plan = None; self.prof_ref = None; self.prof_last = None; self.delta = None
        self.car_told = set(); self.wrapped = False
        self.fuel_plan = None; self.fuel_target = None; self.bb_lap = -99; self.bb_net = 0; self.pre_announced = set()
        self.pit_due = False; self.pit_reminded = False
        self.driver_map = None      # what the driver said about the fuel map: "lean" | "rich" | None
        self.pit_plan = None        # the lap at whose end the driver said they will stop
        if c is not None and self.enabled:
            line = S.tune_line(c.lib_tune, c.lib_count, bool(c.tune))
            if line:
                self.say(line, 20.0, "tune")

    # ---- every frame --------------------------------------------------------------------------------------------
    def on_frame(self, c, row, meta):
        if meta["lap"] != self.lap_seen:
            self.lap_seen = meta["lap"]; self.idx = 0; self.s = []; self.judged = set(); self.advised = {}
            self.announced = set(getattr(self, "pre_announced", ()))       # corners already called before the line
            self.pre_announced = set()
            self.pit_reminded = False
            self.t = []; self.pid0 = row[C["pid"]]; self.plan = None
        tr, ref = c.track, c.ref
        self.delta = None if not ref else self.delta
        if not (self.enabled and tr is not None and ref and ref.get("analysis")) or meta["lap"] < 1:
            return
        pts = tr["ref"]; lo, hi = max(0, self.idx - 10), min(len(pts), self.idx + 80)
        d2 = (pts[lo:hi, 0] - row[C["x"]]) ** 2 + (pts[lo:hi, 2] - row[C["z"]]) ** 2
        self.idx = lo + int(np.argmin(d2)); s = self.idx * A.STEP; self.s.append(s); self.t.append((row[C["pid"]] - self.pid0) / 60.0)
        v = max(row[C["speed"]], 5.0)
        if len(self.s) % 6 == 0:                         # live gap to the best lap at this point of the track
            ps, pt = self._profile(c); self.delta = round(self.t[-1] - float(np.interp(s, ps, pt)), 2)
        corners, rz = tr["corners"], (getattr(c, "best_zones", None) or ref["analysis"]["zones"])
        zs = A.zones(corners, tr["length"])
        clean = [l for l in c.session_laps if l.get("analysis") and not l.get("pit")]       # a pit lap teaches nothing about the corners
        last = clean[-1]["analysis"]["zones"] if clean and clean[-1] is c.session_laps[-1] else None
        if self.pit_due and not self.pit_reminded and s >= 0.8 * tr["length"]:      # the reminder that matters: before the pit entry
            self.pit_reminded = True
            self.say("Pit now. Pit this lap for fuel.", 12.0, "fuel")
        total = meta.get("total_laps") or 0
        for k, corner in enumerate(corners):                # a corner just after the line has to be called before the line:
            target = (rz[k] or {}).get("brake_s", corner["start"])     # six seconds ahead of turn one is still the previous lap
            if target - v * LEAD >= 0 or k in self.pre_announced or (total > 0 and meta["lap"] >= total):
                continue
            if tr["length"] + target - v * LEAD <= s:
                self.pre_announced.add(k)
                adv = A.advise(last[k], rz[k]) if last and k < len(last) else None
                if adv and adv["loss"] >= MIN_LOSS:
                    self.advised_next = {k: adv}
                    self.say(S.pre_corner(adv), (tr["length"] - s + target) / v - 0.5, "corner")
        for k, corner in enumerate(corners):
            target = (rz[k] or {}).get("brake_s", corner["start"])
            if k not in self.announced and target - v * LEAD <= s < target - v * TOO_LATE:
                self.announced.add(k)
                if self.plan is None:                    # once per lap: which corners are worth a call
                    cand = {j: A.advise(last[j], rz[j]) for j in range(min(len(last), len(rz)))} if last else {}
                    cand = {j: a for j, a in cand.items() if a and a["loss"] >= MIN_LOSS}
                    self.plan = {j: cand[j] for j in sorted(cand, key=lambda j: -cand[j]["loss"])[:int(CFG.get("max_calls"))]}
                adv = self.plan.get(k)
                if adv:
                    self.advised[k] = adv
                    self.say(S.pre_corner(adv), (target - s) / v - 0.5, "corner")
            if k not in self.judged and k < len(corners) - 1 and s >= min(corner["end"] + 40, zs[k][1]):
                self.judged.add(k)
                self._judge(c, k, corner, zs, rz, s, v)

    def _profile(self, c):
        """Time-at-distance for the reference lap, so any stretch of the current lap can be compared with it."""
        if self.prof_ref is None or self.prof_ref[0] != c.ref["id"]:
            fr = c.store.load_frames(c.ref["id"])
            self.prof_ref = (c.ref["id"], np.maximum.accumulate(A.project(fr, c.track["ref"])), A.lap_time_axis(fr))
        return self.prof_ref[1], self.prof_ref[2]

    def _judge(self, c, k, corner, zs, rz, s, v):
        """Just after the corner: how did this attempt compare with the best lap and with the previous lap?"""
        a = zs[k][0]
        span = lambda ss, tt: float(np.interp(s, ss, tt) - np.interp(a, ss, tt))
        cur = self.t[-1] - float(np.interp(a, self.s, self.t))
        vs_ref = cur - span(*self._profile(c))
        nxt = (rz[k + 1] or {}).get("brake_s", c.track["corners"][k + 1]["start"])
        if (nxt - s) / v - LEAD < QUIET_GAP:                  # the next corner call is due: stay quiet
            return
        if k in self.advised:
            vs_last = cur - span(*self.prof_last) if self.prof_last else 0.0
            self.say(S.verdict(corner["n"], vs_ref, vs_last), 3.0, "verdict")
        elif vs_ref > 0.4:
            self.say(f"Turn {S.words(corner['n'])}. Lost {S.gap(vs_ref)}.", 3.0, "verdict")

    # ---- every lap ----------------------------------------------------------------------------------------------
    def on_lap(self, c, lap):
        self.prof_last = (np.maximum.accumulate(np.asarray(self.s)), np.asarray(self.t)) if len(self.s) > 100 else None
        if not self.enabled:
            return
        if getattr(c, "track_news", None):               # the copilot has just named this track from where the car drove
            self.say(f"Track recognised. {c.track_news}.", 20.0, "info"); c.track_news = None
        prev = [l["time_ms"] for l in c.session_laps[:-1] if not l["first"]]
        best_before = min(prev) if prev else None
        ref_ms = c.ref and c.ref["time_ms"]
        if ref_ms and c.ref["id"] != lap["id"]:
            best_before = min(best_before, ref_ms) if best_before else ref_ms
        self.say(S.lap_line(lap["time_ms"], best_before), 8.0, "lap")
        total = c.meta.get("total_laps") or 0
        if total > 0 and lap["lap_no"] >= total and not self.wrapped:      # the flag: one summary of what to change
            self.wrapped = True
            try: self.say(self._wrap(c), 90.0, "summary")
            except Exception as e: self.log(f"race summary failed: {e!r}")
            return
        f = self._fuel(c, lap)
        if f:
            self.say(f, 15.0, "fuel")
        t = self._tyres(lap)
        if t:
            self.say(t, 15.0, "tyres")
        try:
            bb = self._brakes(c, lap)
            if bb:
                self.say(bb, 15.0, "brakes")
        except Exception as e:
            self.log(f"brake balance call failed: {e!r}")
        self._car(c)

    def _wrap(self, c):
        """End of the race, in one piece: best lap, where the time went (driving), what to change on the car."""
        laps = [l for l in c.session_laps if l.get("analysis") and not l.get("pit")]
        out = [f"Race done. Best lap {S.lap_time(min(l['time_ms'] for l in c.session_laps))}."]
        bz = c.best_zones or []
        per = {}                                                    # corner -> losses, incidents, causes over the race
        for l in laps:
            for k, z in enumerate(l["analysis"]["zones"]):
                if k >= len(bz) or not z or not bz[k]:
                    continue
                d = per.setdefault(k, dict(n=z["n"], loss=0.0, inc=0, causes=Counter()))
                d["loss"] += max(0.0, z["time"] - bz[k]["time"])
                if A.incident(z, bz[k]):
                    d["inc"] += 1
                else:
                    adv = A.advise(z, bz[k])
                    if adv and adv["cause"] != "time":
                        d["causes"][adv["cause"]] += 1
        worst = [d for d in sorted(per.values(), key=lambda d: -d["loss"]) if d["loss"] >= 0.5][:3]
        why = dict(brake_early="braking too early", brake_late="braking too late", apex_slow="too slow at the apex",
                   throttle_late="late back on the power", exit_slow="slow on the exit")
        if worst:
            bits = []
            for d in worst:
                t = f"turn {S.words(d['n'])}, {S.gap(d['loss'])} in total"
                if d["inc"]:
                    t += f", {S.words(d['inc'])} {'incident' if d['inc'] == 1 else 'incidents'}"
                elif d["causes"]:
                    t += ", mostly " + why[d["causes"].most_common(1)[0][0]]
                bits.append(t)
            out.append("Driving. Most time lost at " + "; ".join(bits) + ".")
        sums = [l["analysis"]["summary"] for l in c.session_laps if not l["first"] and l.get("analysis") and not l.get("pit")]
        adv = TA.advise(sums, c.tune and c.tune["sheet"], c.meta, pitted=any(l.get("pit") for l in c.session_laps))
        items = adv["items"][:2] if adv["ready"] else []
        if items:
            out.append("On the car. " + " ".join(TA.spoken(i) for i in items))
        elif adv["ready"]:
            out.append("On the car. Nothing stood out. Leave the settings alone.")
        if not c.tune:
            out.append("Send me the settings sheet and I will give you numbers.")
        return " ".join(out)

    def _car(self, c):
        """Once the session has enough laps: name the biggest thing the car itself is doing wrong, once per problem."""
        try:
            sums = [l["analysis"]["summary"] for l in c.session_laps if not l["first"] and l.get("analysis")]
            adv = TA.advise(sums, c.tune and c.tune["sheet"], c.meta)
            top = adv["items"][0] if adv["ready"] and adv["items"] else None
            if top and top["score"] >= 0.8 and top["key"] not in self.car_told:
                self.car_told.add(top["key"]); self.say(TA.spoken(top), 20.0, "tune")
        except Exception as e:
            self.log(f"tune advice failed: {e!r}")

    def _fuel(self, c, lap):
        """Fuel strategy at the line: lean when that gets you home without a stop, pit (and push) when it cannot,
        rich again when there is fuel to spare. Per-lap use is measured from the laps, pit laps left out."""
        used = [l["fuel_start"] - l["fuel_end"] for l in c.session_laps[-4:] if not l.get("pit") and l["fuel_start"] - l["fuel_end"] > 0.05][-3:]
        if not used:
            return None
        per = sum(used) / len(used); left = lap["fuel_end"] / per
        total = c.meta.get("total_laps") or 0
        to_go = total - lap["lap_no"] if total > 0 else None
        if to_go is not None and to_go <= 0:
            return None
        said = lambda key, msg: None if self.fuel_plan == key else (setattr(self, "fuel_plan", key), msg)[1]
        if to_go is None:                                # no lap count (time trial, practice): only warn when low
            return said("soon", f"Fuel for {S.words(int(left))} more {'lap' if int(left) == 1 else 'laps'}.") if left < 2.6 else None
        need = lap["fuel_end"] / to_go                   # per lap, to reach the flag on what is in the tank
        if lap.get("pit") or left >= to_go + 0.3:
            self.pit_due = False
        if left >= to_go + 0.3:                          # enough to finish
            if self.fuel_plan == "lean" and used[-1] <= need * 1.03:
                self.fuel_plan = "lean_ok"; return "Fuel is on target. Hold this."
            if left >= to_go + 1.0 and self.fuel_plan != "rich":
                was = self.fuel_plan; self.fuel_plan = "rich"
                if was in ("lean", "lean_ok") or lap.get("pit"):
                    spare = round(left - to_go, 1)
                    return f"Fuel to spare, {S.one_dp(spare)} {'lap' if spare == 1 else 'laps'} extra. Richest fuel map. Push."
            return None
        saving = 1 - need / per
        if lap.get("pit"):
            self.pit_plan = None
        if self.pit_plan and to_go > 0:                  # the driver named the lap of the stop: hold them to it, or say it will not reach
            reach = lap["lap_no"] + int(left - 0.3)      # the last lap the tank safely completes
            take = math.ceil(max(0.0, (to_go - left) * per + per * 0.3))
            if self.pit_plan <= lap["lap_no"]:
                self.pit_plan = None
            elif self.pit_plan <= reach:
                self.fuel_plan = "pit"
                if self.pit_plan == lap["lap_no"] + 1:
                    self.pit_due = True
                    return f"Pit this lap, as you planned. Take {S.words(take)} litres."
                return f"Fuel is fine until your stop on lap {S.words(self.pit_plan)}."
            else:
                self.pit_plan = None; self.fuel_plan = None
                # falls through to the ordinary countdown, which names the lap it has to be
        if saving <= LEAN_MAX and left >= 1.3 and self.driver_map != "rich":      # reachable without a stop (not if the driver stays rich)
            self.fuel_target = need
            if self.fuel_plan != "lean":
                self.fuel_plan = "lean"
                short = round(to_go - left, 1)
                return (f"Fuel is short by {S.one_dp(short)} {'lap' if short == 1 else 'laps'}. Go lean now to finish without a stop. "
                        f"Target {S.one_dp(need)} per lap. You are using {S.one_dp(per)}.")
            return f"Still over on fuel. Last lap {S.one_dp(used[-1])}, target {S.one_dp(need)}. Leaner map, or lift earlier."
        # A stop is needed. Say so EVERY lap, as a countdown, and say plainly which lap (real race, 11 Nov 2026: it said
        # "pit by lap eight" twice and then nothing on the lap of the stop).
        can = int(left - 0.3)                            # full laps safely left in the tank, counting this one
        take = math.ceil((to_go - left) * per + per * 0.3)
        first = self.fuel_plan != "pit"; self.fuel_plan = "pit"
        lead = "Saving will not cover it. Stay rich and push. " if first else ""
        if can <= 1:
            self.pit_due = True
            return (f"Pit this lap for fuel. Take {S.words(take)} litres." if left >= 1.0 else
                    f"Fuel will not last the lap. Save fuel and pit this lap. Take {S.words(take)} litres.")
        if can == 2:
            return f"{lead}Pit next lap for fuel. Take {S.words(take)} litres."
        return f"{lead}Pit in {S.words(can - 1)} laps, at the end of lap {S.words(lap['lap_no'] + can)}. Take {S.words(take)} litres."

    def outlook(self, c):
        """Where the fuel stands right now, for answers to the driver: dict(per, left, to_go, need, reach) or None before
        the first measured lap. left = laps in the tank; to_go = laps to the flag counting this one; reach = last lap the
        tank safely completes."""
        from .packet import C
        if not c.live or c.row is None or not c.lap_no:
            return None
        used = [l["fuel_start"] - l["fuel_end"] for l in c.session_laps[-4:] if not l.get("pit") and l["fuel_start"] - l["fuel_end"] > 0.05][-3:]
        if not used:
            return None
        per = sum(used) / len(used); now = float(c.row[C["fuel"]]); left = now / per
        total = c.meta.get("total_laps") or 0
        to_go = total - c.lap_no + 1 if total > 0 else None
        return dict(per=per, left=left, to_go=to_go, total=total, lap=c.lap_no, need=(now / to_go if to_go else None),
                    reach=c.lap_no - 1 + int(left - 0.3))

    def fuel_advice(self, c):
        """Which fuel map to run, in one sentence."""
        o = self.outlook(c)
        if not c.live:
            return "No car on track."
        if not o:
            return "No lap measured yet. Start on the rich map. I will tell you after lap one."
        if o["to_go"] is None:
            return f"No lap count here. You are using {S.one_dp(o['per'])} a lap, good for {S.one_dp(o['left'])} laps."
        if o["left"] >= o["to_go"] + 1.0:
            return f"Rich. You have {S.one_dp(o['left'] - o['to_go'])} laps of fuel to spare."
        if o["left"] >= o["to_go"] + 0.3:
            return "Hold what you have. The fuel is just enough to finish."
        if 1 - o["need"] / o["per"] <= LEAN_MAX and self.driver_map != "rich":
            return f"Lean. Target {S.one_dp(o['need'])} a lap to finish without a stop. You are using {S.one_dp(o['per'])}."
        return f"Rich, and stop. Saving will not cover it. Pit by the end of lap {S.words(max(o['lap'], o['reach']))}."

    def driver_says_map(self, c, which):
        """The driver says which fuel map they are on (or staying on). -> the answer."""
        self.driver_map = which
        o = self.outlook(c)
        if not o or o["to_go"] is None:
            return f"Copy. {which.capitalize()}."
        enough = o["left"] >= o["to_go"] + 0.3
        if which == "rich":
            if enough:
                return "Copy. Rich. The fuel is enough to finish."
            self.fuel_plan = None                        # the next lap's call is the pit countdown, not "go lean"
            return f"Copy. Rich. Then you need a stop, by the end of lap {S.words(max(o['lap'], o['reach']))}."
        if enough:
            return "Copy. Lean. You have enough fuel, you could run rich."
        if 1 - o["need"] / o["per"] <= LEAN_MAX:
            return f"Copy. Lean. Target {S.one_dp(o['need'])} a lap. You are using {S.one_dp(o['per'])}."
        return f"Copy. Lean will not cover it. You need a stop by the end of lap {S.words(max(o['lap'], o['reach']))}."

    def driver_plans_pit(self, c, lap_no, why="fuel"):
        """The driver says at the end of which lap they will stop (None = no lap named). -> the answer."""
        total = c.meta.get("total_laps") or 0
        if lap_no is None:
            return "Copy. Pit" + (f" for {why}" if why != "a stop" else "") + ". Tell me the lap."
        if total and lap_no > total:
            lap_no = total
        o = self.outlook(c)
        if why == "fuel" and total and lap_no >= total:
            return "The last lap ends at the flag. A stop there gains nothing." + (f" You need one by the end of lap {S.words(max(o['lap'], o['reach']))}." if o and o["to_go"] and o["left"] < o["to_go"] + 0.3 else "")
        if o and o["reach"] < lap_no and (o["to_go"] is None or o["left"] < o["to_go"] + 0.3):
            return f"Fuel will not last to lap {S.words(lap_no)}. Pit by the end of lap {S.words(max(o['lap'], o['reach']))}."
        self.pit_plan = lap_no
        return f"Copy. Pit at the end of lap {S.words(lap_no)}" + (f", for {why}." if why != "a stop" else ".")

    def _brakes(self, c, lap):
        """Brake balance during the race, from how the car behaved into the corners over the last two clean laps."""
        clean = [l for l in c.session_laps if l.get("analysis") and not l.get("pit") and l["analysis"]["summary"].get("handling")][-2:]
        if len(clean) < 2 or clean[-1] is not c.session_laps[-1] or lap["lap_no"] - self.bb_lap < BB_EVERY:
            return None
        h = [l["analysis"]["summary"]["handling"] for l in clean]
        over = sum(x["oversteer"]["entry"] for x in h) / 2 + sum(x["spins"]["braking"] for x in h)
        under = sum(x["understeer"]["entry"] for x in h) / 2 if all(x.get("steering") for x in h) else 0.0
        if over >= 1.0 and over > under + 0.5 and self.bb_net > -2:
            self.bb_net -= 1; self.bb_lap = lap["lap_no"]
            return "The rear is loose into the corners. Brake balance one step to the front."
        if under >= 2.0 and under > over + 1.0 and self.bb_net < 2:
            self.bb_net += 1; self.bb_lap = lap["lap_no"]
            return "The car pushes on the way in. Brake balance one step to the rear."
        return None

    def _tyres(self, lap):
        an = lap.get("analysis")
        if not an or lap["lap_no"] - self.tyre_warned_lap < 3:
            return None
        t = an["summary"]["tyre_avg"]; f, r = (t["fl"] + t["fr"]) / 2, (t["rl"] + t["rr"]) / 2
        msg = None
        if f > HOT and f > r + 8:
            msg = f"Front tyres are hot, {S.words(f)} degrees. Ease off on corner entry."
        elif r > HOT and r > f + 8:
            msg = f"Rear tyres are hot, {S.words(r)} degrees. Gentler on the throttle out of corners."
        elif f > HOT + 10 and r > HOT + 10:
            msg = f"All four tyres are overheating, {S.words((f + r) / 2)} degrees."
        if msg:
            self.tyre_warned_lap = lap["lap_no"]
        return msg
