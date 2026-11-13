"""Ask: a question in plain words, answered by the configured model from the driver's own laps and settings.

The model gets facts worked out by the app (the same figures the pages show), never the database and never the raw
telemetry:
  driving     totals, the cars and tracks driven, the best lap in each car on each track
  cars        for the car on the page, cars named in the question, or the last one driven: its figures, the settings on
              it, what the laps say to change (with numbers), what earlier changes did, tunes on file
  tracks      for the track on the page or named in the question: the cars ranked, where the time goes by corner
  session     the session on the page, or the latest: laps, consistency, the costliest corners, how the car behaved
  guides      sourced tuning statements about the settings the question names
  live        what the car is doing now, when it is on track
It is told to answer only from those facts and to say what is missing when they do not cover the question.
Nothing is stored: the question, the answer and the last few turns live in the browser and in one request."""
import json, re, threading, time, urllib.error, urllib.request
from . import api, knowledge as K, library as L, settings as CFG
from .cli import car_name, debrief
from .store import Store

BUSY = threading.Lock()                # one question at a time: the model is shared with the screenshot reader
MAX_FACTS = 24_000                     # characters of facts sent with a question
EXAMPLES = ["What should I change on the car next?", "Where am I losing the most time?", "Which car have I driven the most?",
            "How consistent was my last session?", "What does the rear anti-roll bar do?"]
PROMPT = """You are the race engineer inside one driver's Gran Turismo 7 telemetry app. Today is {today}.

Rules:
- Use ONLY the facts in the JSON below. They come from the driver's own laps, settings sheets and filed tuning guides.
  Never use knowledge of your own about cars, tracks, settings values or lap times.
- If the facts do not answer the question, say what is missing in one sentence (for example: no settings sheet on file
  for that car, or fewer than three timed laps). Do not guess.
- For car changes, name the setting as the game does, with the value now and the value to try, and say why in a few
  words. Take them from "suggested_changes" first. One change at a time: say which to try first.
- "guides" are general statements from tuning guides, each with its source: use them to explain what a setting does,
  and say that they are general.
- Lap times as m:ss.mmm, speeds in km/h, gaps in seconds.
- Be short: at most 130 words, plain sentences, no headings, no lists, no tables, no markdown.

FACTS:
{facts}
{history}
QUESTION: {question}"""

RADIO = """You are "Copilot", the voice in one driver's ear in their Gran Turismo 7 sim rig: their race engineer, and good
company. Your answer is spoken aloud. It is {now}.

How to answer:
- One or two short sentences, at most 30 words. Spoken language: no lists, no symbols, no markdown. Answer what was
  asked and stop. Asked the time, say only the time.
- Be warm and natural, like a friend on the radio. Small talk, jokes and questions that have nothing to do with racing
  are welcome: just answer them. Never tell the driver to focus or concentrate, and never refuse a harmless question.
- Your name is Copilot. Speech-to-text may write it Co-pilot, Coppola, Go pilot or Pilot: that is you being addressed.
- About this car, its settings, the laps, fuel, tyres or the track: use ONLY the FACTS below ("now" is the car at this
  moment). If they do not cover it, say in a few words what is missing. Never invent a number.
- You cannot see the weather, rain, other cars, race positions, damage, tyre wear or flags. Asked about one of these, say
  that you cannot see it from the telemetry. Never make it up.
- When the driver TELLS you something (it is raining, I got hit, the tyres are gone, a plan), believe it, acknowledge it
  in a few words and add one practical tip. Rain: brake earlier, be gentle on the throttle, wet or intermediate tyres at
  the next stop. "told_by_driver" in the facts is what they told you earlier: keep it in mind.
- "fuel_verdict" in "now" is worked out by the app from the laps: for any fuel question, say what it says, in your own
  words. Do not do fuel arithmetic of your own.
- Reading "now": tyre temperatures under 60 are cold, 60 to 100 are fine, over 100 are hot. "fuel_needed_per_lap_to_finish"
  against "fuel_per_lap" says how much has to be saved; a lean fuel map and lifting early save up to about a quarter per lap.
- Only when the words are clearly not meant for you (noise, half a sentence, talk to someone else in the room), answer
  with exactly the one word NOTHING. When unsure, answer.

FACTS:
{facts}
{history}
DRIVER: {question}"""

