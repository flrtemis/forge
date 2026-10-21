# FORGE Roam — one frontend whose backend roams

## The idea

Training a voice takes hours. Free GPU platforms (Colab, Kaggle) kill sessions.
Your own GPU might be busy. **Roam** decouples *the job* from *where it runs*:

- The FORGE Train tab describes a job: dataset + hyperparams.
- The orchestrator picks a provider, launches training, and watches it.
- If the provider dies (session killed, quota exhausted, GPU lost), the
  orchestrator pulls the latest checkpoint home and resumes on the next
  provider — automatically.
- The UI never changes. One progress log. The backend roams.

## Architecture

```
FORGE Train tab  →  RoamJob (persisted JSON)  →  RoamOrchestrator
                                                        │
                          ┌───────────────┬─────────────┴───────────────┐
                     LocalProvider   KaggleProvider   (ColabProvider: manual,
                      (your GPU)     (free GPU)       documented below)
```

**Provider contract** (`forge/roam/providers.py`): `is_available`, `prepare`,
`start → handle`, `poll → running|done|failed`, `fetch` (pull checkpoints),
`stop`. Any new platform is ~100 lines implementing this interface.

**Failover flow**:
1. `prepare`: stage dataset + code on the provider (Kaggle: upload dataset
   once, reuse by slug; push kernel).
2. `start`: launch. A `DONE` marker file is written when `train_voice`
   returns — this is how the orchestrator distinguishes *finished training*
   from *killed session*.
3. `poll`: health checks. Checkpoints sync home opportunistically.
4. On `failed`: rescue-fetch checkpoints, `stop`, pick next provider,
   resume via `TrainerArgs(restore_path=...)`.

**State** survives restarts: `workdir/roam/job.json` + `workdir/roam/roam.log`.

## Providers

### local (working now)
Your own NVIDIA GPU. Zero setup beyond FORGE itself.

### kaggle (implemented, needs credentials)
Free GPU via the Kaggle Kernels API.
1. `pip install kaggle`
2. kaggle.com → Account → API → Create New Token → save as
   `~/.kaggle/kaggle.json`
3. Select "Roam (auto-failover)" in the Train tab.

How it works: dataset uploaded once as a private Kaggle dataset (cached by
slug); a kernel bundle (driver + trainer) is pushed with GPU enabled; the
driver resumes from the previous kernel's output via `kernel_sources`.
`kaggle kernels output` pulls checkpoints home. Session killed? The
orchestrator pushes a new kernel version that resumes where it died.

Limits: kernels have max runtimes (~9–12h GPU); private datasets count
against your quota; first push uploads the dataset (slow once, then cached).

### colab (documented manual path)
Colab has no stable public API for programmatic kernel management — the
reliable route is assisted: the orchestrator prepares a self-contained
notebook + dataset bundle, you run it once in Colab, and point FORGE at the
Colab-hosted checkpoint sync (e.g. a Drive folder). A `ColabProvider`
implementing the provider contract around Drive-synced checkpoints is the
natural next adapter; the interface is ready for it.

## The honest bits

- Cross-provider resume re-downloads the dataset per provider (cached after
  the first time) and ships checkpoints (1–2GB). Failover isn't instant;
  it's *automatic*.
- Free tiers owe you nothing: quotas, queues, and killed sessions are the
  price. Roam just makes them survivable.
- Your own GPU is still the fastest, most private option. Roam is for when
  it's busy — or when you'd rather spend someone else's electricity.
