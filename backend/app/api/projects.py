"""Project workspace endpoints."""

from __future__ import annotations

import json
import shutil

from fastapi import APIRouter, Depends, HTTPException

from ..config import settings
from ..schemas.models import EditsPut, ProjectCreate, ProjectPatch
from ..storage.db import db, now, row_dict, tx
from ..storage.files import delete_project_files, dir_size, new_id, project_dir, sign
from ..workers.jobs import public_job
from .deps import owned_project, owner

router = APIRouter(prefix="/api/projects", tags=["projects"])


def project_view(p: dict) -> dict:
    con = db()
    assets = con.execute("SELECT kind, COUNT(*) n, SUM(bytes) b FROM assets WHERE project_id=? GROUP BY kind",
                         (p["id"],)).fetchall()
    job = con.execute("SELECT * FROM jobs WHERE project_id=? ORDER BY created_at DESC LIMIT 1", (p["id"],)).fetchone()
    runs = [row_dict(r) for r in con.execute(
        "SELECT id, job_id, mode, created_at, summary FROM runs WHERE project_id=? ORDER BY created_at DESC", (p["id"],))]
    sig = sign(p["id"])
    return {
        "id": p["id"],
        "name": p["name"],
        "createdAt": p["created_at"],
        "updatedAt": p["updated_at"],
        "expiresAt": p["expires_at"],
        "status": p["status"],
        "inputType": p["input_type"],
        "inputCount": sum(a["n"] for a in assets),
        "inputBytes": sum(a["b"] or 0 for a in assets),
        "settings": p["settings"],
        "quality": p["quality"],
        "latestRun": p["latest_run"],
        "thumbnail": f"/api/projects/{p['id']}/files/{p['thumbnail']}?sig={sig}" if p["thumbnail"] else None,
        "job": public_job(row_dict(job)) if job else None,
        "runs": [{**r, "baseUrl": f"/api/projects/{p['id']}/files/runs/{r['id']}/outputs/", "sig": sig} for r in runs],
        "sig": sig,
    }


@router.post("")
def create_project(body: ProjectCreate, who: str = Depends(owner)):
    count = db().execute("SELECT COUNT(*) c FROM projects WHERE owner=?", (who,)).fetchone()["c"]
    if count >= 50:
        raise HTTPException(429, "You've reached the limit of 50 projects. Delete some to make room.")
    pid = new_id(16)
    t = now()
    db().execute(
        "INSERT INTO projects(id, owner, name, created_at, updated_at, expires_at, status) VALUES(?,?,?,?,?,?, 'draft')",
        (pid, who, body.name, t, t, t + settings.retention_hours * 3600),
    )
    (project_dir(pid) / "inputs").mkdir(parents=True, exist_ok=True)
    return project_view(owned_project(pid, who))


@router.get("")
def list_projects(who: str = Depends(owner)):
    rows = db().execute("SELECT * FROM projects WHERE owner=? ORDER BY updated_at DESC", (who,)).fetchall()
    return {"projects": [project_view(row_dict(r)) for r in rows], "retentionHours": settings.retention_hours}


@router.get("/{project_id}")
def get_project(project_id: str, who: str = Depends(owner)):
    return project_view(owned_project(project_id, who))


@router.patch("/{project_id}")
def update_project(project_id: str, body: ProjectPatch, who: str = Depends(owner)):
    p = owned_project(project_id, who)
    if body.name is not None:
        db().execute("UPDATE projects SET name=?, updated_at=? WHERE id=?", (" ".join(body.name.split()), now(), p["id"]))
    if body.asset_order is not None:
        with tx() as con:
            for i, aid in enumerate(body.asset_order):
                con.execute("UPDATE assets SET position=? WHERE id=? AND project_id=?", (i, aid, p["id"]))
    return project_view(owned_project(project_id, who))


@router.delete("/{project_id}")
def delete_project(project_id: str, who: str = Depends(owner)):
    p = owned_project(project_id, who)
    running = db().execute("SELECT id FROM jobs WHERE project_id=? AND state IN ('queued','running')", (p["id"],)).fetchall()
    for r in running:
        db().execute("UPDATE jobs SET cancel_requested=1 WHERE id=?", (r["id"],))
    db().execute("DELETE FROM projects WHERE id=?", (p["id"],))
    delete_project_files(p["id"])
    return {"deleted": True, "note": "Uploads, frames and reconstructions were permanently removed."}


@router.post("/{project_id}/duplicate")
def duplicate_project(project_id: str, who: str = Depends(owner)):
    """Copy inputs and settings into a new project (outputs are not copied)."""
    p = owned_project(project_id, who)
    nid = new_id(16)
    t = now()
    db().execute(
        "INSERT INTO projects(id, owner, name, created_at, updated_at, expires_at, status, input_type, settings, quality)"
        " VALUES(?,?,?,?,?,?, 'draft', ?, ?, ?)",
        (nid, who, (p["name"] + " copy")[:80], t, t, t + settings.retention_hours * 3600, p["input_type"],
         json.dumps(p["settings"]), json.dumps(p["quality"]) if p["quality"] else None),
    )
    src, dst = project_dir(p["id"]), project_dir(nid)
    (dst / "inputs").mkdir(parents=True, exist_ok=True)
    for sub in ("inputs", "thumbs"):
        if (src / sub).exists():
            shutil.copytree(src / sub, dst / sub, dirs_exist_ok=True, copy_function=_link_or_copy)
    for a in db().execute("SELECT * FROM assets WHERE project_id=?", (p["id"],)).fetchall():
        db().execute(
            "INSERT INTO assets(id, project_id, kind, original_name, stored_name, bytes, sha256, width, height, duration, position, created_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (new_id(12), nid, a["kind"], a["original_name"], a["stored_name"], a["bytes"], a["sha256"], a["width"],
             a["height"], a["duration"], a["position"], t),
        )
    return project_view(owned_project(nid, who))


def _link_or_copy(s, d):
    import os

    try:
        os.link(s, d)
    except OSError:
        shutil.copy2(s, d)


@router.get("/{project_id}/storage")
def storage_usage(project_id: str, who: str = Depends(owner)):
    p = owned_project(project_id, who)
    return {"bytes": dir_size(project_dir(p["id"]))}


@router.get("/{project_id}/runs/{run_id}/edits")
def get_edits(project_id: str, run_id: str, who: str = Depends(owner)):
    p = owned_project(project_id, who)
    row = db().execute("SELECT edits FROM runs WHERE id=? AND project_id=?", (run_id, p["id"])).fetchone()
    if row is None:
        raise HTTPException(404, "Run not found.")
    return json.loads(row["edits"])


@router.put("/{project_id}/runs/{run_id}/edits")
def put_edits(project_id: str, run_id: str, body: EditsPut, who: str = Depends(owner)):
    """Edits are an operation list stored beside — never applied to — the
    original reconstruction, so they can always be undone."""
    p = owned_project(project_id, who)
    cur = db().execute("UPDATE runs SET edits=? WHERE id=? AND project_id=?",
                       (body.model_dump_json(), run_id, p["id"]))
    if cur.rowcount == 0:
        raise HTTPException(404, "Run not found.")
    return body.model_dump()
