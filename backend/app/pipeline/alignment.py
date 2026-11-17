"""Canonical scene frame: Y-up, centred, normalised scale.

SfM output lives in an arbitrary frame (COLMAP fixes the first camera, with
arbitrary scale).  This step chooses a frame that is pleasant to view and
documented in the manifest:

* **up** – the dominant ground plane's normal when one is found and agrees
  with the cameras' average image-up direction; otherwise that average.
* **origin** – on the ground plane under the subject, or the robust centre.
* **yaw** – the first camera sits on the +Z side, so the default view looks
  the way the capture started.
* **scale** – 95% of reliable points within one unit of the origin.  Units are
  therefore *relative* until the user supplies a reference length.
"""

from __future__ import annotations

import numpy as np

from ..geometry.transforms import Similarity, estimate_up_from_cameras, fit_plane_ransac, rotation_between
from .sparse_model import SparseModel


def canonical_frame(model: SparseModel, use_ground_plane: bool = True) -> tuple[Similarity, dict]:
    reliable = (model.track_lengths >= 3) & (model.errors < 2.0)
    P = model.points[reliable] if reliable.sum() > 50 else model.points
    center = np.median(P, axis=0)
    cam_up = estimate_up_from_cameras([v.camera.R for v in model.views])
    up, ground, info = cam_up, None, {"upSource": "camera-average"}

    if use_ground_plane and len(P) > 200:
        spread = np.percentile(np.linalg.norm(P - center, axis=1), 90)
        try:
            n, d, mask = fit_plane_ransac(P, threshold=0.01 * spread, iterations=400)
            frac = float(mask.mean())
            if n @ cam_up < 0:
                n, d = -n, -d
            angle = float(np.degrees(np.arccos(np.clip(n @ cam_up, -1, 1))))
            # Cameras must be on the positive side, i.e. above the ground.
            above = np.mean(model.centers @ n + d > 0)
            if frac > 0.15 and angle < 25 and above > 0.9:
                up, ground = n, (n, d)
                info = {"upSource": "ground-plane", "groundInlierFraction": frac, "groundAngleToCameraUpDeg": angle}
        except ValueError:
            pass

    R = rotation_between(up, np.array([0.0, 1.0, 0.0]))
    origin = center.copy()
    if ground is not None:
        n, d = ground
        origin = center - (center @ n + d) * n  # project centre onto plane
    # Yaw so the first camera lies toward +Z.
    c0 = R @ (model.views[0].camera.center - origin)
    yaw = np.arctan2(c0[0], c0[2])
    cy, sy = np.cos(-yaw), np.sin(-yaw)
    Ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    R = Ry @ R
    r95 = float(np.percentile(np.linalg.norm((P - origin) @ R.T, axis=1), 95))
    s = 1.0 / max(r95, 1e-9)
    sim = Similarity(s, R, -s * R @ origin)
    info.update({"scale": s, "units": "relative"})
    return sim, info


def coverage_degrees(model: SparseModel) -> float:
    """Azimuthal span of cameras around the subject (after alignment, Y-up).

    Uses the largest empty gap between camera azimuths, so a full orbit gives
    ~360° and a single-sided sweep gives its actual span.
    """
    reliable = (model.track_lengths >= 3)
    P = model.points[reliable] if reliable.sum() > 20 else model.points
    c = np.median(P, axis=0)
    d = model.centers - c
    az = np.sort(np.degrees(np.arctan2(d[:, 0], d[:, 2])) % 360)
    if len(az) < 2:
        return 0.0
    gaps = np.diff(np.r_[az, az[0] + 360])
    return float(360 - gaps.max())
