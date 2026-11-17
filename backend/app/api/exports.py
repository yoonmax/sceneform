"""Signed file serving and on-demand exports."""

from __future__ import annotations

import io
import json
import re
import zipfile

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, Response
from PIL import Image

from ..pipeline.edits import apply_edits, total_transform
from ..pipeline.export import read_points_bin, write_mesh, write_pcd, write_point_ply
from ..storage.db import db
from ..storage.files import project_dir, run_dir, safe_join
from .deps import signed_project

router = APIRouter(tags=["exports"])
ALLOWED = [re.compile(p) for p in (r"^thumbs/[0-9a-f]+\.jpg$", r"^analysis/\d+\.jpg$", r"^inputs/[0-9a-f]+\.\w+$",
                                   r"^runs/[0-9a-f]+/outputs/.+$")]


@router.get("/api/projects/{project_id}/files/{path:path}")
def get_file(path: str, project: dict = Depends(signed_project)):
    if not any(p.match(path) for p in ALLOWED) or ".." in path:
        raise HTTPException(404, "Not found.")
    try:
        target = safe_join(project_dir(project["id"]), path)
    except PermissionError:
        raise HTTPException(404, "Not found.")
    if not target.is_file():
        raise HTTPException(404, "Not found.")
    media = None
    if target.suffix in (".bin", ".u16", ".conf"):
        media = "application/octet-stream"
    return FileResponse(target, media_type=media, headers={"Cache-Control": "private, max-age=3600",
                                                           "X-Content-Type-Options": "nosniff"})


def _slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s[:40] or "scene"


KINDS = {
    "points-ply": ("points", "ply"), "points-pcd": ("points", "pcd"), "sparse-ply": ("sparse", "ply"),
    "cameras-json": ("cameras", "json"), "colmap-zip": ("colmap", "zip"), "frames-zip": ("frames", "zip"),
    "depth-zip": ("depth", "zip"), "mesh-glb": ("mesh", "glb"), "mesh-obj": ("mesh", "obj"),
    "splat-ply": ("splat", "ply"), "report-json": ("report", "json"), "report-md": ("report", "md"),
}


@router.get("/api/projects/{project_id}/runs/{run_id}/export/{kind}")
def export(run_id: str, kind: str, confidence: float = Query(default=0.5, ge=0, le=1), apply_edits_: bool = Query(True, alias="edits"),
           project: dict = Depends(signed_project)):
    if kind not in KINDS:
        raise HTTPException(404, "Unknown export type.")
    row = db().execute("SELECT * FROM runs WHERE id=? AND project_id=?", (run_id, project["id"])).fetchone()
    if row is None:
        raise HTTPException(404, "Run not found.")
    out = run_dir(project["id"], run_id) / "outputs"
    exp = run_dir(project["id"], run_id) / "exports"
    exp.mkdir(exist_ok=True)
    manifest = json.loads((out / "manifest.json").read_text())
    ops = json.loads(row["edits"]).get("ops", []) if apply_edits_ else []
    base, ext = KINDS[kind]
    fname = f"sceneform-{_slug(project['name'])}-{base}.{ext}"
    dest = exp / fname

    if kind in ("points-ply", "points-pcd", "sparse-ply"):
        src = manifest["pointCloud"] if kind != "sparse-ply" else manifest["sparse"]
        d = read_points_bin(out / src["file"], src["layout"])
        P, keep, unit = apply_edits(d["points"], ops)
        if "confidence" in d and kind != "sparse-ply":
            keep &= d["confidence"] >= confidence
        comments = [f"sceneform {base} export", f"units: {unit['kind']}" + (f" ({unit['unit']})" if unit["unit"] else ""),
                    f"confidence >= {confidence:.2f}" if kind != "sparse-ply" else "sparse SfM points"]
        if ext == "ply":
            write_point_ply(dest, P[keep], d["colors"][keep], d.get("confidence")[keep] if "confidence" in d else None,
                            comments=comments)
        else:
            write_pcd(dest, P[keep], d["colors"][keep])
    elif kind == "cameras-json":
        cams = json.loads((out / "cameras.json").read_text())
        cams["editTransform"] = total_transform(ops).tolist()
        cams["note"] = ("Poses are in the reconstruction frame (world.fromColmap maps COLMAP's frame to it). "
                        "editTransform is the user's edit stack, not applied to the poses.")
        dest.write_text(json.dumps(cams, indent=1))
    elif kind == "colmap-zip":
        _zip_dir(out / "colmap", dest, "colmap/")
    elif kind == "frames-zip":
        _zip_dir(out / "frames", dest, "frames/")
    elif kind == "depth-zip":
        buf = zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED)
        meta = []
        for f in manifest["frames"]:
            dm = f.get("depth")
            if not dm:
                continue
            q = np.frombuffer((out / dm["file"]).read_bytes(), "<u2").reshape(dm["height"], dm["width"])
            png = io.BytesIO()
            Image.fromarray(q.astype(np.uint16)).save(png, format="PNG")
            name = f"depth_{f['index']:03d}.png"
            buf.writestr(name, png.getvalue())
            meta.append({"image": name, "frame": f["frame"], "near": dm["near"], "far": dm["far"], "invalid": 65535,
                         "decode": "depth = near + value / 65534 * (far - near)", "units": "relative"})
        buf.writestr("depth.json", json.dumps(meta, indent=1))
        buf.close()
    elif kind in ("mesh-glb", "mesh-obj"):
        if not manifest.get("mesh"):
            raise HTTPException(404, "This reconstruction has no mesh.")
        import trimesh

        m = trimesh.load(out / manifest["mesh"]["file"], force="mesh", process=False)
        T = total_transform(ops)
        V = np.asarray(m.vertices) @ T[:3, :3].T + T[:3, 3]
        cols = m.visual.vertex_colors[:, :3] if hasattr(m.visual, "vertex_colors") else None
        write_mesh(dest, V, np.asarray(m.faces), cols)
    elif kind == "splat-ply":
        if not manifest.get("splat"):
            raise HTTPException(404, "This reconstruction has no Gaussian splat.")
        return FileResponse(out / manifest["splat"]["file"], filename=fname, media_type="application/octet-stream")
    elif kind == "report-json":
        dest.write_text(json.dumps(_report(manifest, project, ops), indent=1))
    elif kind == "report-md":
        dest.write_text(_report_md(_report(manifest, project, ops)))
    return FileResponse(dest, filename=fname, media_type="application/octet-stream")


