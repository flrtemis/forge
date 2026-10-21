"""FORGE package."""

# --- audio-compat shim -------------------------------------------------------
# torchaudio>=2.9 routes torchaudio.load()/save() through torchcodec, which
# needs FFmpeg shared DLLs that this venv's torchcodec install is missing ->
# every WAV load/save crashes with "Could not load libtorchcodec".
# FORGE only ever feeds plain WAV files (22050 Hz mono, written by
# forge/dataset.py) to the trainer/synthesizer, and `soundfile` (already a
# dependency) handles those natively with no FFmpeg involved. So route .wav
# loads AND saves through soundfile; everything else stays on the original
# torchaudio functions. Contracts are identical:
#   load  -> (float32 tensor, sample_rate), shape (channels, samples)
#   save  -> writes (channels, samples) tensor to uri at sample_rate
try:
    import soundfile as _sf
    import torch as _torch
    import torchaudio as _ta

    if not getattr(_ta, "_forge_audio_patched", False):
        _orig_ta_load = _ta.load
        _orig_ta_save = _ta.save

        def _forge_audio_load(uri, *args, **kwargs):
            if str(uri).lower().endswith(".wav"):
                data, sr = _sf.read(str(uri), dtype="float32", always_2d=True)
                # soundfile -> (samples, channels); torchaudio -> (channels, samples)
                return _torch.from_numpy(data.T.copy()), sr
            return _orig_ta_load(uri, *args, **kwargs)

        def _forge_audio_save(uri, src, sample_rate, *args, **kwargs):
            if str(uri).lower().endswith(".wav"):
                arr = src.detach().cpu().numpy() if hasattr(src, "detach") else src
                # torchaudio -> (channels, samples); soundfile -> (samples, channels)
                _sf.write(str(uri), arr.T, sample_rate)
                return
            return _orig_ta_save(uri, src, sample_rate, *args, **kwargs)

        _ta.load = _forge_audio_load
        _ta.save = _forge_audio_save
        _ta._forge_audio_patched = True
except Exception:
    pass  # audio stack not importable in this context; leave as-is
