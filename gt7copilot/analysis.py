"""Lap analysis: path, track fingerprint, corner detection, per-corner metrics, lap comparison, coaching advice."""
import math
import numpy as np
from .packet import C, HZ, F_REV_LIMIT, F_TCS, F_ASM

STEP = 2.0                  # metres between reference path points
CURV_ON = 1 / 220.0         # |curvature| above this = cornering (radius under 220 m)
LEFT_SIGN = 1               # sign of curvature that means "left" (TODO: confirm on a real lap)


def lap_time_axis(fr):
    """Seconds since the first frame, from the game's packet counter (so pauses don't count)."""
    pid = fr[:, C["pid"]]
    return (pid - pid[0]) / HZ


def path_of(fr, step=STEP):
    """Resample the driven line to one point every `step` metres. Returns (pts[n,3], length)."""
    xyz = fr[:, [C["x"], C["y"], C["z"]]]
    seg = np.hypot(np.diff(xyz[:, 0]), np.diff(xyz[:, 2]))
    d = np.concatenate([[0.0], np.cumsum(seg)])
    grid = np.arange(0.0, d[-1], step)
    pts = np.stack([np.interp(grid, d, xyz[:, i]) for i in range(3)], axis=1)
    return pts, float(d[-1])


def fingerprint(pts, n=256):
    idx = np.linspace(0, len(pts) - 1, n).astype(int)
    return pts[idx][:, [0, 2]]


def same_track(pts_a, len_a, pts_b, len_b):
    """Same layout = same length (3 %) and the two lines lie on top of each other (GT7 coordinates are fixed per track)."""
    if abs(len_a - len_b) > 0.03 * max(len_a, len_b):
        return False
    return float(np.mean(np.hypot(*(fingerprint(pts_a) - fingerprint(pts_b)).T))) < 30.0