# words in a question -> the part of a settings path the guide rows are filed under
SETTING_WORDS = {"camber": "negative_camber", "toe": "toe", "anti-roll": "anti_roll_bar", "anti roll": "anti_roll_bar", "roll bar": "anti_roll_bar",
                 "arb": "anti_roll_bar", "damping": "damping", "damper": "damping", "frequency": "natural_frequency", "spring": "natural_frequency",
                 "ride height": "ride_height", "body height": "ride_height", "differential": "differential", "diff": "differential", "lsd": "differential",
                 "initial torque": "initial_torque", "downforce": "downforce", "aero": "aero", "wing": "aero", "brake balance": "brake_balance",
                 "gear": "transmission", "top speed": "transmission", "ballast": "ballast", "tyre": "tyres", "tire": "tyres"}


def why_not():
    """None when a question can be asked, else the sentence to show."""
    return CFG.why_not("ask")


SHOT = re.compile(r"\b(take|grab|fetch|get|read|capture)\b.{0,30}\b(screen ?shot|capture|settings screen|screen)\b|^\s*screen ?shot\s*$", re.I)


def wants_shot(question):
    """Is this a request to fetch and read the newest PS5 capture ("take a screenshot"), not a question?"""
    q = str(question or "").strip()
    return len(q) <= 80 and bool(SHOT.search(q)) and not re.match(r"\s*(how|why|what|when|where|can|could|does|do|is|are)\b", q, re.I)


def shot(inbox):
    """Fetch the newest PS5 capture through the virtual phone, read it and file it -> dict(answer, shots) or dict(error)."""
    why = why_not()
    if why:
        return dict(error=why)
    if inbox is None:
        return dict(error="Screenshot reading is not available.")
    out = inbox.submit(None, "phone", speak=False)
    if not out.get("ok") and not out.get("shots"):
        return dict(error=out.get("reply") or "The screenshot could not be fetched.")
    return dict(answer=out.get("reply") or "Done.", shots=out.get("shots") or [])


def _model(prompt, max_tokens=500, timeout=120):
    body = dict(model=CFG.get("ask_model") or CFG.get("vision_model"), temperature=0, max_tokens=max_tokens,
                messages=[dict(role="user", content=prompt)])
    headers = {"Content-Type": "application/json"}
    if CFG.get("llm_key"):
        headers["Authorization"] = "Bearer " + CFG.get("llm_key")
    req = urllib.request.Request(CFG.get("llm_url") + "/chat/completions", data=json.dumps(body).encode(), headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)["choices"][0]["message"]["content"] or ""


def _words(text):
    return set(re.findall(r"[a-z0-9]+", (text or "").lower()))


def _named(question, names):
    """Which of {id: name} the question names: every id whose name shares a telling word with it (a model name, a
    number, a place), ignoring words that most names share."""
    q = _words(question); out = []
    common = {"car", "the", "gr", "gt", "gt3", "gt4", "rally", "road", "race", "racing", "concept", "edition", "type", "sport", "track", "circuit",
              "big", "ring", "course", "international", "speedway", "raceway", "park", "of", "de", "la", "and", "by"}
    for key, name in names.items():
        tell = {w for w in _words(name) if w not in common and (len(w) >= 3 or w.isdigit())}
        if tell & q:
            out.append(key)
    return out


