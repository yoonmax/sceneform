"""Job state machine and persistence.

    queued ──▶ running ──▶ succeeded
       │          │  ╲──▶ failed ──┐
       │          ╰────▶ cancelled ─┤
       ╰──────────────▶ cancelled   │
                                    ▼
                    retry: back to queued (new run id)
"""

from __future__ import annotations

import json

from ..storage.db import db, now, row_dict, tx
from ..storage.files import new_id

TERMINAL = {"succeeded", "failed", "cancelled"}
TRANSITIONS = {
    "queued": {"running", "cancelled"},
    "running": {"succeeded", "failed", "cancelled"},
    "failed": {"queued"},
    "cancelled": {"queued"},
    "succeeded": set(),
}


class InvalidTransition(ValueError):
    pass


def create_job(project_id: str, owner: str, mode: str, config: dict) -> dict:
    jid, rid = new_id(12), new_id(8)
    with tx() as con:
        con.execute(
            "INSERT INTO jobs(id, project_id, owner, run_id, mode, state, config, created_at, message)"
            " VALUES(?,?,?,?,?,'queued',?,?,?)",
            (jid, project_id, owner, rid, mode, json.dumps(config), now(), "Waiting for a worker"),
        )
        con.execute("UPDATE projects SET status='queued', updated_at=? WHERE id=?", (now(), project_id))
    return get_job(jid)


def get_job(job_id: str) -> dict | None:
    return row_dict(db().execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())


def transition(job_id: str, to: str, **fields) -> dict:
    with tx() as con:
        row = con.execute("SELECT state FROM jobs WHERE id=?", (job_id,)).fetchone()
        if row is None:
            raise KeyError(job_id)
        if to not in TRANSITIONS[row["state"]]:
            raise InvalidTransition(f"{row['state']} → {to}")
        fields["state"] = to
        if to in TERMINAL:
            fields.setdefault("finished_at", now())
        cols = ", ".join(f"{k}=?" for k in fields)
        con.execute(f"UPDATE jobs SET {cols} WHERE id=?", (*fields.values(), job_id))
    return get_job(job_id)


def update_progress(job_id: str, **fields) -> None:
    fields["heartbeat_at"] = now()
    cols = ", ".join(f"{k}=?" for k in fields)
    db().execute(f"UPDATE jobs SET {cols} WHERE id=? AND state='running'", (*fields.values(), job_id))


def request_cancel(job_id: str) -> dict:
    job = get_job(job_id)
    if job is None:
        raise KeyError(job_id)
    if job["state"] == "queued":
        job = transition(job_id, "cancelled", message="Cancelled before it started")
        _project_status(job["project_id"])
        return job
    if job["state"] == "running":
        db().execute("UPDATE jobs SET cancel_requested=1, message='Stopping…' WHERE id=?", (job_id,))
        return get_job(job_id)
    raise InvalidTransition(f"cannot cancel a {job['state']} job")


def retry(job_id: str) -> dict:
    job = get_job(job_id)
    if job is None:
        raise KeyError(job_id)
    job = transition(job_id, "queued", run_id=new_id(8), attempts=job["attempts"] + 1, error=None, error_code=None,
                     progress=None, stage=None, stage_label=None, cancel_requested=0, started_at=None,
                     finished_at=None, pid=None, message="Waiting for a worker")
    db().execute("UPDATE projects SET status='queued', updated_at=? WHERE id=?", (now(), job["project_id"]))
    return job


def is_cancel_requested(job_id: str) -> bool:
    row = db().execute("SELECT cancel_requested FROM jobs WHERE id=?", (job_id,)).fetchone()
    return bool(row and row["cancel_requested"])


def _project_status(project_id: str) -> None:
    row = db().execute("SELECT state FROM jobs WHERE project_id=? ORDER BY created_at DESC LIMIT 1", (project_id,)).fetchone()
    has_run = db().execute("SELECT 1 FROM runs WHERE project_id=? LIMIT 1", (project_id,)).fetchone()
    state = row["state"] if row else "draft"
    status = {"succeeded": "ready", "running": "processing", "queued": "queued"}.get(state)
    if status is None:
        status = "ready" if has_run else ("failed" if state == "failed" else "draft")
    db().execute("UPDATE projects SET status=?, updated_at=? WHERE id=?", (status, now(), project_id))


def sync_project_status(project_id: str) -> None:
    _project_status(project_id)


def public_job(job: dict) -> dict:
    """Shape a job row for API responses (no internals like pid/owner)."""
    keys = ["id", "project_id", "run_id", "mode", "state", "stage", "stage_label", "progress", "message", "error",
            "error_code", "attempts", "cancel_requested", "created_at", "started_at", "finished_at", "heartbeat_at"]
    out = {k: job.get(k) for k in keys}
    out["cancel_requested"] = bool(out["cancel_requested"])
    return out
