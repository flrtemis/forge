"""Dataset building: upload voice audio -> transcribed training clips + metadata CSVs.

Adapted from the Coqui TTS XTTS fine-tuning demo
(TTS/demos/xtts_ft_demo/utils/formatter.py, Mozilla Public License 2.0),
with Windows-safe paths, 22050 Hz mono normalization, chunked long-file
handling, and quality gates added.
"""
import gc
import math
import os

import pandas
import torch
import torchaudio
from faster_whisper import WhisperModel
from tqdm import tqdm

try:
    from TTS.tts.layers.xtts.tokenizer import multilingual_cleaners
except Exception:  # tokenizer import is optional; fall back to raw text
    multilingual_cleaners = None

AUDIO_TYPES = (".wav", ".mp3", ".flac", ".m4a", ".ogg")
TARGET_SR = 22050
CHUNK_SECONDS = 1200  # process very long files in 20-minute windows to bound RAM
MAX_EVAL_CLIPS = 400  # don't waste hours evaluating on a giant eval set
# Quality gates: with hours of audio, filtering junk matters more than keeping it.
MIN_WORDS_PER_CLIP = 3       # skip fragments like "yeah." / "um."
MAX_NO_SPEECH_PROB = 0.5     # whisper's own "this is probably not speech" score
MIN_RMS_DB = -45.0           # skip near-silent clips (dBFS)


def collect_audio(inputs):
    """Gather audio files from uploaded file paths and/or a folder path."""
    found = []
    for inp in inputs:
        if not inp:
            continue
        p = inp.name if hasattr(inp, "name") else str(inp)
        if os.path.isdir(p):
            for root, _, files in os.walk(p):
                for fn in files:
                    if fn.lower().endswith(AUDIO_TYPES):
                        found.append(os.path.join(root, fn))
        elif os.path.isfile(p) and p.lower().endswith(AUDIO_TYPES):
            found.append(p)
    # de-dupe, stable order
    return sorted(set(found))


def _load_window(path, offset_s, window_s):
    """Load one window of a (possibly huge) audio file, resampled to 22050 mono."""
    # torchaudio.info() removed in 2.9+; use soundfile instead.
    # Also avoiding torchaudio.load() which now requires torchcodec/FFmpeg.
    import soundfile as sf
    _sinfo = sf.info(str(path))
    sr = _sinfo.samplerate
    total = _sinfo.frames
    start_frame = int(offset_s * sr)
    num_frames = int(window_s * sr)
    if start_frame >= total:
        return None, None
    num_frames = min(num_frames, total - start_frame)
    # Load via soundfile (no torchcodec dependency)
    wav_np, _ = sf.read(str(path), start=start_frame, frames=num_frames, dtype='float32', always_2d=True)
    wav = torch.from_numpy(wav_np.T)  # (channels, frames)
    if wav.size(0) > 1:
        wav = torch.mean(wav, dim=0, keepdim=True)
    if sr != TARGET_SR:
        wav = torchaudio.functional.resample(wav, sr, TARGET_SR)
    return wav.squeeze(), TARGET_SR


def _clean_text(text, lang):
    if multilingual_cleaners is not None:
        try:
            return multilingual_cleaners(text, lang)
        except Exception:
            return text
    return text


