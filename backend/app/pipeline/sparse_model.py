"""Backend-independent sparse reconstruction model.

Every SfM backend (COLMAP via pycolmap, or the built-in incremental solver)
produces a :class:`SparseModel`.  Everything downstream – alignment, dense
fusion, splat training, the viewer – only sees this type.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from ..geometry.cameras import PinholeCamera
from ..geometry.transforms import Similarity


@dataclass
class View:
    name: str  # file name inside the frames directory
    camera: PinholeCamera
    # Optional per-view observations: pixel coords and point indices.
    uv: np.ndarray | None = None
    point_ids: np.ndarray | None = None
    timestamp: float | None = None


@dataclass
class SparseModel:
    views: list[View]
    points: np.ndarray  # [N, 3]
    colors: np.ndarray  # [N, 3] uint8
    errors: np.ndarray  # [N] mean reprojection error (px)
    track_lengths: np.ndarray  # [N]
    unregistered: list[str] = field(default_factory=list)
    backend: str = ""
    stats: dict = field(default_factory=dict)

    # ------------------------------------------------------------ queries
    @property
    def centers(self) -> np.ndarray:
        return np.array([v.camera.center for v in self.views])

    def view_depths(self, i: int) -> tuple[np.ndarray, np.ndarray]:
        """(uv, z) of the sparse points observed in view ``i``."""
        v = self.views[i]
        if v.point_ids is None or len(v.point_ids) == 0:
            return np.zeros((0, 2)), np.zeros(0)
        X = self.points[v.point_ids]
        z = v.camera.to_camera(X)[:, 2]
        return v.uv, z

    def reprojection_stats(self) -> dict:
        errs = []
        for v in self.views:
            if v.point_ids is None or len(v.point_ids) == 0:
                continue
            uv, _ = v.camera.project(self.points[v.point_ids])
            e = np.linalg.norm(uv - v.uv, axis=1)
            errs.append(e[np.isfinite(e)])
        if not errs:
            return {"mean": None, "median": None, "p90": None, "observations": 0}
        e = np.concatenate(errs)
        return {
            "mean": float(e.mean()),
            "median": float(np.median(e)),
            "p90": float(np.percentile(e, 90)),
            "observations": int(e.size),
        }

    # ---------------------------------------------------------- transform
    def transformed(self, sim: Similarity) -> "SparseModel":
        views = []
        for v in self.views:
            R, t = sim.transform_extrinsics(v.camera.R, v.camera.t)
            cam = PinholeCamera(v.camera.K, R, t, v.camera.width, v.camera.height, v.camera.dist)
            views.append(View(v.name, cam, v.uv, v.point_ids, v.timestamp))
        return SparseModel(
            views=views,
            points=sim.apply(self.points) if len(self.points) else self.points,
            colors=self.colors,
            errors=self.errors,
            track_lengths=self.track_lengths,
            unregistered=list(self.unregistered),
            backend=self.backend,
            stats=dict(self.stats),
        )

    def subset_points(self, mask: np.ndarray) -> "SparseModel":
        remap = -np.ones(len(self.points), dtype=np.int64)
        remap[mask] = np.arange(int(mask.sum()))
        views = []
        for v in self.views:
            if v.point_ids is None:
                views.append(v)
                continue
            new = remap[v.point_ids]
            keep = new >= 0
            views.append(View(v.name, v.camera, v.uv[keep], new[keep], v.timestamp))
        return SparseModel(views, self.points[mask], self.colors[mask], self.errors[mask],
                           self.track_lengths[mask], self.unregistered, self.backend, self.stats)

    # -------------------------------------------------------------- io
    def save(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(
            directory / "sparse_points.npz",
            points=self.points, colors=self.colors, errors=self.errors, track_lengths=self.track_lengths,
        )
        obs = {}
        for i, v in enumerate(self.views):
            if v.point_ids is not None:
                obs[f"uv_{i}"] = v.uv
                obs[f"ids_{i}"] = v.point_ids
        np.savez_compressed(directory / "sparse_obs.npz", **obs)
        meta = {
            "backend": self.backend,
            "stats": self.stats,
            "unregistered": self.unregistered,
            "views": [
                {
                    "name": v.name,
                    "K": v.camera.K.tolist(),
                    "R": v.camera.R.tolist(),
                    "t": v.camera.t.tolist(),
                    "width": v.camera.width,
                    "height": v.camera.height,
                    "timestamp": v.timestamp,
                }
                for v in self.views
            ],
        }
        (directory / "sparse_model.json").write_text(json.dumps(meta, indent=1))

    @classmethod
    def load(cls, directory: Path) -> "SparseModel":
        meta = json.loads((directory / "sparse_model.json").read_text())
        pts = np.load(directory / "sparse_points.npz")
        obs = np.load(directory / "sparse_obs.npz")
        views = []
        for i, m in enumerate(meta["views"]):
            cam = PinholeCamera(np.array(m["K"]), np.array(m["R"]), np.array(m["t"]), m["width"], m["height"])
            uv = obs[f"uv_{i}"] if f"uv_{i}" in obs else None
            ids = obs[f"ids_{i}"] if f"ids_{i}" in obs else None
            views.append(View(m["name"], cam, uv, ids, m.get("timestamp")))
        return cls(views, pts["points"], pts["colors"], pts["errors"], pts["track_lengths"],
                   meta.get("unregistered", []), meta.get("backend", ""), meta.get("stats", {}))