def _car(st, code, sid=None):
    c = api.car(code, sid); sg = c.get("suggested") or {}; adv = sg.get("advice") or {}
    mine = L.current_tune(st, code)
    sheet = None
    if mine:
        sheet = {k: v for k, v in mine["sheet"].items() if k not in ("hardware", "parts") and v not in (None, [], {})}
        fitted = {k: v for k, v in (mine["sheet"].get("hardware") or {}).items() if v and v != "--"}
        if fitted:
            sheet["fitted"] = fitted
    out = dict(car=c["name"], car_class=c.get("car_class"), drivetrain=c.get("drivetrain"), stock=dict(pp=c.get("pp_stock"), power_hp=c.get("power_hp"), weight_kg=c.get("weight_kg")),
               driven=dict(laps=c["laps"], sessions=len(c["sessions"]), km=c["km"], minutes=c["minutes"], last=c.get("last_driven")),
               best_laps=[dict(track=b["track"], best=b["best"], laps=b["laps"], set_on=b["set_on"]) for b in c["bests"]],
               settings_on_car=sheet and dict(saved=c["sheet"]["saved"], sheet=sheet, pairs_are="[front, rear]", toe="negative = out, positive = in"),
               settings_note=None if sheet else "No settings sheet on file for this car: a screenshot of the Car Settings screen files it.")
    if adv.get("ready"):
        out["suggested_changes"] = dict(
            worked_out_from=sg.get("based_on"), laps_were_before_the_sheet_on_file=bool(sg.get("sheet_newer")),
            change=[dict(setting=r["game_setting"], now=r["now"], to=r["to"], why=r.get("reason")) for r in adv.get("recommended") or []],
            problems=[dict(problem=i["problem"], evidence=i["evidence"],
                           alternatives=[dict(setting=f.get("game_setting") or f["setting"], now=f.get("now"), to=f.get("to"),
                                              direction=None if f.get("to") is not None else f.get("direction"), why=f.get("why"), needs_part=f.get("needs_part")) for f in i["fixes"][:4]],
                           likely_cause_on_sheet=[dict(setting=x.get("game_setting") or x["setting"], now=x["now"], why=x["why"]) for x in i.get("suspect_settings", [])[:3]])
                      for i in adv.get("items", [])],
            parts_to_fit_first=adv.get("parts") or None, notes=adv.get("notes") or None)
    else:
        out["suggested_changes"] = dict(none_yet=sg.get("note") or " ".join(adv.get("notes") or []) or "Needs three timed laps in one session.")
    ex = [dict(changed=e["changed"], one_setting_changed=e["clean_test"], outcome=e["outcome"]) for e in c.get("experiments") or [] if e.get("outcome")]
    if ex:
        out["what_earlier_changes_did"] = dict(reading="best_change_s below zero = faster after the change", changes=ex[-4:])
    if c.get("library"):
        out["tunes_on_file"] = [dict(title=t["title"], author=t.get("author"), status=t["status"], pp=t.get("pp"), tyres=t.get("tyres"), on_car=bool(t.get("on_car")),
                                     your_laps=t["results"], differs_from_your_sheet=(t.get("differs_from_your_sheet") or [])[:12]) for t in c["library"][:4]]
    return out


def _track(tid):
    t = api.track(tid)
    if t.get("error"):
        return None
    rec = t.get("recommended") or {}
    return dict(track=t["name"], length_m=t["length_m"], corners=t["corners"], laps=t["laps"], sessions=len(t["sessions"]),
                cars_ranked=[dict(car=c["name"], best=c["best"], gap_s=c["gap_s"], laps=c["laps"], tune=(c.get("tune") or {}).get("title")) for c in t["cars"][:8]],
                fastest_car=rec.get("car"), best_corners_added_up=rec.get("ideal_lap"),
                corners_in_fastest_car=[dict(turn=c["turn"], avg_loss_s=c["avg_loss_s"], most_often=max(c["main_causes"], key=c["main_causes"].get) if c.get("main_causes") else None,
                                             apex_kmh=c["reference"].get("min_speed"), brake_at_m=c["reference"].get("brake_s") or None, exit_kmh=c["reference"].get("exit_speed"))
                                        for c in sorted(rec.get("corners") or [], key=lambda c: c["turn"])],
                events_seen=t.get("events") or None)


