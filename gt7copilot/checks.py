"""The Test buttons on the Settings tab: each asks one configured service a small question and says what came back."""
import io, json, struct, urllib.error, urllib.request, wave, zlib
from . import capture as CAP, settings as CFG, voice as V


def _png(size=32):
    """A small plain grey picture, made here so the vision test needs no file."""
    row = b"\x00" + b"\x80\x80\x80" * size
    chunk = lambda kind, data: struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(row * size)) + chunk(b"IEND", b""))


def _silence(seconds=0.6):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000); w.writeframes(b"\x00\x00" * int(16000 * seconds))
    return buf.getvalue()


def whisper():
    try:
        fetched = not CFG.why_not("voice_control") and V.ensure_model()
        text = V.transcribe(_silence())
    except RuntimeError as e:
        return dict(ok=False, note=str(e))
    except urllib.error.HTTPError as e:
        return dict(ok=False, note=f"The speech-to-text service answered with error {e.code}. Check the address, key and model.")
    except Exception as e:
        return dict(ok=False, note=f"The speech-to-text service cannot be reached ({type(e).__name__}).")
    return dict(ok=True, note=("The model was downloaded. " if fetched else "") + "The speech-to-text service answered." + (f' It heard "{text}" in silence.' if text else ""))


def vision():
    import base64
    try:
        text = CAP.ask([dict(type="text", text="Reply with the single word OK."),
                        dict(type="image_url", image_url=dict(url="data:image/png;base64," + base64.b64encode(_png()).decode()))],
                       max_tokens=200, timeout=60)
    except RuntimeError as e:
        return dict(ok=False, note=str(e))
    return dict(ok=True, note=f"The vision model accepted a picture and answered: {text.strip()[:60] or '(nothing)'}")


def phone():
    why = CFG.why_not("phone")
    if why:
        return dict(ok=False, note=why)
    try:
        with urllib.request.urlopen(CFG.get("grab_url") + "/healthz", timeout=8) as r:
            d = json.load(r)
    except Exception as e:
        return dict(ok=False, note=f"The virtual phone cannot be reached ({type(e).__name__}). Is the phone profile running?")
    if not d.get("ok", True):
        return dict(ok=False, note=str(d.get("note") or "The virtual phone is not ready."))
    return dict(ok=True, note=str(d.get("note") or "The virtual phone answered."))


TESTS = dict(whisper=whisper, vision=vision, phone=phone)
