"""Local text-to-speech (Kokoro; the voice is a setting) with an on-disk cache. Generation runs on its own thread."""
import hashlib, os, queue, threading, time
from . import settings as CFG

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.environ.get("GT7C_DATA")                       # set in the container: everything writable lives on the data volume
CACHE = os.path.join(DATA, "tts-cache") if DATA else os.path.join(BASE, "tts", "cache")
MODELS = os.environ.get("GT7C_MODELS", os.path.join(BASE, "tts", "models"))


class TTS:
    def __init__(self, on_ready, log=print):
        self.on_ready, self.log = on_ready, log     # on_ready(text, filename, kind, deadline)
        self.q = queue.Queue(); self.k = None
        os.makedirs(CACHE, exist_ok=True)
        threading.Thread(target=self._run, daemon=True).start()

    def say(self, text, ttl=5.0, kind="info"):
        self.q.put((text, kind, time.time() + max(ttl, 0.5)))

    def _file(self, text):
        return hashlib.sha1(f"{CFG.get('tts_voice')}|{text}".encode()).hexdigest()[:20] + ".wav"

    def _synth(self, text, path):
        import soundfile as sf
        if self.k is None:
            from kokoro_onnx import Kokoro
            self.k = Kokoro(os.path.join(MODELS, "kokoro-v1.0.onnx"), os.path.join(MODELS, "voices-v1.0.bin"))
        audio, sr = self.k.create(text, voice=CFG.get("tts_voice"), speed=1.1, lang="en-gb")
        sf.write(path + ".tmp.wav", audio, sr); os.replace(path + ".tmp.wav", path)

    def _run(self):
        try:
            self._synth("Copilot ready.", os.path.join(CACHE, self._file("warmup")))
            self.log("tts ready")
        except Exception as e:
            self.log(f"tts warmup failed: {e}")
        while True:
            text, kind, deadline = self.q.get()
            if time.time() > deadline:
                self.log(f"dropped (late): {text}"); continue
            name = self._file(text); path = os.path.join(CACHE, name)
            try:
                if not os.path.exists(path):
                    self._synth(text, path)
            except Exception as e:
                self.log(f"tts failed: {e}"); name = None      # the page falls back to the browser voice
            self.on_ready(text, name, kind, deadline)
