"""One shape for a GT7 settings sheet, so sheets from photos and from the tune library can be compared.
Pairs are [front, rear]. Toe: negative = out, positive = in. Leave anything not on the sheet as null."""

TEMPLATE = {
    "pp": None, "power_hp": None, "weight_kg": None,
    "tyres": {"front": None, "rear": None},
    "suspension": {"ride_height_mm": [None, None], "anti_roll_bar": [None, None], "damping_compression_pct": [None, None],
                   "damping_expansion_pct": [None, None], "natural_frequency_hz": [None, None],
                   "negative_camber_deg": [None, None], "toe_deg": [None, None]},
    "differential": {"initial_torque": [None, None], "acceleration_sensitivity": [None, None], "braking_sensitivity": [None, None],
                     "front_rear_torque_split": None},
    "aero": {"downforce": [None, None]},
    "ecu_output_pct": None, "power_restrictor_pct": None, "ballast_kg": None, "ballast_position": None,
    "transmission": {"type": None, "top_speed_kmh": None, "gears": [], "final_gear": None},
    "brake_balance": None,
    "parts": [],
    # What is fitted, in the game's words (the selectors on page 1 and the whole of page 2). "--" = cannot be fitted.
    "hardware": {},
}

# Limits that hold for every car in GT7 (anything outside is almost certainly a misread photo). Per-car limits are not checked.
LIMITS = {
    "suspension.anti_roll_bar": (1, 10), "suspension.damping_compression_pct": (20, 40), "suspension.damping_expansion_pct": (30, 50),
    "suspension.negative_camber_deg": (0, 6), "differential.initial_torque": (5, 60),
    "differential.acceleration_sensitivity": (5, 60), "differential.braking_sensitivity": (5, 60),
    "ecu_output_pct": (70, 100), "power_restrictor_pct": (70, 100), "ballast_kg": (0, 200), "ballast_position": (-50, 50),
    "brake_balance": (-5, 5),
}
ENDS = ("front", "rear")


def flat(sheet, prefix=""):
    """{'suspension': {'anti_roll_bar': [4, 6]}} -> {'suspension.anti_roll_bar.front': 4, '...rear': 6}. Nulls are dropped."""
    out = {}
    for k, v in (sheet or {}).items():
        p = f"{prefix}{k}"
        if isinstance(v, dict):
            out.update(flat(v, p + "."))
        elif isinstance(v, list) and p == "parts":
            out[p] = sorted(str(x) for x in v)
        elif isinstance(v, list) and p.endswith(".gears"):
            for i, g in enumerate(v):
                out[f"{p}.{i + 1}"] = g
        elif isinstance(v, list) and len(v) == 2:
            for end, x in zip(ENDS, v):
                if x is not None:
                    out[f"{p}.{end}"] = x
        elif v is not None and v != []:
            out[p] = v
    return out


# The words GT7 itself uses on the Car Settings screen (section, setting), so advice reads like the game.
GAME = {
    "tyres": ("Tires", "Front and Rear"),
    "suspension.ride_height_mm": ("Suspension", "Body Height Adjustment"), "suspension.anti_roll_bar": ("Suspension", "Anti-Roll Bar"),
    "suspension.damping_compression_pct": ("Suspension", "Damping Ratio (Compression)"),
    "suspension.damping_expansion_pct": ("Suspension", "Damping Ratio (Expansion)"),
    "suspension.natural_frequency_hz": ("Suspension", "Natural Frequency"),
    "suspension.negative_camber_deg": ("Suspension", "Negative Camber Angle"), "suspension.toe_deg": ("Suspension", "Toe Angle"),
    "differential.initial_torque": ("Differential Gear", "Initial Torque"),
    "differential.acceleration_sensitivity": ("Differential Gear", "Acceleration Sensitivity"),
    "differential.braking_sensitivity": ("Differential Gear", "Braking Sensitivity"),
    "differential.front_rear_torque_split": ("Differential Gear", "Front/Rear Torque Distribution"),
    "aero.downforce": ("Aerodynamics", "Downforce"), "ecu_output_pct": ("ECU", "Output Adjustment"),
    "power_restrictor_pct": ("Performance Adjustment", "Power Restrictor"), "ballast_kg": ("Performance Adjustment", "Ballast"),
    "ballast_position": ("Performance Adjustment", "Ballast Positioning"),
    "transmission.top_speed_kmh": ("Transmission", "Top Speed (Automatically Adjusted)"),
    "transmission.final_gear": ("Transmission", "Final Gear"), "brake_balance": ("Brakes", "Front/Rear Balance"),
}
# The part that has to be on the car before a setting can be changed, named as the settings screen shows it.
PART = {
    "suspension": "Fully Customized Suspension", "differential": "Fully Customized Differential",
    "differential.front_rear_torque_split": "Torque-Vectoring Center Differential", "aero": "a wing / aero parts (GT Auto)",
    "ecu_output_pct": "Full Control Computer", "power_restrictor_pct": "Power Restrictor", "ballast_kg": "Ballast",
    "transmission": "Fully Customizable: Racing transmission", "brake_balance": "Brake Controller",
}
COMPOUNDS = ["Comfort: Hard", "Comfort: Medium", "Comfort: Soft", "Sports: Hard", "Sports: Medium", "Sports: Soft",
             "Racing: Hard", "Racing: Medium", "Racing: Soft"]


