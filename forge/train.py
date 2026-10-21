"""XTTS v2 fine-tuning on the user's dataset.

Adapted from the Coqui TTS XTTS fine-tuning demo
(TTS/demos/xtts_ft_demo/utils/gpt_train.py, Mozilla Public License 2.0),
made Windows-safe (shutil instead of `cp`) with VRAM-friendly defaults.
"""
import gc
import json
import os
import shutil
import sys
import threading
from datetime import datetime

from trainer import Trainer, TrainerArgs

from TTS.config.shared_configs import BaseDatasetConfig
from TTS.tts.datasets import load_tts_samples
from TTS.tts.layers.xtts.trainer.gpt_trainer import (
    GPTArgs, GPTTrainer, GPTTrainerConfig,
)
from TTS.tts.models.xtts import XttsAudioConfig
from TTS.utils.manage import ModelManager


def _ram_gb():
    """System RAM in use, no new dependencies (Windows API via ctypes)."""
    try:
        import ctypes

        class MS(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong),
                        ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong),
                        ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong),
                        ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong),
                        ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

        ms = MS()
        ms.dwLength = ctypes.sizeof(MS)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(ms))
        total = ms.ullTotalPhys / 1e9
        used = (ms.ullTotalPhys - ms.ullAvailPhys) / 1e9
        return f"{used:.1f}/{total:.1f} GB ({ms.dwMemoryLoad}%)"
    except Exception:
        return "n/a"


GUARD_EXIT_CODE = 42  # run-forge.bat recognizes this: guardrail stop, not a crash


def _ram_percent():
    """System RAM in use as int percent, or None if unreadable."""
    try:
        import ctypes

        class MS(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong),
                        ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong),
                        ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong),
                        ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong),
                        ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

        ms = MS()
        ms.dwLength = ctypes.sizeof(MS)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(ms))
        return int(ms.dwMemoryLoad)
    except Exception:
        return None


class _ResourceGuard(threading.Thread):
    """Turtle-mode autonomous guard. Handles itself — no human needed.

    Every `interval` seconds it checks system RAM:
    - over 85%: warn, garbage-collect, clear CUDA cache (gentle).
    - over 92% twice in a row: write the status file, log loudly,
      then os._exit(42). run-forge.bat sees 42 and explains.
      Coqui already saved a checkpoint, so resume_from recovers.
    With loader workers at 0 this should never fire — it's the airbag.
    """

    def __init__(self, log_fn, status_path, interval=30):
        super().__init__(daemon=True)
        self.log_fn = log_fn
        self.status_path = status_path
        self.interval = interval
        self._stop_event = threading.Event()
        self._hot = 0

    def _vram(self):
        try:
            import torch
            if torch.cuda.is_available():
                free, total = torch.cuda.mem_get_info()
                return f"{(total - free) / 1e9:.1f}/{total / 1e9:.1f} GB"
        except Exception:
            pass
        return "n/a"

    def _tidy(self):
        gc.collect()
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass

    def _status(self, outcome, reason, ram):
        try:
            with open(self.status_path, "w", encoding="utf-8") as f:
                json.dump({"outcome": outcome, "reason": reason,
                           "ram": ram,
                           "time": datetime.now().isoformat(timespec="seconds")},
                          f, indent=1)
        except Exception:
            pass

    def run(self):
        while not self._stop_event.wait(self.interval):
            try:
                pct = _ram_percent()
                if pct is None:
                    continue
                if pct > 92:
                    self._hot += 1
                    self.log_fn(f"[forge] GUARD critical: RAM {pct}% "
                                f"(strike {self._hot}/2) — tidying")
                    self._tidy()
                    if self._hot >= 2:
                        ram = _ram_gb()
                        self.log_fn(
                            f"[forge] GUARD STOP: RAM {ram} — shutting down "
                            f"to protect your PC. Checkpoint is safe, resume "
                            f"to continue. See {self.status_path}")
                        self._status("guard_stop",
                                     "RAM exceeded 92% twice in a row", ram)
                        try:
                            sys.stdout.flush()
                        except Exception:
                            pass
                        os._exit(GUARD_EXIT_CODE)
                else:
                    if self._hot:
                        self.log_fn(f"[forge] GUARD: RAM back to {pct}%, "
                                    f"strikes reset")
                    self._hot = 0
                    if pct > 85:
                        self.log_fn(f"[forge] GUARD warning: RAM {pct}% — "
                                    f"tidying")
                        self._tidy()
                    else:
                        self.log_fn(f"[forge] resources — RAM: {_ram_gb()} | "
                                    f"VRAM: {self._vram()}")
            except Exception:
                pass

    def stop(self):
        self._stop_event.set()


