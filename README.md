# FORGE — your voice, your model

Upload recordings of your voice. Get back a text-to-speech model trained on *you*.
Runs entirely on your machine, offline after the first setup. Nobody else's voice,
nobody else's cloud, nobody else's kill switch.

Built on the proven Coqui XTTS v2 fine-tuning recipe (MPL-2.0), wrapped in a
single three-tab app and hardened for Windows.

## What you need

- **Windows PC with an NVIDIA GPU** (12GB+ VRAM recommended; a 16GB card like the
  RTX 5070 Ti is the sweet spot)
- **Python 3.10 or 3.11** (not 3.12+ — some deps lag behind)
- **ffmpeg** on PATH (for audio handling)
- **Your voice**: clean recordings, one speaker, quiet room. 2 minutes minimum,
  **10–60 minutes recommended**. More varied, natural speech = better voice.
  A ready-made reading script is in `recording-script.txt`.
- Internet **once** (downloads the XTTS v2 base model ~2GB + Whisper ~3GB).
  After that, fully offline.

## Install

```bat
:: 1. CUDA-enabled torch first
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu130
:: (cu130 — the RTX 5070 Ti is Blackwell/sm_120, which needs CUDA 12.8+ kernels;
::  cu121 tops out at sm_90 and dies with "no kernel image is available")

:: 2. Everything else
pip install -r requirements.txt
```

## Run

```bat
python run.py
```

Opens `http://127.0.0.1:5003` in your browser. Three tabs:

1. **Dataset** — upload your recordings → builds transcribed training clips
   (Whisper transcribes + segments automatically; no manual labeling).
2. **Train** — fine-tunes XTTS v2 on your voice. Takes a few hours; the log
   tails live in the UI. Defaults are tuned for a 16GB card — lower *Batch size*
   if you hit VRAM limits.
3. **Voice** — type text, hear *your* voice say it. Export the voice as a
   portable `.zip` (model + config + vocab + speaker reference + manifest).

## Roam — one frontend whose backend roams

Training takes hours; free GPU sessions die. The Train tab's **Backend**
dropdown offers **Roam (auto-failover)**: the job is handed to an
orchestrator (`forge/roam/`) that runs it on your local GPU first, watches
it, and — if the session dies — rescues the latest checkpoint and resumes
on the next provider. The UI never changes; the backend roams.

- **local**: your GPU (works now, zero setup).
- **kaggle**: free GPU via the Kaggle Kernels API. `pip install kaggle`,
  save your API token to `~/.kaggle/kaggle.json`, and Roam will upload your
  dataset once, push a training kernel, and resume across killed sessions
  automatically. See `forge/roam/DESIGN.md`.
- **colab**: documented manual path in DESIGN.md (no stable API; the
  provider interface is ready for an adapter).

## Use your voice anywhere

```bat
.venv\Scripts\activate
python -m forge.synth --voice "%USERPROFILE%\forge\voices\my-voice" --text "Hello world" --out out.wav
```

Or double-click-free and one line shorter:

```bat
say.bat "Hello world"
```

Point anything at that command — scripts, the auto-TTS userscript's future
local-server mode, your phone stack — and it's your voice speaking.

## Read Aloud on any site (Firefox)

Select text on any web page → right-click → **Read Aloud** → hear it in your
own voice. The voice lives in a small local server (a `.pth` can't run inside a
browser); the add-on sends the text there and plays what comes back.

```bat
serve-forge.bat
:: or: python -m forge.server --voice "%USERPROFILE%\forge\voices\my-voice"
```

Then load the add-on once per Firefox session:
`about:debugging#/runtime/this-firefox` → **Load Temporary Add-on…** →
`C:\Users\l3ung\forge\extension\manifest.json`. Sign it once via
addons.mozilla.org to make it permanent.

- **right-click → Read Aloud** — speaks the selection (`Alt`+`Shift`+`R`)
- **right-click → Read Aloud — whole page** — article body only, nav/banners skipped
- a small bar shows `Reading… 3/12` with pause and stop
- if Firefox blocks autoplay, the bar offers one **▶ Start** click

No add-on? <http://127.0.0.1:5004/reader> reads pasted text, and
<http://127.0.0.1:5004/tools> has a self-test plus a draggable bookmarklet.

Setup, signing, the HTTP API (`POST /speak`) and the troubleshooting table:
**[docs/FIREFOX.md](docs/FIREFOX.md)**.

## "I already have a model.pth — how do I run it?"

A `.pth` is the *weights*. It is not yet a voice. XTTS also needs the config it
was trained with, the tokenizer vocab, and a short reference clip of the
speaker. A complete FORGE voice is these four files in one folder:

```
my-voice\
  model.pth        ~1.8 GB  your fine-tuned weights
  config.json       the XTTS v2 config those weights were trained with
  vocab.json        tokenizer vocabulary
  speaker_ref.wav   6–15 s clean clip of the voice (speaker conditioning)
  voice.json        optional manifest FORGE writes
```

Pick the case that matches you:

**1. FORGE already exported it** (`%USERPROFILE%\forge\voices\my-voice`, and a
`.zip` next to it). Point the app or the CLI at that folder — nothing else to do:

```bat
python -m forge.synth --voice "%USERPROFILE%\forge\voices\my-voice" --text "Hello world" --out out.wav
```

