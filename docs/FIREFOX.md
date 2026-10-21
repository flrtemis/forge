# Highlight text on any site → right-click → **Read Aloud**

That is the whole feature: any page, select a paragraph, right-click,
**Read Aloud**, and you hear it in the voice of your own `model.pth`.

```
Firefox ──text──►  127.0.0.1:5004 (python -m forge.server)  ──►  your model.pth (GPU)
        ◄─audio──
```

A `.pth` is 1.8 GB of PyTorch and cannot run inside a browser, so the voice runs
in a tiny server on your own PC and the page plays what it returns. Loopback
only, nothing uploaded, works offline.

---

## Step 1 — start the voice server (once per session)

Double-click **`serve-forge.bat`** in `C:\Users\l3ung\forge`. Or:

```bat
cd C:\Users\l3ung\forge
.venv\Scripts\activate
python -m forge.server --voice "%USERPROFILE%\forge\voices\my-voice"
```

```
[forge] TTS server on http://127.0.0.1:5004/  (voice: C:\Users\l3ung\forge\voices\my-voice)
```

Leave that window open while you read; it loads the model on the first sentence
(10–20 s) and then answers in about a second. **No voice given?** It uses the
newest folder in `%USERPROFILE%\forge\voices`. First stop is also this window's
`Ctrl+C`.

**Check it before going further:** open <http://127.0.0.1:5004/tools> and press
**Speak a test sentence**. If you hear your voice, the hard part is done and any
remaining problem is browser-side.

## Step 2 — load the add-on (four clicks, once per Firefox session)

1. Start the server (step 1).
2. Address bar: `about:debugging#/runtime/this-firefox`
3. **Load Temporary Add-on…**
4. Pick `C:\Users\l3ung\forge\extension\manifest.json`

A speech-bubble icon appears on the toolbar. **Reload pages that were already
open** (the add-on only attaches to pages loaded after it).

## Step 3 — use it

1. On **any** website, select the text you want to hear (a sentence, a paragraph,
   half a page — anything).
2. **Right-click → Read Aloud.**
3. It speaks, in your voice. A small bar bottom-right shows `Reading… 3/12`
   with pause `❚❚` and stop `■`.

Without a selection you get two more items:

- **Read Aloud — from here** — starts at the paragraph you right-clicked and
  carries on to the end of the article. Works inside links, images, list items
  and code blocks too (it climbs to the enclosing block).
- **Read Aloud — whole page** — the whole article body.

| Action | Menu | Shortcut |
|---|---|---|
| Read the selection | right-click → **Read Aloud** | `Alt`+`Shift`+`R` |
| Read from the paragraph you clicked | right-click → **Read Aloud — from here** | – |
| Read the whole article | right-click → **Read Aloud — whole page** | `Alt`+`Shift`+`A` |
| Pause / resume | the player bar | `Alt`+`Shift`+`P` |
| Stop | right-click → **Stop reading** | `Alt`+`Shift`+`S`, or `Esc` on the page |

## What "the page" means

`document.body` is the wrong thing to read — it's mostly navigation. The player
picks the most specific *prose container* first:

| Page | What gets read |
|---|---|
| **GitHub repo** | the **README** (`.markdown-body`) — not the file list, sidebar, branch bar or footer |
| **GitHub issue / PR** | the description **and every comment**, in order |
| **GitHub code view** | the code lines; toolbar ("Go to file", "Code") skipped |
| **GitHub wiki / gist** | the rendered markdown |
| **Blog post** | `.entry-content` / `.post-content` / `article` / `.post` — comments and newsletter boxes excluded |
| **Docs site** (mkdocs, sphinx, docusaurus) | `.md-content` / `.rst-content` / `.prose` — the table-of-contents sidebar is excluded |
| **Plain article-shaped page** | whatever prose exists; anything inside `header`, `nav`, `footer`, `aside`, or with a class/id like `sidebar`, `cookie`, `breadcrumb`, `promo`, `newsletter` is dropped |
| **Everything else** | the best available `<main>`/`<article>` |

Code fences inside prose (`<pre>`) are skipped unless you tick *Read code
blocks too* — "pip install torch torchaudio --index-url https://…" does not
become a pleasant sentence. Selecting the code and using **Read Aloud** always
works, since the selection path never filters.

Detection is deliberately conservative: if it can't find a prose container it
reads the body and filters chrome, and if the right-click landed outside the
article, "from here" falls back to the whole page instead of reading the menu.

**GitHub specifics:** repo pages are single-page apps, so the add-on stays
loaded as you browse — but if the URL changes mid-sentence, reading **stops**
rather than narrating the page you just left. Re-open the menu on the new page.

If Firefox blocks the first playback (its autoplay policy doesn't always count a
right-click as a page gesture), the bar says **“Autoplay blocked — click ▶ to
start”**. One click and it reads normally from there.

## Permanent install (so it survives restarts)

Temporary add-ons disappear when Firefox closes. Make it permanent by signing
it once — free, no review queue for unlisted add-ons:

