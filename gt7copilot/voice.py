"""Voice control: what the driver says into the earpiece microphone, turned into text by a Whisper service, matched
against a short list of commands by rule (no language model), answered through the copilot's voice.
Only sentences that start with the name are acted on, so rig noise and talk with other people are ignored."""
import json, os, re, threading, time, urllib.request, uuid
import difflib
from . import analysis as A, ask as ASK, capture as CAP, settings as CFG, speech as S, tuneadvice as TA



def name_pattern():
    """The wake name as a pattern, from the spellings in Settings (the name and the ways speech-to-text writes it)."""
    names = [n.strip().lower() for n in str(CFG.get("wake_names")).split(",") if n.strip()] or ["copilot"]
    if "copilot" in names:                               # how speech-to-text wrote it in a real race (12 Nov 2026)
        names += ["co pilot", "copilots", "co pilots", "go pilot", "go pilots", "no pilot", "no pilots", "coe pilot", "cool pilot", "call pilot",
                  "coppola", "hi pilot", "high pilot", "copy lot", "cope pilot", "kopilot", "co pilate", "copilate", "copilit", "cop pilot", "pilot"]
    lead = r"(?:(?:hey|ok|okay|right|alright|all right|so|and|um|uh|well|yo|now)\s+)*"       # "Right, copilot, ..."
    return lead + r"(?:" + "|".join(re.escape(n) for n in sorted(set(names), key=len, reverse=True)) + r")\b[,.!]?\s*"


ARTICLES = {"a", "an", "the", "my", "our", "your", "his", "her", "this", "that", "one", "any", "no", "i", "you", "we", "he", "she", "auto"}
FOLLOW_UP = 12.0           # seconds after the name was said (or an answer given) in which the name can be left out

NOT_THE_NAME = {"couple", "couples", "coupled", "copula", "cupola", "capital", "capable", "compiled", "complete", "completely", "people"}


def sounds_like_name(t):
    """Speech-to-text writes "Copilot" in many ways ("Coppola", "Kaupala", "Hi pilot", "Go pilot"). When the usual pattern
    does not fit, compare the sound: the consonants of the first word or two against those of "copilot" (c-p-l-t).
    -> the number of leading words that are the name (0 = it is not)."""
    names = [n.strip().lower() for n in str(CFG.get("wake_names")).split(",") if n.strip()] or ["copilot"]
    if "copilot" not in names:
        return 0
    words = t.split()
    bones = lambda w: re.sub(r"(.)\1+", r"\1", re.sub(r"[aeiouyh' ]", "", w.replace("k", "c").replace("q", "c").replace("ph", "f")))
    for n in (2, 1):
        if len(words) < n:
            continue
        w = " ".join(words[:n]); b = bones(w)
        if w in NOT_THE_NAME or len(w.replace(" ", "")) < 6:
            continue
        if n == 1 and b.startswith("cpl") and len(b) <= 5:                      # coppola, kaupala, copala, copilet
            return 1
        # "<short sound> pilot": hi pilot, go pilot, co pilot, cool pilot - but not "the pilot", "a pilot", "my pilot"
        if n == 2 and bones(words[1]).startswith("plt") and words[0] not in ARTICLES and bones(words[0]) in ("", "c", "g", "cl"):
            return 2
    return 0


def ensure_model(timeout=900):
    """The bundled speech-to-text container (speaches) starts without a model and does not fetch one by itself: ask it
    to download the model named on the Settings tab if it does not have it. -> True when a download was done.
    Other services have no such route; any refusal is left alone and shows up in the transcription itself."""
    base = CFG.get("whisper_url").split("/audio/")[0]
    model = CFG.get("whisper_model")
    headers = {"Authorization": "Bearer " + CFG.get("whisper_token")} if CFG.get("whisper_token") else {}
    try:
        with urllib.request.urlopen(urllib.request.Request(base + "/models", headers=headers), timeout=10) as r:
            if any(m.get("id") == model for m in json.load(r).get("data", [])):
                return False
        url = base + "/models/" + urllib.parse.quote(model)
        with urllib.request.urlopen(urllib.request.Request(url, data=b"", headers=headers, method="POST"), timeout=timeout):
            return True
    except Exception:
        return False