def _session(st, sid):
    d = debrief(st, sid); beh = d.get("car_behaviour") or {}
    return dict(session=sid, started=d["started"], car=d["car"]["name"], track=(d.get("track") or {}).get("name"), best=d.get("best"),
                best_corners_added_up=d.get("ideal_lap"), consistency=d.get("consistency"), best_ever_in_this_car_here=d.get("all_time_best"),
                laps=[dict(lap=l["lap"], time=l["time"], standing_start=l["first_lap"] or None, fuel_used=l["fuel_used"]) for l in d["laps"][:40]],
                costliest_corners=[dict(turn=c["turn"], avg_loss_s=c["avg_loss_s"], worst_loss_s=c["worst_loss_s"], causes=c["main_causes"],
                                        wheelspin_s=c["wheelspin_s"] or None, lockup_s=c["lockup_s"] or None) for c in (d.get("corners") or [])[:5]],
                per_lap_averages=beh.get("per_lap_avg"), tyre_temps_last_lap=beh.get("tyre_avg_last_lap"))


def facts(question, where=None, live=None):
    """What the model is given. where: {car, track, session} of the page the question was asked on."""
    st = Store(); where = where or {}; out = {}
    ov = api.overview()
    out["driving"] = dict(totals=ov["totals"],
                          cars=[dict(car=c["name"], laps=c["laps"], km=c["km"], minutes=c["minutes"], sessions=c["sessions"], last_driven=c["last_driven"],
                                     car_class=c.get("car_class"), drivetrain=c.get("drivetrain"), settings_on_file=c["sheet_on_file"]) for c in ov["cars"]],
                          tracks=ov["tracks"], best_laps=[dict(car=r["car"], track=r["track"], best=r["best"], set_on=r["set_on"]) for r in ov["records"]],
                          latest_sessions=[dict(session=s["id"], started=s["started"], car=s["car"], track=s["track"], laps=s["laps"], best=s["best"]) for s in ov["recent"]])
    if not ov["totals"]["laps"]:
        out["driving"]["note"] = "No laps recorded yet."
    driven = {c["code"]: c["name"] for c in ov["cars"]}
    # which cars, tracks and session the question is about
    sid = _int(where.get("session")) or (ov["recent"][0]["id"] if ov["recent"] else None)
    se = st.q("SELECT car, track_id FROM sessions WHERE id=?", sid) if sid else []
    cars = [c for c in [_int(where.get("car"))] if c] + _named(question, driven)
    if not cars and se:
        cars = [se[0]["car"]]
    tracks = {t["id"]: t["name"] or "" for t in st.q("SELECT id, name FROM tracks")}
    tids = [t for t in [_int(where.get("track"))] if t] + _named(question, tracks)
    if not tids and se and se[0]["track_id"]:
        tids = [se[0]["track_id"]]
    try:
        out["cars"] = [_car(st, c, sid if se and se[0]["car"] == c and where.get("session") else None) for c in list(dict.fromkeys(cars))[:2]]
    except Exception as e:
        out["cars_note"] = f"The car figures could not be worked out ({type(e).__name__})."
    try:
        out["tracks"] = [t for t in (_track(t) for t in list(dict.fromkeys(tids))[:2] if t in tracks) if t]
    except Exception as e:
        out["tracks_note"] = f"The track figures could not be worked out ({type(e).__name__})."
    if sid and se:
        try:
            out["session"] = dict(_session(st, sid), which="the session on the page" if where.get("session") else "the latest session")
        except Exception as e:
            out["session_note"] = f"The session could not be worked out ({type(e).__name__})."
    q = question.lower(); parts = list(dict.fromkeys(v for k, v in SETTING_WORDS.items() if k in q))
    if parts:
        code = cars[0] if cars else None; rows = []
        for p in parts[:3]:
            rows += [dict(K.short(r), setting=r.get("setting"), end=r.get("end"), direction=r.get("direction")) for r in K.find(st, car=code, setting=p) if r["kind"] != "example"][:5]
        out["guides"] = dict(note="General statements from tuning guides, filtered for the car's layout. Not measured on this car.", rows=rows[:12])
    if live and live.get("live"):
        out["live"] = dict(on_track=True, car=car_name(live["car"]) if live.get("car") else None, track=(live.get("track") or {}).get("name"), lap=live.get("lap"),
                           total_laps=live.get("total_laps") or None, now=live.get("now"), laps_this_session=live.get("laps"))
    return out


