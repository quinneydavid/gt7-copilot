"""How the car behaved over a lap, measured from the frames: slides, spins, understeer, one-wheel spin, gearing.
Everything is seconds per lap or a count, so laps and sessions can be averaged. Signs are worked out from the data
itself (which way is 'left' for yaw and for the steering wheel), so nothing depends on GT7's conventions."""
import numpy as np
from .packet import C, HZ, F_REV_LIMIT

LAT_CORNER = 3.0     # m/s^2 sideways: above this the car is cornering
LAT_HARD = 6.0       # ...and above this it is cornering hard (where understeer shows)
SPIN_YAW = 1.2       # rad/s: the car is going round, not cornering
PHASES = ("entry", "mid", "exit")


def _smooth(a, n):
    n = max(1, int(n)) | 1
    return np.convolve(np.pad(a, n // 2, mode="edge"), np.ones(n) / n, mode="valid")


def _held(mask, n=9):
    """Keep only stretches where mask holds for at least n frames (0.15 s): one odd frame is not a slide."""
    out = np.zeros(len(mask), bool); i = 0
    while i < len(mask):
        if mask[i]:
            j = i
            while j + 1 < len(mask) and mask[j + 1]:
                j += 1
            if j - i + 1 >= n:
                out[i:j + 1] = True
            i = j + 1
        else:
            i += 1
    return out


def _sec(mask):
    return round(float(mask.sum() / HZ), 2)


def measure(fr):
    """-> dict, or None when the lap has too little cornering to say anything."""
    v = fr[:, C["speed"]]; thr, brk = fr[:, C["thr"]], fr[:, C["brk"]]
    dt = np.maximum(np.gradient(fr[:, C["pid"]]) / HZ, 1 / HZ)
    path = _smooth(np.gradient(np.unwrap(np.arctan2(fr[:, C["vz"]], fr[:, C["vx"]]))) / dt, 9)    # how fast the car's path turns (rad/s)
    path[v < 8] = 0.0
    yaw = _smooth(fr[:, C["yawrate"]], 5)
    lat = np.abs(path) * v
    corner = (v > 8) & (lat > LAT_CORNER)
    if corner.sum() < 60:
        return None
    yaw = yaw * (np.sign(np.median(yaw[corner] * path[corner])) or 1.0)       # same sign convention as the path
    phase = dict(entry=brk > 0.1, exit=(thr >= 0.3) & (brk <= 0.1)); phase["mid"] = ~phase["entry"] & ~phase["exit"]
    # oversteer: the car rotates faster than its path turns (the rear is coming round)
    excess = yaw * np.sign(path) - np.abs(path)
    over = _held(corner & (excess > np.maximum(0.10, 0.25 * np.abs(path))))
    out = dict(cornering_s=_sec(corner), oversteer={p: _sec(over & phase[p]) for p in PHASES})
    # spins: count them and note what the driver was doing just before
    spinning = (np.abs(yaw) > SPIN_YAW) & (v > 5)
    spins = dict(braking=0, power=0, coasting=0); last = -10 ** 9
    for i in np.flatnonzero(spinning):
        if i - last > 2 * HZ:
            a = max(0, i - int(0.6 * HZ))
            spins["braking" if brk[a:i + 1].max() > 0.5 else "power" if thr[a:i + 1].max() > 0.5 else "coasting"] += 1
        last = i
    out["spins"] = spins
    # steering (heartbeat B only): understeer = much more lock than the corner needs; countersteer = lock against the turn
    has_steer = fr.shape[1] > C["steer"] and np.isfinite(fr[:, C["steer"]]).mean() > 0.9
    out["steering"] = bool(has_steer)
    if has_steer:
        st = np.nan_to_num(fr[:, C["steer"]])
        kappa = np.divide(path, v, out=np.zeros(len(v)), where=v > 8)
        calm = (v > 8) & (lat > 2.0) & (lat < 5.0) & ~over & (np.abs(kappa) > 1e-4)
        if calm.sum() >= 90:
            k = float(np.median(st[calm] / kappa[calm]))                       # wheel angle per unit of curvature when nothing is sliding
            need = k * kappa
            under = _held(corner & (lat > LAT_HARD) & ~over & (st * need > 0) & (np.abs(st) > 1.35 * np.abs(need) + 0.03))
            counter = _held(corner & (st * need < 0) & (np.abs(st) > 0.05), 6)
            out["understeer"] = {p: _sec(under & phase[p]) for p in PHASES}
            out["countersteer_s"] = _sec(counter)
    # one driven wheel spinning faster than its partner while cornering on the power (differential too open)
    power = corner & (thr > 0.5)
    for ax, (l, r) in dict(front=("ws_fl", "ws_fr"), rear=("ws_rl", "ws_rr")).items():
        a, b = fr[:, C[l]], fr[:, C[r]]
        out[f"one_wheel_spin_{ax}_s"] = _sec(_held(power & (np.abs(a - b) > 0.08 * v) & (np.maximum(a, b) > 1.06 * v), 6))
    # gearing
    gear = fr[:, C["gear"]].astype(int); top = int(gear.max()); lim = (fr[:, C["flags"]].astype(int) & F_REV_LIMIT) > 0
    in_top = gear == top
    out["gearing"] = dict(top_gear=top, top_gear_pct=round(float(in_top.mean() * 100), 1), limiter_top_gear_s=_sec(lim & in_top),
                          rpm_max_top_gear=int(fr[in_top, C["rpm"]].max()), full_throttle_top_gear_s=_sec(in_top & (thr > 0.95)))
    return out