In the app, tab **3 · Voice** fills that path in automatically; you can also
paste the folder *or* `model.pth` itself into the field and press **Speak**.

**2. You only have the raw checkpoint** from `forge\run\training\<run-name>\`
(`model.pth` or `best_model.pth`). `config.json` and `vocab.json` were copied
next to it by training, so give the CLI the `.pth` and a reference wav — any
clean clip of the voice works, 6–15 s:

```bat
python -m forge.synth --checkpoint "%USERPROFILE%\forge\run\training\FORGE_XTTS-...\model.pth" ^
    --speaker-ref "%USERPROFILE%\forge\run\training\FORGE_XTTS-...\wavs\clip_00000001.wav" ^
    --text "Hello world" --out out.wav
```

Add `--config` / `--vocab` only if those two files live somewhere else.

**3. The `.pth` came from somewhere else** (another repo, a download, a
friend). It will only load if it is an **XTTS v2 GPT checkpoint** *and* you also
have its `config.json` and `vocab.json` — the base XTTS v2 ones are fine only if
it was fine-tuned from XTTS v2 with the standard recipe. A `.pth` from Bark,
Piper, VITS, So-VITS-SVC, RVC or Tortoise is a different architecture and will
never load here. Copy the three files plus your reference wav into one folder,
then use case 1 or 2. Note the licence: Coqui's XTTS v2 weights are **CPML —
non-commercial**; your own fine-tune inherits that.

### Windows 10 Home specifics

- **Home is fine.** Nothing here needs Hyper-V, WSL2, Docker, Pro/Enterprise
  features, or admin rights after Python and the GPU driver are installed.
  Training and inference are plain Python + CUDA.
- **GPU**: install the NVIDIA driver, then a CUDA build of torch (see *Install*).
  On a card without enough VRAM the `.pth` still *runs* — inference needs far
  less than training. Force CPU with `--device cpu` if CUDA acts up; it's slow
  (a sentence takes tens of seconds), but it works on integrated graphics.
- **Quote every path.** `C:\Users\<you>\...` contains no spaces usually, but
  `%USERPROFILE%` expands with backslashes — always wrap it in `"` so cmd.exe
  doesn't eat it, and use `^` to continue a long command on the next line.
- **If the Windows Store's Python stub opens instead of Python**, install from
  python.org (3.10/3.11) and tick *Add python.exe to PATH*.
- **A Git checkout's `model.pth` may be a 12-byte placeholder** (real weights
  are ~1.8 GB and are usually not committed). If you see "is only N bytes —
  that is not trained weights", you're holding the placeholder, not your model.
- SmartScreen may warn the first time `say.bat` runs (*More info → Run anyway*);
  it's a plain batch file that activates `.venv` and calls `forge.synth`.

## Honest expectations

- 2 min of audio: it will work, barely. 10+ min: recognizably you.
  30–60 min: genuinely good. **30 hours: as good as this technology gets** —
  FORGE has no data ceiling. Point it at a folder of recordings and it will
  transcribe, segment, quality-filter (silence / non-speech / fragments are
  dropped automatically), and train on all of it.
- More data needs *fewer* epochs, not more — the app suggests epoch counts
  from your dataset size (10 epochs for minutes of audio, down to 3 for 8h+).
- Garbage in, garbage out: background noise, echo, and mic-handling sounds
  become part of the voice. Record in a closet if you have to — clothes are
  free acoustic treatment.
- Training is the slow part (hours, not minutes — longer for huge datasets).
  Dataset building is minutes-to-an-hour depending on size. Inference
  afterwards is seconds.
- This fine-tunes the base model's speech generator on your data. The result
  is *your* voice model — a `model.pth` you own — not a reference-clip trick.

## Responsibility

Only train on your own voice, or a voice you have explicit permission to use.
Every exported package is your responsibility once it leaves your machine.

## Layout

```
forge/
  run.py               # launcher
  run-forge.bat        # double-click launcher (activates .venv)
  serve-forge.bat      # local TTS server for browsing (Firefox) — port 5004
  say.bat              # say.bat "hello" -> said.wav, played
  requirements.txt
  README.md
  recording-script.txt # ~10 minutes of varied reading material
  forge/
    app.py             # Gradio UI (Dataset -> Train -> Voice)
    dataset.py         # whisper transcription + segmentation -> CSVs
    train.py           # XTTS v2 GPT fine-tuning (Windows-safe)
    synth.py           # inference engine + voice packaging + CLI
    server.py          # HTTP TTS server (Firefox reader, extensions, scripts)
    web/               # the reader page (no build step, no CDN)
    files.py           # workdir tree browser
    roam/              # failover orchestrator (local -> Kaggle)
  extension/           # Firefox add-on: read any page in your voice
  docs/FIREFOX.md      # browser setup + troubleshooting
```

`forge.synth` is the importable API too, if you'd rather drive it from your own
script:

```python
from forge.synth import synthesize
synthesize("Hello world", r"C:\Users\me\forge\voices\my-voice", "out.wav", "en")

# many lines? load once, then speak as often as you like
from forge.synth import TTSEngine
engine = TTSEngine(r"C:\Users\me\forge\voices\my-voice")
for line in ["first", "second", "third"]:
    open(f"{line}.wav", "wb").write(engine.speak(line))
```