def _int(v):
    try: return int(v)
    except (TypeError, ValueError): return None


def _shrink(f):
    """Keep the facts inside what the model can take: drop the bulkiest optional parts first."""
    blob = lambda: json.dumps(f, ensure_ascii=False, default=str, separators=(",", ":"))
    for drop in (lambda: [c.pop("tunes_on_file", None) for c in f.get("cars", [])], lambda: f.get("session", {}).pop("laps", None),
                 lambda: f.pop("guides", None), lambda: f.__setitem__("tracks", f.get("tracks", [])[:1]), lambda: f.__setitem__("cars", f.get("cars", [])[:1]),
                 lambda: f.pop("session", None)):
        if len(blob()) <= MAX_FACTS:
            break
        drop()
    return blob()[:MAX_FACTS * 2]


def _earlier(history):
    turns = []
    for t in (history or [])[-3:]:
        if isinstance(t, dict) and t.get("q") and t.get("a"):
            turns.append(f"Earlier question: {str(t['q'])[:400]}\nYour earlier answer: {str(t['a'])[:900]}")
    return ("\nEARLIER IN THIS CHAT (for context only; the facts above are newer):\n" + "\n".join(turns) + "\n") if turns else ""


def answer(question, history=None, where=None, live=None, model=None):
    """-> dict(answer) or dict(error). model: a stand-in for tests (prompt -> text)."""
    question = re.sub(r"\s+", " ", str(question or "")).strip()[:400]
    why = why_not()
    if why:
        return dict(error=why)
    if len(question) < 3:
        return dict(error="Type a question first.")
    if not BUSY.acquire(blocking=False):
        return dict(error="The last question is still being answered. Give it a moment.")
    try:
        prompt = PROMPT.format(today=time.strftime("%A %d %B %Y"), facts=_shrink(facts(question, where, live)), history=_earlier(history), question=question)
        text = re.sub(r"[*#`]+", "", (model or _model)(prompt) or "").strip()
        return dict(answer=text[:2500]) if text else dict(error="The model gave no answer. Try again.")
    except urllib.error.HTTPError as e:
        return dict(error=f"The model answered with error {e.code}. Check its address, key and name in Settings.")
    except (OSError, KeyError, IndexError, ValueError):
        return dict(error="The model did not answer. Try again in a minute.")
    finally:
        BUSY.release()


def radio(question, history=None, live=None, now=None, model=None):
    """A spoken question that is not one of the fixed commands -> a short answer to say, or None when there is nothing
    to say (the model judged it noise, is off, is busy or failed). history: [(question, answer)] of the last moments.
    now: what the car is doing at this moment (fuel, tyres, gap ...), added to the facts."""
    question = re.sub(r"\s+", " ", str(question or "")).strip()[:300]
    if why_not() or len(question) < 3 or not BUSY.acquire(blocking=False):
        return None
    try:
        where = dict(car=live.get("car"), track=(live.get("track") or {}).get("id")) if live and live.get("live") else None
        f = facts(question, where, live)                  # "this car", "this track" = the ones on track now
        if now:
            f["now"] = now
        f.get("driving", {}).pop("latest_sessions", None)
        hist = "".join(f"\nEARLIER, DRIVER: {q}\nEARLIER, YOU: {a}" for q, a in (history or [])[-3:])
        prompt = RADIO.format(now=time.strftime("%A %d %B %Y, ") + time.strftime("%I:%M %p").lstrip("0"), facts=_shrink(f), history=hist, question=question)
        text = re.sub(r"[*#`_]+", "", (model or (lambda p: _model(p, max_tokens=110, timeout=15)))(prompt) or "").strip()
        text = re.sub(r"\s+", " ", text)
        return None if not text or text.upper().strip(" .!") == "NOTHING" else text[:400]
    except Exception:
        return None
    finally:
        BUSY.release()


