#!/usr/bin/env python3
"""A simulated car, for trying the copilot without a console and for the demo data behind the README pictures.

It drives laps of one of the known layouts (the outline in data/circuits.json, smoothed into a driving line) and sends
what a console sends: 60 encrypted telemetry packets a second to UDP port 33740.

  python3 tools/demo/sim.py                      ten laps of Tsukuba in a Toyota GR86, to the copilot on this machine
  python3 tools/demo/sim.py --to 192.0.2.10 --track "Brands Hatch Indy Circuit" --car 3539 --laps 12
  python3 tools/demo/sim.py --list               the layouts it can drive
  --fast-laps 2    send the first two laps at ten times the speed, so the copilot has a reference lap at once
  --race           a race of --laps laps (the copilot then makes its fuel calls); otherwise a practice session

The driving is made up: a speed profile from the corner radii with braking zones, a driver who is a little different on
every lap, some wheelspin out of slow corners. Nothing here is used by the app. Needs numpy and pycryptodome, like the tests."""
import argparse, json, math, os, socket, sys, time
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
from gt7copilot.packet import build, decrypt, parse     # noqa: E402

HZ = 60.0
STEP = 2.0                              # metres between points of the driving line
GEARS = (3.082, 2.102, 1.546, 1.192, 0.962, 0.814)      # the gearbox packet.build() reports
SHIFT_RPM = 8200.0
MIN_RADIUS = 22.0                       # the outline is coarse (16 m squares) and draws hairpins too tight: for grip, none is tighter than this
MAX_YAW = 0.95                          # ...and the car never turns faster than this (rad/s), or a hairpin would look like a spin

# Made-up but plausible figures per car code: power (W), mass with driver (kg), sideways grip, braking and traction
# (m/s^2), air drag (1/m) and fuel (litres per km).
CARS = {
    3481: dict(name="Toyota GR86 RZ '21", power=160e3, mass=1345, grip=10.4, brake=9.6, traction=6.0, drag=0.00045, fuel_km=1.05, tank=50.0),
    3539: dict(name="Porsche 911 GT3 RS (992) '22", power=350e3, mass=1525, grip=11.6, brake=11.0, traction=8.0, drag=0.00040, fuel_km=1.55, tank=64.0),
}
# How the driver and the car behave over a session. Seconds are per lap.
DRIVER = dict(seed=1, pace=1.0, wheelspin=1.0, exit_slide=0.0, understeer=0.0, front_lock=0.0, weak={}, late={}, off={}, learn=0.025, scatter=0.006)
# weak / late: {corner: (metres, spread)} = on the brakes that much too early / on the throttle that much too late there.
# off: {lap: corner} = a moment in that corner on that lap. pace: 1.0 = everything the tyres give.


def circuits():
    return json.load(open(os.path.join(ROOT, "data", "circuits.json"), encoding="utf-8"))


def _roll_mean(a, n):
    """Moving average over a closed loop."""
    n = max(1, int(n)) | 1; pad = n // 2
    return np.convolve(np.concatenate([a[-pad:], a, a[:pad]]), np.ones(n) / n, mode="valid")


def line(name):
    """The driving line of a layout: a closed, smooth line through its outline -> (xz[n,2] every STEP metres, length)."""
    data = circuits(); grid = data.get("grid", 16)
    c = next((c for c in data["circuits"] if c["name"].lower() == name.lower()), None)
    if c is None:
        raise SystemExit(f"No layout named {name!r}. --list shows the names.")
    cells = np.asarray(c["cells"], float)
    pts = cells * grid + np.sign(cells) * grid / 2          # the middle of each square (squares are counted towards zero)

    def resample(p, step):
        closed = np.vstack([p, p[:1]])
        d = np.concatenate([[0.0], np.cumsum(np.hypot(*np.diff(closed, axis=0).T))])
        s = np.arange(0.0, d[-1], step)
        return np.stack([np.interp(s, d, closed[:, i]) for i in (0, 1)], axis=1)

    p = resample(pts, 4.0)
    for _ in range(4):                                      # the squares make a staircase: round it into a line
        p = np.stack([_roll_mean(p[:, i], 15) for i in (0, 1)], axis=1)
    p = resample(p, STEP)
    nxt = np.roll(p, -1, axis=0)
    return p, float(np.hypot(*(nxt - p).T).sum())


