"""Geometry pipeline unit tests.

Verifies that the backproject → Kabsch/RANSAC → camera-to-body chain in
``relocalization.py`` is mathematically correct, independent of Isaac Sim and
the feature matcher quality.

Run with:
    cd /mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench
    PYTHONPATH=scripts python -m unittest tests/test_geometry_pipeline.py -v
"""

import json
import math
import unittest
from unittest import mock

import numpy as np

from relocalization import (
    backproject_points,
    build_local_map_match_snapshot,
    camera_point_to_body,
    camera_rotation_to_body_yaw,
    corridor_degeneracy_ratio,
    fused_anchor_relocalization,
    local_map_anchor_relocalization,
    quat_wxyz_to_matrix,
    ransac_rigid_transform,
    rigid_transform_3d,
    scan_context_anchor_relocalization,
)
from route_memory_agent import AnchorRelocalization, RouteAnchor, wrap_angle
from scan_context import build_scan_context, column_shift_similarity, shift_to_yaw_rad


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _rotation_z(angle_rad: float) -> np.ndarray:
    c, s = math.cos(angle_rad), math.sin(angle_rad)
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]], dtype=np.float32)


def _rotation_y(angle_rad: float) -> np.ndarray:
    c, s = math.cos(angle_rad), math.sin(angle_rad)
    return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]], dtype=np.float32)


def _rotation_x(angle_rad: float) -> np.ndarray:
    c, s = math.cos(angle_rad), math.sin(angle_rad)
    return np.array([[1, 0, 0], [0, c, -s], [0, s, c]], dtype=np.float32)


def _fallback_camera_to_body() -> np.ndarray:
    return np.array([[0, 0, 1], [-1, 0, 0], [0, -1, 0]], dtype=np.float32)


def _angle_diff(a: float, b: float) -> float:
    return math.atan2(math.sin(a - b), math.cos(a - b))


def _yaw_to_quat_wxyz(yaw: float) -> np.ndarray:
    """Flat (no roll/pitch) yaw rotation as w,x,y,z quaternion."""
    hw = yaw / 2.0
    return np.array([math.cos(hw), 0.0, 0.0, math.sin(hw)], dtype=np.float32)


def _make_intrinsics(fx: float = 256.0, fy: float = 256.0,
                     cx: float = 256.0, cy: float = 256.0) -> np.ndarray:
    return np.array([[fx, 0, cx], [0, fy, cy], [0, 0, 1]], dtype=np.float32)


def _project_to_depth_image(
    points_3d: np.ndarray,
    K: np.ndarray,
    img_size: int = 512,
) -> tuple[np.ndarray, np.ndarray]:
    """Project 3-D camera-frame points to pixel coords + a depth image."""
    fx, fy = float(K[0, 0]), float(K[1, 1])
    cx, cy = float(K[0, 2]), float(K[1, 2])
    depth_image = np.zeros((img_size, img_size), dtype=np.float32)
    uvs = []
    for p in points_3d:
        z = float(p[2])
        if z <= 0:
            uvs.append((-1.0, -1.0))
            continue
        u = fx * float(p[0]) / z + cx
        v = fy * float(p[1]) / z + cy
        ui, vi = int(round(u)), int(round(v))
        if 0 <= ui < img_size and 0 <= vi < img_size:
            depth_image[vi, ui] = z
        uvs.append((u, v))
    return np.asarray(uvs, dtype=np.float32), depth_image


# ---------------------------------------------------------------------------
# Group 1: Kabsch SVD correctness
# ---------------------------------------------------------------------------

class TestRigidTransform3D(unittest.TestCase):

    def _check(self, R_gt, t_gt, n=40, tol=1e-4):
        rng = np.random.default_rng(42)
        source = rng.standard_normal((n, 3)).astype(np.float32) * 3.0
        target = (R_gt @ source.T).T + t_gt
        R_est, t_est = rigid_transform_3d(source, target)
        self.assertIsNotNone(R_est)
        np.testing.assert_allclose(R_est, R_gt, atol=tol,
                                   err_msg="rotation mismatch")
        np.testing.assert_allclose(t_est, t_gt, atol=tol,
                                   err_msg="translation mismatch")

    def test_pure_translation(self):
        self._check(np.eye(3, dtype=np.float32), np.array([1.5, -0.8, 2.3], dtype=np.float32))

    def test_pure_rotation_z(self):
        self._check(_rotation_z(math.radians(37)), np.zeros(3, dtype=np.float32))

    def test_general_transform(self):
        R = _rotation_z(math.radians(45)) @ _rotation_y(math.radians(20))
        t = np.array([3.0, -1.0, 0.5], dtype=np.float32)
        self._check(R.astype(np.float32), t)

    def test_no_reflection(self):
        """det(R) must be +1, not -1 (Kabsch fix for reflections)."""
        rng = np.random.default_rng(7)
        R_gt = _rotation_z(math.radians(120)) @ _rotation_x(math.radians(15))
        source = rng.standard_normal((30, 3)).astype(np.float32)
        target = (R_gt @ source.T).T
        R_est, _ = rigid_transform_3d(source, target)
        self.assertAlmostEqual(float(np.linalg.det(R_est)), 1.0, places=5,
                               msg="rotation must not be a reflection")

    def test_too_few_points_returns_none(self):
        pts = np.eye(2, 3, dtype=np.float32)
        R, t = rigid_transform_3d(pts, pts)
        self.assertIsNone(R)
        self.assertIsNone(t)


# ---------------------------------------------------------------------------
# Group 2: RANSAC robustness
# ---------------------------------------------------------------------------

class TestRansacRigidTransform(unittest.TestCase):

    def _make_data(self, R_gt, t_gt, n=50, outlier_fraction=0.0,
                   noise_sigma=0.0, seed=0):
        rng = np.random.default_rng(seed)
        source = rng.standard_normal((n, 3)).astype(np.float32) * 2.5
        target = (R_gt @ source.T).T + t_gt
        if noise_sigma > 0:
            target += rng.standard_normal(target.shape).astype(np.float32) * noise_sigma
        n_out = int(n * outlier_fraction)
        if n_out > 0:
            target[:n_out] = rng.standard_normal((n_out, 3)).astype(np.float32) * 5.0
        return source, target

    def test_no_outliers_exact_recovery(self):
        R_gt = _rotation_z(math.radians(55)).astype(np.float32)
        t_gt = np.array([2.0, -1.0, 0.3], dtype=np.float32)
        src, tgt = self._make_data(R_gt, t_gt)
        R, t, inliers = ransac_rigid_transform(src, tgt, threshold_m=0.05)
        self.assertIsNotNone(R)
        np.testing.assert_allclose(R, R_gt, atol=1e-4)
        np.testing.assert_allclose(t, t_gt, atol=1e-4)
        self.assertGreaterEqual(int(inliers.sum()), len(src) - 1)

    def test_50_percent_outliers(self):
        R_gt = (_rotation_z(math.radians(30)) @ _rotation_y(math.radians(10))).astype(np.float32)
        t_gt = np.array([1.0, 2.0, -0.5], dtype=np.float32)
        src, tgt = self._make_data(R_gt, t_gt, n=60, outlier_fraction=0.5, seed=1)
        R, t, inliers = ransac_rigid_transform(src, tgt, iterations=200, threshold_m=0.1)
        self.assertIsNotNone(R, "RANSAC should find consensus despite 50% outliers")
        np.testing.assert_allclose(R, R_gt, atol=1e-3)
        np.testing.assert_allclose(t, t_gt, atol=1e-3)

    def test_too_few_points_returns_none(self):
        pts = np.eye(5, 3, dtype=np.float32)
        R, t, inliers = ransac_rigid_transform(pts, pts)
        self.assertIsNone(R)

    def test_inlier_mask_shape(self):
        R_gt = _rotation_z(0.3).astype(np.float32)
        t_gt = np.array([0.5, -0.5, 0.2], dtype=np.float32)
        src, tgt = self._make_data(R_gt, t_gt, n=30)
        R, t, inliers = ransac_rigid_transform(src, tgt)
        self.assertIsNotNone(R)
        self.assertEqual(inliers.shape, (30,))
        self.assertEqual(inliers.dtype, bool)


