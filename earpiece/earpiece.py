#!/usr/bin/env python3
"""GT7 Copilot earpiece: plays the copilot's calls into one audio device (for example one earbud) on a sim PC or a
Mac, without a browser.

  earpiece.py run       listen to the server, play each call into the device, keep the device connected,
                        (Windows) start SimHub if it is not running, tell the server how things are (default)
  earpiece.py supervise run the earpiece and start it again whenever it stops (what the Windows system task runs: the
                        Windows sound and Bluetooth calls can take the whole process down, 0xC0000005 on 11 Nov 2026).
                        On a Mac launchd does this job.
  earpiece.py listen    the microphone half of voice control, as its own process (started by run). Recording and
                        playing in ONE process failed on the build PC (every call "could not play" while the mic was
                        open, 12 Nov 2026); a second process playing while the first held the mic worked.
  earpiece.py doctor    print what this machine looks like to the earpiece (audio devices, the device, SimHub, the server)
  earpiece.py connect   ask the system once to connect the device
  earpiece.py test      say one test line through the device

Config: earpiece.json in the home folder  {url, token, device, volume, voice, connect_when, simhub_path, start_simhub, simhub_api}
        Windows: %LOCALAPPDATA%\\GT7Copilot      Mac: ~/Library/Application Support/GT7Copilot
        volume = the device's system volume (0-1), set and unmuted each time it connects (Windows only; a silent
        earbud on the first night was exactly this). null = leave it alone.
        voice = listen on the device's microphone and send what is said to the server (voice control). The open
        microphone puts a Bluetooth earbud in call mode, so the copilot's own voice sounds like a phone call.
Log:    Windows: earpiece.log in the home folder.   Mac: ~/Library/Logs/GT7Copilot/earpiece.log

Windows: installed by setup.ps1 (downloaded from the copilot page) as a scheduled task that runs as SYSTEM from boot,
NOT inside the user's sign-in: in a Remote Desktop or other remote session Windows shows only "Remote Audio" and hides the
earbud (found on the build PC, 11 Nov 2026); a system task keeps the PC's real sound devices. A system task cannot
open desktop programs, so there it only reports whether SimHub runs.
Mac: installed by setup-mac.sh as a LaunchAgent of the signed-in user: sound devices and the microphone permission
belong to the user's session there. Written from the documentation; not yet run on a real Mac.
`--home DIR` says where the config lives."""
import io, json, logging, logging.handlers, os, queue, subprocess, sys, threading, time, urllib.error, urllib.request, wave

VERSION = "0.3.4"
MAC = sys.platform == "darwin"
HOME = os.environ.get("GT7C_EARPIECE_HOME") or (os.path.expanduser("~/Library/Application Support/GT7Copilot") if MAC else
                                                os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "GT7Copilot"))


def log_file():
    if MAC:
        d = os.path.expanduser("~/Library/Logs/GT7Copilot"); os.makedirs(d, exist_ok=True)
        return os.path.join(d, "earpiece.log")
    return os.path.join(HOME, "earpiece.log")


def pid_alive(pid):
    try:
        import psutil
        return psutil.pid_exists(pid)
    except ImportError:                      # the Mac install has no psutil
        try: os.kill(pid, 0); return True
        except PermissionError: return True
        except OSError: return False
DEFAULTS = dict(url="", token="", device="AirPods", simhub_path=r"C:\Program Files (x86)\SimHub\SimHubWPF.exe",
                start_simhub=True, simhub_api="http://127.0.0.1:8888", volume=0.6, voice=True, connect_when="always")        # connect_when: always (the AirPod is only for this) | live (only while GT7 sends data) | never
HEADER = "X-GT7C-Earpiece"
log = logging.getLogger("earpiece")


def config():
    cfg = dict(DEFAULTS)
    try:
        cfg.update(json.load(open(os.path.join(HOME, "earpiece.json"), encoding="utf-8-sig")))
    except FileNotFoundError:
        pass
    cfg["url"] = (os.environ.get("GT7C_URL") or cfg["url"]).rstrip("/")
    cfg["token"] = os.environ.get("GT7C_EARPIECE_TOKEN") or cfg["token"]
    return cfg


def request(cfg, path, body=None, timeout=10, raw=None):
    data = raw if raw is not None else (None if body is None else json.dumps(body).encode())
    req = urllib.request.Request(cfg["url"] + path, data=data,
                                 headers={HEADER: cfg["token"], "Content-Type": "audio/wav" if raw is not None else "application/json"})
    return urllib.request.urlopen(req, timeout=timeout)


# ---------------------------------------------------------------- Windows: audio device, Bluetooth, SimHub

