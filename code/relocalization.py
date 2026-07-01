"""Pure-geometry relocalization utilities for round-trip VLN evaluation.

All functions here depend only on numpy / math / cv2 / torch (optional, for
LoFTR).  Keeping them in a separate module allows unit-testing outside the
Isaac Sim environment (which requires a full headless GPU launch to import).
"""

from __future__ import annotations

import math
from typing import Optional

import numpy as np

try:
    import cv2
except Exception:  # pragma: no cover - exercised only in minimal test envs
    cv2 = None


# ---------------------------------------------------------------------------
# Descriptor field accessors
# ---------------------------------------------------------------------------

def descriptor_depth(descriptor: object) -> Optional[np.ndarray]:
    if not isinstance(descriptor, dict):
        return None
    for key in ("depth_depth_measurement", "depth_obs"):
        depth = descriptor.get(key)
        if isinstance(depth, np.ndarray):
            return np.asarray(depth, dtype=np.float32)
    return None


def descriptor_rgb_gray(descriptor: object) -> Optional[np.ndarray]:
    if not isinstance(descriptor, dict):
        return None
    rgb = descriptor.get("rgb")
    if not isinstance(rgb, np.ndarray):
        return None
    rgb = np.asarray(rgb)
    if rgb.ndim != 3 or rgb.shape[2] < 3:
        return None
    if rgb.dtype != np.uint8:
        rgb = np.clip(rgb, 0, 255).astype(np.uint8)
    if cv2 is None:
        return np.dot(rgb[:, :, :3], [0.299, 0.587, 0.114]).astype(np.uint8)
    return cv2.cvtColor(rgb[:, :, :3], cv2.COLOR_RGB2GRAY)


def descriptor_rear_depth(descriptor: object) -> Optional[np.ndarray]:
    if not isinstance(descriptor, dict):
        return None
    for key in ("rear_depth_depth_measurement", "rear_depth_obs"):
        depth = descriptor.get(key)
        if isinstance(depth, np.ndarray):
            return np.asarray(depth, dtype=np.float32)
    return None


def descriptor_rear_rgb_gray(descriptor: object) -> Optional[np.ndarray]:
    if not isinstance(descriptor, dict):
        return None
    rgb = descriptor.get("rear_rgb")
    if not isinstance(rgb, np.ndarray):
        return None
    rgb = np.asarray(rgb)
    if rgb.ndim != 3 or rgb.shape[2] < 3:
        return None
    if rgb.dtype != np.uint8:
        rgb = np.clip(rgb, 0, 255).astype(np.uint8)
    if cv2 is None:
        return np.dot(rgb[:, :, :3], [0.299, 0.587, 0.114]).astype(np.uint8)
    return cv2.cvtColor(rgb[:, :, :3], cv2.COLOR_RGB2GRAY)


def build_rear_view_descriptor(descriptor: object) -> Optional[dict]:
    """Expose a saved rear RGB-D view through the standard descriptor fields."""
    if not isinstance(descriptor, dict):
        return None
    rear_depth = descriptor_rear_depth(descriptor)
    rear_rgb = descriptor.get("rear_rgb")
    if rear_depth is None or not isinstance(rear_rgb, np.ndarray):
        return None
    rear = dict(descriptor)
    rear["rgb"] = np.asarray(rear_rgb).copy()
    rear["depth_obs"] = np.asarray(rear_depth, dtype=np.float32).copy()
    if isinstance(descriptor.get("rear_camera_intrinsics"), np.ndarray):
        rear["camera_intrinsics"] = np.asarray(
            descriptor["rear_camera_intrinsics"], dtype=np.float32
        ).reshape(3, 3)
    if isinstance(descriptor.get("rear_camera_position_w"), np.ndarray):
        rear["camera_position_w"] = np.asarray(
            descriptor["rear_camera_position_w"], dtype=np.float32
        ).reshape(3)
    if isinstance(descriptor.get("rear_camera_quat_wxyz"), np.ndarray):
        rear["camera_quat_wxyz"] = np.asarray(
            descriptor["rear_camera_quat_wxyz"], dtype=np.float32
        ).reshape(4)
    if isinstance(descriptor.get("rear_camera_rotation_body"), np.ndarray):
        rear["camera_rotation_body"] = np.asarray(
            descriptor["rear_camera_rotation_body"], dtype=np.float32
        ).reshape(3, 3)
    if isinstance(descriptor.get("rear_camera_position_body"), np.ndarray):
        rear["camera_position_body"] = np.asarray(
            descriptor["rear_camera_position_body"], dtype=np.float32
        ).reshape(3)
    rear["view"] = "rear"
    return rear


def descriptor_intrinsics(
    descriptor: object, width: int = 512, height: int = 512
) -> np.ndarray:
    if isinstance(descriptor, dict) and isinstance(
        descriptor.get("camera_intrinsics"), np.ndarray
    ):
        return np.asarray(descriptor["camera_intrinsics"], dtype=np.float32).reshape(3, 3)
    focal = 0.5 * float(width) / math.tan(math.radians(90.0) / 2.0)
    return np.asarray(
        [[focal, 0.0, width / 2.0], [0.0, focal, height / 2.0], [0.0, 0.0, 1.0]],
        dtype=np.float32,
    )


def descriptor_camera_pose(
    descriptor: object,
) -> Optional[tuple[np.ndarray, np.ndarray]]:
    if not isinstance(descriptor, dict):
        return None
    position = descriptor.get("camera_position_w")
    quat = descriptor.get("camera_quat_wxyz")
    if not isinstance(position, np.ndarray) or not isinstance(quat, np.ndarray):
        return None
    return (
        np.asarray(position, dtype=np.float32).reshape(3),
        np.asarray(quat, dtype=np.float32).reshape(4),
    )