# ---------------------------------------------------------------------------
# Group 3: camera_point_to_body coordinate-frame conversion
# ---------------------------------------------------------------------------

class TestCameraPointToBody(unittest.TestCase):
    """
    Verify the two paths of camera_point_to_body:

    Fallback (no extrinsic stored):
        body_x = cam_z    (forward = depth)
        body_y = -cam_x   (left    = -right)
        body_z = -cam_y   (up      = -down)

    With extrinsic (rotation_body_camera, camera_position_body):
        p_body = R_body_cam @ p_cam + cam_pos_body

    And the critical oracle consistency check:
        Given anchor camera world pose and current camera / robot world poses,
        the formula must produce the same body-frame anchor position as the
        oracle (world-frame difference projected into body frame).
    """

    def test_fallback_axis_mapping(self):
        """Forward-facing camera: cam-z maps to body-x, cam-x maps to -body-y."""
        # Point 1 m directly in front of camera (cam_z = 1)
        p = np.array([0.0, 0.0, 1.0], dtype=np.float32)
        body = camera_point_to_body(p, {})   # empty descriptor → fallback
        np.testing.assert_allclose(body, [1.0, 0.0, 0.0], atol=1e-6,
                                   err_msg="cam-z should map to body-x (forward)")

    def test_fallback_left_axis(self):
        # Point 1 m to the left in body = -x in camera
        p = np.array([-1.0, 0.0, 0.0], dtype=np.float32)
        body = camera_point_to_body(p, {})
        np.testing.assert_allclose(body, [0.0, 1.0, 0.0], atol=1e-6,
                                   err_msg="cam -x should map to body-y (left)")

    def test_fallback_up_axis(self):
        # Up in body = -y in camera
        p = np.array([0.0, -1.0, 0.0], dtype=np.float32)
        body = camera_point_to_body(p, {})
        np.testing.assert_allclose(body, [0.0, 0.0, 1.0], atol=1e-6,
                                   err_msg="cam -y should map to body-z (up)")

    def test_with_extrinsic_identity_plus_offset(self):
        """Camera is 0.3 m forward of body origin, no rotation — all coords identical."""
        R_body_cam = np.eye(3, dtype=np.float32)
        cam_pos_body = np.array([0.3, 0.0, 0.5], dtype=np.float32)
        descriptor = {
            "camera_rotation_body": R_body_cam,
            "camera_position_body": cam_pos_body,
        }
        p_cam = np.array([0.0, 0.0, 3.0], dtype=np.float32)
        body = camera_point_to_body(p_cam, descriptor)
        # Expected: R_body_cam @ [0,0,3] + [0.3, 0, 0.5] = [0,0,3] + [0.3,0,0.5] = [0.3,0,3.5]
        np.testing.assert_allclose(body, [0.3, 0.0, 3.5], atol=1e-5)

    def test_oracle_consistency(self):
        """
        Core correctness test.

        Given:
          - anchor camera world pose  (Pa_w, Ra_w)
          - current camera world pose (Pc_w, Rc_w)
          - robot body world pose     (Pb_w, Rb_w)

        The feature-depth pipeline computes:
          t_cam  = Rc_w.T @ (Pa_w - Pc_w)   [anchor origin in current cam]
          p_body = R_body_cam @ t_cam + cam_pos_body

        The oracle computes:
          dx_world = Pa_w - Pb_w
          p_body_oracle = Rb_w.T @ dx_world

        These must be equal (analytically derived):
          R_body_cam = Rb_w.T @ Rc_w
          cam_pos_body = Rb_w.T @ (Pc_w - Pb_w)

          p_body = Rb_w.T @ Rc_w @ Rc_w.T @ (Pa_w - Pc_w)
                   + Rb_w.T @ (Pc_w - Pb_w)
                 = Rb_w.T @ (Pa_w - Pc_w + Pc_w - Pb_w)
                 = Rb_w.T @ (Pa_w - Pb_w)
                 = p_body_oracle   ✓
        """
        rng = np.random.default_rng(99)

        # Random anchor camera pose in world
        Pa_w = rng.standard_normal(3).astype(np.float32) * 3.0
        yaw_a = float(rng.uniform(-math.pi, math.pi))
        Ra_w = _rotation_z(yaw_a).astype(np.float32)   # anchor cam → world

        # Random current camera pose in world
        Pc_w = rng.standard_normal(3).astype(np.float32) * 3.0
        yaw_c = float(rng.uniform(-math.pi, math.pi))
        Rc_w = _rotation_z(yaw_c).astype(np.float32)   # current cam → world

        # Random robot body pose in world
        Pb_w = rng.standard_normal(3).astype(np.float32) * 3.0
        yaw_b = float(rng.uniform(-math.pi, math.pi))
        Rb_w = _rotation_z(yaw_b).astype(np.float32)   # body → world

        # Extrinsic of current camera in current body frame
        R_body_cam = (Rb_w.T @ Rc_w).astype(np.float32)
        cam_pos_body = (Rb_w.T @ (Pc_w - Pb_w)).astype(np.float32)

        descriptor = {
            "camera_rotation_body": R_body_cam,
            "camera_position_body": cam_pos_body,
        }

        # t = anchor cam origin in current cam frame (perfect RANSAC result)
        t_cam = (Rc_w.T @ (Pa_w - Pc_w)).astype(np.float32)

        # Feature-depth path
        p_body_feat = camera_point_to_body(t_cam, descriptor)

        # Oracle path: anchor in body frame = Rb_w.T @ (Pa_w - Pb_w)
        p_body_oracle = (Rb_w.T @ (Pa_w - Pb_w)).astype(np.float32)

        np.testing.assert_allclose(
            p_body_feat[:2], p_body_oracle[:2], atol=1e-4,
            err_msg=(
                "feature-depth and oracle anchor positions in body frame must agree.\n"
                f"  feat:   {p_body_feat}\n"
                f"  oracle: {p_body_oracle}"
            ),
        )

    def test_oracle_consistency_multiple_random_poses(self):
        """Run oracle consistency over 20 random pose configurations."""
        rng = np.random.default_rng(123)
        for trial in range(20):
            Pa_w = rng.standard_normal(3).astype(np.float32) * 5.0
            Pc_w = rng.standard_normal(3).astype(np.float32) * 5.0
            Pb_w = rng.standard_normal(3).astype(np.float32) * 5.0

            yaw_c = float(rng.uniform(-math.pi, math.pi))
            yaw_b = float(rng.uniform(-math.pi, math.pi))
            Rc_w = (_rotation_z(yaw_c) @ _rotation_y(float(rng.uniform(-0.3, 0.3)))).astype(np.float32)
            Rb_w = _rotation_z(yaw_b).astype(np.float32)

            R_body_cam = (Rb_w.T @ Rc_w).astype(np.float32)
            cam_pos_body = (Rb_w.T @ (Pc_w - Pb_w)).astype(np.float32)
            descriptor = {
                "camera_rotation_body": R_body_cam,
                "camera_position_body": cam_pos_body,
            }
            t_cam = (Rc_w.T @ (Pa_w - Pc_w)).astype(np.float32)

            feat = camera_point_to_body(t_cam, descriptor)
            oracle = (Rb_w.T @ (Pa_w - Pb_w)).astype(np.float32)

            np.testing.assert_allclose(
                feat[:2], oracle[:2], atol=1e-4,
                err_msg=f"trial {trial}: feat={feat[:2]} oracle={oracle[:2]}",
            )