# The Car Settings screen, in the game's order and on the game's two pages:
# (page, column, section, [(path, unit, front/rear pair?, label)]). hardware.* rows are the selectors (what is fitted).
HW = lambda key, label: (f"hardware.{key}", "", False, label)
LAYOUT = [
    (1, 0, "Tires", [("tyres", "", True, "")]),
    (1, 0, "Suspension", [HW("suspension", "Suspension"), ("suspension.ride_height_mm", "mm", True, None), ("suspension.anti_roll_bar", "Lv.", True, None),
                          ("suspension.damping_compression_pct", "%", True, None), ("suspension.damping_expansion_pct", "%", True, None),
                          ("suspension.natural_frequency_hz", "Hz", True, None), ("suspension.negative_camber_deg", "°", True, None),
                          ("suspension.toe_deg", "°", True, None)]),
    (1, 0, "Differential Gear", [HW("differential", "Differential"), ("differential.initial_torque", "Lv.", True, None),
                                 ("differential.acceleration_sensitivity", "Lv.", True, None), ("differential.braking_sensitivity", "Lv.", True, None),
                                 HW("center_differential", "Torque-Vectoring Center Differential"),
                                 ("differential.front_rear_torque_split", "", False, None)]),
    (1, 1, "Aerodynamics", [("aero.downforce", "Lv.", True, None)]),
    (1, 1, "ECU", [HW("ecu", "ECU"), ("ecu_output_pct", "%", False, None)]),
    (1, 1, "Performance Adjustment", [("ballast_kg", "kg", False, None), ("ballast_position", "", False, None), ("power_restrictor_pct", "%", False, None)]),
    (1, 1, "Transmission", [("transmission.type", "", False, "Transmission"), ("transmission.top_speed_kmh", "km/h", False, None)]),
    (1, 1, "Nitrous/Overtake", [HW("nitrous", "Nitrous/Overtake"), HW("nitrous_output_pct", "Output Adjustment")]),
    (2, 0, "Supercharger", [HW("turbocharger", "Turbocharger"), HW("anti_lag", "Anti-Lag"), HW("anti_lag_system", "Anti-Lag System"),
                            HW("intercooler", "Intercooler"), HW("supercharger", "Supercharger")]),
    (2, 0, "Intake & Exhaust", [HW("air_cleaner", "Air Cleaner"), HW("muffler", "Muffler"), HW("exhaust_manifold", "Exhaust Manifold")]),
    (2, 0, "Brakes", [HW("brake_system", "Brake System"), HW("brake_pads", "Brake Pads"), HW("handbrake", "Handbrake"),
                      HW("handbrake_torque_pct", "Handbrake Torque"), HW("brake_balance", "Brake Balance"), ("brake_balance", "", False, None)]),
    (2, 1, "Steering", [HW("steering_angle_kit", "Steering Angle Kit"), HW("four_ws", "4WS System"), HW("rear_steering_angle", "Rear Steering Angle")]),
    (2, 1, "Drivetrain", [HW("clutch_flywheel", "Clutch & Flywheel"), HW("propeller_shaft", "Propellor Shaft")]),
    (2, 1, "Engine Tuning", [HW("bore_up", "Bore Up"), HW("stroke_up", "Stroke Up"), HW("engine_balance", "Engine Balance Tuning"),
                             HW("polish_ports", "Polish Ports"), HW("high_lift_cam", "High Lift Cam Shaft"),
                             HW("titanium_rods_pistons", "Titanium Connecting Rods & Pistons"), HW("racing_crank", "Racing Crank Shaft"),
                             HW("high_compression_pistons", "High Compression Pistons")]),
    (2, 1, "Bodywork", [HW("weight_reduction_1", "Weight Reduction: Stage 1"), HW("weight_reduction_2", "Weight Reduction: Stage 2"),
                        HW("weight_reduction_3", "Weight Reduction: Stage 3"), HW("weight_reduction_4", "Weight Reduction: Stage 4"),
                        HW("weight_reduction_5", "Weight Reduction: Stage 5"), HW("body_rigidity", "Increase Body Rigidity")]),
]
HARDWARE_KEYS = [r[0].split(".", 1)[1] for _, _, _, rows in LAYOUT for r in rows if r[0].startswith("hardware.")]


def _show(path, v):
    if v is None:
        return None
    if path == "tyres":
        return compound(v) or str(v)
    if path == "suspension.toe_deg":
        return f"{'out' if v < 0 else 'in' if v > 0 else ''} {abs(v):.2f}".strip()
    if path in ("suspension.natural_frequency_hz",):
        return f"{v:.2f}"
    if path == "suspension.negative_camber_deg":
        return f"{v:.1f}"
    return str(int(v)) if isinstance(v, float) and v.is_integer() else str(v)


