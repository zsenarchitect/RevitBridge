import pytest
from fastapi.testclient import TestClient

from billing.provider import NoopBillingProvider
from billing.rates import RateCard
from web.app import create_app
from worker.metering import MemoryUsageLedger
from worker.queue import MemoryJobQueue


@pytest.fixture()
def svc(tmp_path):
    queue, ledger, billing = MemoryJobQueue(), MemoryUsageLedger(), NoopBillingProvider()
    app = create_app(queue=queue, ledger=ledger, billing=billing,
                     rates=RateCard(), data_dir=str(tmp_path / "data"),
                     start_workers=False)
    return {"app": app, "client": TestClient(app), "queue": queue,
            "ledger": ledger, "billing": billing, "pool": app.state.pool}


def _upload(client, ifc_bytes, to="obj", backend="ifcopenshell"):
    return client.post("/api/jobs",
                       files={"file": ("sample.ifc", ifc_bytes, "application/octet-stream")},
                       data={"to": to, "backend": backend})


def test_health_formats_backends(svc):
    c = svc["client"]
    assert c.get("/api/health").json() == {"ok": True}
    assert "glb" in c.get("/api/formats").json()["outputs"]
    assert c.get("/api/backends").json()["ifcopenshell"]["status"] == "proven"


def test_full_job_lifecycle(svc, sample_ifc):
    c, pool = svc["client"], svc["pool"]
    r = _upload(c, open(sample_ifc, "rb").read())
    assert r.status_code == 202
    job_id = r.json()["job_id"]

    assert pool.drain_once() is True
    assert pool.drain_once() is False  # queue empty

    st = c.get(f"/api/jobs/{job_id}").json()
    assert st["status"] == "done"
    assert st["progress"] == 100
    assert st["metered_seconds"] >= 0
    assert st["cost_usd"] >= 0
    assert st["download_url"] == f"/api/jobs/{job_id}/download"

    dl = c.get(f"/api/jobs/{job_id}/download")
    assert dl.status_code == 200
    assert dl.content.startswith(b"# RevitBridge OBJ export")

    # metering foundation: the ledger has the event, billing saw it
    events = svc["ledger"].events()
    assert len(events) == 1 and events[0].job_id == job_id
    assert events[0].metered_seconds >= 0
    assert len(svc["billing"].reported) == 1


def test_unsupported_target_rejected(svc, sample_ifc):
    c = svc["client"]
    r = _upload(c, open(sample_ifc, "rb").read(), to="step")
    assert r.status_code == 400


def test_unknown_job_404(svc):
    assert svc["client"].get("/api/jobs/nope").status_code == 404


def test_download_before_done_409(svc, sample_ifc):
    c = svc["client"]
    job_id = _upload(c, open(sample_ifc, "rb").read()).json()["job_id"]
    assert c.get(f"/api/jobs/{job_id}/download").status_code == 409


def test_failed_job_reports_error(svc, tmp_path):
    c, pool = svc["client"], svc["pool"]
    r = c.post("/api/jobs",
               files={"file": ("broken.ifc", b"not an ifc file", "application/octet-stream")},
               data={"to": "obj", "backend": "ifcopenshell"})
    job_id = r.json()["job_id"]
    pool.drain_once()
    st = c.get(f"/api/jobs/{job_id}").json()
    assert st["status"] == "failed"
    assert st["error"]
    # failed jobs are still metered (machine time was spent)
    assert len(svc["ledger"].events()) == 1
