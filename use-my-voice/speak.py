#!/usr/bin/env python3
"""speak.py — read any text aloud with YOUR OWN model.pth.

No FORGE app, no server, no extension, no repo. This is one file. It loads the
XTTS v2 checkpoint you trained, turns text into speech, and plays it through
your speakers while it's still generating the rest.

    python speak.py "hello there"           # say this
    python speak.py --file notes.txt        # say a file
    type notes.txt | python speak.py        # say stdin
    python speak.py                         # say the clipboard (Windows)
    python speak.py --watch                 # say the clipboard, forever:
                                            #   copy text anywhere -> it speaks
    python speak.py "hi" --out hi.wav       # save instead of playing

Where your model lives (the folder FORGE exported, or a single .pth):

    C:/Users/you/forge/voices/my-voice/
        model.pth  config.json  vocab.json  speaker_ref.wav

It looks there by default; override with --voice, or write the path once into
a file called voice.txt next to this script.

Requires: torch + coqui-tts (the same ones FORGE installed) + numpy.
Nothing else. If the .venv that FORGE made exists, say.bat uses it.
"""
from __future__ import annotations

import argparse
import os
import queue
import re
import sys
import tempfile
import threading
import time
import wave

SAMPLE_RATE = 24000
HERE = os.path.dirname(os.path.abspath(__file__))
MIN_CKPT_BYTES = 1_000_000


# --------------------------------------------------------------------------
# where is the model?
# --------------------------------------------------------------------------
def _expand(p: str) -> str:
    return os.path.expanduser(os.path.expandvars(str(p).strip().strip('"')))


def _pick(folder: str, *candidates: str) -> str | None:
    for name in candidates:
        path = os.path.join(folder, name)
        if os.path.isfile(path):
            return path
    return None


def find_voice(voice_arg: str | None = None) -> dict:
    """Locate model.pth + config.json + vocab.json + a reference wav."""
    tried = []

    def from_folder(folder: str):
        ckpt = _pick(folder, "model.pth", "best_model.pth", "model.pth.tar")
        if not ckpt:
            tried.append(f"{folder} (no model.pth)")
            return None
        ref = _pick(folder, "speaker_ref.wav", "speaker_ref_original.wav")
        if not ref:                       # any wav in the folder will do
            wavs = sorted(f for f in os.listdir(folder) if f.lower().endswith(".wav"))
            ref = os.path.join(folder, wavs[0]) if wavs else None
        return {"dir": folder, "checkpoint": ckpt,
                "config": _pick(folder, "config.json", "config_config.json"),
                "vocab": _pick(folder, "vocab.json", "tokenizer.json"),
                "speaker_ref": ref}

    def from_checkpoint(path: str):
        folder = os.path.dirname(os.path.abspath(path))
        found = from_folder(folder)
        if found:
            found["checkpoint"] = path
        return found

    sources = []
    if voice_arg:
        sources.append(_expand(voice_arg))
    env = os.environ.get("MYVOICE") or os.environ.get("FORGE_VOICE")
    if env:
        sources.append(_expand(env))
    txt = os.path.join(HERE, "voice.txt")
    if os.path.isfile(txt):
        with open(txt, encoding="utf-8") as fh:
            line = fh.read().strip().splitlines()
        if line:
            sources.append(_expand(line[0]))
    sources.append(os.path.join(HERE, "voice"))                       # folder beside the script
    sources.append(os.path.join(os.path.expanduser("~"), "forge", "voices", "my-voice"))

    for src in sources:
        if os.path.isfile(src):
            found = from_checkpoint(src)
        elif os.path.isdir(src):
            found = from_folder(src)
        else:
            tried.append(f"{src} (does not exist)")
            continue
        if found:
            found["_sources_tried"] = tried
            return found

    raise SystemExit(
        "Could not find your model.\n"
        "Tried:\n  " + "\n  ".join(tried) + "\n\n"
        "Pass the folder once:\n"
        '  python speak.py "hello" --voice "C:\\Users\\you\\forge\\voices\\my-voice"\n'
        "or put that path on a single line in voice.txt next to speak.py.")


def check_voice(spec: dict) -> None:
    missing = [k for k in ("config", "vocab", "speaker_ref") if not spec.get(k)]
    if missing:
        have = sorted(os.listdir(spec["dir"]))
        raise SystemExit(
            f"{spec['dir']} is missing: {', '.join(missing)}\n"
            f"It contains: {', '.join(have) if have else '(nothing)'}\n"
            "A voice = model.pth + config.json + vocab.json + a speaker_ref.wav "
            "(6-15 s of the voice).")
    size = os.path.getsize(spec["checkpoint"])
    if size < MIN_CKPT_BYTES:
        raise SystemExit(
            f"{spec['checkpoint']} is only {size} bytes — that is not trained "
            "weights. Point --voice at the real model.pth (~1.8 GB).")