class TestCameraRotationToBodyYaw(unittest.TestCase):
    """Verify that the 3-D registration rotation is kept as anchor dtheta."""

    def test_fallback_camera_axes_extract_anchor_yaw(self):
        yaw = math.radians(37.0)
        R_body_cam = _fallback_camera_to_body()
        R_cam_body = R_body_cam.T
        R_anchor_to_current_camera = (
            R_cam_body @ _rotation_z(yaw) @ R_body_cam
        ).astype(np.float32)

        dtheta = camera_rotation_to_body_yaw(
            R_anchor_to_current_camera,
            current_descriptor={},
            anchor_descriptor={},
        )

        self.assertAlmostEqual(_angle_diff(dtheta, yaw), 0.0, places=5)

    def test_extrinsic_camera_axes_extract_anchor_yaw(self):
        current_yaw = math.radians(-20.0)
        anchor_yaw = math.radians(55.0)
        expected = _angle_diff(anchor_yaw, current_yaw)

        R_body_cam = _fallback_camera_to_body()
        R_current_world = _rotation_z(current_yaw) @ R_body_cam
        R_anchor_world = _rotation_z(anchor_yaw) @ R_body_cam
        R_anchor_to_current_camera = (
            R_current_world.T @ R_anchor_world
        ).astype(np.float32)

        descriptor = {
            "camera_rotation_body": R_body_cam,
            "camera_position_body": np.zeros(3, dtype=np.float32),
        }
        dtheta = camera_rotation_to_body_yaw(
            R_anchor_to_current_camera,
            current_descriptor=descriptor,
            anchor_descriptor=descriptor,
        )

        self.assertAlmostEqual(_angle_diff(dtheta, expected), 0.0, places=5)


# ---------------------------------------------------------------------------
# Group 4: Full end-to-end synthetic pipeline
# ---------------------------------------------------------------------------

class TestFullPipelineSynthetic(unittest.TestCase):
    """
    Construct a synthetic scene with a known anchor camera pose and a known
    current camera pose, project world 3-D points through both cameras, then
    verify that the backproject → RANSAC → camera_to_body pipeline recovers
    the correct anchor_dx_m / anchor_dy_m.
    """

    def _build_scene(
        self,
        R_anchor_world,   # anchor cam → world
        t_anchor_world,   # anchor cam origin in world
        R_current_world,  # current cam → world
        t_current_world,  # current cam origin in world
        R_body_world,     # robot body → world
        t_body_world,     # robot body origin in world
        n_points=60,
        img_size=512,
        focal=256.0,
        seed=7,
    ):
        rng = np.random.default_rng(seed)
        K = _make_intrinsics(focal, focal, img_size / 2, img_size / 2)

        # Random 3-D world points in front of both cameras
        # Place them along the line between anchor and current, scattered
        world_points = rng.standard_normal((n_points, 3)).astype(np.float32)
        world_points[:, 2] = np.abs(world_points[:, 2]) * 1.5 + 1.5
        midpoint = (t_anchor_world + t_current_world) / 2.0
        world_points += midpoint[None, :]

        # Transform world → anchor cam frame
        anchor_points = (R_anchor_world.T @ (world_points - t_anchor_world[None, :]).T).T
        # Transform world → current cam frame
        current_points = (R_current_world.T @ (world_points - t_current_world[None, :]).T).T

        # Keep points with positive z in both cameras
        valid = (anchor_points[:, 2] > 0.1) & (current_points[:, 2] > 0.1)
        anchor_points = anchor_points[valid]
        current_points = current_points[valid]

        # Project to UV and build depth images
        anchor_uv, anchor_depth = _project_to_depth_image(anchor_points, K, img_size)
        current_uv, current_depth = _project_to_depth_image(current_points, K, img_size)

        # Only keep points whose UV landed inside the image
        inside = (
            (anchor_uv[:, 0] >= 0) & (anchor_uv[:, 0] < img_size) &
            (anchor_uv[:, 1] >= 0) & (anchor_uv[:, 1] < img_size) &
            (current_uv[:, 0] >= 0) & (current_uv[:, 0] < img_size) &
            (current_uv[:, 1] >= 0) & (current_uv[:, 1] < img_size)
        )
        anchor_uv = anchor_uv[inside]
        current_uv = current_uv[inside]

        # Current camera extrinsic in current body frame
        R_body_cam = (R_body_world.T @ R_current_world).astype(np.float32)
        cam_pos_body = (R_body_world.T @ (t_current_world - t_body_world)).astype(np.float32)

        anchor_descriptor = {"camera_intrinsics": K}
        current_descriptor = {
            "camera_intrinsics": K,
            "camera_rotation_body": R_body_cam,
            "camera_position_body": cam_pos_body,
        }

        return (
            anchor_uv, anchor_depth, anchor_descriptor,
            current_uv, current_depth, current_descriptor,
            K,
        )

    def _run_pipeline(
        self,
        anchor_uv, anchor_depth, anchor_descriptor,
        current_uv, current_depth, current_descriptor,
        K,
    ):
        """Backproject → RANSAC → camera_to_body."""
        a_pts, a_valid = backproject_points(anchor_uv, anchor_depth, K)
        c_pts, c_valid = backproject_points(current_uv, current_depth, K)
        valid = sorted(set(a_valid).intersection(c_valid))
        self.assertGreaterEqual(len(valid), 6, "need ≥6 valid 3-D correspondences")

        a_idx = {v: i for i, v in enumerate(a_valid)}
        c_idx = {v: i for i, v in enumerate(c_valid)}
        a_3d = np.asarray([a_pts[a_idx[i]] for i in valid], dtype=np.float32)
        c_3d = np.asarray([c_pts[c_idx[i]] for i in valid], dtype=np.float32)

        R, t, inliers = ransac_rigid_transform(a_3d, c_3d, iterations=200, threshold_m=0.05)
        self.assertIsNotNone(R, "RANSAC failed on perfect synthetic data")
        self.assertGreaterEqual(int(inliers.sum()), 6)

        # t is anchor cam origin in current cam frame
        body = camera_point_to_body(t, current_descriptor)
        return body

    def test_pure_translation_between_cameras(self):
        """Anchor 4 m ahead of current camera; robot body coincides with current cam."""
        R_id = np.eye(3, dtype=np.float32)
        t_anchor_w = np.array([4.0, 0.0, 0.0], dtype=np.float32)   # anchor world pos
        t_current_w = np.zeros(3, dtype=np.float32)                  # current world pos
        t_body_w = np.zeros(3, dtype=np.float32)

        (a_uv, a_depth, a_desc,
         c_uv, c_depth, c_desc, K) = self._build_scene(
            R_id, t_anchor_w, R_id, t_current_w, R_id, t_body_w
        )
        body = self._run_pipeline(a_uv, a_depth, a_desc, c_uv, c_depth, c_desc, K)

        # Expected: anchor at (4,0) in world → body_x=4, body_y=0 (camera z-forward)
        # But camera z is world x here (identity rotation), so:
        # t_cam = R_current.T @ (t_anchor - t_current) = [4,0,0]
        # _camera_point_to_body fallback: body = [cam_z, -cam_x, -cam_y] = [0, -4, 0]
        # Wait — let me recalculate properly.
        # With identity rotations: R_body_cam = I, cam_pos_body = 0
        # body = I @ t_cam + 0 = t_cam = [4, 0, 0]
        # → anchor is 4 m in camera-x direction
        # → anchor_dx = 4 m, anchor_dy = 0 m (camera x IS body x with identity extrinsic)
        np.testing.assert_allclose(body[0], 4.0, atol=0.05,
                                   err_msg="anchor_dx should be 4 m")
        np.testing.assert_allclose(body[1], 0.0, atol=0.05,
                                   err_msg="anchor_dy should be 0")

    def test_yaw_rotated_cameras(self):
        """
        Current camera is yaw-rotated 90° relative to the anchor.
        The oracle says the anchor is in a known direction in body frame;
        the pipeline must agree.
        """
        # Anchor camera looking along +X (yaw=0), at world origin
        R_anchor_w = np.eye(3, dtype=np.float32)
        t_anchor_w = np.zeros(3, dtype=np.float32)

        # Current camera looking along +Y (yaw=90°), 3 m behind (+X direction)
        yaw_c = math.radians(90)
        R_current_w = _rotation_z(yaw_c).astype(np.float32)
        t_current_w = np.array([3.0, 0.0, 0.0], dtype=np.float32)

        # Robot body same as current camera (no offset)
        R_body_w = R_current_w.copy()
        t_body_w = t_current_w.copy()

        (a_uv, a_depth, a_desc,
         c_uv, c_depth, c_desc, K) = self._build_scene(
            R_anchor_w, t_anchor_w,
            R_current_w, t_current_w,
            R_body_w, t_body_w,
        )
        body = self._run_pipeline(a_uv, a_depth, a_desc, c_uv, c_depth, c_desc, K)

        # Oracle: anchor at (0,0), current body at (3,0).
        # world delta = anchor_w - body_w = (-3, 0, 0)
        # body = R_body_w.T @ delta = R_z(-90) @ [-3,0,0] = [0, 3, 0]  (approx)
        # i.e., anchor is 3 m to the left (body_y = 3 m)
        oracle_body = (R_body_w.T @ (t_anchor_w - t_body_w)).astype(np.float32)
        np.testing.assert_allclose(
            body[:2], oracle_body[:2], atol=0.1,
            err_msg=(
                f"pipeline body={body[:2]} does not match oracle={oracle_body[:2]}"
            ),
        )

    def test_consistency_with_oracle_formula_varied_yaw(self):
        """
        10 random camera configurations: pipeline anchor_dx/dy must match oracle.
        This is the key regression test — if it passes, the geometry is correct.
        If it fails, there is a coordinate-frame bug.
        """
        rng = np.random.default_rng(2025)
        failures = []
        evaluated = 0
        for trial in range(20):  # extra trials in case some produce too few points
            yaw_a = float(rng.uniform(-math.pi, math.pi))
            yaw_c = float(rng.uniform(-math.pi, math.pi))
            yaw_b = float(rng.uniform(-math.pi, math.pi))

            R_anchor_w = _rotation_z(yaw_a).astype(np.float32)
            R_current_w = _rotation_z(yaw_c).astype(np.float32)
            R_body_w = _rotation_z(yaw_b).astype(np.float32)

            t_anchor_w = rng.standard_normal(3).astype(np.float32) * 2.0
            t_anchor_w[2] = 0.0
            t_current_w = rng.standard_normal(3).astype(np.float32) * 2.0
            t_current_w[2] = 0.0
            t_body_w = t_current_w + rng.standard_normal(3).astype(np.float32) * 0.3
            t_body_w[2] = 0.0

            try:
                (a_uv, a_depth, a_desc,
                 c_uv, c_depth, c_desc, K) = self._build_scene(
                    R_anchor_w, t_anchor_w,
                    R_current_w, t_current_w,
                    R_body_w, t_body_w,
                    seed=trial,
                )
                body = self._run_pipeline(
                    a_uv, a_depth, a_desc, c_uv, c_depth, c_desc, K
                )
            except AssertionError:
                # Too few projected points for this random config — skip trial
                continue

            evaluated += 1

            oracle = (R_body_w.T @ (t_anchor_w - t_body_w)).astype(np.float32)
            err = float(np.linalg.norm(body[:2] - oracle[:2]))
            if err > 0.15:
                failures.append(
                    f"trial {trial}: err={err:.3f} m  "
                    f"body={body[:2].tolist()} oracle={oracle[:2].tolist()}"
                )

        self.assertGreaterEqual(evaluated, 8,
                               f"Too few evaluable trials ({evaluated}/20); check scene generator")
        self.assertEqual(
            failures, [],
            "Pipeline anchor position does not match oracle for:\n" + "\n".join(failures),
        )


