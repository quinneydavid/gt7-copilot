"""PS5 screenshots as input: fetch the newest capture from the PlayStation App (the grabber next to the virtual phone),
have the local vision model say what screen it is and read it, and act on it:
  car settings (either page)  -> file the settings sheet for the car
  event / race information    -> name the track, remember the event's rules (laps, fuel and tyre rates, tyres allowed)
  anything else               -> say what it is
The model only reads; what is filed is checked by code (limits, car match) first."""
import base64, copy, hashlib, json, re, time, urllib.error, urllib.request
from . import cli, knowledge as K, library as L, settings as CFG, sheet as S

PROMPT = """This is a screenshot from Gran Turismo 7. Say which screen it is and read it. Reply with ONE JSON object, no other text.

"screen" is one of:
 "car_settings_1"  the detailed Car Settings page with Tires, Suspension, Differential Gear, Aerodynamics, ECU, Performance Adjustment, Transmission, Nitrous/Overtake
 "car_settings_2"  the second Car Settings page with Supercharger, Intake & Exhaust, Brakes, Steering, Drivetrain, Engine Tuning, Bodywork
 "event"           race / event information (number of laps, track name, regulations)
 "other"           anything else

Always give "car": the car name shown (or null) and "summary": one short sentence saying what the screen shows.
On either Car Settings page also give "settings_sheet": the number in the "Settings Sheet N" title at the top (null if not shown).

For car_settings_1 also give "sheet" with exactly these keys (null when not shown). Pairs are [front, rear].
{"pp": number, "power": number, "power_unit": "HP" or "PS" or "kW" or "BHP", "weight": number, "weight_unit": "lbs" or "kg",
 "tyres": {"front": text, "rear": text},
 "suspension": {"ride_height_mm": [f, r], "anti_roll_bar": [f, r], "damping_compression_pct": [f, r], "damping_expansion_pct": [f, r],
                "natural_frequency_hz": [f, r], "negative_camber_deg": [f, r], "toe_deg": [f, r], "toe_direction": ["in" or "out" or "none", same]},
 "differential": {"initial_torque": [f, r], "acceleration_sensitivity": [f, r], "braking_sensitivity": [f, r], "front_rear_torque_split": "45:55"},
 "aero": {"downforce": [f, r]}, "ecu_output_pct": number, "power_restrictor_pct": number, "ballast_kg": number, "ballast_position": number,
 "transmission": {"type": text, "top_speed": number, "top_speed_unit": "km/h" or "mph"},
 "hardware": {"suspension": text, "differential": text, "center_differential": text, "ecu": text, "nitrous": text, "nitrous_output_pct": text}}
Toe direction comes from the small icon left of the toe number: lines closer together at the top = "in", closer at the bottom = "out", parallel = "none".

For car_settings_2 give "sheet": {"brake_balance": number,
 "hardware": {"turbocharger": text, "anti_lag": text, "anti_lag_system": text, "intercooler": text, "supercharger": text, "air_cleaner": text,
  "muffler": text, "exhaust_manifold": text, "brake_system": text, "brake_pads": text, "handbrake": text, "handbrake_torque_pct": text,
  "brake_balance": text, "steering_angle_kit": text, "four_ws": text, "rear_steering_angle": text, "clutch_flywheel": text,
  "propeller_shaft": text, "bore_up": text, "stroke_up": text, "engine_balance": text, "polish_ports": text, "high_lift_cam": text,
  "titanium_rods_pistons": text, "racing_crank": text, "high_compression_pistons": text, "weight_reduction_1": text, "weight_reduction_2": text,
  "weight_reduction_3": text, "weight_reduction_4": text, "weight_reduction_5": text, "body_rigidity": text}}
"brake_balance" (number) is the Front/Rear Balance value; hardware "brake_balance" is the text beside Brake Balance. Write "--" where the screen shows --.

For event give "event": {"name": text, "track": text, "laps": number, "cars": number, "fuel_rate": number, "tyre_wear_rate": number,
 "tyres_allowed": [text], "category": text}. "track" is the full track and layout name as written on the screen."""