1. Zip the **contents** of `C:\Users\l3ung\forge\extension\` (so `manifest.json`
   is at the top of the zip, not inside a folder). In Explorer: select all items
   in `extension\` → right-click → *Send to → Compressed (zipped) folder*.
2. Go to <https://addons.mozilla.org/developers/addon/submit/>, choose
   **On your own site** (unlisted), upload the zip.
3. Download the signed `.xpi` it gives you, then in Firefox:
   `about:addons` → gear icon → **Install Add-on From File…**
4. Done — the “Read Aloud” menu item is there after every restart.

(Alternatively, with Firefox Developer Edition or Nightly, set
`xpinstall.signatures.required` to `false` in `about:config` and install the
unsigned zip renamed to `.xpi`.)

## No add-on at all? Two fallbacks

**The reader page** — <http://127.0.0.1:5004/reader>: paste text, **Read aloud**.
Best source of clean text is Reader View (`Ctrl`+`Alt`+`R`, then select all,
copy). Gives you a clickable sentence list, speed and expressiveness sliders.

**A bookmarklet** — open <http://127.0.0.1:5004/tools>, drag the **Read Aloud**
button to your bookmarks toolbar. Then: select text → click the bookmark. No
install, survives restarts, but it's a toolbar click rather than a right-click,
and some sites' CSP blocks `javascript:` links.

## Where it can't work (Firefox restriction, not a bug)

Extensions are not allowed to touch these, so “Read Aloud” is not offered or
will report it can't inject:

- `about:` pages (`about:config`, `about:newtab`, …)
- `addons.mozilla.org` (Mozilla blocks add-ons there on purpose)
- Firefox's **built-in PDF viewer** and `view-source:` pages
- `file://` URLs unless you enable *“Allow this extension to access local files”*
- **inside an iframe** the click is visible but the frame's content usually isn't
  (cross-origin), so "from here" reads the top page instead; the built-in PDF
  viewer is the common case of this

For those, copy the text and paste it into the reader page. (A PDF opened in
Firefox: `Ctrl`+`A`, `Ctrl`+`C`, paste into the reader.)

## The HTTP API (for scripts, other browsers, anything)

```bat
curl -X POST http://127.0.0.1:5004/speak ^
     -H "Content-Type: application/json" ^
     -d "{\"text\":\"Hello from my own voice\"}" -o out.wav
start "" out.wav
```

| Method | Path | Body / query | Returns |
|---|---|---|---|
| GET | `/tools` | – | setup + self-test page |
| GET | `/reader`, `/` | – | the reader page |
| GET | `/health`, `/voice` | – | active voice, languages, loaded?, device |
| GET | `/api/voices` | – | voices in `%USERPROFILE%\forge\voices` |
| POST | `/speak` | `{"text","lang","speed","temperature"}` | `audio/wav` 24 kHz mono 16-bit |
| POST | `/voices` | `{"voice":"C:\\path\\to\\folder"}` | switch voice (loads on next line) |

Errors are `{"error": "..."}` with real status codes: 400 bad input, 401 bad
token, 403 wrong `Host` header, 413 text too long (> 5000 chars — the add-on
chunks at ~900), 500 synthesis failed.

No HTTP at all:

```python
from forge.synth import TTSEngine
engine = TTSEngine(r"C:\Users\l3ung\forge\voices\my-voice")   # long
open("line.wav", "wb").write(engine.speak("Hello world"))      # ~1 s each after the first
```

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| No “Read Aloud” in the right-click menu | The add-on isn't loaded (`about:debugging` should list it) — temporary add-ons vanish on Firefox restart. Re-load step 2. |
| Menu is there, nothing happens | Server not running or crashed. Check the console window; open <http://127.0.0.1:5004/tools>. Then reload the tab. |
| “Autoplay blocked — click ▶ to start” | Firefox's autoplay policy. Click ▶ once; it then plays normally. |
| Bar shows `FORGE error: Failed to fetch` | Server down, wrong port, or a `--token` mismatch. Start/restart the server; check the port in the add-on's settings. |
| Silent first sentence for ~20 s | The model is loading into VRAM. Normal. |
| `WinError 10048` on start | Port 5004 already in use → `--port 5005`, and set that URL in the add-on's settings. |
| `No voice given and none found` | No export in `%USERPROFILE%\forge\voices`; pass `--voice <folder>`. |
| `… is only 12 bytes — that is not trained weights` | You pointed at the Git placeholder, not your real checkpoint. |
| 401 | Started with `--token`; put the same token in the add-on settings. |
| 403 “wrong Host header” | Something reached the server under another hostname (DNS-rebinding guard). Use `127.0.0.1`/`localhost`. |
| Works on some sites, not others | Restricted pages above (about:, AMO, PDF viewer, file://). Or the page blocks the content script and needs a reload. |
| Choppy / gaps between sentences | The GPU is busy (e.g. training). Lower `--device cpu`? no — rather close the training app; or expect it. |
| Voice sounds flat / strange | Temperature 0.6–0.8, speed 0.95–1.05 in the add-on settings; and a clean `speaker_ref.wav`. |

## Security

- Binds to `127.0.0.1`: only this PC can reach it. No uploads, no telemetry.
- **CORS is open**, which is what lets the page-side player talk to the server
  from any site you visit. Consequence: any site you visit can ask your GPU to
  synthesise text. If that bothers you, start with `--token <random-string>` and
  put the same string in the add-on's settings (requests without it get 401).
- **Host header pinning** refuses requests addressed to another hostname, which
  blocks DNS-rebinding attacks.
- `--host 0.0.0.0` exposes your voice to the whole LAN — only with `--token`.

## Why not…?

- **`speechSynthesis`** — that's Microsoft's system voices, not yours.
- **Running the model in the browser** — XTTS v2 is a 1.8 GB autoregressive
  transformer; browser ports exist for tiny models, not this one.
- **A `file://` page instead of the server** — Firefox blocks `fetch` from file
  pages. `127.0.0.1` is a secure context, so the served pages behave like https
  pages without needing a certificate.
