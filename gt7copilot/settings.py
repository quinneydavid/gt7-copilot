"""Settings: one file in the data folder (settings.json, readable by the owner only), changed from the Settings tab.

Every value has a default. An environment variable (GT7C_...) only gives the value used until the setting is saved
for the first time; after that the file wins. Secrets never leave through view(): the page sees "set" or "not set".
Changing settings needs the admin password (salted PBKDF2 hash in the same file). Driving pages need no password."""
import hashlib, hmac, json, os, secrets, threading, time

ROOT = os.environ.get("GT7C_DATA", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data"))
FILE = os.path.join(ROOT, "settings.json")

# key: (kind, default, environment variable, label, help). kind: text | secret | bool | int | choice:a,b
FIELDS = {
    "ps5":            ("text", "", "GT7C_PS5", "Console address", "IP address of the PS5 or PS4 on the home network."),
    "heartbeat":      ("choice:B,A,~", "B", "GT7C_HEARTBEAT", "Telemetry packet type",
                       "B has the steering angle. The copilot falls back to A by itself when B cannot be read."),
    "copilot_on":     ("bool", True, "GT7C_COPILOT_ON", "Spoken calls", "The copilot talks while driving."),
    "max_calls":      ("int", 8, "GT7C_MAX_CALLS", "Corner calls per lap", "The biggest losses first. 1 to 20."),
    "tts_voice":      ("text", "bm_george", "GT7C_VOICE", "Voice", "A Kokoro voice name, e.g. bm_george, am_michael, af_heart."),
    "wake_names":     ("text", "copilot,co-pilot,co pilot,copilots", "GT7C_NAME", "Wake name",
                       "Spoken before every command. Comma separated: the name and the ways speech-to-text writes it."),
    "voice_on":       ("bool", False, "GT7C_VOICE_ON", "Voice control", "Spoken commands from the earpiece microphone."),
    "voice_open_live": ("bool", False, "GT7C_VOICE_OPEN_LIVE", "No name needed while driving",
                        "While the car is on track, commands and questions are taken without the wake name. Off the track the name is still needed."),
    "whisper_url":    ("text", "", "GT7C_WHISPER_URL", "Speech-to-text address",
                       "OpenAI-compatible transcription endpoint, e.g. http://whisper:8000/v1/audio/transcriptions"),
    "whisper_token":  ("secret", "", "GT7C_WHISPER_TOKEN", "Speech-to-text key", "Only if the service asks for one."),
    "whisper_model":  ("text", "Systran/faster-distil-whisper-small.en", "GT7C_WHISPER_MODEL", "Speech-to-text model", ""),
    "screenshots_on": ("bool", False, "GT7C_SCREENSHOTS_ON", "Screenshot reading",
                       "A vision model reads settings and event screens from a PS5 screenshot or a photo."),
    "llm_url":        ("text", "", "GT7C_LLM_URL", "Vision model address", "OpenAI-compatible base address, e.g. http://ollama:11434/v1"),
    "llm_key":        ("secret", "", "GT7C_LLM_KEY", "Vision model key", "Only if the service asks for one."),
    "vision_model":   ("text", "", "GT7C_VISION_MODEL", "Vision model name", "A model that accepts images."),
    "upload_on":      ("bool", True, "GT7C_UPLOAD_ON", "Upload on the page", "The file field on the Screenshots page, and shot-file on the command line."),
    "share_on":       ("bool", False, "GT7C_SHARE_ON", "Share sheet (Android)",
                       "The page installed as an app appears in the phone's share sheet. Needs the page on https."),
    "shortcut_on":    ("bool", False, "GT7C_SHORTCUT_ON", "Shortcut (iPhone) or script",
                       "Pictures posted to /api/shot with the share token."),
    "share_token":    ("secret", "", "GT7C_SHARE_TOKEN", "Share token", "Goes into the Shortcut. May only send pictures."),
    "folder_on":      ("bool", False, "GT7C_FOLDER_ON", "Watched folder", "Pictures that appear in a folder are read, then moved to done or failed."),
    "folder_path":    ("text", "", "GT7C_FOLDER", "Folder", "Empty = the folder inbox in the data volume."),
    "phone_on":       ("bool", False, "GT7C_PHONE_ON", "Virtual phone",
                       "Fetch the newest PS5 capture from the PlayStation App on the virtual phone."),
    "grab_url":       ("text", "", "GT7C_GRAB_URL", "Virtual phone address", "e.g. http://phone:6081"),
    "grab_token":     ("secret", "", "GT7C_GRAB_TOKEN", "Virtual phone token", "Shared with the phone container."),
    "phone_view_url": ("text", "", "GT7C_PHONE_VIEW_URL", "Virtual phone screen address",
                       "The phone's web view, e.g. http://phone:6080. The Phone page shows it to the signed-in admin."),
    "phone_view_password": ("secret", "", "GT7C_PHONE_VIEW_PASSWORD", "Virtual phone screen password",
                            "The web view's password, so the Phone page opens without asking. Empty = it asks."),
    "ask_on":         ("bool", False, "GT7C_ASK_ON", "Ask",
                       "A chat on the page: questions in plain words, answered by the model from your own laps and settings."),
    "ask_model":      ("text", "", "GT7C_ASK_MODEL", "Model for Ask",
                       "A model name at the address in the Screenshots group. Empty = the vision model."),
    "earpiece_on":    ("bool", False, "GT7C_EARPIECE_ON", "Earpiece", "A program on the sim PC or a Mac plays the calls and sends the microphone."),
    "earpiece_token": ("secret", "", "GT7C_EARPIECE_TOKEN", "Earpiece token", "Filled into the installer downloaded from this page."),
    "agent_on":       ("bool", False, "GT7C_AGENT_ON", "Agent door", "Lets a chat agent or the command line on another machine use the copilot."),
    "agent_token":    ("secret", "", "GT7C_TOKEN", "Agent token", "The agent sends it as a bearer token."),
}
GROUPS = [("Console", ["ps5", "heartbeat"]),
          ("Copilot voice", ["copilot_on", "max_calls", "tts_voice"]),
          ("Voice control", ["voice_on", "voice_open_live", "wake_names", "whisper_url", "whisper_token", "whisper_model"]),
          ("Screenshots", ["screenshots_on", "llm_url", "llm_key", "vision_model", "upload_on", "share_on", "shortcut_on", "share_token",
                           "folder_on", "folder_path", "phone_on", "grab_url", "grab_token", "phone_view_url", "phone_view_password"]),
          ("Ask", ["ask_on", "ask_model"]),
          ("Earpiece", ["earpiece_on", "earpiece_token"]),
          ("Agent door", ["agent_on", "agent_token"])]
GENERATED = ("earpiece_token", "agent_token", "share_token")      # tokens this app makes itself (Generate / Rotate on the page)
OFF = {"voice_on": "Voice control is turned off in Settings.", "screenshots_on": "Screenshots are turned off in Settings.",
       "phone_on": "The virtual phone is turned off in Settings. Upload the screenshot on the page instead.",
       "upload_on": "Uploading pictures is turned off in Settings.", "share_on": "Sharing from a phone is turned off in Settings.",
       "shortcut_on": "Pictures from a Shortcut are turned off in Settings.", "folder_on": "The watched folder is turned off in Settings.",
       "ask_on": "Ask is turned off in Settings.", "earpiece_on": "The earpiece is turned off in Settings.", "agent_on": "The agent door is turned off in Settings."}

_lock = threading.RLock()
_saved = None            # what the file holds
_listeners = []          # called with the set of changed keys after a save


def _truthy(v):
    return str(v).strip().lower() in ("1", "true", "yes", "on")


def _env_default(key):
    kind, default, env = FIELDS[key][:3]
    raw = os.environ.get(env)
    if key == "grab_token" and not raw:                      # compose: a token file both containers can read
        raw = _token_file(os.environ.get("GT7C_GRAB_TOKEN_FILE"))
    if raw is None or raw == "":
        if key in ("earpiece_on", "agent_on"):               # a token given at first start opens that door
            return bool(os.environ.get(FIELDS[key.replace("_on", "_token")][2]))
        if key == "shortcut_on":
            return bool(os.environ.get("GT7C_SHARE_TOKEN"))
        return default
    if kind == "bool":
        return _truthy(raw)
    if kind == "int":
        try: return int(raw)
        except ValueError: return default
    return raw


def _token_file(path):
    """The token in `path`, made on first use. '' when there is no such path."""
    if not path:
        return ""
    try:
        if not os.path.exists(path):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)   # the phone container runs as another user
            with os.fdopen(fd, "w") as f:
                f.write(secrets.token_urlsafe(32))
        return open(path).read().strip()
    except OSError:
        return ""


