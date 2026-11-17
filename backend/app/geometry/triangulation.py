"""Triangulation and reprojection error."""

from __future__ import annotations

import numpy as np


def triangulate_dlt(P1: np.ndarray, P2: np.ndarray, x1: np.ndarray, x2: np.ndarray) -> np.ndarray:
    """Vectorised linear (DLT) two-view triangulation -> [N, 3] points."""
    x1 = np.atleast_2d(x1).astype(np.float64)
    x2 = np.atleast_2d(x2).astype(np.float64)
    n = x1.shape[0]
    A = np.empty((n, 4, 4))
    A[:, 0] = x1[:, 0:1] * P1[2] - P1[0]
    A[:, 1] = x1[:, 1:2] * P1[2] - P1[1]
    A[:, 2] = x2[:, 0:1] * P2[2] - P2[0]
    A[:, 3] = x2[:, 1:2] * P2[2] - P2[1]
    # Row-normalise for conditioning.
    A /= np.linalg.norm(A, axis=2, keepdims=True) + 1e-18
    _, _, Vt = np.linalg.svd(A)
    Xh = Vt[:, -1]
    with np.errstate(divide="ignore", invalid="ignore"):
        return Xh[:, :3] / Xh[:, 3:4]


def triangulate_multiview(projections, observations) -> np.ndarray:
    """DLT triangulation of one point seen in >= 2 views."""
    rows = []
    for P, (u, v) in zip(projections, observations):
        r1 = u * P[2] - P[0]
        r2 = v * P[2] - P[1]
        rows.append(r1 / (np.linalg.norm(r1) + 1e-18))
        rows.append(r2 / (np.linalg.norm(r2) + 1e-18))
    _, _, Vt = np.linalg.svd(np.array(rows))
    X = Vt[-1]
    return X[:3] / X[3]


def triangulation_angle_deg(C1: np.ndarray, C2: np.ndarray, X: np.ndarray) -> np.ndarray:
    """Angle between the two viewing rays at each point (degrees).

    Small angles (< ~2°) mean depth is poorly constrained.
    """
    X = np.atleast_2d(X)
    a = X - C1
    b = X - C2
    cos = np.einsum("ij,ij->i", a, b) / (np.linalg.norm(a, axis=1) * np.linalg.norm(b, axis=1) + 1e-18)
    return np.rad2deg(np.arccos(np.clip(cos, -1.0, 1.0)))


def reprojection_errors(P: np.ndarray, X: np.ndarray, x: np.ndarray) -> np.ndarray:
    """Pixel distance between observed ``x`` and the projection of ``X``."""
    X = np.atleast_2d(X)
    Xh = np.hstack([X, np.ones((len(X), 1))])
    proj = Xh @ P.T
    with np.errstate(divide="ignore", invalid="ignore"):
        uv = proj[:, :2] / proj[:, 2:3]
    err = np.linalg.norm(uv - x, axis=1)
    err[~np.isfinite(err) | (proj[:, 2] <= 0)] = np.inf
    return err