class WindowsPC:
    """Everything that touches Windows. Each method is safe to call from any thread."""

    def __init__(self, cfg):
        self.cfg = cfg; self.name = cfg["device"].lower(); self.lock = threading.Lock(); self.mic = None

    # -- the AirPod's microphone (voice control)
    def mic_start(self, on_frames):
        """Open the AirPod's microphone: on_frames(int16 mono samples at 16 kHz) is called every 100 ms."""
        import sounddevice as sd
        with self.lock:
            if self.mic is not None:
                return True
            sd._terminate(); sd._initialize(); apis = sd.query_hostapis()
            for i, d in enumerate(sd.query_devices()):
                if d["max_input_channels"] > 0 and self.name in d["name"].lower() and "WASAPI" in apis[d["hostapi"]]["name"]:
                    st = sd.InputStream(device=i, channels=1, samplerate=16000, dtype="int16", blocksize=1600,
                                        callback=lambda data, n, t, status: on_frames(data[:, 0].copy()),
                                        extra_settings=sd.WasapiSettings(auto_convert=True))
                    st.start(); self.mic = st; log.info("microphone open: %s", d["name"]); return True
            return False

    def mic_alive(self):
        return self.mic is not None and self.mic.active

    def mic_stop(self):
        with self.lock:
            st, self.mic = self.mic, None
        try:
            if st: st.abort(); st.close()
        except Exception:
            pass

    # -- the AirPod as Windows sees it
    def endpoints(self):
        """Every playback device Windows knows, connected or not: [(name, active, id)]. Best effort: a Bluetooth
        device that is away often has no readable name."""
        import warnings, comtypes
        from pycaw.pycaw import AudioUtilities
        comtypes.CoInitialize()
        out = []
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            coll = AudioUtilities.GetDeviceEnumerator().EnumAudioEndpoints(0, 0xF)      # 0 = playback, 0xF = any state
            for i in range(coll.GetCount()):
                try:
                    d = AudioUtilities.CreateDevice(coll.Item(i))
                    st = getattr(d.state, "value", d.state)
                    out.append((d.FriendlyName or "", st == 1 or str(d.state).endswith("Active"), d.id or ""))
                except Exception as e:
                    out.append((f"(unreadable: {type(e).__name__})", False, ""))
        return out

    def airpod(self):
        """(connected, name). Connected = the player can open it right now, which is the thing that matters."""
        with self.lock:
            found = self._output()
        if found and found[2]:
            return True, found[1]["name"]
        try:
            for n, a, _ in self.endpoints():
                if self.name in n.lower() and "hands-free" not in n.lower():
                    return a, n
        except Exception as e:
            log.debug("endpoint list failed: %s", e)
        return False, (found[1]["name"] if found else None)

    def set_volume(self, level):
        """Unmute the AirPod and set its Windows volume. Returns what it was before: (volume, muted)."""
        import warnings, comtypes
        from ctypes import POINTER, cast
        from comtypes import CLSCTX_ALL
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
        comtypes.CoInitialize()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            coll = AudioUtilities.GetDeviceEnumerator().EnumAudioEndpoints(0, 1)        # playback, connected
            for i in range(coll.GetCount()):
                dev = coll.Item(i); name = (AudioUtilities.CreateDevice(dev).FriendlyName or "").lower()
                if self.name in name and "hands-free" not in name:
                    vol = cast(dev.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None), POINTER(IAudioEndpointVolume))
                    was = (round(vol.GetMasterVolumeLevelScalar(), 2), bool(vol.GetMute()))
                    vol.SetMute(0, None); vol.SetMasterVolumeLevelScalar(float(level), None)
                    return was
        return None

    def connect(self):
        """Run the one-shot reconnect in a child process: a wrong COM call there cannot take the earpiece down."""
        r = subprocess.run([sys.executable, os.path.abspath(__file__), "connect"], capture_output=True, text=True, timeout=40,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        log.info("connect: exit %s %s", r.returncode, (r.stdout + r.stderr).strip()[-300:])
        return r.returncode == 0

    # -- playing a clip into it
    def _output(self):
        import sounddevice as sd
        if self.mic is None:                                        # (not while the microphone is open: it would close it)
            sd._terminate(); sd._initialize()                       # the device list is read once; read it again
        apis = sd.query_hostapis()
        best = None
        for i, d in enumerate(sd.query_devices()):
            if d["max_output_channels"] < 1 or self.name not in d["name"].lower() or "hands-free" in d["name"].lower():
                continue
            api = apis[d["hostapi"]]["name"]
            if "WASAPI" in api:
                return i, d, True
            best = best or (i, d, False)
        return best

    def play(self, wav_bytes):
        import numpy as np, sounddevice as sd
        with self.lock:
            found = self._output()
            if not found:
                return False
            i, d, wasapi = found
            with wave.open(io.BytesIO(wav_bytes)) as w:
                rate, ch = w.getframerate(), w.getnchannels()
                pcm = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).reshape(-1, ch)
            if ch == 1 and d["max_output_channels"] >= 2:
                pcm = np.repeat(pcm, 2, axis=1)
            extra = sd.WasapiSettings(auto_convert=True) if wasapi else None      # Windows resamples 24 kHz for us
            sd.play(pcm, rate, device=i, extra_settings=extra, blocking=True)
            return True

    # -- SimHub
    def simhub_running(self):
        import psutil
        return any((p.info["name"] or "").lower() == "simhubwpf.exe" for p in psutil.process_iter(["name"]))

    def simhub_detail(self):
        """What SimHub itself says through its local web API: {"game": the game it is set to, "data": True when it is
        receiving that game's data}. None when the API does not answer (SimHub still starting, or its web server is off)."""
        api = (self.cfg.get("simhub_api") or "").rstrip("/")
        if not api:
            return None
        try:
            with urllib.request.urlopen(api + "/Api/GetGameData", timeout=2) as r:
                d = json.loads(r.read().decode("utf-8", "replace"))
            return {"game": d.get("GameName") or None, "data": bool(d.get("GameRunning"))}
        except Exception:
            return None

    def start_simhub(self):
        if session_id() == 0:                       # a system task: SimHub would start where nobody can see it
            return False
        path = self.cfg["simhub_path"]
        if not os.path.exists(path):
            log.warning("SimHub not found at %s", path); return False
        subprocess.Popen([path], cwd=os.path.dirname(path)); log.info("started SimHub"); return True


