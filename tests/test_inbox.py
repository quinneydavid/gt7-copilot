"""The screenshot inbox: the share sheet, the Shortcut with its share token, the watched folder (a half-written file
included), each route's own switch, the results kept for the page, and the spoken result while a session is live."""
import json, os, shutil, sys, tempfile, time, urllib.error, urllib.request
tmp = tempfile.mkdtemp()
for k in [k for k in os.environ if k.startswith("GT7C_")]:
    del os.environ[k]
os.environ.update(GT7C_DATA=tmp)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [ROOT, os.path.join(ROOT, "tests")]
from gt7copilot import inbox as INBOX, pwa, server, settings as CFG

ok = lambda cond, what: (print(("ok   " if cond else "FAIL ") + what), cond or sys.exit(1))
PNG = b"\x89PNG\r\n\x1a\n" + b"p" * 64
JPG = b"\xff\xd8\xff" + b"j" * 64

read, said, live = [], [], {"on": False}
def shot(image):                                   # the stand-in reader: Voice.shot's shape
    read.append(image)
    return dict(ok=True, reply="Sheet filed for the test car.") if image != JPG + b"bad" else dict(ok=False, reply="I could not read that sheet cleanly.")
box = INBOX.Inbox(shot, lambda text, ttl, kind: said.append(text), lambda: live["on"], lambda m: None)
PORT = 18781; URL = f"http://127.0.0.1:{PORT}"
server.serve(PORT, server.Hub(), lambda: dict(live=False), lambda *a: None, lambda on: None, inbox=box)


def post(path, body, headers=None):
    try:
        with urllib.request.urlopen(urllib.request.Request(URL + path, data=body, headers=headers or {}, method="POST"), timeout=10) as r:
            raw = r.read(); return r.status, (json.loads(raw) if raw[:1] == b"{" else raw.decode())
    except urllib.error.HTTPError as e:
        raw = e.read(); return e.code, (json.loads(raw) if raw[:1] == b"{" else raw.decode())

def form(image, name="shot.png", field="image"):
    b = "xXboundaryXx"
    body = (f'--{b}\r\nContent-Disposition: form-data; name="title"\r\n\r\nGran Turismo 7\r\n'
            f'--{b}\r\nContent-Disposition: form-data; name="{field}"; filename="{name}"\r\nContent-Type: image/png\r\n\r\n').encode() + image + f"\r\n--{b}--\r\n".encode()
    return body, {"Content-Type": f"multipart/form-data; boundary={b}"}

# ---- everything off ----------------------------------------------------------------------------------------------------
st, d = post("/api/shot", PNG, {"X-GT7C-Share": "x"}); ok(st == 409 and d["reply"] == "Screenshots are turned off in Settings.", "screenshots off: the Shortcut door says so")
st, page = post("/share", *form(PNG)); ok(st == 200 and "Screenshots are turned off in Settings." in page and "<html" in page, "...and the share sheet gets a page saying so")
CFG.save(dict(screenshots_on=True, llm_url="http://127.0.0.1:1/v1", vision_model="seer"))
st, d = post("/api/shot", PNG, {"X-GT7C-Share": "x"}); ok(st == 409 and d["reply"] == "Pictures from a Shortcut are turned off in Settings.", "the Shortcut route has its own switch")
st, page = post("/share", *form(PNG)); ok("Sharing from a phone is turned off in Settings." in page, "the share sheet has its own switch")
ok(box.scan() == 0 and INBOX.why_not("folder") == "The watched folder is turned off in Settings.", "the folder has its own switch")
ok(INBOX.why_not("upload") is None, "uploading on the page is on from the start")
ok(post("/api/screenshot", PNG)[0] == 400 and post("/api/screenshots/read", b"")[0] == 400, "an upload without the page's own header (another site's form) is refused")
PAGE = {"X-GT7C": "1"}
CFG.save(dict(upload_on=False)); st, d = post("/api/screenshot", PNG, PAGE); ok(st == 409 and d["reply"] == "Uploading pictures is turned off in Settings.", "...and can be switched off")
CFG.save(dict(upload_on=True)); ok(not read, "nothing was read while the routes were off")