# --------------------------------------------------------------------------
# model
# --------------------------------------------------------------------------
def _venv_hint() -> str:
    """Point at FORGE's own virtualenv when it exists next to this script."""
    for rel in (r"..\.venv\Scripts\python.exe", r"..\.venv\bin\python",
                r".venv\Scripts\python.exe"):
        candidate = os.path.abspath(os.path.join(HERE, rel))
        if os.path.isfile(candidate):
            return ("Or use FORGE's working virtualenv, no installs needed:\n"
                    f'  "{candidate}" speak.py "hello"')
    return ""


def _import_hint(message: str) -> str:
    """Turn the usual dependency clashes into a one-line fix."""
    lower = message.lower()
    if "numba needs numpy" in lower:
        return (
            "Your Python has conflicting package versions (Coqui's audio stack "
            "imports numba, and numba refuses the installed numpy).\n\n"
            "This is NOT your model. Fix it with one command, then rerun:\n"
            '  python -m pip install "numpy<2.4"\n\n'
            "Something upgraded numpy to 2.4 after FORGE was set up. If you would "
            "rather touch nothing global, use FORGE's own virtualenv:\n"
            + (_venv_hint() or "  ..\\.venv\\Scripts\\python.exe speak.py \"hello\""))
    if "no module named 'librosa'" in lower or "no module named 'numba'" in lower:
        return (
            "Coqui TTS is installed but its audio dependencies are not.\n"
            "  python -m pip install librosa numba\n" + _venv_hint())
    return ("Could not import Coqui TTS:\n  " + message +
            "\n\nTry:\n  python -m pip install --upgrade coqui-TTS\n" + _venv_hint())


class Voice:
    """One loaded XTTS voice. Load costs ~15 s; each sentence ~1 s."""

    def __init__(self, spec: dict, device: str = "auto", log=print):
        try:
            import torch
            from TTS.tts.configs.xtts_config import XttsConfig
            from TTS.tts.models.xtts import Xtts
        except ModuleNotFoundError as exc:
            raise SystemExit(
                f"Missing Python package: {exc.name}\n"
                "Install them once (the same ones FORGE used):\n"
                "  pip install torch torchaudio --index-url "
                "https://download.pytorch.org/whl/cu130\n"
                "  pip install coqui-TTS\n"
                + _venv_hint())
        except ImportError as exc:
            raise SystemExit(_import_hint(str(exc)))

        if device == "auto":
            device = "cuda" if torch.cuda.is_available() else "cpu"
        self.device = device
        self.torch = torch
        gb = os.path.getsize(spec["checkpoint"]) / 1e9
        log(f"[speak] loading {os.path.basename(spec['checkpoint'])} "
            f"({gb:.1f} GB) on {device} ...")
        if gb > 3:
            log("[speak] that is a full training checkpoint (weights + optimizer "
                "state). Loading it needs a few GB of free RAM and takes a while; "
                "after that it is fast.")

        cfg = XttsConfig()
        cfg.load_json(spec["config"])
        model = Xtts.init_from_config(cfg)
        try:
            model.load_checkpoint(cfg, checkpoint_path=spec["checkpoint"],
                                  vocab_path=spec["vocab"], use_deepspeed=False)
        except Exception as exc:                    # trainer-format checkpoints
            log(f"[speak] standard load failed ({type(exc).__name__}: "
                f"{str(exc).splitlines()[0]}) — trying as a raw state dict")
            self._load_raw(model, spec["checkpoint"])
        model.to(device)
        model.eval()

        self.model = model
        (self.gpt_cond_latent,
         self.speaker_embedding) = model.get_conditioning_latents(
            audio_path=[spec["speaker_ref"]])
        log("[speak] ready.")

    def _load_raw(self, model, checkpoint_path: str) -> None:
        """Load a checkpoint Coqui's loader did not like.

        FORGE's trainer writes full checkpoints ({"model": …, "optimizer": …});
        older/simpler scripts write a bare state dict with a "model." prefix or
        a "module." prefix from DataParallel. Try the plausible shapes.
        """
        torch = self.torch
        blob = torch.load(checkpoint_path, map_location="cpu", weights_only=False)
        state = blob
        for key in ("model", "state_dict", "model_state_dict"):
            if isinstance(blob, dict) and key in blob and isinstance(blob[key], dict):
                state = blob[key]
                break
        cleaned = {}
        for key, value in state.items():
            for prefix in ("module.", "_orig_mod."):
                if key.startswith(prefix):
                    key = key[len(prefix):]
            cleaned[key] = value
        missing, unexpected = model.load_state_dict(cleaned, strict=False)
        if len(missing) > len(cleaned) // 2:
            raise SystemExit(
                "This .pth does not look like an XTTS v2 checkpoint:\n"
                f"  {checkpoint_path}\n"
                f"  {len(missing)} of {len(cleaned)} tensors did not match the "
                "model. Is it from a different trainer/architecture?")
        if missing or unexpected:
            self.log(f"[speak] loaded with {len(missing)} missing / "
                     f"{len(unexpected)} extra tensors (usually harmless)")

    def say(self, text: str, lang="en", speed=1.0, temperature=0.7) -> bytes:
        """Text -> 16-bit mono 24 kHz WAV bytes (header included)."""
        out = self.model.inference(
            text, lang, self.gpt_cond_latent, self.speaker_embedding,
            temperature=float(temperature), speed=float(speed),
            enable_text_splitting=False,
        )
        wav = out["wav"]
        if hasattr(wav, "detach"):                 # torch tensor
            wav = wav.detach().cpu().numpy()
        import numpy as np
        pcm = np.clip(np.asarray(wav, dtype=np.float32).reshape(-1), -1.0, 1.0)
        pcm = (pcm * 32767.0).astype("<i2").tobytes()
        return pcm_to_wav(pcm)