# ---------------------------------------------------------------- Mac: audio device, Bluetooth

class MacPC:
    """The same jobs on macOS, through CoreAudio (sounddevice). No SimHub there. The device's volume is left alone:
    macOS has no simple way to set the volume of a device that is not the default output."""
    has_simhub = False

    def __init__(self, cfg, run=subprocess.run, which=None):
        import shutil
        self.cfg = cfg; self.name = cfg["device"].lower(); self.lock = threading.Lock(); self.mic = None
        self.run, self.which = run, which or shutil.which

    def _blueutil(self):
        """Path of blueutil, or None. A LaunchAgent's PATH does not include Homebrew, so its folders are tried too."""
        return self.which("blueutil") or next((p for p in ("/opt/homebrew/bin/blueutil", "/usr/local/bin/blueutil") if os.path.exists(p)), None)

    def _sd(self, fresh=True):
        import sounddevice as sd
        if fresh and self.mic is None:                              # the device list is read once; read it again
            sd._terminate(); sd._initialize()
        return sd

    def _find(self, key):
        """(index, device) of the first device with channels of that kind whose name matches."""
        for i, d in enumerate(self._sd().query_devices()):
            if d[key] > 0 and self.name in d["name"].lower():
                return i, d
        return None

    def mic_start(self, on_frames):
        with self.lock:
            if self.mic is not None:
                return True
            found = self._find("max_input_channels")
            if not found:
                return False
            sd = self._sd(fresh=False)
            st = sd.InputStream(device=found[0], channels=1, samplerate=16000, dtype="int16", blocksize=1600,
                                callback=lambda data, n, t, status: on_frames(data[:, 0].copy()))
            st.start(); self.mic = st; log.info("microphone open: %s", found[1]["name"]); return True

    def mic_alive(self):
        return self.mic is not None and self.mic.active

    def mic_stop(self):
        with self.lock:
            st, self.mic = self.mic, None
        try:
            if st: st.abort(); st.close()
        except Exception:
            pass

    def endpoints(self):
        """Playback devices the Mac can open now, plus paired Bluetooth devices when blueutil is installed."""
        out = [(d["name"], True, "") for d in self._sd().query_devices() if d["max_output_channels"] > 0]
        have = {n.lower() for n, _, _ in out}
        for dev in self._paired():
            if (dev.get("name") or "").lower() not in have:
                out.append((dev.get("name") or "", bool(dev.get("connected")), dev.get("address") or ""))
        return out

    def airpod(self):
        with self.lock:
            found = self._find("max_output_channels")
        if found:
            return True, found[1]["name"]
        for dev in self._paired():
            if self.name in (dev.get("name") or "").lower():
                return False, dev.get("name")
        return False, None

    def set_volume(self, level):
        return None

    def _paired(self):
        tool = self._blueutil()
        if not tool:
            return []
        try:
            r = self.run([tool, "--paired", "--format", "json"], capture_output=True, text=True, timeout=15)
            return json.loads(r.stdout or "[]") if r.returncode == 0 else []
        except Exception:
            return []

    def connect(self):
        """Ask macOS to connect the paired Bluetooth device. Needs the small tool blueutil (brew install blueutil);
        without it macOS connects the device by itself or from the menu bar, and this only says so."""
        tool = self._blueutil()
        if not tool:
            log.info("connect: blueutil is not installed, leaving the connection to macOS"); return False
        for dev in self._paired():
            if self.name in (dev.get("name") or "").lower() and dev.get("address"):
                r = self.run([tool, "--connect", dev["address"]], capture_output=True, text=True, timeout=40)
                log.info("connect %s: exit %s %s", dev.get("name"), r.returncode, ((r.stdout or "") + (r.stderr or "")).strip()[-200:])
                return r.returncode == 0
        log.info("connect: no paired Bluetooth device named like '%s'", self.cfg["device"]); return False

    def play(self, wav_bytes):
        import numpy as np
        with self.lock:
            found = self._find("max_output_channels")
            if not found:
                return False
            i, d = found
            with wave.open(io.BytesIO(wav_bytes)) as w:
                rate, ch = w.getframerate(), w.getnchannels()
                pcm = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).reshape(-1, ch)
            if ch == 1 and d["max_output_channels"] >= 2:
                pcm = np.repeat(pcm, 2, axis=1)
            self._sd(fresh=False).play(pcm, rate, device=i, blocking=True)      # CoreAudio converts the sample rate
            return True

    def simhub_running(self):
        return None                                   # not applicable on a Mac

    def start_simhub(self):
        return False


