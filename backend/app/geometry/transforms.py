"""Rigid and similarity transforms, rotations, and scene alignment helpers."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


def skew(v: np.ndarray) -> np.ndarray:
    x, y, z = np.asarray(v, dtype=np.float64)
    return np.array([[0.0, -z, y], [z, 0.0, -x], [-y, x, 0.0]])


def so3_exp(w: np.ndarray) -> np.ndarray:
    """Rodrigues: axis-angle vector -> rotation matrix."""
    w = np.asarray(w, dtype=np.float64)
    theta = np.linalg.norm(w)
    if theta < 1e-12:
        return np.eye(3) + skew(w)
    k = skew(w / theta)
    return np.eye(3) + np.sin(theta) * k + (1.0 - np.cos(theta)) * (k @ k)


def so3_log(R: np.ndarray) -> np.ndarray:
    """Rotation matrix -> axis-angle vector (robust near 0 and pi)."""
    R = np.asarray(R, dtype=np.float64)
    cos = np.clip((np.trace(R) - 1.0) / 2.0, -1.0, 1.0)
    theta = np.arccos(cos)
    if theta < 1e-7:
        return np.array([R[2, 1] - R[1, 2], R[0, 2] - R[2, 0], R[1, 0] - R[0, 1]]) / 2.0
    if np.pi - theta < 1e-5:
        # Near pi: axis from the dominant column of R + I.
        M = (R + np.eye(3)) / 2.0
        i = int(np.argmax(np.diag(M)))
        axis = M[:, i] / np.sqrt(max(M[i, i], 1e-12))
        return axis / np.linalg.norm(axis) * theta
    w = np.array([R[2, 1] - R[1, 2], R[0, 2] - R[2, 0], R[1, 0] - R[0, 1]])
    return w * theta / (2.0 * np.sin(theta))


def rotation_angle_deg(R_a: np.ndarray, R_b: np.ndarray) -> float:
    """Geodesic angle between two rotations, degrees."""
    cos = (np.trace(R_a.T @ R_b) - 1.0) / 2.0
    return float(np.rad2deg(np.arccos(np.clip(cos, -1.0, 1.0))))


def nearest_rotation(M: np.ndarray) -> np.ndarray:
    """Project a 3x3 matrix onto SO(3) (polar decomposition)."""
    U, _, Vt = np.linalg.svd(M)
    D = np.diag([1.0, 1.0, np.sign(np.linalg.det(U @ Vt))])
    return U @ D @ Vt


def rotation_between(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Minimal rotation taking unit direction ``a`` onto ``b``."""
    a = np.asarray(a, dtype=np.float64) / np.linalg.norm(a)
    b = np.asarray(b, dtype=np.float64) / np.linalg.norm(b)
    v = np.cross(a, b)
    c = float(np.dot(a, b))
    if c < -1.0 + 1e-10:
        # 180 degrees: rotate about any axis orthogonal to a.
        axis = np.cross(a, [1.0, 0.0, 0.0])
        if np.linalg.norm(axis) < 1e-6:
            axis = np.cross(a, [0.0, 1.0, 0.0])
        return so3_exp(axis / np.linalg.norm(axis) * np.pi)
    k = skew(v)
    return np.eye(3) + k + k @ k * (1.0 / (1.0 + c))


