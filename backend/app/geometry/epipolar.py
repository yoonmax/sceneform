"""Two-view epipolar geometry implemented from first principles.

These routines are intentionally written out (rather than delegating to
``cv2.findEssentialMat``) so the inspection tools can expose each step:
normalised eight-point estimation, rank enforcement, RANSAC scoring with the
Sampson distance, essential-matrix decomposition, and the cheirality test.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .triangulation import triangulate_dlt


def _hartley_normalise(pts: np.ndarray):
    """Translate to the centroid and scale so the mean distance is sqrt(2)."""
    c = pts.mean(0)
    d = np.sqrt(((pts - c) ** 2).sum(1)).mean()
    s = np.sqrt(2.0) / max(d, 1e-12)
    T = np.array([[s, 0.0, -s * c[0]], [0.0, s, -s * c[1]], [0.0, 0.0, 1.0]])
    ph = np.hstack([pts, np.ones((len(pts), 1))]) @ T.T
    return ph, T


def fundamental_eight_point(x1: np.ndarray, x2: np.ndarray) -> np.ndarray:
    """Normalised eight-point algorithm; returns rank-2 F with x2ᵀ F x1 = 0."""
    if len(x1) < 8:
        raise ValueError("eight-point algorithm needs >= 8 correspondences")
    p1, T1 = _hartley_normalise(np.asarray(x1, dtype=np.float64))
    p2, T2 = _hartley_normalise(np.asarray(x2, dtype=np.float64))
    A = np.column_stack(
        [
            p2[:, 0] * p1[:, 0], p2[:, 0] * p1[:, 1], p2[:, 0],
            p2[:, 1] * p1[:, 0], p2[:, 1] * p1[:, 1], p2[:, 1],
            p1[:, 0], p1[:, 1], np.ones(len(p1)),
        ]
    )
    _, _, Vt = np.linalg.svd(A)
    F = Vt[-1].reshape(3, 3)
    U, S, Vt = np.linalg.svd(F)
    F = U @ np.diag([S[0], S[1], 0.0]) @ Vt
    F = T2.T @ F @ T1
    return F / (np.linalg.norm(F) + 1e-18)


def sampson_distance(F: np.ndarray, x1: np.ndarray, x2: np.ndarray) -> np.ndarray:
    """First-order geometric error of correspondences w.r.t. F (pixels²)."""
    h1 = np.hstack([x1, np.ones((len(x1), 1))])
    h2 = np.hstack([x2, np.ones((len(x2), 1))])
    Fx1 = h1 @ F.T
    Ftx2 = h2 @ F
    num = np.einsum("ij,ij->i", h2, Fx1) ** 2
    den = Fx1[:, 0] ** 2 + Fx1[:, 1] ** 2 + Ftx2[:, 0] ** 2 + Ftx2[:, 1] ** 2
    return num / np.maximum(den, 1e-18)


@dataclass
class RansacResult:
    model: np.ndarray
    inliers: np.ndarray
    iterations: int


def ransac_fundamental(
    x1: np.ndarray,
    x2: np.ndarray,
    threshold_px: float = 1.5,
    confidence: float = 0.999,
    max_iterations: int = 5000,
    rng: np.random.Generator | None = None,
) -> RansacResult:
    """RANSAC over the eight-point solver with adaptive iteration count."""
    rng = rng or np.random.default_rng(0)
    n = len(x1)
    if n < 8:
        raise ValueError("not enough matches for RANSAC")
    thr2 = threshold_px**2
    best_inliers = np.zeros(n, dtype=bool)
    best_count = 0
    needed = max_iterations
    it = 0
    while it < min(needed, max_iterations):
        it += 1
        sample = rng.choice(n, 8, replace=False)
        try:
            F = fundamental_eight_point(x1[sample], x2[sample])
        except np.linalg.LinAlgError:
            continue
        inl = sampson_distance(F, x1, x2) < thr2
        c = int(inl.sum())
        if c > best_count:
            best_count, best_inliers = c, inl
            w = c / n
            denom = np.log(max(1.0 - w**8, 1e-12))
            needed = int(np.ceil(np.log(1.0 - confidence) / denom)) if denom < 0 else 1
    if best_count < 8:
        raise ValueError("RANSAC failed to find a consistent model")
    F = fundamental_eight_point(x1[best_inliers], x2[best_inliers])
    inliers = sampson_distance(F, x1, x2) < thr2
    return RansacResult(F, inliers, it)


def essential_from_fundamental(F: np.ndarray, K1: np.ndarray, K2: np.ndarray) -> np.ndarray:
    E = K2.T @ F @ K1
    U, S, Vt = np.linalg.svd(E)
    s = (S[0] + S[1]) / 2.0
    return U @ np.diag([s, s, 0.0]) @ Vt


def decompose_essential(E: np.ndarray):
    """The four (R, t) candidates for E = [t]x R (t has unit norm)."""
    U, _, Vt = np.linalg.svd(E)
    if np.linalg.det(U) < 0:
        U = -U
    if np.linalg.det(Vt) < 0:
        Vt = -Vt
    W = np.array([[0.0, -1.0, 0.0], [1.0, 0.0, 0.0], [0.0, 0.0, 1.0]])
    R1 = U @ W @ Vt
    R2 = U @ W.T @ Vt
    t = U[:, 2]
    return [(R1, t), (R1, -t), (R2, t), (R2, -t)]


def recover_pose(E: np.ndarray, x1: np.ndarray, x2: np.ndarray, K1: np.ndarray, K2: np.ndarray):
    """Pick the decomposition with the most points in front of both cameras.

    Returns (R, t, mask_in_front, points3d) with camera 1 at the origin.
    """
    P1 = K1 @ np.hstack([np.eye(3), np.zeros((3, 1))])
    best = None
    for R, t in decompose_essential(E):
        P2 = K2 @ np.hstack([R, t[:, None]])
        X = triangulate_dlt(P1, P2, x1, x2)
        z1 = X[:, 2]
        z2 = (X @ R.T + t)[:, 2]
        front = (z1 > 0) & (z2 > 0) & np.isfinite(X).all(1)
        if best is None or front.sum() > best[2].sum():
            best = (R, t, front, X)
    return best
