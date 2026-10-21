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
python -m forge.synth --voice %USERPROFILE%\forge\voices\my-voice --text "Hello world" --out out.wav
```

Point anything at that command — scripts, the auto-TTS userscript's future
local-server mode, your phone stack — and it's your voice speaking.

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
  requirements.txt
  README.md
  recording-script.txt # ~10 minutes of varied reading material
  forge/
    app.py             # Gradio UI (Dataset -> Train -> Voice)
    dataset.py         # whisper transcription + segmentation -> CSVs
    train.py           # XTTS v2 GPT fine-tuning (Windows-safe)
    synth.py           # inference + voice packaging + CLI
```