def this_machine(cfg):
    return MacPC(cfg) if MAC else WindowsPC(cfg)


def session_id():
    """Windows session this runs in: 0 = system task / service, None = not Windows."""
    try:
        import ctypes
        sid = ctypes.c_ulong()
        ctypes.windll.kernel32.ProcessIdToSessionId(os.getpid(), ctypes.byref(sid))
        return sid.value
    except Exception:
        return None


def bt_reconnect(name):
    """Ask the Bluetooth audio driver to connect every audio service of the named device (what the Windows 'Connect'
    button does). Uses the driver's one-shot reconnect property on the device behind each playback endpoint."""
    import comtypes
    from ctypes import POINTER, Structure, byref, c_void_p, sizeof, windll, wstring_at
    from ctypes.wintypes import BOOL, UINT, ULONG
    from comtypes import CLSCTX_ALL, COMMETHOD, GUID, HRESULT, IUnknown
    from pycaw.pycaw import AudioUtilities

    class IConnector(IUnknown):
        _iid_ = GUID("{9C2C4058-23F5-41DE-877A-DF3AF236A09E}")
        _methods_ = [COMMETHOD([], HRESULT, "GetType", (["out"], POINTER(UINT), "t")),
                     COMMETHOD([], HRESULT, "GetDataFlow", (["out"], POINTER(UINT), "f")),
                     COMMETHOD([], HRESULT, "ConnectTo", (["in"], c_void_p, "to")),
                     COMMETHOD([], HRESULT, "Disconnect"),
                     COMMETHOD([], HRESULT, "IsConnected", (["out"], POINTER(BOOL), "c")),
                     COMMETHOD([], HRESULT, "GetConnectedTo", (["out"], POINTER(c_void_p), "to")),
                     COMMETHOD([], HRESULT, "GetConnectorIdConnectedTo", (["out"], POINTER(c_void_p), "id")),
                     COMMETHOD([], HRESULT, "GetDeviceIdConnectedTo", (["out"], POINTER(c_void_p), "id"))]

    class IDeviceTopology(IUnknown):
        _iid_ = GUID("{2A07407E-6497-4A18-9787-32F79BD0D98F}")
        _methods_ = [COMMETHOD([], HRESULT, "GetConnectorCount", (["out"], POINTER(UINT), "n")),
                     COMMETHOD([], HRESULT, "GetConnector", (["in"], UINT, "i"), (["out"], POINTER(POINTER(IConnector)), "c"))]

    class KSPROPERTY(Structure):
        _fields_ = [("Set", GUID), ("Id", ULONG), ("Flags", ULONG)]

    class IKsControl(IUnknown):
        _iid_ = GUID("{28F54685-06FD-11D2-B27A-00A0C9223196}")
        _methods_ = [COMMETHOD([], HRESULT, "KsProperty", (["in"], POINTER(KSPROPERTY), "p"), (["in"], ULONG, "len"),
                               (["in"], c_void_p, "data"), (["in"], ULONG, "dlen"), (["out"], POINTER(ULONG), "ret"))]

    BT_AUDIO = GUID("{7FA06C40-B8F6-4C7E-8556-E8C33A12E54D}"); ONESHOT_RECONNECT = 0; TYPE_GET = 1
    comtypes.CoInitialize()
    enum = AudioUtilities.GetDeviceEnumerator()
    seen, asked = set(), 0
    for d in AudioUtilities.GetAllDevices():
        if not d.id or name.lower() not in (d.FriendlyName or "").lower():
            continue
        try:
            topo = enum.GetDevice(d.id).Activate(IDeviceTopology._iid_, CLSCTX_ALL, None).QueryInterface(IDeviceTopology)
            for i in range(topo.GetConnectorCount()):
                raw = topo.GetConnector(i).GetDeviceIdConnectedTo()
                if not raw:
                    continue
                ks_id = wstring_at(raw); windll.ole32.CoTaskMemFree(c_void_p(raw))
                if ks_id in seen:
                    continue
                seen.add(ks_id)
                ks = enum.GetDevice(ks_id).Activate(IKsControl._iid_, CLSCTX_ALL, None).QueryInterface(IKsControl)
                prop = KSPROPERTY(BT_AUDIO, ONESHOT_RECONNECT, TYPE_GET)
                ks.KsProperty(byref(prop), sizeof(prop), None, 0)
                asked += 1; print(f"asked to connect: {d.FriendlyName}")
        except Exception as e:                                       # not a Bluetooth device, or the driver said no
            print(f"{d.FriendlyName}: {type(e).__name__}: {e}")
    return asked