def train_voice(language, num_epochs, batch_size, grad_accum, train_csv, eval_csv,
                output_path, max_audio_length=255995, log_fn=print, resume_from=None):
    """resume_from: trainer checkpoint dir to continue from (roam failover)."""
    run_name = "FORGE_XTTS"
    out_path = os.path.join(output_path, "run", "training")
    os.makedirs(out_path, exist_ok=True)

    config_dataset = BaseDatasetConfig(
        formatter="coqui",
        dataset_name="forge_dataset",
        path=os.path.dirname(train_csv),
        meta_file_train=train_csv,
        meta_file_val=eval_csv,
        language=language,
    )

    ckpt_dir = os.path.join(out_path, "XTTS_v2.0_original_model_files")
    os.makedirs(ckpt_dir, exist_ok=True)

    links = {
        "dvae.pth": "https://coqui.gateway.scarf.sh/hf-coqui/XTTS-v2/main/dvae.pth",
        "mel_stats.pth": "https://coqui.gateway.scarf.sh/hf-coqui/XTTS-v2/main/mel_stats.pth",
        "vocab.json": "https://coqui.gateway.scarf.sh/hf-coqui/XTTS-v2/main/vocab.json",
        "model.pth": "https://coqui.gateway.scarf.sh/hf-coqui/XTTS-v2/main/model.pth",
        "config.json": "https://coqui.gateway.scarf.sh/hf-coqui/XTTS-v2/main/config.json",
    }
    missing = [name for name in links if not os.path.isfile(os.path.join(ckpt_dir, name))]
    if missing:
        log_fn("[forge] downloading XTTS v2 base files (one-time, ~2GB)...")
        ModelManager._download_model_files([links[n] for n in missing], ckpt_dir, progress_bar=True)

    dvae_ckpt = os.path.join(ckpt_dir, "dvae.pth")
    mel_norm = os.path.join(ckpt_dir, "mel_stats.pth")
    tokenizer_file = os.path.join(ckpt_dir, "vocab.json")
    xtts_checkpoint = os.path.join(ckpt_dir, "model.pth")
    xtts_config_file = os.path.join(ckpt_dir, "config.json")

    model_args = GPTArgs(
        max_conditioning_length=132300,   # 6 s
        min_conditioning_length=66150,    # 3 s
        max_wav_length=max_audio_length,  # ~11.6 s at 22050 Hz
        max_text_length=200,
        mel_norm_file=mel_norm,
        dvae_checkpoint=dvae_ckpt,
        xtts_checkpoint=xtts_checkpoint,
        tokenizer_file=tokenizer_file,
        gpt_num_audio_tokens=1026,
        gpt_start_audio_token=1024,
        gpt_stop_audio_token=1025,
        gpt_use_masking_gt_prompt_approach=True,
        gpt_use_perceiver_resampler=True,
    )
    audio_config = XttsAudioConfig(sample_rate=22050, dvae_sample_rate=22050,
                                   output_sample_rate=24000)
    config = GPTTrainerConfig(
        epochs=num_epochs,
        output_path=out_path,
        model_args=model_args,
        run_name=run_name,
        project_name="forge",
        run_description="FORGE voice fine-tuning",
        dashboard_logger="tensorboard",
        audio=audio_config,
        batch_size=batch_size,
        batch_group_size=48,
        eval_batch_size=batch_size,
        num_loader_workers=0,  # was 4: each worker = a full dataset copy in RAM
                                       # (the 4 python.exe at 30% RAM each). 0 = main process loads alone.
        eval_split_max_size=256,
        print_step=50,
        plot_step=100,
        log_model_step=100,
        save_step=1000,
        save_n_checkpoints=1,
        save_checkpoints=True,
        print_eval=False,
        optimizer="AdamW",
        optimizer_wd_only_on_weights=True,
        optimizer_params={"betas": [0.9, 0.96], "eps": 1e-8, "weight_decay": 1e-2},
        lr=5e-06,
        lr_scheduler="MultiStepLR",
        lr_scheduler_params={"milestones": [50000 * 18, 150000 * 18, 300000 * 18],
                             "gamma": 0.5, "last_epoch": -1},
        test_sentences=[],
    )

    log_fn("[forge] initializing model...")
    model = GPTTrainer.init_from_config(config)
    train_samples, eval_samples = load_tts_samples(
        [config_dataset], eval_split=True,
        eval_split_max_size=config.eval_split_max_size,
        eval_split_size=config.eval_split_size)
    log_fn(f"[forge] {len(train_samples)} train / {len(eval_samples)} eval samples.")
    log_fn(f"[forge] RAM-saver: loader workers=0 (killed the 4 python.exe at 30% RAM each)")
    log_fn(f"[forge] system RAM at train start: {_ram_gb()}")

    # ---- governor, part 1: pre-flight gate. Turtle refuses to sprint ----
    ram_start = _ram_percent()
    if ram_start is not None and ram_start > 90:
        msg = (f"[forge] REFUSING to start: system RAM already at {ram_start}% — "
               f"free up memory or reboot, then retry. {_ram_gb()}")
        log_fn(msg)
        raise RuntimeError(msg)

    log_fn("[forge] training...")

    trainer = Trainer(
        TrainerArgs(restore_path=resume_from, skip_train_epoch=False,
                    start_with_eval=False, grad_accum_steps=grad_accum),
        config, output_path=out_path, model=model,
        train_samples=train_samples, eval_samples=eval_samples)

    # ---- governor, part 2: the autonomous guard. No human needed. ----
    guard = _ResourceGuard(log_fn, os.path.join(output_path, "forge_guard.json"),
                           interval=30)
    log_fn("[forge] governor on — autonomous RAM guard, checks every 30s")
    guard.start()
    try:
        trainer.fit()
    finally:
        guard.stop()

    # longest training clip becomes the speaker reference for inference
    lens = [len(s["text"].split()) for s in train_samples]
    speaker_ref = train_samples[lens.index(max(lens))]["audio_file"]
    exp_path = trainer.output_path

    # keep config + vocab next to the checkpoint (shutil: Windows-safe)
    shutil.copy(xtts_config_file, exp_path)
    shutil.copy(tokenizer_file, exp_path)

    del model, trainer, train_samples, eval_samples
    gc.collect()

    best = os.path.join(exp_path, "best_model.pth")
    return {
        "config": os.path.join(exp_path, "config.json"),
        "vocab": os.path.join(exp_path, "vocab.json"),
        "checkpoint": best if os.path.isfile(best) else exp_path,
        "exp_path": exp_path,
        "speaker_ref": speaker_ref,
    }
