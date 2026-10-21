"""Roam providers: each knows how to run a training job *somewhere*.

A provider implements: is_available, prepare, start, poll, fetch, stop.
The orchestrator treats them interchangeably — that's what lets the
backend roam while the frontend never changes.
"""
import json
import os
import shutil
import subprocess
import threading
import time

from .job import RoamJob


# ---------------------------------------------------------------- base
class BaseProvider:
    name = "base"
    poll_interval = 10  # seconds between health checks

    def is_available(self):
        """(bool, reason) — can this provider run right now?"""
        return False, "not implemented"

    def prepare(self, job, log):
        """Stage dataset + code bundle. Idempotent."""

    def start(self, job, log):
        """Launch training. Returns a handle for poll/fetch/stop."""

    def poll(self, job, handle, log):
        """'running' | 'done' | 'failed'"""

    def fetch(self, job, handle, log):
        """Pull checkpoints/outputs back into job.ckpt_dir."""

    def stop(self, job, handle, log):
        """Best-effort stop."""


def _sh(cmd, log, cwd=None, timeout=None):
    log(f"$ {' '.join(cmd)}")
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    if p.stdout:
        log(p.stdout[-4000:])
    if p.returncode != 0 and p.stderr:
        log(p.stderr[-4000:])
    return p


# ---------------------------------------------------------------- local GPU
class LocalProvider(BaseProvider):
    name = "local"
    poll_interval = 10

    def is_available(self):
        try:
            import torch
            if torch.cuda.is_available():
                return True, f"cuda: {torch.cuda.get_device_name(0)}"
            return False, "torch has no CUDA GPU"
        except Exception as e:
            return False, f"torch unavailable: {e}"

    def prepare(self, job, log):
        os.makedirs(job["ckpt_dir"], exist_ok=True)
        log(f"[{self.name}] workdir ready at {job['ckpt_dir']}")

    def start(self, job, log):
        from .. import train as forge_train
        state = {"alive": True, "error": None}

        def _run():
            try:
                ckpt = job.latest_checkpoint()
                resume = os.path.dirname(ckpt) if ckpt else None
                if resume:
                    log(f"[{self.name}] resuming from {resume}")
                # output under roam_dir so latest_checkpoint() can find it
                forge_train.train_voice(
                    job["language"], job["epochs"], job["batch_size"],
                    job["grad_accum"], job["train_csv"], job["eval_csv"],
                    job.roam_dir, int(job["max_audio_len_s"] * 22050),
                    log_fn=log, resume_from=resume)
                open(os.path.join(job["ckpt_dir"], "DONE"), "w").write("done")
            except Exception as e:
                state["error"] = e
                log(f"[{self.name}] FAILED: {e}")
            finally:
                state["alive"] = False

        t = threading.Thread(target=_run, daemon=True)
        t.start()
        return {"thread": t, "state": state}

    def poll(self, job, handle, log):
        st = handle["state"]
        if st["error"]:
            return "failed"
        if os.path.isfile(os.path.join(job["ckpt_dir"], "DONE")):
            return "done"
        return "running" if st["alive"] else "failed"

    def fetch(self, job, handle, log):
        # Local training writes checkpoints straight into the workdir tree;
        # consolidate the newest best_model into ckpt_dir.
        latest = job.latest_checkpoint()
        if latest:
            log(f"[{self.name}] latest checkpoint: {latest}")

    def stop(self, job, handle, log):
        log(f"[{self.name}] stop requested (thread will exit on its own)")