def _load():
    global _saved
    if _saved is None:
        try:
            _saved = json.load(open(FILE, encoding="utf-8"))
        except (OSError, ValueError):
            _saved = {}
    return _saved


def reload():
    """Forget what was read (another process may have saved; tests)."""
    global _saved
    with _lock:
        _saved = None


def get(key):
    with _lock:
        s = _load()
        return s[key] if key in s else _env_default(key)


def on_change(fn):
    _listeners.append(fn)


def _write(data):
    os.makedirs(ROOT, exist_ok=True)
    tmp = FILE + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1)
    os.replace(tmp, FILE); os.chmod(FILE, 0o600)


def _clean(key, value):
    kind = FIELDS[key][0]
    if kind == "bool":
        return value if isinstance(value, bool) else _truthy(value)
    if kind == "int":
        n = int(value)
        if key == "max_calls" and not 1 <= n <= 20:
            raise ValueError("Corner calls per lap must be 1 to 20.")
        return n
    v = str(value).strip()
    if kind.startswith("choice:") and v not in kind[7:].split(","):
        raise ValueError(f"{FIELDS[key][3]} must be one of {kind[7:]}.")
    if len(v) > 500:
        raise ValueError(f"{FIELDS[key][3]} is too long.")
    if key.endswith("_url") and v and not v.startswith(("http://", "https://")):
        raise ValueError(f"{FIELDS[key][3]} must start with http:// or https://")
    if key == "wake_names" and not [n for n in v.split(",") if n.strip()]:
        raise ValueError("The wake name cannot be empty.")
    if key == "folder_path" and v and not os.path.isabs(v):
        raise ValueError("The folder must be a full path, e.g. /data/inbox.")
    return v.rstrip("/") if key in ("llm_url", "grab_url", "phone_view_url") else v


