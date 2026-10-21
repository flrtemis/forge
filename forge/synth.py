"""Inference with a FORGE-trained voice + voice packaging/export.

Also usable as a CLI so the voice can be used *anywhere*:
    python -m forge.synth --voice ~/forge/voices/my-voice --text "Hello world" --out out.wav
"""
import argparse
import json
import os
import shutil
import tempfile
import zipfile

import torch
import torchaudio

_model_cache = {}


def load_voice(voice_dir):
    """Load a fine-tuned voice package. Returns the XTTS model."""
    from TTS.tts.configs.xtts_config import XttsConfig
    from TTS.tts.models.xtts import Xtts

    if voice_dir in _model_cache:
        return _model_cache[voice_dir]
    with open(os.path.join(voice_dir, "voice.json")) as f:
        manifest = json.load(f)
    config = XttsConfig()
    config.load_json(manifest["config"])
    model = Xtts.init_from_config(config)
    model.load_checkpoint(config, checkpoint_path=manifest["checkpoint"],
                          vocab_path=manifest["vocab"], use_deepspeed=False)
    if torch.cuda.is_available():
        model.cuda()
    _model_cache[voice_dir] = (model, manifest)
    return model, manifest


def synthesize(text, voice_dir, out_wav, lang="en", temperature=0.7):
    model, manifest = load_voice(voice_dir)
    ref = manifest["speaker_ref"]
    if not os.path.isabs(ref):
        ref = os.path.join(voice_dir, ref)
    gpt_cond_latent, speaker_embedding = model.get_conditioning_latents(audio_path=[ref])
    out = model.inference(text, lang, gpt_cond_latent, speaker_embedding,
                          temperature=temperature)
    torchaudio.save(out_wav, torch.tensor(out["wav"]).unsqueeze(0), 24000)
    return out_wav


def export_voice(name, checkpoint, config, vocab, speaker_ref, voices_root):
    """Package a trained voice into a portable folder + zip."""
    voice_dir = os.path.join(voices_root, name)
    os.makedirs(voice_dir, exist_ok=True)
    for src, dst in ((checkpoint, "model.pth"), (config, "config.json"),
                     (vocab, "vocab.json")):
        shutil.copy(src, os.path.join(voice_dir, dst))
    ref_dst = os.path.join(voice_dir, "speaker_ref.wav")
    shutil.copy(speaker_ref, ref_dst)
    manifest = {
        "name": name,
        "checkpoint": os.path.join(voice_dir, "model.pth"),
        "config": os.path.join(voice_dir, "config.json"),
        "vocab": os.path.join(voice_dir, "vocab.json"),
        "speaker_ref": ref_dst,
        "sample_rate": 24000,
    }
    with open(os.path.join(voice_dir, "voice.json"), "w") as f:
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
    p.add_argument("--voice", required=True, help="Voice package dir (contains voice.json)")
    p.add_argument("--text", required=True)
    p.add_argument("--out", default="forge_out.wav")
    p.add_argument("--lang", default="en")
    args = p.parse_args()
    synthesize(args.text, args.voice, args.out, args.lang)
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
