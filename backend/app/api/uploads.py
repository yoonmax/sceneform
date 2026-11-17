"""Uploads, the input contact sheet, and pre-flight quality analysis."""

from __future__ import annotations

import hashlib
import os

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, UploadFile
from PIL import Image

from ..config import settings
from ..pipeline.frame_selection import SelectionParams, select_keyframes
from ..pipeline.media import (IMAGE_KINDS, UNSUPPORTED_HINTS, VIDEO_KINDS, MediaError, decode_video_frames,
                              load_image, probe_video, sniff)
from ..pipeline.quality import build_report, frame_metrics, orb_features, pair_metrics
from ..storage.db import db, now
from ..storage.files import new_id, project_dir, sign
from .deps import owned_project, owner

router = APIRouter(prefix="/api/projects/{project_id}", tags=["uploads"])
EXT = {"jpeg": "jpg", "png": "png", "webp": "webp", "mp4": "mp4", "mov": "mov", "webm": "webm"}
CHUNK = 1 << 20


def _asset_view(pid: str, a, sig: str) -> dict:
    return {
        "id": a["id"], "kind": a["kind"], "name": a["original_name"], "bytes": a["bytes"],
        "width": a["width"], "height": a["height"], "duration": a["duration"], "position": a["position"],
        "thumb": f"/api/projects/{pid}/files/thumbs/{a['id']}.jpg?sig={sig}",
        "url": f"/api/projects/{pid}/files/inputs/{a['stored_name']}?sig={sig}",
    }


@router.get("/assets")
def list_assets(project_id: str, who: str = Depends(owner)):
    p = owned_project(project_id, who)
    sig = sign(p["id"])
    rows = db().execute("SELECT * FROM assets WHERE project_id=? ORDER BY position, created_at", (p["id"],)).fetchall()
    return {"assets": [_asset_view(p["id"], a, sig) for a in rows]}


@router.post("/uploads")
async def upload(project_id: str, files: list[UploadFile], who: str = Depends(owner)):
    p = owned_project(project_id, who)
    pdir = project_dir(p["id"])
    inputs, thumbs = pdir / "inputs", pdir / "thumbs"
    inputs.mkdir(parents=True, exist_ok=True)
    thumbs.mkdir(exist_ok=True)
    existing = db().execute("SELECT kind, bytes, sha256 FROM assets WHERE project_id=?", (p["id"],)).fetchall()
    total = sum(r["bytes"] for r in existing)
    known = {r["sha256"] for r in existing}
    kinds = {r["kind"] for r in existing}
    count = len(existing)
    added, rejected = [], []
    for f in files:
        tmp = inputs / f".partial-{new_id(8)}"
        h = hashlib.sha256()
        size, head = 0, b""
        try:
            with open(tmp, "wb") as out:
                while chunk := await f.read(CHUNK):
                    if not head:
                        head = chunk[:64]
                        kind = sniff(head)
                        if kind not in IMAGE_KINDS | VIDEO_KINDS:
                            raise MediaError(UNSUPPORTED_HINTS.get(kind or "", "Unsupported file type. Use MP4, MOV, WebM, JPEG, PNG or WebP."))
                    size += len(chunk)
                    limit = settings.max_image_bytes if kind in IMAGE_KINDS else settings.max_upload_bytes
                    if size > limit or total + size > settings.max_upload_bytes:
                        raise MediaError(f"File is too large (limit {limit // (1 << 20)} MB per file, "
                                         f"{settings.max_upload_bytes // (1 << 20)} MB per project).")
                    h.update(chunk)
                    out.write(chunk)
            if size == 0:
                raise MediaError("This file is empty.")
            group = "video" if kind in VIDEO_KINDS else "image"
            if (group == "video" and (kinds or count)) or (group == "image" and "video" in kinds):
                raise MediaError("A project takes either one video or a set of photos.")
            if group == "image" and count >= settings.max_images:
                raise MediaError(f"A project can hold at most {settings.max_images} photos.")
            digest = h.hexdigest()
            if digest in known:
                raise MediaError("This file was already uploaded.")
            aid = new_id(12)
            stored = f"{new_id(8)}.{EXT[kind]}"
            final = inputs / stored
            os.replace(tmp, final)
            width = height = duration = None
            try:
                if group == "image":
                    img, info = load_image(final, max_side=320)
                    width, height = info.width, info.height
                    with Image.open(final) as im:
                        width, height = im.size
                    Image.fromarray(img).save(thumbs / f"{aid}.jpg", quality=80)
                else:
                    vi = probe_video(final)
                    if vi.duration > settings.max_video_seconds:
                        raise MediaError(f"Videos can be at most {settings.max_video_seconds:.0f} seconds long.")
                    width, height, duration = vi.width, vi.height, vi.duration
                    first = next(decode_video_frames(final, 1.0, 320, min(0.5, vi.duration / 2), None), None)
                    if first is None:
                        raise MediaError("We couldn't decode any frames from this video.")
                    Image.fromarray(first[1]).save(thumbs / f"{aid}.jpg", quality=80)
            except MediaError:
                final.unlink(missing_ok=True)
                raise
            from ..pipeline.media import safe_filename

            db().execute(
                "INSERT INTO assets(id, project_id, kind, original_name, stored_name, bytes, sha256, width, height, duration, position, created_at)"
                " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (aid, p["id"], group, safe_filename(f.filename or ""), stored, size, digest, width, height, duration, count, now()),
            )
            known.add(digest)
            kinds.add(group)
            total += size
            count += 1
            added.append(aid)
        except MediaError as exc:
            rejected.append({"name": f.filename, "reason": str(exc)})
        finally:
            tmp.unlink(missing_ok=True)
            await f.close()
    if added:
        db().execute("UPDATE projects SET input_type=?, updated_at=? WHERE id=?",
                     ("video" if "video" in kinds else "photos", now(), p["id"]))
    sig = sign(p["id"])
    rows = db().execute("SELECT * FROM assets WHERE project_id=? ORDER BY position, created_at", (p["id"],)).fetchall()
    return {"added": added, "rejected": rejected, "assets": [_asset_view(p["id"], a, sig) for a in rows]}