def save(changes):
    """Store new values. A secret given as '' or None is left as it is; `{"clear": [keys]}` empties secrets;
    `{"generate": [keys]}` makes new tokens. -> the set of keys that changed."""
    changes = dict(changes)
    clear, generate = changes.pop("clear", []) or [], changes.pop("generate", []) or []
    with _lock:
        data = dict(_load()); changed = set()
        for key, value in changes.items():
            if key not in FIELDS:
                raise ValueError(f"Unknown setting: {key}")
            if FIELDS[key][0] == "secret" and value in ("", None):
                continue
            v = _clean(key, value)
            if v != get(key) or key not in data:
                if v != get(key): changed.add(key)
                data[key] = v
        for key in clear:
            if key in FIELDS and FIELDS[key][0] == "secret":
                data[key] = ""; changed.add(key)
        for key in generate:
            if key in GENERATED:
                data[key] = secrets.token_urlsafe(32); changed.add(key)
        _write(data)
        global _saved
        _saved = data
    for fn in list(_listeners):
        try: fn(changed)
        except Exception: pass
    return changed


def view():
    """What the Settings tab shows. Secrets appear only as set / not set."""
    out = []
    for title, keys in GROUPS:
        rows = []
        for k in keys:
            kind, _, env, label, help_ = FIELDS[k]
            v = get(k)
            row = dict(key=k, kind=kind.split(":")[0], label=label, help=help_)
            if kind == "secret":
                row.update(set=bool(v), generated=k in GENERATED)
            else:
                row["value"] = v
            if kind.startswith("choice:"):
                row["choices"] = kind[7:].split(",")
            rows.append(row)
        out.append(dict(title=title, rows=rows))
    return out


