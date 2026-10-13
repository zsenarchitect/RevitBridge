"""Async job queue for the hosted conversion service.

Prototype ships an in-memory queue; the JobQueue ABC is the seam where
Redis/RQ/Celery plugs in later without touching the web routes or workers.
"""

from __future__ import annotations

import threading
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class Job:
    id: str
    filename: str
    src_path: str
    src_fmt: str
    dst_fmt: str
    backend: str | None = None
    user_id: str = "anonymous"
    status: str = "queued"  # queued | running | done | failed
    progress: int = 0
    error: str | None = None
    result_path: str | None = None
    metered_seconds: float = 0.0
    cost_usd: float = 0.0
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None


class JobQueue(ABC):
    @abstractmethod
    def submit(self, job: Job) -> str: ...
    @abstractmethod
    def get(self, job_id: str) -> Job | None: ...
    @abstractmethod
    def claim_next(self) -> Job | None:
        """Atomically move the oldest queued job to running and return it."""

    @abstractmethod
    def update(self, job: Job) -> None: ...


class MemoryJobQueue(JobQueue):
    """Prototype queue. Single process; lost on restart (see roadmap)."""

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._order: list[str] = []
        self._lock = threading.Lock()

    def submit(self, job: Job) -> str:
        if not job.id:
            job.id = uuid.uuid4().hex[:12]
        with self._lock:
            self._jobs[job.id] = job
            self._order.append(job.id)
        return job.id

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def claim_next(self) -> Job | None:
        with self._lock:
            for jid in self._order:
                job = self._jobs[jid]
                if job.status == "queued":
                    job.status = "running"
                    job.started_at = time.time()
                    job.progress = 5
                    return job
        return None

    def update(self, job: Job) -> None:
        with self._lock:
            self._jobs[job.id] = job