def transcribe(wav, _again=True):
    """WAV bytes -> text ('' when nothing was said). Raises when the service cannot be reached."""
    why = CFG.why_not("voice_control")
    if why:
        raise RuntimeError(why)
    b = uuid.uuid4().hex
    part = lambda name, value: f'--{b}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
    # Only the name, as a spelling hint ("Copilot", not "Coppola" or "Hi pilot"). Whole example sentences are left out
    # on purpose: speech-to-text tends to repeat its hint when it hears only noise, and that must not become a command.
    hint = ([n.strip() for n in str(CFG.get("wake_names")).split(",") if n.strip()] or ["Copilot"])[0].capitalize() + "."
    body = (part("model", CFG.get("whisper_model")) + part("language", "en") + part("prompt", hint)   # the hint steers how the name is written
            + f'--{b}\r\nContent-Disposition: form-data; name="file"; filename="say.wav"\r\nContent-Type: audio/wav\r\n\r\n'.encode()
            + wav + f"\r\n--{b}--\r\n".encode())
    headers = {"Content-Type": f"multipart/form-data; boundary={b}"}
    if CFG.get("whisper_token"):
        headers["Authorization"] = "Bearer " + CFG.get("whisper_token")
    req = urllib.request.Request(CFG.get("whisper_url"), data=body, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return (json.load(r).get("text") or "").strip()
    except urllib.error.HTTPError:
        if _again and ensure_model():                    # the service had no model yet: it has now, ask once more
            return transcribe(wav, _again=False)
        raise


# Settings a driver can ask for by name: (words that mean it, the sheet rows they cover). The first match wins, so the
# exact names come before the section names. The words are matched on text without punctuation ("anti-roll" = "anti roll").
ASKABLE = [
    (("initial torque", "initial"), ["differential.initial_torque"]),
    (("acceleration sensitivity", "accel sensitivity", "acceleration"), ["differential.acceleration_sensitivity"]),
    (("braking sensitivity", "brake sensitivity"), ["differential.braking_sensitivity"]),
    (("torque split", "torque distribution"), ["differential.front_rear_torque_split"]),
    (("differential", "diff", "lsd"), ["differential.initial_torque", "differential.acceleration_sensitivity", "differential.braking_sensitivity"]),
    (("ride height", "body height", "height"), ["suspension.ride_height_mm"]),
    (("anti roll", "roll bar", "sway bar", "arb"), ["suspension.anti_roll_bar"]),
    (("compression",), ["suspension.damping_compression_pct"]),
    (("expansion", "rebound", "extension"), ["suspension.damping_expansion_pct"]),
    (("damping", "damper", "dampers", "shocks"), ["suspension.damping_compression_pct", "suspension.damping_expansion_pct"]),
    (("natural frequency", "frequency", "spring", "springs"), ["suspension.natural_frequency_hz"]),
    (("camber",), ["suspension.negative_camber_deg"]),
    (("toe",), ["suspension.toe_deg"]),
    (("suspension",), ["suspension.ride_height_mm", "suspension.anti_roll_bar", "suspension.damping_compression_pct",
                       "suspension.damping_expansion_pct", "suspension.natural_frequency_hz", "suspension.negative_camber_deg", "suspension.toe_deg"]),
    (("downforce", "aero", "wing"), ["aero.downforce"]),
    (("brake balance", "brake bias", "braking balance"), ["brake_balance"]),
    (("ballast",), ["ballast_kg", "ballast_position"]),
    (("restrictor",), ["power_restrictor_pct"]),
    (("ecu", "output adjustment"), ["ecu_output_pct"]),
    (("top speed", "gearing", "transmission", "gear ratio", "gear ratios"), ["transmission.top_speed_kmh"]),
]


def asked_setting(q):
    """The sheet rows a question names, and the end it asks about ("front", "rear" or None for both). -> (paths, end) or None."""
    for words, paths in ASKABLE:
        if any(re.search(rf"\b{re.escape(w)}\b", q) for w in words):
            end = "rear" if re.search(r"\b(rear|back)\b", q) else "front" if re.search(r"\bfront\b", q) else None
            return paths, end
    return None


class Voice:
    def __init__(self, col, co, say, hub, log=print, store=None):
        self.col, self.co, self.say, self.hub, self.log, self.store = col, co, say, hub, log, store
        self.busy = False                          # a screenshot is being fetched and read
        self.inbox = None                          # set by the daemon: results are then kept for the page
        self.told = []                             # what the driver told the copilot this session: (when, words)
        self.open_until = 0.0                      # until then a sentence without the name is taken as a follow-up
        self.chat = []                             # the last spoken questions the model answered: (when, question, answer)
        self.job = dict(running=False, step="", result=None, at=0.0)      # "read the new screenshots": progress for the page

    def hear(self, wav):
        """One utterance from the earpiece. -> dict(heard, command, reply)."""
        why = CFG.why_not("voice_control")
        if why:
            return dict(heard=None, command=None, reply=None, error=why)
        text = transcribe(wav)
        out = self.handle(text)
        self.log(f"heard: {text!r} -> {out.get('command')}: {out.get('reply')}")
        self._speak(out)
        return out

    def _speak(self, out):
        """Say an answer. A model's answer goes sentence by sentence, so the first words come before the rest is made."""
        if not out.get("reply"):
            return
        parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+", out["reply"]) if p.strip()] if out.get("command") == "chat" else [out["reply"]]
        for p in parts:
            self.say(p, 25.0, "voice")

    def hear_text(self, text):
        """The same, from typed words (page, CLI, tests)."""
        out = self.handle(text)
        self.log(f"typed: {text!r} -> {out.get('command')}: {out.get('reply')}")
        self._speak(out)
        return out

    # What speech-to-text makes of noise, and words that are never a request on their own.
    NOISE = {"thank you", "thanks", "thank you very much", "thanks for watching", "bye", "bye bye", "peace", "yes", "yeah", "no", "okay", "ok",
             "you", "oh", "hmm", "uh", "so", "right", "i'm hungry", "one second", "that's it", "let's go", "come on", "nice", "hello",
             "thank you so much", "thanks a lot", "love you", "love you dude", "oh my god", "oh no", "wow", "what", "okay okay", "all right", "alright"}
    PLAIN = {"fuel", "fuel_map", "tyres", "best", "last", "gap", "lap", "advice", "corners", "track", "hello"}      # read-outs a longer question may only mention
    ONE_WORD = {"fuel", "tyres", "tires", "gap", "repeat", "quiet", "talk", "help", "screenshot", "screenshots"}
    ASKING = r"(what|what's|whats|how|how's|which|when|where|who|why|can|could|should|shall|do|does|did|is|are|am|will|would|tell|give|read|show|say|check|any)\b"

    def _own_voice(self, t):
        """Is this the copilot's own call coming back through the microphone? (same words as something it just said)"""
        now = time.time(); words = lambda x: re.sub(r"[^a-z0-9 ]+", " ", (x or "").lower()).split()
        for ev in reversed(self.hub.recent[-4:]):
            if ev.get("type") != "say" or now - ev.get("t", 0) > 20:
                continue
            said = words(ev.get("text"))
            if said and difflib.SequenceMatcher(None, " ".join(said), " ".join(words(t))).ratio() > 0.6:
                return True
            if now - ev.get("t", 0) < 0.4 * len(said) + 1.0 and set(words(t)) <= set(said):     # still in the air, and all its words
                return True
        return False

    def _context(self):
        """What the model is given beside the question: the app's state, the car at this moment, the last exchanges."""
        c = self.col
        live = c.state(); now = None
        if c.live and c.row is not None:
            from .packet import C
            o = self.co.outlook(c) or {}
            now = dict(lap=c.lap_no, total_laps=c.meta.get("total_laps") or None, fuel=round(float(c.row[C["fuel"]]), 1),
                       fuel_per_lap=o.get("per") and round(o["per"], 2), laps_of_fuel_left=o.get("left") and round(o["left"], 1),
                       laps_to_go_including_this=o.get("to_go"), fuel_needed_per_lap_to_finish=o.get("need") and round(o["need"], 2),
                       gap_to_best_lap_s=self.co.delta, driver_says_fuel_map=self.co.driver_map,
                       planned_pit_lap=self.co.pit_plan, fuel_verdict=self.co.fuel_advice(c), speed_kmh=round(float(c.row[C["speed"]]) * 3.6),
                       tyre_temps_c=dict(zip(("front_left", "front_right", "rear_left", "rear_right"), (round(float(c.row[C["tt_" + w]])) for w in ("fl", "fr", "rl", "rr")))),
                       best_lap_this_session=min((l["time_ms"] for l in c.session_laps if l["time_ms"] > 0), default=None),
                       automatic_calls="on" if self.co.enabled else "muted")
        told = [w for at, w in self.told if time.time() - at < 5400]
        if told:
            now = dict(now or {}, told_by_driver=told)
        hist = [(q, a) for at, q, a in self.chat if time.time() - at < 180]
        return live, now, hist

    def _chat(self, text):
        """Not one of the fixed commands: let the Ask model answer it in a sentence or two (None = nothing to say)."""
        try:
            live, now, hist = self._context()
            reply = ASK.radio(text, hist, live, now)
        except Exception as e:
            self.log(f"chat failed: {e!r}"); reply = None
        if reply:
            self.chat = (self.chat + [(time.time(), text, reply)])[-4:]
        return reply

    SETTING_PATHS = dict(
        initial_torque=["differential.initial_torque"], acceleration_sensitivity=["differential.acceleration_sensitivity"],
        braking_sensitivity=["differential.braking_sensitivity"], torque_split=["differential.front_rear_torque_split"],
        differential=["differential.initial_torque", "differential.acceleration_sensitivity", "differential.braking_sensitivity"],
        ride_height=["suspension.ride_height_mm"], anti_roll_bar=["suspension.anti_roll_bar"], damping_compression=["suspension.damping_compression_pct"],
        damping_expansion=["suspension.damping_expansion_pct"], damping=["suspension.damping_compression_pct", "suspension.damping_expansion_pct"],
        natural_frequency=["suspension.natural_frequency_hz"], camber=["suspension.negative_camber_deg"], toe=["suspension.toe_deg"],
        suspension=["suspension.ride_height_mm", "suspension.anti_roll_bar", "suspension.damping_compression_pct", "suspension.damping_expansion_pct",
                    "suspension.natural_frequency_hz", "suspension.negative_camber_deg", "suspension.toe_deg"],
        downforce=["aero.downforce"], brake_balance=["brake_balance"], ballast=["ballast_kg", "ballast_position"],
        power_restrictor=["power_restrictor_pct"], ecu=["ecu_output_pct"], top_speed=["transmission.top_speed_kmh"])

    def _routed(self, text, named):
        """Let the model say what the sentence means, then answer: the fixed read-outs give the figures, the model its own
        words for everything else. -> dict(heard, command, reply), or None when the model gave nothing usable (the
        caller then uses the keyword rules)."""
        c, co = self.col, self.co
        try:
            live, now, hist = self._context()
            r = ASK.route(text, hist, live, now, named)
        except Exception as e:
            self.log(f"route failed: {e!r}"); return None
        if not r:
            return None
        it = r.get("intent"); out = lambda command, reply: dict(heard=text, command=command, reply=reply)
        if r.get("told") and it not in ("nothing",):
            self.told = (self.told + [(time.time(), re.sub(r"\s+", " ", text or "").strip()[:160])])[-6:]
        if it == "nothing":
            return out(None, None)
        if it == "chat":                                 # the model chose to answer itself where the app has the exact answer
            ql = re.sub(r"[^a-z0-9' ]+", " ", (text or "").lower())
            asks = re.search(r"\b(what|what's|whats|which|where|read|tell me|should i|recommend\w*)\b", ql) and not re.search(r"\b(i|i've|i have|i just|we|we've)\s+(moved|changed|put|went|gone|raised|lowered|softened|stiffened)\b|\b(i've|i have|i just)\s+set\b", ql)
            if asks and re.search(r"\b(fuel (map|mix\w*)|lean or rich|rich or lean)\b", ql): it = "fuel_map"
            elif asks and re.search(r"\b(which corner|worst corner|where am i losing|where do i lose|losing (the )?most time)\b", ql): it = "losing_time"
            elif asks and re.match(r"\s*(?:\w+\W+){0,3}?(what|what's|whats|read|tell me)\b", ql) and asked_setting(ql) and not re.search(r"\b(do|does|mean|for|why|how)\b", ql):
                paths, end = asked_setting(ql)
                return out("setting", self._setting(paths, end))
        if it == "chat":
            if not r.get("say"):
                return None
            self.chat = (self.chat + [(time.time(), text, r["say"])])[-4:]
            return out("chat", r["say"])
        if it == "fuel": return out("fuel", self._fuel())
        if it == "fuel_map": return out("fuel_map", co.fuel_advice(c))
        if it == "tyres": return out("tyres", self._tyres())
        if it == "best_lap": return out("best", self._best())
        if it == "last_lap": return out("last", self._last_lap())
        if it == "gap": return out("gap", self._gap())
        if it == "lap_count": return out("lap", self._lap())
        if it == "losing_time": return out("corners", self._corners())
        if it == "car_advice": return out("advice", self._advice())
        if it == "read_changes": return out("advice", self._advice(every=True))
        if it == "read_setting" and r.get("setting") in self.SETTING_PATHS:
            return out("setting", self._setting(self.SETTING_PATHS[r["setting"]], r.get("end") if r.get("end") in ("front", "rear") else None))
        if it == "track": return out("track", self._track())
        if it == "says_fuel_map" and r.get("map") in ("lean", "rich"):
            return out("driver_map", co.driver_says_map(c, r["map"]))
        if it == "says_pit":
            if not c.live:
                return out("pit_plan", "No car on track.")
            lap = r.get("lap"); lap = int(lap) if isinstance(lap, (int, float)) and 0 < lap < 500 else None
            return out("pit_plan", co.driver_plans_pit(c, lap, r.get("why") if r.get("why") in ("fuel", "tyres") else "a stop"))
        if it == "screenshot": return out("captures", self.take())
        if it == "screenshots_all": return out("captures_new", self.read_new(speak=True)["reply"])
        if it == "repeat": return out("repeat", self._last() or "Nothing to repeat.")
        if it == "quiet":
            co.enabled = False; return out("quiet", "Quiet. Say copilot, talk, to bring me back.")
        if it == "talk":
            co.enabled = True; return out("talk", "Talking again.")
        if it == "hello": return out("hello", "Yes. I hear you.")
        return None

    # ---- words -> command ------------------------------------------------------------------------------------------
    def handle(self, text):
        t = re.sub(r"[^a-z0-9' ]+", " ", (text or "").lower()).strip()
        m = re.match(name_pattern(), t)
        like = 0 if m else sounds_like_name(t)           # "Kaupala, can you hear me"
        tail = None if (m or like) else re.search(r"[, ]\s*" + name_pattern().rstrip("*").rstrip("\\s") + r"$", t)     # "how's my speed, copilot"
        called = None
        if not (m or like or tail):                      # "Pollock, can you hear me": an unknown word, a comma, then a fixed command
            v = re.match(r"\s*([A-Za-z' ]{2,14}),\s*(.+)$", text or "")
            if v and len(v.group(1).split()) <= 2:
                rest = re.sub(r"[^a-z0-9' ]+", " ", v.group(2).lower()).strip()
                if rest and self._command(text, rest, dry=True) not in ("unknown", None):
                    called = rest
        named = bool(m) or like > 0 or bool(tail) or called is not None
        talking = time.time() < self.open_until          # the copilot has just answered: a follow-up needs no name
        if named or talking:
            self.open_until = time.time() + FOLLOW_UP
        if not named:                                    # no name: while driving (when Settings allow it) or in a conversation, and never noise
            if not ((self.col.live and CFG.get("voice_open_live")) or talking):
                return dict(heard=text, command=None, reply=None)       # not for me
            if t in self.NOISE or (len(t.split()) < 2 and t not in self.ONE_WORD) or self._own_voice(t):
                return dict(heard=text, command=None, reply=None)
            q = re.sub(r"^(?:(?:hey|ok|okay|right|alright|so|and|um|uh|well|now|please)\s+)+", "", t)      # "hey, what car ..."
        else:
            q = t[m.end():].strip() if m else t[:tail.start()].strip() if tail else called if called is not None else " ".join(t.split()[like:])
        # With a model, the model says what the sentence means (keyword rules kept guessing wrong: "I'm tired" is not a
        # tyre stop). One or two words ("fuel", "be quiet") stay with the rules: instant and unambiguous.
        if len(q.split()) > 2 and ASK.why_not() is None:
            routed = self._routed(text, named or talking)
            if routed is not None:
                if routed["command"] is None and named:
                    routed = dict(heard=text, command="unknown", reply="Say again?")
                return routed
        out = self._command(text, q)
        # A fixed command answers a short request ("fuel?", "how are the tyres"). A longer sentence that merely contains
        # one of its words ("which of my cars is fastest at Big Willow", "what tyres should I be on") is a question for the
        # model, when there is one; the model has the same figures in its facts.
        if out["command"] in self.PLAIN and len(q.split()) > 4 and ASK.why_not() is None:
            reply = self._chat(text)
            if reply:
                return dict(heard=text, command="chat", reply=reply)
        if out["command"] != "unknown":
            return out
        # Not a fixed command. With the name it was meant for the copilot; without it only a question or request counts.
        asking = len(q.split()) >= 3 and (re.match(self.ASKING, q) or "?" in (text or ""))
        if not named and not asking and not (talking and len(q.split()) >= 3):      # in a conversation a statement counts too
            return dict(heard=text, command=None, reply=None)
        if len(q.split()) >= 3 and not re.match(self.ASKING, q):     # it starts as a statement ("it is raining, what should I do"): kept for the session
            self.told = (self.told + [(time.time(), q)])[-6:]
        reply = self._chat(text)
        if reply:
            return dict(heard=text, command="chat", reply=reply)
        return out if named else dict(heard=text, command=None, reply=None)

    def _command(self, text, q, dry=False):
        """q (the words after the name) -> the answer of the fixed command it is, or command "unknown".
        dry=True: only which command it would be, nothing done or said (the commands that act are named, not run)."""
        if dry:
            hasd = lambda *w: any(re.search(rf"\b{x}", q) for x in w)
            if hasd("can you hear", "do you hear", "are you there", "radio check", "mic check", "are you listening"): return "hello"
            if hasd("fuel", "petrol", "tyre", "tire", "best lap", "last lap", "gap", "which lap", "what lap", "how many laps", "laps left",
                    "what should i change", "what to change", "screenshot", "repeat", "say again"): return "known"
            return "known" if asked_setting(q) or self._statement(q, hasd, dry=True) else "unknown"
        has = lambda *w: any(re.search(rf"\b{x}", q) for x in w)
        if not q:                                        # the name alone; at most one "Yes?" in twenty seconds, in case noise is heard as the name
            again = time.time() - getattr(self, "_hello_at", 0) < 20; self._hello_at = time.time()
            return dict(heard=text, command="hello", reply=None if again else "Yes?")
        if has("can you hear", "do you hear", "are you there", "you there", "hello", "testing", "radio check", "mic check", "is this working", "are you listening"):
            return dict(heard=text, command="hello", reply="Yes. I hear you.")
        if has("repeat", "say again", "say that again", "what did you say", "pardon"):
            return dict(heard=text, command="repeat", reply=self._last() or "Nothing to repeat.")
        short = len(q.split()) <= 4                      # "be quiet", "talk again" - not a sentence that happens to hold the word
        if (short and has("quiet", "mute", "silence")) or has("shut up", "stop talking", "be quiet", "stop the calls"):
            self.co.enabled = False
            return dict(heard=text, command="quiet", reply="Quiet. Say copilot, talk, to bring me back.")
        if not self.co.enabled and ((short and has("talk", "unmute", "speak")) or has("you can talk", "come back", "start talking", "talk again", "calls on")):
            self.co.enabled = True
            return dict(heard=text, command="talk", reply="Talking again.")
        said = self._statement(q, has)                                          # the driver telling the plan, not asking
        if said:
            return dict(heard=text, command=said[0], reply=said[1])
        if has("read") and has("setting", "sheet", "setup", "changes"):          # "read me the settings": every change, not the first four
            return dict(heard=text, command="advice", reply=self._advice(every=True))
        named = asked_setting(q)
        if named and not has("temp"):                                            # "what should I set the rear differential at"
            return dict(heard=text, command="setting", reply=self._setting(*named))
        if has("lean", "rich", "fuel mix", "fuel map", "fuel mixture", "mixture", "save fuel"):   # "recommended fuel mix", "should I go lean"
            return dict(heard=text, command="fuel_map", reply=self.co.fuel_advice(self.col))
        if has("fuel", "petrol", "gas"):
            return dict(heard=text, command="fuel", reply=self._fuel())
        if has("tyre", "tire", "tyres", "tires", "temps", "temperature"):
            return dict(heard=text, command="tyres", reply=self._tyres())
        if has("best", "fastest", "record"):
            return dict(heard=text, command="best", reply=self._best())
        if has("last lap", "previous lap", "how was that", "that lap"):
            return dict(heard=text, command="last", reply=self._last_lap())
        if has("gap", "delta", "how am i doing", "ahead", "behind"):
            return dict(heard=text, command="gap", reply=self._gap())
        if has("which lap", "what lap", "how many laps", "laps left", "laps to go", "lap"):
            return dict(heard=text, command="lap", reply=self._lap())
        if has("screenshots", "screen shots", "captures") or (has("screenshot", "screen shot", "capture") and has("all", "new", "every", "these", "those", "three", "two", "both")):
            return dict(heard=text, command="captures_new", reply=self.read_new(speak=True)["reply"])
        if has("screenshot", "screen shot", "capture", "new setup", "new settings", "new sheet", "read the screen", "look at the screen",
               "i changed", "changed the"):
            return dict(heard=text, command="captures", reply=self.take())
        if has("what should i change", "what to change", "setup", "settings", "advice", "change on the car", "change on this car"):
            return dict(heard=text, command="advice", reply=self._advice())
        if has("where am i losing", "where do i lose", "losing time", "worst corner", "which corner"):
            return dict(heard=text, command="corners", reply=self._corners())
        if has("how's the track", "how is the track", "hows the track", "which track", "what track", "what circuit", "which circuit", "about this track", "about the track", "where are we") or q in ("track", "the track"):
            return dict(heard=text, command="track", reply=self._track())
        if has("help", "what can you do", "commands"):
            return dict(heard=text, command="help", reply="Ask me: fuel. Which fuel map. Tyres. Best lap. Last lap. Gap. Which lap. Where am I losing time. "
                                                         "What should I change. What is the rear differential. Read me the settings. Repeat. Quiet. Talk. Take a screenshot.")
        return dict(heard=text, command="unknown", reply="Say again?")

    NUMBERS = {w: n for n, w in enumerate("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen "
                                          "seventeen eighteen nineteen twenty".split())}

    def _statement(self, q, has, dry=False):
        """Things the driver tells the copilot: the fuel map they are on, the lap they will stop, that the race starts.
        -> (command, reply) or None when the sentence is a question or something else."""
        c, co = self.col, self.co
        asking = re.search(r"\b(should|recommend\w*|which|what|how|do i|shall|can i|could i|is it|or)\b", q)
        telling = re.search(r"\b(i'm|i am|im|i'll|i will|i ll|i'm going|gonna|going to|we're|we are|we will|we'll|staying|stay|let's|lets|i need|i have to|i plan|planning)\b", q)
        if dry:
            return bool(has("lean", "rich") or (telling and has("pit", "box", "refuel")))
        if has("lean", "rich") and not asking and (telling or re.search(r"\b(fuel|map|mix\w*) (is|on|set)\b", q) or len(q.split()) <= 3):
            which = "lean" if re.search(r"\blean", q) else "rich"
            return "driver_map", co.driver_says_map(c, which)
        if telling and not asking and has("pit", "box", "refuel", "fuel", "stop", "tyres", "tires", "tyre", "tire"):
            why = "tyres" if has("tyre", "tire") and not has("fuel", "refuel") else "fuel" if has("fuel", "refuel") else "a stop"
            total = c.meta.get("total_laps") or 0
            lap = None
            if has("last lap", "final lap"): lap = total or None
            elif has("next lap"): lap = (c.lap_no or 0) + 1
            elif has("this lap", "now"): lap = c.lap_no or None
            else:
                m = re.search(r"\bin (\w+) laps?\b", q)
                n = m and (int(m.group(1)) if m.group(1).isdigit() else self.NUMBERS.get(m.group(1)))
                if n is not None:
                    lap = (c.lap_no or 0) + n
                else:
                    m = re.search(r"\b(?:lap|on|that|at)\s+(?:lap\s+|that\s+)?(\d{1,2}|" + "|".join(self.NUMBERS) + r")\b", q)
                    lap = m and (int(m.group(1)) if m.group(1).isdigit() else self.NUMBERS[m.group(1)])
            if not c.live:
                return "pit_plan", "No car on track."
            return "pit_plan", co.driver_plans_pit(c, lap or None, why)
        if re.search(r"\b(let's race|lets race|let's go|start(ing)? (the )?rac\w*|going to (start )?rac\w*|we're racing|ready to race|race time|here we go)\b", q):
            tr = c.track or {}; total = c.meta.get("total_laps") or 0
            bits = ", ".join(b for b in [tr.get("name"), f"{S.words(total)} laps" if total else None] if b)
            return "start", "Copy. " + (bits[0].upper() + bits[1:] + ". " if bits else "") + "I am with you. Good luck."
        return None

    def _track(self):
        c = self.col; tr = c.track
        if not tr:
            return "I do not know this track yet. Finish a lap and I will have it." if c.live else "No car on track."
        said = (tr.get("name") or "A track without a name yet") + f". {S.one_dp(tr['length'] / 1000)} kilometres, {S.words(len(tr['corners']) if isinstance(tr.get('corners'), (list, tuple)) else int(tr.get('corners') or 0))} corners."
        if c.ref:
            said += f" Your best here in this car, {S.lap_time(c.ref['time_ms'])}."
        worst = self._corners() if self._clean() else ""
        return said + (" " + worst if worst.startswith("Most time") else "")

    def shot(self, image=None):
        """Read a screenshot and act on it, now. image = an uploaded picture; without one the newest PS5 capture is fetched
        through the virtual phone (about half a minute). -> dict(ok, reply)."""
        why = CFG.why_not("screenshots") or (None if image else CFG.why_not("phone"))
        if why:
            return dict(ok=False, reply=why)
        if self.busy:
            return dict(ok=False, reply="Still reading the last one.")
        self.busy = True; kept = []
        try:
            out = dict(ok=True, reply=CAP.take(self.col, self.store, self.log, image, kept))
        except RuntimeError as e:
            out = dict(ok=False, reply=str(e))
        except Exception as e:
            self.log(f"capture failed: {e!r}")
            out = dict(ok=False, reply="Something went wrong reading the screenshot.")
        finally:
            self.busy = False
        try:                                             # the result beside each kept picture (Screenshots page)
            if kept and self.store is not None:
                self.store.x(f"UPDATE shots SET ok=?, reply=? WHERE id IN ({','.join('?' * len(kept))})", int(out["ok"]), out["reply"], *kept)
                out["shots"] = kept
        except Exception:
            pass
        return out

    def read_new(self, back=False, speak=False):
        """Read every PS5 capture not read before, in the background (a quarter of a minute per capture). The page follows
        self.job; speak=True says the result when it is done. -> dict(ok, reply) about the start."""
        why = CFG.why_not("screenshots") or CFG.why_not("phone")
        if why:
            return dict(ok=False, reply=why)
        if self.busy:
            return dict(ok=False, reply="Still reading the last one.")
        self.busy = True
        self.job = dict(running=True, step="Opening the PlayStation App.", result=None, at=time.time())

        def run():
            try:
                out = CAP.take_new(self.col, self.store, self.log, back=back, progress=lambda text: self.job.update(step=text))
            except RuntimeError as e:
                out = dict(ok=False, reply=str(e), shots=[], read=0, cars=[])
            except Exception as e:
                self.log(f"reading the new captures failed: {e!r}")
                out = dict(ok=False, reply="Something went wrong reading the screenshots.", shots=[], read=0, cars=[])
            finally:
                self.busy = False
            try:
                if out.get("shots") and self.store is not None:
                    self.store.x(f"UPDATE shots SET route=? WHERE id IN ({','.join('?' * len(out['shots']))})", "virtual phone", *out["shots"])
                if self.inbox:
                    self.inbox.record("phone", out)
            except Exception:
                pass
            self.job = dict(running=False, step="", result=out, at=time.time())
            self.log(f"new captures: {out['reply']}")
            if speak:
                self.say(out["reply"], 120.0, "voice")
        threading.Thread(target=run, daemon=True).start()
        return dict(ok=True, reply="Reading the new screenshots. About a quarter of a minute each.")

    def take(self):
        """The spoken command: fetch the newest PS5 capture in the background and say the result."""
        why = CFG.why_not("screenshots") or CFG.why_not("phone")
        if why:
            return why
        if self.busy:
            return "Still reading the last one."
        fetch = (lambda: self.inbox.submit(None, "phone", speak=False)) if self.inbox else self.shot
        threading.Thread(target=lambda: self.say(fetch()["reply"], 60.0, "voice"), daemon=True).start()
        return "Fetching the screenshot. Give me half a minute."

    # ---- answers ---------------------------------------------------------------------------------------------------
    def _last(self):
        for ev in reversed(self.hub.recent):
            if ev.get("type") == "say" and ev.get("kind") not in ("voice", "test"):
                return ev["text"]
        return None

    def _clean(self):
        return [l for l in self.col.session_laps if not l.get("pit")]

    def _fuel(self):
        c = self.col
        if not c.live or c.row is None:
            return "No car on track."
        from .packet import C
        now = float(c.row[C["fuel"]])
        used = [l["fuel_start"] - l["fuel_end"] for l in self._clean()[-3:] if l["fuel_start"] - l["fuel_end"] > 0.05]
        if not used:
            return f"Fuel {S.words(now)}. No lap done yet, so no rate."
        per = sum(used) / len(used); left = now / per
        total = c.meta.get("total_laps") or 0
        msg = f"Fuel {S.words(now)}. Using {S.one_dp(per)} a lap. Good for {S.one_dp(left)} more laps."
        if total > 0 and c.lap_no:
            to_go = total - c.lap_no + 1
            msg += f" {S.words(to_go).capitalize()} to go, this one included." + (" You need a stop." if left < to_go - 0.2 else " Enough to finish.")
        return msg

    def _tyres(self):
        c = self.col
        if not c.live or c.row is None:
            return "No car on track."
        from .packet import C
        t = [round(float(c.row[C["tt_" + w]])) for w in ("fl", "fr", "rl", "rr")]
        note = " Hot." if max(t) >= 100 else (" Cold." if max(t) < 60 else "")
        return f"Tyres. Front left {S.words(t[0])}, front right {S.words(t[1])}, rear left {S.words(t[2])}, rear right {S.words(t[3])}.{note}"

    def _best(self):
        c = self.col
        laps = [l["time_ms"] for l in c.session_laps if l["time_ms"] > 0]
        parts = []
        if laps:
            parts.append(f"Best this session, {S.lap_time(min(laps))}.")
        if c.ref:
            parts.append(f"Best ever here in this car, {S.lap_time(c.ref['time_ms'])}.")
        return " ".join(parts) or "No lap recorded yet."

    def _last_lap(self):
        c = self.col
        if not c.session_laps:
            return "No lap recorded yet."
        l = c.session_laps[-1]; best = min(x["time_ms"] for x in c.session_laps)
        d = (l["time_ms"] - best) / 1000.0
        return f"Last lap, {S.lap_time(l['time_ms'])}." + (" That is your best." if d <= 0 else f" {S.gap(d).capitalize()} off your best.")

    def _gap(self):
        d = self.co.delta if self.col.live else None
        if d is None:
            return "No gap yet. It needs a best lap on this track."
        return "Level with your best lap." if abs(d) < 0.05 else f"{S.gap(d).capitalize()} {'behind' if d > 0 else 'ahead of'} your best lap."

    def _lap(self):
        c = self.col; total = c.meta.get("total_laps") or 0
        if not c.live or not c.lap_no:
            return "No car on track."
        return f"Lap {S.words(c.lap_no)}" + (f" of {S.words(total)}. {S.words(max(0, total - c.lap_no)).capitalize()} to go after this one." if total > 0 else ".")

    def _basis(self):
        """What advice is worked out from: this session's laps, or the last session that had enough of them.
        -> (laps, car, sheet, meta, where)"""
        c = self.col
        laps = [dict(first=l["first"], pit=l.get("pit"), analysis=l.get("analysis")) for l in c.session_laps]
        car, sheet, meta, where = c.car, c.tune and c.tune["sheet"], c.meta, ""
        if len(self._timed(laps)) < TA.MIN_LAPS and self.store is not None:          # nothing driven yet: the last real session
            from . import knowledge as K, library as L
            for se in self.store.q("SELECT * FROM sessions ORDER BY id DESC LIMIT 12"):
                rows = self.store.q("SELECT first, analysis FROM laps WHERE session_id=? AND analysis IS NOT NULL ORDER BY id", se["id"])
                cand = [dict(first=r["first"], analysis=json.loads(r["analysis"])) for r in rows]
                for l in cand:
                    l["pit"] = l["analysis"]["summary"].get("pit")
                if len(self._timed(cand)) >= TA.MIN_LAPS and (not c.live or se["car"] == c.car):
                    laps, car = cand, se["car"]
                    t = L.current_tune(self.store, car); sheet = t and t["sheet"]
                    meta = dict(json.loads(se["meta"] or "{}"), drivetrain=(K.spec(car) or {}).get("drivetrain"))
                    where = "From your last session. "
                    break
        return laps, car, sheet, meta, where

    @staticmethod
    def _timed(laps):
        return [l for l in laps if not l["first"] and l.get("analysis") and not l.get("pit")]

    def _advised(self, laps, sheet, meta):
        """The advice for those laps, or None when there are too few of them or it cannot be worked out."""
        try:
            adv = TA.advise([l["analysis"]["summary"] for l in self._timed(laps)], sheet, meta, pitted=any(l.get("pit") for l in laps))
        except Exception as e:
            self.log(f"advice failed: {e!r}")
            return None
        return adv if adv.get("ready") else None

    def _advice(self, every=False):
        """What to change on the car. every: read out all the changes, not the first four."""
        laps, car, sheet, meta, where = self._basis()
        adv = self._advised(laps, sheet, meta)
        if not adv:
            return "I need three timed laps first."
        rec = adv.get("recommended") or []
        if rec:                                          # the same list as the settings sheet on the page
            said = ". ".join(f"{r['game_setting'].replace(': ', ', ').replace('(', '').replace(')', '')}: {r['now']} to {r['to']}" for r in (rec if every else rec[:4]))
            return f"{where}{S.words(len(rec)).capitalize()} {'change' if len(rec) == 1 else 'changes'}. {said}."
        if not adv["items"]:
            return where + "Nothing on the car stands out. The time is in the driving."
        return where + " ".join(TA.spoken(i) for i in adv["items"][:2])

    def _setting(self, paths, end=None):
        """A setting asked for by name: what the sheet on file says, and what to set it to when the laps ask for a change."""
        from . import cli, library as L, sheet as SH
        c = self.col
        laps, car, sheet, meta, _ = self._basis()
        if self.store is not None and not c.live:        # not driving: the car whose sheet was filed last, if that is newer than the last drive
            t = self.store.q("SELECT car, created FROM tunes ORDER BY id DESC LIMIT 1")
            se = self.store.q("SELECT started FROM sessions ORDER BY id DESC LIMIT 1")
            if t and (not car or not se or t[0]["created"] > (se[0]["started"] or 0)) and t[0]["car"] != car:
                car, laps = t[0]["car"], []
                cur = L.current_tune(self.store, car); sheet = cur and cur["sheet"]
        if not car:
            return "I do not know which car you mean. Drive it, or take a screenshot of its settings."
        name = cli.car_name(car)
        if not sheet:
            return f"No settings sheet on file for the {name}. Take a screenshot of the Car Settings screen first."
        adv = self._advised(laps, sheet, meta) if laps else None
        rec = {(r["path"], r.get("end")): r for r in ((adv or {}).get("recommended") or [])}
        flat, lines = SH.flat(sheet), []
        for path in paths:
            label = SH.GAME[path][1].split(" (")[0].replace("/", " ")
            pair = any(path == row[0] and row[2] for _, _, _, rows in SH.LAYOUT for row in rows)
            ends = ([end] if end else list(SH.ENDS)) if pair else [None]
            bits, sets = [], []
            for e in ends:
                now = flat.get(f"{path}.{e}" if e else path)
                if now is None:
                    continue
                bits.append(f"{e + ' ' if e and len(ends) > 1 else ''}{SH._show(path, now)}")
                r = rec.get((path, e))
                if r:
                    sets.append(f"set {'the ' + e if e and len(ends) > 1 else 'it'} to {r['to']}")
            if bits:
                lines.append(f"{label}, {', '.join(bits)}" + (". Change: " + ", ".join(sets) if sets else ""))
        if not lines:
            return f"That is not on the sheet for the {name}."
        head = ("" if c.live else f"On the {name}. ") + (end.capitalize() + ". " if end else "")
        tail = "" if any("Change:" in l for l in lines) else (" Keep it there." if adv and len(lines) == 1 else "")
        return head + ". ".join(lines) + "." + tail

    def _corners(self):
        c = self.col; bz = c.best_zones or []
        per = {}
        for l in self._clean():
            for k, z in enumerate((l.get("analysis") or {}).get("zones") or []):
                if k < len(bz) and z and bz[k]:
                    d = per.setdefault(z["n"], [0.0, 0]); d[0] += max(0.0, z["time"] - bz[k]["time"]); d[1] += 1
        worst = sorted(((v[0] / v[1], n) for n, v in per.items() if v[1]), reverse=True)[:2]
        worst = [(a, n) for a, n in worst if a >= 0.1]
        if not worst:
            return "Nothing to go on yet. Do a few laps."
        return "Most time lost at " + ", then ".join(f"turn {S.words(n)}, {S.gap(a)} a lap" for a, n in worst) + "."
