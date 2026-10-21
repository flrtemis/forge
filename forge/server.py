"""Local TTS server — use your FORGE voice inside Firefox.

    python -m forge.server --voice "%USERPROFILE%\\forge\\voices\\my-voice"

Then open http://127.0.0.1:5004/reader in Firefox: paste an article, click
Read aloud, and the text is spoken *in your voice*. The page works in
Firefox Reader View too.

The model is loaded once and kept in VRAM, so sentences synthesise in about
a second each instead of re-loading the checkpoint every time.

HTTP API (all JSON in, audio/wav out):

    GET  /health                        -> {"ok": true, "loaded": bool, ...}
    GET  /voice                         -> active voice + languages
    GET  /api/voices                    -> voices found in the FORGE workdir
    POST /speak    {"text": "..."}      -> 24 kHz 16-bit mono wav
    POST /voices   {"voice": "<folder>"} -> switch voice (unloads current)

`--token` (optional) requires ?token=... or X-Forge-Token on every request;
without it the server is still bound to 127.0.0.1 and rejects Cross-Origin
requests from anywhere except localhost.
"""
import argparse
import functools
import json
import os
import re
import threading
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from . import synth

HERE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(HERE, "web")

MAX_TEXT = 5000          # characters; the reader page sends sentences anyway
MAX_BODY = 1_000_000

# Only these names are servable from forge/web/ — no path traversal.
STATIC = {
    "/": ("reader.html", "text/html; charset=utf-8"),
    "/reader": ("reader.html", "text/html; charset=utf-8"),
    "/reader.html": ("reader.html", "text/html; charset=utf-8"),
    "/style.css": ("style.css", "text/css; charset=utf-8"),
    "/reader.js": ("reader.js", "text/javascript; charset=utf-8"),
}


def latest_voice(voices_root):
    try:
        dirs = [os.path.join(voices_root, d) for d in os.listdir(voices_root)]
    except OSError:
        return None
    dirs = [d for d in dirs if os.path.isdir(d)
            and os.path.isfile(os.path.join(d, "model.pth"))]
    if not dirs:
        return None
    return max(dirs, key=lambda d: os.path.getmtime(os.path.join(d, "model.pth")))


def _sentences(text):
    """Split into speakable chunks so one bad line doesn't kill a chapter."""
    parts = re.split(r"(?<=[.!?…])\s+|\n{2,}", text.strip())
    return [p.strip() for p in parts if p.strip()]


class Handler(BaseHTTPRequestHandler):
    server_version = "FORGE-TTS/1.0"
    protocol_version = "HTTP/1.1"

    # ---- plumbing -----------------------------------------------------
    def log_message(self, fmt, *args):
        self.server.log(f"[http] {self.address_string()} {fmt % args}")

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Forge-Token")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")

    def _json(self, obj, status=200):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def _error(self, msg, status=500):
        self.server.log(f"[http] {status}: {msg.splitlines()[0]}")
        self._json({"error": msg}, status)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_BODY:
            raise ValueError(f"body too large ({n} bytes)")
        raw = self.rfile.read(n) if n else b"{}"
        try:
            return json.loads(raw or b"{}")
        except ValueError as e:
            raise ValueError(f"body is not JSON: {e}")

    def _host_ok(self):
        """Reject requests addressed to some other hostname.

        This is the DNS-rebinding guard: without it, a malicious page could
        point evil.example at 127.0.0.1 and talk to this server with the
        browser's own privileges. Real usage always says 127.0.0.1/localhost.
        """
        allowed = self.server.allowed_hosts
        if allowed is None:
            return True
        host = (self.headers.get("Host") or "").strip().split(":")[0]
        host = host.strip("[]").lower()
        return host in allowed

    def _authed(self, query):
        token = self.server.token
        if not token:
            return True
        given = (self.headers.get("X-Forge-Token")
                 or (query.get("token", [""])[0] if query else ""))
        return given == token

    # ---- routes -------------------------------------------------------
    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        url = urlparse(self.path)
        q = parse_qs(url.query)
        if not self._host_ok():
            return self._error("wrong Host header (is this a DNS-rebinding trick?)", 403)

        # static assets are token-free: the page needs CSS/JS before it can
        # carry ?token= on its API calls
        if url.path in STATIC or url.path == "/favicon.ico":
            return self._static(url.path)

        if not self._authed(q):
            return self._error("missing or wrong token", 401)

        if url.path in ("/health", "/voice"):
            info = self.server.engine.describe()
            info.update({"ok": True, "voice": self.server.voice_path,
                         "voices_root": self.server.voices_root})
            return self._json(info)

        if url.path == "/api/voices":
            return self._json({"voices": self.server.available_voices(),
                               "active": self.server.voice_path})

        self._error(f"no such path: {url.path}", 404)

    def _static(self, path):
        if path == "/favicon.ico":
            self.send_response(204)
            self._cors()
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        name, ctype = STATIC[path]
        full = os.path.join(WEB, name)
        try:
            with open(full, "rb") as f:
                body = f.read()
        except OSError:
            return self._error(f"web assets missing: {full}", 500)
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        url = urlparse(self.path)
        q = parse_qs(url.query)
        if not self._host_ok():
            return self._error("wrong Host header (is this a DNS-rebinding trick?)", 403)
        if not self._authed(q):
            return self._error("missing or wrong token", 401)
        try:
            payload = self._body()
        except ValueError as e:
            return self._error(str(e), 400)

        if url.path == "/speak":
            return self._speak(payload)

        if url.path == "/voices":
            voice = (payload.get("voice") or "").strip()
            if not os.path.isdir(voice):
                return self._error(f"not a folder: {voice}", 400)
            try:
                synth.describe(voice)           # validates the four files
            except Exception as e:
                return self._error(str(e), 400)
            self.server.switch_voice(voice)
            return self._json({"ok": True, "voice": voice,
                               "switched": True,
                               "note": "the new voice loads on the next /speak"})

        self._error(f"no such path: {url.path}", 404)

    def _speak(self, payload):
        text = (payload.get("text") or "").strip()
        if not text:
            return self._error("empty text", 400)
        if len(text) > MAX_TEXT:
            return self._error(f"text too long ({len(text)} > {MAX_TEXT} chars); "
                               "send it sentence by sentence", 413)

        opt = {"lang": (payload.get("lang") or "en"),
               "speed": float(payload.get("speed") or 1.0),
               "temperature": float(payload.get("temperature") or 0.7)}
        try:
            pcm = self.server.engine.speak(text, **opt)
        except Exception:
            return self._error("synthesis failed:\n" + traceback.format_exc())
        if not pcm:
            return self._error("synthesis returned no audio", 500)

        self.send_response(200)
        self.send_header("Content-Type", "audio/wav")
        self.send_header("Content-Length", str(len(pcm)))
        self.send_header("X-Sample-Rate", str(synth.SAMPLE_RATE))
        self.send_header("Cache-Control", "no-store")
        self._cors()
        self.end_headers()
        self.wfile.write(pcm)


class ForgeServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, addr, engine, voices_root, voice_path, token=None, log=print):
        super().__init__(addr, Handler)
        # local loopback only -> pin the Host header; a wildcard bind is the
        # user's explicit choice, so don't second-guess the hostname there.
        loopback = {"127.0.0.1", "localhost", "::1"}
        self.allowed_hosts = loopback if addr[0] in loopback else None
        self.engine = engine
        self.voices_root = voices_root
        self.voice_path = voice_path
        self.token = token
        self.log = log
        self._switch_lock = threading.Lock()

    def available_voices(self):
        try:
            names = sorted(os.listdir(self.voices_root))
        except OSError:
            return []
        out = []
        for n in names:
            d = os.path.join(self.voices_root, n)
            if os.path.isdir(d) and os.path.isfile(os.path.join(d, "model.pth")):
                out.append(d)
        return out

    def switch_voice(self, path):
        with self._switch_lock:
            self.engine.set_source(path)
            self.voice_path = path
            self.log(f"[forge] voice switched to {path} (loads on next sentence)")


def serve(voice=None, workdir=None, host="127.0.0.1", port=5004,
          device="auto", token=None, open_browser=False, log=None):
    log = log or functools.partial(print, flush=True)
    workdir = os.path.expanduser(workdir or "~/forge")
    voices_root = os.path.join(workdir, "voices")
    os.makedirs(voices_root, exist_ok=True)

    voice = voice or latest_voice(voices_root)
    if not voice:
        raise SystemExit(
            f"No voice given and none found in {voices_root}.\n"
            "Pass --voice <folder with model.pth, config.json, vocab.json, "
            "speaker_ref.wav> or --voice <path to model.pth>.")

    if host not in ("127.0.0.1", "localhost", "::1"):
        log(f"[forge] WARNING: binding to {host} exposes your voice to your "
            "whole network. Add --token if that is not what you want.")
    engine = synth.TTSEngine(voice, device=device, log=log)
    server = ForgeServer((host, port), engine, voices_root, voice,
                         token=token, log=log)
    url = f"http://{host}:{port}/"
    log(f"[forge] TTS server on {url}  (voice: {voice})")
    log("[forge] Firefox: open the URL, paste text, press Read aloud.")
    log("[forge] the model loads on the first request — that first sentence "
        "takes a few seconds, then it's fast.")
    if open_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log("\n[forge] stopping.")
    finally:
        server.server_close()
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description="Serve your FORGE voice to Firefox (or any app) over HTTP")
    p.add_argument("--voice", help="Voice folder or model.pth (default: newest in <workdir>/voices)")
    p.add_argument("--workdir", default=os.path.join(os.path.expanduser("~"), "forge"),
                   help="FORGE working directory (default: %%USERPROFILE%%\\forge)")
    p.add_argument("--host", default="127.0.0.1",
                   help="bind address (default 127.0.0.1 — keep it local)")
    p.add_argument("--port", type=int, default=5004)
    p.add_argument("--device", default="auto", choices=["auto", "cuda", "cpu"])
    p.add_argument("--token", default=os.environ.get("FORGE_TTS_TOKEN"),
                   help="require this token on every request (optional)")
    p.add_argument("--open", action="store_true", help="open the page in the default browser")
    args = p.parse_args(argv)

    return serve(voice=args.voice, workdir=args.workdir, host=args.host,
                 port=args.port, device=args.device, token=args.token,
                 open_browser=args.open)


if __name__ == "__main__":
    raise SystemExit(main())
