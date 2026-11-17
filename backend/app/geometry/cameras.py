"""Pinhole camera model and coordinate conventions.

Conventions used throughout sceneform
-------------------------------------
* **World frame** – right-handed. After scene alignment the world is *Y-up*
  so it can be handed to three.js without further rotation.
* **Camera frame (OpenCV / COLMAP)** – +X right, +Y down, +Z forward
  (the viewing direction).
* **Extrinsics** – stored world-to-camera: ``x_cam = R @ X_world + t``.
  The camera centre is ``C = -R.T @ t``.
* **Camera frame (OpenGL / three.js)** – +X right, +Y up, -Z forward.
  ``x_gl = diag(1, -1, -1) @ x_cv``.
* **Pixels** – (u, v) with the origin at the top-left corner of the top-left
  pixel; the centre of pixel (0, 0) is at (0.5, 0.5).  COLMAP uses the same
  convention, OpenCV uses pixel *centres* at integers.  sceneform stores
  intrinsics in the COLMAP/pixel-corner convention and converts explicitly
  in :func:`opencv_principal_point`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

# Flip between the OpenCV and OpenGL camera frames (self-inverse).
CV_TO_GL = np.diag([1.0, -1.0, -1.0])


def intrinsics_matrix(fx: float, fy: float, cx: float, cy: float) -> np.ndarray:
    return np.array([[fx, 0.0, cx], [0.0, fy, cy], [0.0, 0.0, 1.0]], dtype=np.float64)


def intrinsics_from_fov(width: int, height: int, fov_x_deg: float) -> np.ndarray:
    """Pinhole intrinsics with square pixels and a centred principal point."""
    fx = 0.5 * width / np.tan(np.deg2rad(fov_x_deg) / 2.0)
    return intrinsics_matrix(fx, fx, width / 2.0, height / 2.0)


def fov_from_focal(focal: float, size: float) -> float:
    """Full field of view (degrees) for a focal length in pixels."""
    return float(np.rad2deg(2.0 * np.arctan2(size / 2.0, focal)))


def opencv_principal_point(cx: float, cy: float) -> tuple[float, float]:
    """Convert a pixel-corner principal point to OpenCV's pixel-centre one."""
    return cx - 0.5, cy - 0.5


@dataclass
class PinholeCamera:
    """A calibrated pinhole view with world-to-camera extrinsics."""

    K: np.ndarray
    R: np.ndarray = field(default_factory=lambda: np.eye(3))
    t: np.ndarray = field(default_factory=lambda: np.zeros(3))
    width: int = 0
    height: int = 0
    # Optional radial/tangential distortion (OpenCV order k1 k2 p1 p2 k3).
    dist: np.ndarray | None = None

    def __post_init__(self) -> None:
        self.K = np.asarray(self.K, dtype=np.float64).reshape(3, 3)
        self.R = np.asarray(self.R, dtype=np.float64).reshape(3, 3)
        self.t = np.asarray(self.t, dtype=np.float64).reshape(3)

    # ----------------------------------------------------------------- poses
    @property
    def center(self) -> np.ndarray:
        return -self.R.T @ self.t

    @property
    def forward(self) -> np.ndarray:
        """Unit viewing direction in world coordinates (camera +Z)."""
        return self.R[2].copy()

    @property
    def up(self) -> np.ndarray:
        """Unit 'up' of the image in world coordinates (camera -Y)."""
        return -self.R[1].copy()

    @property
    def projection(self) -> np.ndarray:
        """3x4 projection matrix P = K [R | t]."""
        return self.K @ np.hstack([self.R, self.t[:, None]])

    def world_to_camera(self) -> np.ndarray:
        T = np.eye(4)
        T[:3, :3] = self.R
        T[:3, 3] = self.t
        return T

    def camera_to_world(self) -> np.ndarray:
        T = np.eye(4)
        T[:3, :3] = self.R.T
        T[:3, 3] = self.center
        return T

    @classmethod
    def from_camera_to_world(cls, K, c2w, width=0, height=0) -> "PinholeCamera":
        c2w = np.asarray(c2w, dtype=np.float64)
        R = c2w[:3, :3].T
        t = -R @ c2w[:3, 3]
        return cls(K=K, R=R, t=t, width=width, height=height)

    @classmethod
    def look_at(cls, K, eye, target, up=(0.0, 1.0, 0.0), width=0, height=0) -> "PinholeCamera":
        """OpenCV camera at ``eye`` looking at ``target`` with image-up ≈ ``up``."""
        eye = np.asarray(eye, dtype=np.float64)
        z = np.asarray(target, dtype=np.float64) - eye
        z /= np.linalg.norm(z)
        up = np.asarray(up, dtype=np.float64)
        # Right-handed camera: x = y × z with y = -up  =>  x = z × up.
        x = np.cross(z, up)
        if np.linalg.norm(x) < 1e-9:
            x = np.cross(z, np.array([0.0, 0.0, 1.0]))
        x /= np.linalg.norm(x)
        y = np.cross(z, x)
        R = np.stack([x, y, z])
        return cls(K=K, R=R, t=-R @ eye, width=width, height=height)

    # ------------------------------------------------------------ projection
    def to_camera(self, X: np.ndarray) -> np.ndarray:
        X = np.atleast_2d(X)
        return X @ self.R.T + self.t

    def project(self, X: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Project world points; returns (uv [N,2], depth [N]).

        Points behind the camera get NaN pixel coordinates.
        """
        Xc = self.to_camera(X)
        z = Xc[:, 2]
        with np.errstate(divide="ignore", invalid="ignore"):
            uvw = Xc @ self.K.T
            uv = uvw[:, :2] / uvw[:, 2:3]
        uv[z <= 1e-12] = np.nan
        return uv, z

    def backproject(self, uv: np.ndarray, depth: np.ndarray) -> np.ndarray:
        """Lift pixels with z-depth (along the optical axis) to world points."""
        uv = np.atleast_2d(uv).astype(np.float64)
        depth = np.asarray(depth, dtype=np.float64).reshape(-1)
        ones = np.ones((uv.shape[0], 1))
        rays = np.hstack([uv, ones]) @ np.linalg.inv(self.K).T
        Xc = rays * depth[:, None]
        return (Xc - self.t) @ self.R  # R^T (Xc - t)

    def pixel_rays(self, uv: np.ndarray) -> np.ndarray:
        """Unit world-space ray directions through pixels."""
        uv = np.atleast_2d(uv).astype(np.float64)
        d = np.hstack([uv, np.ones((uv.shape[0], 1))]) @ np.linalg.inv(self.K).T
        d = d @ self.R
        return d / np.linalg.norm(d, axis=1, keepdims=True)

    def in_image(self, uv: np.ndarray, margin: float = 0.0) -> np.ndarray:
        return (
            np.isfinite(uv).all(axis=1)
            & (uv[:, 0] >= margin)
            & (uv[:, 1] >= margin)
            & (uv[:, 0] < self.width - margin)
            & (uv[:, 1] < self.height - margin)
        )

    # -------------------------------------------------------------- export
    def fov_y(self) -> float:
        return fov_from_focal(self.K[1, 1], self.height)

    def fov_x(self) -> float:
        return fov_from_focal(self.K[0, 0], self.width)

    def to_threejs(self) -> dict:
        """Pose for a three.js PerspectiveCamera (Y-up world assumed).

        three.js cameras look down their local -Z with +Y up, so the
        camera-to-world rotation is ``R.T @ diag(1,-1,-1)``.
        """
        R_gl = self.R.T @ CV_TO_GL
        return {
            "position": self.center.tolist(),
            "quaternion": rotation_to_quaternion_xyzw(R_gl).tolist(),
            "fovY": self.fov_y(),
            "aspect": (self.width / self.height) if self.height else 1.0,
        }

    def scaled(self, factor: float) -> "PinholeCamera":
        """Same pose, intrinsics for an image resized by ``factor``."""
        S = np.diag([factor, factor, 1.0])
        return PinholeCamera(
            K=S @ self.K,
            R=self.R,
            t=self.t,
            width=int(round(self.width * factor)),
            height=int(round(self.height * factor)),
            dist=self.dist,
        )


def rotation_to_quaternion_xyzw(R: np.ndarray) -> np.ndarray:
    """Rotation matrix -> unit quaternion (x, y, z, w), w >= 0."""
    R = np.asarray(R, dtype=np.float64)
    tr = np.trace(R)
    if tr > 0:
        s = np.sqrt(tr + 1.0) * 2
        w = 0.25 * s
        x = (R[2, 1] - R[1, 2]) / s
        y = (R[0, 2] - R[2, 0]) / s
        z = (R[1, 0] - R[0, 1]) / s
    elif R[0, 0] > R[1, 1] and R[0, 0] > R[2, 2]:
        s = np.sqrt(1.0 + R[0, 0] - R[1, 1] - R[2, 2]) * 2
        w = (R[2, 1] - R[1, 2]) / s
        x = 0.25 * s
        y = (R[0, 1] + R[1, 0]) / s
        z = (R[0, 2] + R[2, 0]) / s
    elif R[1, 1] > R[2, 2]:
        s = np.sqrt(1.0 + R[1, 1] - R[0, 0] - R[2, 2]) * 2
        w = (R[0, 2] - R[2, 0]) / s
        x = (R[0, 1] + R[1, 0]) / s
        y = 0.25 * s
        z = (R[1, 2] + R[2, 1]) / s
    else:
        s = np.sqrt(1.0 + R[2, 2] - R[0, 0] - R[1, 1]) * 2
        w = (R[1, 0] - R[0, 1]) / s
        x = (R[0, 2] + R[2, 0]) / s
        y = (R[1, 2] + R[2, 1]) / s
        z = 0.25 * s
    q = np.array([x, y, z, w])
    q /= np.linalg.norm(q)
    return -q if q[3] < 0 else q


def quaternion_xyzw_to_rotation(q) -> np.ndarray:
    x, y, z, w = np.asarray(q, dtype=np.float64) / np.linalg.norm(q)
    return np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ]
    )
