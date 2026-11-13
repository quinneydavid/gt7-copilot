#!/usr/bin/env python3
"""Take the pictures in docs/images again, after the page has changed.

  pip install numpy pycryptodome playwright pillow && playwright install chromium     # in a virtual environment
  python3 tools/demo/shots.py                    # about three minutes; writes docs/images/*.png

It fills a throw-away data folder with make_demo.py, starts the copilot on it, drives the simulated car (sim.py) so the
Live page has a car on track, and photographs the pages with a headless browser. The Ask picture is answered by a
stand-in for the model that runs inside this script: no model, console or network is needed.

Uses UDP port 33740 (the copilot's telemetry port: stop a copilot that runs on this machine first) and TCP 18765, 18766.
GT7C_CHROME names a browser to use instead of Playwright's own. --only live,ask takes just those pictures."""
import argparse, io, json, os, shutil, subprocess, sys, tempfile, threading, time, urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path[:0] = [ROOT, HERE]
import sim                                           # noqa: E402

PAGE, MODEL = 18765, 18766
URL = f"http://127.0.0.1:{PAGE}"
PASSWORD = "demo-password"
GR86 = 3481
SHOTS = ("live", "sessions", "session", "tune", "settings", "ask", "phone")
answer = ["(no answer made yet)"]                    # what the stand-in model says


class Model(BaseHTTPRequestHandler):
    """The stand-in for the chat model: one answer, whatever is asked."""
    def log_message(self, *a): pass

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length", 0)))
        body = json.dumps(dict(choices=[dict(message=dict(role="assistant", content=answer[0]))])).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(body)))
        self.end_headers(); self.wfile.write(body)


def get(path):
    return json.load(urllib.request.urlopen(URL + path, timeout=10))


def wait_for(what, test, seconds, every=0.1):
    end = time.time() + seconds
    while time.time() < end:
        try:
            got = test()
            if got: return got
        except OSError:
            pass
        time.sleep(every)
    raise SystemExit(f"Gave up waiting for {what}.")


def save(png, path):
    """Write the picture with a 256-colour palette when Pillow is there: the page is flat colour, the file a third of the size."""
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(png)).convert("RGB")
        img.quantize(256, method=Image.Quantize.FASTOCTREE, dither=Image.Dither.NONE).save(path, optimize=True)
    except ImportError:
        open(path, "wb").write(png)
    print(f"  {os.path.relpath(path, ROOT)}  {os.path.getsize(path) // 1024} KB", flush=True)


def the_answer(d):
    """A plain answer from the session's own figures, as the model would word them."""
    cause = dict(brake_early="you brake too early there", brake_late="you brake too late there", apex_slow="you are slow at the apex",
                 throttle_late="you are late on the throttle", exit_slow="the exit is slow", time="it is a little slow all the way through")
    top = lambda c: cause.get(max(c["main_causes"], key=c["main_causes"].get, default="time"), cause["time"])
    a, b = d["corners"][0], d["corners"][1]
    return (f"Most of it is in two corners. Turn {a['turn']} costs {a['avg_loss_s']:.2f} s a lap on average: {top(a)}. "
            f"Turn {b['turn']} costs {b['avg_loss_s']:.2f} s: {top(b)}. Your best lap was {d['best']['time']} and the best of each corner "
            f"added up gives {d['ideal_lap']}, so the pace is there. Work on turn {a['turn']} first.")