# ---------------------------------------------------------------------------
# P1 (heading-consistency gate) / P2 (corridorness gate) for local_map_icp
# ---------------------------------------------------------------------------

def _corridor_points() -> np.ndarray:
    """Two parallel walls -> normals cluster on one axis -> degenerate."""
    xs = np.linspace(-3.0, 3.0, 60)
    return np.concatenate(
        [
            np.stack([xs, np.full_like(xs, -1.0)], axis=1),
            np.stack([xs, np.full_like(xs, 1.0)], axis=1),
        ]
    ).astype(np.float32)


def _rectangle_outline_points() -> np.ndarray:
    """Closed rectangle outline -> normals span both axes -> well conditioned."""
    top = np.stack([np.linspace(-2.0, 2.0, 40), np.full(40, 1.0)], axis=1)
    bottom = np.stack([np.linspace(-2.0, 2.0, 40), np.full(40, -1.0)], axis=1)
    left = np.stack([np.full(20, -2.0), np.linspace(-1.0, 1.0, 20)], axis=1)
    right = np.stack([np.full(20, 2.0), np.linspace(-1.0, 1.0, 20)], axis=1)
    return np.concatenate([top, bottom, left, right], axis=0).astype(np.float32)


def _rotate_2d(points: np.ndarray, theta: float) -> np.ndarray:
    c, s = math.cos(theta), math.sin(theta)
    rotation = np.array([[c, -s], [s, c]], dtype=np.float32)
    return points @ rotation.T


class TestCorridorDegeneracyRatio(unittest.TestCase):
    """corridor_degeneracy_ratio: PCA eigenvalue ratio of local-normal scatter (P2)."""

    def test_corridor_is_degenerate(self):
        ratio = corridor_degeneracy_ratio(_corridor_points())
        self.assertIsNotNone(ratio)
        self.assertLess(ratio, 0.05, "parallel-wall corridor should score near 0")

    def test_corner_is_well_conditioned(self):
        ratio = corridor_degeneracy_ratio(_rectangle_outline_points())
        self.assertIsNotNone(ratio)
        self.assertGreater(ratio, 0.3, "a closed rectangle outline should score well above the 0.15 skip threshold")

    def test_too_few_points_returns_none(self):
        self.assertIsNone(corridor_degeneracy_ratio(np.zeros((3, 2), dtype=np.float32)))


class TestLocalMapCorridorSkipGate(unittest.TestCase):
    """P2: local_map_anchor_relocalization must skip ICP entirely on a degenerate anchor."""

    def _make_anchor(self, points: np.ndarray) -> RouteAnchor:
        return RouteAnchor(
            index=0,
            pose_from_start=[0.0, 0.0, 0.0],
            distance_from_start_m=5.0,
            route_remaining_to_start_m=5.0,
            descriptor={"local_map_points_body": points},
        )

    def test_corridor_anchor_is_skipped_by_default_threshold(self):
        anchor = self._make_anchor(_corridor_points())
        current_descriptor = {"local_map_points_body": _corridor_points()}
        diagnostics: dict = {}
        result = local_map_anchor_relocalization(
            current_descriptor, [anchor], diagnostics=diagnostics
        )
        self.assertIsNone(result)
        self.assertEqual(diagnostics.get("corridor_degenerate_anchor_skipped"), 1)

    def test_corridor_anchor_is_used_when_gate_disabled(self):
        anchor = self._make_anchor(_corridor_points())
        current_descriptor = {"local_map_points_body": _corridor_points()}
        result = local_map_anchor_relocalization(
            current_descriptor,
            [anchor],
            corridor_degeneracy_skip_threshold=-1.0,
        )
        self.assertIsNotNone(result)

    def test_well_conditioned_anchor_is_not_skipped(self):
        anchor = self._make_anchor(_rectangle_outline_points())
        current_descriptor = {"local_map_points_body": _rectangle_outline_points()}
        diagnostics: dict = {}
        result = local_map_anchor_relocalization(
            current_descriptor, [anchor], diagnostics=diagnostics
        )
        self.assertIsNotNone(result)
        self.assertNotIn("corridor_degenerate_anchor_skipped", diagnostics)