def view(sheet, changes=()):
    """The sheet laid out like the game's Car Settings screen (both pages), with proposed changes marked.
    changes: [{path, end, to, problem}]. -> [{page, col, section, rows: [{label, unit, cells: [{end, value, was, why}]}]}]"""
    ch = {(c["path"], c.get("end")): c for c in changes}
    out = []
    for page, col, section, rows in LAYOUT:
        rs = []
        for path, unit, pair, lab in rows:
            x = sheet
            for k in path.split("."):
                x = x.get(k) if isinstance(x, dict) else None
            if path == "tyres":
                vals = [(e, (x or {}).get(e)) for e in ENDS]
            elif pair:
                vals = list(zip(ENDS, x if isinstance(x, list) and len(x) == 2 else [None, None]))
            else:
                vals = [(None, x)]
            if all(v is None for _, v in vals):
                continue
            cells = []
            for end, v in vals:
                c = ch.get((path, end)) or (ch.get((path, None)) if path == "tyres" else None)
                cell = dict(end=end, value=_show(path, v))
                if c:
                    cell.update(value=_show(path, c["to"]), was=_show(path, v), why=c.get("problem"))
                cells.append(cell)
            rs.append(dict(label=lab if lab is not None else GAME[path][1], unit=unit, cells=cells))
        if rs:
            out.append(dict(page=page, col=col, section=section, rows=rs))
    return out


def game_label(path, end=None):
    """'suspension.anti_roll_bar', 'rear' -> 'Suspension: Anti-Roll Bar (Rear)'."""
    sec, name = GAME.get(path, (None, None))
    if not sec:
        return label(path) + (f" › {end}" if end else "")
    return f"{sec}: {name}" + (f" ({end.capitalize()})" if end else "")


def part_for(path):
    return PART.get(path) or PART.get(path.split(".")[0])


def compound(name):
    """'Racing Medium' / 'racing: medium' / 'RM' -> 'Racing: Medium' (None if it is not a dry compound)."""
    t = str(name or "").replace(":", " ").split()
    short = {"CH": 0, "CM": 1, "CS": 2, "SH": 3, "SM": 4, "SS": 5, "RH": 6, "RM": 7, "RS": 8}
    if len(t) == 1 and t[0].upper() in short:
        return COMPOUNDS[short[t[0].upper()]]
    for c in COMPOUNDS:
        if len(t) >= 2 and [w.lower() for w in c.replace(":", "").split()] == [t[0].lower(), t[1].lower()]:
            return c
    return None


def softer(name, steps=1):
    """One compound softer / harder (steps=-1) within the same family; None at the end of the family."""
    c = compound(name)
    if not c:
        return None
    i = COMPOUNDS.index(c); j = i + steps
    return COMPOUNDS[j] if 0 <= j < len(COMPOUNDS) and j // 3 == i // 3 else None


def label(path):
    return path.replace("_", " ").replace(".", " › ")


def problems(sheet):
    """Reasons to doubt a sheet (unknown sections, values outside what GT7 allows). Empty list = looks fine."""
    out = [f"unknown section '{k}'" for k in sheet if k not in TEMPLATE]
    out += [f"unknown hardware entry '{k}'" for k in (sheet.get("hardware") or {}) if k not in HARDWARE_KEYS]
    for path, v in flat(sheet).items():
        base = path.rsplit(".", 1)[0] if path.rsplit(".", 1)[-1] in ENDS else path
        if base in LIMITS and isinstance(v, (int, float)):
            lo, hi = LIMITS[base]
            if not lo <= v <= hi:
                out.append(f"{label(path)} = {v} is outside {lo} to {hi}")
    return out


def _same(a, b):
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(a - b) < 0.0051
    return str(a).strip().lower() == str(b).strip().lower()


def diff(mine, theirs):
    """Settings that differ between two sheets. Only settings present on both are compared, plus parts."""
    a, b = flat(mine), flat(theirs)
    out = [dict(setting=label(p), mine=a[p], theirs=b[p]) for p in a if p in b and p != "parts" and not _same(a[p], b[p])]
    pa, pb = set(a.get("parts", [])), set(b.get("parts", []))
    if pa and pb and pa != pb:
        out.append(dict(setting="parts", mine=sorted(pa - pb), theirs=sorted(pb - pa)))
    return out


def compared(mine, theirs):
    """How many settings the two sheets have in common (a diff of nothing over 3 settings proves little)."""
    a, b = flat(mine), flat(theirs)
    return sum(1 for p in a if p in b and p != "parts")


def gears_match(ratios, sheet):
    """Do the gear ratios the car reports over telemetry match this sheet's gearbox?"""
    g = [x for x in ((sheet or {}).get("transmission") or {}).get("gears") or [] if x]
    r = [x for x in ratios or [] if x]
    return len(g) >= 3 and len(g) == len(r) and all(abs(float(x) - float(y)) < 0.006 for x, y in zip(g, r))