class GrabError(RuntimeError):
    """A fetch that failed; code = the fetcher's answer (404 = there is no capture at that place in the list)."""
    def __init__(self, msg, code=0): super().__init__(msg); self.code = code


def grab(index=1, mode=""):
    """mode "stay": the list in the app as it stands (the next capture of a batch). -> (jpeg bytes, capture id). Raises GrabError (a RuntimeError) with a sentence fit to be spoken."""
    why = CFG.why_not("phone")
    if why:
        raise RuntimeError(why)
    req = urllib.request.Request(f"{CFG.get('grab_url')}/grab?index={index}" + (f"&mode={mode}" if mode else ""), data=b"", headers={"X-GT7C-Grab": CFG.get("grab_token")}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=150) as r:
            return r.read(), r.headers.get("X-Capture-Id", "")
    except urllib.error.HTTPError as e:
        why = {423: "The virtual phone is locked. Unlock it first.", 404: "There is no screenshot in the PlayStation App.",
               409: "I am already fetching one.", 401: "The PlayStation App on the virtual phone is signed out.",
               504: "The PlayStation App was too slow. Try again."}.get(e.code)
        raise GrabError(why or f"The PlayStation App did not give me the screenshot. Error {e.code}.", e.code)
    except Exception as e:
        raise RuntimeError("I cannot reach the virtual phone.")


