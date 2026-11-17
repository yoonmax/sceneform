"""Structure-from-Motion through COLMAP (pycolmap bindings, BSD-3-Clause).

COLMAP is the mature, production SfM system; sceneform drives it and then
converts the result into its own :class:`SparseModel`.  After mapping, images
are undistorted to an ideal pinhole model so every downstream consumer
(depth fusion, splat training, the browser viewer) can assume K[R|t].
"""

from __future__ import annotations

import shutil
import threading
from pathlib import Path
from typing import Callable

import numpy as np

from ..geometry.cameras import PinholeCamera
from .sparse_model import SparseModel, View

ProgressFn = Callable[[str, float | None, str], None]


class SfMError(RuntimeError):
    pass


def _watch_cancel(token, is_cancelled: Callable[[], bool], stop: threading.Event) -> None:
    while not stop.wait(0.5):
        if is_cancelled():
            token.cancel()
            return


def run_colmap(
    frames_dir: Path,
    work_dir: Path,
    image_names: list[str],
    *,
    single_camera: bool = True,
    focal_px: float | None = None,
    sequential: bool = False,
    max_features: int = 6000,
    refine_principal_point: bool = False,
    progress: ProgressFn | None = None,
    is_cancelled: Callable[[], bool] = lambda: False,
) -> tuple[SparseModel, Path]:
    """Run feature extraction, matching, incremental mapping, undistortion.

    Returns the sparse model (pinhole, undistorted) and the directory holding
    a COLMAP-format undistorted dataset (``images/`` + ``sparse/``) that
    splat trainers can consume directly.
    """
    import pycolmap

    progress = progress or (lambda *a: None)
    work_dir.mkdir(parents=True, exist_ok=True)
    db = work_dir / "database.db"
    if db.exists():
        db.unlink()
    token = pycolmap.CancellationToken()
    stop = threading.Event()
    watcher = threading.Thread(target=_watch_cancel, args=(token, is_cancelled, stop), daemon=True)
    watcher.start()
    try:
        progress("features", None, f"Detecting SIFT features in {len(image_names)} images")
        reader = pycolmap.ImageReaderOptions()
        reader.camera_model = "SIMPLE_RADIAL"
        if focal_px:
            reader.default_focal_length_factor = 1.2  # fallback; explicit params below win
        ext = pycolmap.FeatureExtractionOptions()
        ext.sift.max_num_features = max_features
        ext.max_image_size = 2000
        pycolmap.extract_features(
            db, frames_dir, image_names=image_names,
            camera_mode=pycolmap.CameraMode.SINGLE if single_camera else pycolmap.CameraMode.AUTO,
            reader_options=reader, extraction_options=ext, device=pycolmap.Device.cpu,
            cancellation_token=token,
        )
        if token.is_cancelled:
            raise SfMError("cancelled")
        if focal_px:
            _apply_focal_prior(db, focal_px)

        progress("matching", None, "Matching features between views")
        mopts = pycolmap.FeatureMatchingOptions()
        mopts.use_gpu = False
        if sequential:
            pair = pycolmap.SequentialPairingOptions()
            pair.overlap = 12
            pair.quadratic_overlap = True
            pycolmap.match_sequential(db, matching_options=mopts, pairing_options=pair,
                                      device=pycolmap.Device.cpu, cancellation_token=token)
        else:
            pycolmap.match_exhaustive(db, matching_options=mopts, device=pycolmap.Device.cpu,
                                      cancellation_token=token)
        if token.is_cancelled:
            raise SfMError("cancelled")

        progress("mapping", 0.0, "Recovering camera poses")
        sparse_dir = work_dir / "sparse"
        if sparse_dir.exists():
            shutil.rmtree(sparse_dir)
        sparse_dir.mkdir()
        opts = pycolmap.IncrementalPipelineOptions()
        opts.ba_refine_principal_point = refine_principal_point
        opts.num_threads = -1
        opts.random_seed = 0
        registered = {"n": 0}

        def on_next():
            registered["n"] += 1
            progress("mapping", min(1.0, registered["n"] / max(1, len(image_names))),
                     f"Registered {registered['n']} of {len(image_names)} views")

        recs = pycolmap.incremental_mapping(db, frames_dir, sparse_dir, options=opts,
                                            next_image_callback=on_next, cancellation_token=token)
        if token.is_cancelled:
            raise SfMError("cancelled")
        if not recs:
            raise SfMError(
                "Camera poses couldn't be recovered. The views may not overlap enough, "
                "or the scene may lack texture."
            )
        best_id = max(recs, key=lambda k: recs[k].num_reg_images())
        rec = recs[best_id]
        rec_dir = sparse_dir / str(best_id)

        progress("undistort", None, "Undistorting images to an ideal pinhole model")
        und = work_dir / "undistorted"
        if und.exists():
            shutil.rmtree(und)
        pycolmap.undistort_images(und, rec_dir, frames_dir, output_type="COLMAP")
        rec_u = pycolmap.Reconstruction(und / "sparse")
        model = reconstruction_to_model(rec_u, image_names)
        model.stats["colmap"] = {
            "num_models": len(recs),
            "registered": rec.num_reg_images(),
            "mean_reprojection_error_px": float(rec.compute_mean_reprojection_error()),
            "mean_track_length": float(rec.compute_mean_track_length()),
            "distorted_camera": {cid: {"model": c.model_name, "params": list(map(float, c.params))}
                                 for cid, c in rec.cameras.items()},
        }
        return model, und
    finally:
        stop.set()


