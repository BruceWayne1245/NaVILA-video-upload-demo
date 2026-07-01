"""Geometry pipeline unit tests.

Verifies that the backproject → Kabsch/RANSAC → camera-to-body chain in
``relocalization.py`` is mathematically correct, independent of Isaac Sim and
the feature matcher quality.

Run with:
    cd /mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench
    PYTHONPATH=scripts python -m unittest tests/test_geometry_pipeline.py -v
"""

import math
import unittest

import numpy as np

from relocalization import (
    backproject_points,
    build_rear_view_descriptor,
    camera_point_to_body,
    camera_rotation_to_body_yaw,
    descriptor_depth,
    local_map_anchor_relocalization,
    quat_wxyz_to_matrix,
    ransac_rigid_transform,
    rigid_transform_3d,
)
from route_memory_agent import RouteAnchor


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

    def test_rear_view_descriptor_exposes_standard_fields(self):
        descriptor = {
            "rear_rgb": np.zeros((4, 4, 3), dtype=np.uint8),
            "rear_depth_depth_measurement": np.ones((4, 4), dtype=np.float32),
            "rear_camera_intrinsics": np.eye(3, dtype=np.float32),
            "rear_camera_rotation_body": np.eye(3, dtype=np.float32),
            "rear_camera_position_body": np.array([0.1, 0.0, 0.5], dtype=np.float32),
        }

        rear = build_rear_view_descriptor(descriptor)

        self.assertIsNotNone(rear)
        self.assertEqual(rear["view"], "rear")
        self.assertIn("rgb", rear)
        np.testing.assert_allclose(descriptor_depth(rear), np.ones((4, 4), dtype=np.float32))
        np.testing.assert_allclose(rear["camera_intrinsics"], np.eye(3, dtype=np.float32))

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


class TestLocalMapRelocalizationSynthetic(unittest.TestCase):
    def test_lidar_local_map_recovers_anchor_pose_in_current_body(self):
        anchor_points = np.asarray(
            [
                [-1.2, -0.8], [-0.6, -0.8], [0.0, -0.8], [0.6, -0.8], [1.2, -0.8],
                [-1.2, 0.2], [-0.6, 0.2], [0.0, 0.2], [0.6, 0.2], [1.2, 0.2],
                [-0.9, 1.1], [-0.2, 1.4], [0.7, 1.3],
                [1.4, -0.3], [1.6, 0.4], [1.7, 1.1],
                [-1.5, 0.6], [-1.7, 1.0], [-1.8, 1.4],
                [0.2, -1.4], [0.9, -1.6], [1.5, -1.5],
            ],
            dtype=np.float32,
        )
        theta = math.radians(155.0)
        translation = np.asarray([1.35, -0.55], dtype=np.float32)
        rot = np.asarray(
            [[math.cos(theta), -math.sin(theta)], [math.sin(theta), math.cos(theta)]],
            dtype=np.float32,
        )
        current_points = (anchor_points @ rot.T + translation).astype(np.float32)
        current_points = np.concatenate(
            [
                current_points,
                np.asarray([[2.2, 1.7], [-2.0, -1.8], [2.4, -1.5]], dtype=np.float32),
            ],
            axis=0,
        )
        distractor_points = anchor_points * np.asarray([1.0, -1.0], dtype=np.float32) + 3.0
        anchors = [
            RouteAnchor(
                index=0,
                pose_from_start=[0.0, 0.0, 0.0],
                distance_from_start_m=0.0,
                route_remaining_to_start_m=0.0,
                descriptor={"local_map_points_body": distractor_points},
            ),
            RouteAnchor(
                index=1,
                pose_from_start=[1.0, 0.0, 0.0],
                distance_from_start_m=1.0,
                route_remaining_to_start_m=1.0,
                descriptor={"local_map_points_body": anchor_points},
            ),
        ]

        result = local_map_anchor_relocalization(
            {"local_map_points_body": current_points},
            anchors,
            return_candidates=False,
        )

        self.assertIsNotNone(result)
        self.assertEqual(result.anchor_index, 1)
        self.assertEqual(result.backend, "local_map_icp")
        self.assertAlmostEqual(result.anchor_dx_m, float(translation[0]), delta=0.10)
        self.assertAlmostEqual(result.anchor_dy_m, float(translation[1]), delta=0.10)
        self.assertAlmostEqual(_angle_diff(result.anchor_dtheta_rad, theta), 0.0, delta=math.radians(5.0))
        self.assertGreaterEqual(result.confidence, 0.5)


if __name__ == "__main__":
    unittest.main()