# ---------------------------------------------------------------- the earpiece itself (runs anywhere, PC injected)

class Earpiece:
    def __init__(self, cfg, pc):
        self.cfg, self.pc = cfg, pc
        self.calls = queue.Queue(); self.live = False; self.stop = threading.Event()
        self.last_connect = 0.0; self.note = ""; self.played = 0; self.skipped = 0
        self.diag_at = 0.0; self.diag_state = None; self.was_connected = False
        self.frames = queue.Queue(maxsize=600); self.speaking_until = 0.0; self.heard = 0
        self.listener = None; self.mic_off_until = 0.0

    # -- listening
    def on_event(self, ev):
        if ev.get("type") == "state":
            was, self.live = self.live, bool(ev.get("live"))
            if self.live and not was:
                log.info("GT7 is live"); self.last_connect = 0.0
                self.ensure_simhub()
        elif ev.get("type") == "say":
            while self.calls.qsize() > 1:                            # never fall behind the car: drop the oldest
                try: self.calls.get_nowait(); self.skipped += 1
                except queue.Empty: break
            self.calls.put(ev)

    def listen(self):
        while not self.stop.is_set():
            try:
                with request(self.cfg, "/events", timeout=30) as r:
                    log.info("listening to %s", self.cfg["url"])
                    for line in r:
                        if self.stop.is_set():
                            return
                        if line.startswith(b"data: "):
                            self.on_event(json.loads(line[6:]))
            except Exception as e:
                self.live = False
                log.warning("lost the server (%s: %s), retrying", type(e).__name__, e)
            self.stop.wait(5)

    # -- speaking
    # -- hearing (voice control)
    def hear(self):
        """Cut what the microphone hears into utterances (by loudness) and send each one to the server."""
        import numpy as np
        floor, buf, pre, quiet, talking = 150.0, [], [], 0, False
        while not self.stop.is_set():
            try: fr = self.frames.get(timeout=1)
            except queue.Empty: continue
            if time.time() < self.speaking_until or time.time() < self.speaking_file():   # the copilot is talking: not the driver
                buf, pre, quiet, talking = [], [], 0, False; continue
            rms = float(np.sqrt((fr.astype(np.float64) ** 2).mean()))
            loud = rms > max(350.0, floor * 2.5)
            if not talking:
                pre = (pre + [fr])[-4:]                               # 0.4 s kept from before the first loud frame
                if loud:
                    talking, buf, quiet = True, list(pre), 0
                else:
                    floor = 0.95 * floor + 0.05 * rms
                continue
            buf.append(fr); quiet = 0 if loud else quiet + 1
            if loud and len(buf) >= 6:                                # the driver is speaking: the player holds its next call
                self.mark_driver()
            if quiet >= 8 or len(buf) >= 100:                         # 0.8 s of silence ends it; 10 s at most
                said, talking, pre = buf[:-quiet] if quiet else buf, False, []
                if len(said) >= 7:                                    # shorter than 0.7 s is a click or a cough
                    self.send_utterance(np.concatenate(said + buf[-2:]))
                buf = []

    # The microphone runs in a process of its own (see "listen"), so the speaking process tells it through a small file
    # until when the copilot's own voice is in the air. Without it the microphone hears the calls and sends them back.
    def speaking_file(self):
        now = time.time()
        if now - getattr(self, "_sf_at", 0) > 0.3:
            self._sf_at = now
            try:
                with open(os.path.join(HOME, "speaking")) as f: self._sf = float(f.read().strip() or 0)
            except (OSError, ValueError): self._sf = 0.0
        return getattr(self, "_sf", 0.0)

    # The other direction: while the driver is speaking, a new call would talk over them and make the microphone deaf
    # in the middle of their sentence. The listener notes it in a small file; the player waits a moment for them to finish.
    def mark_driver(self):
        now = time.time()
        if now - getattr(self, "_md_at", 0) > 0.25:
            self._md_at = now
            try:
                with open(os.path.join(HOME, "driver"), "w") as f: f.write(str(now + 1.2))
            except OSError: pass

    def driver_speaking(self):
        try:
            with open(os.path.join(HOME, "driver")) as f: return time.time() < float(f.read().strip() or 0)
        except (OSError, ValueError): return False

    def mark_speaking(self, wav):
        try:
            with wave.open(io.BytesIO(wav)) as w: secs = w.getnframes() / float(w.getframerate() or 24000)
        except Exception: secs = 4.0
        self.speaking_until = time.time() + secs + 0.6
        try:
            with open(os.path.join(HOME, "speaking"), "w") as f: f.write(str(self.speaking_until))
        except OSError: pass

    def send_utterance(self, samples):
        b = io.BytesIO()
        with wave.open(b, "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000); w.writeframes(samples.tobytes())
        try:
            out = json.load(request(self.cfg, "/api/hear", raw=b.getvalue(), timeout=25))
            self.heard += 1
            if out.get("command"):
                log.info("heard: %s -> %s", out.get("heard"), out.get("command"))
            elif out.get("heard"):
                log.info("heard, not for the copilot: %s", str(out["heard"])[:80])
        except Exception as e:
            log.warning("could not send what was said: %s: %s", type(e).__name__, e)

    def stop_listener(self):
        try:
            if self.listener and self.listener.poll() is None:
                self.listener.kill()
        except Exception:
            pass
        self.listener = None

    def on_frames(self, fr):
        self.last_frame = time.time()
        try: self.frames.put_nowait(fr)
        except queue.Full: pass

    def speak_one(self, ev):
        if ev.get("deadline") and time.time() > ev["deadline"] + 1:  # too late to be useful (the corner has gone)
            self.skipped += 1; return False
        if not ev.get("url"):
            self.skipped += 1; return False
        try:
            wav = request(self.cfg, ev["url"]).read()
            held = time.time()
            while self.driver_speaking() and time.time() - held < 2.5:        # let the driver finish (at most two and a half seconds)
                time.sleep(0.15)
            if time.time() - held > 0.3 and ev.get("deadline") and ev.get("kind") != "voice" and time.time() > ev["deadline"] + 1:
                self.skipped += 1; return False                              # a corner call that is now too late
            self.mark_speaking(wav)
            try:
                ok = self.pc.play(wav)
            except Exception as e:
                if self.listener is None or self.listener.poll() is not None:
                    raise
                # Speaking matters more than listening: stop the microphone for ten minutes and say it again.
                log.warning("could not play with the microphone open (%s): microphone off for 10 minutes", str(e)[:80])
                self.stop_listener(); self.mic_off_until = time.time() + 600
                time.sleep(1.5); ok = self.pc.play(wav)
        except Exception as e:
            log.warning("could not play '%s': %s: %s", ev.get("text"), type(e).__name__, e); ok = False
        if ok: self.played += 1; log.info("said: %s", ev.get("text"))
        else: self.skipped += 1
        return ok

    def speak(self):
        while not self.stop.is_set():
            try: ev = self.calls.get(timeout=1)
            except queue.Empty: continue
            self.speak_one(ev)

    # -- keeping the PC ready
    def ensure_simhub(self):
        try:
            if self.cfg["start_simhub"] and self.pc.simhub_running() is False:
                self.pc.start_simhub()
        except Exception as e:
            log.warning("SimHub check failed: %s", e)

    def tick(self):
        """One round of housekeeping; returns the report sent to the server."""
        rep = dict(version=VERSION, airpod=False, device=None, simhub=None, note="")
        try:
            rep["airpod"], rep["device"] = self.pc.airpod()
        except Exception as e:
            rep["note"] = f"audio check failed: {e}"
        try:
            rep["simhub"] = self.pc.simhub_running()
            if rep["simhub"]:                                   # running: ask SimHub which game it is set to and whether data arrives
                det = getattr(self.pc, "simhub_detail", lambda: None)()
                rep["simhub_api"] = det is not None
                if det: rep["simhub_game"], rep["simhub_data"] = det["game"], det["data"]
        except Exception as e:
            rep["note"] = f"SimHub check failed: {e}"
        if rep["airpod"] and not self.was_connected and self.cfg.get("volume") is not None:     # just connected
            try:
                was = self.pc.set_volume(self.cfg["volume"])
                if was is not None:
                    log.info("device volume set to %s, unmuted (was %s)", self.cfg["volume"], was)
            except Exception as e:
                log.warning("could not set the device volume: %s: %s", type(e).__name__, e)
        self.was_connected = rep["airpod"]
        if self.cfg.get("voice") and hasattr(self.pc, "mic_start"):       # the listener is its own process: keep it alive
            if time.time() >= self.mic_off_until and (self.listener is None or self.listener.poll() is not None):
                self.listener = subprocess.Popen([sys.executable, os.path.abspath(__file__), "--home", HOME, "listen"],
                                                 env=dict(os.environ, GT7C_EARPIECE_PARENT=str(os.getpid())),
                                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            rep["mic"] = self.listener is not None and self.listener.poll() is None
        want = self.cfg["connect_when"]
        if not rep["airpod"] and (want == "always" or (want == "live" and self.live)) and time.time() - self.last_connect > 20:
            self.last_connect = time.time()
            if rep["device"] is None:
                rep["note"] = f"no playback device named '{self.cfg['device']}' (pair it with this machine once)"
            else:
                try: self.pc.connect()
                except Exception as e: log.warning("connect failed: %s", e)
        if time.time() - self.diag_at > 300 or rep["airpod"] != self.diag_state:      # the full picture, for fixing things from afar
            self.diag_at, self.diag_state = time.time(), rep["airpod"]
            try: rep["diag"] = doctor(self.cfg, self.pc, server=False)[:6000]
            except Exception as e: rep["diag"] = f"doctor failed: {type(e).__name__}: {e}"
        rep["played"], rep["skipped"] = self.played, self.skipped
        try:
            request(self.cfg, "/api/earpiece", rep).read()
        except Exception as e:
            log.debug("report not sent: %s", e)
        return rep

    def run(self):
        log.info("gt7copilot earpiece %s: server %s, device '%s'", VERSION, self.cfg["url"], self.cfg["device"])
        self.ensure_simhub()
        for f in (self.listen, self.speak):
            threading.Thread(target=f, daemon=True).start()
        last = None
        while not self.stop.is_set():
            rep = self.tick(); now = (rep["airpod"], rep["simhub"], rep["note"])
            if now != last:
                log.info("device %s, SimHub %s%s", "connected" if rep["airpod"] else "not connected",
                         {True: "running", False: "not running", None: "not applicable" if getattr(self.pc, "has_simhub", True) is False else "unknown"}[rep["simhub"]],
                         " - " + rep["note"] if rep["note"] else "")
                last = now
            self.stop.wait(10)


def doctor(cfg, pc, server=True):
    """What this PC looks like to the earpiece, as text."""
    lines = []
    print = lambda *a: lines.append(" ".join(str(x) for x in a))
    print(f"gt7copilot earpiece {VERSION}\nconfig: {os.path.join(HOME, 'earpiece.json')}\nserver: {cfg['url'] or '(not set)'}   token: {'set' if cfg['token'] else 'MISSING'}")
    print(f"looking for a playback device named like: '{cfg['device']}'")
    mark = lambda n: "   <-- name matches" if cfg["device"].lower() in n.lower() else ""
    if MAC:
        import shutil
        print("macOS:", "blueutil found (can ask Bluetooth to connect)" if (pc._blueutil() if hasattr(pc, "_blueutil") else shutil.which("blueutil")) else
              "blueutil not installed: macOS connects the device itself; `brew install blueutil` lets the earpiece ask")
    else:
        sid = session_id()
        print("session:", os.environ.get("SESSIONNAME") or ("system task" if sid == 0 else "?"), f"(id {sid})",
              "- Remote Desktop session: Windows hides the PC's own sound devices here" if os.environ.get("SESSIONNAME", "").upper().startswith("RDP") else "")
    try:
        eps = pc.endpoints()
        print(f"playback devices the system knows ({len(eps)}):")
        for n, a, i in eps:
            print(f"  {'connected    ' if a else 'not connected'}  {n or '(no name)'}{mark(n)}")
    except Exception as e:
        print(f"  playback devices: FAILED {type(e).__name__}: {e}")
    try:
        import sounddevice as sd
        apis = sd.query_hostapis()
        outs = [(apis[d["hostapi"]]["name"], d["name"].replace("\r", " ").replace("\n", " ")) for d in sd.query_devices() if d["max_output_channels"]]
        print(f"devices the player can open ({len(outs)})" + ("" if MAC else "; it uses the 'Windows WASAPI' entry") + ":")
        for api, n in outs:
            print(f"  {api:16} {n}{mark(n)}")
    except Exception as e:
        print(f"  player: FAILED {type(e).__name__}: {e}")
    try:
        print("device now (connected, name):", pc.airpod())
    except Exception as e:
        print(f"  device: FAILED {type(e).__name__}: {e}")
    if MAC:
        try:
            import sounddevice as sd
            ins = [d["name"] for d in sd.query_devices() if d["max_input_channels"]]
            print(f"microphones ({len(ins)}):", ", ".join(n + mark(n).replace("   <-- name matches", " (matches)") for n in ins) or "none")
            print("microphone access: macOS asks once for Python; System Settings > Privacy & Security > Microphone shows the answer")
        except Exception as e:
            print(f"  microphones: FAILED {type(e).__name__}: {e}")
    else:
        try:
            print("SimHub:", "running" if pc.simhub_running() else "not running", "| installed:", os.path.exists(cfg["simhub_path"]))
            det = pc.simhub_detail() if pc.simhub_running() else None
            if pc.simhub_running():
                print("  its web API (" + str(cfg.get("simhub_api")) + "):", f"game {det['game']}, {'receiving data' if det['data'] else 'no game data now'}" if det else "no answer")
        except Exception as e:
            print(f"  SimHub: FAILED {e}")
    if server:
        try:
            with request(cfg, "/events", timeout=10) as r:
                print("server:", r.status, r.readline().decode()[:80].strip())
        except Exception as e:
            print(f"server: FAILED {type(e).__name__}: {e}")
    return "\n".join(lines)


def main(argv):
    global HOME
    argv = list(argv)
    if "--home" in argv:
        i = argv.index("--home"); HOME = argv[i + 1]; del argv[i:i + 2]
        os.environ["GT7C_EARPIECE_HOME"] = HOME                       # the connect child process reads it too
    cmd = argv[0] if argv else "run"
    cfg = config()
    if cmd == "supervise":
        os.makedirs(HOME, exist_ok=True)
        while True:
            t0 = time.time()
            rc = subprocess.call([sys.executable, os.path.abspath(__file__), "--home", HOME, "run"],
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            with open(log_file(), "a", encoding="utf-8") as f:
                f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} supervisor: the earpiece stopped (exit {rc}) after {time.time() - t0:.0f} s, starting it again\n")
            time.sleep(3 if time.time() - t0 > 30 else 20)
    if cmd == "connect" and not MAC:
        n = bt_reconnect(cfg["device"]); print(f"{n} connect request(s) sent"); return 0 if n else 1
    pc = this_machine(cfg)
    if cmd == "connect":
        logging.basicConfig(level=logging.INFO, format="%(message)s")
        return 0 if pc.connect() else 1
    if cmd == "doctor":
        print(doctor(cfg, pc)); return 0
    os.makedirs(HOME, exist_ok=True)
    h = logging.handlers.RotatingFileHandler(log_file(), maxBytes=500_000, backupCount=2, encoding="utf-8")
    h.setFormatter(logging.Formatter("%(asctime)s %(message)s")); log.addHandler(h); log.setLevel(logging.INFO)
    if sys.stdout: log.addHandler(logging.StreamHandler())
    if not cfg["url"] or not cfg["token"]:
        log.error("no url/token in %s", os.path.join(HOME, "earpiece.json")); return 2
    if cmd == "test":
        ep = Earpiece(cfg, pc); threading.Thread(target=ep.listen, daemon=True).start(); time.sleep(2)
        print("device:", pc.airpod()); print("asking the server for a test line is done from the page (Test voice); waiting 30 s for any call...")
        try: ev = ep.calls.get(timeout=30)
        except queue.Empty: print("no call arrived"); return 1
        print("played" if ep.speak_one(ev) else "NOT played", "-", ev.get("text")); return 0
    if cmd == "listen":                               # the microphone process
        ep = Earpiece(cfg, pc); threading.Thread(target=ep.hear, daemon=True).start()
        log.info("listener %s: waiting for the device's microphone", VERSION)
        parent = int(os.environ.get("GT7C_EARPIECE_PARENT", "0")); opened = 0.0
        while True:
            if parent:                                # never outlive the earpiece that started it (no second listener)
                if not pid_alive(parent):
                    log.info("listener: the earpiece is gone, stopping"); return 0
            try:
                # An open microphone that delivers nothing for 5 s has stalled (seen after the device reconnects): open it again.
                stalled = pc.mic_alive() and time.time() - max(getattr(ep, "last_frame", 0), opened) > 5
                if stalled:
                    log.warning("microphone: open but silent for 5 s, opening it again")
                if stalled or not pc.mic_alive():
                    pc.mic_stop()
                    if pc.mic_start(ep.on_frames): opened = time.time()
            except Exception as e:
                log.warning("microphone: %s: %s", type(e).__name__, str(e)[:120])
            time.sleep(5)
    if cmd == "run":
        ep = Earpiece(cfg, pc)
        try: ep.run()
        finally: ep.stop_listener()
        return 0
    print(__doc__); return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
