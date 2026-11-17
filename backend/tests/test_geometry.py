import numpy as np
import pytest

from app.geometry.bundle import bundle_adjust
from app.geometry.cameras import (
    CV_TO_GL,
    PinholeCamera,
    intrinsics_from_fov,
    quaternion_xyzw_to_rotation,
    rotation_to_quaternion_xyzw,
)
from app.geometry.epipolar import (
    decompose_essential,
    essential_from_fundamental,
    fundamental_eight_point,
    ransac_fundamental,
    recover_pose,
    sampson_distance,
)
from app.geometry.transforms import (
    Similarity,
    estimate_up_from_cameras,
    fit_plane_ransac,
    nearest_rotation,
    rotation_angle_deg,
    rotation_between,
    so3_exp,
    so3_log,
    umeyama,
)
from app.geometry.triangulation import (
    reprojection_errors,
    triangulate_dlt,
    triangulate_multiview,
    triangulation_angle_deg,
)
from app.geometry.validation import is_rotation, validate_cameras, validate_point_cloud

from .synthetic import random_points, ring_cameras


# --------------------------------------------------------------- cameras
def test_look_at_orientation_is_upright_and_forward():
    K = intrinsics_from_fov(640, 480, 60)
    cam = PinholeCamera.look_at(K, eye=(0, 0, -5), target=(0, 0, 0), up=(0, 1, 0), width=640, height=480)
    assert is_rotation(cam.R)
    np.testing.assert_allclose(cam.forward, [0, 0, 1], atol=1e-12)
    np.testing.assert_allclose(cam.up, [0, 1, 0], atol=1e-12)
    # A point above the target must appear in the upper half of the image.
    uv, z = cam.project(np.array([[0.0, 1.0, 0.0]]))
    assert uv[0, 1] < 240 and z[0] > 0
    # Right-handed, Y-up world, looking along +Z: world +X appears on the image left.
    uv, _ = cam.project(np.array([[1.0, 0.0, 0.0]]))
    assert uv[0, 0] < 320


def test_project_backproject_roundtrip():
    cams = ring_cameras(5)
    X = random_points(200)
    for c in cams:
        uv, z = c.project(X)
        Xb = c.backproject(uv, z)
        np.testing.assert_allclose(Xb, X, atol=1e-9)


def test_points_behind_camera_are_nan():
    K = intrinsics_from_fov(100, 100, 90)
    cam = PinholeCamera(K=K, width=100, height=100)
    uv, z = cam.project(np.array([[0, 0, -1.0], [0, 0, 1.0]]))
    assert np.isnan(uv[0]).all() and np.isfinite(uv[1]).all()
    assert z[0] < 0


def test_camera_to_world_inverse_and_center():
    cam = ring_cameras(3)[1]
    T = cam.camera_to_world() @ cam.world_to_camera()
    np.testing.assert_allclose(T, np.eye(4), atol=1e-12)
    np.testing.assert_allclose(cam.to_camera(cam.center[None]), 0, atol=1e-12)
    cam2 = PinholeCamera.from_camera_to_world(cam.K, cam.camera_to_world(), cam.width, cam.height)
    np.testing.assert_allclose(cam2.R, cam.R, atol=1e-12)
    np.testing.assert_allclose(cam2.t, cam.t, atol=1e-12)


def test_threejs_pose_looks_at_target():
    """three.js cameras look down local -Z; check the converted pose does."""
    cam = ring_cameras(8)[3]
    pose = cam.to_threejs()
    R_gl = quaternion_xyzw_to_rotation(pose["quaternion"])
    look = R_gl @ np.array([0, 0, -1.0])
    to_target = -np.asarray(pose["position"])
    to_target /= np.linalg.norm(to_target)
    np.testing.assert_allclose(look, to_target, atol=1e-9)
    # local +Y of the three.js camera is image-up
    np.testing.assert_allclose(R_gl @ np.array([0, 1.0, 0]), cam.up, atol=1e-9)
    assert np.isclose(np.linalg.det(R_gl), 1.0)
    np.testing.assert_allclose(CV_TO_GL @ CV_TO_GL, np.eye(3))


def test_quaternion_roundtrip_including_180_degrees():
    rng = np.random.default_rng(3)
    mats = [so3_exp(rng.normal(size=3)) for _ in range(50)]
    mats += [so3_exp(np.array([np.pi, 0, 0])), so3_exp(np.array([0, np.pi, 0])), np.eye(3)]
    for R in mats:
        q = rotation_to_quaternion_xyzw(R)
        np.testing.assert_allclose(quaternion_xyzw_to_rotation(q), R, atol=1e-9)


def test_scaled_intrinsics_preserve_projection_ratio():
    cam = ring_cameras(4)[0]
    small = cam.scaled(0.5)
    X = random_points(50)
    uv, _ = cam.project(X)
    uv2, _ = small.project(X)
    np.testing.assert_allclose(uv2, uv * 0.5, atol=1e-9)


