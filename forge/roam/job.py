"""Roam job state — persisted as JSON so the orchestrator survives restarts."""
import json
import os
import time
import uuid


def _job_path(workdir):
    return os.path.join(workdir, "roam", "job.json")


class RoamJob:
    def __init__(self, workdir):
        self.workdir = workdir
        self.roam_dir = os.path.join(workdir, "roam")
        os.makedirs(self.roam_dir, exist_ok=True)
        self.path = _job_path(workdir)
        self.data = {
            "job_id": uuid.uuid4().hex[:8],
            "created": time.time(),
            "status": "idle",          # idle | running | done | failed
            "dataset_dir": "",         # prepared dataset (wavs + CSVs)
            "dataset_hash": "",
            "train_csv": "",
            "eval_csv": "",
            "language": "en",
            "epochs": 10,
            "batch_size": 4,
            "grad_accum": 4,
            "max_audio_len_s": 11,
            "ckpt_dir": os.path.join(self.roam_dir, "checkpoints"),
            "providers_tried": [],
            "kaggle_dataset": "",      # slug of uploaded dataset (cached)
            "kaggle_kernel": "",       # current kernel id
            "done_marker": False,
        }
        if os.path.isfile(self.path):
            try:
                with open(self.path) as f:
                    self.data.update(json.load(f))
            except Exception:
                pass
        self.save()

    def save(self):
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self.data, f, indent=2)
        os.replace(tmp, self.path)

    def __getitem__(self, k):
        return self.data[k]

    def __setitem__(self, k, v):
        self.data[k] = v
        self.save()

    @property
    def log_path(self):
        return os.path.join(self.roam_dir, "roam.log")

    def latest_checkpoint(self):
        """Newest best_model.pth under the roam dir, or None."""
        best = None
        best_mtime = 0
        for root, _dirs, files in os.walk(self.roam_dir):
            # skip the staged upload dirs; checkpoints never live there
            if "kaggle_dataset" in root or "kaggle_kernel" in root:
                continue
            for fn in files:
                if fn in ("best_model.pth", "checkpoint_latest.pth"):
                    fp = os.path.join(root, fn)
                    try:
                        mt = os.path.getmtime(fp)
                    except OSError:
                        continue
                    if mt > best_mtime:
                        best, best_mtime = fp, mt
        return best
