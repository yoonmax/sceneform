"""Child-process entry point: ``python -m app.workers.run_job <job_id>``.

Running each job in its own process isolates native-library crashes and
memory, and lets the supervisor enforce timeouts by killing the process.
"""

from __future__ import annotations

import json
import sys
import time
import traceback
from pathlib import Path

from ..pipeline.media import MediaError
from ..pipeline.runner import Cancelled, Context, RunConfig, run
from ..storage.db import db, now
from ..storage.files import project_dir, run_dir
from . import jobs

FRIENDLY = {
    "Camera poses couldn't be recovered": "camera_failure",
    "High-quality mode needs": "no_gpu",
}


def main(job_id: str) -> int:
    job = jobs.get_job(job_id)
    if job is None or job["state"] != "running":
        return 2
    pid = job["project_id"]
    rdir = run_dir(pid, job["run_id"])
    rdir.mkdir(parents=True, exist_ok=True)
    log_path = rdir / "events.jsonl"
    log = open(log_path, "a", buffering=1)
    last_write = {"t": 0.0}
    cancel_cache = {"t": 0.0, "v": False}

    def is_cancelled() -> bool:
        t = time.time()
        if t - cancel_cache["t"] > 0.5:
            cancel_cache["t"], cancel_cache["v"] = t, jobs.is_cancel_requested(job_id)
        return cancel_cache["v"]

    def on_event(ev: dict) -> None:
        ev = {"t": round(time.time(), 3), **ev}
        log.write(json.dumps(ev) + "\n")
        t = time.time()
        if ev["type"] == "stage":
            jobs.update_progress(job_id, stage=ev["stage"], stage_label=ev["label"], progress=None, message=ev["label"])
            last_write["t"] = t
        elif ev["type"] == "progress" and (t - last_write["t"] > 0.4 or ev.get("progress") in (0.0, 1.0)):
            jobs.update_progress(job_id, progress=ev.get("progress"), message=ev.get("message") or None)
            last_write["t"] = t

    rows = db().execute("SELECT stored_name FROM assets WHERE project_id=? ORDER BY position, created_at", (pid,)).fetchall()
    inputs = [project_dir(pid) / "inputs" / r["stored_name"] for r in rows]
    cfg_dict = {k: v for k, v in job["config"].items() if k in RunConfig.__dataclass_fields__}
    cfg_dict["mode"] = job["mode"]
    cfg = RunConfig(**cfg_dict)
    try:
        manifest = run(inputs, rdir, cfg, Context(on_event, is_cancelled))
    except Cancelled:
        jobs.transition(job_id, "cancelled", message="Cancelled", progress=None)
        jobs.sync_project_status(pid)
        return 0
    except MediaError as exc:
        _fail(job_id, pid, str(exc), "input", log)
        return 1
    except Exception as exc:  # noqa: BLE001 - every failure must be recorded
        msg = str(exc)
        code = next((c for k, c in FRIENDLY.items() if k in msg), "internal")
        log.write(json.dumps({"t": time.time(), "type": "log", "level": "error", "message": traceback.format_exc()}) + "\n")
        if code == "internal":
            msg = f"Something went wrong while {(_stage(job_id) or 'processing').replace('_', ' ')}. {msg[:300]}"
        _fail(job_id, pid, msg, code, log)
        return 1
    summary = {
        "points": manifest["pointCloud"]["stats"]["count"],
        "cameras": manifest["cameras"]["count"],
        "inputFrames": manifest["metrics"]["inputFrames"],
        "hasSplat": bool(manifest["splat"]),
        "hasMesh": bool(manifest["mesh"]),
        "quality": manifest["quality"]["score"],
        "seconds": manifest["processing"]["totalSeconds"],
        "reprojectionErrorPx": manifest["metrics"]["sparseReprojectionErrorPx"]["mean"],
        "bytes": sum(p.stat().st_size for p in (rdir / "outputs").rglob("*") if p.is_file()),
    }
    con = db()
    con.execute("INSERT INTO runs(id, project_id, job_id, mode, created_at, summary) VALUES(?,?,?,?,?,?)",
                (job["run_id"], pid, job_id, job["mode"], now(), json.dumps(summary)))
    con.execute("UPDATE projects SET latest_run=?, thumbnail=?, quality=?, updated_at=? WHERE id=?",
                (job["run_id"], f"runs/{job['run_id']}/outputs/cover.jpg", json.dumps(manifest["quality"]), now(), pid))
    jobs.transition(job_id, "succeeded", progress=1.0, message="Your scene is ready", stage="completed",
                    stage_label="Completed")
    jobs.sync_project_status(pid)
    return 0


def _stage(job_id: str) -> str | None:
    j = jobs.get_job(job_id)
    return j and j.get("stage")


def _fail(job_id, pid, message, code, log) -> None:
    log.write(json.dumps({"t": time.time(), "type": "log", "level": "error", "message": message}) + "\n")
    jobs.transition(job_id, "failed", error=message, error_code=code, message="Reconstruction failed")
    jobs.sync_project_status(pid)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