class TestLocalMapHeadingConsistencyGate(unittest.TestCase):
    """P1: local_map_anchor_relocalization must resolve 180-degree ICP ambiguity
    using the caller's dead-reckoning yaw rather than trusting ICP score alone.

    A rectangle outline centered on its own local origin is exactly symmetric
    under a 180-degree rotation about that origin, so for any small true delta
    (dx, dy, dtheta) applied to it, both a theta and a (theta + pi) alignment
    achieve *zero* ICP residual -- reproducing the genuine ambiguity described
    in the README root-cause analysis, not an approximation of it.
    """

    def setUp(self):
        self.anchor_pose_from_start = [1.0, 2.0, 0.5]
        self.true_dtheta = 0.2
        self.true_dx, self.true_dy = 0.3, 0.15
        rect = _rectangle_outline_points()
        self.anchor = RouteAnchor(
            index=0,
            pose_from_start=self.anchor_pose_from_start,
            distance_from_start_m=5.0,
            route_remaining_to_start_m=5.0,
            descriptor={"local_map_points_body": rect},
        )
        current_points = _rotate_2d(rect, self.true_dtheta) + np.array(
            [self.true_dx, self.true_dy], dtype=np.float32
        )
        self.current_descriptor = {"local_map_points_body": current_points}
        # NOTE (2026-07-02, found via a large-rotation regression check): the
        # correct relationship, re-derived from the ICP source/target
        # convention (icp_rigid_transform_2d(anchor_points, current_points)
        # finds theta such that current = R(theta) @ anchor + t), is
        # current_absolute_yaw = anchor_absolute_yaw - dtheta, NOT +dtheta.
        # This file previously used "+" here; it happened to still pass
        # because true_dtheta was small enough (0.2 rad) that the resulting
        # ~23-degree reference error stayed under the 90-degree gate
        # tolerance by coincidence -- a large-angle synthetic case (110 deg)
        # exposed it directly (implied_yaw landed nowhere near either the
        # "+"-convention reference or its flip). The gate implementation
        # itself was already correct; only this test's own ground-truth
        # convention was wrong.
        self.true_absolute_yaw = wrap_angle(self.anchor_pose_from_start[2] - self.true_dtheta)
        self.flipped_absolute_yaw = wrap_angle(self.true_absolute_yaw + math.pi)

    def test_gate_follows_true_yaw_reference(self):
        result = local_map_anchor_relocalization(
            self.current_descriptor, [self.anchor], dead_reckoning_yaw_rad=self.true_absolute_yaw
        )
        self.assertIsNotNone(result)
        self.assertAlmostEqual(
            wrap_angle(result.anchor_dtheta_rad - self.true_dtheta), 0.0, delta=0.05
        )

    def test_gate_follows_flipped_yaw_reference(self):
        """If the caller's own dead-reckoning thinks it is flipped, the gate must
        select the flipped-consistent ICP solution too -- proving it actually
        reads the reference rather than having a fixed preferred branch."""
        result = local_map_anchor_relocalization(
            self.current_descriptor, [self.anchor], dead_reckoning_yaw_rad=self.flipped_absolute_yaw
        )
        self.assertIsNotNone(result)
        expected_flipped_dtheta = wrap_angle(self.true_dtheta + math.pi)
        self.assertAlmostEqual(
            wrap_angle(result.anchor_dtheta_rad - expected_flipped_dtheta), 0.0, delta=0.05
        )

    def test_gate_is_noop_without_dead_reckoning_reference(self):
        """Backward compatibility: omitting dead_reckoning_yaw_rad must still
        return a valid candidate (previous callers/tests are unaffected)."""
        result = local_map_anchor_relocalization(self.current_descriptor, [self.anchor])
        self.assertIsNotNone(result)

    def test_gate_discriminates_at_large_rotation_angle(self):
        """2026-07-02: the small true_dtheta (0.2 rad ~= 11 deg) used by the
        other tests in this class left a ~23-degree reference-sign error
        undetected (both the true and flipped hypotheses still landed on the
        correct side of the 90-degree tolerance by coincidence). A large,
        unambiguous rotation (110 deg, not near 0 or 180) is a much stronger
        check that true/flipped discrimination is correct at scale, not just
        for small angles."""
        anchor_pose_from_start = [1.0, 2.0, 0.5]
        true_dtheta = math.radians(110.0)
        rect = _rectangle_outline_points()
        anchor = RouteAnchor(
            index=0, pose_from_start=anchor_pose_from_start, distance_from_start_m=5.0,
            route_remaining_to_start_m=5.0, descriptor={"local_map_points_body": rect},
        )
        current_points = _rotate_2d(rect, true_dtheta) + np.array([0.3, 0.15], dtype=np.float32)
        current_descriptor = {"local_map_points_body": current_points}
        true_absolute_yaw = wrap_angle(anchor_pose_from_start[2] - true_dtheta)

        result = local_map_anchor_relocalization(
            current_descriptor, [anchor], dead_reckoning_yaw_rad=true_absolute_yaw
        )
        self.assertIsNotNone(result)
        self.assertAlmostEqual(wrap_angle(result.anchor_dtheta_rad - true_dtheta), 0.0, delta=0.1)

    def test_gate_rejects_anchor_when_no_seed_is_consistent(self):
        """With zero tolerance, a reference a few degrees off the true solution's
        own (slightly noisy) ICP estimate must reject the anchor outright rather
        than silently returning an inconsistent pose."""
        implausible_yaw = wrap_angle(self.true_absolute_yaw + math.radians(20.0))
        diagnostics: dict = {}
        result = local_map_anchor_relocalization(
            self.current_descriptor,
            [self.anchor],
            dead_reckoning_yaw_rad=implausible_yaw,
            heading_consistency_max_error_rad=math.radians(5.0),
            diagnostics=diagnostics,
        )
        self.assertIsNone(result)
        self.assertEqual(diagnostics.get("heading_consistency_rejected"), 1)


class TestLocalMapMatchSnapshot(unittest.TestCase):
    """build_local_map_match_snapshot: the anchor/current point-cloud snapshot
    plot_anchor_match_diagnostics.py renders, for opt-in visual diagnosis of
    LiDAR anchor matches (see capture_match_snapshots below)."""

    def test_transform_and_inlier_mask_are_correct(self):
        anchor_points = np.array([[0.0, 0.0], [1.0, 0.0], [0.0, 1.0], [5.0, 5.0]], dtype=np.float32)
        theta = math.pi / 2.0
        translation = np.array([2.0, 3.0], dtype=np.float32)
        # current_points contains exact transforms of the first three anchor
        # points (should be inliers) but not the fourth (should be an outlier).
        current_points = np.array([[2.0, 3.0], [2.0, 4.0], [1.0, 3.0], [-8.0, -8.0]], dtype=np.float32)

        snapshot = build_local_map_match_snapshot(anchor_points, current_points, theta, translation)

        self.assertEqual(snapshot["anchor_inlier_mask"], [True, True, True, False])
        self.assertAlmostEqual(snapshot["theta_rad"], theta, places=5)
        self.assertEqual(snapshot["translation"], [2.0, 3.0])
        # Must be plain JSON-serializable types (no numpy scalars/arrays).
        json.dumps(snapshot)

    def test_snapshot_shapes_match_input_point_counts(self):
        anchor_points = _rectangle_outline_points()
        current_points = _rotate_2d(anchor_points, 0.1) + np.array([0.2, -0.1], dtype=np.float32)
        snapshot = build_local_map_match_snapshot(anchor_points, current_points, 0.1, np.array([0.2, -0.1]))
        self.assertEqual(len(snapshot["anchor_points_body"]), len(anchor_points))
        self.assertEqual(len(snapshot["current_points_body"]), len(current_points))
        self.assertEqual(len(snapshot["anchor_inlier_mask"]), len(anchor_points))


