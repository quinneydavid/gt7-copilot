"""Naming a track from where the car drives. The game sends no track name, but its coordinates are fixed per track, so a
driven line can be laid over known outlines (data/circuits.json, built by tools/build_circuits.py from the circuit
inventory of zetetos/gt-telemetry, MIT). An outline is the set of 16 m squares the racing surface passes through.

  on     share of the driven points that lie on the outline (their square or a neighbouring one)
  cover  share of the outline's squares the driven line passed (a short layout lies ON a longer one, but does not cover it)

A full lap is named when one outline fits both ways and has the lap's length. Part of a lap gives a guess as soon as every
outline that still fits belongs to one track. The direction is read from the order of the squares, so a lap driven against
the outline's order is the reverse layout."""
import functools, json, os

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ON_MIN, COVER_MIN, LENGTH_TOL = 0.88, 0.85, 0.09      # an outline can have a gap (Suzuka East: 200 m); lengths in the data are up to 6 % off the game's
GUESS_AFTER = 500.0           # metres driven before a guess is offered
NEAR = [(dx, dz) for dx in (-1, 0, 1) for dz in (-1, 0, 1)]


@functools.lru_cache(None)
def load():
    try:
        d = json.load(open(os.path.join(BASE, "data", "circuits.json"), encoding="utf-8"))
    except (OSError, ValueError):
        return 16, []
    out = []
    for c in d["circuits"]:
        cells = [tuple(k) for k in c["cells"]]
        out.append(dict(c, cells=cells, set=frozenset(cells), order={k: i for i, k in enumerate(cells)}))
    return d.get("grid", 16), out


def _cell(v, grid):
    return int(v / grid)                                  # towards zero, as the source data was made


def _scores(points, grid, circuits):
    """points: [(x, z)] in metres, in driving order -> [(circuit, on, cover, direction)]"""
    lap = [(_cell(x, grid), _cell(z, grid)) for x, z in points]
    lapset = set(lap)
    out = []
    for c in circuits:
        hit = [next(((kx + dx, kz + dz) for dx, dz in NEAR if (kx + dx, kz + dz) in c["set"]), None) for kx, kz in lap]
        on = sum(h is not None for h in hit) / len(lap)
        if on < 0.5:
            continue
        cover = sum(any((kx + dx, kz + dz) in lapset for dx, dz in NEAR) for kx, kz in c["cells"]) / len(c["cells"])
        n, fwd, back = len(c["cells"]), 0, 0              # which way round: do the outline's squares come up in its order?
        idx = [c["order"][h] for h in hit if h is not None]
        for a, b in zip(idx, idx[1:]):
            step = (b - a + n // 2) % n - n // 2
            fwd += step > 0; back += step < 0
        out.append((c, on, cover, 1 if fwd >= back else -1))
    return out


def _named(c, direction):
    return c["name"] + (" (Reverse)" if direction < 0 and "lockwise" not in c["name"] else "")


def name_lap(points, length):
    """A full lap -> dict(name, id, reverse, on, cover) or None when no outline fits it both ways with its length."""
    grid, circuits = load()
    if not circuits or len(points) < 20:
        return None
    fits = [(c, on, cover, d) for c, on, cover, d in _scores(points, grid, circuits)
            if on >= ON_MIN and cover >= COVER_MIN and abs(c["length"] - length) <= LENGTH_TOL * c["length"]]
    if not fits:
        return None
    fits.sort(key=lambda f: (-(f[1] + f[2]), abs(f[0]["length"] - length)))
    c, on, cover, d = fits[0]
    if len(fits) > 1 and fits[1][1] + fits[1][2] > on + cover - 0.02 and abs(fits[1][0]["length"] - length) <= abs(c["length"] - length):
        c, on, cover, d = fits[1]                         # two outlines fit alike: the one with the nearer length
    return dict(name=_named(c, d), id=c["id"], reverse=d < 0 and "lockwise" not in c["name"], on=round(on, 3), cover=round(cover, 3))


def guess(points, driven):
    """Part of a lap (driven = metres so far) -> the track it can only be, as text, or None while several tracks still fit.
    The guess is the track without its layout: layouts share tarmac, so the layout is only certain when the lap is done."""
    grid, circuits = load()
    if not circuits or driven < GUESS_AFTER or len(points) < 10:
        return None
    fits = [(c, d) for c, on, cover, d in _scores(points, grid, circuits) if on >= 0.97]
    if not fits:
        return None
    bases = {c["base"] for c, _ in fits}                  # the layout is only certain at the line: a guess names the track
    return bases.pop() if len(bases) == 1 else None
