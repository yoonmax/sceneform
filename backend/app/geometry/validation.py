"""Sanity checks applied to every reconstruction before it is saved."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


class GeometryError(ValueError):
    """Raised when reconstructed geometry violates a hard invariant."""


@dataclass
class ValidationReport:
    ok: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def error(self, msg: str) -> None:
        self.ok = False
        self.errors.append(msg)

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)


def is_rotation(R: np.ndarray, tol: float = 1e-5) -> bool:
    R = np.asarray(R, dtype=np.float64)
    return (
        R.shape == (3, 3)
        and np.isfinite(R).all()
        and np.allclose(R.T @ R, np.eye(3), atol=tol)
        and abs(np.linalg.det(R) - 1.0) < tol
    )


def validate_intrinsics(K: np.ndarray, width: int, height: int, report: ValidationReport) -> None:
    K = np.asarray(K)
    if not np.isfinite(K).all():
        report.error("intrinsics contain non-finite values")
        return
    fx, fy, cx, cy = K[0, 0], K[1, 1], K[0, 2], K[1, 2]
    if fx <= 0 or fy <= 0:
        report.error("focal length must be positive")
    diag = float(np.hypot(width, height))
    if not (0.15 * diag < fx < 15 * diag):
        report.warn(f"unusual focal length {fx:.1f}px for a {width}x{height} image")
    if not (0 <= cx <= width and 0 <= cy <= height):
        report.warn("principal point lies outside the image")
    if abs(fx / fy - 1.0) > 0.05:
        report.warn("non-square pixels (fx/fy differs by more than 5%)")


def validate_cameras(cameras, report: ValidationReport | None = None) -> ValidationReport:
    report = report or ValidationReport()
    if len(cameras) < 2:
        report.error("fewer than two registered cameras")
    centers = []
    for i, cam in enumerate(cameras):
        if not is_rotation(cam.R):
            report.error(f"camera {i}: rotation is not orthonormal with det +1")
        if not np.isfinite(cam.t).all():
            report.error(f"camera {i}: translation is not finite")
        validate_intrinsics(cam.K, cam.width, cam.height, report)
        centers.append(cam.center)
    if len(centers) >= 2:
        C = np.array(centers)
        spread = np.linalg.norm(C - C.mean(0), axis=1).max()
        if spread < 1e-9:
            report.error("all cameras share the same centre (no baseline)")
    return report


def finite_point_mask(points: np.ndarray) -> np.ndarray:
    return np.isfinite(points).all(axis=1)


def validate_point_cloud(points: np.ndarray, colors: np.ndarray | None = None) -> ValidationReport:
    report = ValidationReport()
    if points.ndim != 2 or points.shape[1] != 3:
        report.error("points must be an [N, 3] array")
        return report
    if len(points) == 0:
        report.error("point cloud is empty")
        return report
    bad = (~finite_point_mask(points)).sum()
    if bad:
        report.error(f"{bad} non-finite points")
    if colors is not None:
        if len(colors) != len(points):
            report.error("color count does not match point count")
        elif colors.dtype == np.uint8:
            pass
        elif np.nanmax(colors) > 1.0 + 1e-6 or np.nanmin(colors) < 0:
            report.error("float colors must lie in [0, 1]")
    ext = np.ptp(points[finite_point_mask(points)], axis=0) if len(points) else np.zeros(3)
    if np.any(ext <= 0):
        report.warn("point cloud is degenerate along at least one axis")
    return report