def _apply_focal_prior(db: Path, focal_px: float) -> None:
    """Seed every camera's focal length with a (validated) EXIF prior."""
    import sqlite3

    con = sqlite3.connect(db)
    try:
        rows = con.execute("SELECT camera_id, params, width, height FROM cameras").fetchall()
        for cid, blob, w, h in rows:
            params = np.frombuffer(blob, dtype=np.float64).copy()
            params[0] = focal_px
            con.execute("UPDATE cameras SET params=?, prior_focal_length=1 WHERE camera_id=?",
                        (params.tobytes(), cid))
        con.commit()
    finally:
        con.close()


def reconstruction_to_model(rec, image_names: list[str]) -> SparseModel:
    order = {n: i for i, n in enumerate(image_names)}
    p3d_ids = sorted(rec.points3D.keys())
    index_of = {pid: i for i, pid in enumerate(p3d_ids)}
    pts = np.array([rec.points3D[p].xyz for p in p3d_ids], dtype=np.float64).reshape(-1, 3)
    cols = np.array([rec.points3D[p].color for p in p3d_ids], dtype=np.uint8).reshape(-1, 3)
    errs = np.array([rec.points3D[p].error for p in p3d_ids], dtype=np.float64)
    tl = np.array([rec.points3D[p].track.length() for p in p3d_ids], dtype=np.int32)

    views = []
    for img in sorted(rec.images.values(), key=lambda im: order.get(im.name, 1 << 30)):
        if not img.has_pose:
            continue
        cam = rec.cameras[img.camera_id]
        K = np.asarray(cam.calibration_matrix(), dtype=np.float64)
        pose = img.cam_from_world()
        R = np.asarray(pose.rotation.matrix(), dtype=np.float64)
        t = np.asarray(pose.translation, dtype=np.float64)
        uv, ids = [], []
        for p2d in img.points2D:
            if p2d.has_point3D():
                uv.append(p2d.xy)
                ids.append(index_of[p2d.point3D_id])
        views.append(View(
            name=img.name,
            camera=PinholeCamera(K, R, t, cam.width, cam.height),
            uv=np.array(uv, dtype=np.float64).reshape(-1, 2),
            point_ids=np.array(ids, dtype=np.int64),
        ))
    registered = {v.name for v in views}
    return SparseModel(
        views=views, points=pts, colors=cols, errors=errs, track_lengths=tl,
        unregistered=[n for n in image_names if n not in registered], backend="colmap",
    )
