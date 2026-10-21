"""Inference with a FORGE-trained voice + voice packaging/export.

A voice is four files that must travel together:

    model.pth       the fine-tuned XTTS v2 weights (the .pth you trained)
    config.json     the XTTS v2 model config the weights were trained with
    vocab.json      the tokenizer vocabulary
    speaker_ref.wav a clean 6-15 s clip of the voice (speaker conditioning)

`--voice` can be a folder (with or without `voice.json`) or, if the other
three files sit next to it, the `.pth` itself.

CLI:
    python -m forge.synth --voice "%USERPROFILE%\\forge\\voices\\my-voice" ^
        --text "Hello world" --out out.wav

    python -m forge.synth --checkpoint "run\\training\\FORGE_XTTS-...\\model.pth" ^
        --speaker-ref "dataset\\wavs\\clip.wav" --text "Hello world" --out out.wav
"""
import argparse
import json
import os
import io
import shutil
import threading
import wave
import zipfile

import numpy as np
import soundfile as sf

# checkpoint path -> (model, spec, (gpt_cond_latent, speaker_embedding))
_model_cache = {}

SAMPLE_RATE = 24000
MIN_CHECKPOINT_BYTES = 1_000_000  # a real XTTS checkpoint is ~1.8 GB


def _resolve(base_dir, value, default_name):
    """Find a file: the recorded path if it still exists, else its sibling,
    else the conventional file name inside `base_dir`."""
    if value:
        v = os.path.expandvars(os.path.expanduser(str(value)))
        if os.path.isfile(v):
            return os.path.abspath(v)
        for cand in (os.path.join(base_dir, os.path.basename(v)),
                     os.path.join(base_dir, os.path.basename(v).lower())):
            if os.path.isfile(cand):
                return os.path.abspath(cand)
    cand = os.path.join(base_dir, default_name)
    return os.path.abspath(cand) if os.path.isfile(cand) else None


def _first_wav(base_dir):
    try:
        wavs = sorted(f for f in os.listdir(base_dir) if f.lower().endswith(".wav"))
    except OSError:
        return None
    return os.path.join(base_dir, wavs[0]) if wavs else None


def describe(voice=None, checkpoint=None, config=None, vocab=None,
             speaker_ref=None):
    """Work out where a voice's four files are, from a folder, a .pth, or
    explicit paths. Returns a dict; missing files are None."""
    base_dir, manifest = None, {}

    if voice:
        voice = os.path.expandvars(os.path.expanduser(str(voice).strip().strip('"')))
        if os.path.isfile(voice):
            base_dir = os.path.dirname(os.path.abspath(voice))
            checkpoint = checkpoint or voice
        elif os.path.isdir(voice):
            base_dir = os.path.abspath(voice)
            manifest_path = os.path.join(base_dir, "voice.json")
            if os.path.isfile(manifest_path):
                try:
                    with open(manifest_path, encoding="utf-8") as f:
                        manifest = json.load(f)
                except (OSError, ValueError):
                    manifest = {}
    elif checkpoint:
        base_dir = os.path.dirname(os.path.abspath(
            os.path.expandvars(os.path.expanduser(checkpoint))))

    if base_dir is None:
        raise FileNotFoundError(
            "No voice given. Pass --voice <folder or model.pth> "
            "(or --checkpoint <model.pth>).")

    spec = {
        "name": manifest.get("name") or os.path.basename(base_dir),
        "dir": base_dir,
        "checkpoint": _resolve(base_dir, checkpoint or manifest.get("checkpoint"),
                               "model.pth"),
        "config": _resolve(base_dir, config or manifest.get("config"),
                           "config.json"),
        "vocab": _resolve(base_dir, vocab or manifest.get("vocab"),
                          "vocab.json"),
        "speaker_ref": _resolve(base_dir, speaker_ref or manifest.get("speaker_ref"),
                                "speaker_ref.wav") or _first_wav(base_dir),
        "sample_rate": SAMPLE_RATE,
    }
    return spec


def _check(spec):
    """Fail early with a message that says what to do, not just what broke."""
    missing = [k for k in ("checkpoint", "config", "vocab", "speaker_ref")
               if not spec.get(k) or not os.path.isfile(spec[k])]
    if missing:
        have = sorted(os.listdir(spec["dir"])) if os.path.isdir(spec["dir"]) else []
        raise FileNotFoundError(
            "Voice package is incomplete — missing: " + ", ".join(missing) + "\n"
            f"Folder: {spec['dir']}\n"
            f"Contains: {', '.join(have) if have else '(nothing)'}\n"
            "A voice needs model.pth + config.json + vocab.json + a reference "
            ".wav in one folder. Point --checkpoint/--config/--vocab/"
            "--speaker-ref at them if they live apart.")
    size = os.path.getsize(spec["checkpoint"])
    if size < MIN_CHECKPOINT_BYTES:
        raise RuntimeError(
            f"{spec['checkpoint']} is only {size} bytes — that is not trained "
            "weights.\nIf you copied this folder from a Git checkout, the real "
            "checkpoint was replaced by a placeholder. Use the model.pth from "
            "your own machine (it should be ~1.8 GB).")


