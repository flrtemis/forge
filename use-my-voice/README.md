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

Check it yourself with a *deep* import — `import TTS` alone passes even when the
audio stack is broken, because Coqui loads most of itself lazily:

```bat
python -c "from TTS.tts.configs.xtts_config import XttsConfig; print('ok')"
```

If that raises `Numba needs NumPy 2.3 or less. Got NumPy 2.4.`, run
`python -m pip install "numpy<2.4"` — a numpy upgrade elsewhere broke the
librosa/numba stack that Coqui needs. Nothing to do with your model.

If that fails, install them once. On a new machine:

```bat
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu130
pip install coqui-TTS
```

Nothing else: no numpy install step (torch brings it), no flask, no gradio, no
browser, no server, no add-on. Audio plays through `winsound`, which is part of
Python on Windows.

## Windows gotchas already handled

Two things bite every Coqui/XTTS setup on Windows. Both are patched inside
`speak.py`, so you don't have to think about them:

1. **`Could not load libtorchcodec`** — torchaudio ≥ 2.9 decodes audio through
   torchcodec, which wants FFmpeg *shared* DLLs. `speak.py` reads WAV files
   itself (8/16/24/32-bit PCM, float, WAVE_FORMAT_EXTENSIBLE) and patches
   `torchaudio.load`, so loading `speaker_ref.wav` never reaches torchcodec.
2. **`Numba needs NumPy 2.3 or less. Got NumPy 2.4.`** — a numpy upgrade broke
   Coqui's librosa/numba stack. Either `python -m pip install "numpy<2.4"`, or
   run with FORGE's `.venv`, which is already consistent (`say.bat` prefers it).

## Speed

The model takes ~15 s to load into VRAM the first time. After that each sentence
takes about a second, and `speak.py` **starts talking after the first sentence**
while it generates the rest — and keeps generating ahead of playback, so there
are no gaps.

That's why `--watch` exists: it loads once and stays loaded. If you run
`say.bat` fresh for every sentence you pay the 15 s every time.

## Desktop double-clickers

A `.bat` you double-click gets no chance to type flags, so there are four ways
to get them in. Use whichever fits the moment.

### 1. `My Voice.bat` — it asks (best default)

Double-click it and a menu appears:

```
   1   Normal speech
   2   Slower and clearer        --speed 0.9
   3   More expressive           --temperature 0.85
   4   Steadier, predictable     --temperature 0.6
   5   Another language ...      --lang es
   6   Custom flags ...          type anything

   N   Start watching the clipboard with the above
   Q   Quit

    [##########----------]  4s  then it starts on its own
```

Press a number to change the voice, then `N` (or let the countdown run out and
it starts with **the settings you used last time** — it remembers them in
`%LOCALAPPDATA%\MyVoice\settings.txt`). No editing, ever.

### 1z. How long the menu waits

There is a visible countdown under the menu, so you can always see how much time
you have left:

```
    [##########----------]  4s  then it starts on its own
```

The bar fills in from the left while the number counts down, and when it reaches
zero it starts on its own. Press a key at any moment and it reacts right away —
you never have to wait for the bar to finish. `WAIT=0` swaps the bar for
`No countdown - press a key when you are ready.`

It is a real countdown rather than one long sleep: the `.bat` re-asks once per
second, which is exactly why a key pressed halfway through is caught instantly
instead of being ignored until the timer ends.

To change the length, open the file in Notepad and edit **one line** near the
top:

```bat
REM  8   = default: quick, but you have time to press a key
REM  20  = plenty of time to think
REM  0   = never auto-start; wait until you press a key (no countdown)
set "WAIT=8"
```

`set "WAIT=20"` gives you twenty seconds; `set "WAIT=0"` makes it wait forever
(no countdown at all). Windows' `choice` tops out at 9999 seconds, which is
plenty.

### 1a. What `settings.txt` should look like

The menu saves your choice in `%LOCALAPPDATA%\MyVoice\settings.txt`. Open it
with `notepad "%LOCALAPPDATA%\MyVoice\settings.txt"` — that's where you can
write several settings and see them all at once.

**Everything on one line** (this is what the menu writes):

```
--speed 0.9 --temperature 0.85 --lang es
```