def descriptor_camera_to_body(
    descriptor: object,
) -> Optional[tuple[np.ndarray, np.ndarray]]:
    if not isinstance(descriptor, dict):
        return None
    rotation = descriptor.get("camera_rotation_body")
    position = descriptor.get("camera_position_body")
    if not isinstance(rotation, np.ndarray) or not isinstance(position, np.ndarray):
        return None
    return (
        np.asarray(rotation, dtype=np.float32).reshape(3, 3),
        np.asarray(position, dtype=np.float32).reshape(3),
    )


# ---------------------------------------------------------------------------
# Core math helpers
# ---------------------------------------------------------------------------

def quat_wxyz_to_matrix(quat: object) -> np.ndarray:
    """Unit quaternion (w, x, y, z) → 3×3 rotation matrix."""
    w, x, y, z = [float(v) for v in quat]
    norm = math.sqrt(w * w + x * x + y * y + z * z)
    if norm <= 1e-8:
        return np.eye(3, dtype=np.float32)
    w, x, y, z = w / norm, x / norm, y / norm, z / norm
    return np.asarray(
        [
            [1.0 - 2.0 * (y * y + z * z), 2.0 * (x * y - z * w), 2.0 * (x * z + y * w)],
            [2.0 * (x * y + z * w), 1.0 - 2.0 * (x * x + z * z), 2.0 * (y * z - x * w)],
            [2.0 * (x * z - y * w), 2.0 * (y * z + x * w), 1.0 - 2.0 * (x * x + y * y)],
        ],
        dtype=np.float32,
    )


def camera_point_to_body(
    point_camera: object, descriptor: object
) -> np.ndarray:
    """Transform a 3-D point from current-camera frame to current-body frame.

    Uses the extrinsic stored in *descriptor* when available; falls back to
    the canonical forward-facing camera mapping otherwise.

    Fallback convention (camera z-forward, x-right, y-down):
      body_x (forward) = camera_z
      body_y (left)    = -camera_x
      body_z (up)      = -camera_y
    """
    camera_to_body = descriptor_camera_to_body(descriptor)
    point_camera = np.asarray(point_camera, dtype=np.float32).reshape(3)
    if camera_to_body is None:
        return np.asarray(
            [point_camera[2], -point_camera[0], -point_camera[1]], dtype=np.float32
        )
    rotation_body_camera, camera_position_body = camera_to_body
    return (rotation_body_camera @ point_camera + camera_position_body).astype(np.float32)


def camera_rotation_to_body_yaw(
    rotation_anchor_to_current_camera: object,
    current_descriptor: object,
    anchor_descriptor: object,
) -> float:
    """Extract anchor-relative yaw from a camera-frame 3-D rotation.

    ``rotation_anchor_to_current_camera`` maps anchor-camera axes into the
    current-camera frame.  Convert that relative rotation into body axes, then
    read the heading of the anchor body x-axis in the current body frame.
    """
    rotation_anchor_to_current_camera = np.asarray(
        rotation_anchor_to_current_camera, dtype=np.float32
    ).reshape(3, 3)

    current_camera_to_body = descriptor_camera_to_body(current_descriptor)
    anchor_camera_to_body = descriptor_camera_to_body(anchor_descriptor)
    if current_camera_to_body is None:
        current_rotation_body_camera = np.asarray(
            [[0.0, 0.0, 1.0], [-1.0, 0.0, 0.0], [0.0, -1.0, 0.0]],
            dtype=np.float32,
        )
    else:
        current_rotation_body_camera, _ = current_camera_to_body

    if anchor_camera_to_body is None:
        anchor_rotation_body_camera = np.asarray(
            [[0.0, 0.0, 1.0], [-1.0, 0.0, 0.0], [0.0, -1.0, 0.0]],
            dtype=np.float32,
        )
    else:
        anchor_rotation_body_camera, _ = anchor_camera_to_body

    rotation_current_body_anchor_body = (
        current_rotation_body_camera
        @ rotation_anchor_to_current_camera
        @ anchor_rotation_body_camera.T
    )
    anchor_forward_in_current_body = rotation_current_body_anchor_body[:, 0]
    return float(math.atan2(
        float(anchor_forward_in_current_body[1]),
        float(anchor_forward_in_current_body[0]),
    ))


# ---------------------------------------------------------------------------
# 3-D point backprojection
# ---------------------------------------------------------------------------

def backproject_points(
    points_uv: object, depth: Optional[np.ndarray], intrinsics: np.ndarray
) -> tuple[np.ndarray, list[int]]:
    """Lift 2-D pixel coordinates to 3-D camera-frame points using *depth*.

    Returns ``(points_3d, valid_indices)`` where *valid_indices* lists the
    indices into *points_uv* whose depth sample was finite and in range.
    """
    points: list[list[float]] = []
    valid_indices: list[int] = []
    if depth is None:
        return np.empty((0, 3), dtype=np.float32), []
    depth = np.asarray(depth, dtype=np.float32)
    if depth.ndim != 2:
        depth = np.squeeze(depth)
    fx, fy = float(intrinsics[0, 0]), float(intrinsics[1, 1])
    cx, cy = float(intrinsics[0, 2]), float(intrinsics[1, 2])
    height, width = depth.shape[:2]
    for i, (u, v) in enumerate(points_uv):
        x = int(round(float(u)))
        y = int(round(float(v)))
        if x < 0 or y < 0 or x >= width or y >= height:
            continue
        z = float(depth[y, x])
        if not math.isfinite(z) or z <= 0.05 or z >= 10.0:
            continue
        points.append([(float(u) - cx) * z / fx, (float(v) - cy) * z / fy, z])
        valid_indices.append(i)
    return np.asarray(points, dtype=np.float32), valid_indices


# ---------------------------------------------------------------------------
# Kabsch SVD + RANSAC 3-D rigid transform
# ---------------------------------------------------------------------------

