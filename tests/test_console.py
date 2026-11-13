"""The console's power state: the copilot asks the console's discovery port and reads On / Rest mode / Off from the answer.
A stand-in console answers on a local port."""
import os, sys, socket, tempfile, threading, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["GT7C_DATA"] = tempfile.mkdtemp()
from gt7copilot import daemon as D
CFG = D.CFG

def ok(c, what):
    print(("ok   " if c else "FAIL ") + what)
    if not c: sys.exit(1)

srv = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); srv.bind(("127.0.0.1", 0)); srv.settimeout(0.2)
answer = {"line": b"HTTP/1.1 200 Ok"}
def console():
    while True:
        try: q, src = srv.recvfrom(2048)
        except socket.timeout: continue
        if q.startswith(b"SRCH") and answer["line"]:
            srv.sendto(answer["line"] + b"\nhost-id:AA\nhost-type:PS5\nhost-name:PS5-test\n", src)
threading.Thread(target=console, daemon=True).start()

link = D.Link(); link.POWER_PORT = srv.getsockname()[1]
ok(link.ask_power("127.0.0.1", 1) == ("on", "PS5-test"), "a console that is on answers 200: on, with its name")
answer["line"] = b"HTTP/1.1 620 Server Standby"
ok(link.ask_power("127.0.0.1", 1)[0] == "rest", "a console in rest mode answers 620: rest")
answer["line"] = None
ok(link.ask_power("127.0.0.1", 0.3) == (None, None), "no answer: unknown")

real = CFG.get
CFG.get = lambda k: "127.0.0.1" if k == "ps5" else real(k)
link.ask_power = lambda addr, timeout=0.3, f=link.ask_power: f(addr, 0.3)
answer["line"] = b"HTTP/1.1 200 Ok"; link.check_power()
ok(link.console() == dict(power="on", name="PS5-test", game=False), "the page gets: on, its name, no game data")
answer["line"] = None; link.check_power(); link.check_power()
ok(link.power == "on", "two unanswered questions do not yet mean off")
link.check_power(); ok(link.console()["power"] == "off", "three do")
link.last = time.time()
ok(link.console() == dict(power="on", name="PS5-test", game=True), "telemetry arriving proves it is on, and the game is sending")
print("console: all passed")