def mime(image):
    """The picture's type from its first bytes (PS5 captures are JPEG; phone photos and uploads may be PNG or WebP)."""
    if image[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if image[:4] == b"RIFF" and image[8:12] == b"WEBP":
        return "image/webp"
    if image[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    return None


def ask(content, max_tokens=1800, timeout=120):
    """One question to the vision model -> its text. Raises RuntimeError with a sentence fit to be spoken."""
    why = CFG.why_not("screenshots")
    if why:
        raise RuntimeError(why)
    body = dict(model=CFG.get("vision_model"), temperature=0, max_tokens=max_tokens, messages=[dict(role="user", content=content)])
    headers = {"Content-Type": "application/json"}
    if CFG.get("llm_key"):
        headers["Authorization"] = "Bearer " + CFG.get("llm_key")
    req = urllib.request.Request(CFG.get("llm_url") + "/chat/completions", data=json.dumps(body).encode(), headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)["choices"][0]["message"]["content"] or ""
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"The vision model answered with error {e.code}.")
    except (OSError, KeyError, IndexError, ValueError):
        raise RuntimeError("I cannot reach the vision model.")


def read(image):
    """What the vision model sees on the screenshot, as a dict (see PROMPT)."""
    kind = mime(image)
    if not kind:
        raise RuntimeError("That file is not a picture I can read. Use JPEG, PNG or WebP.")
    text = ask([dict(type="text", text=PROMPT),
                dict(type="image_url", image_url=dict(url=f"data:{kind};base64," + base64.b64encode(image).decode()))])
    m = re.search(r"\{.*\}", text, re.S)
    return json.loads(m.group(0)) if m else dict(screen="other", summary=text[:120])


def _num(x):
    try: return float(str(x).replace(",", "").strip())
    except (TypeError, ValueError): return None


def to_sheet(seen, base=None):
    """One or two read pages -> a sheet in the settings-sheet shape, on top of the previous sheet (base) for whatever was not captured."""
    sh = copy.deepcopy(base) if base else copy.deepcopy(S.TEMPLATE)
    sh.setdefault("hardware", {})
    for page in seen:
        src = page.get("sheet") or {}
        if page.get("screen") == "car_settings_1":
            sh["pp"] = _num(src.get("pp")) or sh.get("pp")
            p = _num(src.get("power"))
            if p:
                sh["power_hp"] = round(p * {"KW": 1.341, "PS": 0.9863}.get(str(src.get("power_unit", "")).upper(), 1.0))
            w = _num(src.get("weight"))
            if w:
                sh["weight_kg"] = round(w * 0.45359237) if str(src.get("weight_unit", "")).lower().startswith("lb") else round(w)
            ty = src.get("tyres") or {}
            sh["tyres"] = {e: (S.compound(ty.get(e)) or ty.get(e) or (sh.get("tyres") or {}).get(e)) and
                              (S.compound(ty.get(e)) or ty.get(e) or sh["tyres"].get(e)).replace(":", "") for e in S.ENDS}
            su = src.get("suspension") or {}
            for k in ("ride_height_mm", "anti_roll_bar", "damping_compression_pct", "damping_expansion_pct", "natural_frequency_hz", "negative_camber_deg"):
                v = su.get(k)
                if isinstance(v, list) and len(v) == 2 and all(_num(x) is not None for x in v):
                    sh["suspension"][k] = [_num(x) for x in v]
            toe, td = su.get("toe_deg"), su.get("toe_direction") or ["", ""]
            if isinstance(toe, list) and len(toe) == 2 and all(_num(x) is not None for x in toe):
                old = (sh["suspension"].get("toe_deg") or [None, None])
                out = []
                for i in range(2):
                    v = abs(_num(toe[i])); d = str(td[i] if i < len(td) else "").lower()
                    if old[i] is not None and abs(abs(old[i]) - v) < 0.005:
                        out.append(old[i])                               # same size as before: keep the direction on file
                    else:
                        out.append(-v if d == "out" else v)
                sh["suspension"]["toe_deg"] = out
            di = src.get("differential") or {}
            for k in ("initial_torque", "acceleration_sensitivity", "braking_sensitivity"):
                v = di.get(k)
                if isinstance(v, list) and len(v) == 2:                 # a value the reader left out keeps what is on file
                    # 0 is what the game shows at an end without a driven axle (the front of a rear-driven car): no value there
                    was = sh["differential"].get(k) or [None, None]
                    sh["differential"][k] = [None if _num(x) == 0 else _num(x) if _num(x) is not None else was[n] for n, x in enumerate(v)]
            sp = re.sub(r"\s", "", str(di.get("front_rear_torque_split") or ""))
            if re.fullmatch(r"\d{1,3}:\d{1,3}", sp):
                sh["differential"]["front_rear_torque_split"] = sp
            df = (src.get("aero") or {}).get("downforce")
            if isinstance(df, list) and len(df) == 2:
                was = sh["aero"].get("downforce") or [None, None]
                sh["aero"]["downforce"] = [_num(x) if _num(x) is not None else was[n] for n, x in enumerate(df)]
            for k in ("ecu_output_pct", "power_restrictor_pct", "ballast_kg", "ballast_position"):
                if _num(src.get(k)) is not None:
                    sh[k] = _num(src[k])
            tr = src.get("transmission") or {}
            if tr.get("type"):
                sh["transmission"]["type"] = tr["type"]
            ts = _num(tr.get("top_speed"))
            if ts:
                sh["transmission"]["top_speed_kmh"] = round(ts * 1.609344) if str(tr.get("top_speed_unit", "")).lower() == "mph" else round(ts)
        if page.get("screen") == "car_settings_2" and _num(src.get("brake_balance")) is not None:
            sh["brake_balance"] = _num(src["brake_balance"])
        for k, v in (src.get("hardware") or {}).items():
            if k in S.HARDWARE_KEYS and v not in (None, ""):
                sh["hardware"][k] = str(v)
    for path in ("suspension", "differential"):                           # whole numbers stay whole
        for k, v in sh[path].items():
            if isinstance(v, list):
                sh[path][k] = [int(x) if isinstance(x, float) and x.is_integer() else x for x in v]
    for k in ("pp", "ecu_output_pct", "power_restrictor_pct", "ballast_kg", "ballast_position", "brake_balance"):
        if isinstance(sh.get(k), float) and sh[k].is_integer():
            sh[k] = int(sh[k])
    if isinstance((sh.get("aero") or {}).get("downforce"), list):
        sh["aero"]["downforce"] = [int(x) if isinstance(x, float) and x.is_integer() else x for x in sh["aero"]["downforce"]]
    return sh


def _same_car(shown, code):
    a = set(re.findall(r"[a-z0-9]+", (shown or "").lower())); b = set(re.findall(r"[a-z0-9]+", cli.car_name(code).lower()))
    return len(a & b) >= max(1, min(len(a), len(b)) - 1)


def digest(image):
    """A fingerprint of the picture itself. For a JPEG the notes in front of the picture (EXIF and the like) are left out:
    the PlayStation App writes the time of the download there, so the same capture differs in those bytes every time."""
    if image[:2] == b"\xff\xd8":
        i, keep = 2, [b"\xff\xd8"]
        try:
            while i + 4 <= len(image) and image[i] == 0xFF:
                marker, size = image[i + 1], int.from_bytes(image[i + 2:i + 4], "big")
                if marker == 0xDA:                                        # start of scan: the picture data runs to the end
                    keep.append(image[i:]); i = len(image); break
                if not (0xE0 <= marker <= 0xEF or marker == 0xFE):        # APPn and comments are the notes
                    keep.append(image[i:i + 2 + size])
                i += 2 + size
            if i >= len(image):
                return hashlib.sha1(b"".join(keep)).hexdigest()
        except (IndexError, ValueError):
            pass
    return hashlib.sha1(image).hexdigest()


def known(store, cid, image):
    """Was this capture read before? Told by the picture itself: the PlayStation App names a download after the time of
    the download, so its name says nothing. Pictures kept before fingerprints existed get theirs here, once."""
    for r in store.q("SELECT id, mime FROM shots WHERE hash IS NULL OR hash NOT LIKE 'p:%'"):
        try:
            with open(store.shot_path(r["id"], r["mime"]), "rb") as f:
                store.x("UPDATE shots SET hash=? WHERE id=?", "p:" + digest(f.read()), r["id"])
        except OSError:
            store.x("UPDATE shots SET hash=? WHERE id=?", "p:", r["id"])
    return bool(store.q("SELECT id FROM shots WHERE hash=? LIMIT 1", "p:" + digest(image)))


def match_car(shown, hint=None):
    """The car a screen names -> its code, or None when the name fits no car or several equally well.
    hint: a car that wins when the name fits it (the car on track)."""
    if not shown:
        return hint
    if hint and _same_car(shown, hint):
        return hint
    tok = lambda t: set(re.findall(r"[a-z0-9]+", (t or "").lower()))
    a = tok(shown); best = []
    for c in K._specs().values():
        b = tok(c["name"]); both = len(a & b)
        if both and both >= min(len(a), len(b)) - 1:
            best.append((both - 0.01 * len(a ^ b), c["code"]))
    best.sort(reverse=True)
    if not best or (len(best) > 1 and best[0][0] - best[1][0] < 0.005):
        return None
    return best[0][1]


def open_doubts(tune):
    """The values still to confirm on a filed sheet (list of dicts, see sheet.doubts)."""
    try: return json.loads((tune or {}).get("doubts") or "[]")
    except ValueError: return []


def slot_of(seen):
    """The game's settings sheet number the pages show ("Settings Sheet 2" -> 2), or None when no page says."""
    for p in seen:
        n = _num(p.get("settings_sheet"))
        if n and 1 <= n <= 20:
            return int(n)
    return None


def _neighbour_slot(pages, n, car):
    """The sheet number for a settings page that does not show one: that of the nearest numbered settings page of the same
    car, the one captured just before it first (page 1, then the arrow to page 2), else the one just after."""
    for k in list(range(n - 1, -1, -1)) + list(range(n + 1, len(pages))):
        q = pages[k]
        if q.get("slot") and q.get("car") == car:
            return q["slot"]
    return None


def _base(store, car, slot):
    """The sheet a new read builds on: the newest one of the same game settings sheet (page 2 of sheet 1 never mixes into
    sheet 2), or the newest of any when the screenshot does not say which sheet it is."""
    if slot:
        r = store.q("SELECT * FROM tunes WHERE car=? AND slot=? ORDER BY id DESC LIMIT 1", car, slot)
        if r:
            r[0]["sheet"] = json.loads(r[0]["sheet"]); return r[0]
        if store.q("SELECT 1 FROM tunes WHERE car=? AND slot IS NOT NULL AND slot<>? LIMIT 1", car, slot):
            return None                                                   # another sheet is on file: this one starts fresh
    return L.current_tune(store, car)


def file_sheet(col, store, car, seen, note, log=print, shots=None):
    """Pages read for one car (oldest first) -> its sheet filed. -> the sentence to say.
    A value outside the usual range does not stop the filing: it is filed, flagged, and named in the sentence so the driver
    can confirm or correct it on the car page. Raises RuntimeError only when nothing at all could be read."""
    slot = slot_of(seen)
    prev = _base(store, car, slot)
    on_car = L.current_tune(store, car)
    fresh = to_sheet(seen)                                                # only what this read saw
    if S.blank(fresh):
        log("sheet not filed: nothing read")
        raise RuntimeError("I could not read any settings on that picture.")
    sheet = to_sheet(seen, prev and prev["sheet"])
    was = open_doubts(prev); was_paths = {d["path"] for d in was}
    old = S.flat(prev["sheet"]) if prev else {}
    now = S.flat(fresh)
    doubts = [d for d in S.doubts(fresh)                                  # a value confirmed before and read the same again is fine
              if not (d["path"] in old and old[d["path"]] == d["value"] and d["path"] not in was_paths)]
    doubts += [d for d in was if d["path"] not in now]                    # flags on settings this read did not see stay
    filed = S.flat(sheet)                                                 # what is filed must say what the screenshot says
    for path, v in now.items():
        if path in filed and path != "parts" and not S._same(filed[path], v) and path not in {d["path"] for d in doubts}:
            base, end = path.rsplit(".", 1) if path.rsplit(".", 1)[-1] in S.ENDS else (path, None)
            game = S.game_label(base, end)
            text = (f"{game}: the screenshot shows {'out' if v < 0 else 'in'}, the sheet keeps {'out' if filed[path] < 0 else 'in'}"
                    if base == "suspension.toe_deg" else f"{game}: the screenshot shows {v}, the sheet has {filed[path]}")
            doubts.append(dict(path=path, value=filed[path], read=v, lo=None, hi=None, game=game, text=text))
    if doubts:
        log(f"sheet filed with values to check: {[d['text'] for d in doubts]}")
    check = (" Please check: " + "; ".join(d["text"] for d in doubts) + ". Confirm or correct it on the car page.") if doubts else ""
    gone = S.pages_missing(sheet)
    if gone:
        check += f" {S.PAGE_NAMES[gone[0]].split(' (')[0].capitalize()} of the settings is not on file yet: take a screenshot of it too." if len(gone) == 1 else ""
    name = cli.car_name(car) + (f" (Settings Sheet {slot})" if slot else "")
    switched = bool(on_car and prev and on_car["id"] != prev["id"])      # the newest screenshot shows another sheet than the one on file
    if prev and not switched and not S.diff(prev["sheet"], sheet) and [d["path"] for d in doubts] == [d["path"] for d in was]:
        return f"Same sheet as before for the {name}. Nothing changed." + check
    changes = S.diff(prev["sheet"], sheet) if prev else []
    store.x("INSERT INTO tunes(car,created,source,sheet,note,library_id,doubts,shots,slot) VALUES(?,?,?,?,?,?,?,?,?)", car, time.time(), "screenshot",
            json.dumps(sheet), note, L.link_for_sheet(store, car, sheet), json.dumps(doubts) if doubts else None,
            json.dumps([i for i in (shots or []) if i]) or None, slot)
    if (on_car and on_car.get("slot") and slot and on_car["slot"] != slot) or (not prev and on_car):
        check = f" This is now the sheet on the car (your newest screenshot)." + check
    if col is not None and col.car == car:
        col.tune = L.current_tune(store, car)
    if not prev:
        return f"Sheet filed for the {name}." + check
    said = "; ".join(f"{c['setting'].replace(' › ', ' ')}, {c['mine']} to {c['theirs']}" for c in changes[:3] if c["setting"] != "parts")
    return f"Sheet filed for the {name}. {len(changes)} {'change' if len(changes) == 1 else 'changes'}" + (f": {said}." if said else ".") + check


def check_values(col, store, car, values):
    """The driver confirmed or corrected flagged values on the car page. values = {flat path: number}. A new sheet is filed
    with them (source "checked"); the flags on those settings are cleared. -> dict(ok, reply)."""
    prev = L.current_tune(store, car)
    if not prev:
        raise ValueError("No settings sheet on file for this car.")
    sheet = copy.deepcopy(prev["sheet"]); left = open_doubts(prev); fixed = []
    for path, v in (values or {}).items():
        n = _num(v)
        if n is None:
            raise ValueError(f"{path}: type a number.")
        n = int(n) if n.is_integer() else n
        if path not in S.flat(sheet) and path not in {d["path"] for d in left}:
            raise ValueError(f"{path} is not on the sheet.")
        S.set_value(sheet, path, n); fixed.append(path)
    left = [d for d in left if d["path"] not in fixed]
    store.x("INSERT INTO tunes(car,created,source,sheet,note,library_id,doubts,shots,slot) VALUES(?,?,?,?,?,?,?,?,?)", car, time.time(), "checked",
            json.dumps(sheet), "values checked on the car page", L.link_for_sheet(store, car, sheet), json.dumps(left) if left else None, prev.get("shots"), prev.get("slot"))
    if col is not None and getattr(col, "car", None) == car:
        col.tune = L.current_tune(store, car)
    changed = [c for c in S.diff(prev["sheet"], sheet)]
    return dict(ok=True, reply=f"Saved. {len(fixed)} {'value' if len(fixed) == 1 else 'values'} checked" +
                (f", {len(changed)} corrected." if changed else ", all as read.") + (f" {len(left)} still to check." if left else ""))


def reread(col, store, shot_id, log=print):
    """Read a kept picture again and file what it shows (after a reader or limit fix, or from the car page). -> the sentence."""
    r = store.q("SELECT * FROM shots WHERE id=?", int(shot_id))
    if not r:
        raise RuntimeError("That screenshot is no longer kept.")
    r = r[0]
    with open(store.shot_path(r["id"], r["mime"] or "image/jpeg"), "rb") as f:
        image = f.read()
    seen = read(image); kind = seen.get("screen")
    store.x("UPDATE shots SET kind=?, summary=? WHERE id=?", kind, (seen.get("summary") or seen.get("car") or "")[:500] or None, r["id"])
    log(f"shot {r['id']} read again: {kind}: {seen.get('summary')}")
    try:
        if kind in ("car_settings_1", "car_settings_2"):
            car = r["car"] or match_car(seen.get("car") or "", col.car if col is not None else None)
            if not car:
                raise RuntimeError(f"I read a settings sheet for the {seen.get('car') or 'car'}, but I do not know which car that is.")
            out = file_sheet(col, store, car, [seen], f"read again from screenshot {r['id']}", log, [r["id"]])
            store.x("UPDATE shots SET ok=1, reply=?, car=? WHERE id=?", out, car, r["id"])
            return out
        if kind == "event":
            out = note_event(col, store, seen.get("event") or {})
        else:
            raise RuntimeError("That is not a settings or event screen. " + (seen.get("summary") or ""))
    except RuntimeError as e:
        store.x("UPDATE shots SET ok=0, reply=? WHERE id=?", str(e), r["id"])
        raise
    store.x("UPDATE shots SET ok=1, reply=? WHERE id=?", out, r["id"])
    return out


def note_event(col, store, ev):
    """An event screen that was read -> remembered, and the track named if it had no name. -> the sentence to say."""
    store.x("CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, seen REAL, track_id INTEGER, data TEXT)")
    tid = col.track["id"] if col.track else None
    store.x("INSERT INTO events(seen,track_id,data) VALUES(?,?,?)", time.time(), tid, json.dumps(ev))
    bits = [ev.get("name"), ev.get("track")] + ([f"{int(ev['laps'])} laps"] if _num(ev.get("laps")) else [])
    if _num(ev.get("fuel_rate")): bits.append(f"fuel times {int(_num(ev['fuel_rate']))}")
    if _num(ev.get("tyre_wear_rate")): bits.append(f"tyre wear times {int(_num(ev['tyre_wear_rate']))}")
    named = ""
    if ev.get("track") and col.track and (not col.track.get("name") or col.track.get("name_src") == "outline") and col.track.get("name") != ev["track"]:
        store.x("UPDATE tracks SET name=?, name_src='screen' WHERE id=?", ev["track"], col.track["id"])   # the screen's name beats the outline's
        col.track["name"] = ev["track"]; col.track["name_src"] = "screen"
        named = " I have named this track."
    return "Event noted. " + ". ".join(str(b) for b in bits if b) + "." + named


BATCH = 15                # captures looked at in one go


def take_new(col, store, log=print, back=False, limit=BATCH, progress=None):
    """Read every capture in the PlayStation App that was not read before, newest first, and file what they show: one
    sheet per car (both pages when both were captured), events noted. Stops at the first capture already read;
    back=True looks through the whole list instead and reads the ones that were skipped earlier.
    -> dict(ok, reply, shots=[ids], read, cars=[codes]). Raises RuntimeError when the first fetch fails."""
    tell = progress or (lambda text: None)
    pages, last, stopped = [], None, None
    for i in range(1, limit + 1):
        tell(f"Fetching capture {i} from the PlayStation App." + (f" {len(pages)} new so far." if pages else ""))
        try:
            jpeg, cid = grab(i, "" if i == 1 else "stay")
        except GrabError as e:
            if i == 1 and e.code != 404:
                raise
            if e.code != 404:
                stopped = str(e)
            break
        fp = digest(jpeg)
        if fp == last:                                                    # the list has no more: the fetcher gave the last one again
            break
        last = fp
        if known(store, cid, jpeg):
            if back:
                continue
            break
        tell(f"Reading capture {i}." + (f" {len(pages)} new so far." if pages else ""))
        try:
            seen = read(jpeg)
        except RuntimeError as e:
            if not pages:
                raise
            stopped = str(e); break
        log(f"capture {cid}: {seen.get('screen')}: {seen.get('summary')}")
        sid = keep(store, jpeg, seen, str(cid), None)
        pages.append(dict(seen=seen, sid=sid, cid=cid))
    if not pages:
        return dict(ok=True, reply="No new screenshots in the PlayStation App." + (" " + stopped if stopped else ""), shots=[], read=0, cars=[])
    pages.reverse()                                                       # oldest first: the newest page of a kind wins
    mark = lambda ids, ok, reply, car=None: [store.x("UPDATE shots SET ok=?, reply=?, car=IFNULL(?, car) WHERE id=?", int(ok), reply, car, i) for i in ids if i]
    groups, said, cars, failed = {}, [], [], 0
    for p in pages:
        if p["seen"].get("screen") in ("car_settings_1", "car_settings_2"):
            p["car"] = match_car(p["seen"].get("car") or "", col.car); p["slot"] = slot_of([p["seen"]])
    for n, p in enumerate(pages):
        kind = p["seen"].get("screen")
        if kind in ("car_settings_1", "car_settings_2"):
            shown = p["seen"].get("car") or ""; car = p["car"]
            slot = p["slot"] or _neighbour_slot(pages, n, car)            # a page without a number joins the sheet shot just before it
            if slot and not p["slot"]:
                p["seen"]["settings_sheet"] = slot
            g = groups.setdefault((car or ("?" + shown.lower()), slot), dict(car=car, shown=shown, pages=[]))
            g["pages"].append(p); g["last"] = n                            # filed in order of their newest capture: the newest sheet ends on the car
        elif kind == "event":
            try:
                r = note_event(col, store, p["seen"].get("event") or {}); mark([p["sid"]], True, r, col.car)
                said.append(r)
            except Exception as e:
                log(f"event not noted: {e!r}"); mark([p["sid"]], False, "The event could not be noted."); failed += 1
        else:
            mark([p["sid"]], False, "Not a settings or event screen. " + (p["seen"].get("summary") or ""))
    for g in sorted(groups.values(), key=lambda g: g["last"]):
        ids = [p["sid"] for p in g["pages"]]
        if not g["car"]:
            r = f"I read a settings sheet for the {g['shown'] or 'car'}, but I do not know which car that is."
            mark(ids, False, r); said.append(r); failed += 1; continue
        try:
            n = len({p["seen"].get("screen") for p in g["pages"]})
            r = file_sheet(col, store, g["car"], [p["seen"] for p in g["pages"]],
                           "read from PS5 capture" + ("s " if len(ids) > 1 else " ") + ", ".join(str(p["cid"]) for p in g["pages"]) + (" (2 pages)" if n == 2 else ""), log, ids)
            mark(ids, True, r, g["car"]); cars.append(g["car"]); said.append(r)
        except RuntimeError as e:
            mark(ids, False, str(e), g["car"]); said.append(f"{cli.car_name(g['car'])}: {e}"); failed += 1
    n = len(pages)
    head = f"Read {n} new screenshot{'' if n == 1 else 's'}. "
    if not said:
        said = ["None of them is a settings or event screen."]
    return dict(ok=failed == 0 or bool(cars), reply=head + " ".join(said) + (" Then I stopped: " + stopped if stopped else ""),
                shots=[p["sid"] for p in pages if p["sid"]], read=n, cars=cars)


def keep(store, image, seen, source, kept, car=None):
    """Keep a picture that was read, with what was seen on it, for the Screenshots page. Never worth failing a read over."""
    try:
        sid = store.save_shot(image, mime(image) or "image/jpeg", seen.get("screen"), seen.get("summary") or seen.get("car"), source, car)
        try: store.x("UPDATE shots SET hash=? WHERE id=?", "p:" + digest(image), sid)
        except Exception: pass
        if kept is not None:
            kept.append(sid)
        return sid
    except Exception:
        return None


def take(col, store, log=print, image=None, kept=None):
    """Read a screenshot and act on it. image = an uploaded picture; without one the newest capture is fetched through the
    virtual phone. -> the sentence to say. Raises RuntimeError (with a sentence) when a part is off or cannot be reached.
    kept: a list that receives the ids of the pictures stored for the Screenshots page."""
    if image is not None:
        jpeg, cid = image, "upload"
    else:
        jpeg, cid = grab(1)
    first = read(jpeg); kind = first.get("screen")
    log(f"capture {cid}: {kind}: {first.get('summary')}")
    mine = []; keep(store, jpeg, first, str(cid), mine, col.car if kind == "event" else None)
    if kept is not None:
        kept.extend(mine)
    if kind in ("car_settings_1", "car_settings_2"):
        seen = [first]
        try:                                                              # the other page, if it is the capture just before
            if image is not None:
                raise RuntimeError("uploads are read one page at a time")
            j2, c2 = grab(2); second = read(j2)
            other = "car_settings_2" if kind == "car_settings_1" else "car_settings_1"
            if second.get("screen") == other and (second.get("car") or "") == (first.get("car") or "") \
                    and (not slot_of([first]) or not slot_of([second]) or slot_of([first]) == slot_of([second])):
                seen.append(second); log(f"capture {c2}: {other} of the same car, used too"); keep(store, j2, second, str(c2), mine if kept is None else kept)
        except Exception as e:
            log(f"second capture not used: {e}")
        car = col.car or (store.q("SELECT car FROM sessions ORDER BY id DESC LIMIT 1") or [{}])[0].get("car")
        shown = first.get("car")
        if not car or (shown and not _same_car(shown, car)):
            found = cli.car_find(shown) if shown else []
            if len(found) == 1:
                car = found[0]["code"] if isinstance(found[0], dict) else found[0]
            elif not car:
                raise RuntimeError(f"I read a settings sheet for the {shown or 'car'}, but I do not know which car that is.")
            else:
                raise RuntimeError(f"That sheet is for the {shown}, not the car I last saw. I did not file it.")
        try:
            ids = (mine if kept is None else kept)
            store.x(f"UPDATE shots SET car=? WHERE id IN ({','.join('?' * len(ids))})", car, *ids) if ids else None
        except Exception:
            pass
        return file_sheet(col, store, car, seen, ("read from an uploaded picture" if image is not None else f"read from PS5 capture {cid}") + (" (2 pages)" if len(seen) == 2 else ""), log, list(mine if kept is None else kept))
    if kind == "event":
        return note_event(col, store, first.get("event") or {})
    raise RuntimeError("That is not a settings or event screen. " + (first.get("summary") or ""))