INTENTS = """  fuel            how much fuel, how many laps it lasts, whether it reaches the end (a read-out of the figures)
  fuel_map        which fuel map to run, lean or rich, whether to save fuel
  tyres           the tyre TEMPERATURES right now (only temperatures: hot, cold, how are the temps)
  best_lap        the best lap time
  last_lap        the last lap time
  gap             the gap to the driver's own best lap right now
  lap_count       which lap it is, how many laps are left
  losing_time     where, in which corners, the time is being lost
  car_advice      what to change on the car's settings (general: "what should I change")
  read_changes    read out every suggested settings change
  read_setting    the value of one named setting on the settings sheet; give "setting" and "end"
  track           which track this is, what is known about it
  says_fuel_map   the driver TELLS which fuel map they are on or switching to; give "map": "lean" or "rich"
  says_pit        the driver TELLS they will pit / box; give "lap" (the lap number at whose end they stop, worked out from
                  the current lap: this lap = current, next lap = current + 1; null when no lap is said) and "why": "fuel", "tyres" or "a stop"
  screenshot      the driver ORDERS a new PS5 screenshot to be fetched and read now
  screenshots_all the driver ORDERS all new screenshots to be read
  repeat          say the last call again
  quiet           stop the automatic calls (mute)
  talk            bring the automatic calls back (unmute)
  hello           a check that the copilot hears them (can you hear me, are you there, radio check)
  chat            anything else: a question about the driving, the car, a corner, the race, something the driver tells you
                  (rain, a spin, a hit, a change they made, how they feel), small talk, a general question. YOU answer it in "say".
  nothing         clearly not meant for the copilot: noise, half a sentence, talk to someone else in the room"""
SETTINGS_ENUM = ("initial_torque acceleration_sensitivity braking_sensitivity differential torque_split ride_height anti_roll_bar damping_compression "
                 "damping_expansion damping natural_frequency camber toe suspension downforce brake_balance ballast power_restrictor ecu top_speed").split()
