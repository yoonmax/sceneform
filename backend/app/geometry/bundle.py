"""Sparse bundle adjustment with a robust loss (SciPy trust-region solver).

Parameterisation: per camera an axis-angle rotation (3) and translation (3),
a shared focal length (optionally refined), and per point XYZ (3).  The
Jacobian sparsity pattern is supplied so the solver scales to thousands of
points.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import least_squares
from scipy.sparse import lil_matrix

from .transforms import so3_exp, so3_log


def _rotate(points: np.ndarray, rvecs: np.ndarray) -> np.ndarray:
    """Rotate each point by its own axis-angle vector (vectorised Rodrigues)."""
    theta = np.linalg.norm(rvecs, axis=1)[:, None]
    with np.errstate(invalid="ignore", divide="ignore"):
        v = np.where(theta > 1e-12, rvecs / theta, 0.0)
    dot = (points * v).sum(1, keepdims=True)
    cos, sin = np.cos(theta), np.sin(theta)
    return cos * points + sin * np.cross(v, points) + dot * (1 - cos) * v


@dataclass
class BundleResult:
    rotations: list
    translations: list
    points: np.ndarray
    focal: float
    initial_rmse: float
    final_rmse: float
    iterations: int
    success: bool


def bundle_adjust(
    rotations,
    translations,
    points: np.ndarray,
    observations: np.ndarray,
    cam_idx: np.ndarray,
    pt_idx: np.ndarray,
    K: np.ndarray,
    fixed_cameras: tuple = (0,),
    refine_focal: bool = False,
    loss: str = "huber",
    f_scale: float = 2.0,
    max_nfev: int = 100,
) -> BundleResult:
    """Minimise reprojection error over poses and points.

    ``observations[k]`` is the pixel of point ``pt_idx[k]`` in camera
    ``cam_idx[k]``.  Cameras listed in ``fixed_cameras`` anchor the gauge.
    """
    n_cams = len(rotations)
    n_pts = len(points)
    fx, fy, cx, cy = K[0, 0], K[1, 1], K[0, 2], K[1, 2]
    aspect = fy / fx
    fixed = set(fixed_cameras)
    free = [i for i in range(n_cams) if i not in fixed]
    free_pos = {c: i for i, c in enumerate(free)}
    rv0 = np.array([so3_log(R) for R in rotations])
    tv0 = np.array([np.asarray(t, dtype=np.float64) for t in translations])

    n_cam_params = 6 * len(free)
    n_f = 1 if refine_focal else 0

    def unpack(x):
        rv = rv0.copy()
        tv = tv0.copy()
        cam = x[:n_cam_params].reshape(-1, 6)
        for c, i in free_pos.items():
            rv[c] = cam[i, :3]
            tv[c] = cam[i, 3:]
        f = x[n_cam_params] if refine_focal else fx
        pts = x[n_cam_params + n_f :].reshape(n_pts, 3)
        return rv, tv, f, pts

    def residuals(x):
        rv, tv, f, pts = unpack(x)
        Xc = _rotate(pts[pt_idx], rv[cam_idx]) + tv[cam_idx]
        z = Xc[:, 2]
        z = np.where(np.abs(z) < 1e-9, 1e-9, z)
        u = f * Xc[:, 0] / z + cx
        v = f * aspect * Xc[:, 1] / z + cy
        return np.concatenate([u - observations[:, 0], v - observations[:, 1]])

    x0 = np.concatenate(
        [np.hstack([rv0[free], tv0[free]]).ravel(), [fx] if refine_focal else [], points.ravel()]
    )

    m = len(observations)
    A = lil_matrix((2 * m, x0.size), dtype=np.int8)
    obs = np.arange(m)
    for c in free:
        sel = obs[cam_idx == c]
        base = 6 * free_pos[c]
        for k in range(6):
            A[sel, base + k] = 1
            A[m + sel, base + k] = 1
    if refine_focal:
        A[:, n_cam_params] = 1
    for k in range(3):
        col = n_cam_params + n_f + 3 * pt_idx + k
        A[obs, col] = 1
        A[m + obs, col] = 1

    r0 = residuals(x0)
    init_rmse = float(np.sqrt(np.mean(r0[:m] ** 2 + r0[m:] ** 2)))
    res = least_squares(
        residuals,
        x0,
        jac_sparsity=A,
        x_scale="jac",
        loss=loss,
        f_scale=f_scale,
        method="trf",
        max_nfev=max_nfev,
        verbose=0,
    )
    rv, tv, f, pts = unpack(res.x)
    r = res.fun
    final_rmse = float(np.sqrt(np.mean(r[:m] ** 2 + r[m:] ** 2)))
    return BundleResult(
        rotations=[so3_exp(w) for w in rv],
        translations=[t.copy() for t in tv],
        points=pts,
        focal=float(f),
        initial_rmse=init_rmse,
        final_rmse=final_rmse,
        iterations=int(res.nfev),
        success=bool(res.success),
    )
