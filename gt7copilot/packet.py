"""GT7 telemetry packet: decrypt, parse into a flat row, and build (for the simulator)."""
import struct

KEY = b"Simulator Interface Packet GT7 ver 0.0"[:32]
MAGIC = 0x47375330
XOR_A = 0xDEADBEAF          # heartbeat "A" (296-byte packet)
# Heartbeat letter -> (packet length, IV mask). "B" adds steering wheel angle + body motion, "~" adds a few more fields.
KINDS = {"A": (0x128, 0xDEADBEAF), "B": (0x13C, 0xDEADBEEF), "~": (0x158, 0x55FABB4F)}
BY_LEN = {n: x for n, x in KINDS.values()}
HZ = 60.0

try:
    from Crypto.Cipher import Salsa20 as _S

    def salsa20(key, nonce, data):
        return _S.new(key=key, nonce=nonce).decrypt(data)
except ImportError:          # pure-python fallback (slow but dependency-free)
    from gt7probe import salsa20  # type: ignore

# Columns of a stored frame (one float64 row per packet).
COLS = ["pid", "x", "y", "z", "vx", "vy", "vz", "rot_y", "yawrate", "body_h", "speed", "rpm", "gear", "thr", "brk",
        "fuel", "tt_fl", "tt_fr", "tt_rl", "tt_rr", "ws_fl", "ws_fr", "ws_rl", "ws_rr",
        "su_fl", "su_fr", "su_rl", "su_rr", "flags", "boost", "water", "oil",
        "steer", "sway", "heave", "surge"]          # only from heartbeat B/~ (NaN otherwise; laps recorded before have no such columns)
C = {n: i for i, n in enumerate(COLS)}

F_ON_TRACK, F_PAUSED, F_LOADING, F_IN_GEAR, F_TURBO, F_REV_LIMIT, F_HANDBRAKE = 1, 2, 4, 8, 16, 32, 64
F_ASM, F_TCS = 1024, 2048


def decrypt(pkt):
    if len(pkt) not in BY_LEN:
        return None
    iv1 = struct.unpack_from("<I", pkt, 0x40)[0]
    d = salsa20(KEY, struct.pack("<II", iv1 ^ BY_LEN[len(pkt)], iv1), bytes(pkt))
    return d if struct.unpack_from("<I", d, 0)[0] == MAGIC else None


def parse(d):
    """Decrypted packet -> (row, meta). row follows COLS; meta holds the slow-changing session values."""
    f = struct.unpack_from
    x, y, z, vx, vy, vz = f("<6f", d, 0x04)
    rot_y = f("<f", d, 0x20)[0]
    yawrate = f("<f", d, 0x30)[0]
    body_h, rpm = f("<2f", d, 0x38)
    fuel, fuel_cap, speed, boost, _oilp, water, oil = f("<7f", d, 0x44)
    tt = f("<4f", d, 0x60)
    pid, lap, total_laps, best_ms, last_ms = f("<ihhii", d, 0x70)
    rpm_lo, rpm_hi, _vmax, flags = f("<hhhH", d, 0x88)
    g, thr, brk = d[0x90], d[0x91], d[0x92]
    rps = f("<4f", d, 0xA4)
    rad = f("<4f", d, 0xB4)
    su = f("<4f", d, 0xC4)
    ratios = f("<8f", d, 0x104)
    car = f("<i", d, 0x124)[0]
    extra = f("<f", d, 0x128) + f("<3f", d, 0x130) if len(d) >= 0x13C else (float("nan"),) * 4   # steering wheel angle (rad), sway, heave, surge
    row = [pid, x, y, z, vx, vy, vz, rot_y, yawrate, body_h, speed, rpm, g & 15, thr / 255.0, brk / 255.0, fuel,
           *tt, *[abs(rps[i]) * rad[i] for i in range(4)], *su, flags, boost - 1.0, water, oil, *extra]
    meta = dict(lap=lap, total_laps=total_laps, best_ms=best_ms, last_ms=last_ms, car=car, fuel_cap=fuel_cap,
                rpm_alert=(rpm_lo, rpm_hi), flags=flags, top_ratio=f("<f", d, 0x100)[0],
                gear_ratios=[round(r, 3) for r in ratios if r > 0], suggested_gear=g >> 4)
    return row, meta


def build(p):
    """Inverse of parse for the simulator: dict -> encrypted packet (316-byte "B" when p has 'steer', else 296-byte "A")."""
    n, mask = KINDS["B" if "steer" in p else "A"]
    d = bytearray(n)
    if "steer" in p:
        struct.pack_into("<f", d, 0x128, p["steer"])
    s = struct.pack_into
    s("<I", d, 0, MAGIC)
    s("<6f", d, 0x04, p["x"], p.get("y", 0), p["z"], p.get("vx", 0), 0, p.get("vz", 0))
    s("<f", d, 0x20, p.get("rot_y", 0)); s("<f", d, 0x30, p.get("yawrate", 0))
    s("<2f", d, 0x38, 0.1, p["rpm"])
    s("<I", d, 0x40, p["pid"] & 0xFFFFFFFF)
    s("<7f", d, 0x44, p["fuel"], 100.0, p["speed"], 1.0, 5.0, 85.0, 110.0)
    s("<4f", d, 0x60, *p["tt"])
    s("<ihhii", d, 0x70, p["pid"], p["lap"], p.get("total_laps", 0), p.get("best_ms", -1), p.get("last_ms", -1))
    s("<hhhH", d, 0x88, 8200, 9000, 250, p.get("flags", F_ON_TRACK | F_IN_GEAR))
    d[0x90] = p["gear"] | (15 << 4); d[0x91] = int(p["thr"] * 255); d[0x92] = int(p["brk"] * 255)
    s("<4f", d, 0xA4, *[-w / 0.35 for w in p["ws"]]); s("<4f", d, 0xB4, 0.35, 0.35, 0.35, 0.35)
    s("<4f", d, 0xC4, 0.24, 0.24, 0.22, 0.22)
    s("<f", d, 0x100, 2.837); s("<8f", d, 0x104, 3.082, 2.102, 1.546, 1.192, 0.962, 0.814, 0, 0)
    s("<i", d, 0x124, p.get("car", 3265))
    iv1 = p["pid"] & 0xFFFFFFFF
    enc = bytearray(salsa20(KEY, struct.pack("<II", iv1 ^ mask, iv1), bytes(d)))
    enc[0x40:0x44] = struct.pack("<I", iv1)      # the IV travels in clear
    return bytes(enc)
