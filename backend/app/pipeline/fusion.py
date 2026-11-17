"""SfM-anchored dense depth fusion.

Monocular networks predict depth only up to an unknown affine transform of
inverse depth, and they are frequently inconsistent between frames.  The
SfM reconstruction, by contrast, gives sparse but multi-view-verified depth.
This module combines both:

1. **Global alignment** – per view, fit ``1/z ≈ a·d + b`` between network
   disparity ``d`` and SfM inverse depth with RANSAC followed by Huber IRLS.
2. **Local correction** – the remaining log-ratio between SfM and aligned
   depth is smoothed onto a coarse grid (a regularised, Gaussian-weighted
   average) and applied multiplicatively.  This fixes low-frequency warping
   of the network without inventing detail.
3. **Edge cleanup** – pixels on depth discontinuities ("flying pixels") are
   invalidated using the gradient of log-depth.
4. **Multi-view consistency** – every pixel is lifted to 3D, projected into
   co-visible neighbour views, and compared with their depth.  The fraction
   of agreeing neighbours becomes the point's *confidence*.  This is a
   geometric consistency check (in the spirit of COLMAP's fusion step), not a
   learned confidence.

Depth here is in *reconstruction units*: scale-ambiguous unless the user
supplies a reference measurement.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np

from ..geometry.cameras import PinholeCamera
from .point_cloud import PointCloud
from .sparse_model import SparseModel


@dataclass
class DepthAlignment:
    a: float
    b: float
    inliers: int
    total: int
    median_rel_error_global: float
    median_rel_error_local: float
    usable: bool
    reason: str = ""


@dataclass
class ViewDepth:
    index: int
    camera: PinholeCamera  # at fusion resolution
    depth: np.ndarray  # [H,W] float32, 0 = invalid
    confidence: np.ndarray = None  # [H,W] float32 in [0,1]
    alignment: DepthAlignment | None = None
    image: np.ndarray | None = None  # [H,W,3] uint8


@dataclass
class FusionParams:
    stride: int = 2
    neighbours: int = 10
    rel_tolerance: float = 0.02  # upper bound; per-view tolerance adapts to depth spread
    min_tolerance: float = 0.002
    min_consistent: int = 2
    min_baseline_deg: float = 4.0
    edge_threshold: float = 0.025  # max |∇ log z| per pixel
    grid: tuple[int, int] = (8, 6)
    max_rel_error: float = 0.2
    min_sparse: int = 25


def bilinear(img: np.ndarray, uv: np.ndarray) -> np.ndarray:
    """Sample a single-channel image at sub-pixel (u, v) in pixel-corner coords."""
    x = uv[:, 0] - 0.5
    y = uv[:, 1] - 0.5
    h, w = img.shape
    x0 = np.clip(np.floor(x).astype(int), 0, w - 2)
    y0 = np.clip(np.floor(y).astype(int), 0, h - 2)
    fx = np.clip(x - x0, 0, 1)
    fy = np.clip(y - y0, 0, 1)
    return (
        img[y0, x0] * (1 - fx) * (1 - fy)
        + img[y0, x0 + 1] * fx * (1 - fy)
        + img[y0 + 1, x0] * (1 - fx) * fy
        + img[y0 + 1, x0 + 1] * fx * fy
    )


def fit_inverse_depth_affine(d: np.ndarray, z: np.ndarray, rng=None, iters: int = 300, tol: float = 0.05):
    """Robustly fit 1/z = a·d + b with a > 0.  Returns (a, b, inlier_mask)."""
    rng = rng or np.random.default_rng(0)
    y = 1.0 / z
    n = len(d)
    best = (None, None, np.zeros(n, bool))
    for _ in range(iters):
        i, j = rng.choice(n, 2, replace=False)
        if abs(d[i] - d[j]) < 1e-9:
            continue
        a = (y[i] - y[j]) / (d[i] - d[j])
        if a <= 0:
            continue
        b = y[i] - a * d[i]
        pred = a * d + b
        with np.errstate(divide="ignore", invalid="ignore"):
            rel = np.abs(1.0 / pred - z) / z
        inl = (pred > 0) & (rel < tol)
        if inl.sum() > best[2].sum():
            best = (a, b, inl)
    a, b, inl = best
    if a is None or inl.sum() < 5:
        raise ValueError("depth alignment failed")
    # Huber IRLS on the inliers, in inverse-depth space weighted by z² so that
    # residuals correspond to relative depth error.
    w = np.ones(int(inl.sum()))
    D, Y, Z = d[inl], y[inl], z[inl]
    for _ in range(10):
        A = np.stack([D, np.ones_like(D)], 1) * (w * Z)[:, None]
        sol, *_ = np.linalg.lstsq(A, Y * w * Z, rcond=None)
        a, b = sol
        r = np.abs((a * D + b - Y) * Z)
        k = 1.345 * (np.median(r) / 0.6745 + 1e-9)
        w = np.where(r <= k, 1.0, k / np.maximum(r, 1e-12))
    pred = a * d + b
    with np.errstate(divide="ignore", invalid="ignore"):
        rel = np.abs(1.0 / pred - z) / z
    return float(a), float(b), (pred > 0) & (rel < 2 * tol)


def local_correction(shape, uv: np.ndarray, log_ratio: np.ndarray, grid=(8, 6), prior: float = 3.0) -> np.ndarray:
    """Smooth sparse log-ratios onto a coarse grid and upsample to ``shape``.

    Each grid node takes a Gaussian-weighted mean of nearby residuals,
    shrunk toward zero by ``prior`` pseudo-observations, so regions without
    SfM support are left untouched.
    """
    h, w = shape
    gx, gy = grid
    cx = (np.arange(gx) + 0.5) * w / gx
    cy = (np.arange(gy) + 0.5) * h / gy
    sigma = 0.8 * max(w / gx, h / gy)
    field_ = np.zeros((gy, gx), np.float32)
    for yi, yc in enumerate(cy):
        for xi, xc in enumerate(cx):
            d2 = (uv[:, 0] - xc) ** 2 + (uv[:, 1] - yc) ** 2
            wts = np.exp(-d2 / (2 * sigma**2))
            field_[yi, xi] = (wts * log_ratio).sum() / (wts.sum() + prior)
    return cv2.resize(field_, (w, h), interpolation=cv2.INTER_CUBIC)


def align_view(disp: np.ndarray, cam: PinholeCamera, uv: np.ndarray, z: np.ndarray, params: FusionParams):
    """Turn network disparity into depth in reconstruction units."""
    valid = np.isfinite(z) & (z > 0) & cam.in_image(uv, margin=1)
    uv, z = uv[valid], z[valid]
    if len(z) < params.min_sparse:
        return None, DepthAlignment(0, 0, 0, len(z), 1.0, 1.0, False, "too few SfM points in view")
    d = bilinear(disp, uv)
    try:
        a, b, inl = fit_inverse_depth_affine(d, z)
    except ValueError:
        return None, DepthAlignment(0, 0, 0, len(z), 1.0, 1.0, False, "could not align depth")
    inv = a * disp + b
    with np.errstate(divide="ignore", invalid="ignore"):
        depth = np.where(inv > 1e-6, 1.0 / inv, 0.0).astype(np.float32)
    zg = bilinear(depth, uv)
    rel_g = np.abs(zg - z) / z
    ok = inl & (zg > 0)
    lr = np.zeros(len(z), np.float32)
    lr[ok] = np.log(z[ok] / zg[ok])
    corr = local_correction(depth.shape, uv[ok], lr[ok], params.grid)
    depth = np.where(depth > 0, depth * np.exp(corr), 0.0).astype(np.float32)
    zl = bilinear(depth, uv)
    rel_l = np.abs(zl - z) / z
    # Restrict to the depth range actually supported by SfM in this view.
    zlo, zhi = np.percentile(z, [2, 98])
    lo, hi = zlo * 0.85, zhi * 1.2
    depth[(depth < lo) | (depth > hi)] = 0
    med_l = float(np.median(rel_l[ok])) if ok.any() else 1.0
    al = DepthAlignment(a, b, int(inl.sum()), len(z), float(np.median(rel_g)), med_l,
                        med_l < params.max_rel_error, "" if med_l < params.max_rel_error else "alignment error too high")
    return depth, al


def remove_depth_edges(depth: np.ndarray, threshold: float) -> np.ndarray:
    logd = np.where(depth > 0, np.log(np.maximum(depth, 1e-9)), 0)
    gx = np.abs(np.diff(logd, axis=1, append=logd[:, -1:]))
    gy = np.abs(np.diff(logd, axis=0, append=logd[-1:, :]))
    edge = np.maximum(gx, gy) > threshold
    edge = cv2.dilate(edge.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool)
    out = depth.copy()
    out[edge] = 0
    return out


def covisibility_neighbours(model: SparseModel, k: int, min_baseline_deg: float = 4.0) -> list[list[int]]:
    """Neighbours sharing many SfM points *and* a useful baseline.

    Near-identical neighbours share the same depth errors, so agreement with
    them proves little; the score is down-weighted below ``2·min_baseline``
    and views under ``min_baseline`` are excluded.
    """
    sets = [set(v.point_ids.tolist()) if v.point_ids is not None else set() for v in model.views]
    centers = model.centers
    nbrs = []
    for i, si in enumerate(sets):
        if model.views[i].point_ids is not None and len(model.views[i].point_ids):
            focus = np.median(model.points[model.views[i].point_ids], axis=0)
        else:
            focus = model.points.mean(0)
        scores = []
        for j, sj in enumerate(sets):
            if j == i:
                continue
            shared = len(si & sj)
            if shared < 15:
                continue
            a, b = centers[i] - focus, centers[j] - focus
            ang = np.degrees(np.arccos(np.clip(a @ b / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-12), -1, 1)))
            if ang < min_baseline_deg:
                continue
            scores.append((shared * min(1.0, ang / (2 * min_baseline_deg)), j))
        scores.sort(reverse=True)
        nbrs.append([j for _, j in scores[:k]])
    return nbrs


def view_tolerance(model: SparseModel, i: int, params: FusionParams) -> float:
    """Relative depth tolerance scaled to the depth spread of the view."""
    _, z = model.view_depths(i)
    if len(z) < 10:
        return params.rel_tolerance
    p10, p50, p90 = np.percentile(z, [10, 50, 90])
    return float(np.clip(0.15 * (p90 - p10) / p50, params.min_tolerance, params.rel_tolerance))


def consistency(views: list[ViewDepth], nbrs: list[list[int]], params: FusionParams, progress=None,
                tolerances: dict | None = None) -> PointCloud:
    """Multi-view geometric consistency; returns the fused point cloud."""
    pts, cols, confs, srcs = [], [], [], []
    by_index = {v.index: v for v in views}
    for n_done, v in enumerate(views):
        h, w = v.depth.shape
        ys, xs = np.mgrid[0 : h : params.stride, 0 : w : params.stride]
        ys, xs = ys.ravel(), xs.ravel()
        z = v.depth[ys, xs]
        m = z > 0
        ys, xs, z = ys[m], xs[m], z[m]
        uv = np.stack([xs + 0.5, ys + 0.5], 1).astype(np.float64)
        X = v.camera.backproject(uv, z)
        agree = np.zeros(len(z), np.int32)
        seen = np.zeros(len(z), np.int32)
        # Free-space violations: the point would float in front of a surface
        # that view j observes, i.e. it blocks a ray j saw past it.
        violate = np.zeros(len(z), np.int32)
        for j in nbrs[v.index]:
            o = by_index.get(j)
            if o is None:
                continue
            uvj, zj = o.camera.project(X)
            inside = o.camera.in_image(uvj, margin=1) & (zj > 0)
            if not inside.any():
                continue
            ii = np.where(inside)[0]
            px = np.clip(uvj[ii, 0].astype(int), 0, o.depth.shape[1] - 1)
            py = np.clip(uvj[ii, 1].astype(int), 0, o.depth.shape[0] - 1)
            dj = o.depth[py, px]
            has = dj > 0
            rel = np.abs(zj[ii] - dj) / np.maximum(dj, 1e-9)
            seen[ii[has]] += 1
            tol = (tolerances or {}).get(v.index, params.rel_tolerance)
            agree[ii[has & (rel < tol)]] += 1
            violate[ii[has & (zj[ii] < dj * (1.0 - 3.0 * tol))]] += 1
        conf = np.where(seen > 0, agree / np.maximum(seen, 1), 0.0)
        # Views with a weaker SfM alignment produce less trustworthy points.
        if v.alignment is not None:
            conf = conf * float(np.clip(1.0 - v.alignment.median_rel_error_local / params.max_rel_error, 0.3, 1.0))
        keep = (agree >= params.min_consistent) & (violate < agree)
        conf = conf * np.where(seen > 0, 1.0 - violate / np.maximum(seen, 1), 0.0)
        cmap = np.zeros_like(v.depth)
        cmap[ys, xs] = conf
        v.confidence = cv2.dilate(cmap, np.ones((params.stride, params.stride), np.float32))
        pts.append(X[keep].astype(np.float32))
        cols.append(v.image[ys[keep], xs[keep]])
        confs.append(conf[keep].astype(np.float32))
        srcs.append(np.full(int(keep.sum()), v.index, np.int16))
        if progress:
            progress((n_done + 1) / len(views), f"Checked depth consistency for {n_done + 1} of {len(views)} views")
    if not pts:
        return PointCloud(np.zeros((0, 3), np.float32), np.zeros((0, 3), np.uint8), np.zeros(0, np.float32))
    pc = PointCloud(np.concatenate(pts), np.concatenate(cols), np.concatenate(confs), np.concatenate(srcs))
    pc.log.append({"step": "multi-view consistency", "before": None, "after": len(pc)})
    return pc


@dataclass
class FusionResult:
    cloud: PointCloud
    views: list[ViewDepth]
    skipped: list[dict] = field(default_factory=list)
    stats: dict = field(default_factory=dict)


def fuse(
    model: SparseModel,
    images: list[np.ndarray],
    disparities: list[np.ndarray],
    params: FusionParams | None = None,
    progress=None,
) -> FusionResult:
    """Align every view's disparity to SfM and fuse consistent points."""
    params = params or FusionParams()
    views, skipped = [], []
    for i, (v, img, disp) in enumerate(zip(model.views, images, disparities)):
        h, w = disp.shape
        s = w / v.camera.width
        cam = v.camera.scaled(s)
        cam.width, cam.height = w, h
        uv, z = model.view_depths(i)
        depth, al = align_view(disp, cam, uv * s, z, params)
        if depth is None or not al.usable:
            skipped.append({"view": i, "name": v.name, "reason": al.reason})
            continue
        depth = remove_depth_edges(depth, params.edge_threshold)
        if img.shape[:2] != (h, w):
            img = cv2.resize(img, (w, h), interpolation=cv2.INTER_AREA)
        views.append(ViewDepth(i, cam, depth, None, al, img))
        if progress:
            progress(0.3 * (i + 1) / len(model.views), f"Aligned depth for view {i + 1} of {len(model.views)}")
    nbrs = covisibility_neighbours(model, params.neighbours, params.min_baseline_deg)
    tols = {v.index: view_tolerance(model, v.index, params) for v in views}
    cloud = consistency(views, nbrs, params,
                        progress=(lambda f, m: progress(0.3 + 0.7 * f, m)) if progress else None,
                        tolerances=tols)
    errs = [v.alignment.median_rel_error_local for v in views]
    stats = {
        "views_fused": len(views),
        "views_skipped": len(skipped),
        "median_alignment_rel_error": float(np.median(errs)) if errs else None,
        "points_before_filtering": len(cloud),
        "median_rel_tolerance": float(np.median(list(tols.values()))) if tols else None,
        "min_consistent_views": params.min_consistent,
    }
    return FusionResult(cloud, views, skipped, stats)