def _smooth(a, n):
    n = max(1, int(n)) | 1
    return np.convolve(np.pad(a, n // 2, mode="edge"), np.ones(n) / n, mode="valid")


def curvature(pts, step=STEP):
    dx, dz = np.gradient(_smooth(pts[:, 0], 5)), np.gradient(_smooth(pts[:, 2], 5))
    heading = np.unwrap(np.arctan2(dz, dx))
    return _smooth(np.gradient(heading) / step, 20 / step)


def detect_corners(pts, step=STEP):
    """Corners = stretches where the line curves tighter than a 220 m radius. Returns dicts in metres along the lap."""
    k = curvature(pts, step)
    on = np.abs(k) > CURV_ON
    runs, i, n = [], 0, len(k)
    while i < n:
        if on[i]:
            j = i
            while j + 1 < n and on[j + 1] and np.sign(k[j + 1]) == np.sign(k[i]):
                j += 1
            runs.append([i, j, np.sign(k[i])])
            i = j + 1
        else:
            i += 1
    merged = []
    for r in runs:                                   # join pieces of one corner split by a short straighter bit
        if merged and r[2] == merged[-1][2] and (r[0] - merged[-1][1]) * step < 30:
            merged[-1][1] = r[1]
        else:
            merged.append(r)
    out = []
    for a, b, sgn in merged:
        if (b - a) * step < 20:
            continue
        apex = a + int(np.argmax(np.abs(k[a:b + 1])))
        out.append(dict(n=len(out) + 1, start=a * step, apex=apex * step, end=b * step,
                        dir="left" if sgn == LEFT_SIGN else "right", radius=round(1 / abs(k[apex]), 1)))
    return out


def zones(corners, length):
    """Split the whole lap into one zone per corner (boundaries halfway between corners) so zone times add up to the lap."""
    b = [0.0] + [(corners[i - 1]["end"] + corners[i]["start"]) / 2 for i in range(1, len(corners))] + [length]
    return [(b[i], b[i + 1]) for i in range(len(corners))]


def project(fr, ref_pts, step=STEP, start_idx=0, window=150):
    """Reference distance (metres along the reference line) for every frame, searching forward from the last match."""
    s = np.empty(len(fr)); idx = start_idx; n = len(ref_pts)
    xs, zs = fr[:, C["x"]], fr[:, C["z"]]
    for i in range(len(fr)):
        lo, hi = max(0, idx - 10), min(n, idx + window)
        d2 = (ref_pts[lo:hi, 0] - xs[i]) ** 2 + (ref_pts[lo:hi, 2] - zs[i]) ** 2
        idx = lo + int(np.argmin(d2))
        s[i] = idx * step
    return s


def _first(mask, hold=6):
    """Index of the first frame where mask holds for `hold` frames (0.1 s), else None."""
    run = 0
    for i, m in enumerate(mask):
        run = run + 1 if m else 0
        if run >= hold:
            return i - hold + 1
    return None


def slip_masks(fr):
    """Wheelspin / lockup per axle from wheel speed against car speed."""
    v = fr[:, C["speed"]]
    f = (fr[:, C["ws_fl"]] + fr[:, C["ws_fr"]]) / 2
    r = (fr[:, C["ws_rl"]] + fr[:, C["ws_rr"]]) / 2
    moving = v > 8
    power, braking = (fr[:, C["thr"]] > 0.5) & moving, (fr[:, C["brk"]] > 0.2) & moving
    lock_f = braking & (np.minimum(fr[:, C["ws_fl"]], fr[:, C["ws_fr"]]) < 0.85 * v)
    lock_r = braking & (np.minimum(fr[:, C["ws_rl"]], fr[:, C["ws_rr"]]) < 0.85 * v)
    return dict(spin_f=power & (f > 1.08 * v), spin_r=power & (r > 1.08 * v), lock_f=lock_f, lock_r=lock_r)


def zone_metrics(fr, s, t, corner, zone):
    """What the driver did in one corner zone. Distances are metres along the reference line, speeds km/h."""
    a, b = zone
    sel = (s >= a) & (s < b)
    if sel.sum() < 10:
        return None
    i0, i1 = int(np.argmax(sel)), int(len(sel) - np.argmax(sel[::-1]) - 1)
    f, ss, tt = fr[i0:i1 + 1], s[i0:i1 + 1], t[i0:i1 + 1]
    v = f[:, C["speed"]] * 3.6
    m = dict(n=corner["n"], time=round(float(tt[-1] - tt[0]), 3))
    near = (ss >= corner["start"] - 30) & (ss <= corner["end"] + 30)
    if not near.any():
        return m
    imin = int(np.argmin(np.where(near, v, 1e9)))
    m.update(min_speed=round(float(v[imin]), 1), min_s=float(ss[imin]), gear=int(f[imin, C["gear"]]))
    ib = _first((f[:imin + 1, C["brk"]] > 0.1))
    if ib is not None:
        m.update(brake_s=float(ss[ib]), entry_speed=round(float(v[ib]), 1), max_brake=round(float(f[:imin + 1, C["brk"]].max()), 2))
    it = _first(f[imin:, C["thr"]] > 0.5)
    if it is not None:
        m["throttle_s"] = float(ss[imin + it])
    iexit = int(np.argmin(np.abs(ss - corner["end"])))
    m["exit_speed"] = round(float(v[iexit]), 1)
    sm = slip_masks(f)
    m.update({k: round(float(x.sum() / HZ), 2) for k, x in sm.items() if x.any()})
    tcs = (f[:, C["flags"]].astype(int) & F_TCS) > 0
    if tcs.any():
        m["tcs"] = round(float(tcs.sum() / HZ), 2)
    return m


def lap_summary(fr):
    """Whole-lap facts about the car: tyres, slip, limiter, fuel, suspension."""
    fl = fr[:, C["flags"]].astype(int)
    sm = slip_masks(fr)
    temps = {w: round(float(fr[:, C["tt_" + w]].mean()), 1) for w in ("fl", "fr", "rl", "rr")}
    out = dict(max_speed=round(float(fr[:, C["speed"]].max() * 3.6), 1), tyre_avg=temps,
               tyre_max={w: round(float(fr[:, C["tt_" + w]].max()), 1) for w in ("fl", "fr", "rl", "rr")},
               tyre_front_minus_rear=round((temps["fl"] + temps["fr"] - temps["rl"] - temps["rr"]) / 2, 1),
               fuel_used=round(float(fr[0, C["fuel"]] - fr[-1, C["fuel"]]), 3),
               limiter_s=round(float(((fl & F_REV_LIMIT) > 0).sum() / HZ), 2),
               tcs_s=round(float(((fl & F_TCS) > 0).sum() / HZ), 2), asm_s=round(float(((fl & F_ASM) > 0).sum() / HZ), 2),
               full_throttle_pct=round(float((fr[:, C["thr"]] > 0.95).mean() * 100), 1),
               braking_pct=round(float((fr[:, C["brk"]] > 0.1).mean() * 100), 1),
               coasting_pct=round(float(((fr[:, C["thr"]] < 0.05) & (fr[:, C["brk"]] < 0.05)).mean() * 100), 1),
               susp_min={w: round(float(fr[:, C["su_" + w]].min()), 3) for w in ("fl", "fr", "rl", "rr")},
               susp_max={w: round(float(fr[:, C["su_" + w]].max()), 3) for w in ("fl", "fr", "rl", "rr")})
    out.update({k + "_s": round(float(x.sum() / HZ), 2) for k, x in sm.items()})
    try:
        from . import handling
        out["handling"] = handling.measure(fr)
    except Exception as e:                           # never lose a lap over the handling maths
        out["handling"] = None; out["handling_error"] = repr(e)
    g = fr[:, C["gear"]]
    up = np.where(np.diff(g) > 0)[0]
    if len(up):
        out["upshift_rpm_avg"] = int(fr[up, C["rpm"]].mean())
    return out


def analyse_lap(fr, track):
    """Full analysis of a lap on a known track -> dict(zones=[...], summary={...})."""
    ref = np.asarray(track["ref"])
    s, t = project(fr, ref), lap_time_axis(fr)
    zs = zones(track["corners"], track["length"])
    return dict(zones=[zone_metrics(fr, s, t, c, z) for c, z in zip(track["corners"], zs)], summary=lap_summary(fr))


MAX_METRES = 60        # a braking / throttle point further off than this is not a coaching point, something else happened
MAX_KMH = 30           # same for apex and exit speed
INCIDENT_SPEED = 0.65  # minimum speed below this share of the reference = a spin, an off or a crash
INCIDENT_LOSS = 2.5    # ...or this many seconds lost in one corner (real laps, 11 Nov 2026: spins lost 3.4 to 12 s)


def incident(cur, ref):
    """True when the corner went wrong outright (spin, off, crash) rather than a bit slow."""
    if not cur or not ref:
        return False
    if cur.get("min_speed") is not None and ref.get("min_speed") and cur["min_speed"] < ref["min_speed"] * INCIDENT_SPEED:
        return True
    return cur["time"] - ref["time"] > INCIDENT_LOSS


STEP_KMH = 10          # ask for at most this much more speed in one go: a target has to feel reachable
STEP_METRES = 20       # ...and at most this much later/earlier on the brakes


def best_zones(laps_zones):
    """Per corner, the reference the copilot coaches against: the fastest attempt among the given laps, with its speeds
    and braking point taken as the MIDDLE of the three fastest attempts. One lap is never the best everywhere (the best
    real lap had a 1.8 s mistake in turn one), and one freak pass is not a target (164 km/h through turn two once,
    155 to 159 on the other fastest passes: reported as unrealistic by the driver, 11 Nov 2026)."""
    out = []
    for k in range(max((len(z) for z in laps_zones), default=0)):
        cands = sorted((z[k] for z in laps_zones if k < len(z) and z[k] and z[k].get("time")), key=lambda z: z["time"])
        if not cands:
            out.append(None); continue
        ref = dict(cands[0]); top = cands[:3]
        if len(top) == 3:
            for f in ("min_speed", "entry_speed", "exit_speed", "brake_s", "throttle_s"):
                vals = sorted(t[f] for t in top if f in t)
                if len(vals) == 3 and f in ref:
                    ref[f] = vals[1]
        out.append(ref)
    return out


def advise(cur, ref):
    """Compare one corner (cur) with the reference corner (ref). Returns the main cause of the loss or None.
    Numbers are only quoted when they are believable; an incident gets a caution, not a coaching point."""
    if not cur or not ref:
        return None
    loss = cur["time"] - ref["time"]
    if loss < 0.08:
        return None
    a = dict(n=cur["n"], loss=round(loss, 2), ref_min_speed=ref.get("min_speed"))
    if incident(cur, ref):
        return dict(a, cause="incident")
    if "brake_s" in cur and "brake_s" in ref:
        d = ref["brake_s"] - cur["brake_s"]                 # positive = braked earlier than the reference
        if 8 < d <= MAX_METRES:
            return dict(a, cause="brake_early", metres=min(STEP_METRES, int(round(d, -1)) or 5))
        if -MAX_METRES <= d < -8 and cur.get("min_speed", 0) < ref.get("min_speed", 0) - 3:
            return dict(a, cause="brake_late", metres=min(STEP_METRES, int(round(-d, -1)) or 5))
    if "min_speed" in cur and "min_speed" in ref and 3 < ref["min_speed"] - cur["min_speed"] <= MAX_KMH:
        step = min(STEP_KMH, int(round(ref["min_speed"] - cur["min_speed"])))
        return dict(a, cause="apex_slow", kmh=step, target=int(round(cur["min_speed"] + step)))
    if "throttle_s" in cur and "throttle_s" in ref and 8 < cur["throttle_s"] - ref["throttle_s"] <= MAX_METRES:
        return dict(a, cause="throttle_late", metres=int(round(cur["throttle_s"] - ref["throttle_s"], -1)) or 5)
    if 3 < ref.get("exit_speed", 0) - cur.get("exit_speed", 0) <= MAX_KMH:
        return dict(a, cause="exit_slow", kmh=min(STEP_KMH, int(round(ref["exit_speed"] - cur["exit_speed"]))))
    return dict(a, cause="time")


def fmt_time(ms):
    if ms is None or ms <= 0:
        return "-"
    m, s = divmod(ms / 1000.0, 60)
    return f"{int(m)}:{s:06.3f}"