def rigid_transform_3d(
    source_points: np.ndarray, target_points: np.ndarray
) -> tuple[Optional[np.ndarray], Optional[np.ndarray]]:
    """Kabsch SVD: find R, t such that R @ source + t ≈ target.

    Returns ``(rotation, translation)`` or ``(None, None)`` if fewer than
    three point pairs are provided.
    """
    source = np.asarray(source_points, dtype=np.float32)
    target = np.asarray(target_points, dtype=np.float32)
    if len(source) < 3 or len(target) < 3:
        return None, None
    source_centroid = source.mean(axis=0)
    target_centroid = target.mean(axis=0)
    source_centered = source - source_centroid
    target_centered = target - target_centroid
    covariance = source_centered.T @ target_centered
    try:
        u, _, vt = np.linalg.svd(covariance)
    except np.linalg.LinAlgError:
        return None, None
    rotation = vt.T @ u.T
    if np.linalg.det(rotation) < 0:
        vt[-1, :] *= -1
        rotation = vt.T @ u.T
    translation = target_centroid - rotation @ source_centroid
    return rotation.astype(np.float32), translation.astype(np.float32)


def ransac_rigid_transform(
    source_points: np.ndarray,
    target_points: np.ndarray,
    iterations: int = 96,
    threshold_m: float = 0.18,
) -> tuple[Optional[np.ndarray], Optional[np.ndarray], Optional[np.ndarray]]:
    """RANSAC wrapper around :func:`rigid_transform_3d`.

    Returns ``(rotation, translation, inlier_mask)`` or
    ``(None, None, None)`` if fewer than 6 points or no consensus found.
    """
    if len(source_points) < 6:
        return None, None, None
    rng = np.random.default_rng(7)
    best_inliers = None
    best_rotation = None
    best_translation = None
    count = len(source_points)
    for _ in range(iterations):
        sample = rng.choice(count, size=3, replace=False)
        rotation, translation = rigid_transform_3d(
            source_points[sample], target_points[sample]
        )
        if rotation is None:
            continue
        residual = np.linalg.norm(
            (rotation @ source_points.T).T + translation - target_points, axis=1
        )
        inliers = residual < threshold_m
        if best_inliers is None or int(inliers.sum()) > int(best_inliers.sum()):
            best_inliers = inliers
            best_rotation = rotation
            best_translation = translation
    if best_inliers is None or int(best_inliers.sum()) < 6:
        return None, None, None
    rotation, translation = rigid_transform_3d(
        source_points[best_inliers], target_points[best_inliers]
    )
    return rotation, translation, best_inliers


# ---------------------------------------------------------------------------
# 2-D local-map / LiDAR scan matching
# ---------------------------------------------------------------------------

def descriptor_local_map_points(descriptor: object) -> Optional[np.ndarray]:
    """Return local LiDAR/map points in body coordinates as an Nx2 array."""
    if not isinstance(descriptor, dict):
        return None
    for key in (
        "local_map_points_body",
        "lidar_points_body",
        "scan_points_body",
        "height_scan_points_body",
    ):
        points = descriptor.get(key)
        if points is None:
            continue
        arr = np.asarray(points, dtype=np.float32)
        if arr.ndim == 3 and arr.shape[0] == 1:
            arr = arr[0]
        if arr.ndim != 2 or arr.shape[1] < 2 or arr.shape[0] == 0:
            continue
        finite = np.isfinite(arr).all(axis=1)
        arr = arr[finite]
        if arr.shape[0] == 0:
            continue
        if arr.shape[1] >= 3:
            z = arr[:, 2]
            obstacle = (z >= -0.20) & (z <= 1.80)
            if int(obstacle.sum()) >= 12:
                arr = arr[obstacle]
        return np.asarray(arr[:, :2], dtype=np.float32)
    return None


def voxel_downsample_2d(points: np.ndarray, voxel_size_m: float = 0.12, max_points: int = 256) -> np.ndarray:
    points = np.asarray(points, dtype=np.float32)
    if points.ndim != 2 or points.shape[1] < 2 or len(points) == 0:
        return np.empty((0, 2), dtype=np.float32)
    voxel = max(1e-3, float(voxel_size_m))
    keys = np.round(points[:, :2] / voxel).astype(np.int32)
    _, first = np.unique(keys, axis=0, return_index=True)
    down = points[np.sort(first), :2]
    if len(down) > max_points:
        idx = np.linspace(0, len(down) - 1, int(max_points)).astype(np.int32)
        down = down[idx]
    return np.asarray(down, dtype=np.float32)


def _rotation_2d(theta: float) -> np.ndarray:
    c = math.cos(float(theta))
    s = math.sin(float(theta))
    return np.asarray([[c, -s], [s, c]], dtype=np.float32)


def _rigid_transform_2d(source_points: np.ndarray, target_points: np.ndarray) -> tuple[Optional[float], Optional[np.ndarray]]:
    source = np.asarray(source_points, dtype=np.float32)
    target = np.asarray(target_points, dtype=np.float32)
    if len(source) < 3 or len(target) < 3:
        return None, None
    source_centroid = source.mean(axis=0)
    target_centroid = target.mean(axis=0)
    source_centered = source - source_centroid
    target_centered = target - target_centroid
    covariance = source_centered.T @ target_centered
    try:
        u, _, vt = np.linalg.svd(covariance)
    except np.linalg.LinAlgError:
        return None, None
    rotation = vt.T @ u.T
    if np.linalg.det(rotation) < 0:
        vt[-1, :] *= -1
        rotation = vt.T @ u.T
    theta = math.atan2(float(rotation[1, 0]), float(rotation[0, 0]))
    translation = target_centroid - rotation @ source_centroid
    return float(theta), np.asarray(translation, dtype=np.float32)


