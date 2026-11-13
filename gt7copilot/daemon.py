#!/usr/bin/env python3
"""gt7copilotd: listens to the PS5, records laps, runs the copilot and serves the copilot page."""
import os, socket, threading, time
from .collector import Collector, name_tracks
from .copilot import Copilot
from .packet import decrypt, parse
from .server import Hub, serve
from .store import Store
from .tts import TTS
from .voice import Voice
from .checks import TESTS
from .inbox import Inbox
from . import __version__, settings as CFG

PORT = int(os.environ.get("GT7C_PORT", "8765"))


def log(msg):
    print(time.strftime("%H:%M:%S"), msg, flush=True)


class Link:
    """The telemetry socket's view of the console: where packets come from and when, for the Settings tab's Test and Find."""
    def __init__(self):
        self.seen = {}            # source address -> time of its last readable packet
        self.unread = {}          # source address -> time of its last packet that could not be read
        self.ask = []             # addresses to send one heartbeat to right away (Test / Find)
        self.error = None         # the last send error, as text
        self.last = 0.0           # time of the last readable telemetry packet from anywhere
        self.power = None         # "on" | "rest" | "off" | None (not asked yet): the console's answer to a status question
        self.name = None          # the console's own name, from that answer
        self.misses = 0

    POWER_PORT = 9302             # the console's device discovery port (the one the PlayStation App and Remote Play ask)

    def ask_power(self, addr, timeout=2.0):
        """Ask the console whether it is on. Returns ("on" | "rest", its name) or (None, None) when nothing answers."""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as q:
                q.settimeout(timeout)
                q.sendto(b"SRCH * HTTP/1.1\ndevice-discovery-protocol-version:00030010\n", (addr, self.POWER_PORT))
                text = q.recvfrom(2048)[0].decode("utf-8", "replace")
        except OSError:
            return None, None
        head = text.split("\n", 1)[0]
        name = next((l.split(":", 1)[1].strip() for l in text.splitlines() if l.lower().startswith("host-name:")), None)
        return ("on" if " 200 " in head + " " else "rest" if " 620 " in head + " " else None), name

    def check_power(self):
        """One round: ask, and call the console off only after three questions without an answer."""
        addr = str(CFG.get("ps5") or "").strip()
        if not addr:
            self.power = self.name = None; return
        power, name = self.ask_power(addr)
        if power:
            self.power, self.name, self.misses = power, name or self.name, 0
        else:
            self.misses += 1
            if self.misses >= 3: self.power = "off"

    def watch_power(self, every=10.0):
        def loop():
            while True:
                try: self.check_power()
                except Exception: pass
                time.sleep(every)
        threading.Thread(target=loop, daemon=True).start()

    def console(self):
        """For the page: is the console on, and is Gran Turismo 7 sending data. Telemetry arriving proves it is on, whatever
        the status question said (a network may let the telemetry through and not the question)."""
        game = time.time() - self.last < 5
        return dict(power="on" if game else self.power, name=self.name, game=game)

    def test(self, body):
        """Send a heartbeat to the address on the form (saved or not) and wait for packets from it."""
        addr = str(body.get("address") or CFG.get("ps5") or "").strip()
        if not addr:
            return dict(ok=False, note="Type the console's address first, or press Find.")
        try:
            addr = socket.gethostbyname(addr)
        except OSError:
            return dict(ok=False, note=f"The name {addr} does not resolve to an address.")
        t0 = time.time(); self.ask.append(addr)
        while time.time() - t0 < 4:
            if self.seen.get(addr, 0) >= t0:
                return dict(ok=True, note=f"Telemetry is arriving from {addr}.")
            time.sleep(0.2)
        if self.unread.get(addr, 0) >= t0:
            return dict(ok=False, note=f"Packets arrive from {addr} but cannot be read. Try packet type A.")
        if self.error:
            return dict(ok=False, note=f"The heartbeat could not be sent to {addr}: {self.error}")
        return dict(ok=False, note=f"No telemetry from {addr} in 4 seconds. Gran Turismo 7 must be running (in a race or on track), "
                                   "and UDP port 33740 must reach this machine.")

    def find(self, body):
        """Ask the whole local network once and report who answers. Only reaches the console when this program shares its
        network (host networking); inside a container network the broadcast stays in the container network."""
        t0 = time.time(); self.ask.append("255.255.255.255")
        while time.time() - t0 < 4:
            got = [a for a, t in self.seen.items() if t >= t0]
            if got:
                return dict(ok=True, address=got[0], note=f"A console running Gran Turismo 7 answered from {got[0]}.")
            time.sleep(0.2)
        return dict(ok=False, note="Nothing answered. Gran Turismo 7 must be running, and Find only works when the copilot is on the "
                                   "same network as the console (host networking). The address is in the console's network settings.")