def _zip_dir(src, dest, prefix):
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(src.rglob("*")):
            if f.is_file():
                z.write(f, prefix + str(f.relative_to(src)))


def _report(manifest, project, ops) -> dict:
    return {
        "project": project["name"],
        "createdAt": manifest["createdAt"],
        "mode": manifest["mode"],
        "source": manifest["source"],
        "inputQuality": manifest["quality"],
        "metrics": manifest["metrics"],
        "pointCloud": manifest["pointCloud"]["stats"],
        "mesh": manifest["mesh"]["diagnostics"] if manifest.get("mesh") else None,
        "splat": manifest["splat"] if manifest.get("splat") else None,
        "processing": manifest["processing"],
        "edits": ops,
        "units": manifest["units"],
        "disclaimer": ("Confidence values are geometric-consistency scores, not real-world accuracy. "
                       "Distances are relative unless a reference length was set."),
    }


def _report_md(r: dict) -> str:
    m = r["metrics"]
    rep = m["sparseReprojectionErrorPx"]
    lines = [
        f"# sceneform report — {r['project']}", "",
        f"*Created {r['createdAt']} · mode: {r['mode']}*", "",
        "## Input", f"- Source: {r['source'].get('type')}", f"- Input quality score: {r['inputQuality']['score']}/100 ({r['inputQuality']['grade']}, heuristic)",
    ]
    lines += [f"  - {f['message']}" for f in r["inputQuality"]["findings"]]
    lines += ["", "## Cameras", f"- Registered views: {m['registeredViews']} of {m['inputFrames']}",
              f"- Sparse points: {m['sparsePoints']}",
              f"- Reprojection error: mean {rep['mean']:.2f}px, median {rep['median']:.2f}px, p90 {rep['p90']:.2f}px" if rep["mean"] is not None else "- Reprojection error: n/a",
              f"- Azimuthal coverage: {m['coverageDeg']:.0f}°", "", "## Dense geometry",
              f"- Points: {r['pointCloud']['count']:,}",
              f"- Depth views fused: {m['depthFusion']['views_fused']} (skipped {m['depthFusion']['views_skipped']})"]
    if r.get("mesh"):
        d = r["mesh"]
        lines += [f"- Mesh: {d['faces']:,} faces, {d['components']} components, watertight: {d['watertight']}"]
    if r.get("splat"):
        s = r["splat"]
        lines += ["", "## Gaussian splat", f"- Trainer: {s['training']['trainer']} on {s['training']['device']}, {s['training']['iterations']:,} steps",
                  f"- Splats: {s['stats']['count']:,}"]
        h = s["training"].get("heldout_metrics") or {}
        if "psnr" in h:
            lines.append(f"- Held-out views: PSNR {h['psnr']:.2f} dB, SSIM {h.get('ssim', float('nan')):.3f} ({h.get('num_test', '?')} views)")
    lines += ["", "## Notes", r["disclaimer"], ""]
    return "\n".join(lines)
