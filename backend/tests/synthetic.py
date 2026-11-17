"""Synthetic scenes with known geometry, shared by the test-suite."""

from __future__ import annotations

import numpy as np

from app.geometry.cameras import PinholeCamera, intrinsics_from_fov


def ring_cameras(n=12, radius=4.0, height=1.0, width=640, img_height=480, fov=60.0, target=(0, 0, 0)):
    K = intrinsics_from_fov(width, img_height, fov)
    cams = []
    for i in range(n):
        a = 2 * np.pi * i / n
        eye = np.array([radius * np.cos(a), height, radius * np.sin(a)])
        cams.append(PinholeCamera.look_at(K, eye, target, up=(0, 1, 0), width=width, height=img_height))
    return cams


def random_points(n=400, extent=1.0, seed=0):
    rng = np.random.default_rng(seed)
    return rng.uniform(-extent, extent, size=(n, 3))


def observe(cams, X, noise_px=0.0, seed=1):
    rng = np.random.default_rng(seed)
    obs = []
    for c in cams:
        uv, z = c.project(X)
        uv = uv + rng.normal(0, noise_px, uv.shape) if noise_px else uv
        obs.append((uv, z))
    return obs