def _device(device="auto"):
    import torch
    if device == "auto":
        device = "cuda" if torch.cuda.is_available() else "cpu"
    if device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("--device cuda requested, but CUDA is not available. "
                           "Install a CUDA build of torch, or use --device cpu.")
    return device


class XttsVoice:
    """One loaded voice, reusable across many lines of text.

    Loading XTTS costs ~10-20 s and ~2 GB of VRAM; synthesising a sentence
    costs ~1 s. Anything that speaks more than once (the browser server, a
    batch of scripts) should hold one of these rather than call
    `synthesize()` per line.

    Not thread-safe: XTTS inference is not. Wrap it in `TTSEngine` (below)
    if you need concurrency — that is what the HTTP server does.
    """

    def __init__(self, source=None, checkpoint=None, config=None, vocab=None,
                 speaker_ref=None, device="auto", log=print):
        from TTS.tts.configs.xtts_config import XttsConfig
        from TTS.tts.models.xtts import Xtts

        self.spec = describe(source, checkpoint, config, vocab, speaker_ref)
        _check(self.spec)
        self.device = _device(device)

        log(f"[forge] loading {self.spec['checkpoint']} on {self.device} ...")
        cfg = XttsConfig()
        cfg.load_json(self.spec["config"])
        self.config = cfg
        self.model = Xtts.init_from_config(cfg)
        self.model.load_checkpoint(cfg, checkpoint_path=self.spec["checkpoint"],
                                   vocab_path=self.spec["vocab"], use_deepspeed=False)
        self.model.to(self.device)
        self.model.eval()

        ref = self.spec["speaker_ref"]
        (self.gpt_cond_latent,
         self.speaker_embedding) = self.model.get_conditioning_latents(audio_path=[ref])
        self.languages = self._languages()
        log(f"[forge] voice ready ({self.spec['name']}), "
            f"{len(self.languages)} languages")

    def _languages(self):
        langs = getattr(self.config, "languages", None) or ["en"]
        if isinstance(langs, str):
            langs = [langs]
        return list(langs)

    def wav(self, text, lang="en", temperature=0.7, speed=1.0, top_p=0.85,
            top_k=50, repetition_penalty=10.0, split_sentences=True):
        """Text -> float32 numpy waveform at 24 kHz."""
        out = self.model.inference(
            text, lang, self.gpt_cond_latent, self.speaker_embedding,
            temperature=float(temperature),
            speed=float(speed),
            top_p=float(top_p),
            top_k=int(top_k),
            repetition_penalty=float(repetition_penalty),
            enable_text_splitting=bool(split_sentences),
        )
        wav = out["wav"]
        if hasattr(wav, "detach"):          # torch tensor
            wav = wav.detach().cpu().numpy()
        return np.asarray(wav, dtype=np.float32).reshape(-1)

    def pcm16(self, text, **kw):
        """Text -> 16-bit little-endian PCM bytes (what browsers play)."""
        wav = np.clip(self.wav(text, **kw), -1.0, 1.0)
        return (wav * 32767.0).astype("<i2").tobytes()


class TTSEngine:
    """A lazily-loaded voice + a lock, safe to share between threads.

    The first `speak()` triggers the load, so an HTTP server can start
    instantly and only pay for the model when the first sentence arrives.
    """

    def __init__(self, voice=None, device="auto", log=print):
        self.source = voice
        self.device = device
        self.log = log
        self._voice = None
        self._lock = threading.Lock()

    @property
    def loaded(self):
        return self._voice is not None

    def voice(self):
        if self._voice is None:
            self._voice = XttsVoice(self.source, device=self.device, log=self.log)
        return self._voice

    def set_source(self, source):
        """Point the engine at another voice; it loads on the next speak()."""
        with self._lock:
            self.source = source
            self._voice = None

    def speak(self, text, **kw):
        """Text -> a complete WAV file (bytes), ready to POST to a browser."""
        with self._lock:
            return wav_bytes(self.voice().pcm16(text, **kw))

    def describe(self):
        v = self._voice
        if v is None:
            return {"loaded": False, "name": None,
                    "languages": [], "device": None}
        return {"loaded": True, "name": v.spec["name"],
                "dir": v.spec["dir"], "device": v.device,
                "languages": v.languages, "sample_rate": SAMPLE_RATE}


