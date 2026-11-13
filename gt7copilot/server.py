"""HTTP for the copilot page: the page's data, live events (SSE), cached audio, kept screenshots, the virtual phone's
screen passed through for the admin, settings, and the doors for the earpiece and for agents."""
import hmac, json, os, queue, re, select, socket, threading, time, urllib.error, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, urlparse
from .tts import CACHE, BASE
from . import api, ask as ASK, cli, inbox as INBOX, pwa
from .store import Store

from . import settings as CFG

# The earpiece (earpiece/): a small program on the sim PC or a Mac that plays the calls into one audio device without a
# browser. It sends its token in X-GT7C-Earpiece and may only listen (/events, /audio/*) and report its own status.
EARPIECE_HEADER = "X-GT7C-Earpiece"
EARPIECE_DIR = os.path.join(BASE, "earpiece")
TRUST_DOOR = os.environ.get("GT7C_TRUST_DOOR", "") == "1"      # see H._admin: only when a sign-in stands in front of the page
EARPIECE_STALE = 30.0          # seconds without a report before the page says the earpiece is not running
MAX_IMAGE = 12_000_000         # bytes: an uploaded screenshot or photo
VNC_PASSWORD_FILE = os.environ.get("GT7C_VNC_PASSWORD_FILE", "")      # compose: the phone's web view password, for the Settings tab


def earpiece_ok(headers):
    """None = not an earpiece request (no header); True/False = header present and right/wrong (or the earpiece is off)."""
    got = headers.get(EARPIECE_HEADER)
    if got is None:
        return None
    tok = CFG.get("earpiece_token") if CFG.get("earpiece_on") else ""
    return bool(tok) and hmac.compare_digest(got.encode(), tok.encode())


class Hub:
    def __init__(self):
        self.clients = set(); self.lock = threading.Lock(); self.recent = []

    def publish(self, ev):
        ev["t"] = time.time(); self.recent = (self.recent + [ev])[-30:]
        with self.lock:
            for q in list(self.clients):
                try: q.put_nowait(ev)
                except queue.Full: self.clients.discard(q)


SHARE_HEADER = "X-GT7C-Share"     # the share token: an iPhone Shortcut or a script may send pictures with it, nothing else


