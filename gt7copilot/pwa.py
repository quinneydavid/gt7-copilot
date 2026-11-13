"""What a phone needs to install the page as an app and offer it in the share sheet (Android, Chrome, https only):
the manifest with a share target, a service worker, two icons, and the small page shown after a picture was shared."""
import html, json, struct, zlib

MANIFEST = dict(
    name="GT7 Copilot", short_name="GT7 Copilot", start_url="/", scope="/", display="standalone",
    background_color="#14161a", theme_color="#14161a",
    icons=[dict(src="/icon-192.png", sizes="192x192", type="image/png", purpose="any"),
           dict(src="/icon-512.png", sizes="512x512", type="image/png", purpose="any")],
    # Sharing a picture to the app posts it to /share as a form (server.py -> inbox.py).
    share_target=dict(action="/share", method="POST", enctype="multipart/form-data",
                      params=dict(files=[dict(name="image", accept=["image/jpeg", "image/png", "image/webp"])])))

# The worker does nothing with requests: every page and every shared picture goes straight to the server.
WORKER = "self.addEventListener('install',()=>self.skipWaiting());self.addEventListener('activate',e=>e.waitUntil(self.clients.claim()));self.addEventListener('fetch',()=>{});\n"

_icons = {}


def icon(size):
    """A plain icon drawn here (a ring on a dark square), so the repository holds no binary files."""
    if size not in _icons:
        c = (size - 1) / 2; outer, inner = size * 0.36, size * 0.24
        rows = bytearray()
        for y in range(size):
            rows.append(0)
            for x in range(size):
                d = ((x - c) ** 2 + (y - c) ** 2) ** 0.5
                rows += b"\xe8\xea\xed" if inner <= d <= outer else b"\x14\x16\x1a"
        chunk = lambda kind, data: struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
        _icons[size] = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
                        + chunk(b"IDAT", zlib.compress(bytes(rows), 9)) + chunk(b"IEND", b""))
    return _icons[size]


FILES = {"/manifest.webmanifest": lambda: (json.dumps(MANIFEST).encode(), "application/manifest+json"),
         "/sw.js": lambda: (WORKER.encode(), "text/javascript; charset=utf-8"),
         "/icon-192.png": lambda: (icon(192), "image/png"),
         "/icon-512.png": lambda: (icon(512), "image/png")}


def result_page(ok, text):
    """The page a phone shows after sharing a picture. ok None = no picture was involved."""
    head = "Picture read" if ok else ("Picture not filed" if ok is False else "GT7 Copilot")
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>GT7 Copilot</title><style>
:root{{color-scheme:light dark}}body{{font:17px/1.5 system-ui,sans-serif;margin:0;padding:28px 20px;background:#f4f5f7;color:#16181c}}
@media(prefers-color-scheme:dark){{body{{background:#14161a;color:#e8eaed}}a{{color:#9ec5ff}}}}
h1{{font-size:20px;margin:0 0 10px}}p{{margin:0 0 18px}}</style></head>
<body><h1>{html.escape(head)}</h1><p>{html.escape(text)}</p><p><a href="/#screenshots">Open GT7 Copilot</a></p></body></html>""".encode()