# ---- the Shortcut: share token -----------------------------------------------------------------------------------------
CFG.save(dict(shortcut_on=True))
st, d = post("/api/shot", PNG, {"X-GT7C-Share": ""}); ok(st == 409 and d["reply"] == "The share token is not set in Settings.", "on without a token: says what is missing")
CFG.save(dict(generate=["share_token"])); tok = CFG.get("share_token")
ok(len(tok) > 20 and tok not in json.dumps(CFG.view()), "the share token is generated and never shown in the settings view")
ok(post("/api/shot", PNG)[0] == 401 and post("/api/shot", PNG, {"X-GT7C-Share": "wrong"})[0] == 401, "no token or a wrong token is refused")
st, d = post("/api/shot", PNG, {"X-GT7C-Share": tok}); ok(st == 200 and d["ok"] and read[-1] == PNG, "the right token: the picture (sent as the request body) is read")
st, d = post("/api/shot", JPG, {"Authorization": "Bearer " + tok}); ok(st == 200 and read[-1] == JPG, "the token also works as a bearer token")
body, h = form(PNG + b"2", "IMG_0001.png", "file"); st, d = post("/api/shot", body, dict(h, **{"X-GT7C-Share": tok}))
ok(st == 200 and read[-1] == PNG + b"2", "a picture sent as a form field is read too")
st, d = post("/api/shot", b"not a picture", {"X-GT7C-Share": tok}); ok(st == 409 and "not a picture" in d["reply"], "something that is not a picture is refused")
st, d = post("/api/cli", json.dumps(dict(argv=["tracks"])).encode(), {"Authorization": "Bearer " + tok}); ok(st in (401, 403), "the share token opens nothing else")
old = tok; CFG.save(dict(generate=["share_token"])); ok(post("/api/shot", PNG, {"X-GT7C-Share": old})[0] == 401, "after a rotation the old token stops working")
tok = CFG.get("share_token")

# ---- the share sheet ---------------------------------------------------------------------------------------------------
CFG.save(dict(share_on=True))
st, page = post("/share", *form(PNG + b"3", "ps-app.png")); ok(st == 200 and "Picture read" in page and "Sheet filed for the test car." in page and read[-1] == PNG + b"3", "a shared picture is read and the phone gets a result page")
st, page = post("/share", *form(JPG + b"bad")); ok("Picture not filed" in page and "could not read that sheet cleanly" in page, "a picture that cannot be filed says why on that page")
st, page = post("/share", *form(b"hello", "note.txt")); ok("No picture was sent." in page, "a share without a picture says so")
m = json.loads(urllib.request.urlopen(URL + "/manifest.webmanifest").read()); t = m["share_target"]
ok(t["action"] == "/share" and t["method"] == "POST" and t["enctype"] == "multipart/form-data" and t["params"]["files"][0]["name"] == "image", "the manifest offers the page as a share target for pictures")
ok(urllib.request.urlopen(URL + "/sw.js").headers["Content-Type"].startswith("text/javascript") and urllib.request.urlopen(URL + "/icon-192.png").read()[:8] == b"\x89PNG\r\n\x1a\n"
   and len(pwa.icon(512)) > 500, "the worker and the icons an installable page needs are served")
ok(b'rel="manifest"' in urllib.request.urlopen(URL + "/").read(), "the page links its manifest")