def _curvature(xz):
    nxt, prv = np.roll(xz, -1, axis=0), np.roll(xz, 1, axis=0)
    head = np.arctan2(nxt[:, 1] - prv[:, 1], nxt[:, 0] - prv[:, 0])
    turn = (np.roll(head, -1) - np.roll(head, 1) + math.pi) % (2 * math.pi) - math.pi      # over two steps, across the seam too
    return _roll_mean(turn / (2 * STEP), 15)


def _corners(vt, vmax):
    """Indices of the slowest point of each corner (limit speed clearly under the straight-line speed)."""
    n = len(vt); out = []
    for i in range(n):
        if vt[i] < 0.9 * vmax and vt[i] <= vt[i - 1] and vt[i] < vt[(i + 1) % n]:
            if out and (i - out[-1]) * STEP < 70:
                if vt[i] < vt[out[-1]]: out[-1] = i
            else:
                out.append(i)
    return out


def drive(track, car=3481, laps=10, driver=None):
    """One session as arrays, a row per packet: dict(lap, x, z, vx, vz, v, thr, brk, gear, rpm, yaw, steer, ws_f, ws_r, burn, s) plus length and laps."""
    spec = CARS[car]; d = dict(DRIVER, **(driver or {})); rng = np.random.default_rng(d["seed"])
    xz, length = line(track); n = len(xz); real = np.abs(_curvature(xz))
    k = np.clip(np.maximum(0.0, real - 1 / 600.0), 0.0, 1 / MIN_RADIUS)      # what is left of the staircase on a straight is not a corner
    g, br, tr, P, m, cd = spec["grip"], spec["brake"], spec["traction"], spec["power"], spec["mass"], spec["drag"]
    vmax = (P / m / cd) ** (1 / 3)
    base = np.minimum(np.minimum(vmax, np.sqrt(g / np.maximum(k, 1e-5))), MAX_YAW / np.maximum(real, 1e-5))
    apex = _corners(base, vmax)
    total = laps + 1                                        # one more lap, so the last one ends at speed and is closed
    vt = np.empty(total * n); kk = np.tile(k, total)
    for lap in range(total):
        pace = d["pace"] - d["learn"] * math.exp(-lap / 2.5) - abs(rng.normal(0, d["scatter"]))      # the driver finds grip lap by lap
        lim = base * math.sqrt(pace)
        for j, a in enumerate(apex):
            f = 1.0 - abs(rng.normal(0, 0.012))
            if d["off"].get(lap + 1) == j:                  # a moment: far too slow through this one
                f = 0.55
            w = int(60 / STEP); idx = np.arange(a - w, a + w) % n
            lim[idx] *= 1.0 - (1.0 - f) * 0.5 * (1 + np.cos(np.linspace(-math.pi, math.pi, 2 * w)))
        vt[lap * n:(lap + 1) * n] = lim
    v = vt.copy(); v[0] = 1.0                               # a standing start
    circle = lambda vv, i: math.sqrt(max(0.0, 1.0 - min(1.0, vv * vv * kk[i] / g) ** 2))
    for i in range(len(v) - 1):
        a = min(tr * circle(v[i], i), P / (m * max(v[i], 4.0))) - cd * v[i] ** 2 - 0.15
        v[i + 1] = min(v[i + 1], math.sqrt(max(v[i] ** 2 + 2 * a * STEP, 1.0)))
    for i in range(len(v) - 1, 0, -1):
        b = br * (0.25 + 0.75 * circle(v[i], i)) + cd * v[i] ** 2
        v[i - 1] = min(v[i - 1], math.sqrt(v[i] ** 2 + 2 * b * STEP))
    W = int(300 / STEP)
    for lap in range(laps):                                 # the driver's habits: on the brakes too early here, late on the throttle there
        for j, a in enumerate(apex):
            a += lap * n
            early = max(0.0, rng.normal(*d["weak"][j])) if j in d["weak"] else max(0.0, rng.normal(0, 4))
            e = int(early / STEP)
            if e and a - W > 0:
                seg = v[a - W:a + 1].copy(); v[a - W:a + 1] = np.minimum(seg, np.concatenate([seg[e:], np.full(e, seg[-1])]))
            late = max(0.0, rng.normal(*d["late"][j])) if j in d["late"] else 0.0
            e = int(late / STEP)
            if e:
                seg = v[a:a + W].copy(); v[a:a + W] = np.minimum(seg, np.concatenate([np.full(e, seg[0]), seg[:-e]]))
    # ---- from distance to time: one row per packet ----
    dist = np.arange(len(v)) * (length / n)
    t = np.concatenate([[0.0], np.cumsum((length / n) / np.maximum((v[:-1] + v[1:]) / 2, 0.5))])
    end = float(np.interp(laps * length + 25.0, dist, t))
    tf = np.arange(0.0, end, 1 / HZ)
    s = np.interp(tf, t, dist); vf = np.interp(s, dist, v)
    lap_no = (s // length).astype(int) + 1; loc = s % length
    grid = np.arange(n + 1) * (length / n); per = lambda a: np.interp(loc, grid, np.concatenate([a, a[:1]]))
    x, z = per(xz[:, 0]), per(xz[:, 1])
    nxt = np.roll(xz, -1, axis=0) - xz; tan = nxt / np.hypot(*nxt.T)[:, None]
    tx, tz = per(tan[:, 0]), per(tan[:, 1]); norm = np.hypot(tx, tz); tx, tz = tx / norm, tz / norm
    smooth = lambda a, w: np.convolve(np.pad(a, w // 2, mode="edge"), np.ones(w) / w, mode="valid")
    acc = smooth(np.gradient(vf) * HZ, 5); drag = cd * vf ** 2 + 0.15
    can = np.minimum(tr, P / (m * np.maximum(vf, 4.0)))
    thr = np.where(acc > -0.6, np.clip((acc + drag) / can, 0, 1), 0.0); thr[thr > 0.9] = 1.0
    brk = np.where(acc <= -0.6, np.clip((-acc - drag) / (br * 1.12), 0, 1), 0.0)
    thr, brk = smooth(thr, 7), smooth(brk, 7)
    thr[brk > 0.05] = 0.0; thr[0:20] = 1.0
    top = float(vf.max()) * 1.03                             # the gearing suits the track: top gear nearly used up
    rpm_in = lambda gi, vv: SHIFT_RPM * vv / top * GEARS[gi] / GEARS[-1]
    gear = np.empty(len(vf), int); cur = 0
    for i, vv in enumerate(vf):
        while cur < len(GEARS) - 1 and rpm_in(cur, vv) > 8000: cur += 1
        while cur > 0 and rpm_in(cur - 1, vv) < 6900: cur -= 1
        gear[i] = cur
    rpm = np.maximum(1400.0, np.array([rpm_in(gi, vv) for gi, vv in zip(gear, vf)])) + rng.normal(0, 12, len(vf))
    yaw = smooth(np.gradient(np.unwrap(np.arctan2(tz, tx))) * HZ, 9)          # how fast the line itself turns, in rad/s
    steer = 9.0 * yaw / np.maximum(vf, 5.0); ws_r = vf.copy(); ws_f = vf.copy()
    burn = np.cumsum((0.3 + 0.7 * thr) * vf); burn *= spec["fuel_km"] / 1000.0 * s[-1] / burn[-1]      # litres used so far
    # ---- the car's behaviour: wheelspin and a slide out of slow corners, understeer into the tight ones ----
    slow = [j for j, a in enumerate(apex) if base[a] < 0.62 * vmax] or list(range(len(apex)))
    tight = sorted(range(len(apex)), key=lambda j: base[apex[j]])[:3]
    frame_at = lambda lap, a: int(np.searchsorted(s, lap * length + a * (length / n)))
    for lap in range(laps):
        for j in slow:
            i = frame_at(lap, apex[j]); on = np.flatnonzero(thr[i:i + 240] > 0.6)
            if not len(on): continue
            i += int(on[0]); dur = int(max(0.0, rng.normal(d["wheelspin"] / len(slow), 0.12)) * HZ)
            ws_r[i:i + dur] *= 1.0 + 0.13 * np.hanning(dur + 2)[1:-1] ** 0.3 if dur else 1.0
            sl = int(max(0.0, rng.normal(d["exit_slide"] / len(slow), 0.08)) * HZ)
            if sl > 9:
                yaw[i:i + sl] = np.clip(yaw[i:i + sl] * 1.6, -1.15, 1.15); steer[i:i + sl] *= 0.2
        for j in tight:
            i = frame_at(lap, apex[j]); dur = int(max(0.0, rng.normal(d["understeer"] / len(tight), 0.08)) * HZ)
            if dur > 9:
                steer[i - dur:i] *= 2.0
            hard = np.flatnonzero(brk[max(0, i - 300):i] > 0.7)       # the front wheels lock for a moment at the start of the braking
            dur = int(max(0.0, rng.normal(d["front_lock"] / len(tight), 0.06)) * HZ)
            if len(hard) and dur:
                i = max(0, i - 300) + int(hard[0]) + 6; ws_f[i:i + dur] *= 0.78
    return dict(lap=lap_no, x=x, z=z, vx=vf * tx, vz=vf * tz, v=vf, thr=thr, brk=brk, gear=gear + 1, rpm=rpm, yaw=yaw, steer=steer,
                ws_r=ws_r, ws_f=ws_f, burn=burn, s=s, length=length, laps=laps)


def packets(track="Tsukuba Circuit", car=3481, laps=10, driver=None, race=False, fuel=None, start_pid=1000):
    """The session as encrypted packets, in order. A lap counts once the car is over the line."""
    f = drive(track, car, laps, driver); spec = CARS[car]; length = f["length"]
    fuel0 = spec["tank"] if fuel is None else fuel
    last_ms = best_ms = -1; lap_start = 0
    for i in range(len(f["v"])):
        lap = int(f["lap"][i])
        if i and lap != f["lap"][i - 1]:
            last_ms = int(round((i - lap_start) / HZ * 1000)); best_ms = last_ms if best_ms < 0 else min(best_ms, last_ms); lap_start = i
        warm = 1.0 - math.exp(-f["s"][i] / 3500.0); load = abs(f["yaw"][i]) * f["v"][i] / 12.0
        front, rear = 58 + 24 * warm + 3 * load, 56 + 22 * warm + 2 * load + 40 * (f["ws_r"][i] / max(f["v"][i], 1.0) - 1.0)
        v = float(f["v"][i])
        yield build(dict(pid=start_pid + i, x=float(f["x"][i]), z=float(f["z"][i]), vx=float(f["vx"][i]), vz=float(f["vz"][i]),
                         yawrate=float(f["yaw"][i]), steer=float(f["steer"][i]), rpm=float(f["rpm"][i]), speed=v,
                         fuel=max(0.0, fuel0 - float(f["burn"][i])),
                         tt=(front, front + 1.5, rear, rear + 1.0), lap=lap, total_laps=laps if race else 0,
                         last_ms=last_ms, best_ms=best_ms, gear=int(f["gear"][i]), thr=float(f["thr"][i]), brk=float(f["brk"][i]),
                         ws=[float(f["ws_f"][i]), float(f["ws_f"][i]), float(f["ws_r"][i]), float(f["ws_r"][i])], car=car))


def send(to="127.0.0.1", port=33740, fast_laps=0, fast=10.0, on_lap=None, **session):
    """Send a session in real time. The first `fast_laps` laps go out `fast` times quicker."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); gen = packets(**session)
    due = time.time(); lap = 0
    for pkt in gen:
        sock.sendto(pkt, (to, port))
        now_lap = parse(decrypt(pkt))[1]["lap"]
        if now_lap != lap:
            lap = now_lap
            if on_lap: on_lap(lap)
        due += 1 / HZ / (fast if lap <= fast_laps else 1.0)
        wait = due - time.time()
        if wait > 0: time.sleep(wait)
        else: due = time.time()


def main():
    ap = argparse.ArgumentParser(description="A simulated car that sends Gran Turismo 7 telemetry to the copilot.")
    ap.add_argument("--to", default="127.0.0.1", help="the machine the copilot runs on (default: this one)")
    ap.add_argument("--port", type=int, default=33740)
    ap.add_argument("--track", default="Tsukuba Circuit", help="a layout name from --list")
    ap.add_argument("--car", type=int, default=3481, choices=sorted(CARS), help="car code: " + ", ".join(f"{c} = {v['name']}" for c, v in CARS.items()))
    ap.add_argument("--laps", type=int, default=10)
    ap.add_argument("--seed", type=int, default=1, help="another number, another driver")
    ap.add_argument("--fast-laps", type=int, default=0, help="send the first N laps at ten times the speed")
    ap.add_argument("--race", action="store_true", help="a race of --laps laps instead of a practice session")
    ap.add_argument("--list", action="store_true", help="print the layouts and stop")
    a = ap.parse_args()
    if a.list:
        for c in circuits()["circuits"]:
            print(f"{c['length'] / 1000:6.2f} km  {c['name']}")
        return
    print(f"{CARS[a.car]['name']} at {a.track}: {a.laps} laps to {a.to}:{a.port}. Open the copilot's Live page.", flush=True)
    try:
        send(a.to, a.port, a.fast_laps, track=a.track, car=a.car, laps=a.laps, race=a.race,
             driver=dict(seed=a.seed, wheelspin=1.4, understeer=0.7, weak={1: (14, 6)}),
             on_lap=lambda n: print(f"lap {n}" if n <= a.laps else "done", flush=True))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
