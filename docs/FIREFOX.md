# Read the web in your own voice — Firefox (Windows 10 Home)

Your `model.pth` can't run *inside* Firefox: it's a 1.8 GB PyTorch checkpoint,
and browsers don't run PyTorch on your GPU. What does work — and what this
guide sets up — is the standard architecture:

```
Firefox (page, extension)  ──HTTP──►  python -m forge.server  ──►  your model.pth (GPU)
        text                                                            audio
```

The browser sends text to a small server on your own machine, gets back a WAV,
and plays it. Nothing leaves the PC; the server only listens on `127.0.0.1`.

Three ways to use it, easiest first:

| | What | Setup |
|---|---|---|
| **1** | **Reader page** — paste text, click Read aloud | none, works in any Firefox |
| **2** | **Extension** — right-click any page → "read in my voice" | load once via `about:debugging` |
| **3** | **HTTP API** — `POST /speak` from your own scripts | none |

---

## 1 · Start the server

Double-click **`serve-forge.bat`** in the FORGE folder. It activates `.venv`,
starts the server, and opens `http://127.0.0.1:5004/reader` in Firefox.

Or by hand:

```bat
cd C:\Users\l3ung\forge
.venv\Scripts\activate
python -m forge.server --voice "%USERPROFILE%\forge\voices\my-voice"
```

```
[forge] TTS server on http://127.0.0.1:5004/  (voice: C:\Users\l3ung\forge\voices\my-voice)
```

Notes:

- The model **loads on the first sentence** (10–20 s) and then stays in VRAM.
  After that a sentence is typically ~0.5–2 s.
- **Leave that window open while you read.** Closing it turns the voice off.
- No `--voice`? It picks the newest voice in `%USERPROFILE%\forge\voices`.
- `--device cpu` if CUDA is misbehaving (works, ~10–30 s per sentence).
- `--port 5005` if 5004 is taken. `--open` launches the browser for you.

Pin the console window to the taskbar, or make a shortcut in
`%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup` if you want the voice
always available (it idles at ~2 GB VRAM, so only if you have room).

## 2 · The reader page

Open <http://127.0.0.1:5004/reader>.

- Paste an article, a chapter, subtitles, an email → **Read aloud**
  (<kbd>Ctrl</kbd>+<kbd>Enter</kbd>).
- Each sentence appears as a line; it's highlighted as it's spoken, and you can
  **click any line to restart from there**.
- Sentences are synthesised *ahead* of playback, one request each, so a 20-page
  article starts speaking almost immediately instead of after ten minutes.
- **Speed** (0.6–1.6×) and **Expressiveness** (temperature: low = flat and
  steady, high = more varied and lively — 0.6–0.8 is the sweet spot).
- **Language** comes from the model's own language list (XTTS v2 ships with 17).

Getting text *into* it:

- **Long articles**: Firefox Reader View (<kbd>Ctrl</kbd>+<kbd>Alt</kbd>+<kbd>R</kbd>),
  then <kbd>Ctrl</kbd>+<kbd>A</kbd> → <kbd>Ctrl</kbd>+<kbd>C</kbd> → paste.
  Reader View strips menus, ads and sidebars, which is exactly what you want —
  a nav bar read aloud is unbearable.
- **PDFs**: select in Firefox's PDF viewer, copy, paste.
- **Epub/text files**: open the file directly in Firefox, copy all, paste.
- Keep the reader tab **pinned** (<kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>P</kbd>)
  so it stays out of the way but the page (and its audio) stays alive.

## 3 · The extension — read *any* page in place

`extension/` in this repo is a Manifest V2 Firefox add-on. It adds
"FORGE: read this page / read the selection" to the right-click menu and to the
toolbar button, and plays inside the page itself (so it survives closing the
popup and keeps playing while you scroll).

### Load it (2 minutes, temporary)

1. Start the server (step 1).
2. In Firefox, go to `about:debugging#/runtime/this-firefox`.
3. **Load Temporary Add-on…** → pick `C:\Users\l3ung\forge\extension\manifest.json`.
4. Open any article → right-click → **FORGE: read this page in my voice**.

A temporary add-on is removed when Firefox restarts — reload it the same way.
(After installing, **reload pages that were already open** so the content
script is injected.)

### Load it permanently (signed)

Firefox release refuses unsigned add-ons, so either:

- **Sign it for yourself** (free, no review queue for unlisted add-ons):
  zip the *contents* of `extension/`, upload at
  <https://addons.mozilla.org/developers/addon/submit/> as **On your own site**
  (unlisted), download the signed `.xpi`, and open it in Firefox
  (`about:addons` → gear → *Install Add-on From File*). It then loads
  automatically forever.
- or use **Firefox Developer Edition / Nightly**, set
  `xpinstall.signatures.required` to `false` in `about:config`, and install the
  unsigned zip as an `.xpi`.