**One thing per line** — same result, easier to read and edit. Blank lines and
comments (`#`, `REM`, `::`) are fine and are ignored:

```
# My Voice settings
--speed 0.9

--temperature 0.85
REM slower is clearer for long documents
--lang es
```

Rules that matter:

- A flag and its value can share a line (`--speed 0.9`) or sit on separate
  lines; the lines are joined with spaces, so both work.
- Paths containing spaces need quotes: `--voice "D:\My Voices\my-voice"`.
- Only pass flags the script understands (`speak.py --help`); a typo is reported
  as `unrecognized arguments: --speeed` rather than silently ignored.
- **Save as ANSI or UTF-8 *without* BOM.** Notepad's default ("UTF-8") is fine;
  "UTF-8 with BOM" puts three invisible bytes in front of the first flag, which
  then isn't recognised as a flag. `--watch` now prints
  `ignoring stray text argument(s)` when that happens, so it isn't silent.
- No `--watch` needed in the file (the .bat adds it), and `--voice` is supplied
  by the .bat too — anything you add here wins, because it comes last.
- Picking `1` (normal speech) in the menu deletes this file, so it can't keep
  applying an old slowing-down choice.

### 2. One desktop icon per mood (shortcut arguments)

A Windows shortcut can carry flags, so you get the same result with zero
keystrokes at launch:

1. Right-click `My Voice.bat` → **Send to → Desktop (create shortcut)**.
2. Right-click that shortcut → **Properties**.
3. In *Target*, append the flags **outside** the closing quote:

   ```
   "C:\Users\l3ung\Desktop\forge\use-my-voice\My Voice.bat" --speed 0.9 --temperature 0.85
   ```
4. Rename it *My Voice - Slow*. Repeat for *- Lively*, *- Spanish*.

Double-clicking it skips the menu and runs with those flags.

### 3. Drag a text file onto the icon

`My Voice.bat` reads any `.txt`/`.md` you drop on it (your saved settings still
apply):

```
[My Voice - Spanish.bat]  <-  article.txt
```

### 4. Edit the one `OPTIONS` line

`Watch My Voice.bat` and `Read What I Copied.bat` are the plain versions: open
in Notepad, change

```bat
set "OPTIONS="
```

to e.g. `set "OPTIONS=--speed 0.9 --lang es"`, save. That's it — the file *is*
the configuration.

### Flags from a terminal (no menu at all)

```bat
..\.venv\Scripts\python.exe speak.py --watch --speed 0.9 --temperature 0.85 --lang es
```

Every flag works with `--watch`; they are just more arguments on one command
line, in any order. Re-copying **the same text** speaks it again; `--watch`
ignores whatever is already on the clipboard at startup (add `--speak-now` to
read that too).

`Read What I Copied.bat` is the one-shot version: copy, double-click, it reads
the clipboard once and exits.

## Options

| Flag | What it does |
|---|---|
| `--voice PATH` | folder or `model.pth` (default: `voice.txt`, then `%USERPROFILE%\forge\voices\my-voice`) |
| `--check` | load the model and report what it found, say nothing |
| `--watch --speak-now` | also read whatever was already on the clipboard at startup |
| `--file notes.txt` | read a file (this is what a dropped file becomes) |
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
| `Could not load libtorchcodec` / `FFmpeg is not properly installed` | Old torchaudio decoding a WAV. Handled: `speak.py` reads WAVs itself and patches `torchaudio.load`, so this should not appear. If it does, you're on an older copy — re-download. |
| `Numba needs NumPy 2.3 or less. Got NumPy 2.4.` | A numpy/numba clash, not your model. `python -m pip install "numpy<2.4"` (or run with FORGE's `.venv`, which is already consistent). |
| `[speak] no audio player here` | It saved numbered `.wav` files instead — open them. |
| `CUDA out of memory` | `--device cpu`, or close whatever else is using the GPU. |
| Nothing at all, no error | The clipboard was empty — copy something first. |

## Why this is the whole story

`model.pth` is a PyTorch checkpoint: it needs Python + torch to run, and that's
unavoidable. But it does not need the FORGE app, its UI, its training code or
its server. `speak.py` is 500 lines, uses only `torch`, `TTS`, `numpy` and the
Python standard library, and runs from any folder you drop it in.
