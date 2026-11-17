"""Job state machine and supervisor (with stand-in worker commands)."""

import sys
import time

import pytest

from app.storage.db import db, now
from app.workers import jobs
from app.workers.worker import Supervisor, cleanup_expired


@pytest.fixture()
def project(data_dir):
    db().execute("INSERT INTO projects(id, owner, name, created_at, updated_at) VALUES('aa11', 'o', 'p', 0, 0)")
    return "aa11"


def wait_for(fn, timeout=15):
    t = time.time()
    while time.time() - t < timeout:
        if fn():
            return True
        time.sleep(0.1)
    return False


def test_transitions_are_enforced(project):
    j = jobs.create_job(project, "o", "quick", {})
    with pytest.raises(jobs.InvalidTransition):
        jobs.transition(j["id"], "succeeded")
    jobs.transition(j["id"], "running")
    jobs.transition(j["id"], "succeeded")
    with pytest.raises(jobs.InvalidTransition):
        jobs.retry(j["id"])
    with pytest.raises(jobs.InvalidTransition):
        jobs.request_cancel(j["id"])


def test_progress_only_updates_running_jobs(project):
    j = jobs.create_job(project, "o", "quick", {})
    jobs.update_progress(j["id"], progress=0.5)
    assert jobs.get_job(j["id"])["progress"] is None
    jobs.transition(j["id"], "running")
    jobs.update_progress(j["id"], progress=0.5, stage="estimating_depth")
    got = jobs.get_job(j["id"])
    assert got["progress"] == 0.5 and got["stage"] == "estimating_depth" and got["heartbeat_at"]


def sup(cmd):
    return Supervisor(poll_seconds=0.05, command=lambda jid: [sys.executable, "-c", cmd])


def test_worker_crash_marks_failed(project):
    s = sup("import sys; sys.exit(3)")
    j = jobs.create_job(project, "o", "quick", {})
    s.tick()
    assert jobs.get_job(j["id"])["state"] == "running"
    assert wait_for(lambda: (s.tick() or True) and jobs.get_job(j["id"])["state"] == "failed")
    got = jobs.get_job(j["id"])
    assert got["error_code"] == "worker_crash" and "unexpectedly" in got["error"]
    assert db().execute("SELECT status FROM projects WHERE id=?", (project,)).fetchone()["status"] == "failed"


def test_cancel_running_job_kills_after_grace(project, monkeypatch):
    import app.workers.worker as w

    monkeypatch.setattr(w, "CANCEL_GRACE_SECONDS", 0.3)
    s = sup("import time; time.sleep(60)")
    j = jobs.create_job(project, "o", "quick", {})
    s.tick()
    jobs.request_cancel(j["id"])
    assert jobs.get_job(j["id"])["cancel_requested"] == 1
    assert wait_for(lambda: (s.tick() or True) and jobs.get_job(j["id"])["state"] == "cancelled")
    assert not s.procs


def test_timeout(project, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "job_timeout_seconds", 0.3)
    s = sup("import time; time.sleep(60)")
    j = jobs.create_job(project, "o", "quick", {})
    s.tick()
    assert wait_for(lambda: (s.tick() or True) and jobs.get_job(j["id"])["state"] == "failed")
    assert jobs.get_job(j["id"])["error_code"] == "timeout"


def test_concurrency_limit_and_queue_order(project, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "max_concurrent_jobs", 1)
    s = sup("import time; time.sleep(0.4)")
    a = jobs.create_job(project, "o", "quick", {})
    time.sleep(0.01)
    b = jobs.create_job(project, "o", "quick", {})
    s.tick()
    assert jobs.get_job(a["id"])["state"] == "running" and jobs.get_job(b["id"])["state"] == "queued"
    assert wait_for(lambda: (s.tick() or True) and jobs.get_job(b["id"])["state"] == "running")
    s.stop()


def test_recover_marks_orphaned_jobs(project):
    j = jobs.create_job(project, "o", "quick", {})
    jobs.transition(j["id"], "running")
    Supervisor().recover()
    got = jobs.get_job(j["id"])
    assert got["state"] == "failed" and got["error_code"] == "interrupted"
    assert jobs.retry(j["id"])["state"] == "queued"


def test_retention_cleanup(data_dir):
    from app.storage.files import project_dir

    db().execute("INSERT INTO projects(id, owner, name, created_at, updated_at, expires_at) VALUES('bb22','o','x',0,0,?)", (now() - 1,))
    d = project_dir("bb22")
    (d / "inputs").mkdir(parents=True)
    (d / "inputs" / "f.jpg").write_bytes(b"x")
    assert cleanup_expired() == 1
    assert not d.exists()
    assert db().execute("SELECT 1 FROM projects WHERE id='bb22'").fetchone() is None