class TestCaptureMatchSnapshotsFlag(unittest.TestCase):
    """capture_match_snapshots: opt-in point-cloud snapshots attached to
    accepted covisibility records for local_map_icp and scan_context, without
    changing the default (off) behavior or any existing scalar metrics."""

    def _make_anchor(self, points: np.ndarray) -> RouteAnchor:
        return RouteAnchor(
            index=0,
            pose_from_start=[0.0, 0.0, 0.0],
            distance_from_start_m=5.0,
            route_remaining_to_start_m=5.0,
            descriptor={"local_map_points_body": points},
        )

    def test_local_map_icp_attaches_snapshot_when_requested(self):
        rect = _rectangle_outline_points()
        anchor = self._make_anchor(rect)
        current_descriptor = {
            "local_map_points_body": _rotate_2d(rect, 0.05) + np.array([0.1, 0.05], dtype=np.float32)
        }
        diagnostics: dict = {}
        result = local_map_anchor_relocalization(
            current_descriptor, [anchor], diagnostics=diagnostics, capture_match_snapshots=True,
        )
        self.assertIsNotNone(result)
        records = [r for r in diagnostics["covisibility_records"] if r.get("outcome") == "pose_candidate"]
        self.assertEqual(len(records), 1)
        snapshot = records[0]["match_snapshot"]
        self.assertEqual(len(snapshot["anchor_inlier_mask"]), len(snapshot["anchor_points_body"]))
        self.assertGreater(sum(snapshot["anchor_inlier_mask"]), 0, "well-aligned rectangles should have inliers")
        json.dumps(snapshot)

    def test_local_map_icp_omits_snapshot_by_default(self):
        rect = _rectangle_outline_points()
        anchor = self._make_anchor(rect)
        current_descriptor = {"local_map_points_body": rect}
        diagnostics: dict = {}
        result = local_map_anchor_relocalization(current_descriptor, [anchor], diagnostics=diagnostics)
        self.assertIsNotNone(result)
        records = [r for r in diagnostics["covisibility_records"] if r.get("outcome") == "pose_candidate"]
        self.assertEqual(len(records), 1)
        self.assertNotIn("match_snapshot", records[0])

    def test_scan_context_attaches_snapshot_when_requested(self):
        rect = _rectangle_outline_points()
        anchor = self._make_anchor(rect)
        current_descriptor = {"local_map_points_body": rect}
        diagnostics: dict = {}
        result = scan_context_anchor_relocalization(
            current_descriptor, [anchor], diagnostics=diagnostics, capture_match_snapshots=True,
        )
        self.assertIsNotNone(result)
        records = [r for r in diagnostics.get("covisibility_records", []) if r.get("outcome") == "pose_candidate"]
        self.assertEqual(len(records), 1)
        snapshot = records[0]["match_snapshot"]
        self.assertIn("anchor_points_body", snapshot)
        json.dumps(snapshot)

    def test_scan_context_omits_snapshot_by_default(self):
        rect = _rectangle_outline_points()
        anchor = self._make_anchor(rect)
        current_descriptor = {"local_map_points_body": rect}
        diagnostics: dict = {}
        result = scan_context_anchor_relocalization(current_descriptor, [anchor], diagnostics=diagnostics)
        self.assertIsNotNone(result)
        self.assertNotIn("covisibility_records", diagnostics)


# ---------------------------------------------------------------------------
# P3: Scan Context (2026-07-02)
# ---------------------------------------------------------------------------

def _l_shape_points(offset=(0.0, 0.0)) -> np.ndarray:
    arm1 = np.stack([np.linspace(0.5, 4.0, 40), np.zeros(40)], axis=1)
    arm2 = np.stack([np.zeros(40), np.linspace(0.5, 4.0, 40)], axis=1)
    pts = np.concatenate([arm1, arm2], axis=0).astype(np.float32)
    return pts + np.array(offset, dtype=np.float32)


def _point_at_cell(
    ring: int, sector: int, num_rings: int = 20, num_sectors: int = 60,
    max_radius_m: float = 6.0, height: float = 1.0,
    radial_jitter: float = 0.0, sector_frac: float = 0.5,
) -> list:
    """A single (x, y, z) point landing at a specific (ring, sector) Scan
    Context cell (optionally offset radially and/or within the sector's
    angular span), for tests that need exact control over which grid cells
    end up occupied (e.g. scattered vs. connected regions)."""
    r = (ring + 0.5) * max_radius_m / num_rings + radial_jitter
    theta = (sector + sector_frac) * 2.0 * math.pi / num_sectors
    return [r * math.cos(theta), r * math.sin(theta), height]


def _points_at_cell(ring: int, sector: int, count: int = 16, **kwargs) -> list:
    """``count`` distinct points inside the same cell (spread across a small
    grid of radial x within-sector-angle jitter, never crossing into a
    neighboring ring or sector) with > voxel_downsample_2d's default 0.12 m
    spacing between combinations so enough of them survive its dedup as
    separate points. scan_context_anchor_relocalization requires >= 12 raw
    (and >= 12 post-voxel-downsample) points as a basic "is this real data"
    sanity floor, well above what a test targeting a handful of specific grid
    cells would naturally produce with single points; a plain 1-D radial-only
    spread doesn't reliably clear this for small cell counts (2026-07-02:
    found via a test that lost points to voxel-downsample dedup), so this
    spreads jitter across two axes instead."""
    radial_vals = np.linspace(-0.13, 0.13, 5)
    frac_vals = np.linspace(0.15, 0.85, 5)
    combos = [(r, f) for r in radial_vals for f in frac_vals]
    return [
        _point_at_cell(ring, sector, radial_jitter=combos[i % len(combos)][0],
                        sector_frac=combos[i % len(combos)][1], **kwargs)
        for i in range(count)
    ]


def _straight_corridor_points() -> np.ndarray:
    xs = np.linspace(-3.0, 3.0, 60)
    return np.concatenate(
        [
            np.stack([xs, np.full_like(xs, -1.0)], axis=1),
            np.stack([xs, np.full_like(xs, 1.0)], axis=1),
        ]
    ).astype(np.float32)


class TestScanContextDescriptor(unittest.TestCase):
    """Pure descriptor/similarity math (no anchors, no AnchorRelocalization)."""

    def test_column_shift_recovers_known_rotation(self):
        base = _l_shape_points()
        true_rotation = math.radians(42.0)  # exact multiple of the 6-deg sector width
        c, s = math.cos(true_rotation), math.sin(true_rotation)
        rotation = np.array([[c, -s], [s, c]], dtype=np.float32)
        rotated = base @ rotation.T

        sc_a = build_scan_context(rotated)
        sc_b = build_scan_context(base)
        similarity, shift = column_shift_similarity(sc_a, sc_b)
        recovered_yaw = shift_to_yaw_rad(shift, sc_a.shape[1])

        self.assertAlmostEqual(similarity, 1.0, places=3)
        self.assertAlmostEqual(recovered_yaw, true_rotation, delta=math.radians(3.0))

    def test_distinct_shapes_score_low_similarity(self):
        sc_a = build_scan_context(_l_shape_points())
        sc_b = build_scan_context(_straight_corridor_points())
        similarity, _ = column_shift_similarity(sc_a, sc_b)
        self.assertLess(similarity, 0.6)

    def test_empty_point_cloud_returns_zero_grid(self):
        grid = build_scan_context(np.zeros((0, 2), dtype=np.float32))
        self.assertEqual(float(grid.sum()), 0.0)


