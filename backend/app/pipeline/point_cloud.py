"""Point-cloud processing: filtering, downsampling, normals, bounds.

All operations are vectorised NumPy / SciPy (cKDTree) so they scale to a few
million points without pulling in a heavy dependency.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.spatial import cKDTree


@dataclass
class PointCloud:
    points: np.ndarray  # [N,3] float32/64
    colors: np.ndarray  # [N,3] uint8
    confidence: np.ndarray | None = None  # [N] in [0,1]
    source_view: np.ndarray | None = None  # [N] int16 index of the view it came from
    normals: np.ndarray | None = None  # [N,3]
    log: list[dict] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.points)

    def subset(self, mask: np.ndarray, step: str | None = None) -> "PointCloud":
        before = len(self)
        pc = PointCloud(
            self.points[mask],
            self.colors[mask],
            None if self.confidence is None else self.confidence[mask],
            None if self.source_view is None else self.source_view[mask],
            None if self.normals is None else self.normals[mask],
            list(self.log),
        )
        if step:
            pc.log.append({"step": step, "before": before, "after": len(pc)})
        return pc


def remove_nonfinite(pc: PointCloud) -> PointCloud:
    return pc.subset(np.isfinite(pc.points).all(1), "remove non-finite")


def filter_confidence(pc: PointCloud, threshold: float) -> PointCloud:
    if pc.confidence is None:
        return pc
    return pc.subset(pc.confidence >= threshold, f"confidence >= {threshold:.2f}")


def statistical_outlier_removal(pc: PointCloud, k: int = 16, std_ratio: float = 2.0) -> PointCloud:
    """Drop points whose mean k-NN distance is far above the global mean."""
    if len(pc) <= k + 1:
        return pc
    tree = cKDTree(pc.points)
    d, _ = tree.query(pc.points, k=k + 1, workers=-1)
    mean_d = d[:, 1:].mean(1)
    thr = mean_d.mean() + std_ratio * mean_d.std()
    return pc.subset(mean_d <= thr, f"statistical outliers (k={k}, σ={std_ratio})")


def radius_outlier_removal(pc: PointCloud, radius: float, min_neighbors: int = 4) -> PointCloud:
    tree = cKDTree(pc.points)
    counts = tree.query_ball_point(pc.points, r=radius, return_length=True, workers=-1)
    return pc.subset(counts > min_neighbors, f"radius outliers (r={radius:.4f})")


def voxel_downsample(pc: PointCloud, voxel: float) -> PointCloud:
    """Average all points falling in the same voxel (positions, colors,
    confidence); keeps the most common source view."""
    if voxel <= 0 or len(pc) == 0:
        return pc
    keys = np.floor(pc.points / voxel).astype(np.int64)
    keys -= keys.min(0)
    dims = keys.max(0) + 1
    lin = (keys[:, 0] * dims[1] + keys[:, 1]) * dims[2] + keys[:, 2]
    uniq, inv, counts = np.unique(lin, return_inverse=True, return_counts=True)
    m = len(uniq)

    def avg(a):
        out = np.zeros((m,) + a.shape[1:], dtype=np.float64)
        np.add.at(out, inv, a)
        return out / counts.reshape((-1,) + (1,) * (a.ndim - 1))

    w = pc.confidence if pc.confidence is not None else np.ones(len(pc))
    pts = avg(pc.points.astype(np.float64))
    cols = np.clip(avg(pc.colors.astype(np.float64)), 0, 255).astype(np.uint8)
    conf = None
    if pc.confidence is not None:
        # Agreement across many observations raises confidence a little.
        conf = np.clip(avg(w) * (1 + 0.05 * np.log2(counts)), 0, 1)
    src = None
    if pc.source_view is not None:
        # First occurrence wins (cheap; exact mode is not important here).
        first = np.full(m, -1, dtype=np.int64)
        order = np.argsort(inv, kind="stable")
        starts = np.r_[0, np.cumsum(counts)[:-1]]
        first = order[starts]
        src = pc.source_view[first]
    out = PointCloud(pts, cols, conf, src, None, list(pc.log))
    out.log.append({"step": f"voxel downsample ({voxel:.4f})", "before": len(pc), "after": m})
    return out


def estimate_normals(pc: PointCloud, k: int = 16, viewpoints: np.ndarray | None = None) -> PointCloud:
    """PCA normals, oriented towards the nearest camera centre if given."""
    if len(pc) < k:
        return pc
    tree = cKDTree(pc.points)
    _, idx = tree.query(pc.points, k=k, workers=-1)
    nb = pc.points[idx]  # [N,k,3]
    nb = nb - nb.mean(1, keepdims=True)
    cov = np.einsum("nki,nkj->nij", nb, nb)
    _, vecs = np.linalg.eigh(cov)
    normals = vecs[:, :, 0]
    if viewpoints is not None and len(viewpoints):
        vt = cKDTree(viewpoints)
        _, ci = vt.query(pc.points)
        to_cam = viewpoints[ci] - pc.points
        flip = (normals * to_cam).sum(1) < 0
        normals[flip] *= -1
    pc.normals = normals.astype(np.float32)
    return pc


def robust_bounds(points: np.ndarray, lo: float = 1.0, hi: float = 99.0) -> dict:
    if len(points) == 0:
        z = [0.0, 0.0, 0.0]
        return {"min": z, "max": z, "center": z, "radius": 0.0}
    mn = np.percentile(points, lo, axis=0)
    mx = np.percentile(points, hi, axis=0)
    c = (mn + mx) / 2
    return {
        "min": mn.tolist(),
        "max": mx.tolist(),
        "center": c.tolist(),
        "radius": float(np.linalg.norm(mx - mn) / 2),
    }


def crop_box(pc: PointCloud, mn, mx) -> PointCloud:
    m = np.all((pc.points >= np.asarray(mn)) & (pc.points <= np.asarray(mx)), axis=1)
    return pc.subset(m, "crop")


def density(points: np.ndarray, k: int = 8) -> np.ndarray:
    """Inverse mean k-NN distance, normalised to [0,1] (for visualisation)."""
    if len(points) <= k:
        return np.ones(len(points))
    d, _ = cKDTree(points).query(points, k=k + 1, workers=-1)
    inv = 1.0 / (d[:, 1:].mean(1) + 1e-9)
    lo, hi = np.percentile(inv, [2, 98])
    return np.clip((inv - lo) / (hi - lo + 1e-12), 0, 1)