# ------------------------------------------------------------ rotations
def test_so3_exp_log_roundtrip():
    rng = np.random.default_rng(0)
    for _ in range(100):
        w = rng.normal(size=3)
        w *= rng.uniform(0, np.pi - 1e-3) / np.linalg.norm(w)
        np.testing.assert_allclose(so3_log(so3_exp(w)), w, atol=1e-8)
    w = np.array([0, 0, np.pi])
    np.testing.assert_allclose(so3_exp(so3_log(so3_exp(w))), so3_exp(w), atol=1e-6)


def test_rotation_between_and_nearest_rotation():
    a, b = np.array([0, 0, 1.0]), np.array([1.0, 1.0, 0]) / np.sqrt(2)
    R = rotation_between(a, b)
    np.testing.assert_allclose(R @ a, b, atol=1e-12)
    R = rotation_between(a, -a)
    np.testing.assert_allclose(R @ a, -a, atol=1e-9)
    noisy = so3_exp([0.2, 0.1, -0.3]) + 1e-3
    assert is_rotation(nearest_rotation(noisy))


def test_umeyama_recovers_similarity():
    rng = np.random.default_rng(1)
    X = rng.normal(size=(100, 3))
    sim = Similarity(2.5, so3_exp([0.3, -0.7, 0.2]), np.array([1.0, -2.0, 0.5]))
    Y = sim.apply(X)
    est = umeyama(X, Y)
    assert est.s == pytest.approx(2.5, rel=1e-9)
    np.testing.assert_allclose(est.R, sim.R, atol=1e-9)
    np.testing.assert_allclose(est.apply(X), Y, atol=1e-9)
    np.testing.assert_allclose(est.inverse().apply(Y), X, atol=1e-9)


def test_similarity_preserves_projections_of_transformed_cameras():
    cams = ring_cameras(6)
    X = random_points(100)
    sim = Similarity(0.37, so3_exp([1.0, 0.2, -0.5]), np.array([3.0, 1.0, -2.0]))
    Xn = sim.apply(X)
    for c in cams:
        R2, t2 = sim.transform_extrinsics(c.R, c.t)
        c2 = PinholeCamera(c.K, R2, t2, c.width, c.height)
        np.testing.assert_allclose(c2.project(Xn)[0], c.project(X)[0], atol=1e-8)
        np.testing.assert_allclose(c2.center, sim.apply(c.center[None])[0], atol=1e-9)


def test_plane_fit_ransac_with_outliers():
    rng = np.random.default_rng(2)
    plane = np.c_[rng.uniform(-1, 1, 300), np.full(300, 0.5), rng.uniform(-1, 1, 300)]
    plane += rng.normal(0, 0.002, plane.shape)
    outliers = rng.uniform(-1, 1, (100, 3))
    n, d, mask = fit_plane_ransac(np.vstack([plane, outliers]), threshold=0.01)
    assert abs(abs(n[1]) - 1) < 1e-3
    assert abs(abs(d) - 0.5) < 1e-2
    assert mask[:300].mean() > 0.97


def test_up_vector_from_level_cameras():
    up = estimate_up_from_cameras([c.R for c in ring_cameras(10, height=0.0)])
    np.testing.assert_allclose(up, [0, 1, 0], atol=1e-9)


# --------------------------------------------------------- triangulation
def test_triangulation_exact_and_multiview():
    cams = ring_cameras(6)
    X = random_points(100)
    uv = [c.project(X)[0] for c in cams]
    Xt = triangulate_dlt(cams[0].projection, cams[2].projection, uv[0], uv[2])
    np.testing.assert_allclose(Xt, X, atol=1e-8)
    Xm = triangulate_multiview([c.projection for c in cams], [u[7] for u in uv])
    np.testing.assert_allclose(Xm, X[7], atol=1e-8)
    err = reprojection_errors(cams[1].projection, Xt, uv[1])
    assert err.max() < 1e-6


def test_triangulation_with_noise_has_subpixel_reprojection():
    cams = ring_cameras(6)
    X = random_points(300)
    rng = np.random.default_rng(5)
    uv0 = cams[0].project(X)[0] + rng.normal(0, 0.5, (300, 2))
    uv1 = cams[1].project(X)[0] + rng.normal(0, 0.5, (300, 2))
    Xt = triangulate_dlt(cams[0].projection, cams[1].projection, uv0, uv1)
    assert np.median(reprojection_errors(cams[0].projection, Xt, uv0)) < 1.0
    ang = triangulation_angle_deg(cams[0].center, cams[1].center, X)
    assert np.all(ang > 5)


def test_reprojection_error_inf_behind_camera():
    cam = ring_cameras(1)[0]
    behind = cam.center + 2 * (cam.center - 0)  # further away from the target
    err = reprojection_errors(cam.projection, behind[None], np.zeros((1, 2)))
    assert np.isinf(err[0])


