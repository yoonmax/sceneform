"""Exports are re-read with independent readers (plyfile, trimesh, numpy)."""

import json

import numpy as np
import pytest

from app.geometry.cameras import quaternion_xyzw_to_rotation
from app.pipeline.edits import apply_edits, total_transform
from app.pipeline.export import (camera_record, read_pcd, read_ply, read_points_bin, write_colmap_text,
                                 write_depth_u16, write_mesh, write_pcd, write_point_ply, write_points_bin)
from app.pipeline.gaussian_splat import _quat_mul, prune_for_web, read_splat_ply, splat_stats

from .synthetic import random_points, ring_cameras


@pytest.fixture()
def cloud():
    rng = np.random.default_rng(0)
    P = random_points(1000).astype(np.float32)
    C = rng.integers(0, 255, (1000, 3), dtype=np.uint8)
    conf = rng.uniform(0, 1, 1000).astype(np.float32)
    N = rng.normal(size=(1000, 3)).astype(np.float32)
    return P, C, conf, N


def test_ply_roundtrip_with_plyfile(tmp_path, cloud):
    from plyfile import PlyData

    P, C, conf, N = cloud
    path = tmp_path / "c.ply"
    write_point_ply(path, P, C, conf, N, comments=["units: relative"])
    ext = PlyData.read(str(path))  # independent reader
    v = ext["vertex"]
    np.testing.assert_array_equal(np.stack([v["x"], v["y"], v["z"]], 1), P)
    np.testing.assert_array_equal(np.stack([v["red"], v["green"], v["blue"]], 1), C)
    np.testing.assert_allclose(v["confidence"], conf)
    assert "units: relative" in ext.comments
    own = read_ply(path)
    np.testing.assert_array_equal(own["nx"], N[:, 0])


def test_pcd_roundtrip(tmp_path, cloud):
    P, C, *_ = cloud
    write_pcd(tmp_path / "c.pcd", P, C)
    d = read_pcd(tmp_path / "c.pcd")
    np.testing.assert_array_equal(d["points"], P)
    np.testing.assert_array_equal(d["colors"], C)
    header = (tmp_path / "c.pcd").read_bytes()[:300].decode("ascii", "ignore")
    assert "FIELDS x y z rgb" in header and "DATA binary" in header


def test_points_bin_layout(tmp_path, cloud):
    P, C, conf, _ = cloud
    src = np.arange(1000) % 7
    layout = write_points_bin(tmp_path / "p.bin", P, C, conf, src)
    assert (tmp_path / "p.bin").stat().st_size == layout["bytes"]
    assert layout["source"]["offset"] % 2 == 0  # Uint16Array alignment
    d = read_points_bin(tmp_path / "p.bin", layout)
    np.testing.assert_array_equal(d["points"], P)
    np.testing.assert_array_equal(d["colors"], C)
    np.testing.assert_allclose(d["confidence"], np.round(conf * 255) / 255, atol=1 / 255)
    np.testing.assert_array_equal(d["source"], src)


def test_depth_quantisation(tmp_path):
    d = np.linspace(1, 5, 64 * 48, dtype=np.float32).reshape(48, 64)
    d[0, :5] = 0
    meta = write_depth_u16(tmp_path / "d.u16", d)
    q = np.frombuffer((tmp_path / "d.u16").read_bytes(), "<u2").reshape(48, 64)
    assert (q[0, :5] == 65535).all()
    dec = meta["near"] + q[1:] / meta["scale"] * (meta["far"] - meta["near"])
    np.testing.assert_allclose(dec, d[1:], atol=(5 - 1) / 65534)


@pytest.mark.parametrize("ext", ["glb", "obj", "ply"])
def test_mesh_export_reimport(tmp_path, ext):
    import trimesh

    box = trimesh.creation.box()
    cols = np.full((len(box.vertices), 3), 200, np.uint8)
    write_mesh(tmp_path / f"m.{ext}", box.vertices, box.faces, cols)
    m = trimesh.load(tmp_path / f"m.{ext}", force="mesh", process=False)
    assert len(m.faces) == 12
    np.testing.assert_allclose(m.bounds, box.bounds, atol=1e-6)