def features():
    """What is switched on and usable, with the sentence to say when it is not. For the page, the CLI and agents."""
    def state(on_key, needs):
        if not get(on_key):
            return dict(on=False, ready=False, why=OFF[on_key])
        missing = [FIELDS[k][3] for k in needs if not get(k)]
        return dict(on=True, ready=not missing, why="Not set in Settings: " + ", ".join(missing) + "." if missing else None)
    return dict(console=dict(on=True, ready=bool(get("ps5")), why=None if get("ps5") else "The console address is not set in Settings."),
                voice_control=state("voice_on", ["whisper_url"]),
                screenshots=state("screenshots_on", ["llm_url", "vision_model"]),
                phone=state("phone_on", ["grab_url"]) if get("screenshots_on") else dict(on=bool(get("phone_on")), ready=False, why=OFF["screenshots_on"]),
                phone_view=state("phone_on", ["phone_view_url"]),
                ask=_ask_state(),
                earpiece=state("earpiece_on", ["earpiece_token"]),
                agent_door=state("agent_on", ["agent_token"]))


def _ask_state():
    if not get("ask_on"):
        return dict(on=False, ready=False, why=OFF["ask_on"])
    missing = ([] if get("llm_url") else ["Vision model address (Screenshots group)"]) + ([] if get("ask_model") or get("vision_model") else ["Model for Ask"])
    return dict(on=True, ready=not missing, why="Not set in Settings: " + ", ".join(missing) + "." if missing else None)


def why_not(feature):
    """None when the feature can be used, else the sentence to say."""
    f = features()[feature]
    return None if f["ready"] else f["why"]


# ---- admin password and sign-in ------------------------------------------------------------------------------------------
_sessions = {}           # cookie value -> expiry
SESSION_HOURS = 12
_fails = {}              # client address -> times of its recent wrong passwords


def _hash(password, salt):
    return hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 200_000).hex()


def admin_set():
    return bool(_load().get("admin")) or bool(os.environ.get("GT7C_ADMIN_PASSWORD"))


def set_password(password):
    if len(password or "") < 8:
        raise ValueError("The password needs at least 8 characters.")
    salt = secrets.token_hex(16)
    with _lock:
        data = dict(_load()); data["admin"] = dict(salt=salt, hash=_hash(password, salt))
        _write(data)
        global _saved
        _saved = data
        _sessions.clear()


def check_password(password, who=""):
    """`who` = the client's address: ten wrong passwords lock that address out for five minutes, and nobody else."""
    now = time.time()
    for k in list(_fails):
        _fails[k] = [t for t in _fails[k] if now - t < 300]
        if not _fails[k]: del _fails[k]
    if len(_fails.get(who, [])) >= 10:
        raise ValueError("Too many wrong passwords. Wait five minutes.")
    adm = _load().get("admin")
    if adm:
        ok = hmac.compare_digest(_hash(password or "", adm["salt"]), adm["hash"])
    else:
        env = os.environ.get("GT7C_ADMIN_PASSWORD", "")
        ok = bool(env) and hmac.compare_digest((password or "").encode(), env.encode())
    if not ok:
        _fails.setdefault(who, []).append(now)
    return ok


def sign_in(password, who=""):
    """-> a session value for the cookie, or None."""
    if not check_password(password, who):
        return None
    tok = secrets.token_urlsafe(32)
    _sessions[tok] = time.time() + SESSION_HOURS * 3600
    return tok


def signed_in(session):
    return bool(session) and _sessions.get(session, 0) > time.time()


def sign_out(session):
    _sessions.pop(session, None)
