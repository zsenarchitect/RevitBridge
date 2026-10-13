"""Metering: every job records machine time. This ledger is the billing foundation.

Each finished job emits a UsageEvent: who, what backend, how many seconds of
worker machine time, and the cost computed from the rate card. The hosted
service bills off these events (see billing/).
"""

from __future__ import annotations

import sqlite3
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class UsageEvent:
    job_id: str
    user_id: str
    backend: str
    src_fmt: str
    dst_fmt: str
    input_bytes: int
    output_bytes: int
    metered_seconds: float
    cost_usd: float
    started_at: float
    finished_at: float
    recorded_at: float = 0.0

    def __post_init__(self):
        if not self.recorded_at:
            self.recorded_at = time.time()


class UsageLedger(ABC):
    @abstractmethod
    def record(self, event: UsageEvent) -> None: ...
    @abstractmethod
    def events(self, user_id: str | None = None) -> list[UsageEvent]: ...


class MemoryUsageLedger(UsageLedger):
    def __init__(self) -> None:
        self._events: list[UsageEvent] = []
        self._lock = threading.Lock()

    def record(self, event: UsageEvent) -> None:
        with self._lock:
            self._events.append(event)

    def events(self, user_id: str | None = None) -> list[UsageEvent]:
        with self._lock:
            evts = list(self._events)
        if user_id is not None:
            evts = [e for e in evts if e.user_id == user_id]
        return evts


class SqliteUsageLedger(UsageLedger):
    """Prototype-persistent ledger. Swap for Postgres at scale (see roadmap)."""

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS usage_events (
        job_id TEXT PRIMARY KEY, user_id TEXT, backend TEXT,
        src_fmt TEXT, dst_fmt TEXT, input_bytes INTEGER, output_bytes INTEGER,
        metered_seconds REAL, cost_usd REAL,
        started_at REAL, finished_at REAL, recorded_at REAL
    )"""

    def __init__(self, path: str) -> None:
        self._path = path
        self._lock = threading.Lock()
        with sqlite3.connect(path) as con:
            con.execute(self.SCHEMA)

    def record(self, event: UsageEvent) -> None:
        with self._lock, sqlite3.connect(self._path) as con:
            con.execute(
                "INSERT OR REPLACE INTO usage_events VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (event.job_id, event.user_id, event.backend, event.src_fmt,
                 event.dst_fmt, event.input_bytes, event.output_bytes,
                 event.metered_seconds, event.cost_usd, event.started_at,
                 event.finished_at, event.recorded_at),
            )

    def events(self, user_id: str | None = None) -> list[UsageEvent]:
        with self._lock, sqlite3.connect(self._path) as con:
            rows = con.execute(
                "SELECT * FROM usage_events" + (" WHERE user_id=?" if user_id else ""),
                (user_id,) if user_id else (),
            ).fetchall()
        return [UsageEvent(*r) for r in rows]