def test_camera_record_and_colmap_text(tmp_path):
    cams = ring_cameras(4)
    rec = camera_record("a.jpg", cams[1], 1)
    R = np.array(rec["extrinsics"]["R"])
    np.testing.assert_allclose(quaternion_xyzw_to_rotation(rec["extrinsics"]["quaternionXYZW"]), R, atol=1e-9)
    assert rec["intrinsics"]["model"] == "PINHOLE"
    json.dumps(rec)
    write_colmap_text(tmp_path / "colmap", [f"{i}.jpg" for i in range(4)], cams, random_points(5), np.zeros((5, 3)))
    import pycolmap

    rec2 = pycolmap.Reconstruction()
    rec2.read_text(str(tmp_path / "colmap"))
    assert rec2.num_images() == 4 and rec2.num_points3D() == 5
    img = rec2.images[2]
    np.testing.assert_allclose(img.cam_from_world().rotation.matrix(), cams[1].R, atol=1e-6)


def test_edit_replay():
    P = np.array([[1.0, 0, 0], [0, 0, 1], [5, 5, 5]])
    ops = [{"type": "rotate", "params": {"axis": [0, 1, 0], "degrees": 90}},
           {"type": "crop", "params": {"min": [-2, -2, -2], "max": [2, 2, 2]}},
           {"type": "removePoints", "params": {"indices": [1]}},
           {"type": "scaleReference", "params": {"measured": 2.0, "actual": 0.5, "unit": "m"}},
           {"type": "display", "params": {"pointSize": 3}}]
    Q, keep, unit = apply_edits(P, ops)
    np.testing.assert_allclose(Q[0], [0, 0, -0.25], atol=1e-9)
    assert keep.tolist() == [True, False, False]
    assert unit == {"kind": "scale-estimated", "unit": "m"}
    T = total_transform(ops)
    np.testing.assert_allclose((np.c_[P, np.ones(3)] @ T.T)[:, :3], Q, atol=1e-9)
    with pytest.raises(ValueError):
        apply_edits(P, [{"type": "scale", "params": {"factor": -1}}])


def _fake_splat(path, n=200):
    rng = np.random.default_rng(1)
    fields = ["x", "y", "z", "nx", "ny", "nz", "f_dc_0", "f_dc_1", "f_dc_2"] + [f"f_rest_{i}" for i in range(9)] + \
             ["opacity", "scale_0", "scale_1", "scale_2", "rot_0", "rot_1", "rot_2", "rot_3"]
    arr = np.zeros(n, dtype=[(f, "<f4") for f in fields])
    for f in fields:
        arr[f] = rng.normal(size=n)
    arr["opacity"][:50] = -10  # nearly transparent
    arr["x"][-1] = np.nan
    header = "ply\nformat binary_little_endian 1.0\n" + f"element vertex {n}\n" + "".join(f"property float {f}\n" for f in fields) + "end_header\n"
    path.write_bytes(header.encode() + arr.tobytes())


def test_splat_prune_and_validate(tmp_path):
    _fake_splat(tmp_path / "s.ply")
    st = splat_stats(read_splat_ply(tmp_path / "s.ply"))
    assert st["count"] == 200 and not st["finite"]
    info = prune_for_web(tmp_path / "s.ply", tmp_path / "w.ply", max_splats=100, keep_sh=True)
    assert info["output"] == 100
    out = read_splat_ply(tmp_path / "w.ply")
    assert np.isfinite(out["x"]).all()
    assert (1 / (1 + np.exp(-out["opacity"])) >= 0.02).all()
    assert "f_rest_8" in out
    q = np.stack([out[f"rot_{i}"] for i in range(4)], 1)
    np.testing.assert_allclose(np.linalg.norm(q, axis=1), 1, atol=1e-5)
    with pytest.raises(ValueError, match="not a 3D Gaussian splat"):
        write_point_ply(tmp_path / "p.ply", np.zeros((3, 3)))
        read_splat_ply(tmp_path / "p.ply")


def test_quaternion_product_matches_matrices():
    from app.geometry.cameras import rotation_to_quaternion_xyzw
    from app.geometry.transforms import so3_exp

    Ra, Rb = so3_exp([0.3, 0.2, -0.1]), so3_exp([-0.5, 0.9, 0.4])
    qa = np.roll(rotation_to_quaternion_xyzw(Ra), 1)
    qb = np.roll(rotation_to_quaternion_xyzw(Rb), 1)
    q = _quat_mul(qa, qb[None])[0]
    np.testing.assert_allclose(quaternion_xyzw_to_rotation(np.roll(q, -1)), Ra @ Rb, atol=1e-9)