def build_dataset(audio_files, target_language="en", out_path=None,
                  buffer=0.2, eval_percentage=0.15, speaker_name="me",
                  whisper_model="large-v2", progress_cb=None):
    """Transcribe + segment uploaded audio into XTTS training clips.

    Returns dict with train_csv, eval_csv, num_clips, total_minutes, etc.
    """
    os.makedirs(out_path, exist_ok=True)

    # Force CPU for Whisper: torch.cuda.is_available() is True but faster-whisper
    # needs cublas64_12.dll which is missing on this system. CPU/int8 works fine.
    device = "cpu"
    compute = "int8"
    print(f"[forge] loading whisper {whisper_model} on {device} (forced: cublas missing for CUDA)")
    asr_model = WhisperModel(whisper_model, device=device, compute_type=compute)

    metadata = {"audio_file": [], "text": [], "speaker_name": []}
    audio_total_size = 0.0
    skipped = {"no_speech": 0, "too_quiet": 0, "too_short_text": 0, "too_short_audio": 0}

    files = collect_audio(audio_files if isinstance(audio_files, (list, tuple)) else [audio_files])
    if not files:
        raise ValueError("No audio files found in the upload / folder.")
    it = tqdm(files, desc="transcribing") if progress_cb is None else files

    clip_idx = 0
    for fi, audio_path in enumerate(it):
        if progress_cb:
            progress_cb(fi / max(len(files), 1),
                        desc=f"transcribing {os.path.basename(audio_path)} ({fi+1}/{len(files)})")
        # torchaudio.info() was removed in torchaudio 2.9+; use soundfile (bundled dep) instead
        try:
            import soundfile as sf
            _sinfo = sf.info(str(audio_path))
            duration_s = _sinfo.frames / _sinfo.samplerate
        except ImportError:
            # Fallback: load audio to get duration (slower but always works)
            _wav, _sr = torchaudio.load(str(audio_path))
            duration_s = _wav.shape[-1] / _sr
        n_windows = max(1, int((duration_s + CHUNK_SECONDS - 1) // CHUNK_SECONDS))

        # Transcribe once per file; windows below just slice the word list.
        segments, _ = asr_model.transcribe(str(audio_path), word_timestamps=True,
                                           language=target_language)
        all_words = []
        word_nsp = {}  # id(word) -> whisper's "probably not speech" score
        for seg in segments:
            nsp = getattr(seg, "no_speech_prob", 0.0)
            for wd in seg.words:
                word_nsp[id(wd)] = nsp
                all_words.append(wd)

        for w in range(n_windows):
            wav, sr = _load_window(audio_path, w * CHUNK_SECONDS, CHUNK_SECONDS)
            if wav is None or wav.numel() == 0:
                continue
            audio_total_size += wav.size(-1) / sr
            base_offset = w * CHUNK_SECONDS

            words_list = []
            for wd in all_words:
                if base_offset <= wd.start < base_offset + CHUNK_SECONDS:
                    wd.start -= base_offset
                    wd.end -= base_offset
                    words_list.append(wd)

            sentence, sentence_start, first_word = "", None, True
            sent_words = []
            for word_idx, word in enumerate(words_list):
                if first_word:
                    sentence_start = word.start
                    if word_idx == 0:
                        sentence_start = max(sentence_start - buffer, 0)
                    else:
                        prev_end = words_list[word_idx - 1].end
                        sentence_start = max(sentence_start - buffer,
                                            (prev_end + sentence_start) / 2)
                    sentence = word.word
                    sent_words = [word]
                    first_word = False
                else:
                    sentence += word.word
                    sent_words.append(word)

                if word.word and word.word[-1] in ("!", ".", "?"):
                    sentence = sentence[1:] if sentence.startswith(" ") else sentence
                    sentence = _clean_text(sentence.strip(), target_language)

                    base, _ = os.path.splitext(os.path.basename(audio_path))
                    rel = os.path.join("wavs", f"{base}_{str(clip_idx).zfill(8)}.wav").replace(os.sep, "/")
                    abs_path = os.path.join(out_path, "wavs", f"{base}_{str(clip_idx).zfill(8)}.wav")
                    os.makedirs(os.path.dirname(abs_path), exist_ok=True)

                    if word_idx + 1 < len(words_list):
                        next_start = words_list[word_idx + 1].start
                    else:
                        next_start = (wav.shape[0] - 1) / sr
                    word_end = min((word.end + next_start) / 2, word.end + buffer)

                    clip = wav[int(sr * sentence_start):int(sr * word_end)].unsqueeze(0)
                    clip_idx += 1
                    first_word = True

                    # ---- quality gates: 30h of audio only helps if it's clean ----
                    if clip.size(-1) < sr / 3:
                        skipped["too_short_audio"] += 1
                        continue
                    if not sentence or len(sentence.split()) < MIN_WORDS_PER_CLIP:
                        skipped["too_short_text"] += 1
                        continue
                    rms_db = 20 * math.log10(clip.pow(2).mean().sqrt().item() + 1e-10)
                    if rms_db < MIN_RMS_DB:
                        skipped["too_quiet"] += 1
                        continue
                    worst_nsp = max((word_nsp.get(id(wd), 0.0) for wd in sent_words),
                                    default=0.0)
                    if worst_nsp > MAX_NO_SPEECH_PROB:
                        skipped["no_speech"] += 1
                        continue
                    # ---- gates passed: keep the clip ----

                    # Save via soundfile (avoiding torchcodec dependency)
                    import soundfile as _sf
                    _clip_np = clip.squeeze().cpu().numpy()
                    _sf.write(abs_path, _clip_np, sr)
                    metadata["audio_file"].append(rel)
                    metadata["text"].append(sentence)
                    metadata["speaker_name"].append(speaker_name)

    df = pandas.DataFrame(metadata)
    if len(df) == 0:
        raise ValueError(
            "No usable speech clips survived quality filtering. "
            "Check that your recordings contain clear, audible speech — "
            f"filtered out: {skipped}.")
    df = df.sample(frac=1, random_state=42)
    n_val = min(max(1, int(len(df) * eval_percentage)), MAX_EVAL_CLIPS)
    df_eval, df_train = df[:n_val], df[n_val:]
    df_train = df_train.sort_values("audio_file")
    df_eval = df_eval.sort_values("audio_file")

    train_csv = os.path.join(out_path, "metadata_train.csv")
    eval_csv = os.path.join(out_path, "metadata_eval.csv")
    df_train.to_csv(train_csv, sep="|", index=False)
    df_eval.to_csv(eval_csv, sep="|", index=False)

    del asr_model
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

    return {
        "train_csv": train_csv,
        "eval_csv": eval_csv,
        "num_clips": len(df),
        "num_train": len(df_train),
        "num_eval": len(df_eval),
        "total_minutes": round(audio_total_size / 60, 1),
        "skipped": skipped,
        "num_files": len(files),
    }