# ---------------------------------------------------------- epipolar
def _two_view(noise=0.0, outliers=0, seed=0):
    cams = ring_cameras(12)
    c1, c2 = cams[0], cams[2]
    X = random_points(400, seed=seed)
    rng = np.random.default_rng(seed)
    x1 = c1.project(X)[0] + rng.normal(0, noise, (400, 2))
    x2 = c2.project(X)[0] + rng.normal(0, noise, (400, 2))
    if outliers:
        x2[:outliers] = rng.uniform(0, 640, (outliers, 2))
    return c1, c2, X, x1, x2


def test_eight_point_satisfies_epipolar_constraint():
    c1, c2, X, x1, x2 = _two_view()
    F = fundamental_eight_point(x1, x2)
    assert np.linalg.matrix_rank(F, tol=1e-8) == 2
    assert sampson_distance(F, x1, x2).max() < 1e-8


def test_ransac_rejects_outliers():
    c1, c2, X, x1, x2 = _two_view(noise=0.3, outliers=120)
    res = ransac_fundamental(x1, x2, threshold_px=1.5)
    inl = res.inliers
    assert inl[120:].mean() > 0.95
    assert inl[:120].mean() < 0.1


def test_essential_decomposition_and_pose_recovery():
    c1, c2, X, x1, x2 = _two_view(noise=0.2)
    F = ransac_fundamental(x1, x2).model
    E = essential_from_fundamental(F, c1.K, c2.K)
    assert len(decompose_essential(E)) == 4
    R, t, front, Xr = recover_pose(E, x1, x2, c1.K, c2.K)
    R_true = c2.R @ c1.R.T
    t_true = c2.t - R_true @ c1.t
    assert rotation_angle_deg(R, R_true) < 0.5
    cos = np.dot(t, t_true) / np.linalg.norm(t_true)
    assert cos > 0.999
    assert front.mean() > 0.95


# ------------------------------------------------------- bundle adjust
def test_bundle_adjustment_reduces_error_on_perturbed_scene():
    cams = ring_cameras(8, radius=4)
    X = random_points(150, extent=0.8)
    rng = np.random.default_rng(7)
    obs, ci, pi = [], [], []
    for c_i, c in enumerate(cams):
        uv, _ = c.project(X)
        obs.append(uv + rng.normal(0, 0.3, uv.shape))
        ci.append(np.full(len(X), c_i))
        pi.append(np.arange(len(X)))
    obs, ci, pi = np.vstack(obs), np.concatenate(ci), np.concatenate(pi)
    R0 = [c.R if i == 0 else so3_exp(rng.normal(0, 0.01, 3)) @ c.R for i, c in enumerate(cams)]
    t0 = [c.t if i == 0 else c.t + rng.normal(0, 0.03, 3) for i, c in enumerate(cams)]
    X0 = X + rng.normal(0, 0.03, X.shape)
    # Fixing two exact cameras pins the gauge, including scale.
    res = bundle_adjust(
        [cams[0].R, cams[1].R] + R0[2:], [cams[0].t, cams[1].t] + t0[2:], X0, obs, ci, pi,
        cams[0].K, fixed_cameras=(0, 1),
    )
    assert res.final_rmse < res.initial_rmse
    assert res.final_rmse < 0.5
    assert np.median(np.linalg.norm(res.points - X, axis=1)) < 0.01


def test_bundle_adjustment_refines_focal():
    cams = ring_cameras(8, radius=4)
    X = random_points(150, extent=0.8)
    obs, ci, pi = [], [], []
    for c_i, c in enumerate(cams):
        obs.append(c.project(X)[0])
        ci.append(np.full(len(X), c_i))
        pi.append(np.arange(len(X)))
    K_bad = cams[0].K.copy()
    K_bad[0, 0] *= 1.05
    K_bad[1, 1] *= 1.05
    res = bundle_adjust(
        [c.R for c in cams], [c.t for c in cams], X.copy(), np.vstack(obs),
        np.concatenate(ci), np.concatenate(pi), K_bad, fixed_cameras=(0, 1), refine_focal=True,
    )
    assert res.focal == pytest.approx(cams[0].K[0, 0], rel=2e-3)


# ---------------------------------------------------------- validation
def test_validation_flags_bad_geometry():
    cams = ring_cameras(4)
    assert validate_cameras(cams).ok
    bad = ring_cameras(2)
    bad[1].R = bad[1].R * 1.1
    assert not validate_cameras(bad).ok
    rep = validate_point_cloud(np.array([[0, 0, 0], [np.nan, 1, 1], [1, 2, 3.0]]))
    assert not rep.ok
    assert validate_point_cloud(random_points(10), np.zeros((10, 3), np.uint8)).ok