@router.delete("/assets/{asset_id}")
def delete_asset(project_id: str, asset_id: str, who: str = Depends(owner)):
    p = owned_project(project_id, who)
    a = db().execute("SELECT * FROM assets WHERE id=? AND project_id=?", (asset_id, p["id"])).fetchone()
    if a is None:
        raise HTTPException(404, "File not found.")
    db().execute("DELETE FROM assets WHERE id=?", (asset_id,))
    shared = db().execute("SELECT 1 FROM assets WHERE stored_name=?", (a["stored_name"],)).fetchone()
    if not shared:
        (project_dir(p["id"]) / "inputs" / a["stored_name"]).unlink(missing_ok=True)
    (project_dir(p["id"]) / "thumbs" / f"{asset_id}.jpg").unlink(missing_ok=True)
    left = db().execute("SELECT COUNT(*) c FROM assets WHERE project_id=?", (p["id"],)).fetchone()["c"]
    if not left:
        db().execute("UPDATE projects SET input_type=NULL WHERE id=?", (p["id"],))
    return {"deleted": asset_id}


@router.post("/analyze")
def analyze(project_id: str, sample_fps: float = 2.0, trim_start: float = 0.0, trim_end: float | None = None,
            who: str = Depends(owner)):
    """Pre-flight input check. Heuristic; nothing is reconstructed here."""
    p = owned_project(project_id, who)
    pdir = project_dir(p["id"])
    rows = db().execute("SELECT * FROM assets WHERE project_id=? ORDER BY position, created_at", (p["id"],)).fetchall()
    if not rows:
        raise HTTPException(400, "Upload a video or some photos first.")
    sig = sign(p["id"])
    try:
        if rows[0]["kind"] == "video":
            a = rows[0]
            frames, stamps = [], []
            fps = float(np.clip(sample_fps, 0.5, 6))
            for ts, fr in decode_video_frames(pdir / "inputs" / a["stored_name"], fps, 640, trim_start, trim_end):
                frames.append(fr)
                stamps.append(ts)
                if len(frames) >= 400:
                    break
            if len(frames) < 3:
                raise MediaError("The selected part of the video is too short.")
            sel = select_keyframes(frames, stamps, SelectionParams())
            cand_dir = pdir / "analysis"
            cand_dir.mkdir(exist_ok=True)
            for old in cand_dir.glob("*.jpg"):
                old.unlink()
            for c in sel.candidates:
                im = Image.fromarray(frames[c.index])
                im.thumbnail((240, 240))
                im.save(cand_dir / f"{c.index:04d}.jpg", quality=78)
            metrics = [sel.candidates[i].metrics for i in sel.selected]
            report = build_report(metrics, sel.pairs, a["width"] or 0, a["height"] or 0).as_dict()
            candidates = sel.as_dict()["candidates"]
            for c in candidates:
                c["thumb"] = f"/api/projects/{p['id']}/files/analysis/{c['index']:04d}.jpg?sig={sig}"
            out = {"type": "video", "report": report, "candidates": candidates, "selected": sel.selected}
        else:
            imgs, ok_rows = [], []
            for a in rows:
                try:
                    img, _ = load_image(pdir / "inputs" / a["stored_name"], max_side=640)
                except MediaError:
                    continue
                imgs.append(img)
                ok_rows.append(a)
            metrics = [frame_metrics(im) for im in imgs]
            feats = [orb_features(im) for im in imgs]
            pairs = [pair_metrics(x, y) for x, y in zip(feats, feats[1:])]
            report = build_report(metrics, pairs, min(r["width"] for r in ok_rows), min(r["height"] for r in ok_rows)).as_dict()
            out = {"type": "photos", "report": report,
                   "assets": [{"id": a["id"], "flags": report["frameFlags"][i], "sharpness": round(metrics[i].sharpness, 1)}
                              for i, a in enumerate(ok_rows)]}
    except MediaError as exc:
        raise HTTPException(422, str(exc))
    import json

    db().execute("UPDATE projects SET quality=?, updated_at=? WHERE id=?", (json.dumps(out["report"]), now(), p["id"]))
    return out
