# speak.py — use your model.pth, without FORGE

One file. It loads the voice you trained and reads text out loud on your PC.

```
python speak.py "hello there"        # say this
python speak.py --file notes.txt     # say a file
python speak.py                      # say whatever is on the clipboard
python speak.py --watch              # say whatever you copy, forever
python speak.py "hi" --out hi.wav    # save a wav instead of playing
```

On Windows you don't even need to type that — double-click **`say.bat`**
(or pin it to the taskbar) and it speaks the clipboard.

**To read this conversation:** copy the text you want (select it, `Ctrl`+`C`),
then double-click `say.bat`. Or run `say.bat --watch` once and from then on
every `Ctrl`+`C` is spoken in your voice — no clicking, no browser, no FORGE.

---

## First run: prove the model loads

```bat
say.bat --check
```

It prints the four files it found, the checkpoint size, the device and the
languages, and says `OK` — without speaking. If that works, everything after it
works. (A 5–6 GB `model.pth` is normal: that's a full training checkpoint with
optimizer state, not a stripped one. It needs a few GB of free RAM and a slow
first load, then it's fast.)

## Where your model is

The folder FORGE exported already has everything:

```
C:\Users\l3ung\forge\voices\my-voice\
    model.pth         your trained weights (~1.8 GB)
    config.json       the XTTS v2 config it was trained with
    vocab.json        tokenizer vocabulary
    speaker_ref.wav   6–15 s of your voice
```

It finds that folder automatically. If yours lives elsewhere, either
pass it once:

```bat
python speak.py "hello" --voice "D:\my-voice"
```

…or write the path on one line into a file called **`voice.txt`** next to
`speak.py`:

```
D:\my-voice
```

A single `model.pth` works too — as long as `config.json`, `vocab.json` and a
`.wav` of your voice sit next to it (`--voice path\to\model.pth`).

## Requirements

Python with **torch + coqui-TTS**.

`say.bat` finds that Python itself — it tries, in order: `%FORGE_PY%` if you set
it, FORGE's `.venv` next door, `py -3.11` / `-3.12` / `-3.10` / `-3.13`, then
plain `python`. First one that can `import torch, TTS` wins. If you installed
the packages with plain `pip` (no venv), plain `python` is what it will use.

Check it yourself with:

```bat
python -c "import torch, TTS; print('ok')"
```

If that fails, install them once. On a new machine:

```bat
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu130
pip install coqui-TTS
```

Nothing else: no numpy install step (torch brings it), no flask, no gradio, no
browser, no server, no add-on. Audio plays through `winsound`, which is part of
Python on Windows.

## Speed

The model takes ~15 s to load into VRAM the first time. After that each sentence
takes about a second, and `speak.py` **starts talking after the first sentence**
while it generates the rest — and keeps generating ahead of playback, so there
are no gaps.

That's why `--watch` exists: it loads once and stays loaded. If you run
`say.bat` fresh for every sentence you pay the 15 s every time.

## Options

| Flag | What it does |
|---|---|
| `--voice PATH` | folder or `model.pth` (default: `voice.txt`, then `%USERPROFILE%\forge\voices\my-voice`) |
| `--check` | load the model and report what it found, say nothing |
| `--out file.wav` | save the whole thing as one wav instead of playing |
| `--lang en` | language code (XTTS v2 has 17) |
| `--speed 1.0` | 0.9 slower, 1.1 brisker |
| `--temperature 0.7` | 0.6 = steady, 0.9 = more expressive |
| `--device cpu` | if CUDA misbehaves (much slower) |
| `--raw` | don't strip markdown (`**`, `#`, links, code fences) |
| `--quiet` | no progress lines on stderr |

Markdown is stripped by default because copied chat/article text is full of
`**bold**`, `#` headings, links and code fences, and those read badly aloud.
Code fences are dropped entirely.

## Make it a keyboard shortcut

1. Right-click `say.bat` → **Send to → Desktop (create shortcut)**.
2. Right-click the new shortcut → **Properties** → *Shortcut key* → press
   e.g. `Ctrl`+`Alt`+`S` → **OK**.
3. Select text anywhere, `Ctrl`+`C`, then `Ctrl`+`Alt`+`S`.

Still no FORGE, no extra software: that's a built-in Windows shortcut.

## If something goes wrong

| Message | Meaning |
|---|---|
| `Could not find your model.` | It lists every path it tried. Add `--voice` or a `voice.txt`. |
| `…is only 12 bytes` | You pointed at a placeholder (a Git checkout), not the real model. |
| `does not look like an XTTS v2 checkpoint` | The `.pth` is from a different architecture (Bark, RVC, So-VITS…). |
| `is missing: config, vocab, speaker_ref` | Point `--voice` at the exported folder, not a bare `.pth` on its own. |
| `Missing Python package: TTS` | `pip install coqui-TTS`, or use FORGE's `.venv` (`say.bat` does). |
| `[speak] no audio player here` | It saved numbered `.wav` files instead — open them. |
| `CUDA out of memory` | `--device cpu`, or close whatever else is using the GPU. |
| Nothing at all, no error | The clipboard was empty — copy something first. |

## Why this is the whole story

`model.pth` is a PyTorch checkpoint: it needs Python + torch to run, and that's
unavoidable. But it does not need the FORGE app, its UI, its training code or
its server. `speak.py` is 500 lines, uses only `torch`, `TTS`, `numpy` and the
Python standard library, and runs from any folder you drop it in.