# ---------------------------------------------------------------- Kaggle
class KaggleProvider(BaseProvider):
    """Free GPU via Kaggle Kernels API. Real implementation.

    Setup: pip install kaggle, put credentials at ~/.kaggle/kaggle.json
    (from kaggle.com -> Account -> API -> Create New Token).
    """
    name = "kaggle"
    poll_interval = 60

    def _kaggle(self):
        k = shutil.which("kaggle")
        cred = os.path.expanduser("~/.kaggle/kaggle.json")
        return k, cred

    def _username(self):
        with open(os.path.expanduser("~/.kaggle/kaggle.json")) as f:
            return json.load(f)["username"]

    def is_available(self):
        k, cred = self._kaggle()
        if not k:
            return False, "kaggle CLI not installed (pip install kaggle)"
        if not os.path.isfile(cred):
            return False, "no ~/.kaggle/kaggle.json credentials"
        return True, "kaggle CLI + credentials present"

    # ---- dataset: upload once, version on change ----
    def _ensure_dataset(self, job, log):
        user = self._username()
        slug = f"{user}/forge-ds-{job['job_id']}".lower().replace("_", "-")
        ddir = os.path.join(job.roam_dir, "kaggle_dataset")
        os.makedirs(ddir, exist_ok=True)
        # link (or copy) the prepared wavs + CSVs into the dataset dir
        for rel in ("wavs", "metadata_train.csv", "metadata_eval.csv"):
            src = os.path.join(job["dataset_dir"], rel)
            dst = os.path.join(ddir, os.path.basename(rel.rstrip("/")) if rel != "wavs" else "wavs")
            if os.path.isdir(src):
                if os.path.isdir(dst):
                    shutil.rmtree(dst)
                shutil.copytree(src, dst)
            elif os.path.isfile(src):
                shutil.copy(src, ddir)
        meta = {"id": slug, "title": f"FORGE dataset {job['job_id']}",
                "licenses": [{"name": "private"}]}
        with open(os.path.join(ddir, "dataset-metadata.json"), "w") as f:
            json.dump(meta, f)
        k, _ = self._kaggle()
        if job["kaggle_dataset"]:
            r = _sh([k, "datasets", "version", "-p", ddir, "-m", "forge update"], log)
        else:
            r = _sh([k, "datasets", "create", "-p", ddir], log)
        if r.returncode != 0:
            raise RuntimeError("kaggle dataset upload failed")
        job["kaggle_dataset"] = slug
        return slug

    # ---- kernel bundle: driver + trainer code ----
    def _bundle(self, job, dataset_slug, log):
        bdir = os.path.join(job.roam_dir, "kaggle_kernel")
        os.makedirs(bdir, exist_ok=True)
        user = self._username()
        kernel_id = f"{user}/forge-train-{job['job_id']}".lower().replace("_", "-")

        # driver: runs inside the Kaggle kernel
        driver = f'''"""FORGE roam driver — generated. Runs inside a Kaggle kernel."""
import json, os, subprocess, sys

subprocess.run([sys.executable, "-m", "pip", "install", "-q", "coqui-TTS"],
               check=False)

DS = "/kaggle/input/{dataset_slug.split('/')[-1]}"
OUT = "/kaggle/working/forge_out"
os.makedirs(OUT, exist_ok=True)

# resume: previous kernel output attached via kernel_sources lands here
resume = None
inp_root = "/kaggle/input"
prev_slug = "{job['kaggle_kernel'].split('/')[-1] if job['kaggle_kernel'] else ''}"
if prev_slug:
    cand = os.path.join(inp_root, prev_slug)
    for root, _d, files in os.walk(cand):
        if "best_model.pth" in files:
            resume = root
            break

sys.path.insert(0, "/kaggle/working")
from forge_train import train_voice

train_voice(
    "{job['language']}", {job['epochs']}, {job['batch_size']}, {job['grad_accum']},
    os.path.join(DS, "metadata_train.csv"), os.path.join(DS, "metadata_eval.csv"),
    OUT, {int(job['max_audio_len_s'] * 22050)}, log_fn=print, resume_from=resume)

open(os.path.join(OUT, "DONE"), "w").write("done")
print("FORGE kernel training complete.")
'''
        with open(os.path.join(bdir, "main.py"), "w") as f:
            f.write(driver)

        # trainer code: copy of forge/train.py (self-contained)
        import forge.train as _t
        shutil.copy(_t.__file__, os.path.join(bdir, "forge_train.py"))

        sources = []
        if job["kaggle_kernel"]:
            sources = [job["kaggle_kernel"]]
        meta = {
            "id": kernel_id,
            "title": f"FORGE train {job['job_id']}",
            "code_file": "main.py",
            "language": "python",
            "kernel_type": "script",
            "is_private": True,
            "enable_gpu": True,
            "enable_internet": True,
            "dataset_sources": [dataset_slug],
            "kernel_sources": sources,
            "competition_sources": [],
            "model_sources": [],
        }
        with open(os.path.join(bdir, "kernel-metadata.json"), "w") as f:
            json.dump(meta, f)
        return bdir, kernel_id

    def prepare(self, job, log):
        slug = self._ensure_dataset(job, log)
        bdir, kernel_id = self._bundle(job, slug, log)
        k, _ = self._kaggle()
        r = _sh([k, "kernels", "push", "-p", bdir], log)
        if r.returncode != 0:
            raise RuntimeError("kaggle kernels push failed")
        job["kaggle_kernel"] = kernel_id
        log(f"[{self.name}] kernel pushed: {kernel_id}")

    def start(self, job, log):
        # push == start for Kaggle; the kernel runs on push
        return {"kernel": job["kaggle_kernel"], "t0": time.time()}

    def poll(self, job, handle, log):
        k, _ = self._kaggle()
        r = _sh([k, "kernels", "status", handle["kernel"]], log)
        out = (r.stdout or "").lower()
        if "complete" in out:
            # fetch outputs to check the DONE marker
            self.fetch(job, handle, log)
            done = os.path.isfile(os.path.join(job["ckpt_dir"], "DONE"))
            return "done" if done else "failed"
        if "error" in out or "cancelled" in out:
            return "failed"
        return "running"

    def fetch(self, job, handle, log):
        k, _ = self._kaggle()
        os.makedirs(job["ckpt_dir"], exist_ok=True)
        _sh([k, "kernels", "output", handle["kernel"], "-p", job["ckpt_dir"], "-q"], log)

    def stop(self, job, handle, log):
        log(f"[{self.name}] kernels can't be force-stopped via API; leaving it")


PROVIDERS = [LocalProvider(), KaggleProvider()]
