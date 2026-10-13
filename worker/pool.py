"""Conversion worker pool.

Workers claim jobs from the queue, run them through revit_bridge.pipeline,
time the run (that wall-clock time IS the metered machine time), record a
UsageEvent, and report usage to the billing provider.
"""

from __future__ import annotations

import os
import threading
import time
import traceback
from pathlib import Path

from revit_bridge.errors import ConversionError
from revit_bridge.pipeline import convert

from .metering import UsageEvent, UsageLedger
from .queue import Job, JobQueue


class WorkerPool:
    def __init__(self, queue: JobQueue, ledger: UsageLedger, billing,
                 rates, workdir: str, n_workers: int = 2) -> None:
        self.queue = queue
        self.ledger = ledger
        self.billing = billing
        self.rates = rates
        self.workdir = workdir
        self.n_workers = n_workers
        self._threads: list[threading.Thread] = []
        self._stop = threading.Event()

    # -- lifecycle ---------------------------------------------------------
    def start(self) -> None:
        self._stop.clear()
        for i in range(self.n_workers):
            t = threading.Thread(target=self._loop, name=f"rb-worker-{i}", daemon=True)
            t.start()
            self._threads.append(t)

    def stop(self, timeout: float = 10.0) -> None:
        self._stop.set()
        for t in self._threads:
            t.join(timeout=timeout / max(len(self._threads), 1))
        self._threads.clear()

    def _loop(self) -> None:
        while not self._stop.is_set():
            if not self.drain_once():
                time.sleep(0.25)

    # -- job execution ------------------------------------------------------
    def drain_once(self) -> bool:
        """Claim and run a single job. Returns False when the queue was empty."""
        job = self.queue.claim_next()
        if job is None:
            return False
        self._run_job(job)
        return True

    def _run_job(self, job: Job) -> None:
        job_dir = Path(self.workdir) / job.id
        job_dir.mkdir(parents=True, exist_ok=True)
        out_name = f"{Path(job.filename).stem}.{job.dst_fmt}"
        dst = str(job_dir / out_name)
        t0 = time.time()
        try:
            job.progress = 15
            self.queue.update(job)
            result = convert(job.src_path, dst, to=job.dst_fmt,
                             backend=job.backend, workdir=str(job_dir))
            job.progress = 90
            self.queue.update(job)
            job.status = "done"
            job.result_path = result
        except ConversionError as e:
            job.status = "failed"
            job.error = str(e)
        except Exception:  # noqa: BLE001 - never kill the worker thread
            job.status = "failed"
            job.error = f"unexpected: {traceback.format_exc(limit=3)}"
        finally:
            t1 = time.time()
            job.metered_seconds = round(t1 - t0, 3)
            job.finished_at = t1
            job.progress = 100 if job.status == "done" else job.progress
            backend_used = job.backend or "auto"
            job.cost_usd = self.rates.cost_usd(backend_used, job.metered_seconds)
            self.queue.update(job)
            out_bytes = 0
            if job.result_path and os.path.exists(job.result_path):
                out_bytes = os.path.getsize(job.result_path)
            event = UsageEvent(
                job_id=job.id, user_id=job.user_id, backend=backend_used,
                src_fmt=job.src_fmt, dst_fmt=job.dst_fmt,
                input_bytes=os.path.getsize(job.src_path),
                output_bytes=out_bytes,
                metered_seconds=job.metered_seconds, cost_usd=job.cost_usd,
                started_at=job.started_at or t0, finished_at=t1,
            )
            self.ledger.record(event)
            try:
                self.billing.report_usage(event)
            except Exception:  # noqa: BLE001 - billing must never lose a job record
                pass  # the ledger is the source of truth; billing retries from it
