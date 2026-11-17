"""Optional mesh extraction by TSDF depth fusion + marching cubes.

Each aligned depth map is integrated into a truncated signed distance field
(Curless & Levoy 1996).  Only voxels observed from several views and with
consistent sign survive; marching cubes (scikit-image) extracts the surface
and vertex colors are blended per voxel.

The mesh is an *approximation* of visible surfaces.  Unobserved sides stay
open, and thin or reflective structures are often missing — the diagnostics
report this rather than hiding it.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .fusion import ViewDepth


@dataclass
class MeshResult:
    vertices: np.ndarray  # [V,3] float32
    faces: np.ndarray  # [F,3] int32
    colors: np.ndarray  # [V,3] uint8
    diagnostics: dict


def tsdf_fuse(
    views: list[ViewDepth],
    bounds_min: np.ndarray,
    bounds_max: np.ndarray,
    resolution: int = 192,
    trunc_voxels: float = 4.0,
    min_weight: float = 2.0,
    min_confidence: float = 0.3,
    progress=None,
) -> MeshResult | None:
    from skimage.measure import marching_cubes

    bmin = np.asarray(bounds_min, np.float64)
    bmax = np.asarray(bounds_max, np.float64)
    extent = bmax - bmin
    voxel = float(extent.max() / resolution)
    dims = np.maximum(np.ceil(extent / voxel).astype(int), 2)
    trunc = trunc_voxels * voxel

    gz, gy, gx = np.meshgrid(np.arange(dims[2]), np.arange(dims[1]), np.arange(dims[0]), indexing="ij")
    centers = np.stack([gx, gy, gz], -1).reshape(-1, 3) * voxel + bmin + voxel / 2
    n = len(centers)
    tsdf = np.ones(n, np.float32)
    weight = np.zeros(n, np.float32)
    color = np.zeros((n, 3), np.float32)

    for k, v in enumerate(views):
        cam = v.camera
        uv, z = cam.project(centers)
        inside = cam.in_image(uv) & (z > 0)
        idx = np.where(inside)[0]
        px = uv[idx, 0].astype(int)
        py = uv[idx, 1].astype(int)
        d = v.depth[py, px]
        c = v.confidence[py, px] if v.confidence is not None else np.ones_like(d)
        ok = (d > 0) & (c >= min_confidence)
        idx, px, py, d, c, zz = idx[ok], px[ok], py[ok], d[ok], c[ok], z[idx][ok]
        sdf = d - zz
        near = sdf > -trunc
        idx, px, py, sdf, c = idx[near], px[near], py[near], sdf[near], c[near]
        val = np.minimum(1.0, sdf / trunc)
        w_new = c.astype(np.float32)
        w_old = weight[idx]
        tot = w_old + w_new
        tsdf[idx] = (tsdf[idx] * w_old + val * w_new) / tot
        color[idx] = (color[idx] * w_old[:, None] + v.image[py, px].astype(np.float32) * w_new[:, None]) / tot[:, None]
        weight[idx] = tot
        if progress:
            progress((k + 1) / len(views), f"Integrated depth from {k + 1} of {len(views)} views")

    vol = tsdf.reshape(dims[2], dims[1], dims[0])
    wvol = weight.reshape(dims[2], dims[1], dims[0])
    mask = wvol >= min_weight
    if mask.sum() < 64 or not ((vol[mask] < 0).any() and (vol[mask] > 0).any()):
        return None
    vol = np.where(mask, vol, 1.0)
    verts, faces, _, _ = marching_cubes(vol, level=0.0, mask=mask, allow_degenerate=False)
    # marching_cubes returns (z, y, x) voxel coordinates.
    verts_xyz = verts[:, ::-1] * voxel + bmin + voxel / 2
    vi = np.clip(np.round(verts).astype(int), 0, np.array(vol.shape) - 1)
    vcol = color.reshape(dims[2], dims[1], dims[0], 3)[vi[:, 0], vi[:, 1], vi[:, 2]]
    faces = faces[:, ::-1].astype(np.int32)  # flip winding after axis swap

    diag = mesh_diagnostics(verts_xyz, faces)
    diag.update({"voxel_size": voxel, "grid": dims.tolist(), "truncation": trunc,
                 "observed_voxels": int(mask.sum()), "method": "TSDF fusion + marching cubes"})
    return MeshResult(verts_xyz.astype(np.float32), faces, np.clip(vcol, 0, 255).astype(np.uint8), diag)


def mesh_diagnostics(vertices: np.ndarray, faces: np.ndarray) -> dict:
    import trimesh

    m = trimesh.Trimesh(vertices, faces, process=False)
    comps = m.split(only_watertight=False)
    sizes = sorted((len(c.faces) for c in comps), reverse=True)
    edges = m.edges_sorted
    uniq, counts = np.unique(edges, axis=0, return_counts=True)
    boundary = int((counts == 1).sum())
    return {
        "vertices": int(len(vertices)),
        "faces": int(len(faces)),
        "components": len(sizes),
        "largest_component_fraction": float(sizes[0] / max(1, sum(sizes))) if sizes else 0.0,
        "watertight": bool(m.is_watertight),
        "boundary_edges": boundary,
        "surface_area": float(m.area),
    }


def keep_largest_components(res: MeshResult, min_fraction: float = 0.02) -> MeshResult:
    """Drop small floating fragments (keeps components ≥ min_fraction of faces)."""
    import trimesh

    m = trimesh.Trimesh(res.vertices, res.faces, vertex_colors=res.colors, process=False)
    comps = m.split(only_watertight=False)
    total = sum(len(c.faces) for c in comps)
    keep = [c for c in comps if len(c.faces) >= min_fraction * total]
    if not keep:
        return res
    merged = trimesh.util.concatenate(keep)
    cols = merged.visual.vertex_colors[:, :3].astype(np.uint8)
    diag = dict(res.diagnostics)
    diag.update(mesh_diagnostics(np.asarray(merged.vertices), np.asarray(merged.faces)))
    diag["fragments_removed"] = len(comps) - len(keep)
    return MeshResult(np.asarray(merged.vertices, np.float32), np.asarray(merged.faces, np.int32), cols, diag)