@dataclass
class Similarity:
    """x' = s * R @ x + t."""

    s: float = 1.0
    R: np.ndarray = None  # type: ignore[assignment]
    t: np.ndarray = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        self.R = np.eye(3) if self.R is None else np.asarray(self.R, dtype=np.float64)
        self.t = np.zeros(3) if self.t is None else np.asarray(self.t, dtype=np.float64)

    def apply(self, X: np.ndarray) -> np.ndarray:
        return self.s * (np.atleast_2d(X) @ self.R.T) + self.t

    def matrix(self) -> np.ndarray:
        T = np.eye(4)
        T[:3, :3] = self.s * self.R
        T[:3, 3] = self.t
        return T

    def inverse(self) -> "Similarity":
        Ri = self.R.T
        return Similarity(1.0 / self.s, Ri, -(Ri @ self.t) / self.s)

    def compose(self, other: "Similarity") -> "Similarity":
        """self ∘ other (apply ``other`` first)."""
        return Similarity(self.s * other.s, self.R @ other.R, self.s * self.R @ other.t + self.t)

    def transform_extrinsics(self, R_cam: np.ndarray, t_cam: np.ndarray):
        """Re-express a world-to-camera pose in the transformed world.

        If X' = s R X + t, then x_cam = R_c X + t_c = R_c R^T (X' - t)/s + t_c.
        Scaling the camera frame by s keeps the projection identical:
        x_cam' = s x_cam = (R_c R^T) X' + (s t_c - R_c R^T t).
        """
        R_new = R_cam @ self.R.T
        t_new = self.s * t_cam - R_new @ self.t
        return R_new, t_new


def umeyama(src: np.ndarray, dst: np.ndarray, with_scale: bool = True) -> Similarity:
    """Least-squares similarity aligning ``src`` onto ``dst`` (Umeyama 1991)."""
    src = np.asarray(src, dtype=np.float64)
    dst = np.asarray(dst, dtype=np.float64)
    if src.shape != dst.shape or src.shape[0] < 3:
        raise ValueError("umeyama needs >= 3 corresponding points")
    mu_s, mu_d = src.mean(0), dst.mean(0)
    xs, xd = src - mu_s, dst - mu_d
    cov = xd.T @ xs / src.shape[0]
    U, D, Vt = np.linalg.svd(cov)
    S = np.eye(3)
    if np.linalg.det(U) * np.linalg.det(Vt) < 0:
        S[2, 2] = -1.0
    R = U @ S @ Vt
    var_s = (xs**2).sum() / src.shape[0]
    s = float(np.trace(np.diag(D) @ S) / var_s) if with_scale else 1.0
    t = mu_d - s * R @ mu_s
    return Similarity(s, R, t)


def fit_plane_ransac(
    points: np.ndarray,
    threshold: float,
    iterations: int = 500,
    rng: np.random.Generator | None = None,
):
    """Robust plane fit. Returns (normal, d, inlier_mask) with n·x + d = 0."""
    rng = rng or np.random.default_rng(0)
    P = np.asarray(points, dtype=np.float64)
    n_pts = P.shape[0]
    if n_pts < 3:
        raise ValueError("need >= 3 points to fit a plane")
    best_mask, best_count = None, -1
    for _ in range(iterations):
        a, b, c = P[rng.choice(n_pts, 3, replace=False)]
        n = np.cross(b - a, c - a)
        norm = np.linalg.norm(n)
        if norm < 1e-12:
            continue
        n /= norm
        d = -n @ a
        mask = np.abs(P @ n + d) < threshold
        count = int(mask.sum())
        if count > best_count:
            best_count, best_mask = count, mask
    if best_mask is None:
        raise ValueError("degenerate point set")
    # Refine with least squares on inliers.
    Q = P[best_mask]
    centroid = Q.mean(0)
    _, _, Vt = np.linalg.svd(Q - centroid)
    n = Vt[-1]
    d = -n @ centroid
    mask = np.abs(P @ n + d) < threshold
    return n, float(d), mask


def estimate_up_from_cameras(R_list) -> np.ndarray:
    """Average image-up direction (camera -Y) in world coordinates.

    People overwhelmingly hold cameras roughly level, which makes this a
    reliable gravity prior when no IMU data is available.
    """
    ups = np.array([-np.asarray(R)[1] for R in R_list])
    up = ups.mean(0)
    n = np.linalg.norm(up)
    return up / n if n > 1e-9 else np.array([0.0, 1.0, 0.0])