def pcm_to_wav(pcm: bytes, rate: int = SAMPLE_RATE) -> bytes:
    import io
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return buf.getvalue()


# --------------------------------------------------------------------------
# text -> chunks
# --------------------------------------------------------------------------
ABBREVIATIONS = {
    "mr", "mrs", "ms", "dr", "prof", "st", "vs", "etc", "e.g", "i.e", "fig",
    "no", "inc", "ltd", "co", "dept", "approx", "u.s", "a.m", "p.m", "jr", "sr",
}


def clean_markdown(text: str) -> str:
    """Turn copy-pasted markdown/chat text into words worth hearing."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"```.*?```", " ", text, flags=re.S)        # code fences
    text = re.sub(r"`([^`]*)`", r"\1", text)                  # inline code
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text)         # images
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)      # links
    text = re.sub(r"https?://\S+", " ", text)                 # bare urls
    text = re.sub(r"^[ \t]{0,3}#{1,6}[ \t]*", "", text, flags=re.M)  # headings
    text = re.sub(r"(\*\*|__|\*|_|~~)", "", text)             # emphasis
    text = re.sub(r"\n(?=\s*[-*+]\s)", "\n\n", text)          # one bullet per line
    text = re.sub(r"^[ \t]*[-*+][ \t]+", "", text, flags=re.M)   # bullets
    text = re.sub(r"^[ \t]*>[ \t]?", "", text, flags=re.M)        # quotes
    text = re.sub(r"\|", " ", text)                           # tables
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _ends_with_abbreviation(sentence: str) -> bool:
    """True for '... Dr.' / '... e.g.' — the period did not end the sentence."""
    word = re.sub(r"[.!?…\"'”’)\]]+$", "", sentence).strip().split(" ")[-1]
    return word.lower().rstrip(".") in ABBREVIATIONS


def split_sentences(text: str, max_chars: int = 350) -> list[str]:
    """Split into speakable chunks. Small chunks = speech starts fast."""
    text = clean_markdown(text)
    if not text:
        return []

    chunks: list[str] = []
    for para in re.split(r"\n\s*\n", text):
        para = re.sub(r"\s+", " ", para).strip()
        if not para:
            continue
        parts = re.split(r'(?<=[.!?…])["\'”’)\]]*\s+', para)
        merged: list[str] = []
        for part in parts:
            part = part.strip()
            if not part:
                continue
            if merged and _ends_with_abbreviation(merged[-1]):
                merged[-1] = merged[-1] + " " + part
            else:
                merged.append(part)
        # an overly long "sentence" is usually a run-on or bullet soup
        for piece in merged:
            while len(piece) > max_chars:
                cut = piece.rfind(",", 0, max_chars)
                if cut < max_chars // 2:
                    cut = piece.rfind(" ", 0, max_chars)
                if cut <= 0:
                    cut = max_chars
                chunks.append(piece[:cut + 1].strip())
                piece = piece[cut + 1:].strip()
            if piece:
                chunks.append(piece)
    return chunks


# --------------------------------------------------------------------------
# playing it
# --------------------------------------------------------------------------
class Player:
    """Plays WAV bytes. Windows: winsound (stdlib, blocking). Else: files."""

    def __init__(self, save_path: str | None = None):
        self.save_path = save_path
        self._frames: list[bytes] = []
        self._rate = SAMPLE_RATE
        self._backend = "wav-files"
        if save_path is None:
            if sys.platform.startswith("win"):
                import winsound  # noqa: F401  (stdlib on Windows)
                self._backend = "winsound"
            else:
                try:
                    import sounddevice  # noqa: F401
                    self._backend = "sounddevice"
                except Exception:
                    try:
                        import simpleaudio  # noqa: F401
                        self._backend = "simpleaudio"
                    except Exception:
                        self._backend = "wav-files"

    def play(self, blob: bytes) -> None:
        if self.save_path:
            import io
            with wave.open(io.BytesIO(blob), "rb") as w:
                self._rate = w.getframerate()
                self._frames.append(w.readframes(w.getnframes()))
            return

        if self._backend == "winsound":
            import winsound
            fd, path = tempfile.mkstemp(suffix=".wav")
            os.close(fd)
            try:
                with open(path, "wb") as fh:
                    fh.write(blob)
                winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_NODEFAULT)
            finally:
                try:
                    os.remove(path)
                except OSError:
                    pass
            return

        if self._backend == "sounddevice":
            import io
            import numpy as np
            import sounddevice as sd
            with wave.open(io.BytesIO(blob), "rb") as w:
                rate = w.getframerate()
                data = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2")
            sd.play(data.astype(np.float32) / 32768.0, rate)
            sd.wait()
            return

        if self._backend == "simpleaudio":
            import simpleaudio
            play = simpleaudio.play_buffer(
                read_pcm(blob), 1, 2, read_rate(blob))
            play.wait_done()
            return

        # No sound API: leave numbered wav files in the current folder.
        path = os.path.join(os.getcwd(), f"speak_{int(time.time() * 1000)}.wav")
        with open(path, "wb") as fh:
            fh.write(blob)
        print(f"[speak] no audio player here — wrote {path}")

    def close(self) -> None:
        if not self.save_path:
            return
        with wave.open(self.save_path, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(self._rate)
            for frame in self._frames:
                w.writeframes(frame)
        print(f"[speak] wrote {os.path.abspath(self.save_path)}")


def read_pcm(blob: bytes) -> bytes:
    import io
    with wave.open(io.BytesIO(blob), "rb") as w:
        return w.readframes(w.getnframes())


def read_rate(blob: bytes) -> int:
    import io
    with wave.open(io.BytesIO(blob), "rb") as w:
        return w.getframerate()


def speak_chunks(voice: Voice, chunks: list[str], player: Player, *,
                 lang="en", speed=1.0, temperature=0.7,
                 should_stop=None, log=print) -> bool:
    """Synthesise ahead of playback so there is no gap between sentences.

    Returns False if `should_stop()` asked us to quit early.
    """
    work: queue.Queue = queue.Queue(maxsize=4)
    sentinel = None
    aborted = threading.Event()

    def produce():
        try:
            for text in chunks:
                if aborted.is_set():
                    break
                work.put(voice.say(text, lang=lang, speed=speed,
                                   temperature=temperature))
            work.put(sentinel)
        except Exception as exc:                    # surfaced by the consumer
            work.put(exc)

    thread = threading.Thread(target=produce, daemon=True)
    thread.start()

    while True:
        try:
            item = work.get(timeout=0.2)
        except queue.Empty:
            if should_stop and should_stop():
                aborted.set()
                return False
            continue
        if item is sentinel:
            return True
        if isinstance(item, Exception):
            log(f"[speak] synthesis failed: {item}")
            return False
        player.play(item)
        if should_stop and should_stop():
            aborted.set()
            return False


# --------------------------------------------------------------------------
# input
# --------------------------------------------------------------------------
_tk_root = None


def _tk():
    """One hidden Tk window for clipboard reads (fast, and no subprocess)."""
    global _tk_root
    if _tk_root is None:
        import tkinter
        _tk_root = tkinter.Tk()
        _tk_root.withdraw()
    return _tk_root


def clipboard_text() -> str:
    if sys.platform.startswith("win"):
        try:                                        # stdlib, no subprocess
            return _tk().clipboard_get()
        except Exception:
            pass
        try:
            import subprocess
            out = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "[Console]::OutputEncoding=[Text.Encoding]::UTF8; Get-Clipboard -Raw"],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=10)
            return out.stdout or ""
        except Exception:
            return ""
    for cmd in (["pbpaste"], ["xclip", "-selection", "clipboard", "-o"],
                ["xsel", "--clipboard", "--output"], ["wl-paste"]):
        try:
            import subprocess
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            if out.returncode == 0:
                return out.stdout
        except Exception:
            continue
    return ""


def read_input(args) -> str:
    if args.text:
        return " ".join(args.text)
    if args.file:
        with open(_expand(args.file), encoding="utf-8", errors="replace") as fh:
            return fh.read()
    if args.stdin or not sys.stdin.isatty():
        data = sys.stdin.read()
        if data.strip():
            return data
    return clipboard_text()


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------
def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        description="Read text aloud with your own trained XTTS voice (.pth).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="examples:\n"
               '  python speak.py "hello there"\n'
               "  python speak.py --file article.txt\n"
               "  python speak.py                 (clipboard)\n"
               "  python speak.py --watch         (speak whatever you copy)\n")
    p.add_argument("text", nargs="*", help="text to say")
    p.add_argument("--file", help="read text from this file")
    p.add_argument("--stdin", action="store_true", help="read text from stdin")
    p.add_argument("--watch", action="store_true",
                   help="keep running; speak the clipboard every time it changes")
    p.add_argument("--voice", help="folder with model.pth, or the .pth itself")
    p.add_argument("--out", help="save one wav here instead of playing")
    p.add_argument("--lang", default="en", help="language code (default en)")
    p.add_argument("--speed", type=float, default=1.0)
    p.add_argument("--temperature", type=float, default=0.7)
    p.add_argument("--device", default="auto", choices=["auto", "cuda", "cpu"])
    p.add_argument("--check", action="store_true",
                   help="load the model, report what it found, say nothing")
    p.add_argument("--raw", action="store_true", help="do not strip markdown")
    p.add_argument("--quiet", action="store_true")
    args = p.parse_args(argv)

    log = (lambda *a, **k: None) if args.quiet else \
          (lambda *a, **k: print(*a, **k, file=sys.stderr, flush=True))

    spec = find_voice(args.voice)
    check_voice(spec)
    if args.check:
        print(f"voice folder : {spec['dir']}")
        print(f"checkpoint   : {spec['checkpoint']} "
              f"({os.path.getsize(spec['checkpoint']) / 1e9:.2f} GB)")
        print(f"config       : {spec['config']}")
        print(f"vocab        : {spec['vocab']}")
        print(f"speaker ref  : {spec['speaker_ref']}")
    voice = Voice(spec, device=args.device, log=log)
    if args.check:
        langs = getattr(voice.model.config, "languages", None) or ["en"]
        print(f"device       : {voice.device}")
        print(f"languages    : {', '.join(langs) if isinstance(langs, list) else langs}")
        print("OK — the model loaded and the voice is ready. Now drop --check "
              "and give it text.")
        return 0
    player = Player(save_path=_expand(args.out) if args.out else None)

    def to_chunks(text: str) -> list[str]:
        if args.raw:
            text = text.replace("\r\n", "\n")
        return split_sentences(text)

    try:
        if args.watch:
            if not sys.platform.startswith("win"):
                log("[speak] --watch uses the clipboard; on this OS it may not work")
            log("[speak] watching the clipboard — copy text anywhere to hear it. "
                "Ctrl+C to stop.")
            last = clipboard_text().strip()
            if last:
                log("[speak] (speaking what is already on the clipboard)")
            while True:
                if last:
                    current = last
                    chunks = to_chunks(current)

                    def changed(snapshot=current) -> bool:
                        return clipboard_text().strip() != snapshot

                    speak_chunks(voice, chunks, player, lang=args.lang,
                                 speed=args.speed, temperature=args.temperature,
                                 should_stop=changed, log=log)
                    last = clipboard_text().strip()
                time.sleep(0.3)
                fresh = clipboard_text().strip()
                if fresh != last:
                    last = fresh
            # unreachable

        text = read_input(args)
        if not text or not text.strip():
            log("[speak] nothing to say — pass text, --file, or copy something first")
            return 2
        chunks = to_chunks(text)
        if not chunks:
            log("[speak] no speakable words in that text")
            return 2
        log(f"[speak] {len(chunks)} chunk(s)")
        speak_chunks(voice, chunks, player, lang=args.lang, speed=args.speed,
                     temperature=args.temperature, log=log)
        return 0
    except KeyboardInterrupt:
        print(file=sys.stderr)
        log("[speak] stopped")
        return 130
    finally:
        player.close()


if __name__ == "__main__":
    sys.exit(main())
