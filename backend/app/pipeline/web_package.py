"""Package a reconstruction for the browser viewer and for export.

The output folder is self-contained and static: the public site serves the
same structure for its precomputed examples that the local API serves for
user projects.  ``manifest.json`` is the single entry point.
"""

from __future__ import annotations

import json
import shutil
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image

from ..geometry.validation import validate_cameras
from . import point_cloud as pcm
from .export import (camera_record, write_cameras_json, write_colmap_text, write_depth_u16, write_mesh,
                     write_point_ply, write_points_bin)

FRAME_MAX_SIDE = 1024
THUMB_MAX_SIDE = 256
DEPTH_MAX_SIDE = 384


def _shrink(a: np.ndarray, max_side: int) -> np.ndarray:
    import cv2

    h, w = a.shape[:2]
    s = max_side / max(h, w)
    if s >= 1:
        return a
    return cv2.resize(a, (int(round(w * s)), int(round(h * s))), interpolation=cv2.INTER_NEAREST)


def _hist(values: np.ndarray, bins: int = 20, rng=(0.0, 1.0)) -> list[int]:
    return np.histogram(values, bins=bins, range=rng)[0].astype(int).tolist()


def package(*, out_dir: Path, cfg, model, raw_model, sim, align_info, cloud, fusion, images_dir: Path, ingest,
            mesh, splat, splat_dir: Path, coverage: float, depth_device, versions: dict, timings: dict,
            registration_ratio: float, progress=None) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    for sub in ("frames", "thumbs", "depth"):
        (out_dir / sub).mkdir(exist_ok=True)

    # ------------------------------------------------------- point cloud
    dens = pcm.density(cloud.points)
    layout = write_points_bin(out_dir / "points.bin", cloud.points, cloud.colors, cloud.confidence, cloud.source_view)
    write_point_ply(out_dir / "points.ply", cloud.points, cloud.colors, cloud.confidence, cloud.normals,
                    comments=["sceneform dense point cloud", "units: relative (scale-ambiguous)"])
    sparse_mask = (model.track_lengths >= 2) & np.isfinite(model.points).all(1)
    sp_layout = write_points_bin(out_dir / "sparse.bin", model.points[sparse_mask], model.colors[sparse_mask],
                                 np.clip(1.0 - model.errors[sparse_mask] / 2.0, 0, 1))
    bounds = pcm.robust_bounds(cloud.points)

    # ----------------------------------------------------------- cameras
    reproj = []
    for i, v in enumerate(model.views):
        if v.point_ids is not None and len(v.point_ids):
            uv, _ = v.camera.project(model.points[v.point_ids])
            e = np.linalg.norm(uv - v.uv, axis=1)
            e = e[np.isfinite(e)]
            reproj.append({"mean": float(e.mean()), "median": float(np.median(e)), "observations": int(e.size)})
        else:
            reproj.append(None)
    vrep = validate_cameras([v.camera for v in model.views])
    timestamps = ingest.source.get("timestamps") if ingest.source.get("type") == "video" else None
    frame_index = {n: i for i, n in enumerate(ingest.frame_names)}
    records = []
    fusion_by_view = {fv.index: fv for fv in fusion.views}
    frames_meta = []
    for i, v in enumerate(model.views):
        if progress:
            progress((i + 1) / len(model.views) * 0.6, f"Packaging view {i + 1} of {len(model.views)}")
        src_i = frame_index.get(v.name)
        ts = timestamps[src_i] if (timestamps and src_i is not None and src_i < len(timestamps)) else None
        rec = camera_record(v.name, v.camera, i, ts)
        rec["reprojectionErrorPx"] = reproj[i]
        rec["captureIndex"] = src_i
        stem = f"{i:03d}"
        im = Image.open(images_dir / v.name).convert("RGB")
        full = im.copy()
        full.thumbnail((FRAME_MAX_SIDE, FRAME_MAX_SIDE), Image.Resampling.LANCZOS)
        full.save(out_dir / "frames" / f"{stem}.jpg", quality=86)
        th = im.copy()
        th.thumbnail((THUMB_MAX_SIDE, THUMB_MAX_SIDE), Image.Resampling.LANCZOS)
        th.save(out_dir / "thumbs" / f"{stem}.jpg", quality=80)
        rec["frame"] = f"frames/{stem}.jpg"
        rec["thumb"] = f"thumbs/{stem}.jpg"
        fm = {"index": i, "frame": rec["frame"], "thumb": rec["thumb"], "depth": None}
        fv = fusion_by_view.get(i)
        if fv is not None:
            dsmall = _shrink(fv.depth, DEPTH_MAX_SIDE)
            dmeta = write_depth_u16(out_dir / "depth" / f"{stem}.u16", dsmall)
            conf = (np.clip(_shrink(fv.confidence, DEPTH_MAX_SIDE), 0, 1) * 255).astype(np.uint8) if fv.confidence is not None else None
            if conf is not None:
                (out_dir / "depth" / f"{stem}.conf").write_bytes(conf.tobytes())
            vals = fv.depth[fv.depth > 0]
            fm["depth"] = {
                "file": f"depth/{stem}.u16",
                "confidence": f"depth/{stem}.conf" if conf is not None else None,
                **dmeta,
                "histogram": np.histogram(vals, bins=32, range=(dmeta["near"], dmeta["far"]))[0].tolist() if len(vals) else [],
                "alignment": {
                    "a": fv.alignment.a, "b": fv.alignment.b,
                    "sparsePoints": fv.alignment.total, "inliers": fv.alignment.inliers,
                    "medianRelErrorGlobal": fv.alignment.median_rel_error_global,
                    "medianRelErrorLocal": fv.alignment.median_rel_error_local,
                },
            }
        frames_meta.append(fm)
        records.append(rec)
    world = {
        "up": [0, 1, 0],
        "handedness": "right",
        "units": "relative",
        "fromColmap": sim.matrix().tolist(),
        "alignment": align_info,
    }
    write_cameras_json(out_dir / "cameras.json", records, world)
    write_colmap_text(out_dir / "colmap", [v.name for v in model.views], [v.camera for v in model.views],
                      model.points[sparse_mask], model.colors[sparse_mask])

    # -------------------------------------------------------------- mesh
    mesh_meta = None
    if mesh is not None:
        if progress:
            progress(0.7, "Writing mesh")
        write_mesh(out_dir / "mesh.glb", mesh.vertices, mesh.faces, mesh.colors)
        write_mesh(out_dir / "mesh.obj", mesh.vertices, mesh.faces, mesh.colors)
        mesh_meta = {"file": "mesh.glb", "obj": "mesh.obj", "diagnostics": mesh.diagnostics,
                     "note": "Approximate surface from depth fusion. Unobserved sides remain open."}

    # ------------------------------------------------------------- splat
    splat_meta = None
    if splat is not None:
        if progress:
            progress(0.8, "Preparing the splat for the web")
        from .gaussian_splat import prune_for_web, read_splat_ply, splat_stats

        raw = splat_dir / splat["raw_ply"]
        # Remove floaters far outside the scene (measured in the COLMAP frame).
        r_colmap = 3.0 * bounds["radius"] / sim.s
        info = prune_for_web(raw, out_dir / "splat.ply", sim=None,
                             max_splats=getattr(cfg, "web_max_splats", None) or splat["max_splats_web"],
                             keep_sh=getattr(cfg, "web_keep_sh", True), bounds_radius=r_colmap)
        stats = splat_stats(read_splat_ply(out_dir / "splat.ply"))
        splat_meta = {
            "file": "splat.ply",
            "format": "3dgs-ply",
            # The splat stays in the trainer's (COLMAP) frame so that its
            # spherical harmonics remain valid; the viewer applies this matrix.
            "transform": sim.matrix().T.ravel().tolist(),  # column-major for three.js Matrix4.fromArray
            "training": {k: v for k, v in splat.items() if k not in ("raw_ply",)},
            "pruning": info,
            "stats": stats,
        }

    # ---------------------------------------------------------- manifest
    conf = cloud.confidence if cloud.confidence is not None else np.ones(len(cloud))
    sparse_stats = model.reprojection_stats()
    thumb = out_dir / "thumbs" / "000.jpg"
    if thumb.exists():
        shutil.copy(thumb, out_dir / "cover.jpg")
    manifest = {
        "schema": "sceneform.scene/1",
        "id": uuid.uuid4().hex[:12],
        "title": cfg.title,
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "mode": cfg.mode,
        "cover": "cover.jpg",
        "source": ingest.source,
        "units": {"kind": "relative",
                  "note": "Reconstruction units are scale-ambiguous. Set a reference length to measure."},
        "world": {"up": [0, 1, 0], "file": "cameras.json"},
        "bounds": bounds,
        "pointCloud": {
            "file": "points.bin", "ply": "points.ply", "layout": layout,
            "stats": {
                "count": len(cloud),
                "confidenceHistogram": _hist(conf),
                "densityHistogram": _hist(dens),
                "voxelSize": next((l["step"] for l in reversed(cloud.log) if "voxel" in l["step"]), None),
                "filtering": cloud.log,
            },
            "defaultConfidence": 0.5,
        },
        "sparse": {"file": "sparse.bin", "layout": sp_layout, "count": int(sparse_mask.sum())},
        "cameras": {"file": "cameras.json", "count": len(records), "colmap": "colmap/"},
        "frames": frames_meta,
        "mesh": mesh_meta,
        "splat": splat_meta,
        "quality": ingest.quality,
        "metrics": {
            "registeredViews": len(model.views),
            "inputFrames": len(ingest.frame_names),
            "registrationRatio": registration_ratio,
            "unregistered": raw_model.unregistered,
            "sparsePoints": int(len(model.points)),
            "sparseReprojectionErrorPx": sparse_stats,
            "meanTrackLength": float(model.track_lengths.mean()) if len(model.track_lengths) else None,
            "coverageDeg": coverage,
            "depthFusion": fusion.stats,
            "depthViewsSkipped": fusion.skipped,
            "cameraValidation": {"ok": vrep.ok, "errors": vrep.errors, "warnings": vrep.warnings},
            "splatHeldout": splat_meta["training"].get("heldout_metrics") if splat_meta else None,
        },
        "processing": {
            "pipeline": "sceneform",
            "sfm": "COLMAP incremental mapping (pycolmap)",
            "depth": f"Depth Anything V2 Small, aligned to SfM + multi-view consistency (device: {depth_device})",
            "splat": f"{splat['trainer']} ({splat['device']})" if splat else None,
            "versions": versions,
            "config": asdict(cfg),
        },
        "license": None,
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=1))
    return manifest
