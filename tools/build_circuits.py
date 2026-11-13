#!/usr/bin/env python3
"""Builds data/circuits.json, the outlines the copilot names a track from.

Source: the circuit inventory of zetetos/gt-telemetry (MIT, (c) 2024 vwhitteron): one JSON per layout with the name, the
length and the 16 m grid cells the racing surface passes through, in the game's own coordinates, in lap order.

    git clone https://github.com/zetetos/gt-telemetry /some/dir
    python3 tools/build_circuits.py /some/dir

Only names, lengths and cells are taken. Cells are stored in grid units (metres / 16), x then z, to keep the file small."""
import glob, json, os, sys

GRID = 16
src = os.path.join(sys.argv[1], "pkg", "circuits", "inventory")
out = []
for f in sorted(glob.glob(os.path.join(src, "*.json"))):
    d = json.load(open(f, encoding="utf-8"))
    cells, seen = [], set()
    for c in d["coordinates"]:
        k = (int(c["x"]) // GRID if c["x"] >= 0 else -(-int(c["x"]) // GRID), int(c["z"]) // GRID if c["z"] >= 0 else -(-int(c["z"]) // GRID))
        if k not in seen:                                 # the height is dropped: the same square twice is one cell
            seen.add(k); cells.append(k)
    out.append(dict(id=d["id"], name=d.get("variation") or d["name"], base=d["name"], length=d["length"], cells=cells))
if len(out) < 50:
    sys.exit(f"only {len(out)} circuits found under {src}: not written")
dest = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "circuits.json")
with open(dest, "w", encoding="utf-8") as f:
    json.dump(dict(grid=GRID, source="zetetos/gt-telemetry (MIT, (c) 2024 vwhitteron)", circuits=out), f, ensure_ascii=False, separators=(",", ":"))
print(f"{len(out)} circuits, {sum(len(c['cells']) for c in out)} cells -> {dest} ({os.path.getsize(dest) // 1024} KB)")
