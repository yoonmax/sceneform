"""End-to-end reconstruction against a ray-traced scene with known geometry.

Runs the real COLMAP stage, then checks recovered poses, alignment, fusion,
point-cloud filtering, and output serialisation against ground truth.
"""

import numpy as np
import pytest
from PIL import Image

from app.geometry.transforms import rotation_angle_deg, umeyama
from app.geometry.validation import validate_cameras, validate_point_cloud
from app.pipeline import point_cloud as pcm
from app.pipeline.alignment import canonical_frame, coverage_degrees
from app.pipeline.fusion import FusionParams, fuse
from app.pipeline.sfm_colmap import run_colmap

from .render import Scene, orbit_cameras


@pytest.fixture(scope="module")
def synthetic(tmp_path_factory):
    root = tmp_path_factory.mktemp("synthetic")
    frames = root / "frames"
    frames.mkdir()
    scene, cams = Scene(), orbit_cameras(24)
    names, depths = [], []
    for i, c in enumerate(cams):
        img, z = scene.render(c)
        name = f"frame_{i:04d}.jpg"
        Image.fromarray(img).save(frames / name, quality=95)
        names.append(name)
        depths.append(z)
    model, und = run_colmap(frames, root / "colmap", names, single_camera=True, max_features=4000)
    return {"root": root, "cams": cams, "names": names, "depths": depths, "model": model, "und": und}


def test_all_views_registered_with_low_error(synthetic):
    m = synthetic["model"]
    assert len(m.views) == 24 and not m.unregistered
    stats = m.reprojection_stats()
    assert stats["mean"] < 1.0
    assert validate_cameras([v.camera for v in m.views]).ok


def test_recovered_poses_match_ground_truth_up_to_similarity(synthetic):
    m, gt = synthetic["model"], synthetic["cams"]
    idx = [synthetic["names"].index(v.name) for v in m.views]
    est_c = np.array([v.camera.center for v in m.views])
    gt_c = np.array([gt[i].center for i in idx])
    sim = umeyama(est_c, gt_c)
    pos_err = np.linalg.norm(sim.apply(est_c) - gt_c, axis=1)
    assert np.median(pos_err) < 0.02 * 3.0, pos_err  # < 2% of orbit radius
    rot_err = [rotation_angle_deg(v.camera.R @ sim.R.T, gt[i].R) for v, i in zip(m.views, idx)]
    assert np.median(rot_err) < 0.5, rot_err
    # Focal length recovered from images alone (no EXIF):
    f = np.median([v.camera.K[0, 0] for v in m.views])
    assert f == pytest.approx(gt[0].K[0, 0], rel=0.03)


def test_canonical_frame_is_y_up_and_unit_scale(synthetic):
    m = synthetic["model"]
    sim, info = canonical_frame(m)
    a = m.transformed(sim)
    # Ground plane points (GT y≈0) should have nearly constant y after alignment.
    assert info["upSource"] in ("ground-plane", "camera-average")
    centers = a.centers
    assert (centers[:, 1] > 0).all(), "cameras should be above the ground"
    r95 = np.percentile(np.linalg.norm(a.points, axis=1), 95)
    assert 0.5 < r95 < 1.5
    assert coverage_degrees(a) > 300


def test_fusion_with_exact_disparity_is_consistent(synthetic):
    """Feed ground-truth inverse depth (scrambled by an unknown affine map) to
    the fusion stage; it must recover consistent geometry."""
    m = synthetic["model"]
    sim, _ = canonical_frame(m)
    a = m.transformed(sim)
    images, disps = [], []
    rng = np.random.default_rng(0)
    for v in a.views:
        i = synthetic["names"].index(v.name)
        z = synthetic["depths"][i]
        disp = np.where(z > 0, 1.0 / np.maximum(z, 1e-6), 0)
        disp = disp * rng.uniform(5, 20) + rng.uniform(-0.1, 0.1)  # unknown affine
        small = np.array(Image.fromarray(disp.astype(np.float32)).resize((320, 240), Image.Resampling.NEAREST))
        img = np.array(Image.open(synthetic["und"] / "images" / v.name).convert("RGB").resize((320, 240)))
        disps.append(small)
        images.append(img)
    res = fuse(a, images, disps, FusionParams(stride=2))
    assert res.stats["views_fused"] >= 20
    assert res.stats["median_alignment_rel_error"] < 0.03
    cloud = pcm.voxel_downsample(pcm.filter_confidence(res.cloud, 0.5), 0.01)
    cloud = pcm.statistical_outlier_removal(cloud)
    assert len(cloud) > 5000
    assert validate_point_cloud(cloud.points, cloud.colors).ok
    # Map fused points back to the GT frame and measure distance to the true surfaces.
    est_c = np.array([v.camera.center for v in a.views])
    gt_c = np.array([synthetic["cams"][synthetic["names"].index(v.name)].center for v in a.views])
    to_gt = umeyama(est_c, gt_c)
    P = to_gt.apply(cloud.points)
    in_box = np.all((P > [-0.46, 0.04, -0.46]) & (P < [0.46, 0.96, 0.46]), axis=1)  # inset by 4 cm
    d_ground = np.abs(P[:, 1])
    d_box = np.min(np.stack([np.abs(P[:, 0] - 0.5), np.abs(P[:, 0] + 0.5), np.abs(P[:, 1] - 1.0),
                             np.abs(P[:, 2] - 0.5), np.abs(P[:, 2] + 0.5)], 1), 1)
    on_box = np.all((P > [-0.55, -0.05, -0.55]) & (P < [0.55, 1.05, 0.55]), axis=1)
    dist = np.where(on_box, np.minimum(d_box, d_ground), d_ground)
    assert np.median(dist) < 0.01, np.median(dist)
    assert np.percentile(dist, 90) < 0.04
    assert in_box.mean() < 0.05, "points must not float inside the solid box"
