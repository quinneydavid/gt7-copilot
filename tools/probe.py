#!/usr/bin/env python3
"""GT7 telemetry probe: heartbeat the PS5, decrypt and print/record packets.
usage: tools/probe.py --ps5 IP [--ps5 IP] [--seconds N] [--out file.bin] [--hb A|B|~]"""
import argparse, socket, struct, time, sys

KEY = b"Simulator Interface Packet GT7 ver 0.0"[:32]
XOR = {"A": 0xDEADBEAF, "B": 0xDEADBEEF, "~": 0x55FABB4F}
M = 0xFFFFFFFF
def _rotl(v, n): return ((v << n) & M) | (v >> (32 - n))
def _qr(s, a, b, c, d):
    s[b] ^= _rotl((s[a] + s[d]) & M, 7); s[c] ^= _rotl((s[b] + s[a]) & M, 9)
    s[d] ^= _rotl((s[c] + s[b]) & M, 13); s[a] ^= _rotl((s[d] + s[c]) & M, 18)
def salsa20(key, nonce, data):
    k = struct.unpack("<8I", key); n = struct.unpack("<2I", nonce); out = bytearray()
    for blk in range((len(data) + 63) // 64):
        st = [0x61707865, k[0], k[1], k[2], k[3], 0x3320646E, n[0], n[1], blk & M, blk >> 32,
              0x79622D32, k[4], k[5], k[6], k[7], 0x6B206574]
        s = st[:]
        for _ in range(10):
            _qr(s, 0, 4, 8, 12); _qr(s, 5, 9, 13, 1); _qr(s, 10, 14, 2, 6); _qr(s, 15, 3, 7, 11)
            _qr(s, 0, 1, 2, 3); _qr(s, 5, 6, 7, 4); _qr(s, 10, 11, 8, 9); _qr(s, 15, 12, 13, 14)
        ks = struct.pack("<16I", *[(s[i] + st[i]) & M for i in range(16)])
        chunk = data[blk * 64:(blk + 1) * 64]
        out += bytes(a ^ b for a, b in zip(chunk, ks))
    return bytes(out)
def decrypt(pkt, hb="A"):
    iv1 = struct.unpack_from("<I", pkt, 0x40)[0]; iv2 = iv1 ^ XOR[hb]
    d = salsa20(KEY, struct.pack("<II", iv2, iv1), pkt)
    return d if struct.unpack_from("<I", d, 0)[0] == 0x47375330 else None
def parse(d):
    f = lambda o, n=1: struct.unpack_from("<%df" % n, d, o)
    flags = struct.unpack_from("<H", d, 0x8E)[0]; g = d[0x90]
    return dict(pos=f(0x04, 3), rpm=f(0x3C)[0], fuel=f(0x44)[0], fuel_cap=f(0x48)[0], kmh=f(0x4C)[0] * 3.6,
        boost=f(0x50)[0] - 1, water=f(0x58)[0], oil=f(0x5C)[0], tyre_temp=f(0x60, 4),
        pkt_id=struct.unpack_from("<i", d, 0x70)[0], lap=struct.unpack_from("<h", d, 0x74)[0],
        total_laps=struct.unpack_from("<h", d, 0x76)[0], best_ms=struct.unpack_from("<i", d, 0x78)[0],
        last_ms=struct.unpack_from("<i", d, 0x7C)[0], rpm_alert=struct.unpack_from("<2h", d, 0x88),
        flags=flags, on_track=bool(flags & 1), paused=bool(flags & 2), loading=bool(flags & 4),
        rev_limit=bool(flags & 32), asm=bool(flags & 1024), tcs=bool(flags & 2048),
        gear=g & 15, suggested=g >> 4, throttle=d[0x91], brake=d[0x92], wheel_rps=f(0xA4, 4),
        tyre_radius=f(0xB4, 4), susp=f(0xC4, 4), top_speed_ratio=f(0x100)[0], gear_ratios=f(0x104, 8),
        car_code=struct.unpack_from("<i", d, 0x124)[0])
if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--ps5", required=True)
    ap.add_argument("--seconds", type=float, default=6); ap.add_argument("--out"); ap.add_argument("--hb", default="A")
    a = ap.parse_args()
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.bind(("0.0.0.0", 33740)); s.settimeout(1)
    out = open(a.out, "ab") if a.out else None
    t0 = time.time(); last_hb = 0; n = bad = 0; sizes = {}; last = None
    while time.time() - t0 < a.seconds:
        if time.time() - last_hb > 1.5:
            s.sendto(a.hb.encode(), (a.ps5, 33739)); last_hb = time.time()
        try: pkt, addr = s.recvfrom(4096)
        except socket.timeout: continue
        sizes[len(pkt)] = sizes.get(len(pkt), 0) + 1
        d = decrypt(pkt, a.hb)
        if not d: bad += 1; continue
        n += 1; last = d
        if out: out.write(struct.pack("<dH", time.time(), len(d)) + d)
    print(f"packets ok={n} bad={bad} sizes={sizes} in {a.seconds}s")
    if last:
        for k, v in parse(last).items(): print(f"  {k}: {v}")
