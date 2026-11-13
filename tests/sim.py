#!/usr/bin/env python3
"""Synthetic GT7 driver for tests: laps of a made-up closed circuit, emitted as real encrypted packets.
laps: list of dicts with optional per-corner mistakes, e.g. {"early_brake": {2: 25}} = brake 25 m early into the 2nd slow point."""
import math
import numpy as np
from gt7copilot.packet import build

def circuit(n=4000):
    phi = np.linspace(0, 2 * math.pi, n, endpoint=False)
    r = 320 * (1 + 0.28 * np.sin(2 * phi) + 0.22 * np.cos(3 * phi) + 0.08 * np.sin(5 * phi))
    return np.stack([r * np.cos(phi), r * np.sin(phi)], axis=1)

def speed_profile(xz, ds, slow=None, vmax=70.0, alat=14.0, brake=11.0, accel=4.5, early=None):
    dx, dz = np.gradient(xz[:, 0]), np.gradient(xz[:, 1])
    k = np.abs(np.gradient(np.unwrap(np.arctan2(dz, dx))) / ds)
    vt = np.minimum(vmax, np.sqrt(alat / np.maximum(k, 1e-6)))
    minima = [i for i in range(1, len(vt) - 1) if vt[i] < vt[i - 1] and vt[i] <= vt[i + 1] and vt[i] < vmax - 5]
    for j, f in (slow or {}).items():                      # carry less apex speed at slow point j
        i = minima[j]; vt[max(0, i - 40):i + 40] *= f
    v = vt.copy()
    for _ in range(2):                                     # closed loop: two passes each way
        for i in range(len(v) * 2):
            a, b = i % len(v), (i + 1) % len(v)
            v[b] = min(v[b], math.sqrt(v[a] ** 2 + 2 * accel * ds[a]))
        for i in range(len(v) * 2, 0, -1):
            a, b = i % len(v), (i - 1) % len(v)
            v[b] = min(v[b], math.sqrt(v[a] ** 2 + 2 * brake * ds[b]))
    for j, metres in (early or {}).items():                # brake earlier: hold the apex speed for `metres` before the apex
        i = minima[j]; n = int(metres / ds.mean())
        seg = v[i - 400:i + 1].copy()
        v[i - 400:i + 1] = np.minimum(v[i - 400:i + 1], np.concatenate([seg[n:], np.full(n, seg[-1])]))
    return v, minima

def packets(laps, start_pid=1000, car=3265, total_laps=0, fuel=60.0, fuel_per_lap=2.5, tyre=lambda lap: (70, 70, 72, 72)):
    xz = circuit(); nxt = np.roll(xz, -1, axis=0); ds = np.hypot(*(nxt - xz).T); length = ds.sum()
    tan = nxt - xz; tan /= np.hypot(*tan.T)[:, None]; kap = np.gradient(np.unwrap(np.arctan2(tan[:, 1], tan[:, 0]))) / ds   # signed curvature
    K_STEER = 9.0                                          # steering wheel radians per unit of curvature (made up, constant)
    pid = start_pid; last_ms = -1; best = -1
    for lap_no, spec in enumerate(laps, start=1):
        v, _ = speed_profile(xz, ds, slow=spec.get("slow"), early=spec.get("early_brake"))
        spun = 0; spin_at = -1e9; spin_left = 0
        s = 0.0; i = 0; t = 0.0; cum = np.concatenate([[0], np.cumsum(ds)])
        while s < length:
            i = min(int(np.searchsorted(cum, s, side="right")) - 1, len(xz) - 1)
            frac = (s - cum[i]) / ds[i]; p = xz[i] + (nxt[i] - xz[i]) * frac
            sp = v[i]; acc = (v[(i + 1) % len(v)] ** 2 - v[i] ** 2) / (2 * ds[i])
            thr = 1.0 if acc > 0.3 else (0.3 if acc > -0.5 else 0.0); brk = min(1.0, -acc / 11.0) if acc < -0.5 else 0.0
            spin = 1.12 if (spec.get("wheelspin") and thr == 1.0 and sp < 35) else 1.0
            yaw = sp * kap[i]; steer = K_STEER * kap[i]; lat = abs(yaw) * sp; ws = [sp, sp, sp * spin, sp * spin]; flags = 9
            if spec.get("understeer") and lat > 6:         # needs far more lock than the corner should take
                steer *= spec["understeer"]
            if spec.get("entry_slide") and brk > 0.1 and lat > 3:   # rear coming round on the brakes, driver catching it
                yaw *= 1.6; steer *= -0.5
            if spec.get("brake_spin") and brk > 0.6 and lat > 3 and spun < spec["brake_spin"] and s - spin_at > 300:
                spun += 1; spin_at = s; spin_left = 30
            if spin_left > 0:
                spin_left -= 1; yaw = 2.5 * (1 if kap[i] >= 0 else -1); brk = max(brk, 0.8)
            if spec.get("inside_spin") and thr == 1.0 and lat > 3:
                ws[2] = sp * 1.15
            if spec.get("rear_lock") and brk > 0.5:
                ws[2] = ws[3] = sp * 0.7
            gear = min(6, 1 + int(sp / 12))
            if spec.get("limiter") and gear == 6 and sp > 65:
                flags |= 32
            extra = dict(steer=steer) if not spec.get("no_steer") else {}
            yield build(dict(pid=pid, x=p[0], z=p[1], vx=sp * tan[i][0], vz=sp * tan[i][1], yawrate=yaw, rpm=3000 + sp * 80,
                             fuel=fuel - fuel_per_lap * (s / length), flags=flags,
                             speed=sp, tt=tyre(lap_no), lap=lap_no, total_laps=total_laps, last_ms=last_ms, best_ms=best,
                             gear=gear, thr=thr, brk=brk, ws=ws, car=car, **extra))
            pid += 1; s += sp / 60.0; t += 1 / 60.0
        last_ms = int(t * 1000); best = last_ms if best < 0 else min(best, last_ms); fuel -= fuel_per_lap
    for _ in range(30):                                    # a few frames into the next lap so the last one is closed
        yield build(dict(pid=pid, x=xz[0][0], z=xz[0][1], rpm=5000, fuel=fuel, speed=50, tt=tyre(lap_no + 1), lap=len(laps) + 1,
                         total_laps=total_laps, last_ms=last_ms, best_ms=best, gear=4, thr=1, brk=0, ws=[50] * 4, car=car))
        pid += 1
