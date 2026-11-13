"""The screenshot inbox: every way a picture of a settings or event screen can arrive ends in one place.

  upload     the Screenshots page's file field, and `gt7copilot shot-file` (POST /api/screenshot)
  share      the page installed as an app on an Android phone, picked in the share sheet (POST /share)
  shortcut   an iPhone Shortcut, or any script, with the share token (POST /api/shot)
  folder     a watched folder that a photo sync fills
  phone      the newest PS5 capture, fetched through the virtual phone

Each route has its own switch in Settings. All of them hand the picture to the same reader (capture.take, through
Voice.shot). The last results are kept for the page, and said aloud when a session is live."""
import json, os, threading, time
from email.parser import BytesParser
from email.policy import HTTP
from . import settings as CFG
from .capture import mime

ROUTES = dict(upload="upload", share="share sheet", shortcut="shortcut", folder="folder", phone="virtual phone")
ROUTE_SWITCH = dict(upload="upload_on", share="share_on", shortcut="shortcut_on", folder="folder_on", phone="phone_on")
IMAGE_EXT = (".jpg", ".jpeg", ".png", ".webp")
KEEP = 20                 # results remembered
STABLE = 2.0              # seconds a file's size must stay the same before it is read (a sync may still be writing it)


def why_not(route):
    """None when a picture may come in this way, else the sentence to say."""
    why = CFG.why_not("screenshots")
    if why:
        return why
    if route == "phone":
        return CFG.why_not("phone")
    if not CFG.get(ROUTE_SWITCH[route]):
        return CFG.OFF[ROUTE_SWITCH[route]]
    if route == "shortcut" and not CFG.get("share_token"):
        return "The share token is not set in Settings."
    return None


def folder_path():
    return CFG.get("folder_path") or os.path.join(CFG.ROOT, "inbox")


def from_form(content_type, body):
    """The first picture in a multipart/form-data body -> (bytes, file name), or (None, None)."""
    msg = BytesParser(policy=HTTP).parsebytes(b"Content-Type: " + content_type.encode() + b"\r\nMIME-Version: 1.0\r\n\r\n" + body)
    if not msg.is_multipart():
        return None, None
    for part in msg.iter_parts():
        data = part.get_payload(decode=True) or b""
        if mime(data):
            return data, part.get_filename() or ""
    return None, None


class Inbox:
    def __init__(self, shot, say=None, is_live=lambda: False, log=print, store=None):
        self.shot, self.say, self.is_live, self.log, self.store = shot, say, is_live, log, store
        self.file = os.path.join(CFG.ROOT, "inbox-log.json")
        self.lock = threading.Lock(); self.sizes = {}; self.folder_note = None
        try:
            self.items = json.load(open(self.file, encoding="utf-8"))[-KEEP:]
        except (OSError, ValueError):
            self.items = []

    # ---- results --------------------------------------------------------------------------------------------------
    def record(self, route, out, name=""):
        item = dict(at=time.time(), route=ROUTES.get(route, route), ok=bool(out.get("ok")), reply=out.get("reply") or "", name=name or "")
        with self.lock:
            self.items = (self.items + [item])[-KEEP:]
            try:
                tmp = self.file + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(self.items, f)
                os.replace(tmp, self.file)
            except OSError:
                pass
        return item

    def recent(self, n=8):
        return list(reversed(self.items[-n:]))

    def status(self):
        """For the page: the last results and how each route stands."""
        routes = {r: dict(on=why_not(r) is None, why=why_not(r)) for r in ROUTES}
        return dict(recent=self.recent(), routes=routes, folder=dict(path=folder_path(), note=self.folder_note))

    # ---- one picture ----------------------------------------------------------------------------------------------
    def submit(self, image, route, name="", speak=True):
        """Read a picture that came in by `route` (image None = fetch through the virtual phone). -> dict(ok, reply)."""
        why = why_not(route)
        if why:
            return dict(ok=False, reply=why)
        if route != "phone" and not image:
            return dict(ok=False, reply="No picture was sent.")
        if image and not mime(image):
            out = dict(ok=False, reply="That file is not a picture I can read. Use JPEG, PNG or WebP.")
        else:
            out = self.shot(image)
        try:                                             # how each kept picture came in (Screenshots page)
            if out.get("shots") and self.store is not None:
                self.store.x(f"UPDATE shots SET route=?, name=? WHERE id IN ({','.join('?' * len(out['shots']))})",
                             ROUTES.get(route, route), name or None, *out["shots"])
        except Exception:
            pass
        self.record(route, out, name)
        if speak and self.say and self.is_live():
            try: self.say(out["reply"], 60.0, "voice")
            except Exception: pass
        return out

    # ---- the watched folder ---------------------------------------------------------------------------------------
    def scan(self, now=None):
        """One look at the folder. A picture is read once its size has stood still for STABLE seconds, then moved to
        done/ or failed/ (with a .txt beside it saying why). -> the number read."""
        now = now or time.time()
        if why_not("folder"):
            self.sizes.clear(); self.folder_note = None
            return 0
        path = folder_path()
        try:
            os.makedirs(path, exist_ok=True)
            names = sorted(n for n in os.listdir(path) if n.lower().endswith(IMAGE_EXT) and not n.startswith("."))
        except OSError as e:
            self.folder_note = f"The folder cannot be read: {e.strerror or e}."
            return 0
        self.folder_note = None; done = 0
        for n in names:
            p = os.path.join(path, n)
            try:
                st = os.stat(p)
            except OSError:
                continue
            size, since = self.sizes.get(n, (None, now))
            if size != st.st_size:
                self.sizes[n] = (st.st_size, now); continue
            if now - since < STABLE or st.st_size == 0:
                continue
            self.sizes.pop(n, None)
            try:
                with open(p, "rb") as f:
                    image = f.read(12_000_001)
            except OSError as e:
                self._move(p, n, False, f"could not be opened: {e.strerror or e}"); continue
            if len(image) > 12_000_000:
                out = dict(ok=False, reply="That picture is too large. The limit is 12 MB.")
                self.record("folder", out, n)
            else:
                out = self.submit(image, "folder", n)
            self._move(p, n, out.get("ok"), out.get("reply") or "")
            done += 1
        for n in [n for n in self.sizes if n not in names]:
            del self.sizes[n]
        return done

    def _move(self, p, name, ok, reason):
        sub = os.path.join(os.path.dirname(p), "done" if ok else "failed")
        try:
            os.makedirs(sub, exist_ok=True)
            dest = os.path.join(sub, name)
            if os.path.exists(dest):
                root, ext = os.path.splitext(name); dest = os.path.join(sub, f"{root}-{int(time.time())}{ext}")
            os.replace(p, dest)
            if not ok:
                with open(dest + ".txt", "w", encoding="utf-8") as f:
                    f.write(reason + "\n")
        except OSError as e:
            self.folder_note = f"A picture could not be moved out of the folder: {e.strerror or e}."
            self.log(f"inbox: {name}: {self.folder_note}")

    def watch(self, every=1.0):
        def loop():
            while True:
                try: self.scan()
                except Exception as e: self.log(f"inbox folder: {e!r}")
                time.sleep(every)
        threading.Thread(target=loop, daemon=True).start()