class TestScanContextAnchorRelocalization(unittest.TestCase):
    """End-to-end: does Scan Context pick the right anchor, and correctly
    refuse to pick one when candidates are genuinely ambiguous (the 2026-07-02
    ep994 "wide plausible basin" failure mode)?"""

    def _anchor(self, index, points):
        return RouteAnchor(
            index=index,
            pose_from_start=[float(index), 0.0, 0.0],
            distance_from_start_m=float(index),
            route_remaining_to_start_m=float(index),
            descriptor={"local_map_points_body": points},
        )

    def test_identifies_correct_anchor_among_distinct_shapes(self):
        anchor_a = self._anchor(0, _l_shape_points())
        anchor_b = self._anchor(1, _straight_corridor_points())
        current_descriptor = {"local_map_points_body": _l_shape_points(offset=(0.1, 0.05))}

        result = scan_context_anchor_relocalization(current_descriptor, [anchor_a, anchor_b])

        self.assertIsNotNone(result)
        self.assertEqual(result.anchor_index, 0)
        self.assertAlmostEqual(result.anchor_dx_m, 0.1, delta=0.1)
        self.assertAlmostEqual(result.anchor_dy_m, 0.05, delta=0.1)
        self.assertTrue(result.anchor_heading_reliable)

    def test_refuses_to_pick_between_ambiguous_candidates(self):
        """This is the core ep994 fix: two anchors whose global occupancy
        pattern is indistinguishable from the current view must not be
        resolved by whichever one happens to score a hair higher -- unlike
        local_map_icp's per-candidate residual score, which has no way to
        express 'these are equally plausible, I don't actually know which.'"""
        anchor_c = self._anchor(2, _straight_corridor_points())
        anchor_d = self._anchor(3, _straight_corridor_points())
        current_descriptor = {"local_map_points_body": _straight_corridor_points()}
        diagnostics: dict = {}

        result = scan_context_anchor_relocalization(
            current_descriptor, [anchor_c, anchor_d], diagnostics=diagnostics
        )

        self.assertIsNone(result)
        self.assertEqual(diagnostics.get("scan_context_ambiguous_margin"), 1)

    def test_clear_winner_is_not_blocked_by_margin_check(self):
        """A weakly-similar runner-up must not veto an otherwise clear winner."""
        anchor_a = self._anchor(0, _l_shape_points())
        anchor_b = self._anchor(1, _straight_corridor_points())
        current_descriptor = {"local_map_points_body": _l_shape_points()}

        result = scan_context_anchor_relocalization(current_descriptor, [anchor_a, anchor_b])
        self.assertIsNotNone(result)
        self.assertEqual(result.anchor_index, 0)

    def test_diffuse_scattered_match_is_rejected_despite_high_similarity(self):
        """2026-07-02: a winner whose agreement is scattered thinly across the
        grid (no single connected chunk) must be rejected even if its average
        column similarity is high -- this is the actual ep994 "wide plausible
        basin" mechanism: a big generic area can score well on average without
        any real, spatially coherent match. Six isolated matching cells, each
        10 sectors apart (nowhere near adjacent), score a perfect 1.0 average
        similarity (every non-empty column matches exactly) but the largest
        connected region is a single cell."""
        current_points = np.array(
            [pt for s in (0, 10, 20, 30, 40, 50) for pt in _points_at_cell(5, s)],
            dtype=np.float32,
        )
        anchor_points = current_points.copy()  # identical scattered cells
        anchor = self._anchor(0, anchor_points)
        current_descriptor = {"local_map_points_body": current_points}
        diagnostics: dict = {}

        result = scan_context_anchor_relocalization(
            current_descriptor, [anchor], diagnostics=diagnostics
        )

        self.assertIsNone(result)
        self.assertAlmostEqual(diagnostics.get("last_scan_context_best_similarity"), 1.0, places=5)
        self.assertEqual(diagnostics.get("last_scan_context_best_region_size"), 1)
        self.assertEqual(diagnostics.get("scan_context_diffuse_match"), 1)

    def test_concentrated_match_with_same_similarity_is_accepted(self):
        """Counterpart to the diffuse-match test above: the same six-cell
        count, but placed as one contiguous block, must be accepted -- proving
        the new gate discriminates on connectivity specifically, not just on
        having "fewer" occupied cells."""
        current_points = np.array(
            [pt for s in range(0, 6) for pt in _points_at_cell(5, s)], dtype=np.float32
        )
        anchor_points = current_points.copy()
        anchor = self._anchor(0, anchor_points)
        current_descriptor = {"local_map_points_body": current_points}
        diagnostics: dict = {}

        result = scan_context_anchor_relocalization(
            current_descriptor, [anchor], diagnostics=diagnostics
        )

        self.assertIsNotNone(result)
        self.assertEqual(result.anchor_index, 0)
        self.assertEqual(diagnostics.get("last_scan_context_best_region_size"), 6)

    def test_height_profile_distinguishes_candidates_with_identical_footprint(self):
        """2026-07-02: two candidate anchors share the exact same xy occupancy
        footprint (same cells occupied) but have opposite height profiles --
        binary occupancy (this project's original Scan Context simplification)
        cannot tell them apart at all; the restored max-height-per-cell
        encoding (closer to Kim & Kim 2018) must prefer the one whose height
        profile actually matches the current view."""
        near_ring, far_ring, sector = 3, 12, 20
        current_points = np.array(
            _points_at_cell(near_ring, sector, height=0.1)
            + _points_at_cell(far_ring, sector, height=1.7),
            dtype=np.float32,
        )
        matching_anchor_points = current_points.copy()
        reversed_anchor_points = np.array(
            _points_at_cell(near_ring, sector, height=1.7)
            + _points_at_cell(far_ring, sector, height=0.1),
            dtype=np.float32,
        )
        anchor_match = self._anchor(0, matching_anchor_points)
        anchor_reversed = self._anchor(1, reversed_anchor_points)
        current_descriptor = {"local_map_points_body": current_points}

        result = scan_context_anchor_relocalization(
            current_descriptor, [anchor_match, anchor_reversed],
            min_connected_region_cells=1,
        )

        self.assertIsNotNone(result)
        self.assertEqual(result.anchor_index, 0)


class TestScanContextHeadingConsistencyGate(unittest.TestCase):
    """2026-07-02 fix: Scan Context's own column-shift search spans the full
    360 degrees, so a 180-degree-symmetric anchor shape is just as ambiguous
    to it as it is to local_map_icp's un-gated yaw search -- confirmed on the
    first real batch (ep994 bearing error sat at a stable ~178 deg for many
    consecutive steps). Reuses the same rectangle-outline construction as
    TestLocalMapHeadingConsistencyGate: exactly symmetric under 180-degree
    rotation about its own centroid, so both a theta and a (theta + pi)
    alignment achieve zero residual -- a genuine tie, not an approximation."""

    def setUp(self):
        self.anchor_pose_from_start = [1.0, 2.0, 0.5]
        self.true_dtheta = 0.2
        self.true_dx, self.true_dy = 0.3, 0.15
        rect = _rectangle_outline_points()
        self.anchor = RouteAnchor(
            index=0,
            pose_from_start=self.anchor_pose_from_start,
            distance_from_start_m=5.0,
            route_remaining_to_start_m=5.0,
            descriptor={"local_map_points_body": rect},
        )
        current_points = _rotate_2d(rect, self.true_dtheta) + np.array(
            [self.true_dx, self.true_dy], dtype=np.float32
        )
        self.current_descriptor = {"local_map_points_body": current_points}
        # NOTE (2026-07-02, found via a large-rotation regression check): the
        # correct relationship, re-derived from the ICP source/target
        # convention (icp_rigid_transform_2d(anchor_points, current_points)
        # finds theta such that current = R(theta) @ anchor + t), is
        # current_absolute_yaw = anchor_absolute_yaw - dtheta, NOT +dtheta.
        # This file previously used "+" here; it happened to still pass
        # because true_dtheta was small enough (0.2 rad) that the resulting
        # ~23-degree reference error stayed under the 90-degree gate
        # tolerance by coincidence -- a large-angle synthetic case (110 deg)
        # exposed it directly (implied_yaw landed nowhere near either the
        # "+"-convention reference or its flip). The gate implementation
        # itself was already correct; only this test's own ground-truth
        # convention was wrong.
        self.true_absolute_yaw = wrap_angle(self.anchor_pose_from_start[2] - self.true_dtheta)
        self.flipped_absolute_yaw = wrap_angle(self.true_absolute_yaw + math.pi)

    def test_gate_follows_true_yaw_reference(self):
        result = scan_context_anchor_relocalization(
            self.current_descriptor, [self.anchor], dead_reckoning_yaw_rad=self.true_absolute_yaw
        )
        self.assertIsNotNone(result)
        self.assertAlmostEqual(
            wrap_angle(result.anchor_dtheta_rad - self.true_dtheta), 0.0, delta=0.1
        )

    def test_gate_follows_flipped_yaw_reference(self):
        result = scan_context_anchor_relocalization(
            self.current_descriptor, [self.anchor], dead_reckoning_yaw_rad=self.flipped_absolute_yaw
        )
        self.assertIsNotNone(result)
        expected_flipped_dtheta = wrap_angle(self.true_dtheta + math.pi)
        self.assertAlmostEqual(
            wrap_angle(result.anchor_dtheta_rad - expected_flipped_dtheta), 0.0, delta=0.1
        )

    def test_gate_is_noop_without_dead_reckoning_reference(self):
        """Backward compatibility: omitting dead_reckoning_yaw_rad must still
        return a valid candidate."""
        result = scan_context_anchor_relocalization(self.current_descriptor, [self.anchor])
        self.assertIsNotNone(result)

    def test_gate_discriminates_at_large_rotation_angle(self):
        """2026-07-02: same rationale as
        TestLocalMapHeadingConsistencyGate.test_gate_discriminates_at_large_rotation_angle
        -- this class's small true_dtheta (0.2 rad) left a ~23-degree
        reference-sign error undetected. This is also a regression check for
        the seed-coverage fix: the first real batch
        (scan_context_p3_flipfix_187_680_994_20260702) still showed ~170+ deg
        bearing errors after the narrow +/-20-degree dual-hypothesis seeding
        was replaced by a full 24-seed sweep against the selected anchor."""
        anchor_pose_from_start = [1.0, 2.0, 0.5]
        true_dtheta = math.radians(110.0)
        rect = _rectangle_outline_points()
        anchor = RouteAnchor(
            index=0, pose_from_start=anchor_pose_from_start, distance_from_start_m=5.0,
            route_remaining_to_start_m=5.0, descriptor={"local_map_points_body": rect},
        )
        current_points = _rotate_2d(rect, true_dtheta) + np.array([0.3, 0.15], dtype=np.float32)
        current_descriptor = {"local_map_points_body": current_points}
        true_absolute_yaw = wrap_angle(anchor_pose_from_start[2] - true_dtheta)

        result = scan_context_anchor_relocalization(
            current_descriptor, [anchor], dead_reckoning_yaw_rad=true_absolute_yaw
        )
        self.assertIsNotNone(result)
        self.assertAlmostEqual(wrap_angle(result.anchor_dtheta_rad - true_dtheta), 0.0, delta=0.1)