# ---- the watched folder ------------------------------------------------------------------------------------------------
folder = os.path.join(tmp, "inbox")
CFG.save(dict(folder_on=True)); ok(INBOX.folder_path() == folder, "the folder defaults to inbox in the data folder")
box.scan(); ok(os.path.isdir(folder), "the folder is made when the route is switched on")
part = os.path.join(folder, "sync.jpg"); open(part, "wb").write(JPG[:20]); n0 = len(read); t = time.time()
ok(box.scan(t) == 0, "a new file is not read at once")
open(part, "ab").write(JPG[20:] + b"4")
ok(box.scan(t + 3) == 0 and len(read) == n0, "a file still being written (its size changed) is left alone")
ok(box.scan(t + 4) == 0, "...and waits until its size has stood still for a moment")
ok(box.scan(t + 6) == 1 and read[-1] == JPG + b"4", "then it is read, whole")
ok(not os.path.exists(part) and os.path.exists(os.path.join(folder, "done", "sync.jpg")), "a read picture moves to done")
ok(box.scan(t + 20) == 0 and len(read) == n0 + 1, "nothing in done is read again")
for name, data in (("bad.jpg", JPG + b"bad"), ("notes.txt", b"hello"), (".hidden.png", PNG), ("fake.png", b"not a picture")):
    open(os.path.join(folder, name), "wb").write(data)
box.scan(t + 30); box.scan(t + 40)
ok(os.path.exists(os.path.join(folder, "failed", "bad.jpg")) and "could not read" in open(os.path.join(folder, "failed", "bad.jpg.txt")).read(), "a picture that cannot be filed moves to failed with the reason beside it")
ok("not a picture" in open(os.path.join(folder, "failed", "fake.png.txt")).read(), "a file that only looks like a picture goes to failed too")
ok(os.path.exists(os.path.join(folder, "notes.txt")) and os.path.exists(os.path.join(folder, ".hidden.png")), "other files and hidden files are left alone")
open(os.path.join(folder, "sync.jpg"), "wb").write(JPG + b"5"); box.scan(t + 50); box.scan(t + 60)
ok(len([n for n in os.listdir(os.path.join(folder, "done")) if n.startswith("sync")]) == 2, "a second file with the same name does not overwrite the first")
CFG.save(dict(folder_on=False)); open(os.path.join(folder, "later.png"), "wb").write(PNG); box.scan(t + 70); box.scan(t + 80)
ok(os.path.exists(os.path.join(folder, "later.png")), "switched off, pictures stay where they are")
other = os.path.join(tmp, "elsewhere"); CFG.save(dict(folder_on=True, folder_path=other)); box.scan(t + 90)
ok(os.path.isdir(other) and INBOX.folder_path() == other, "the folder can be moved in Settings")
try: CFG.save(dict(folder_path="relative/path")); ok(False, "relative path")
except ValueError: ok(True, "a folder that is not a full path is refused")

# ---- results for the page, and the voice -------------------------------------------------------------------------------
s = json.loads(urllib.request.urlopen(URL + "/api/inbox").read())
ok(s["recent"][0]["route"] == "folder" and s["recent"][0]["name"] == "sync.jpg" and s["recent"][0]["ok"] and s["recent"][0]["reply"], "the page gets the last results, newest first, with the route")
ok({r["route"] for r in s["recent"]} <= set(INBOX.ROUTES.values()) and len(s["recent"]) <= 8, "...a short list")
ok(s["routes"]["shortcut"]["on"] and s["routes"]["share"]["on"] and not s["routes"]["phone"]["on"] and "virtual phone is turned off" in s["routes"]["phone"]["why"], "...and how each route stands")
ok(json.load(open(os.path.join(tmp, "inbox-log.json")))[-1]["route"] == "folder" and len(INBOX.Inbox(shot).items) == len(box.items), "results survive a restart")
ok(not said, "nothing is said while no session is live")
live["on"] = True; post("/api/shot", PNG, {"X-GT7C-Share": tok}); ok(said == ["Sheet filed for the test car."], "while a session is live the result is said in one line")
st, d = post("/api/screenshot?source=phone", b"", PAGE); ok(st == 409 and "virtual phone is turned off" in d["reply"], "the phone route still answers through the same door")
shutil.rmtree(tmp); print("inbox: all passed")
