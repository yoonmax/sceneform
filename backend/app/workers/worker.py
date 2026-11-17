"""Job supervisor: launches, watches, times out, and cleans up job processes."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from pathlib import Path

from ..config import settings
from ..storage.db import db, now
from ..storage.files import delete_project_files
from . import jobs

BACKEND_ROOT = Path(__file__).resolve().parents[2]
CANCEL_GRACE_SECONDS = 20


class Supervisor:
    def __init__(self, poll_seconds: float = 0.5, command=None):
        self.poll = poll_seconds
        self.procs: dict[str, tuple[subprocess.Popen, float]] = {}
        self.cancel_seen: dict[str, float] = {}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.command = command or (lambda job_id: [sys.executable, "-m", "app.workers.run_job", job_id])
        self._last_cleanup = 0.0

    # -------------------------------------------------------- lifecycle
    def start(self) -> None:
        self.recover()
        self._thread = threading.Thread(target=self._loop, name="sceneform-supervisor", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        for jid, (p, _) in list(self.procs.items()):
            p.terminate()
        if self._thread:
            self._thread.join(timeout=5)

    def recover(self) -> None:
        """Jobs left 'running' by a previous server process cannot resume."""
        for row in db().execute("SELECT id, project_id FROM jobs WHERE state='running'").fetchall():
            jobs.transition(row["id"], "failed", error="The server restarted while this job was running. You can retry it.",
                            error_code="interrupted", message="Interrupted")
            jobs.sync_project_status(row["project_id"])

    # ------------------------------------------------------------- loop
    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception as exc:  # keep supervising no matter what
                print(f"[supervisor] {exc!r}", file=sys.stderr)
            self._stop.wait(self.poll)

    def tick(self) -> None:
        self._reap()
        self._launch()
        if time.time() - self._last_cleanup > 600:
            self._last_cleanup = time.time()
            cleanup_expired()

    def _launch(self) -> None:
        while len(self.procs) < settings.max_concurrent_jobs:
            row = db().execute("SELECT id FROM jobs WHERE state='queued' ORDER BY created_at LIMIT 1").fetchone()
            if row is None:
                return
            jid = row["id"]
            jobs.transition(jid, "running", started_at=now(), heartbeat_at=now(), message="Starting")
            env = {**os.environ, "SCENEFORM_DATA_DIR": str(settings.data_dir), "PYTHONUNBUFFERED": "1"}
            p = subprocess.Popen(self.command(jid), cwd=str(BACKEND_ROOT), env=env,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            db().execute("UPDATE jobs SET pid=? WHERE id=?", (p.pid, jid))
            self.procs[jid] = (p, time.time())

    def _reap(self) -> None:
        for jid, (p, started) in list(self.procs.items()):
            code = p.poll()
            job = jobs.get_job(jid)
            if code is None:
                if job and job["cancel_requested"]:
                    first = self.cancel_seen.setdefault(jid, time.time())
                    if time.time() - first > CANCEL_GRACE_SECONDS:
                        p.kill()
                elif time.time() - started > settings.job_timeout_seconds:
                    p.kill()
                    if job and job["state"] == "running":
                        jobs.transition(jid, "failed", error="The job took too long and was stopped.",
                                        error_code="timeout", message="Timed out")
                        jobs.sync_project_status(job["project_id"])
                continue
            del self.procs[jid]
            self.cancel_seen.pop(jid, None)
            if job and job["state"] == "running":
                if job["cancel_requested"]:
                    jobs.transition(jid, "cancelled", message="Cancelled")
                else:
                    err = (p.stderr.read() or b"").decode("utf-8", "replace")[-1500:] if p.stderr else ""
                    jobs.transition(jid, "failed", error="The reconstruction worker stopped unexpectedly.",
                                    error_code="worker_crash", message=f"Worker exited with code {code}")
                    if err:
                        print(f"[supervisor] job {jid} stderr: {err}", file=sys.stderr)
                jobs.sync_project_status(job["project_id"])


def cleanup_expired() -> int:
    """Delete projects past their retention window (files and rows)."""
    rows = db().execute("SELECT id FROM projects WHERE expires_at IS NOT NULL AND expires_at < ?", (now(),)).fetchall()
    for r in rows:
        running = db().execute("SELECT 1 FROM jobs WHERE project_id=? AND state IN ('queued','running')", (r["id"],)).fetchone()
        if running:
            continue
        delete_project_files(r["id"])
        db().execute("DELETE FROM projects WHERE id=?", (r["id"],))
    return len(rows)
