"""FORGE Gradio app: Dataset -> Train -> Voice."""
import os
import threading
import traceback

import gradio as gr

from . import dataset as ds
from . import files as ff
from . import train as tr
from . import synth as sy

LANGS = ["en", "es", "fr", "de", "it", "pt", "pl", "tr", "ru", "nl",
         "cs", "ar", "zh", "hu", "ko", "ja"]


def build_app(workdir):
    ds_dir = os.path.join(workdir, "dataset")
    voices_root = os.path.join(workdir, "voices")
    os.makedirs(ds_dir, exist_ok=True)
    os.makedirs(voices_root, exist_ok=True)

    state = {"train_csv": "", "eval_csv": "", "voice_dir": "",
             "train_status": "idle", "train_log": "press Start training."}

    # ---------------- dataset ----------------
    def suggest_epochs(total_minutes):
        if total_minutes < 30:
            return 10
        if total_minutes < 120:
            return 6
        if total_minutes < 480:
            return 4
        return 3  # 8h+: the data does the work, fewer epochs needed

    def make_dataset(files, folder, lang, whisper_model, progress=gr.Progress(track_tqdm=True)):
        inputs = list(files or [])
        if folder and folder.strip():
            inputs.append(folder.strip())
        if not inputs:
            return "Upload audio files or point at a folder first.", "", ""
        try:
            res = ds.build_dataset(inputs, target_language=lang, out_path=ds_dir,
                                   whisper_model=whisper_model,
                                   progress_cb=lambda p, desc="": progress(p, desc=desc))
        except Exception:
            return f"Dataset build failed:\n{traceback.format_exc()}", "", ""
        if res["total_minutes"] < 2:
            return (f"Only {res['total_minutes']} minutes of audio — "
                    "FORGE needs at least 2. Add more recordings."), "", ""
        state["train_csv"] = res["train_csv"]
        state["eval_csv"] = res["eval_csv"]
        ep = suggest_epochs(res["total_minutes"])
        state["suggested_epochs"] = ep
        sk = res.get("skipped", {})
        n_skip = sum(sk.values())
        skip_note = (f" Filtered {n_skip} junk clips "
                     f"(silence: {sk.get('too_quiet', 0)}, non-speech: {sk.get('no_speech', 0)}, "
                     f"fragments: {sk.get('too_short_text', 0) + sk.get('too_short_audio', 0)}.)"
                     if n_skip else "")
        tip = "" if res["total_minutes"] >= 10 else (
            "\n\nTip: it works, but more audio (10+ min, ideally 30-60) "
            "makes a much more convincing voice. FORGE scales to 30h+ — "
            "more data, better voice, no ceiling.")
        msg = (f"Dataset ready: {res['num_clips']} clips from {res.get('num_files', '?')} files "
               f"({res['num_train']} train / {res['num_eval']} eval), "
               f"{res['total_minutes']} minutes of your voice.{skip_note} "
               f"Suggested epochs for this much data: **{ep}**.{tip}")
        return msg, res["train_csv"], res["eval_csv"]

    # ---------------- training ----------------
    def _train_worker(lang, epochs, batch, accum, max_len_s):
        state["train_status"] = "running"
        log_path = os.path.join(workdir, "train.log")
        def log_fn(m):
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(m.rstrip() + "\n")
        try:
            import sys
            class Tee:
                def __init__(self, *streams): self.streams = streams
                def write(self, m):
                    for s in self.streams:
                        try: s.write(m)
                        except Exception: pass
                def flush(self):
                    for s in self.streams:
                        try: s.flush()
                        except Exception: pass
            old = sys.stdout
            lf = open(log_path, "a", encoding="utf-8")
            sys.stdout = Tee(old, lf)
            try:
                res = tr.train_voice(lang, int(epochs), int(batch), int(accum),
                                     state["train_csv"], state["eval_csv"],
                                     workdir, int(max_len_s * 22050), log_fn=log_fn)
            finally:
                sys.stdout = old
                lf.close()
            voice_dir, _zip = sy.export_voice(
                "my-voice", res["checkpoint"], res["config"], res["vocab"],
                res["speaker_ref"], voices_root)
            state["voice_dir"] = voice_dir
            state["train_status"] = "done"
            log_fn(f"[forge] voice exported to {voice_dir}")
        except Exception:
            state["train_status"] = "failed"
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(traceback.format_exc())

    def start_training(lang, epochs, batch, accum, max_len_s, tcsv, tcsv2, backend):
        state["train_csv"], state["eval_csv"] = tcsv, tcsv2
        if not tcsv or not tcsv2:
            return "Build the dataset first (tab 1)."
        if state["train_status"] == "running":
            return "Training is already running."
        state["backend"] = backend
        if backend.startswith("Roam"):
            return start_roam(lang, epochs, batch, accum, max_len_s)
        open(os.path.join(workdir, "train.log"), "w").write("")
        state["train_status"] = "running"
        threading.Thread(target=_train_worker,
                         args=(lang, epochs, batch, accum, max_len_s),
                         daemon=True).start()
        return "Training started — watch the log below. This takes hours; leave it running."

    def start_roam(lang, epochs, batch, accum, max_len_s):
        from .roam.job import RoamJob
        from .roam.orchestrator import RoamOrchestrator
        job = RoamJob(workdir)
        job["status"] = "running"
        job["dataset_dir"] = ds_dir
        job["train_csv"] = state["train_csv"]
        job["eval_csv"] = state["eval_csv"]
        job["language"] = lang
        job["epochs"] = int(epochs)
        job["batch_size"] = int(batch)
        job["grad_accum"] = int(accum)
        job["max_audio_len_s"] = int(max_len_s)
        job["done_marker"] = False
        job["providers_tried"] = []
        open(job.log_path, "w").write("")
        state["train_status"] = "running"

        def _run():
            orch = RoamOrchestrator(job)
            orch.run()
            if job["status"] == "done":
                try:
                    voice_dir = export_roam_voice(job)
                    state["voice_dir"] = voice_dir
                    state["train_status"] = "done"
                except Exception as e:
                    state["train_status"] = "failed"
                    with open(job.log_path, "a") as f:
                        f.write(f"[roam] export failed: {e}\n")
            else:
                state["train_status"] = "failed"

        threading.Thread(target=_run, daemon=True).start()
        return ("Roam started — the backend will roam across providers as needed. "
                "Watch the log below; the frontend stays the same no matter where it runs.")

    def export_roam_voice(job):
        import pandas as pd
        ckpt = job.latest_checkpoint()
        if not ckpt:
            raise RuntimeError("no checkpoint found after roam run")
        root = os.path.dirname(ckpt)
        # config + vocab travel next to the checkpoint (train_voice copies them)
        def _find(name):
            for r, _d, files in os.walk(os.path.dirname(root)):
                if name in files:
                    return os.path.join(r, name)
            return None
        config = _find("config.json")
        vocab = _find("vocab.json")
        # speaker reference: first clip from the train CSV
        df = pd.read_csv(job["train_csv"], sep="|")
        rel = df.iloc[0]["audio_file"]
        speaker_ref = rel if os.path.isabs(rel) else os.path.join(job["dataset_dir"], rel)
        voice_dir, _zip = sy.export_voice("my-voice", ckpt, config, vocab,
                                          speaker_ref, voices_root)
        return voice_dir

    def latest_voice():
        """Newest exported voice folder that actually contains a checkpoint."""
        try:
            cands = [os.path.join(voices_root, d) for d in os.listdir(voices_root)]
        except OSError:
            return ""

        def _newest(d):
            try:
                names = [f for f in os.listdir(d) if f.lower().endswith(".pth")]
                return max((os.path.getmtime(os.path.join(d, f)) for f in names),
                           default=0)
            except OSError:
                return 0

        cands = [(d, _newest(d)) for d in cands if os.path.isdir(d)]
        cands = [(d, t) for d, t in cands if t]      # dirs with a real .pth in them
        return max(cands, key=lambda dt: dt[1])[0] if cands else ""

    def resolve_voice(vdir):
        """Accept a folder, a .pth, or nothing (fall back to what we have)."""
        vdir = (vdir or "").strip().strip('"')
        return vdir or state["voice_dir"] or latest_voice()

    def pull_new_voice():
        """Push a freshly trained voice into the field, once — never fight a
        path the user typed in by hand."""
        fresh = state["voice_dir"]
        if fresh and fresh != state.get("voice_pushed"):
            state["voice_pushed"] = fresh
            return gr.update(value=fresh)
        return gr.update()

    def tail_log():
        # roam backend has its own log; local backend uses train.log
        if state.get("backend", "").startswith("Roam"):
            p = os.path.join(workdir, "roam", "roam.log")
        else:
            p = os.path.join(workdir, "train.log")
        if not os.path.isfile(p):
            return state["train_log"]
        with open(p, encoding="utf-8", errors="replace") as f:
            lines = f.read().splitlines()
        tail = "\n".join(lines[-60:])
        s = state["train_status"]
        head = {"running": "● training…", "done": "✓ training complete — see tab 3.",
                "failed": "✗ training failed — check the log tail."}.get(s, "")
        return f"{head}\n\n{tail}" if head else tail

    # ---------------- voice test / export ----------------
    def speak(text, lang, vdir):
        vdir = resolve_voice(vdir)
        if not vdir or not os.path.exists(vdir):
            return None, ("No trained voice yet. Finish tab 2, or paste the path to a "
                          "voice folder (or its model.pth) into the field above.")
        out = os.path.join(workdir, "preview.wav")
        try:
            sy.synthesize(text, vdir, out, lang)
        except Exception:
            return None, f"Synthesis failed:\n{traceback.format_exc()}"
        return out, "Done — press play."

    def export_now(vdir, name):
        vdir = resolve_voice(vdir)
        name = (name or "my-voice").strip().replace(" ", "-")
        if not vdir or not os.path.exists(vdir):
            return None, "No trained voice yet."
        try:
            spec = sy.describe(vdir)
            _, zip_path = sy.export_voice(name, spec["checkpoint"], spec["config"],
                                          spec["vocab"], spec["speaker_ref"],
                                          voices_root)
        except Exception:
            return None, f"Export failed:\n{traceback.format_exc()}"
        return zip_path, f"Exported {zip_path}"

    # ---------------- UI ----------------
    with gr.Blocks(title="FORGE — your voice, your model") as app:
        gr.Markdown("# FORGE\n**Your voice, your model.** Upload recordings, train locally, export a TTS voice that is yours.\n\n> Only train on your own voice, or a voice you have clear permission to use.")

        with gr.Tab("1 · Dataset"):
            gr.Markdown("Upload clean recordings of **one speaker** (you) — or point at a folder "
                        "full of them (better for large collections). 2 minutes minimum, "
                        "10+ recommended, and FORGE scales to **30 hours and beyond**: more data, "
                        "better voice, no ceiling. Quiet room, consistent mic distance, natural "
                        "reading — see `recording-script.txt` for material.")
            up = gr.File(file_count="multiple", label="Voice recordings (wav / mp3 / flac / m4a / ogg)",
                         file_types=["audio"])
            folder = gr.Textbox(label="…or folder path on this machine (e.g. D:\\my-voice\\recordings)",
                                placeholder="Paste a folder path instead of uploading")
            lang1 = gr.Dropdown(LANGS, value="en", label="Language")
            wmodel = gr.Dropdown(["large-v2", "medium", "small", "base", "tiny"],
                                 value="large-v2",
                                 label="Whisper model (smaller = faster transcription, slightly rougher transcripts)")
            b1 = gr.Button("Step 1 — Build dataset", variant="primary")
            ds_msg = gr.Markdown()
            tcsv = gr.Textbox(label="Train CSV (auto-filled)")
            ecsv = gr.Textbox(label="Eval CSV (auto-filled)")
            b1.click(make_dataset, [up, folder, lang1, wmodel], [ds_msg, tcsv, ecsv])

        with gr.Tab("2 · Train") as tab2:
            gr.Markdown("Fine-tunes XTTS v2 on your dataset using your NVIDIA GPU. "
                        "Defaults suit a 16GB card (e.g. RTX 5070 Ti). Expect a few hours — progress appears below. "
                        "Opening this tab applies the epoch suggestion from your dataset size.")
            backend = gr.Dropdown(["Local GPU", "Roam (auto-failover)"],
                                  value="Local GPU",
                                  label="Backend — Roam lets training hop providers (local → Kaggle free GPU) when one dies")
            lang2 = gr.Dropdown(LANGS, value="en", label="Language")
            epochs = gr.Slider(1, 50, value=10, step=1, label="Epochs")
            tab2.select(lambda: gr.update(value=state.get("suggested_epochs", 10)), None, epochs)
            batch = gr.Slider(1, 16, value=4, step=1, label="Batch size (lower if VRAM runs out)")
            accum = gr.Slider(1, 32, value=4, step=1, label="Gradient accumulation steps")
            maxlen = gr.Slider(4, 20, value=11, step=1, label="Max clip length (seconds)")
            b2 = gr.Button("Step 2 — Start training", variant="primary")
            tr_msg = gr.Markdown()
            tr_log = gr.Textbox(label="Training log", lines=20, interactive=False)
            b2.click(start_training, [lang2, epochs, batch, accum, maxlen, tcsv, ecsv, backend], [tr_msg])
            app.load(tail_log, None, tr_log)
            gr.Timer(5).tick(tail_log, None, tr_log)

        with gr.Tab("3 · Voice"):
            gr.Markdown("Test your trained voice, then export it as a portable package. "
                        "Already trained? Point the field below at your voice folder — or "
                        "straight at a `model.pth` — and press Speak. A voice needs "
                        "`model.pth` + `config.json` + `vocab.json` + a reference `.wav`; "
                        "files sitting next to the `.pth` are found automatically.")
            vdir = gr.Textbox(label="Voice folder or model.pth (auto-filled)",
                              value=state["voice_dir"] or latest_voice())
            # after a training run finishes, point the field at the fresh export
            gr.Timer(5).tick(pull_new_voice, None, vdir)
            lang3 = gr.Dropdown(LANGS, value="en", label="Language")
            txt = gr.Textbox(label="Text to speak",
                             value="This is my voice now. It was trained on my own recordings, on my own machine.")
            b3 = gr.Button("Speak", variant="primary")
            audio_out = gr.Audio(label="Preview")
            speak_msg = gr.Markdown()
            b3.click(speak, [txt, lang3, vdir], [audio_out, speak_msg])
            gr.Markdown("### Export")
            vname = gr.Textbox(label="Voice name", value="my-voice")
            b4 = gr.Button("Export voice package (.zip)")
            zip_out = gr.File(label="Download")
            exp_msg = gr.Markdown()
            b4.click(export_now, [vdir, vname], [zip_out, exp_msg])
            gr.Markdown("Use the voice anywhere — from a terminal in this folder:\n"
                        "```bat\n"
                        ".venv\\Scripts\\activate\n"
                        "python -m forge.synth --voice \"%USERPROFILE%\\forge\\voices\\my-voice\" "
                        "--text \"hello\" --out out.wav\n"
                        "```\n"
                        "Or the same file via `--checkpoint path\\to\\model.pth` when it "
                        "sits next to `config.json`, `vocab.json` and a reference `.wav`. "
                        "`say.bat \"some text\"` does the same thing in one click.")

        with gr.Tab("4 · Files"):
            gr.Markdown("Browse everything FORGE has created — datasets, checkpoints, exported voices — with sizes.")
            tree_box = gr.Textbox(label="Working directory tree", lines=25, interactive=False)
            refresh_btn = gr.Button("Refresh tree")
            refresh_btn.click(lambda: ff.tree_string(workdir), None, tree_box)
            app.load(lambda: ff.tree_string(workdir), None, tree_box)

    return app
