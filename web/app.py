"""RevitBridge hosted service: upload -> pick format -> progress -> download.

Run:  uvicorn web.app:app --host 0.0.0.0 --port 8000   (from the repo root,
      with the core installed: pip install -e ".[web]")

Prototype scope, stated plainly:
- In-memory job queue (lost on restart) — swap worker.queue.JobQueue for Redis/RQ.
- SQLite usage ledger (worker/metering.py) — swap for Postgres at scale.
- Noop billing — swap billing.provider.BillingProvider for Stripe.
- Single API key auth via RB_API_KEY env (optional; off when unset).
- No user accounts yet: every job is user_id="anonymous" until auth lands.
"""

from __future__ import annotations

import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from revit_bridge.errors import UnsupportedFormatError
from revit_bridge.formats import INPUT_FORMATS, OUTPUT_FORMATS, canonical, format_from_path, route

from billing.provider import BillingProvider, NoopBillingProvider
from billing.rates import RateCard, rate_card_from_env
from worker.metering import SqliteUsageLedger, UsageLedger
from worker.pool import WorkerPool
from worker.queue import Job, JobQueue, MemoryJobQueue

HERE = Path(__file__).resolve().parent
MAX_UPLOAD_BYTES = int(os.environ.get("RB_MAX_UPLOAD_BYTES", str(500 * 1024 * 1024)))


def _check_api_key(x_api_key: str | None = Header(default=None)):
    expected = os.environ.get("RB_API_KEY", "")
    if expected and x_api_key != expected:
        raise HTTPException(status_code=401, detail="invalid API key")


def create_app(
    queue: JobQueue | None = None,
    ledger: UsageLedger | None = None,
    billing: BillingProvider | None = None,
    rates: RateCard | None = None,
    data_dir: str | Path | None = None,
    start_workers: bool = True,
    n_workers: int = 2,
) -> FastAPI:
    data_dir = Path(data_dir or os.environ.get("RB_DATA_DIR", "data")).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    upload_dir = data_dir / "uploads"
    upload_dir.mkdir(exist_ok=True)

    queue = queue or MemoryJobQueue()
    ledger = ledger or SqliteUsageLedger(str(data_dir / "usage.db"))
    billing = billing or NoopBillingProvider()
    rates = rates or rate_card_from_env()
    pool = WorkerPool(queue, ledger, billing, rates, str(data_dir / "jobs"), n_workers)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if start_workers:
            pool.start()
        yield
        if start_workers:
            pool.stop()

    app = FastAPI(title="RevitBridge", lifespan=lifespan)
    app.state.pool = pool
    app.state.queue = queue
    app.state.ledger = ledger

    def job_json(job: Job) -> dict:
        return {
            "job_id": job.id, "filename": job.filename,
            "src_fmt": job.src_fmt, "dst_fmt": job.dst_fmt,
            "backend": job.backend, "status": job.status,
            "progress": job.progress, "error": job.error,
            "metered_seconds": job.metered_seconds, "cost_usd": job.cost_usd,
            "created_at": job.created_at,
            "finished_at": job.finished_at,
            "download_url": f"/api/jobs/{job.id}/download" if job.status == "done" else None,
        }

    @app.get("/api/health")
    def health():
        return {"ok": True}

    @app.get("/api/formats")
    def formats():
        return {"inputs": sorted(INPUT_FORMATS), "outputs": sorted(OUTPUT_FORMATS)}

    @app.get("/api/backends")
    def backends():
        from revit_bridge.backends import REGISTRY

        return {
            name: {"title": be.title, "status": be.status, "note": be.note}
            for name, be in REGISTRY.items()
        }

    @app.post("/api/jobs", dependencies=[Depends(_check_api_key)])
    async def submit_job(
        file: UploadFile = File(...),
        to: str = Form(...),
        backend: str | None = Form(default=None),
        user_id: str = Form(default="anonymous"),
    ):
        dst_fmt = canonical(to)
        if dst_fmt not in OUTPUT_FORMATS:
            raise HTTPException(400, f"unsupported target format: {to!r}")
        filename = file.filename or "upload"
        try:
            src_fmt = format_from_path(filename)
            route(src_fmt, dst_fmt)  # validates the route exists
        except UnsupportedFormatError as e:
            raise HTTPException(400, str(e)) from e
        if backend:
            from revit_bridge.backends import REGISTRY

            if backend not in REGISTRY:
                raise HTTPException(400, f"unknown backend: {backend!r}")

        job_id = uuid.uuid4().hex[:12]
        safe_name = f"{job_id}_{Path(filename).name}"
        src_path = upload_dir / safe_name
        size = 0
        with open(src_path, "wb") as fh:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    src_path.unlink(missing_ok=True)
                    raise HTTPException(413, "upload too large")
                fh.write(chunk)

        job = Job(id=job_id, filename=Path(filename).name, src_path=str(src_path),
                  src_fmt=src_fmt, dst_fmt=dst_fmt, backend=backend, user_id=user_id)
        queue.submit(job)
        return JSONResponse({"job_id": job_id, "status": "queued"}, status_code=202)

    @app.get("/api/jobs/{job_id}")
    def job_status(job_id: str):
        job = queue.get(job_id)
        if job is None:
            raise HTTPException(404, "unknown job")
        return job_json(job)

    @app.get("/api/jobs/{job_id}/download")
    def job_download(job_id: str):
        job = queue.get(job_id)
        if job is None:
            raise HTTPException(404, "unknown job")
        if job.status != "done" or not job.result_path:
            raise HTTPException(409, f"job is {job.status}; nothing to download yet")
        return FileResponse(job.result_path,
                            filename=f"{Path(job.filename).stem}.{job.dst_fmt}")

    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")

    @app.get("/")
    def index():
        return FileResponse(HERE / "static" / "index.html")

    return app


app = create_app()