def wav_bytes(pcm, sample_rate=SAMPLE_RATE, channels=1):
    """Raw 16-bit PCM -> a complete RIFF/WAVE file.

    Browsers will not decode bare PCM even if you say `audio/wav`; they need
    the 44-byte header. `wave` writes it without touching disk.
    """
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(int(sample_rate))
        w.writeframes(pcm)
    return buf.getvalue()


def load_voice(voice=None, checkpoint=None, config=None, vocab=None,
               speaker_ref=None, device="auto"):
    """Load a fine-tuned voice. `voice` may be a package folder or a .pth.

    Returns (model, spec, (gpt_cond_latent, speaker_embedding)).
    """
    key = (voice, checkpoint, config, vocab, speaker_ref, device)
    if key in _model_cache:
        return _model_cache[key]
    v = XttsVoice(voice, checkpoint, config, vocab, speaker_ref, device)
    _model_cache[key] = (v.model, v.spec, (v.gpt_cond_latent, v.speaker_embedding))
    return _model_cache[key]


def synthesize(text, voice=None, out_wav="forge_out.wav", lang="en",
               temperature=0.7, speed=1.0, device="auto",
               checkpoint=None, config=None, vocab=None, speaker_ref=None,
               voice_obj=None):
    """Speak `text` in the trained voice; writes a 24 kHz wav and returns its path."""
    v = voice_obj or XttsVoice(voice, checkpoint, config, vocab, speaker_ref, device)
    wav = v.wav(text, lang, temperature=temperature, speed=speed)
    out_dir = os.path.dirname(os.path.abspath(out_wav))
    os.makedirs(out_dir, exist_ok=True)
    sf.write(out_wav, wav, SAMPLE_RATE)
    return out_wav


def export_voice(name, checkpoint, config, vocab, speaker_ref, voices_root):
    """Package a trained voice into a portable folder + zip.

    The manifest stores *relative* file names, so the zip works on any
    machine and in any folder.
    """
    for label, path in (("checkpoint", checkpoint), ("config", config),
                        ("vocab", vocab), ("speaker_ref", speaker_ref)):
        if not path or not os.path.isfile(path):
            raise FileNotFoundError(f"export: {label} not found: {path}")

    voice_dir = os.path.join(voices_root, name)
    os.makedirs(voice_dir, exist_ok=True)
    for src, dst in ((checkpoint, "model.pth"), (config, "config.json"),
                     (vocab, "vocab.json"), (speaker_ref, "speaker_ref.wav")):
        if os.path.abspath(src) != os.path.abspath(os.path.join(voice_dir, dst)):
            shutil.copy(src, os.path.join(voice_dir, dst))

    manifest = {
        "name": name,
        "checkpoint": "model.pth",
        "config": "config.json",
        "vocab": "vocab.json",
        "speaker_ref": "speaker_ref.wav",
        "sample_rate": SAMPLE_RATE,
    }
    with open(os.path.join(voice_dir, "voice.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    zip_path = voice_dir + ".zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for root, _, files in os.walk(voice_dir):
            for fn in files:
                full = os.path.join(root, fn)
                z.write(full, os.path.relpath(full, os.path.dirname(voice_dir)))
    return voice_dir, zip_path


def main():
    p = argparse.ArgumentParser(description="Speak with a FORGE voice")
    p.add_argument("--voice", help="Voice package dir, or a model.pth")
    p.add_argument("--checkpoint", help="model.pth / best_model.pth (if not using --voice)")
    p.add_argument("--config", help="config.json (default: next to the checkpoint)")
    p.add_argument("--vocab", help="vocab.json (default: next to the checkpoint)")
    p.add_argument("--speaker-ref", dest="speaker_ref",
                   help="6-15 s wav of the voice (default: speaker_ref.wav next to the checkpoint)")
    p.add_argument("--text", help="Text to speak")
    p.add_argument("--text-file", help="Read the text from a UTF-8 file instead")
    p.add_argument("--out", default="forge_out.wav")
    p.add_argument("--lang", default="en")
    p.add_argument("--device", default="auto", choices=["auto", "cuda", "cpu"])
    p.add_argument("--temperature", type=float, default=0.7)
    p.add_argument("--speed", type=float, default=1.0)
    args = p.parse_args()

    text = args.text
    if args.text_file:
        with open(args.text_file, encoding="utf-8") as f:
            text = f.read().strip()
    if not text:
        p.error("give --text \"...\" or --text-file script.txt")

    synthesize(text, args.voice, args.out, args.lang,
               temperature=args.temperature, speed=args.speed,
               device=args.device,
               checkpoint=args.checkpoint, config=args.config,
               vocab=args.vocab, speaker_ref=args.speaker_ref)
    print(f"wrote {os.path.abspath(args.out)}")


if __name__ == "__main__":
    main()