def serve(port, hub, get_state, say, set_enabled, hear=None, hear_text=None, shot=None, tests=None, inbox=None, reader=None):
    if inbox is None and shot is not None:
        inbox = INBOX.Inbox(shot)
    earpiece = {}                                   # last report from the PC earpiece + when
    diag = {}                                       # its last full picture of the PC (GET /api/state only, not the stream)

    def state():
        ep = dict(earpiece) if earpiece and time.time() - earpiece.get("seen", 0) < EARPIECE_STALE else None
        st = get_state()
        try: name = cli.car_name(st["car"]) if st.get("car") else None
        except Exception: name = None
        f = CFG.features()
        return dict(st, car_name=name, earpiece=ep, earpiece_setup=f["earpiece"]["ready"], console_set=f["console"]["ready"], phone_on=f["phone"]["on"], ask=f["ask"]["ready"],
                    screenshots=f["screenshots"]["ready"], phone=f["phone"]["ready"], voice_control=f["voice_control"]["ready"])

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a): pass

        def _send(self, code, body, ctype="application/json"):
            body = body if isinstance(body, bytes) else body.encode()
            self.send_response(code); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store"); self.end_headers(); self.wfile.write(body)

        def _json(self, code, obj, cookie=None):
            body = json.dumps(obj, default=str).encode()
            self.send_response(code); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            if cookie is not None:
                self.send_header("Set-Cookie", f"gt7c_admin={cookie}; Path=/; HttpOnly; SameSite=Strict" + ("" if cookie else "; Max-Age=0"))
            self.end_headers(); self.wfile.write(body)

        def _session(self):
            for part in (self.headers.get("Cookie") or "").split(";"):
                k, _, v = part.strip().partition("=")
                if k == "gt7c_admin":
                    return v
            return ""

        def _body(self, limit):
            n = int(self.headers.get("Content-Length", 0) or 0)
            if n > limit:
                raise ValueError("too large")
            return self.rfile.read(n)

        def _file(self, path, ctype, cache="private, max-age=86400"):
            try:
                body = open(path, "rb").read()
            except OSError:
                return self._send(404, "{}")
            self.send_response(200); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", cache); self.end_headers(); self.wfile.write(body)

        def _phone_password(self):
            pw = CFG.get("phone_view_password")
            if not pw and VNC_PASSWORD_FILE:
                try: pw = open(VNC_PASSWORD_FILE).read().strip()
                except OSError: pw = ""
            return pw or ""

        def _admin(self):
            """Is this request the admin's? Signed in on Settings - or, with GT7C_TRUST_DOOR=1, anyone who came through the
            page's own door: the installation says a sign-in (single sign-on, a proxy with a login) stands in front of
            every way to the page, so a second password adds nothing. The earpiece and the agent door never count."""
            if TRUST_DOOR and earpiece_ok(self.headers) is None and not self.headers.get("Authorization"):
                return True
            return CFG.signed_in(self._session())

        def _own(self):
            """Not sent by another site's page: it has the page's own header, which a browser lets no foreign page add, or
            the agent token, which no foreign page knows. For everything that changes or starts something."""
            if self.headers.get("X-GT7C") == "1":
                return True
            tok = CFG.get("agent_token") if CFG.why_not("agent_door") is None else ""
            return bool(tok) and hmac.compare_digest(self.headers.get("Authorization", "").encode(), ("Bearer " + tok).encode())

        def _phone_status(self):
            """For the Phone page: is the virtual phone's screen available here, and how the phone is."""
            f = CFG.features(); admin = self._admin()
            out = dict(on=f["phone"]["on"], ready=f["phone_view"]["ready"], why=f["phone_view"]["why"], fetch_ready=f["phone"]["ready"],
                       signed_in=admin, admin_set=CFG.admin_set())
            if f["phone"]["ready"]:
                try:
                    with urllib.request.urlopen(CFG.get("grab_url") + "/healthz", timeout=4) as r:
                        out["health"] = json.load(r)
                except Exception as e:
                    out["health"] = dict(ok=False, note=f"The phone's fetcher cannot be reached ({type(e).__name__}).")
            if out["ready"] and admin:
                pw = self._phone_password()
                out["src"] = "/phone/vnc.html?autoconnect=1&resize=scale&reconnect=1&reconnect_delay=2000&path=phone/websockify" + \
                             (f"#password={quote(pw, safe='')}" if pw else "")
            return out

        def _phone_proxy(self, u):
            """The virtual phone's web view (noVNC), passed through for the signed-in admin so the phone sits inside the
            page: plain files by request, the screen itself as a WebSocket relayed byte for byte."""
            if not self._admin():
                return self._send(401, '{"error":"Sign in on the Settings page first."}')
            why = CFG.why_not("phone_view")
            if why:
                return self._send(409, json.dumps(dict(error=why)))
            base = urlparse(CFG.get("phone_view_url")); sub = u.path[len("/phone"):] or "/"
            if ".." in sub or not base.hostname:
                return self._send(404, "{}")
            target = sub + ("?" + u.query if u.query else "")
            if self.headers.get("Upgrade", "").lower() == "websocket":
                try:
                    up = socket.create_connection((base.hostname, base.port or 80), timeout=10)
                except OSError:
                    return self._send(502, '{"error":"The phone\'s screen cannot be reached."}')
                drop = ("host", "cookie", "origin", "x-forwarded-for", "x-forwarded-host", "x-forwarded-proto", "x-real-ip", "authorization")
                head = [f"GET {target} HTTP/1.1", f"Host: {base.netloc}"] + [f"{k}: {v}" for k, v in self.headers.items() if k.lower() not in drop]
                self.close_connection = True
                try:
                    up.sendall(("\r\n".join(head) + "\r\n\r\n").encode()); up.settimeout(None)
                    me = self.connection; me.settimeout(None)
                    while True:
                        ready, _, _ = select.select([me, up], [], [], 120)
                        if not ready:
                            continue
                        for src, dst in ((me, up), (up, me)):
                            if src in ready:
                                data = src.recv(65536)
                                if not data:
                                    return
                                dst.sendall(data)
                except OSError:
                    return
                finally:
                    up.close()
            try:
                with urllib.request.urlopen(f"{base.scheme}://{base.netloc}{target}", timeout=15) as r:
                    body = r.read(20_000_000); ctype = r.headers.get("Content-Type", "application/octet-stream")
            except urllib.error.HTTPError as e:
                return self._send(e.code, "{}")
            except Exception:
                return self._send(502, '{"error":"The phone\'s screen cannot be reached."}')
            self.send_response(200); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "private, max-age=3600"); self.end_headers(); self.wfile.write(body)

        def _settings_view(self):
            admin = self._admin()
            out = dict(admin_set=CFG.admin_set(), signed_in=admin, door=TRUST_DOOR, features=CFG.features())
            if admin:
                out["groups"] = CFG.view()
                try: out["phone_view_password"] = open(VNC_PASSWORD_FILE).read().strip() if VNC_PASSWORD_FILE else None
                except OSError: out["phone_view_password"] = None
            return out

        def _admin_post(self, path):
            """Settings and sign-in. Only same-site pages may call these: a custom header that another site cannot send."""
            if self.headers.get("X-GT7C") != "1":
                return self._json(400, dict(error="missing X-GT7C header"))
            try:
                body = json.loads(self._body(50_000) or b"{}")
            except ValueError:
                return self._json(400, dict(error="bad request"))
            try:
                if path == "/api/admin/setup":
                    if CFG.admin_set():
                        return self._json(409, dict(error="An admin password is already set."))
                    CFG.set_password(str(body.get("password") or ""))
                    return self._json(200, self._after_login(str(body.get("password"))), cookie=self._cookie)
                if path == "/api/admin/login":
                    out = self._after_login(str(body.get("password") or ""))
                    return self._json(200 if out.get("signed_in") else 401, out, cookie=self._cookie)
                if path == "/api/admin/logout":
                    CFG.sign_out(self._session())
                    return self._json(200, dict(ok=True), cookie="")
                if not self._admin():
                    return self._json(401, dict(error="Sign in on the Settings tab first."))
                if path == "/api/admin/password":
                    CFG.set_password(str(body.get("password") or ""))
                    return self._json(200, self._after_login(str(body.get("password"))), cookie=self._cookie)
                if path == "/api/admin/shot-delete":
                    Store().delete_shot(int(body.get("id")))
                    return self._json(200, dict(ok=True))
                if path == "/api/admin/shot-set":
                    return self._json(200, api.shot_set(int(body.get("id")), body.get("car"), body.get("cover")))
                if path == "/api/admin/track-name":
                    name = str(body.get("name") or "").strip()[:80]
                    if not name:
                        raise ValueError("Type the track's name.")
                    Store().x("UPDATE tracks SET name=?, name_src='you' WHERE id=?", name, int(body.get("id")))
                    return self._json(200, dict(ok=True))
                if path == "/api/settings":
                    changed = CFG.save(body)
                    new = {k: CFG.get(k) for k in (body.get("generate") or []) if k in CFG.GENERATED}     # shown once, on the page that asked
                    return self._json(200, dict(ok=True, changed=sorted(changed), new_tokens=new, **self._settings_view()))
                if path == "/api/settings/test":
                    fn = (tests or {}).get(str(body.get("what")))
                    if not fn:
                        return self._json(404, dict(error="no such test"))
                    return self._json(200, fn(body))
            except ValueError as e:
                return self._json(400, dict(error=str(e)))
            return self._json(404, {})

        def _after_login(self, password):
            self._cookie = CFG.sign_in(password, self.client_address[0])
            if not self._cookie:
                self._cookie = None
                return dict(signed_in=False, error="Wrong password.")
            return dict(ok=True, admin_set=True, signed_in=True, features=CFG.features(), groups=CFG.view())

        def do_GET(self):
            u = urlparse(self.path); qs = parse_qs(u.query)
            ep = earpiece_ok(self.headers)
            if ep is False:
                return self._send(401, '{"error":"bad earpiece token"}')
            if ep and not (u.path in ("/events", "/earpiece/earpiece.py") or u.path.startswith("/audio/")):
                return self._send(403, '{"error":"the earpiece may only listen"}')
            if u.path == "/":
                return self._send(200, open(os.path.join(BASE, "web/index.html"), "rb").read(), "text/html; charset=utf-8")
            if u.path in pwa.FILES:
                body, ctype = pwa.FILES[u.path]()
                return self._send(200, body, ctype)
            if u.path == "/share":                  # the share sheet answers here; opened by hand it only explains
                return self._send(200, pwa.result_page(None, "Pick GT7 Copilot in the phone's share sheet to send a picture."), "text/html; charset=utf-8")
            if u.path == "/api/inbox":
                return self._json(200, inbox.status() if inbox else dict(recent=[], routes={}, folder={}))
            if u.path == "/api/screenshots/job":    # "read the new screenshots": how far it is, and its result when done
                return self._json(200, reader.job if reader else dict(running=False, step="", result=None))
            if u.path == "/healthz":
                return self._send(200, '{"ok":true}')
            if u.path == "/api/state":
                return self._send(200, json.dumps(dict(state(), listeners=len(hub.clients), recent=hub.recent[-10:], earpiece_diag=diag or None)))
            if u.path == "/api/settings":
                return self._json(200, self._settings_view())
            if u.path == "/api/features":
                return self._json(200, CFG.features())
            if u.path in ("/api/say", "/api/heartext", "/api/enable"):      # they change something: POST only (do_POST)
                return self._json(405, dict(error="Use POST, with the header X-GT7C: 1."))
            if u.path == "/phone" or u.path.startswith("/phone/"):
                return self._phone_proxy(u)
            if u.path == "/api/ask":
                return self._json(200, dict(ready=ASK.why_not() is None, why=ASK.why_not(), examples=ASK.EXAMPLES))
            if u.path == "/api/phone":
                return self._json(200, self._phone_status())
            if u.path.startswith("/shots/"):
                try: found = api.shot_file(int(u.path.rsplit("/", 1)[1]))
                except ValueError: found = None
                return self._file(*found) if found else self._send(404, "{}")
            one = lambda k, cast=str: cast(qs[k][0]) if qs.get(k) and qs[k][0] != "" else None
            try:
                if u.path == "/api/overview":
                    return self._send(200, json.dumps(api.overview(), default=str))
                if u.path == "/api/cars":
                    return self._send(200, json.dumps(api.cars(one("q") or ""), default=str))
                if u.path == "/api/car":
                    return self._send(200, json.dumps(api.car(int(qs["code"][0]), one("session", int)), default=str))
                if u.path == "/api/track":
                    return self._send(200, json.dumps(api.track(int(qs["id"][0])), default=str))
                if u.path == "/api/tracks":
                    return self._send(200, json.dumps(api.tracks(), default=str))
                if u.path == "/api/shots":
                    return self._send(200, json.dumps(api.shots(one("car", int), one("group"), min(one("limit", int) or 60, 200), one("offset", int) or 0), default=str))
                if u.path == "/api/sessions":
                    return self._send(200, json.dumps(api.sessions(car=one("car", int), track=one("track", int))))
                if u.path == "/api/session":
                    return self._send(200, json.dumps(api.session(int(qs["id"][0])), default=str))
                if u.path == "/api/trace":
                    return self._send(200, json.dumps(api.trace(int(qs["lap"][0]))))
                if u.path == "/api/garage":
                    return self._send(200, json.dumps(api.garage()))
                if u.path == "/api/library":
                    return self._send(200, json.dumps(api.library(), default=str))
            except Exception as e:
                return self._send(500, json.dumps(dict(error=repr(e))))
            if u.path in ("/earpiece/setup.ps1", "/earpiece/setup-mac.sh"):     # the installer, with this server's address and token filled in
                if not self._admin():                # it carries the earpiece token: for the signed-in admin only
                    return self._send(401, '{"error":"Sign in on the Settings page, then download the installer there."}')
                why = CFG.why_not("earpiece")
                if why:
                    return self._send(404, json.dumps(dict(error=why)))
                host = self.headers.get("X-Forwarded-Host") or self.headers.get("Host", "")
                proto = self.headers.get("X-Forwarded-Proto", "http")
                if not re.fullmatch(r"[A-Za-z0-9.\-:\[\]]+", host) or proto not in ("http", "https"):     # both go into the script as they are
                    return self._send(400, '{"error":"This address cannot be written into the installer."}')
                url = f"{proto}://{host}"
                name = os.path.basename(u.path)
                body = (open(os.path.join(EARPIECE_DIR, name), encoding="utf-8").read().replace("__GT7C_URL__", url)
                        .replace("__GT7C_TOKEN__", CFG.get("earpiece_token")).replace("__GT7C_VOICE__", "1" if CFG.get("voice_on") else "0"))
                self.send_response(200); self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Disposition", f'attachment; filename="gt7copilot-earpiece-{name}"')
                data = body.encode(); self.send_header("Content-Length", str(len(data))); self.send_header("Cache-Control", "no-store"); self.end_headers()
                return self.wfile.write(data)
            if u.path == "/earpiece/earpiece.py":
                return self._send(200, open(os.path.join(EARPIECE_DIR, "earpiece.py"), "rb").read(), "text/plain; charset=utf-8")
            if u.path.startswith("/audio/"):
                name = os.path.basename(u.path)
                p = os.path.join(CACHE, name)
                if name.endswith(".wav") and os.path.exists(p):
                    return self._send(200, open(p, "rb").read(), "audio/wav")
                return self._send(404, "{}")
            if u.path == "/events":
                q = queue.Queue(maxsize=100)
                with hub.lock: hub.clients.add(q)
                self.send_response(200); self.send_header("Content-Type", "text/event-stream"); self.send_header("Cache-Control", "no-store"); self.end_headers()
                try:
                    while True:
                        try: ev = q.get(timeout=0.25 if get_state().get("live") else 2)
                        except queue.Empty: ev = dict(type="state", **state())
                        self.wfile.write(f"data: {json.dumps(ev)}\n\n".encode()); self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, OSError):
                    pass
                finally:
                    with hub.lock: hub.clients.discard(q)
                return
            self._send(404, "{}")

        def do_POST(self):
            """The agent's door: the gt7copilot CLI, run here against the live database. Needs the token when one is set."""
            path = urlparse(self.path).path
            if path == "/api/earpiece":             # the PC earpiece says how it is doing (AirPod, SimHub)
                if earpiece_ok(self.headers) is not True:
                    return self._send(401, '{"error":"bad or missing earpiece token"}')
                try:
                    body = json.loads(self.rfile.read(min(int(self.headers.get("Content-Length", 0)), 20_000)))
                    keep = {k: body.get(k) for k in ("airpod", "device", "simhub", "simhub_api", "simhub_game", "simhub_data", "version", "note", "played", "skipped", "mic", "heard")}
                    if body.get("diag"): diag.update(text=str(body["diag"])[:6000], at=time.time())
                except Exception:
                    return self._send(400, '{"error":"bad report"}')
                earpiece.clear(); earpiece.update(keep, seen=time.time())
                return self._send(200, '{"ok":true}')
            if path == "/api/hear":                 # something the driver said into the earpiece (a WAV from the PC earpiece)
                if earpiece_ok(self.headers) is not True:
                    return self._send(401, '{"error":"bad or missing earpiece token"}')
                why = CFG.why_not("voice_control")
                if why or hear is None:
                    return self._send(409, json.dumps(dict(error=why or "Voice control is not available.")))
                try:
                    wav = self.rfile.read(min(int(self.headers.get("Content-Length", 0)), 2_000_000))
                    return self._send(200, json.dumps(hear(wav)))
                except Exception as e:
                    return self._send(502, json.dumps(dict(error=f"{type(e).__name__}: {e}")))
            if path == "/api/track-name" and earpiece_ok(self.headers) is None:   # anyone who can open the page may name a track
                if self.headers.get("X-GT7C") != "1":
                    return self._json(400, dict(error="missing X-GT7C header"))
                try:
                    body = json.loads(self._body(2_000) or b"{}"); tid = int(body.get("id"))
                except (ValueError, TypeError):
                    return self._json(400, dict(error="bad request"))
                name = str(body.get("name") or "").strip()[:80]
                st = Store()
                if not st.q("SELECT id FROM tracks WHERE id=?", tid):
                    return self._json(404, dict(error="No such track."))
                if name:
                    st.x("UPDATE tracks SET name=?, name_src='you' WHERE id=?", name, tid)
                else:                                    # an empty name takes the name away: the copilot may name it again from its outline
                    st.x("UPDATE tracks SET name=NULL, name_src=NULL WHERE id=?", tid)
                return self._json(200, dict(ok=True, name=name or None))
            if path == "/api/ask" and earpiece_ok(self.headers) is None:      # a question from the page's chat; nothing is stored
                if self.headers.get("X-GT7C") != "1":
                    return self._json(400, dict(error="missing X-GT7C header"))
                try:
                    body = json.loads(self._body(20_000) or b"{}")
                except ValueError:
                    return self._json(400, dict(error="bad request"))
                hist = body.get("h") if isinstance(body.get("h"), list) else []
                where = body.get("where") if isinstance(body.get("where"), dict) else {}
                if ASK.wants_shot(body.get("q")):                  # "take a screenshot": do it, and say what was read
                    return self._json(200, ASK.shot(inbox))
                return self._json(200, ASK.answer(body.get("q"), hist[-6:], where, get_state()))
            if path.startswith(("/api/admin/", "/api/settings")) and earpiece_ok(self.headers) is None:
                return self._admin_post(path)
            if path in ("/api/say", "/api/heartext", "/api/enable", "/api/screenshots/read", "/api/screenshot") and earpiece_ok(self.headers) is None \
                    and not self._own():             # /api/shot has its share token; /share is the phone's share sheet (a plain form)
                return self._json(400, dict(error="missing X-GT7C header"))
            if path in ("/api/say", "/api/heartext", "/api/enable") and earpiece_ok(self.headers) is None:
                qs = parse_qs(urlparse(self.path).query); text = qs.get("text", [""])[0][:300]
                if path == "/api/enable":
                    set_enabled(qs.get("on", ["1"])[0] == "1"); return self._send(200, '{"ok":true}')
                if not text or (path == "/api/heartext" and not hear_text):
                    return self._send(404, "{}")
                if path == "/api/heartext":             # a spoken command, typed (command line)
                    return self._send(200, json.dumps(hear_text(text)))
                say(text, 20.0, "test"); return self._send(200, '{"ok":true}')
            if path == "/api/screenshots/read" and earpiece_ok(self.headers) is None:
                # Read every PS5 capture not read before (?back=1: look through the whole list). Runs in the background;
                # GET /api/screenshots/job follows it.
                if reader is None:
                    return self._json(409, dict(ok=False, reply="Screenshot reading is not available."))
                out = reader.read_new(back=parse_qs(urlparse(self.path).query).get("back", [""])[0] == "1")
                return self._json(200 if out.get("ok") else 409, out)
            if path in ("/api/screenshot", "/api/shot", "/share") and earpiece_ok(self.headers) is None:
                # A picture of a settings or event screen, by one of the inbox routes (inbox.py):
                #   /api/screenshot   the page's file field and the command line (body = the picture), or ?source=phone
                #   /api/shot         an iPhone Shortcut or a script, with the share token (body = the picture, or a form)
                #   /share            the phone's share sheet, through the page installed as an app (a form) -> a small page
                page = path == "/share"
                answer = (lambda code, out: self._send(200, pwa.result_page(out.get("ok"), out.get("reply") or ""), "text/html; charset=utf-8")) if page \
                    else (lambda code, out: self._json(code, out))
                if inbox is None:
                    return answer(409, dict(ok=False, reply="Screenshot reading is not available."))
                route = dict({"/api/shot": "shortcut", "/share": "share"}).get(path, "upload")
                if route == "upload" and parse_qs(urlparse(self.path).query).get("source", [""])[0] == "phone":
                    route = "phone"
                if route == "shortcut":
                    why = INBOX.why_not("shortcut")
                    if why:
                        return answer(409, dict(ok=False, reply=why))
                    got = self.headers.get(SHARE_HEADER) or self.headers.get("Authorization", "").removeprefix("Bearer ").strip()
                    if not hmac.compare_digest(got.encode(), CFG.get("share_token").encode()):
                        return answer(401, dict(ok=False, reply="Wrong or missing share token."))
                try:
                    image = self._body(MAX_IMAGE + 100_000)
                except ValueError:
                    return answer(413, dict(ok=False, reply="That picture is too large. The limit is 12 MB."))
                name = ""
                ctype = self.headers.get("Content-Type", "")
                if ctype.lower().startswith("multipart/form-data"):
                    image, name = INBOX.from_form(ctype, image)
                if image and len(image) > MAX_IMAGE:
                    return answer(413, dict(ok=False, reply="That picture is too large. The limit is 12 MB."))
                out = inbox.submit(None if route == "phone" else (image or b""), route, name)
                return answer(200 if out.get("ok") else 409, out)
            if path != "/api/cli" or earpiece_ok(self.headers) is not None:
                return self._send(404, "{}")
            why = CFG.why_not("agent_door")
            if why:
                return self._send(403, json.dumps(dict(error=why + " The agent door is shut.")))
            if not hmac.compare_digest(self.headers.get("Authorization", "").encode(), ("Bearer " + CFG.get("agent_token")).encode()):
                return self._send(401, '{"error":"bad or missing token"}')
            try:
                body = json.loads(self.rfile.read(min(int(self.headers.get("Content-Length", 0)), 17_000_000)))
                argv = list(body["argv"]); at = dict(cli.FILE_ARG, **{"shot-file": 0}).get(argv[0] if argv and isinstance(argv[0], str) else "")
                if at is not None and not isinstance((argv[1:] + [None] * 2)[at], dict):      # over the network no file of this machine is read
                    return self._send(400, json.dumps(dict(error="send the JSON, not a path")))
                out = cli.run(Store(), argv)
                if out is None:
                    return self._send(400, json.dumps(dict(error="unknown command", usage=cli.__doc__)))
                return self._send(200, json.dumps(out, default=str))
            except Exception as e:
                return self._send(400, json.dumps(dict(error=f"{type(e).__name__}: {e}")))

    srv = ThreadingHTTPServer(("0.0.0.0", port), H); srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv
