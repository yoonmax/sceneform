"""Tiny analytic ray tracer for textured axis-aligned boxes and a ground plane.

Produces photographs *and* exact depth for known cameras, so reconstruction
can be scored against ground truth.
"""

from __future__ import annotations

import cv2
import numpy as np

from app.geometry.cameras import PinholeCamera, intrinsics_from_fov


def make_texture(seed: int, size: int = 512) -> np.ndarray:
    rng = np.random.default_rng(seed)
    t = cv2.resize(rng.integers(40, 220, (size // 16, size // 16, 3), dtype=np.uint8), (size, size),
                   interpolation=cv2.INTER_CUBIC)
    for _ in range(400):
        c = tuple(int(x) for x in rng.integers(0, 255, 3))
        cv2.circle(t, tuple(int(x) for x in rng.integers(0, size, 2)), int(rng.integers(3, 18)), c, -1)
    return t


class Scene:
    """Faces are (axis, offset, (lo_a, hi_a), (lo_b, hi_b), texture)."""

    def __init__(self, seed: int = 0):
        tex = [make_texture(seed + i) for i in range(7)]
        self.faces = [(1, 0.0, (-3, 3), (-3, 3), tex[0])]  # ground y=0, x∈[-3,3], z∈[-3,3]
        lo, hi = np.array([-0.5, 0.0, -0.5]), np.array([0.5, 1.0, 0.5])
        k = 1
        for axis in range(3):
            others = [a for a in range(3) if a != axis]
            for off in (lo[axis], hi[axis]):
                if axis == 1 and off == 0.0:
                    continue  # bottom face hidden by the ground
                self.faces.append((axis, off, (lo[others[0]], hi[others[0]]), (lo[others[1]], hi[others[1]]), tex[k % 7]))
                k += 1

    def render(self, cam: PinholeCamera):
        h, w = cam.height, cam.width
        ys, xs = np.mgrid[0:h, 0:w]
        uv = np.stack([xs.ravel() + 0.5, ys.ravel() + 0.5], 1)
        d = cam.pixel_rays(uv)
        o = cam.center
        best_t = np.full(len(d), np.inf)
        color = np.zeros((len(d), 3), np.uint8)
        for axis, off, ra, rb, tex in self.faces:
            others = [a for a in range(3) if a != axis]
            with np.errstate(divide="ignore", invalid="ignore"):
                t = (off - o[axis]) / d[:, axis]
            p = o + t[:, None] * d
            a, b = p[:, others[0]], p[:, others[1]]
            hit = (t > 1e-6) & (t < best_t) & (a >= ra[0]) & (a <= ra[1]) & (b >= rb[0]) & (b <= rb[1])
            fa = (a[hit] - ra[0]) / (ra[1] - ra[0])
            fb = (b[hit] - rb[0]) / (rb[1] - rb[0])
            ts = tex.shape[0] - 1
            color[hit] = tex[(fb * ts).astype(int), (fa * ts).astype(int)]
            best_t[hit] = t[hit]
        z = best_t * (d @ cam.forward)
        z[~np.isfinite(best_t)] = 0
        img = color.reshape(h, w, 3)
        img[~np.isfinite(best_t).reshape(h, w)] = (235, 235, 240)
        return img, z.reshape(h, w).astype(np.float32)


def orbit_cameras(n=24, radius=3.0, height=1.6, width=640, img_h=480, fov=55.0):
    K = intrinsics_from_fov(width, img_h, fov)
    cams = []
    for i in range(n):
        a = 2 * np.pi * i / n
        eye = [radius * np.cos(a), height + 0.25 * np.sin(3 * a), radius * np.sin(a)]
        cams.append(PinholeCamera.look_at(K, eye, (0, 0.4, 0), width=width, height=img_h))
    return cams