ROUTE = """You are "Copilot", the voice in one driver's ear in their Gran Turismo 7 sim rig: their race engineer, and good
company. It is {now}. Decide what the driver means and reply with ONE JSON object, nothing else:

{{"intent": one of the names below, "say": text or null, "told": true or false,
  "setting": one of [{settings}] or null, "end": "front" or "rear" or null,
  "map": "lean" or "rich" or null, "lap": number or null, "why": "fuel" or "tyres" or "a stop" or null}}

Intents:
{intents}

Choosing:
- A read-out intent (fuel, tyres, best_lap, last_lap, gap, lap_count) is only for a plain request for that figure. A
  question that needs judgement or more than the figure ("are my tyres okay", "which tyres should I fit", "will the fuel
  last if I push") is "chat": answer it yourself from the FACTS.
- A question ABOUT screenshots ("did you get it", "what did it say") is "chat", not an order to take one.
- The driver telling you a setting they changed is "chat" with "told": true. "read_setting" is only a request to hear a value.
- Words like "tired", "top speed", "behind me", "talking" are ordinary words: judge the whole sentence, never one word.
- "What's the time" asks for the time of day: "chat". best_lap and last_lap are only for lap times.
- "What should I set the <setting> at / to", "what is the <setting>" name one setting: "read_setting".
- says_fuel_map only when the driver says lean or rich. "quiet" only when they ask you to stop talking; "too loud",
  "speak up", "talk less" are "chat" (you cannot change the volume or how often the calls come: say so).
- "told": true whenever the driver tells you a fact or a plan worth remembering for this session (it is raining, I spun,
  I changed the wing, I am tired).
- {addressed}

When the intent is "chat", "say" is your spoken answer:
- One or two short sentences, at most 30 words. Spoken language, no lists or symbols. Answer what was asked and stop.
- Warm and natural, like a friend on the radio. Small talk, jokes and off-topic questions are welcome: just answer them.
  Never tell the driver to focus, never refuse a harmless question.
- About this car, its settings, the laps, fuel, tyres or the track: use ONLY the FACTS ("now" is the car at this moment;
  "fuel_verdict" is the app's own answer on fuel: say what it says, do no fuel arithmetic of your own). If the facts do
  not cover it, say in a few words what is missing. Never invent a number.
- You cannot see the weather, rain, other cars, race positions, damage, tyre wear, flags or penalties. Asked about one,
  say you cannot see it from the telemetry. When the driver tells you about one, believe it, acknowledge it in a few
  words and add one practical tip (rain: brake earlier, gentle on the throttle, wet or intermediate tyres at the next
  stop). "told_by_driver" in the facts is what they told you earlier: keep it in mind.
- Tyre temperatures under 60 are cold, 60 to 100 are fine, over 100 are hot.
- You cannot set timers, play music or change anything in the game: say so briefly.
For every other intent "say" is null.

FACTS:
{facts}
{history}
DRIVER: {question}"""


def route(question, history=None, live=None, now=None, named=True, model=None):
    """What a spoken sentence means -> dict(intent, say, told, setting, end, map, lap, why), or None when the model is
    off, busy, fails or answers something that is not the JSON asked for (the caller then falls back to its rules)."""
    question = re.sub(r"\s+", " ", str(question or "")).strip()[:300]
    if why_not() or len(question) < 2 or not BUSY.acquire(blocking=False):
        return None
    try:
        where = dict(car=live.get("car"), track=(live.get("track") or {}).get("id")) if live and live.get("live") else None
        f = facts(question, where, live)
        if now:
            f["now"] = now
        f.get("driving", {}).pop("latest_sessions", None)
        hist = "".join(f"\nEARLIER, DRIVER: {q}\nEARLIER, YOU: {a}" for q, a in (history or [])[-3:])
        addressed = ("The driver said your name, so this is for you: never answer \"nothing\"." if named else
                     "The driver did NOT say your name. The microphone is open while they drive and also hears them talk to people and "
                     "pets in the room and to themselves. Without your name, only two things are for you: something about the car, the "
                     "driving, the race or the track (a question, or something they tell you), and a clear request to you. Everything "
                     "else is \"nothing\": greetings, thanks, affection (\"love you\"), exclamations (\"oh my god\", \"whoa, what are you "
                     "doing\"), household talk (\"dinner is ready\", doors, pets, names of people), half sentences. When in doubt: \"nothing\".")
        prompt = ROUTE.format(now=time.strftime("%A %d %B %Y, ") + time.strftime("%I:%M %p").lstrip("0"), settings=", ".join(SETTINGS_ENUM),
                              intents=INTENTS, addressed=addressed, facts=_shrink(f), history=hist, question=question)
        text = (model or (lambda p: _model(p, max_tokens=160, timeout=15)))(prompt) or ""
        m = re.search(r"\{.*\}", text, re.S)
        out = json.loads(m.group(0)) if m else None
        if not isinstance(out, dict) or not isinstance(out.get("intent"), str):
            return None
        out["intent"] = out["intent"].strip().lower()
        if isinstance(out.get("say"), str):
            out["say"] = re.sub(r"\s+", " ", re.sub(r"[*#`_]+", "", out["say"])).strip()[:400] or None
        return out
    except Exception:
        return None
    finally:
        BUSY.release()