def main():
    ap = argparse.ArgumentParser(description="Take the README pictures from simulated demo data.")
    ap.add_argument("--out", default=os.path.join(ROOT, "docs", "images"))
    ap.add_argument("--only", default="", help="comma separated: " + ", ".join(SHOTS))
    a = ap.parse_args()
    want = [s for s in a.only.split(",") if s] or list(SHOTS)
    from playwright.sync_api import sync_playwright
    os.makedirs(a.out, exist_ok=True)
    data = tempfile.mkdtemp(prefix="gt7c-demo-")
    env = dict(os.environ, GT7C_DATA=data, PYTHONDONTWRITEBYTECODE="1")
    subprocess.run([sys.executable, os.path.join(HERE, "make_demo.py"), data], check=True, env=env)
    threading.Thread(target=HTTPServer(("127.0.0.1", MODEL), Model).serve_forever, daemon=True).start()
    # What a first start would be given: an example console address, Ask switched on with example names. No keys, no tokens.
    env.update(GT7C_PORT=str(PAGE), GT7C_ADMIN_PASSWORD=PASSWORD, GT7C_PS5="192.0.2.20", GT7C_ASK_ON="1",
               GT7C_LLM_URL="http://ollama:11434/v1", GT7C_VISION_MODEL="qwen2.5vl")
    app = subprocess.Popen([sys.executable, "-m", "gt7copilot.daemon"], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    try:
        wait_for("the copilot to start", lambda: get("/healthz"), 30)
        tsukuba = next(t["id"] for t in get("/api/tracks") if t["name"] == "Tsukuba Circuit")
        past = next(s["id"] for s in get("/api/sessions") if s["car_code"] == GR86 and s["track_id"] == tsukuba)     # the newest one on file
        answer[0] = the_answer(get(f"/api/session?id={past}"))
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=os.environ.get("GT7C_CHROME") or None)
            ctx = browser.new_context(viewport=dict(width=1280, height=800), device_scale_factor=2, color_scheme="dark")
            page = ctx.new_page()
            page.goto(URL + "/#live"); page.wait_for_selector("#liveTiles .tile")

            def show(hash_, ready):
                page.evaluate("h => { location.hash = h }", hash_); page.wait_for_selector(ready); page.wait_for_timeout(700)

            def shot(name, until=None, target=page):
                """The page from its top down to the end of the card that holds `until` (or one screen). The window is made that
                tall for the picture, so the Ask button sits in the corner and not in the middle of the page."""
                if name not in want:
                    return
                size = target.viewport_size
                if until:
                    bottom = target.evaluate("s => { const e = document.querySelector(s); return (e.closest('.card') || e).getBoundingClientRect().bottom + scrollY }", until)
                    target.set_viewport_size(dict(width=size["width"], height=int(bottom) + 10)); target.wait_for_timeout(400)
                save(target.screenshot(), os.path.join(a.out, name + ".png"))
                target.set_viewport_size(size)

            # The car goes out: a race of twelve laps at Tsukuba, the first four sent quickly so there is a best lap to compare with.
            car = threading.Thread(target=sim.send, daemon=True, kwargs=dict(
                fast_laps=4, track="Tsukuba Circuit", car=GR86, laps=12, race=True,
                driver=dict(seed=21, wheelspin=0.7, understeer=0.8, front_lock=0.9, learn=0.015, weak={0: (14, 6), 5: (9, 4)}, late={2: (9, 4)})))
            car.start()
            wait_for("the car to be on its sixth lap", lambda: (get("/api/state").get("lap") or 0) >= 6, 240, 1)

            def mid_lap():                           # on a straight, at speed, with the gap to the best lap worked out
                s = get("/api/state"); n = s.get("now") or {}
                return s.get("delta") is not None and n.get("kmh", 0) > 150 and n.get("thr", 0) > 90
            wait_for("a good moment on track", mid_lap, 120, 0.05)
            page.wait_for_timeout(300)
            shot("live", "#log")
            show("sessions", "#sList .row, #sList a")
            shot("sessions")
            show(f"sessions/{past}", "#cTrace svg")
            shot("session", "#cTrace")
            show(f"cars/{GR86}/suggested?session={past}", ".gtbox")
            shot("tune", ".gt")
            show("settings", "#pw")
            page.fill("#pw", PASSWORD); page.click("#pwGo"); page.wait_for_selector("[data-group=Console]"); page.wait_for_timeout(500)
            shot("settings", "[data-group=\"Voice control\"]")
            if "ask" in want:                        # only now is the app pointed at the stand-in model
                page.evaluate("u => adminPost('/api/settings', {llm_url: u})", f"http://127.0.0.1:{MODEL}/v1")
                show(f"sessions/{past}", "#cTrace svg")
                page.click("#askBtn"); page.fill("#askQ", "Where am I losing the most time?"); page.click("#askGo")
                page.wait_for_selector("#askLog .a:not(.wait)"); page.wait_for_timeout(500)
                shot("ask")
            if "phone" in want:
                phone = browser.new_context(viewport=dict(width=390, height=844), device_scale_factor=2, color_scheme="dark", is_mobile=True, has_touch=True).new_page()
                phone.goto(URL + "/#home"); phone.wait_for_selector(".tile"); phone.wait_for_timeout(1200)
                shot("phone", None, phone)
            browser.close()
    finally:
        app.terminate(); app.wait(10)
        shutil.rmtree(data, ignore_errors=True)
    print("Done. Look at every picture before it goes into the repository.")


if __name__ == "__main__":
    main()
