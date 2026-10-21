"""The roam loop: keep the job alive across providers until it's done.

One frontend whose backend roams: this is the piece that watches a training
job, detects a dead provider (killed session, quota exhausted, GPU lost),
pulls the latest checkpoint home, and resumes on the next provider — while
the UI just shows one continuous progress log.
"""
import time
import traceback

from .job import RoamJob
from .providers import PROVIDERS


class RoamOrchestrator:
    def __init__(self, job, log_fn=None, max_failovers=10):
        self.job = job
        self.max_failovers = max_failovers
        self._log_fn = log_fn or (lambda m: None)
        self._stop = False
        lf = open(job.log_path, "a", encoding="utf-8")

        def log(m):
            line = m.rstrip()
            try:
                lf.write(line + "\n")
                lf.flush()
            except Exception:
                pass
            self._log_fn(line)
        self.log = log

    def stop(self):
        self._stop = True

    def _available(self):
        ranked = []
        for p in PROVIDERS:
            ok, reason = p.is_available()
            self.log(f"[roam] provider {p.name}: {'OK' if ok else 'SKIP'} ({reason})")
            if ok:
                ranked.append(p)
        return ranked

    def run(self):
        job = self.job
        job["status"] = "running"
        failovers = 0
        try:
            while not self._stop:
                # already finished elsewhere?
                if job.latest_checkpoint() and job["done_marker"]:
                    job["status"] = "done"
                    self.log("[roam] job complete.")
                    return

                providers = self._available()
                # prefer providers we haven't burned yet, keep local first
                providers.sort(key=lambda p: (p.name in job["providers_tried"],
                                              0 if p.name == "local" else 1))
                if not providers:
                    job["status"] = "failed"
                    self.log("[roam] no providers available — job failed.")
                    return

                provider = providers[0]
                self.log(f"[roam] running on {provider.name} "
                         f"(failover #{failovers})")
                try:
                    provider.prepare(job, self.log)
                    handle = provider.start(job, self.log)
                except Exception as e:
                    self.log(f"[roam] {provider.name} failed to start: {e}")
                    job["providers_tried"] = job["providers_tried"] + [provider.name]
                    failovers += 1
                    continue

                # watch it
                while not self._stop:
                    time.sleep(provider.poll_interval)
                    try:
                        st = provider.poll(job, handle, self.log)
                    except Exception as e:
                        self.log(f"[roam] poll error on {provider.name}: {e}")
                        st = "failed"
                    if st == "done":
                        try:
                            provider.fetch(job, handle, self.log)
                        except Exception as e:
                            self.log(f"[roam] final fetch failed: {e}")
                        job["done_marker"] = True
                        job["status"] = "done"
                        self.log(f"[roam] job complete on {provider.name}.")
                        return
                    if st == "failed":
                        self.log(f"[roam] {provider.name} died — rescuing checkpoints…")
                        try:
                            provider.fetch(job, handle, self.log)
                        except Exception as e:
                            self.log(f"[roam] rescue fetch failed: {e}")
                        try:
                            provider.stop(job, handle, self.log)
                        except Exception:
                            pass
                        break
                    # running: opportunistically sync checkpoints home
                    try:
                        provider.fetch(job, handle, self.log)
                    except Exception:
                        pass

                if self._stop:
                    job["status"] = "failed"
                    self.log("[roam] stopped by user.")
                    return

                job["providers_tried"] = job["providers_tried"] + [provider.name]
                failovers += 1
                if failovers > self.max_failovers:
                    job["status"] = "failed"
                    self.log("[roam] too many failovers — giving up.")
                    return
                self.log("[roam] failing over to next provider…")
        except Exception:
            job["status"] = "failed"
            self.log("[roam] orchestrator crashed:\n" + traceback.format_exc())