# ---------------------------------------------------------------------------
# RGB-D + LiDAR fusion (2026-07-02)
# ---------------------------------------------------------------------------
# These test the *orchestration/agreement* logic in fused_anchor_relocalization
# in isolation from the two underlying backends it combines (each of which
# already has its own dedicated tests above and in test_loftr_matching.py).
# Mocking the two backend calls is the right tool here specifically because
# what's under test is "does the fusion policy combine two independent
# results correctly," not "does LoFTR/Scan Context individually work" --
# constructing a real RGB-D scene just to exercise the merge logic would test
# the wrong thing and be needlessly fragile.

class TestFusedAnchorRelocalization(unittest.TestCase):
    def test_agreement_fuses_both_estimates_with_boosted_confidence(self):
        rgbd = AnchorRelocalization(
            anchor_index=3, anchor_dx_m=1.0, anchor_dy_m=0.5, anchor_dtheta_rad=0.10,
            confidence=0.6, backend="loftr", inlier_count=20,
        )
        lidar = AnchorRelocalization(
            anchor_index=3, anchor_dx_m=1.05, anchor_dy_m=0.55, anchor_dtheta_rad=0.14,
            confidence=0.7, backend="scan_context", inlier_count=30,
        )
        with mock.patch("relocalization.feature_depth_anchor_relocalization", return_value=rgbd), \
             mock.patch("relocalization.scan_context_anchor_relocalization", return_value=lidar):
            result = fused_anchor_relocalization({}, [])

        self.assertIsNotNone(result)
        self.assertEqual(result.anchor_index, 3)
        self.assertEqual(result.backend, "fused_loftr_scan_context")
        self.assertAlmostEqual(result.anchor_dx_m, 1.0269, places=3)
        self.assertGreater(result.confidence, max(rgbd.confidence, lidar.confidence))

    def test_disagreement_on_anchor_identity_yields_no_candidate(self):
        rgbd = AnchorRelocalization(anchor_index=3, anchor_dx_m=1.0, anchor_dy_m=0.5, confidence=0.6, backend="loftr")
        lidar = AnchorRelocalization(anchor_index=7, anchor_dx_m=1.0, anchor_dy_m=0.5, confidence=0.6, backend="scan_context")
        diagnostics: dict = {}
        with mock.patch("relocalization.feature_depth_anchor_relocalization", return_value=rgbd), \
             mock.patch("relocalization.scan_context_anchor_relocalization", return_value=lidar):
            result = fused_anchor_relocalization({}, [], diagnostics=diagnostics)

        self.assertIsNone(result)
        self.assertEqual(diagnostics.get("fused_disagreement_different_anchor"), 1)

    def test_disagreement_on_pose_for_same_anchor_yields_no_candidate(self):
        rgbd = AnchorRelocalization(anchor_index=3, anchor_dx_m=1.0, anchor_dy_m=0.5, anchor_dtheta_rad=0.0, confidence=0.6, backend="loftr")
        lidar = AnchorRelocalization(anchor_index=3, anchor_dx_m=4.0, anchor_dy_m=0.5, anchor_dtheta_rad=0.0, confidence=0.6, backend="scan_context")
        diagnostics: dict = {}
        with mock.patch("relocalization.feature_depth_anchor_relocalization", return_value=rgbd), \
             mock.patch("relocalization.scan_context_anchor_relocalization", return_value=lidar):
            result = fused_anchor_relocalization({}, [], diagnostics=diagnostics)

        self.assertIsNone(result)
        self.assertEqual(diagnostics.get("fused_disagreement_same_anchor_different_pose"), 1)

    def test_single_source_lidar_only_is_used_at_reduced_confidence(self):
        """LoFTR fails (e.g. zero covisibility, camera facing the wrong way
        during return) but Scan Context, being omnidirectional, still
        succeeds -- exactly the complementary-failure-mode scenario that
        motivated fusing the two backends in the first place."""
        lidar = AnchorRelocalization(anchor_index=5, anchor_dx_m=2.0, anchor_dy_m=-1.0, confidence=0.8, backend="scan_context")
        with mock.patch("relocalization.feature_depth_anchor_relocalization", return_value=None), \
             mock.patch("relocalization.scan_context_anchor_relocalization", return_value=lidar):
            result = fused_anchor_relocalization({}, [])

        self.assertIsNotNone(result)
        self.assertEqual(result.anchor_index, 5)
        self.assertEqual(result.backend, "scan_context+fused_single")
        self.assertLess(result.confidence, lidar.confidence)

    def test_both_backends_silent_yields_no_candidate(self):
        with mock.patch("relocalization.feature_depth_anchor_relocalization", return_value=None), \
             mock.patch("relocalization.scan_context_anchor_relocalization", return_value=None):
            result = fused_anchor_relocalization({}, [])
        self.assertIsNone(result)


class TestFusedDiagnosticsAccumulateAcrossCalls(unittest.TestCase):
    """2026-07-03: fused_anchor_relocalization used to build a fresh {} for
    rgbd_diag/lidar_diag on every call and wholesale-overwrite
    diagnostics["fused_rgbd_diagnostics"]/["fused_lidar_diagnostics"] each
    time -- across a whole episode's worth of calls, only the LAST call's
    per-anchor covisibility_records (and match_snapshot) ever survived into
    the saved measurement JSON, silently discarding every earlier attempt.
    Fixed via diagnostics.setdefault(...) so the same nested dict is reused
    call over call; this locks in that a real (non-mocked) Scan Context path
    across multiple fused_anchor_relocalization calls accumulates instead of
    resetting."""

    def _make_anchor(self, points: np.ndarray) -> RouteAnchor:
        return RouteAnchor(
            index=0,
            pose_from_start=[0.0, 0.0, 0.0],
            distance_from_start_m=5.0,
            route_remaining_to_start_m=5.0,
            descriptor={"local_map_points_body": points},
        )

    def test_two_calls_accumulate_lidar_covisibility_records(self):
        rect = _rectangle_outline_points()
        anchor = self._make_anchor(rect)
        current_descriptor = {"local_map_points_body": rect}
        diagnostics: dict = {}
        with mock.patch("relocalization.feature_depth_anchor_relocalization", return_value=None):
            for _ in range(2):
                fused_anchor_relocalization(
                    current_descriptor, [anchor], diagnostics=diagnostics, capture_match_snapshots=True,
                )
        lidar_diag = diagnostics.get("fused_lidar_diagnostics", {})
        self.assertEqual(lidar_diag.get("attempts"), 2, "scalar counters must accumulate, not reset, across calls")
        records = [r for r in lidar_diag.get("covisibility_records", []) if r.get("outcome") == "pose_candidate"]
        self.assertEqual(len(records), 2, "both calls' match snapshots must survive, not just the last one")
        for record in records:
            json.dumps(record["match_snapshot"])


if __name__ == "__main__":
    unittest.main()