### Settings

`about:addons` → FORGE → **Preferences** (or the popup's *Settings* link):
server URL, optional token, language, speed, temperature, and whether to
auto-scroll to the paragraph being read.

### How the page reading works

- It prefers `<article>`/`<main>`/the densest `<p>` container, and drops
  invisible elements plus cookie-banner-looking one-liners.
- It splits content into ≤900-character requests and prefetches nothing, so it
  never blocks the page for long. Long pages simply queue up.
- **Selection wins**: select a paragraph, right-click → *read the selection*.
- Right-click → *FORGE: stop reading* (or the toolbar button) stops instantly.

## 4 · The HTTP API (for everything else)

```bat
:: one sentence to a file
curl -X POST http://127.0.0.1:5004/speak ^
     -H "Content-Type: application/json" ^
     -d "{\"text\":\"Hello from my own voice\"}" -o out.wav
start "" out.wav
```

| Method | Path | Body / query | Returns |
|---|---|---|---|
| GET | `/` or `/reader` | – | the reader page |
| GET | `/health`, `/voice` | – | active voice, languages, loaded?, device |
| GET | `/api/voices` | – | voices found in `%USERPROFILE%\forge\voices` |
| POST | `/speak` | `{"text","lang","speed","temperature"}` | `audio/wav`, 24 kHz mono 16-bit |
| POST | `/voices` | `{"voice":"C:\\path\\to\\folder"}` | switches voice, 200 |
| GET | `/style.css`, `/reader.js` | – | static assets |

Errors come back as `{"error": "..."}` with a real status code (400 bad input,
401 bad token, 403 wrong Host header, 413 text too long, 500 synthesis failed).

From Python, without HTTP at all:

```python
from forge.synth import TTSEngine
engine = TTSEngine(r"C:\Users\l3ung\forge\voices\my-voice")   # loads once
open("a.wav", "wb").write(engine.speak("Hello world"))
```

## 5 · Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Page says "server offline", retries forever | The console window was closed, or the server crashed. Restart `serve-forge.bat`; check its output. |
| `OSError: [WinError 10048]` on start | Port 5004 already in use (another FORGE, or a leftover run). `--port 5005`. |
| `No voice given and none found` | No exported voice in `%USERPROFILE%\forge\voices`. Pass `--voice` with the folder that has `model.pth`, `config.json`, `vocab.json`, `speaker_ref.wav`. |
| `... is only 12 bytes — that is not trained weights` | You pointed at the Git placeholder, not your real checkpoint. |
| First sentence takes ~20 s, then it's fast | Normal — that's the model loading into VRAM. |
| `Firefox blocked autoplay` | Press **Play** once; Firefox only allows audio started by a click. (Once per page.) |
| Extension does nothing on a page | Reload the tab after installing; `about:debugging` must still list the add-on (temporary ones vanish on restart). |
| 401 | Server started with `--token` but the page/extension has no token: use `?token=…` or set it in the extension's settings. |
| 403 "wrong Host header" | Something reached the server under a different hostname — that's the DNS-rebinding guard. Use `127.0.0.1` or `localhost`. |
| Voice sounds flat / rushed / weird | Exaggerated input text is exaggerated back. Try temperature 0.6–0.8, speed 0.95–1.05, and keep `speaker_ref.wav` clean. |
| CUDA out of memory | `--device cpu` (slow) or close the training app; training and inference both want the GPU. |
| Antivirus/firewall popup on first run | It's binding to loopback only. Denying public/private network access is fine — nothing external is needed. |

## 6 · Security notes

- Default bind is `127.0.0.1`: only this PC can reach it. Nothing is uploaded.
- **CORS is open** — `Access-Control-Allow-Origin: *`. That's deliberate: the
  extension's page-side player calls the server from whatever site you're on.
  The consequence is that *any website you visit* can ask your local server to
  synthesise text. It can't read your files or your voice package (the API has
  no file access), but it can make your GPU work. If that bothers you:
  start with `--token <random-string>` and put the same string in the extension
  settings. Requests without it get 401.
- **Host header pinning** blocks DNS-rebinding attacks (a page whose hostname
  resolves to 127.0.0.1 is refused).
- `--host 0.0.0.0` exposes the server to your LAN. Don't, unless you also pass
  `--token`.

## 7 · Why not…?

- **`speechSynthesis` / OS voices** — that's Microsoft's voices, not yours.
- **Running the model in the browser** (ONNX/WebGPU) — XTTS v2 is ~1.8 GB of
  weights and a GPT-style autoregressive decoder; browser ports exist for tiny
  models, not this. The local-server design above gives you the same UX.
- **A `file://` page** — Firefox blocks fetch from file pages; use the served
  `http://127.0.0.1:5004/reader` page instead. (`127.0.0.1` counts as a secure
  context, so no mixed-content issues even if you later serve other pages over
  https.)