def main():
    hub = Hub()
    tts = TTS(lambda text, name, kind, deadline: (log(f"say[{kind}]: {text}"),
                                                  hub.publish(dict(type="say", text=text, kind=kind, url=name and f"/audio/{name}", deadline=deadline))), log)
    store = Store()
    col = Collector(store, log)
    try: name_tracks(store, log)
    except Exception as e: log(f"naming tracks failed: {e!r}")
    co = Copilot(tts.say, log); col.listeners.append(co)
    co.enabled = bool(CFG.get("copilot_on"))
    voice = Voice(col, co, tts.say, hub, log, store)
    link = Link()
    inbox = Inbox(voice.shot, tts.say, lambda: col.live, log, store); voice.inbox = inbox; inbox.watch()
    CFG.on_change(lambda changed: setattr(co, "enabled", bool(CFG.get("copilot_on"))) if "copilot_on" in changed else None)
    serve(PORT, hub, lambda: dict(col.state(), copilot=co.enabled, delta=co.delta if col.live else None, console=link.console()), tts.say, lambda on: setattr(co, "enabled", on),
          hear=voice.hear, hear_text=voice.hear_text, inbox=inbox, reader=voice,
          tests=dict(console=link.test, find=link.find, **{k: (lambda body, fn=fn: fn()) for k, fn in TESTS.items()}))
    link.watch_power()
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    s.bind(("0.0.0.0", 33740)); s.settimeout(1)
    log(f"gt7copilotd {__version__} up: console {CFG.get('ps5') or '(not set: open Settings on the page)'}, page on :{PORT}")
    last_hb = last_pkt = 0.0; undecoded = 0; target = None; hb = b"B"
    while True:
        now = time.time()
        ps5, want = CFG.get("ps5"), str(CFG.get("heartbeat")).encode()
        if (ps5, want) != target:                        # the address or packet type was changed in Settings
            target, hb, undecoded, last_hb = (ps5, want), want, 0, 0.0
        while link.ask:
            try: s.sendto(hb, (link.ask.pop(0), 33739)); link.error = None
            except OSError as e: link.error = str(e)
        if ps5 and now - last_hb > (1.0 if now - last_pkt < 5 else 5.0):
            try: s.sendto(hb, (ps5, 33739))
            except OSError as e: link.error = str(e)
            last_hb = now
        try: pkt, src = s.recvfrom(4096)
        except socket.timeout: continue
        d = decrypt(pkt)
        if not d:
            undecoded += 1; link.unread[src[0]] = time.time()
            if undecoded == 300 and hb != b"A":          # ~5 s of packets we cannot read: ask for the plain kind instead
                log(f"cannot read heartbeat-{hb.decode()} packets ({len(pkt)} bytes): falling back to A (no steering data)"); hb = b"A"
            continue
        undecoded = 0
        last_pkt = time.time(); link.seen[src[0]] = link.last = last_pkt
        try:
            row, meta = parse(d); col.feed(row, meta, last_pkt)
        except Exception as e:                       # never let one bad frame stop the recorder
            log(f"frame error: {e!r}")


if __name__ == "__main__":
    main()