def _nearest_neighbor_2d(source_points: np.ndarray, target_points: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    source = np.asarray(source_points, dtype=np.float32)
    target = np.asarray(target_points, dtype=np.float32)
    nearest = np.zeros((len(source),), dtype=np.int32)
    distances = np.full((len(source),), float("inf"), dtype=np.float32)
    chunk = 128
    for start in range(0, len(source), chunk):
        end = min(len(source), start + chunk)
        diff = source[start:end, None, :] - target[None, :, :]
        dist2 = np.sum(diff * diff, axis=2)
        idx = np.argmin(dist2, axis=1)
        nearest[start:end] = idx.astype(np.int32)
        distances[start:end] = np.sqrt(dist2[np.arange(end - start), idx]).astype(np.float32)
    return nearest, distances


def _apply_transform_2d(points: np.ndarray, theta: float, translation: np.ndarray) -> np.ndarray:
    return (points @ _rotation_2d(theta).T + np.asarray(translation, dtype=np.float32)).astype(np.float32)


def icp_rigid_transform_2d(
    source_points: np.ndarray,
    target_points: np.ndarray,
    *,
    initial_theta: float = 0.0,
    max_iterations: int = 24,
    correspondence_threshold_m: float = 0.45,
) -> Optional[dict]:
    """Align ``source`` to ``target`` with point-to-point 2-D ICP."""
    source = np.asarray(source_points, dtype=np.float32)
    target = np.asarray(target_points, dtype=np.float32)
    if len(source) < 12 or len(target) < 12:
        return None
    theta = float(initial_theta)
    rotation = _rotation_2d(theta)
    translation = target.mean(axis=0) - rotation @ source.mean(axis=0)
    threshold = float(correspondence_threshold_m)
    prev_error = float("inf")
    inliers = None
    distances = None
    for _ in range(int(max_iterations)):
        transformed = _apply_transform_2d(source, theta, translation)
        nearest, distances = _nearest_neighbor_2d(transformed, target)
        inliers = distances < threshold
        if int(inliers.sum()) < 8:
            return None
        theta_delta, translation_delta = _rigid_transform_2d(
            transformed[inliers], target[nearest[inliers]]
        )
        if theta_delta is None or translation_delta is None:
            return None
        theta = float(theta + theta_delta)
        translation = (_rotation_2d(theta_delta) @ translation + translation_delta).astype(np.float32)
        error = float(np.median(distances[inliers]))
        if abs(prev_error - error) < 1e-4:
            break
        prev_error = error
    transformed = _apply_transform_2d(source, theta, translation)
    nearest, distances = _nearest_neighbor_2d(transformed, target)
    inliers = distances < threshold
    if int(inliers.sum()) < 8:
        return None
    return {
        "theta": float(math.atan2(math.sin(theta), math.cos(theta))),
        "translation": np.asarray(translation, dtype=np.float32),
        "median_residual_m": float(np.median(distances[inliers])),
        "mean_residual_m": float(np.mean(distances[inliers])),
        "inlier_count": int(inliers.sum()),
        "overlap_ratio": float(int(inliers.sum()) / max(1, min(len(source), len(target)))),
    }


# ---------------------------------------------------------------------------
# GT covisibility check (uses Isaac world-frame camera poses stored in descriptors)
# ---------------------------------------------------------------------------

def gt_covisibility(
    anchor_descriptor: object,
    current_descriptor: object,
    max_points: int = 900,
    depth_tolerance_m: float = 0.35,
) -> dict:
    anchor_depth = descriptor_depth(anchor_descriptor)
    current_depth = descriptor_depth(current_descriptor)
    if anchor_depth is None or current_depth is None:
        return {"available": False, "reason": "missing_depth"}
    anchor_pose = descriptor_camera_pose(anchor_descriptor)
    current_pose = descriptor_camera_pose(current_descriptor)
    if anchor_pose is None or current_pose is None:
        return {"available": False, "reason": "missing_camera_pose"}

    anchor_depth = np.squeeze(np.asarray(anchor_depth, dtype=np.float32))
    current_depth = np.squeeze(np.asarray(current_depth, dtype=np.float32))
    if anchor_depth.ndim != 2 or current_depth.ndim != 2:
        return {"available": False, "reason": "bad_depth_shape"}

    anchor_k = descriptor_intrinsics(anchor_descriptor, anchor_depth.shape[1], anchor_depth.shape[0])
    current_k = descriptor_intrinsics(current_descriptor, current_depth.shape[1], current_depth.shape[0])
    anchor_position, anchor_quat = anchor_pose
    current_position, current_quat = current_pose
    anchor_rot = quat_wxyz_to_matrix(anchor_quat)
    current_rot = quat_wxyz_to_matrix(current_quat)

    valid = np.isfinite(anchor_depth) & (anchor_depth > 0.05) & (anchor_depth < 10.0)
    ys, xs = np.nonzero(valid)
    if len(xs) == 0:
        return {"available": False, "reason": "no_valid_anchor_depth"}
    stride = max(1, int(math.ceil(math.sqrt(len(xs) / float(max_points)))))
    xs = xs[::stride]
    ys = ys[::stride]
    if len(xs) > max_points:
        xs = xs[:max_points]
        ys = ys[:max_points]

    z = anchor_depth[ys, xs]
    fx_a, fy_a = float(anchor_k[0, 0]), float(anchor_k[1, 1])
    cx_a, cy_a = float(anchor_k[0, 2]), float(anchor_k[1, 2])
    anchor_points = np.stack(
        [
            (xs.astype(np.float32) - cx_a) * z / fx_a,
            (ys.astype(np.float32) - cy_a) * z / fy_a,
            z,
        ],
        axis=1,
    )
    world_points = (anchor_rot @ anchor_points.T).T + anchor_position[None, :]
    current_points = (current_rot.T @ (world_points - current_position[None, :]).T).T
    positive = current_points[:, 2] > 0.05
    if not positive.any():
        return {
            "available": True,
            "sampled_points": int(len(anchor_points)),
            "positive_depth_points": 0,
            "projected_points": 0,
            "depth_consistent_points": 0,
            "projected_ratio": 0.0,
            "depth_consistent_ratio": 0.0,
        }

    points = current_points[positive]
    fx_c, fy_c = float(current_k[0, 0]), float(current_k[1, 1])
    cx_c, cy_c = float(current_k[0, 2]), float(current_k[1, 2])
    us = fx_c * points[:, 0] / points[:, 2] + cx_c
    vs = fy_c * points[:, 1] / points[:, 2] + cy_c
    height, width = current_depth.shape
    inside = (us >= 0.0) & (vs >= 0.0) & (us < width) & (vs < height)
    projected_count = int(inside.sum())
    depth_consistent_count = 0
    if projected_count > 0:
        ui = np.rint(us[inside]).astype(np.int32)
        vi = np.rint(vs[inside]).astype(np.int32)
        ui = np.clip(ui, 0, width - 1)
        vi = np.clip(vi, 0, height - 1)
        observed_depth = current_depth[vi, ui]
        predicted_depth = points[inside, 2]
        depth_ok = np.isfinite(observed_depth) & (observed_depth > 0.05)
        depth_ok &= predicted_depth <= observed_depth + depth_tolerance_m
        depth_ok &= np.abs(predicted_depth - observed_depth) <= (
            max(depth_tolerance_m, 0.15) + 0.15 * observed_depth
        )
        depth_consistent_count = int(depth_ok.sum())

    sampled = int(len(anchor_points))
    return {
        "available": True,
        "sampled_points": sampled,
        "positive_depth_points": int(positive.sum()),
        "projected_points": projected_count,
        "depth_consistent_points": depth_consistent_count,
        "projected_ratio": float(projected_count / sampled) if sampled else 0.0,
        "depth_consistent_ratio": float(depth_consistent_count / sampled) if sampled else 0.0,
    }


# ---------------------------------------------------------------------------
# Feature matching
# ---------------------------------------------------------------------------

_LOFTR_MODEL = None
_LOFTR_DEVICE = None


def feature_matcher_config(matcher_backend: str) -> dict:
    if matcher_backend == "sift":
        if cv2 is None:
            return None
        return {
            "name": "sift",
            "required_keypoints": 20,
            "required_matches": 12,
            "max_cross_matches": 120,
            "ratio": 0.75,
            "norm": cv2.NORM_L2,
        }
    if matcher_backend == "loftr":
        return {
            "name": "loftr",
            "required_keypoints": 0,
            "required_matches": 12,
            "max_cross_matches": 0,
            "ratio": 0.0,
            "norm": None,
        }
    if cv2 is None:
        return None
    return {
        "name": "orb",
        "required_keypoints": 20,
        "required_matches": 12,
        "max_cross_matches": 80,
        "ratio": 0.82,
        "norm": cv2.NORM_HAMMING,
    }


def create_feature_detector(matcher_backend: str) -> Optional[object]:
    if cv2 is None:
        return None
    if matcher_backend == "sift":
        if not hasattr(cv2, "SIFT_create"):
            return None
        return cv2.SIFT_create(nfeatures=1200)
    if not hasattr(cv2, "ORB_create"):
        return None
    return cv2.ORB_create(nfeatures=900)


def _detect_feature_descriptor(
    gray: np.ndarray, detector: object
) -> tuple[Optional[list], Optional[np.ndarray]]:
    if gray is None or detector is None:
        return None, None
    keypoints, descriptor = detector.detectAndCompute(gray, None)
    return keypoints, descriptor


def _match_feature_descriptors(
    anchor_desc: np.ndarray, current_desc: np.ndarray, config: dict
) -> list:
    if anchor_desc is None or current_desc is None:
        return []
    ratio_matcher = cv2.BFMatcher(config["norm"], crossCheck=False)
    cross_matcher = cv2.BFMatcher(config["norm"], crossCheck=True)
    raw_matches = ratio_matcher.knnMatch(anchor_desc, current_desc, k=2)
    matches = []
    for pair in raw_matches:
        if len(pair) != 2:
            continue
        first, second = pair
        if first.distance < config["ratio"] * second.distance:
            matches.append(first)
    if len(matches) < config["required_matches"]:
        matches = sorted(
            cross_matcher.match(anchor_desc, current_desc),
            key=lambda m: m.distance,
        )
        matches = matches[: config["max_cross_matches"]]
    return matches


def loftr_match_points(
    anchor_gray: Optional[np.ndarray],
    current_gray: Optional[np.ndarray],
    diagnostics: Optional[dict] = None,
) -> tuple[Optional[np.ndarray], Optional[np.ndarray], dict]:
    global _LOFTR_MODEL, _LOFTR_DEVICE
    try:
        import torch
        from kornia.feature import LoFTR
    except Exception:
        _diagnostic_inc(diagnostics, "missing_kornia_loftr")
        return None, None, {"loftr_available": False}

    if anchor_gray is None or current_gray is None:
        return None, None, {"loftr_available": True, "reason": "missing_gray"}
    try:
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        if _LOFTR_MODEL is None or _LOFTR_DEVICE != device:
            _LOFTR_MODEL = LoFTR(pretrained="outdoor").to(device).eval()
            _LOFTR_DEVICE = device
        anchor_tensor = torch.from_numpy(anchor_gray.astype(np.float32) / 255.0)[
            None, None
        ].to(device)
        current_tensor = torch.from_numpy(current_gray.astype(np.float32) / 255.0)[
            None, None
        ].to(device)
        with torch.inference_mode():
            output = _LOFTR_MODEL({"image0": anchor_tensor, "image1": current_tensor})
        anchor_uv = output["keypoints0"].detach().cpu().numpy().astype(np.float32)
        current_uv = output["keypoints1"].detach().cpu().numpy().astype(np.float32)
        confidence = output.get("confidence")
        metadata: dict = {"loftr_available": True, "loftr_matches": int(len(anchor_uv))}
        if confidence is not None and len(anchor_uv) > 0:
            conf = confidence.detach().cpu().numpy()
            order = np.argsort(-conf)
            anchor_uv = anchor_uv[order]
            current_uv = current_uv[order]
            metadata["loftr_mean_confidence"] = float(np.mean(conf))
            metadata["loftr_top_confidence"] = float(conf[order[0]])
        return anchor_uv, current_uv, metadata
    except Exception as exc:
        _diagnostic_inc(diagnostics, "loftr_failed")
        return None, None, {"loftr_available": True, "loftr_error": str(exc)[:200]}


def matched_uv_points(
    anchor_gray: Optional[np.ndarray],
    current_gray: Optional[np.ndarray],
    detector: Optional[object],
    current_keypoints: Optional[list],
    current_desc: Optional[np.ndarray],
    matcher_backend: str,
    diagnostics: Optional[dict] = None,
) -> tuple[Optional[np.ndarray], Optional[np.ndarray], dict]:
    config = feature_matcher_config(matcher_backend)
    if matcher_backend == "loftr":
        return loftr_match_points(anchor_gray, current_gray, diagnostics=diagnostics)
    anchor_keypoints, anchor_desc = _detect_feature_descriptor(anchor_gray, detector)
    metadata: dict = {
        "anchor_keypoints": 0 if anchor_keypoints is None else int(len(anchor_keypoints)),
        "current_keypoints": 0 if current_keypoints is None else int(len(current_keypoints)),
    }
    if (
        anchor_desc is None
        or anchor_keypoints is None
        or len(anchor_keypoints) < config["required_keypoints"]
    ):
        metadata["failure_reason"] = "candidate_too_few_keypoints"
        return None, None, metadata
    matches = _match_feature_descriptors(anchor_desc, current_desc, config)
    metadata["matches_2d"] = int(len(matches))
    if len(matches) < config["required_matches"]:
        metadata["failure_reason"] = "too_few_2d_matches"
        return None, None, metadata
    anchor_uv = np.asarray(
        [anchor_keypoints[m.queryIdx].pt for m in matches], dtype=np.float32
    )
    current_uv = np.asarray(
        [current_keypoints[m.trainIdx].pt for m in matches], dtype=np.float32
    )
    return anchor_uv, current_uv, metadata


# ---------------------------------------------------------------------------
# Diagnostic helpers (shared with round_trip_eval callers)
# ---------------------------------------------------------------------------

def _diagnostic_inc(diagnostics: Optional[dict], key: str, amount: int = 1) -> None:
    if diagnostics is not None:
        diagnostics[key] = diagnostics.get(key, 0) + amount


def _append_covisibility_record(diagnostics: Optional[dict], record: dict) -> None:
    if diagnostics is None:
        return
    records = diagnostics.setdefault("covisibility_records", [])
    records.append(record)
    cov = record.get("covisibility", {})
    if cov.get("available"):
        projected = float(cov.get("projected_ratio", 0.0))
        consistent = float(cov.get("depth_consistent_ratio", 0.0))
        if projected >= 0.25:
            _diagnostic_inc(diagnostics, "gt_projected_overlap_ge_25")
        if consistent >= 0.10:
            _diagnostic_inc(diagnostics, "gt_depth_consistent_overlap_ge_10")
        if record.get("outcome") == "ransac_failed" and projected >= 0.25:
            _diagnostic_inc(diagnostics, "ransac_failed_with_gt_projected_overlap_ge_25")
        if record.get("outcome") == "ransac_failed" and consistent >= 0.10:
            _diagnostic_inc(diagnostics, "ransac_failed_with_gt_depth_consistent_overlap_ge_10")
    else:
        _diagnostic_inc(
            diagnostics, f"covisibility_unavailable_{cov.get('reason', 'unknown')}"
        )


# ---------------------------------------------------------------------------
# Main relocalization entry point
# ---------------------------------------------------------------------------

def local_map_anchor_relocalization(
    current_descriptor: object,
    anchors: list,
    max_candidates: Optional[int] = None,
    diagnostics: Optional[dict] = None,
    return_candidates: bool = False,
) -> Optional[object]:
    """Relocalize against saved route anchors using LiDAR/local-map scan matching."""
    from route_memory_agent import AnchorRelocalization

    _diagnostic_inc(diagnostics, "attempts")
    _diagnostic_inc(diagnostics, "local_map_attempts")
    if diagnostics is not None:
        diagnostics["matcher_backend"] = "local_map_icp"
    current_points = descriptor_local_map_points(current_descriptor)
    if current_points is None:
        _diagnostic_inc(diagnostics, "missing_current_local_map")
        return None
    current_points = voxel_downsample_2d(current_points)
    if len(current_points) < 12:
        _diagnostic_inc(diagnostics, "too_few_current_local_map_points")
        return None

    candidates = [
        anchor for anchor in reversed(anchors) if isinstance(anchor.descriptor, dict)
    ]
    if max_candidates is not None and max_candidates > 0:
        candidates_to_search = candidates[:max_candidates]
    else:
        candidates_to_search = candidates
    _diagnostic_inc(diagnostics, "candidate_anchors", len(candidates_to_search))

    yaw_initializers = [math.radians(float(deg)) for deg in range(-180, 180, 15)]
    pose_candidates = []
    best = None
    attempt_index = diagnostics.get("attempts", 0) if diagnostics is not None else None
    for anchor in candidates_to_search:
        anchor_points = descriptor_local_map_points(anchor.descriptor)
        record = {
            "attempt": int(attempt_index) if attempt_index is not None else None,
            "anchor_index": int(anchor.index),
            "anchor_distance_from_start_m": float(anchor.distance_from_start_m),
            "route_remaining_to_start_m": float(anchor.route_remaining_to_start_m),
            "matcher_backend": "local_map_icp",
            "outcome": "not_evaluated",
        }
        if anchor_points is None:
            _diagnostic_inc(diagnostics, "candidate_missing_local_map")
            record["outcome"] = "candidate_missing_local_map"
            _append_covisibility_record(diagnostics, record)
            continue
        anchor_points = voxel_downsample_2d(anchor_points)
        record["anchor_points"] = int(len(anchor_points))
        record["current_points"] = int(len(current_points))
        if len(anchor_points) < 12:
            _diagnostic_inc(diagnostics, "too_few_anchor_local_map_points")
            record["outcome"] = "too_few_anchor_local_map_points"
            _append_covisibility_record(diagnostics, record)
            continue
        best_icp = None
        for yaw in yaw_initializers:
            result = icp_rigid_transform_2d(
                anchor_points,
                current_points,
                initial_theta=yaw,
                max_iterations=16,
                correspondence_threshold_m=0.45,
            )
            if result is None:
                continue
            score = (
                result["overlap_ratio"]
                * max(0.0, 1.0 - result["median_residual_m"] / 0.45)
                * math.sqrt(max(1, result["inlier_count"]))
            )
            if best_icp is None or score > best_icp[0]:
                best_icp = (score, result)
        if best_icp is None:
            _diagnostic_inc(diagnostics, "local_map_icp_failed")
            record["outcome"] = "local_map_icp_failed"
            _append_covisibility_record(diagnostics, record)
            continue
        score, result = best_icp
        overlap = float(result["overlap_ratio"])
        residual = float(result["median_residual_m"])
        inlier_count = int(result["inlier_count"])
        confidence = min(1.0, overlap * max(0.0, 1.0 - residual / 0.45) * 1.5)
        record.update({
            "inlier_count": inlier_count,
            "overlap_ratio": overlap,
            "median_residual_m": residual,
            "mean_residual_m": float(result["mean_residual_m"]),
            "confidence": float(confidence),
            "estimated_anchor_dx_m": float(result["translation"][0]),
            "estimated_anchor_dy_m": float(result["translation"][1]),
            "estimated_anchor_dtheta_deg": float(math.degrees(result["theta"])),
        })
        if inlier_count < 12 or overlap < 0.12 or confidence < 0.15:
            _diagnostic_inc(diagnostics, "low_confidence_local_map_pose")
            record["outcome"] = "low_confidence_local_map_pose"
            _append_covisibility_record(diagnostics, record)
            continue
        candidate = AnchorRelocalization(
            anchor_index=int(anchor.index),
            anchor_dx_m=float(result["translation"][0]),
            anchor_dy_m=float(result["translation"][1]),
            anchor_dtheta_rad=float(result["theta"]),
            confidence=float(confidence),
            backend="local_map_icp",
            inlier_count=inlier_count,
            reprojection_error_px=None,
            anchor_heading_reliable=True,
        )
        record["estimated_distance_to_anchor_m"] = float(candidate.distance_to_anchor_m)
        record["estimated_bearing_to_anchor_deg"] = float(candidate.bearing_to_anchor_deg)
        record["outcome"] = "pose_candidate"
        _append_covisibility_record(diagnostics, record)
        pose_candidates.append(candidate)
        if best is None or score > best[0]:
            best = (score, candidate)
    if best is None:
        _diagnostic_inc(diagnostics, "no_pose_selected")
        return None
    _diagnostic_inc(diagnostics, "successful_estimates")
    pose_candidates.sort(
        key=lambda c: float(c.confidence) * math.sqrt(max(1, int(c.inlier_count or 1))),
        reverse=True,
    )
    if return_candidates:
        return pose_candidates
    return pose_candidates[0]

def feature_depth_anchor_relocalization(
    current_descriptor: object,
    anchors: list,
    max_candidates: Optional[int] = None,
    diagnostics: Optional[dict] = None,
    matcher_backend: str = "orb",
    return_candidates: bool = False,
) -> Optional[object]:
    """Attempt map-free anchor relocalization using feature matching + 3-D RANSAC.

    Imports ``AnchorRelocalization`` lazily from ``route_memory_agent`` so this
    module stays importable in test environments where Isaac is not available.
    """
    from route_memory_agent import AnchorRelocalization

    matcher_backend = str(matcher_backend or "orb").lower()
    if matcher_backend == "feature_depth":
        matcher_backend = "orb"
    config = feature_matcher_config(matcher_backend)
    if config is None:
        _diagnostic_inc(diagnostics, "missing_cv2")
        return None
    _diagnostic_inc(diagnostics, "attempts")
    _diagnostic_inc(diagnostics, f"{config['name']}_attempts")
    if diagnostics is not None:
        diagnostics["matcher_backend"] = config["name"]
    attempt_index = diagnostics.get("attempts", 0) if diagnostics is not None else None
    current_gray = descriptor_rgb_gray(current_descriptor)
    current_depth = descriptor_depth(current_descriptor)
    if current_gray is None or current_depth is None:
        _diagnostic_inc(diagnostics, "missing_current_rgb_or_depth")
        return None

    detector = None
    current_keypoints = None
    current_desc_arr = None
    if matcher_backend != "loftr":
        detector = create_feature_detector(matcher_backend)
        if detector is None:
            _diagnostic_inc(diagnostics, f"missing_{config['name']}_detector")
            return None
        current_keypoints, current_desc_arr = _detect_feature_descriptor(
            current_gray, detector
        )
        if (
            current_desc_arr is None
            or current_keypoints is None
            or len(current_keypoints) < config["required_keypoints"]
        ):
            _diagnostic_inc(diagnostics, "too_few_current_keypoints")
            return None

    current_k = descriptor_intrinsics(
        current_descriptor, current_gray.shape[1], current_gray.shape[0]
    )
    best = None
    pose_candidates = []
    candidates = [
        anchor for anchor in reversed(anchors) if isinstance(anchor.descriptor, dict)
    ]
    if max_candidates is not None and max_candidates > 0:
        candidates_to_search = candidates[:max_candidates]
    else:
        candidates_to_search = candidates
    _diagnostic_inc(diagnostics, "candidate_anchors", len(candidates_to_search))
    for anchor in candidates_to_search:
        views_to_try = [("front", anchor.descriptor)]
        rear_view = build_rear_view_descriptor(anchor.descriptor)
        if rear_view is not None:
            views_to_try.append(("rear", rear_view))
        for view_name, anchor_descriptor in views_to_try:
            covisibility = gt_covisibility(anchor_descriptor, current_descriptor)
            record: dict = {
                "attempt": int(attempt_index) if attempt_index is not None else None,
                "anchor_index": int(anchor.index),
                "anchor_view": view_name,
                "anchor_distance_from_start_m": float(anchor.distance_from_start_m),
                "route_remaining_to_start_m": float(anchor.route_remaining_to_start_m),
                "covisibility": covisibility,
                "matcher_backend": config["name"],
                "outcome": "not_evaluated",
            }
            anchor_gray = descriptor_rgb_gray(anchor_descriptor)
            anchor_depth = descriptor_depth(anchor_descriptor)
            if anchor_gray is None or anchor_depth is None:
                _diagnostic_inc(diagnostics, "candidate_missing_rgb_or_depth")
                record["outcome"] = "candidate_missing_rgb_or_depth"
                _append_covisibility_record(diagnostics, record)
                continue
            anchor_uv, current_uv, match_metadata = matched_uv_points(
                anchor_gray,
                current_gray,
                detector,
                current_keypoints,
                current_desc_arr,
                matcher_backend,
                diagnostics=diagnostics,
            )
            record.update(match_metadata)
            if anchor_uv is None or current_uv is None:
                if matcher_backend == "loftr" and not match_metadata.get(
                    "loftr_available", True
                ):
                    record["outcome"] = "loftr_unavailable"
                    _append_covisibility_record(diagnostics, record)
                    return None
                failure_reason = match_metadata.get(
                    "failure_reason", "candidate_too_few_keypoints"
                )
                _diagnostic_inc(diagnostics, failure_reason)
                record["outcome"] = failure_reason
                _append_covisibility_record(diagnostics, record)
                continue
            record["matches_2d"] = int(len(anchor_uv))
            if len(anchor_uv) < config["required_matches"]:
                _diagnostic_inc(diagnostics, "too_few_2d_matches")
                record["outcome"] = "too_few_2d_matches"
                _append_covisibility_record(diagnostics, record)
                continue
            anchor_k = descriptor_intrinsics(
                anchor_descriptor, anchor_gray.shape[1], anchor_gray.shape[0]
            )
            anchor_points_all, anchor_valid = backproject_points(
                anchor_uv, anchor_depth, anchor_k
            )
            current_points_all, current_valid = backproject_points(
                current_uv, current_depth, current_k
            )
            valid = sorted(set(anchor_valid).intersection(current_valid))
            record["depth_valid_matches"] = int(len(valid))
            if len(valid) < 8:
                _diagnostic_inc(diagnostics, "too_few_depth_valid_matches")
                record["outcome"] = "too_few_depth_valid_matches"
                _append_covisibility_record(diagnostics, record)
                continue
            anchor_index_by_match = {
                match_index: i for i, match_index in enumerate(anchor_valid)
            }
            current_index_by_match = {
                match_index: i for i, match_index in enumerate(current_valid)
            }
            anchor_points = np.asarray(
                [anchor_points_all[anchor_index_by_match[i]] for i in valid], dtype=np.float32
            )
            current_points = np.asarray(
                [current_points_all[current_index_by_match[i]] for i in valid], dtype=np.float32
            )
            rotation, translation, inliers = ransac_rigid_transform(
                anchor_points, current_points, threshold_m=0.35
            )
            if rotation is None:
                _diagnostic_inc(diagnostics, "ransac_failed")
                record["outcome"] = "ransac_failed"
                _append_covisibility_record(diagnostics, record)
                continue
            inlier_count = int(inliers.sum())
            record["inlier_count"] = inlier_count
            if inlier_count < 6:
                _diagnostic_inc(diagnostics, "too_few_3d_inliers")
                record["outcome"] = "too_few_3d_inliers"
                _append_covisibility_record(diagnostics, record)
                continue
            residual = np.linalg.norm(
                (rotation @ anchor_points[inliers].T).T
                + translation
                - current_points[inliers],
                axis=1,
            )
            error = float(np.median(residual))
            record["median_3d_residual_m"] = error
            confidence = min(1.0, (inlier_count / 30.0) * max(0.0, 1.0 - error / 0.45))
            if confidence < 0.15:
                _diagnostic_inc(diagnostics, "low_confidence_pose")
                record["confidence"] = float(confidence)
                record["outcome"] = "low_confidence_pose"
                _append_covisibility_record(diagnostics, record)
                continue

            anchor_origin_in_current_body = camera_point_to_body(
                translation, current_descriptor
            )
            anchor_dtheta = camera_rotation_to_body_yaw(
                rotation, current_descriptor, anchor_descriptor
            )
            candidate = AnchorRelocalization(
                anchor_index=int(anchor.index),
                anchor_dx_m=float(anchor_origin_in_current_body[0]),
                anchor_dy_m=float(anchor_origin_in_current_body[1]),
                anchor_dtheta_rad=float(anchor_dtheta),
                confidence=float(confidence),
                backend=f"feature_depth_{config['name']}_3d3d_{view_name}",
                inlier_count=inlier_count,
                reprojection_error_px=None,
                anchor_heading_reliable=True,
            )
            record["confidence"] = float(confidence)
            record["estimated_anchor_dx_m"] = float(candidate.anchor_dx_m)
            record["estimated_anchor_dy_m"] = float(candidate.anchor_dy_m)
            record["estimated_distance_to_anchor_m"] = float(candidate.distance_to_anchor_m)
            record["estimated_bearing_to_anchor_deg"] = float(candidate.bearing_to_anchor_deg)
            record["outcome"] = "pose_candidate"
            _append_covisibility_record(diagnostics, record)
            score = confidence * math.sqrt(max(1, inlier_count))
            pose_candidates.append(candidate)
            if best is None or score > best[0]:
                best = (score, candidate)
    if best is None:
        _diagnostic_inc(diagnostics, "no_pose_selected")
        return None
    _diagnostic_inc(diagnostics, "successful_estimates")
    if return_candidates:
        pose_candidates.sort(
            key=lambda c: float(c.confidence) * math.sqrt(max(1, int(c.inlier_count or 1))),
            reverse=True,
        )
        return pose_candidates
    return best[1]
