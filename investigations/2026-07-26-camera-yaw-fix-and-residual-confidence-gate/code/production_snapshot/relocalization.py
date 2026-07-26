"""Pure-geometry relocalization utilities for round-trip VLN evaluation.

All functions here depend only on numpy / math / cv2 / torch (optional, for
LoFTR).  Keeping them in a separate module allows unit-testing outside the
Isaac Sim environment (which requires a full headless GPU launch to import).
"""

from __future__ import annotations

import math
from typing import Optional

import numpy as np

from scan_context import (
    build_scan_context,
    column_shift_search_with_region,
    column_shift_similarity,
    largest_connected_agreement_region,
    shift_to_yaw_rad,
)

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

    2026-07-26: the *fallback* ``camera_rotation_body`` (used only when a
    descriptor is missing real extrinsics, e.g. synthetic test fixtures) and
    the *real* captured ``camera_rotation_body`` (always present on genuine
    RGB-D captures) turned out to encode two different, incompatible axis
    conventions -- the fallback matrix maps camera axes into a proper
    forward/left/up body frame (yaw lives in the body x/y plane, i.e.
    column indices (1, 0) below), but every real capture stores
    ``camera_rotation_body`` as literally camera-native (x-right, y-down,
    z-forward duplicated onto "body"), under which yaw actually lives in the
    x/z plane (indices (2, 0)) -- verified directly against real capture
    data in `investigations/2026-07-26-camera-yaw-fix-and-residual-confidence-
    gate/`. Using the (1, 0) fallback-convention formula against real data's
    (2, 0) convention meant ``anchor_forward_in_current_body[1]`` is
    analytically ~0 for a pure yaw rotation, so the old code could only ever
    return ~0 deg or ~180 deg regardless of the true rotation -- a silent,
    total loss of precision affecting every real caller since this function
    started being used for `_loftr_rear_yaw_check` (2026-07-13). Real data
    also needs an additional sign flip when the *current*-side descriptor is
    a rear view (`build_rear_view_descriptor`'s "view" tag) -- found
    empirically, not yet re-derived analytically, but validated against 249
    real samples spanning 0.32-6m (median error 17.4 deg -> 0.33 deg; see the
    investigation folder above for the full validation).
    """
    rotation_anchor_to_current_camera = np.asarray(
        rotation_anchor_to_current_camera, dtype=np.float32
    ).reshape(3, 3)

    current_camera_to_body = descriptor_camera_to_body(current_descriptor)
    anchor_camera_to_body = descriptor_camera_to_body(anchor_descriptor)
    using_real_extrinsics = current_camera_to_body is not None and anchor_camera_to_body is not None
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

    if not using_real_extrinsics:
        # Fallback (synthetic/missing-extrinsics) convention: yaw lives in
        # the body x/y plane. Unchanged from before 2026-07-26.
        return float(math.atan2(
            float(anchor_forward_in_current_body[1]),
            float(anchor_forward_in_current_body[0]),
        ))

    # Real-capture convention: yaw lives in the body x/z plane (see
    # docstring). Additional sign flip when the current side is a rear view.
    yaw = float(math.atan2(
        float(anchor_forward_in_current_body[2]),
        float(anchor_forward_in_current_body[0]),
    ))
    if isinstance(current_descriptor, dict) and current_descriptor.get("view") == "rear":
        yaw = -yaw
    return yaw


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

def _descriptor_local_map_points_raw(descriptor: object) -> Optional[np.ndarray]:
    """Shared extraction + height-band filtering for descriptor_local_map_points
    and descriptor_local_map_points_xyz. Returns the filtered array with all
    original columns intact (x, y, and z when present) -- callers slice down
    to what they actually need."""
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
        return arr
    return None


def descriptor_local_map_points(descriptor: object) -> Optional[np.ndarray]:
    """Return local LiDAR/map points in body coordinates as an Nx2 array.
    Used by the 2-D ICP registration path (local_map_icp and Scan Context's
    refinement step), which has no use for height."""
    arr = _descriptor_local_map_points_raw(descriptor)
    if arr is None:
        return None
    return np.asarray(arr[:, :2], dtype=np.float32)


def descriptor_local_map_points_xyz(descriptor: object) -> Optional[np.ndarray]:
    """Like descriptor_local_map_points but retains the height (z) column when
    the source data has one, for Scan Context's height-encoded cells (2026-07-02:
    closer to the original Kim & Kim 2018 max-height-per-cell encoding, instead
    of this project's earlier binary-occupancy simplification). Pads a zero
    height column when the source truly has no z, so callers always get a
    consistent Nx3 array -- degrades gracefully to a flat/uninformative height
    channel rather than erroring out."""
    arr = _descriptor_local_map_points_raw(descriptor)
    if arr is None:
        return None
    if arr.shape[1] >= 3:
        return np.asarray(arr[:, :3], dtype=np.float32)
    xy = np.asarray(arr[:, :2], dtype=np.float32)
    z = np.zeros((xy.shape[0], 1), dtype=np.float32)
    return np.concatenate([xy, z], axis=1)


def voxel_downsample_2d(points: np.ndarray, voxel_size_m: float = 0.10, max_points: int = 512) -> np.ndarray:
    # 2026-07-03: defaults relaxed from (0.12, 256). The vertical_fov_range fix
    # in go2_matterport_vision_cfg.py raised raw obstacle-band points per scan
    # from ~345 to ~2841 (measured directly on ep4) -- the old 256-point cap
    # was already barely below the old raw budget and would have thrown away
    # nearly all of the new headroom. Still well short of what the literature
    # survey found real indoor LiDAR pipelines retain (1000s of points); a
    # bigger jump is deferred pending the 3-episode validation batch alongside
    # the horizontal_res tightening above.
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


def voxel_downsample_xyz(points: np.ndarray, voxel_size_m: float = 0.10, max_points: int = 512) -> np.ndarray:
    points = np.asarray(points, dtype=np.float32)
    if points.ndim != 2 or points.shape[1] < 2 or len(points) == 0:
        return np.empty((0, 3), dtype=np.float32)
    if points.shape[1] < 3:
        z = np.zeros((points.shape[0], 1), dtype=np.float32)
        points = np.concatenate([points[:, :2], z], axis=1)
    voxel = max(1e-3, float(voxel_size_m))
    keys = np.round(points[:, :2] / voxel).astype(np.int32)
    _, first = np.unique(keys, axis=0, return_index=True)
    down = points[np.sort(first), :3]
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


def _icp_score(result: dict, residual_scale_m: float = 0.45) -> float:
    return float(
        result["overlap_ratio"]
        * max(0.0, 1.0 - float(result["median_residual_m"]) / residual_scale_m)
        * math.sqrt(max(1, int(result["inlier_count"])))
    )


def _estimate_normals_2d(points: np.ndarray, k: int = 8) -> np.ndarray:
    points = np.asarray(points, dtype=np.float32)
    normals = np.zeros((len(points), 2), dtype=np.float32)
    if len(points) < 3:
        return normals
    k = min(max(3, int(k)), max(1, len(points) - 1))
    diff = points[:, None, :2] - points[None, :, :2]
    dist2 = np.einsum("ijk,ijk->ij", diff, diff)
    np.fill_diagonal(dist2, np.inf)
    neighbor_idx = np.argpartition(dist2, k, axis=1)[:, :k]
    for i, idx in enumerate(neighbor_idx):
        patch = points[idx, :2]
        patch = patch - patch.mean(axis=0)
        cov = patch.T @ patch / max(1, len(patch) - 1)
        try:
            eigvals, eigvecs = np.linalg.eigh(cov)
        except np.linalg.LinAlgError:
            continue
        normal = eigvecs[:, int(np.argmin(eigvals))]
        norm = float(np.linalg.norm(normal))
        if norm > 1e-8:
            normals[i] = (normal / norm).astype(np.float32)
    return normals


def _localizability_from_correspondences(
    source_points: np.ndarray,
    target_points: np.ndarray,
    theta: float,
    translation: np.ndarray,
    *,
    correspondence_threshold_m: float = 0.45,
) -> dict:
    source = np.asarray(source_points, dtype=np.float32)
    target = np.asarray(target_points, dtype=np.float32)
    if len(source) < 12 or len(target) < 12:
        return {"available": False, "reason": "too_few_points"}
    transformed = _apply_transform_2d(source[:, :2], theta, translation)
    nearest, distances = _nearest_neighbor_2d(transformed, target[:, :2])
    inliers = distances < float(correspondence_threshold_m)
    if int(inliers.sum()) < 8:
        return {"available": False, "reason": "too_few_inliers"}
    normals = _estimate_normals_2d(target[:, :2])
    rows = []
    for p, target_idx, ok in zip(transformed, nearest, inliers):
        if not bool(ok):
            continue
        n = normals[int(target_idx)]
        if float(np.linalg.norm(n)) < 1e-8:
            continue
        rows.append([float(n[0]), float(n[1]), float(n[0] * (-p[1]) + n[1] * p[0])])
    if len(rows) < 8:
        return {"available": False, "reason": "too_few_normal_constraints"}
    jac = np.asarray(rows, dtype=np.float64)
    hessian = jac.T @ jac
    try:
        eigvals, eigvecs = np.linalg.eigh(hessian)
    except np.linalg.LinAlgError:
        return {"available": False, "reason": "eigendecomposition_failed"}
    eigvals = np.maximum(eigvals, 0.0)
    max_eig = float(eigvals[-1])
    if max_eig <= 1e-9:
        return {"available": False, "reason": "zero_information"}
    normalized = eigvals / max_eig
    condition = float(max_eig / max(float(eigvals[0]), 1e-9))
    weak_mask = normalized < 0.02

    # 2026-07-10: yaw-specific observability, diagnostic-only (does not gate or
    # reject anything -- see investigations/2026-07-10-.../FINDINGS.md and the
    # literature survey's §2.2). `hessian`'s eigen-decomposition above answers
    # "is *some* direction in (tx, ty, theta)-space weakly constrained", but
    # its eigenvectors are generally a mix of translation and rotation, not
    # aligned with the theta axis specifically -- so a corridor-style ambiguity
    # (translation along the corridor trades off against a compensating
    # rotation, the exact "rotational self-alias" failure mode this pipeline's
    # bearing-error investigation flagged as undetected by any existing
    # diagnostic) can leave `quality="full"` here while theta itself is
    # actually barely constrained. The Schur complement of the rotation block
    # against the translation block is the marginal Fisher information on
    # theta *after* optimally accounting for its correlation with translation
    # -- i.e. "how well is yaw constrained once translation is allowed to
    # absorb whatever it can", which is exactly the ambiguity this pipeline
    # cannot currently see.
    translation_block = hessian[:2, :2]
    rotation_translation_block = hessian[:2, 2]
    rotation_block = float(hessian[2, 2])
    yaw_marginal_information = None
    try:
        translation_block_inv = np.linalg.inv(translation_block)
        yaw_marginal_information = float(
            rotation_block
            - rotation_translation_block @ translation_block_inv @ rotation_translation_block
        )
    except np.linalg.LinAlgError:
        yaw_marginal_information = None
    yaw_normalized_marginal_information = (
        float(max(yaw_marginal_information, 0.0) / max_eig)
        if yaw_marginal_information is not None
        else None
    )
    yaw_observability = "unknown"
    if yaw_normalized_marginal_information is not None:
        yaw_observability = "weak" if yaw_normalized_marginal_information < 0.02 else "full"

    return {
        "available": True,
        "constraint_count": int(len(rows)),
        "eigenvalues": [float(v) for v in eigvals],
        "normalized_eigenvalues": [float(v) for v in normalized],
        "condition_number": condition,
        "weak_direction_count": int(weak_mask.sum()),
        "min_normalized_eigenvalue": float(normalized[0]),
        "weakest_direction": [float(v) for v in eigvecs[:, 0]],
        "quality": "degenerate" if bool(weak_mask.any()) or condition > 250.0 else "full",
        "yaw_marginal_information": yaw_marginal_information,
        "yaw_normalized_marginal_information": yaw_normalized_marginal_information,
        "yaw_observability": yaw_observability,
    }


def _height_consistency_from_correspondences(
    source_points_xyz: Optional[np.ndarray],
    target_points_xyz: Optional[np.ndarray],
    theta: float,
    translation: np.ndarray,
    *,
    correspondence_threshold_m: float = 0.45,
    height_threshold_m: float = 0.30,
) -> dict:
    if source_points_xyz is None or target_points_xyz is None:
        return {"available": False, "reason": "missing_xyz"}
    source = np.asarray(source_points_xyz, dtype=np.float32)
    target = np.asarray(target_points_xyz, dtype=np.float32)
    if source.ndim != 2 or target.ndim != 2 or source.shape[1] < 3 or target.shape[1] < 3:
        return {"available": False, "reason": "bad_xyz_shape"}
    if len(source) < 12 or len(target) < 12:
        return {"available": False, "reason": "too_few_points"}
    transformed_xy = _apply_transform_2d(source[:, :2], theta, translation)
    nearest, distances = _nearest_neighbor_2d(transformed_xy, target[:, :2])
    inliers = distances < float(correspondence_threshold_m)
    if int(inliers.sum()) < 8:
        return {"available": False, "reason": "too_few_inliers"}
    dz = np.abs(source[inliers, 2] - target[nearest[inliers], 2])
    consistent = dz <= float(height_threshold_m)
    ratio = float(consistent.sum() / max(1, len(dz)))
    return {
        "available": True,
        "inlier_count": int(inliers.sum()),
        "height_consistent_count": int(consistent.sum()),
        "height_consistent_ratio": ratio,
        "median_abs_height_error_m": float(np.median(dz)),
        "height_threshold_m": float(height_threshold_m),
        "quality": "consistent" if ratio >= 0.70 else "inconsistent",
    }


def _point_to_line_increment_2d(source_points: np.ndarray, target_points: np.ndarray) -> tuple[Optional[float], Optional[np.ndarray]]:
    source = np.asarray(source_points, dtype=np.float32)
    target = np.asarray(target_points, dtype=np.float32)
    if len(source) < 8 or len(target) < 8:
        return None, None
    normals = _estimate_normals_2d(target)
    rows = []
    rhs = []
    for p, q, n in zip(source[:, :2], target[:, :2], normals):
        if float(np.linalg.norm(n)) < 1e-8:
            continue
        rows.append([float(n[0]), float(n[1]), float(n[0] * (-p[1]) + n[1] * p[0])])
        rhs.append(float(np.dot(n, q - p)))
    if len(rows) < 8:
        return None, None
    a = np.asarray(rows, dtype=np.float64)
    b = np.asarray(rhs, dtype=np.float64)
    try:
        solution, *_ = np.linalg.lstsq(a, b, rcond=None)
    except np.linalg.LinAlgError:
        return None, None
    translation = np.asarray([solution[0], solution[1]], dtype=np.float32)
    theta = float(solution[2])
    if not np.isfinite(translation).all() or not math.isfinite(theta):
        return None, None
    theta = max(-0.35, min(0.35, theta))
    translation_norm = float(np.linalg.norm(translation))
    if translation_norm > 1.0:
        translation *= 1.0 / translation_norm
    return theta, translation


def _pose_delta_2d(a: dict, b: dict) -> dict:
    ta = np.asarray(a["translation"], dtype=np.float32)
    tb = np.asarray(b["translation"], dtype=np.float32)
    dtheta = math.atan2(
        math.sin(float(a["theta"]) - float(b["theta"])),
        math.cos(float(a["theta"]) - float(b["theta"])),
    )
    return {
        "translation_m": float(np.linalg.norm(ta - tb)),
        "rotation_deg": float(abs(math.degrees(dtheta))),
    }


def _cluster_icp_basins(scored_results: list[tuple[float, dict]], *, max_translation_m: float = 0.35, max_rotation_deg: float = 20.0) -> list[dict]:
    basins: list[dict] = []
    for score, result in sorted(scored_results, key=lambda item: item[0], reverse=True):
        assigned = False
        for basin in basins:
            delta = _pose_delta_2d(result, basin["best_result"])
            if delta["translation_m"] <= max_translation_m and delta["rotation_deg"] <= max_rotation_deg:
                basin["seed_count"] += 1
                if score > basin["best_score"]:
                    basin["best_score"] = float(score)
                    basin["best_result"] = result
                assigned = True
                break
        if not assigned:
            basins.append({
                "best_score": float(score),
                "best_result": result,
                "seed_count": 1,
            })
    return sorted(basins, key=lambda item: item["best_score"], reverse=True)


def _summarize_icp_basins(basins: list[dict], max_items: int = 4) -> tuple[list[dict], dict]:
    summaries = []
    for basin in basins[:max_items]:
        result = basin["best_result"]
        summaries.append({
            "score": float(basin["best_score"]),
            "seed_count": int(basin["seed_count"]),
            "overlap_ratio": float(result["overlap_ratio"]),
            "median_residual_m": float(result["median_residual_m"]),
            "inlier_count": int(result["inlier_count"]),
            "estimated_anchor_dx_m": float(result["translation"][0]),
            "estimated_anchor_dy_m": float(result["translation"][1]),
            "estimated_anchor_dtheta_deg": float(math.degrees(result["theta"])),
        })
    metrics = {
        "basin_count": int(len(basins)),
        "near_tie_basin_count": 0,
        "best_to_second_score_ratio": None,
        "best_to_second_translation_delta_m": None,
        "best_to_second_rotation_delta_deg": None,
        "ambiguity": "single_basin",
    }
    if len(basins) >= 2 and basins[0]["best_score"] > 0:
        ratio = float(basins[1]["best_score"] / basins[0]["best_score"])
        delta = _pose_delta_2d(basins[0]["best_result"], basins[1]["best_result"])
        near_ties = 0
        for basin in basins[1:]:
            if float(basin["best_score"] / basins[0]["best_score"]) >= 0.85:
                near_ties += 1
        metrics.update({
            "near_tie_basin_count": int(near_ties),
            "best_to_second_score_ratio": ratio,
            "best_to_second_translation_delta_m": float(delta["translation_m"]),
            "best_to_second_rotation_delta_deg": float(delta["rotation_deg"]),
            "ambiguity": (
                "high_confidence_multimodal"
                if ratio >= 0.85 and (delta["translation_m"] >= 0.75 or delta["rotation_deg"] >= 45.0)
                else "ranked_multibasin"
            ),
        })
    return summaries, metrics


def icp_seed_sweep_2d(
    source_points: np.ndarray,
    target_points: np.ndarray,
    yaw_initializers: list[float],
    *,
    max_iterations: int = 16,
    correspondence_threshold_m: float = 0.45,
    objective: str = "point_to_point",
) -> tuple[list[tuple[float, dict]], list[dict], dict]:
    scored = []
    for yaw in yaw_initializers:
        result = icp_rigid_transform_2d(
            source_points,
            target_points,
            initial_theta=yaw,
            max_iterations=max_iterations,
            correspondence_threshold_m=correspondence_threshold_m,
            objective=objective,
        )
        if result is None:
            continue
        scored.append((_icp_score(result, correspondence_threshold_m), result))
    basins = _cluster_icp_basins(scored)
    summaries, metrics = _summarize_icp_basins(basins)
    return scored, summaries, metrics


def _yaw_curve_diagnostics(scored_results: list[tuple[float, dict]]) -> dict:
    """Diagnostics over the *full* yaw-seed sweep (all seeds, before basin
    clustering), diagnostic-only -- does not gate or reject anything.

    2026-07-10, per investigations/2026-07-09-.../route_memory_literature_survey.md
    §2.1/2.2: `_summarize_icp_basins`'s `near_tie_basin_count` and
    `best_to_second_score_ratio` only compare the top-2 *basins* (clusters
    formed by a discrete translation/rotation distance threshold, see
    `_cluster_icp_basins`), so a broad-but-single-basin plateau in the raw
    per-seed score landscape -- narrower than the basin-clustering threshold
    but still wide enough to indicate a poorly-constrained yaw -- is invisible
    to it. This looks at the raw scores across all seeds instead.
    """
    if not scored_results:
        return {"available": False, "reason": "no_seeds"}
    scores = np.asarray([score for score, _ in scored_results], dtype=np.float64)
    thetas_deg = np.asarray([math.degrees(result["theta"]) for _, result in scored_results], dtype=np.float64)
    if len(scores) < 2 or float(scores.max()) <= 0.0:
        return {"available": False, "reason": "degenerate_scores"}

    probs = scores / float(scores.sum())
    probs = np.clip(probs, 1e-12, None)
    entropy = float(-np.sum(probs * np.log(probs)))
    max_entropy = float(np.log(len(scores)))
    normalized_entropy = float(entropy / max_entropy) if max_entropy > 0 else 0.0

    order = np.argsort(-scores)
    top_theta = float(thetas_deg[order[0]])

    def _angular_gap_deg(a: float, b: float) -> float:
        return float(abs(((a - b + 180.0) % 360.0) - 180.0))

    # peak width: total angular span, among seeds scoring within 15% of the
    # top score, of how far apart the two most different such seeds are --
    # a wide value means many meaningfully-different orientations all look
    # nearly as good as the winner (a plateau), even if they all happen to
    # fall inside one basin by the discrete clustering threshold.
    near_peak_mask = scores >= 0.85 * float(scores[order[0]])
    near_peak_thetas = thetas_deg[near_peak_mask]
    peak_width_deg = 0.0
    if len(near_peak_thetas) >= 2:
        gaps = [
            _angular_gap_deg(a, b)
            for i, a in enumerate(near_peak_thetas)
            for b in near_peak_thetas[i + 1:]
        ]
        peak_width_deg = float(max(gaps)) if gaps else 0.0

    # top-1 vs. the best-scoring seed at least 20 deg away (matching
    # `_cluster_icp_basins`'s own rotation-distance threshold), independent of
    # translation -- a small gap here means a meaningfully different
    # orientation almost matches the winner's score.
    top1_next_distinct_gap_deg = None
    top1_next_distinct_score_ratio = None
    for idx in order[1:]:
        if _angular_gap_deg(thetas_deg[idx], top_theta) >= 20.0:
            top1_next_distinct_gap_deg = _angular_gap_deg(thetas_deg[idx], top_theta)
            top1_next_distinct_score_ratio = float(scores[idx] / scores[order[0]])
            break

    return {
        "available": True,
        "seed_count": int(len(scores)),
        "top_yaw_deg": top_theta,
        "yaw_score_entropy": entropy,
        "yaw_score_normalized_entropy": normalized_entropy,
        "yaw_peak_width_deg": peak_width_deg,
        "yaw_top1_next_distinct_gap_deg": top1_next_distinct_gap_deg,
        "yaw_top1_next_distinct_score_ratio": top1_next_distinct_score_ratio,
    }


def _scan_context_yaw_check(
    anchor_points_xyz: Optional[np.ndarray],
    current_points_xyz: Optional[np.ndarray],
    icp_theta_rad: float,
) -> dict:
    """2026-07-12, problem-2 step 4 (per
    investigations/2026-07-09-.../route_memory_literature_survey.md §2.4 and
    investigations/2026-07-10-.../PROGRESS.md's plan): an INDEPENDENT yaw
    estimate from Scan Context's column-shift search, diagnostic-only (never
    gates or rejects, same convention as `_yaw_curve_diagnostics`/
    `_localizability_from_correspondences`'s yaw fields).

    Steps 1-2 (yaw_curve, yaw_observability) only ever re-examine the SAME
    ICP computation more closely -- the score landscape it already produced,
    the correspondence Hessian it already built. Neither can, even in
    principle, catch a case where ICP itself is a genuine, self-consistent
    local optimum that just happens to be wrong (the exact "clean_full_pose,
    healthy overlap/inliers, confidently wrong by 46-65 deg" signature in
    investigations/2026-07-09-.../FINDINGS.md §3.5) -- there is nothing
    "off" in ICP's own internal state to detect in that case. Scan Context is
    a structurally different algorithm (global egocentric occupancy
    similarity via column-shift search, not iterative nearest-point
    minimization), so its failure modes don't coincide with ICP's -- a
    disagreement between the two is evidence neither one alone can produce.

    Sign convention (verified against ICP's own convention, not just
    reasoned about -- see the unit test using a known synthetic rotation):
    `sequential_pair_anchor_relocalization` calls
    `icp_seed_sweep_2d(anchor_points, current_points, ...)`, i.e. ICP's
    `theta` is "the rotation applied to the anchor to align it with current".
    `column_shift_search_with_region(current_sc, anchor_sc)` rolls the
    *anchor's* Scan Context columns to best match current's, and
    `shift_to_yaw_rad` converts that roll into the same "anchor -> current"
    rotation sense -- so `scan_context_yaw_rad` and `icp_theta_rad` are
    directly comparable with no sign flip needed.
    """
    if anchor_points_xyz is None or current_points_xyz is None:
        return {"available": False, "reason": "missing_xyz"}
    if len(anchor_points_xyz) < 12 or len(current_points_xyz) < 12:
        return {"available": False, "reason": "too_few_points"}
    current_sc = build_scan_context(current_points_xyz)
    anchor_sc = build_scan_context(anchor_points_xyz)
    num_sectors = current_sc.shape[1]
    grid_cells = float(current_sc.shape[0] * num_sectors)
    similarity, shift, region_size = column_shift_search_with_region(current_sc, anchor_sc)
    scan_context_yaw_rad = shift_to_yaw_rad(shift, num_sectors)
    agreement_deg = abs(math.degrees(
        math.atan2(math.sin(scan_context_yaw_rad - icp_theta_rad), math.cos(scan_context_yaw_rad - icp_theta_rad))
    ))
    return {
        "available": True,
        "scan_context_yaw_deg": math.degrees(scan_context_yaw_rad),
        "scan_context_similarity": float(similarity),
        "scan_context_region_size": int(region_size),
        "scan_context_region_ratio": float(region_size) / grid_cells,
        "icp_scan_context_yaw_agreement_deg": agreement_deg,
    }


def _loftr_rear_yaw_check(
    anchor_descriptor: object,
    current_descriptor: object,
    icp_theta_rad: float,
    stage1_margin_threshold: float = 0.4,
    stage2_residual_threshold_m: float = 0.06,
    stage2_min_translation_m: float = 0.05,
) -> dict:
    """2026-07-13, per user's proposal (independently arrived at the same idea
    this project's retired `feature_depth_loftr_3d3d_rear` full-search backend
    already implemented, just never wired in as a per-attempt cross-check on
    `sequential_pair`'s ICP output): an INDEPENDENT yaw estimate from a
    genuinely different sensing MODALITY (RGB-D + LoFTR visual feature
    matching against the anchor's saved rear-camera view), not just a
    different algorithm on the same LiDAR point cloud.

    investigations/2026-07-13-icp-bearing-error-cross-batch-deep-dive/
    CORRELATIVE_VERIFIER_CHECK.md found that a structurally different
    LiDAR-only scoring function (occupancy-grid correlation) does not
    reliably disagree with ICP where ICP is wrong -- both are drawn to the
    same wrong solution when the ambiguity is genuine physical *geometric*
    self-similarity, since both only ever see the same LiDAR shape. RGB
    texture (wall color, doors, signage, lighting) is information LiDAR
    shape alone cannot see at all, so a disagreement here is evidence a
    same-modality check structurally cannot produce.

    2026-07-26: generalized from a single hardcoded anchor-rear/current-front
    combo to all 4 front/rear combos, gated by two signals validated in
    `investigations/2026-07-26-camera-yaw-fix-and-residual-confidence-gate/`
    against 249 real samples:
      - Stage 1 (combo selection): LoFTR match-count "class-sum" margin
        (aligned={FF,RR} vs. opposite={FR,RF} match-count totals) --
        `stage1_margin_threshold=0.4` gave 98-99% class accuracy inside 2m.
      - Stage 2 (rotation precision, given the chosen combo): the post-RANSAC
        3-D fit residual -- `stage2_residual_threshold_m=0.06` kept 89% of
        samples with 96.8% of those under 5 deg error, and stays informative
        at every distance rather than crudely correlating with distance
        alone (see the investigation folder for the full validation).
      - Stage 2 (minimum baseline, added same day after validating against
        real `confidently_wrong` ICP cases): near-zero raw (camera-local,
        pre-body-conversion) RANSAC translation lets the rotation solve
        collapse to a spuriously confident but wrong answer, via the same
        room-symmetry aliasing already known to affect LiDAR ICP -- of 259
        real `confidently_wrong` samples, the 45 with true distance <0.01m
        ALL had raw translation norm <=0.04m and ALL collapsed to
        computed_dtheta ~= 0 deg regardless of the true rotation (up to
        176 deg off), despite passing the residual gate with near-perfect
        fits (median residual 0.002m, 3000+ inliers). `stage2_min_
        translation_m=0.05` rejects these almost perfectly (44-45/45) at
        the cost of a small false-reject rate (~2-8 out of ~89) on
        genuinely well-solved non-degenerate cases.
    Still diagnostic-only: never gates or rejects the caller's ICP estimate
    by itself, only reports whether ITS OWN answer should be trusted via
    `vision_gate_passed`.
    """
    anchor_front = anchor_descriptor
    anchor_rear = build_rear_view_descriptor(anchor_descriptor)
    current_front = current_descriptor
    current_rear = build_rear_view_descriptor(current_descriptor)
    if anchor_rear is None or current_rear is None:
        return {"available": False, "reason": "missing_rear_view"}

    combos = {
        "anchorFront_currentFront": (anchor_front, current_front),
        "anchorFront_currentRear": (anchor_front, current_rear),
        "anchorRear_currentFront": (anchor_rear, current_front),
        "anchorRear_currentRear": (anchor_rear, current_rear),
    }
    match_points: dict[str, tuple] = {}
    match_counts: dict[str, int] = {}
    for name, (a_view, c_view) in combos.items():
        a_gray = descriptor_rgb_gray(a_view)
        c_gray = descriptor_rgb_gray(c_view)
        if a_gray is None or c_gray is None:
            continue
        a_uv, c_uv, _meta = loftr_match_points(a_gray, c_gray)
        if a_uv is None:
            continue
        match_points[name] = (a_uv, c_uv, a_view, c_view)
        match_counts[name] = int(len(a_uv))

    if not match_counts:
        return {"available": False, "reason": "missing_rgb_or_no_loftr_matches"}

    aligned = match_counts.get("anchorFront_currentFront", 0) + match_counts.get("anchorRear_currentRear", 0)
    opposite = match_counts.get("anchorFront_currentRear", 0) + match_counts.get("anchorRear_currentFront", 0)
    total = aligned + opposite
    stage1_margin = (abs(aligned - opposite) / total) if total > 0 else 0.0
    winning_class = ("anchorFront_currentFront", "anchorRear_currentRear") if aligned >= opposite \
        else ("anchorFront_currentRear", "anchorRear_currentFront")
    if stage1_margin < stage1_margin_threshold:
        return {
            "available": False, "reason": "low_stage1_margin",
            "stage1_margin": stage1_margin, "combo_matches": dict(match_counts),
        }

    # within the winning class, use whichever specific combo got more matches
    # (both members are geometrically valid per the class-degeneracy found
    # 2026-07-25 -- see investigations/2026-07-25-representative-stage1-wrong-
    # picks-under-1m/ -- so this is a tie-break, not a correctness gate).
    candidates = [c for c in winning_class if c in match_points]
    if not candidates:
        return {"available": False, "reason": "winning_class_missing_matches", "stage1_margin": stage1_margin}
    chosen_combo = max(candidates, key=lambda c: match_counts.get(c, 0))
    anchor_uv, current_uv, chosen_anchor_view, chosen_current_view = match_points[chosen_combo]
    if len(anchor_uv) < 8:
        return {
            "available": False, "reason": "too_few_loftr_matches", "stage1_margin": stage1_margin,
            "chosen_combo": chosen_combo, "loftr_matches": int(len(anchor_uv)),
        }

    anchor_depth = descriptor_depth(chosen_anchor_view)
    current_depth = descriptor_depth(chosen_current_view)
    if anchor_depth is None or current_depth is None:
        return {"available": False, "reason": "missing_depth", "stage1_margin": stage1_margin, "chosen_combo": chosen_combo}

    anchor_k = descriptor_intrinsics(chosen_anchor_view, anchor_depth.shape[1], anchor_depth.shape[0])
    current_k = descriptor_intrinsics(chosen_current_view, current_depth.shape[1], current_depth.shape[0])
    anchor_points_all, anchor_valid = backproject_points(anchor_uv, anchor_depth, anchor_k)
    current_points_all, current_valid = backproject_points(current_uv, current_depth, current_k)
    valid = sorted(set(anchor_valid).intersection(current_valid))
    if len(valid) < 8:
        return {
            "available": False, "reason": "too_few_depth_valid_matches", "stage1_margin": stage1_margin,
            "chosen_combo": chosen_combo, "loftr_matches": int(len(anchor_uv)),
        }

    anchor_index_by_match = {m: i for i, m in enumerate(anchor_valid)}
    current_index_by_match = {m: i for i, m in enumerate(current_valid)}
    anchor_points = np.asarray(
        [anchor_points_all[anchor_index_by_match[i]] for i in valid], dtype=np.float32
    )
    current_points = np.asarray(
        [current_points_all[current_index_by_match[i]] for i in valid], dtype=np.float32
    )

    rotation, translation, inliers = ransac_rigid_transform(anchor_points, current_points, threshold_m=0.35)
    if rotation is None:
        return {
            "available": False, "reason": "ransac_failed", "stage1_margin": stage1_margin,
            "chosen_combo": chosen_combo,
            "loftr_matches": int(len(anchor_uv)), "depth_valid_matches": int(len(valid)),
        }
    inlier_count = int(inliers.sum())
    if inlier_count < 6:
        return {
            "available": False, "reason": "too_few_3d_inliers", "stage1_margin": stage1_margin,
            "chosen_combo": chosen_combo,
            "loftr_matches": int(len(anchor_uv)), "inlier_count": inlier_count,
        }

    residual = np.linalg.norm(
        (rotation @ anchor_points[inliers].T).T + translation - current_points[inliers], axis=1
    )
    median_residual_m = float(np.median(residual))
    raw_translation_norm_m = float(np.linalg.norm(translation))
    # 2026-07-26: near-zero raw (camera-local, pre-body-conversion) translation
    # makes the Kabsch rotation solve unobservable from a locally self-similar
    # scene (the same room-symmetry aliasing already known to affect LiDAR
    # ICP), independent of how good the residual/inlier count look -- found by
    # checking all 259 real confidently_wrong ICP cases: 45 had true distance
    # <0.01m, ALL 45 collapsed to computed_dtheta ~= 0 deg regardless of the
    # true rotation (up to 176 deg off), yet passed the residual gate with
    # near-perfect fit (median residual 0.002m, 3000+ inliers). Their raw
    # translation norm was <=0.04m in every case (median 0.0023m) vs. a
    # median of 1.05m for correctly-solved non-degenerate cases -- a nearly
    # clean separator. See investigations/2026-07-26-camera-yaw-fix-and-
    # residual-confidence-gate/ for the full validation.
    min_translation_gate_passed = raw_translation_norm_m >= stage2_min_translation_m
    stage2_gate_passed = median_residual_m <= stage2_residual_threshold_m and min_translation_gate_passed
    vision_gate_passed = stage2_gate_passed  # stage1 gate already enforced above (early return otherwise)

    anchor_dtheta = camera_rotation_to_body_yaw(rotation, chosen_current_view, chosen_anchor_view)
    agreement_deg = abs(math.degrees(
        math.atan2(math.sin(anchor_dtheta - icp_theta_rad), math.cos(anchor_dtheta - icp_theta_rad))
    ))
    # 2026-07-13 (continued): also expose LoFTR-rear's own translation, in the
    # same body-frame (dx, dy) convention ICP's anchor_dx_m/anchor_dy_m use --
    # lets an offline check compare LoFTR-rear's own BEARING accuracy against
    # ICP's, not just its rotation accuracy (the only thing this function
    # reported before). Reuses camera_point_to_body unmodified, same as
    # feature_depth_anchor_relocalization's own rear-view branch.
    anchor_origin_in_current_body = camera_point_to_body(translation, chosen_current_view)
    loftr_bearing_deg = math.degrees(math.atan2(
        float(anchor_origin_in_current_body[1]), float(anchor_origin_in_current_body[0])
    ))
    return {
        "available": True,
        "stage1_margin": stage1_margin,
        "chosen_combo": chosen_combo,
        "combo_matches": dict(match_counts),
        "loftr_matches": int(len(anchor_uv)),
        "depth_valid_matches": int(len(valid)),
        "inlier_count": inlier_count,
        "median_3d_residual_m": median_residual_m,
        "raw_translation_norm_m": raw_translation_norm_m,
        "min_translation_gate_passed": min_translation_gate_passed,
        "vision_gate_passed": vision_gate_passed,
        "loftr_rear_dtheta_deg": math.degrees(anchor_dtheta),
        "icp_loftr_rear_yaw_agreement_deg": agreement_deg,
        "loftr_rear_dx_m": float(anchor_origin_in_current_body[0]),
        "loftr_rear_dy_m": float(anchor_origin_in_current_body[1]),
        "loftr_rear_bearing_to_anchor_deg": loftr_bearing_deg,
    }


def build_local_map_match_snapshot(
    anchor_points: np.ndarray,
    current_points: np.ndarray,
    theta: float,
    translation: np.ndarray,
    correspondence_threshold_m: float = 0.45,
) -> dict:
    """JSON-serializable snapshot of one anchor-vs-current local-map ICP
    alignment, for offline visual match-quality diagnosis (see
    ``plot_anchor_match_diagnostics.py``). Both point sets are already
    voxel-downsampled (<=256 points) by the time backends call this, so a
    snapshot is only a few KB -- safe to attach per accepted match when a
    caller opts in via ``capture_match_snapshots``, rather than only ever
    keeping the scalar summary metrics (overlap ratio, residual, confidence)
    that the rest of this module already records.
    """
    anchor_points = np.asarray(anchor_points, dtype=np.float32)
    current_points = np.asarray(current_points, dtype=np.float32)
    transformed_anchor = _apply_transform_2d(anchor_points, theta, translation)
    _, distances = _nearest_neighbor_2d(transformed_anchor, current_points)
    inlier_mask = distances < float(correspondence_threshold_m)
    return {
        "anchor_points_body": anchor_points.tolist(),
        "current_points_body": current_points.tolist(),
        "theta_rad": float(theta),
        "translation": [float(translation[0]), float(translation[1])],
        "anchor_inlier_mask": inlier_mask.tolist(),
        "correspondence_threshold_m": float(correspondence_threshold_m),
    }


def corridor_degeneracy_ratio(points: np.ndarray, k: int = 8) -> Optional[float]:
    """Estimate how geometrically constrained a 2-D local-map point cloud is for ICP.

    Point-to-point ICP's translation update is only well-conditioned along
    directions where the surface normal varies; a straight corridor (parallel
    walls) has normals clustered along a single axis, so translation along the
    corridor is almost unconstrained no matter how many points are sampled.

    For each point we estimate a local surface normal from a k-nearest-neighbor
    patch (the eigenvector of the patch covariance with the *smaller*
    eigenvalue — the point spread is thin across a locally-planar wall and wide
    along it). Normals are accumulated into a sign-invariant scatter matrix
    ``mean(n @ n.T)`` (this cancels the +/-n ambiguity of a normal direction
    automatically, since ``n @ n.T == (-n) @ (-n).T``). The eigenvalue ratio
    ``lambda_min / lambda_max`` of that scatter matrix is near 0 when every
    local normal points along the same axis (degenerate corridor) and closer to
    1 when normals span multiple directions (corners, doorways, clutter).

    Returns ``None`` if there are too few points to estimate normals.
    """
    points = np.asarray(points, dtype=np.float64)
    if points.ndim != 2 or points.shape[1] < 2:
        return None
    n = len(points)
    k = max(3, int(k))
    if n < k + 1:
        return None
    xy = points[:, :2]
    diff = xy[:, None, :] - xy[None, :, :]
    dist2 = np.einsum("ijk,ijk->ij", diff, diff)
    np.fill_diagonal(dist2, np.inf)
    neighbor_idx = np.argpartition(dist2, k, axis=1)[:, :k]

    scatter = np.zeros((2, 2), dtype=np.float64)
    valid = 0
    for i in range(n):
        patch = xy[neighbor_idx[i]]
        patch = patch - patch.mean(axis=0)
        cov = (patch.T @ patch) / max(1, len(patch) - 1)
        eigvals, eigvecs = np.linalg.eigh(cov)
        normal = eigvecs[:, 0]
        norm = float(np.linalg.norm(normal))
        if norm < 1e-9:
            continue
        normal = normal / norm
        scatter += np.outer(normal, normal)
        valid += 1
    if valid == 0:
        return None
    scatter /= valid
    eigvals = np.linalg.eigvalsh(scatter)
    lam_min, lam_max = float(eigvals[0]), float(eigvals[1])
    return lam_min / (lam_max + 1e-6)


def icp_rigid_transform_2d(
    source_points: np.ndarray,
    target_points: np.ndarray,
    *,
    initial_theta: float = 0.0,
    max_iterations: int = 24,
    correspondence_threshold_m: float = 0.45,
    objective: str = "point_to_point",
) -> Optional[dict]:
    """Align ``source`` to ``target`` with 2-D ICP.

    ``point_to_line`` and ``point_to_line_2p5d`` use local target normals for
    the incremental solve. ``ndt_2d`` is currently an experimental alias for the
    same point-to-line increment, kept separate so A/B runs can be logged without
    claiming this compact implementation is a full NDT map.
    """
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
        if objective in ("point_to_line", "point_to_line_2p5d", "ndt_2d"):
            theta_delta, translation_delta = _point_to_line_increment_2d(
                transformed[inliers], target[nearest[inliers]]
            )
        else:
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
    dead_reckoning_yaw_rad: Optional[float] = None,
    corridor_degeneracy_skip_threshold: float = 0.15,
    heading_consistency_max_error_rad: float = math.radians(90.0),
    capture_match_snapshots: bool = False,
    icp_objective: str = "point_to_point",
    voxel_size_m: float = 0.10,
    max_points: int = 512,
    quality_policy: str = "diagnostic",
) -> Optional[object]:
    """Relocalize against saved route anchors using LiDAR/local-map scan matching.

    ``dead_reckoning_yaw_rad``, when provided, is the caller's own non-oracle
    action-integrated absolute yaw (radians, relative to the outbound-start
    frame) at the current step (e.g.
    ``RouteMemoryAgent.current_absolute_pose_from_start()[2]``). It is used only
    as a cross-check (P1 heading-consistency gate); passing ``None`` preserves
    the previous behavior (always accept the top-scoring ICP yaw seed).

    ``capture_match_snapshots``, when true, attaches a small anchor/current
    point-cloud snapshot (see ``build_local_map_match_snapshot``) to every
    accepted (``outcome == "pose_candidate"``) covisibility record, for
    offline visualization of *why* a match looked the way it did -- the
    scalar metrics already recorded here (overlap, residual, confidence) say
    a match was bad but not what the two point clouds actually looked like.
    Off by default since it noticeably grows the measurement JSON.
    """
    from route_memory_agent import AnchorRelocalization, compose_pose, inverse_delta, wrap_angle

    def _implied_absolute_yaw(anchor_pose_from_start, dx: float, dy: float, dtheta: float) -> float:
        # Mirrors RouteMemoryAgent._project_estimate_to_anchor's frame composition:
        # (dx, dy, dtheta) is "anchor pose as seen from current", so inverting it and
        # composing onto the anchor's own absolute pose yields current's absolute pose.
        source_pose_from_current = [float(dx), float(dy), float(dtheta)]
        current_pose_from_source = inverse_delta(source_pose_from_current)
        current_pose_from_start = compose_pose(anchor_pose_from_start, current_pose_from_source)
        return wrap_angle(current_pose_from_start[2])

    _diagnostic_inc(diagnostics, "attempts")
    _diagnostic_inc(diagnostics, "local_map_attempts")
    if diagnostics is not None:
        diagnostics["matcher_backend"] = "local_map_icp"
        diagnostics["local_map_icp_objective"] = str(icp_objective)
        diagnostics["local_map_voxel_size_m"] = float(voxel_size_m)
        diagnostics["local_map_max_points"] = int(max_points)
        diagnostics["local_map_quality_policy"] = str(quality_policy)
    current_points = descriptor_local_map_points(current_descriptor)
    if current_points is None:
        _diagnostic_inc(diagnostics, "missing_current_local_map")
        return None
    current_points = voxel_downsample_2d(current_points, voxel_size_m=voxel_size_m, max_points=max_points)
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
        anchor_points = voxel_downsample_2d(anchor_points, voxel_size_m=voxel_size_m, max_points=max_points)
        record["anchor_points"] = int(len(anchor_points))
        record["current_points"] = int(len(current_points))
        if len(anchor_points) < 12:
            _diagnostic_inc(diagnostics, "too_few_anchor_local_map_points")
            record["outcome"] = "too_few_anchor_local_map_points"
            _append_covisibility_record(diagnostics, record)
            continue

        # P2: skip ICP entirely for anchors whose local geometry cannot constrain
        # translation along at least one axis (e.g. a straight corridor slice).
        degeneracy_ratio = corridor_degeneracy_ratio(anchor_points)
        record["corridor_degeneracy_ratio"] = (
            float(degeneracy_ratio) if degeneracy_ratio is not None else None
        )
        if degeneracy_ratio is not None and degeneracy_ratio < corridor_degeneracy_skip_threshold:
            _diagnostic_inc(diagnostics, "corridor_degenerate_anchor_skipped")
            record["outcome"] = "corridor_degenerate_anchor_skipped"
            _append_covisibility_record(diagnostics, record)
            continue

        icp_results, basin_summary, basin_metrics = icp_seed_sweep_2d(
            anchor_points,
            current_points,
            yaw_initializers,
            max_iterations=16,
            correspondence_threshold_m=0.45,
            objective=icp_objective,
        )
        record["icp_basin_count"] = int(basin_metrics["basin_count"])
        record["icp_near_tie_basin_count"] = int(basin_metrics["near_tie_basin_count"])
        record["icp_ambiguity"] = str(basin_metrics["ambiguity"])
        record["icp_top_basins"] = basin_summary
        if basin_metrics["best_to_second_score_ratio"] is not None:
            record["icp_best_to_second_score_ratio"] = float(basin_metrics["best_to_second_score_ratio"])
            record["icp_best_to_second_translation_delta_m"] = float(basin_metrics["best_to_second_translation_delta_m"])
            record["icp_best_to_second_rotation_delta_deg"] = float(basin_metrics["best_to_second_rotation_delta_deg"])
        if not icp_results:
            _diagnostic_inc(diagnostics, "local_map_icp_failed")
            record["outcome"] = "local_map_icp_failed"
            _append_covisibility_record(diagnostics, record)
            continue
        icp_results.sort(key=lambda item: item[0], reverse=True)

        # P1: walk the yaw seeds best-score-first and take the first one whose
        # implied absolute orientation is consistent with dead reckoning, instead
        # of blindly trusting the top score (which corridor symmetry can make a
        # 180-degree-flipped solution win by a hair).
        score = result = None
        heading_error_rad = None
        rejected_flip_count = 0
        for candidate_score, candidate_result in icp_results:
            if dead_reckoning_yaw_rad is None:
                score, result = candidate_score, candidate_result
                break
            implied_yaw = _implied_absolute_yaw(
                anchor.pose_from_start,
                candidate_result["translation"][0],
                candidate_result["translation"][1],
                candidate_result["theta"],
            )
            error = abs(wrap_angle(implied_yaw - dead_reckoning_yaw_rad))
            if error > heading_consistency_max_error_rad:
                rejected_flip_count += 1
                continue
            score, result = candidate_score, candidate_result
            heading_error_rad = error
            break
        if result is None:
            _diagnostic_inc(diagnostics, "heading_consistency_rejected")
            record["outcome"] = "heading_consistency_rejected"
            record["rejected_flip_candidates"] = rejected_flip_count
            _append_covisibility_record(diagnostics, record)
            continue
        if rejected_flip_count:
            record["rejected_flip_candidates"] = rejected_flip_count
        if heading_error_rad is not None:
            record["heading_consistency_error_rad"] = float(heading_error_rad)

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
            degeneracy_ratio=(float(degeneracy_ratio) if degeneracy_ratio is not None else None),
        )
        record["estimated_distance_to_anchor_m"] = float(candidate.distance_to_anchor_m)
        record["estimated_bearing_to_anchor_deg"] = float(candidate.bearing_to_anchor_deg)
        record["outcome"] = "pose_candidate"
        if capture_match_snapshots:
            record["match_snapshot"] = build_local_map_match_snapshot(
                anchor_points, current_points, result["theta"], result["translation"]
            )
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


def sequential_pair_anchor_relocalization(
    current_descriptor: object,
    current_anchor: Optional[object],
    next_anchor: Optional[object],
    diagnostics: Optional[dict] = None,
    return_candidates: bool = False,
    corridor_degeneracy_skip_threshold: float = 0.15,
    heading_consistency_max_error_rad: float = math.radians(90.0),
    capture_match_snapshots: bool = False,
    icp_objective: str = "point_to_point",
    voxel_size_m: float = 0.10,
    max_points: int = 512,
    quality_policy: str = "diagnostic",
    loftr_rear_yaw_check: bool = False,
) -> Optional[object]:
    """Relocalize against exactly two known anchors -- the one the caller is
    currently standing near and the one it's walking toward next -- instead
    of searching every recorded anchor for identity.

    2026-07-04, per the user's design: return always starts standing exactly
    on the last outbound anchor (RouteMemoryAgent.finalize_outbound() appends
    a final anchor at that exact position), so anchor *identity* is known by
    construction the whole way back -- there is never a "which anchor is
    this" question to answer, only "how far/what bearing to the next one."
    Dropping Scan Context's whole-candidate-set disambiguation (the thing
    this project's other backends spend most of their complexity on) is safe
    here specifically because the candidate set is always exactly these two
    anchors; `RouteMemoryAgent._sequence_match_observation`'s existing
    scoring naturally advances `_target_anchor_index` forward as the
    next-anchor candidate starts winning, and it can never jump to a third
    anchor since none are ever offered -- monotonic progression falls out of
    the restricted candidate set, not a separate state machine.

    Same ICP thresholds as ``local_map_anchor_relocalization`` applied to just
    these two anchors instead of a searched candidate list.
    """
    from route_memory_agent import AnchorRelocalization

    _diagnostic_inc(diagnostics, "attempts")
    _diagnostic_inc(diagnostics, "sequential_pair_attempts")
    if diagnostics is not None:
        diagnostics["matcher_backend"] = "sequential_pair"
        diagnostics["sequential_pair_icp_objective"] = str(icp_objective)
        diagnostics["sequential_pair_voxel_size_m"] = float(voxel_size_m)
        diagnostics["sequential_pair_max_points"] = int(max_points)
        diagnostics["sequential_pair_quality_policy"] = str(quality_policy)

    current_points = descriptor_local_map_points(current_descriptor)
    if current_points is None:
        _diagnostic_inc(diagnostics, "missing_current_local_map")
        return None
    current_points = voxel_downsample_2d(current_points, voxel_size_m=voxel_size_m, max_points=max_points)
    current_points_xyz = descriptor_local_map_points_xyz(current_descriptor)
    current_points_xyz = (
        voxel_downsample_xyz(current_points_xyz, voxel_size_m=voxel_size_m, max_points=max_points)
        if current_points_xyz is not None else None
    )
    if len(current_points) < 12:
        _diagnostic_inc(diagnostics, "too_few_current_local_map_points")
        return None

    yaw_initializers = [math.radians(float(deg)) for deg in range(-180, 180, 15)]
    pose_candidates = []
    attempt_index = diagnostics.get("attempts", 0) if diagnostics is not None else None
    for anchor in (current_anchor, next_anchor):
        if anchor is None or not isinstance(anchor.descriptor, dict):
            continue
        anchor_points = descriptor_local_map_points(anchor.descriptor)
        record = {
            "attempt": int(attempt_index) if attempt_index is not None else None,
            "anchor_index": int(anchor.index),
            "anchor_distance_from_start_m": float(anchor.distance_from_start_m),
            "route_remaining_to_start_m": float(anchor.route_remaining_to_start_m),
            "matcher_backend": "sequential_pair",
            "outcome": "not_evaluated",
        }
        if anchor_points is None:
            _diagnostic_inc(diagnostics, "candidate_missing_local_map")
            record["outcome"] = "candidate_missing_local_map"
            _append_covisibility_record(diagnostics, record)
            continue
        anchor_points = voxel_downsample_2d(anchor_points, voxel_size_m=voxel_size_m, max_points=max_points)
        anchor_points_xyz = descriptor_local_map_points_xyz(anchor.descriptor)
        anchor_points_xyz = (
            voxel_downsample_xyz(anchor_points_xyz, voxel_size_m=voxel_size_m, max_points=max_points)
            if anchor_points_xyz is not None else None
        )
        record["anchor_points"] = int(len(anchor_points))
        record["current_points"] = int(len(current_points))
        if anchor_points_xyz is not None:
            record["anchor_points_xyz"] = int(len(anchor_points_xyz))
            record["anchor_z_span_m"] = float(np.ptp(anchor_points_xyz[:, 2])) if len(anchor_points_xyz) else 0.0
        if current_points_xyz is not None:
            record["current_points_xyz"] = int(len(current_points_xyz))
            record["current_z_span_m"] = float(np.ptp(current_points_xyz[:, 2])) if len(current_points_xyz) else 0.0
        if len(anchor_points) < 12:
            _diagnostic_inc(diagnostics, "too_few_anchor_local_map_points")
            record["outcome"] = "too_few_anchor_local_map_points"
            _append_covisibility_record(diagnostics, record)
            continue

        degeneracy_ratio = corridor_degeneracy_ratio(anchor_points)
        record["corridor_degeneracy_ratio"] = (
            float(degeneracy_ratio) if degeneracy_ratio is not None else None
        )
        if degeneracy_ratio is not None and degeneracy_ratio < corridor_degeneracy_skip_threshold:
            _diagnostic_inc(diagnostics, "corridor_degenerate_anchor_observed")

        scored_results, basin_summary, basin_metrics = icp_seed_sweep_2d(
            anchor_points,
            current_points,
            yaw_initializers,
            max_iterations=16,
            correspondence_threshold_m=0.45,
            objective=icp_objective,
        )
        record["icp_basin_count"] = int(basin_metrics["basin_count"])
        record["icp_near_tie_basin_count"] = int(basin_metrics["near_tie_basin_count"])
        record["icp_ambiguity"] = str(basin_metrics["ambiguity"])
        record["icp_top_basins"] = basin_summary
        if basin_metrics["best_to_second_score_ratio"] is not None:
            record["icp_best_to_second_score_ratio"] = float(basin_metrics["best_to_second_score_ratio"])
            record["icp_best_to_second_translation_delta_m"] = float(basin_metrics["best_to_second_translation_delta_m"])
            record["icp_best_to_second_rotation_delta_deg"] = float(basin_metrics["best_to_second_rotation_delta_deg"])
        # 2026-07-10: diagnostic-only, does not gate/reject -- see
        # investigations/2026-07-10-.../FINDINGS.md and _yaw_curve_diagnostics'
        # docstring. Computed from the same seed sweep already run above, no
        # extra ICP calls.
        record["yaw_curve"] = _yaw_curve_diagnostics(scored_results)
        if not scored_results:
            _diagnostic_inc(diagnostics, "sequential_pair_icp_failed")
            record["outcome"] = "sequential_pair_icp_failed"
            _append_covisibility_record(diagnostics, record)
            continue
        score, result = max(scored_results, key=lambda item: item[0])
        localizability = _localizability_from_correspondences(
            anchor_points,
            current_points,
            result["theta"],
            result["translation"],
            correspondence_threshold_m=0.45,
        )
        record["localizability"] = localizability
        record["scan_context_yaw_check"] = _scan_context_yaw_check(
            anchor_points_xyz, current_points_xyz, result["theta"],
        )
        if loftr_rear_yaw_check:
            record["loftr_rear_yaw_check"] = _loftr_rear_yaw_check(
                anchor.descriptor, current_descriptor, result["theta"],
            )
        height_consistency = None
        if icp_objective == "point_to_line_2p5d":
            height_consistency = _height_consistency_from_correspondences(
                anchor_points_xyz,
                current_points_xyz,
                result["theta"],
                result["translation"],
                correspondence_threshold_m=0.45,
            )
            record["height_consistency"] = height_consistency
        match_class = "clean_full_pose"
        if (
            height_consistency is not None
            and height_consistency.get("available")
            and height_consistency.get("quality") == "inconsistent"
        ):
            match_class = "height_inconsistent_2p5d"
            _diagnostic_inc(diagnostics, "sequential_pair_height_inconsistent_2p5d")
        elif localizability.get("available") and localizability.get("quality") == "degenerate":
            match_class = "partial_pose_degenerate"
            _diagnostic_inc(diagnostics, "sequential_pair_partial_pose_degenerate")
        elif basin_metrics["ambiguity"] == "high_confidence_multimodal":
            match_class = "ambiguous_high_confidence"
            _diagnostic_inc(diagnostics, "sequential_pair_ambiguous_high_confidence")
        record["match_class"] = match_class
        if quality_policy == "strict" and match_class in (
            "ambiguous_high_confidence",
            "partial_pose_degenerate",
            "height_inconsistent_2p5d",
        ):
            record["outcome"] = match_class
            _append_covisibility_record(diagnostics, record)
            continue

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
        # 2026-07-26 Stage 1 (shadow, read-only -- per the same phased
        # rollout discipline this project already uses for Policy V2):
        # per-attempt diagnostic only, computed here and NEVER consulted by
        # the accept/promote/confidence logic in this function. Flags the
        # exact precondition this whole investigation targets -- ICP self-
        # reporting high confidence (>=0.9, the same threshold used to
        # define "confidently_wrong" throughout investigations/2026-07-26-
        # camera-yaw-fix-and-residual-confidence-gate/) while the
        # independently-gated vision check (Stage-1 margin + Stage-2
        # residual + Stage-2 min-translation, same investigation) disagrees
        # by a wide margin. The 45deg disagreement threshold is a
        # provisional placeholder, not yet calibrated against a live replay
        # -- recalibrate once offline replay data exists rather than
        # trusting this number.
        _vision_check = record.get("loftr_rear_yaw_check")
        if _vision_check is not None:
            _icp_confidently_wrong_precondition = confidence >= 0.9
            _vision_disagrees = bool(
                _icp_confidently_wrong_precondition
                and _vision_check.get("vision_gate_passed")
                and _vision_check.get("icp_loftr_rear_yaw_agreement_deg", 0.0) >= 45.0
            )
            _vision_check["icp_confidently_wrong_precondition"] = _icp_confidently_wrong_precondition
            _vision_check["vision_disagrees_with_confident_icp"] = _vision_disagrees
            if _vision_disagrees:
                _diagnostic_inc(diagnostics, "vision_disagrees_with_confident_icp")
        if inlier_count < 12 or overlap < 0.12 or confidence < 0.15:
            _diagnostic_inc(diagnostics, "low_confidence_sequential_pair_pose")
            record["outcome"] = "low_confidence_sequential_pair_pose"
            _append_covisibility_record(diagnostics, record)
            continue

        candidate = AnchorRelocalization(
            anchor_index=int(anchor.index),
            anchor_dx_m=float(result["translation"][0]),
            anchor_dy_m=float(result["translation"][1]),
            anchor_dtheta_rad=float(result["theta"]),
            confidence=float(confidence),
            backend="sequential_pair",
            inlier_count=inlier_count,
            reprojection_error_px=None,
            anchor_heading_reliable=True,
            degeneracy_ratio=(float(degeneracy_ratio) if degeneracy_ratio is not None else None),
            match_class=str(match_class),
            near_tie_basin_count=int(basin_metrics["near_tie_basin_count"]),
            best_to_second_score_ratio=(
                float(basin_metrics["best_to_second_score_ratio"])
                if basin_metrics.get("best_to_second_score_ratio") is not None
                else None
            ),
        )
        record["estimated_distance_to_anchor_m"] = float(candidate.distance_to_anchor_m)
        record["estimated_bearing_to_anchor_deg"] = float(candidate.bearing_to_anchor_deg)
        record["outcome"] = "pose_candidate"
        if capture_match_snapshots:
            record["match_snapshot"] = build_local_map_match_snapshot(
                anchor_points, current_points, result["theta"], result["translation"]
            )
        _append_covisibility_record(diagnostics, record)
        pose_candidates.append(candidate)

    if not pose_candidates:
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


def compute_anchor_alias_scores(
    anchors: list,
    min_neighbor_offset: int = 2,
    max_neighbor_offset: int = 5,
    voxel_size_m: float = 0.10,
    max_points: int = 512,
    icp_objective: str = "point_to_point",
) -> dict[int, float]:
    """One-time, offline anchor-distinctiveness precompute (user-proposed
    2026-07-06, see investigations/2026-07-06-anchor-selection-and-icp-aliasing).

    For each anchor, alias_score is the best ICP overlap_ratio it achieves
    against any *other* anchor between min_neighbor_offset and
    max_neighbor_offset route positions away (index distance, not meters) --
    deliberately excluding the immediate +/-1 neighbor, which is *expected* to
    overlap well since consecutive anchors are only about one
    anchor_spacing_m apart. A high score against a non-adjacent anchor
    instead means this anchor's local structure genuinely repeats elsewhere
    on the route.

    Confirmed directly against real hard-11 data before being wired into
    anything: ep187's anchor1 -- where sequential_pair's shadow got
    persistently stuck racing ahead of the true position -- scores
    0.44-0.54 overlap against anchors 3-6 route-positions away (true
    distance 2-5m), essentially flat with distance; a clean anchor pair at
    the same episode (anchor2) drops to ~0.50 by 3 positions away and
    continues falling. Anchor spacing itself was checked and is uniform
    (0.7-1.2m) in both episodes this was found in, ruling out "anchors are
    just unusually close together" as a simpler alternative explanation.

    Call once right after RouteMemoryAgent.finalize_outbound() (every
    anchor's point cloud is fixed by then) -- roughly
    anchor_count * (max_neighbor_offset - min_neighbor_offset + 1) ICP calls
    (each unordered pair computed once, not anchor_count^2), a one-time cost
    that never touches return-phase live-matching latency.
    """
    yaw_initializers = [math.radians(float(deg)) for deg in range(-180, 180, 15)]
    downsampled: dict[int, np.ndarray] = {}
    for anchor in anchors:
        if not isinstance(anchor.descriptor, dict):
            continue
        points = descriptor_local_map_points(anchor.descriptor)
        if points is None:
            continue
        points = voxel_downsample_2d(points, voxel_size_m=voxel_size_m, max_points=max_points)
        if len(points) < 12:
            continue
        downsampled[int(anchor.index)] = points

    scores: dict[int, float] = {idx: 0.0 for idx in downsampled}
    indices = sorted(downsampled)
    for i, idx_a in enumerate(indices):
        for idx_b in indices[i + 1:]:
            offset = idx_b - idx_a
            if offset < min_neighbor_offset or offset > max_neighbor_offset:
                continue
            scored_results, _basin_summary, _basin_metrics = icp_seed_sweep_2d(
                downsampled[idx_a], downsampled[idx_b], yaw_initializers,
                max_iterations=16, correspondence_threshold_m=0.45, objective=icp_objective,
            )
            if not scored_results:
                continue
            _score, result = max(scored_results, key=lambda item: item[0])
            overlap = float(result["overlap_ratio"])
            scores[idx_a] = max(scores[idx_a], overlap)
            scores[idx_b] = max(scores[idx_b], overlap)
    return scores


def scan_context_anchor_relocalization(
    current_descriptor: object,
    anchors: list,
    max_candidates: Optional[int] = None,
    diagnostics: Optional[dict] = None,
    return_candidates: bool = False,
    min_similarity: float = 0.2,
    min_connected_region_cells: int = 3,
    min_combined_score_margin_ratio: float = 1.15,
    dead_reckoning_yaw_rad: Optional[float] = None,
    heading_consistency_max_error_rad: float = math.radians(90.0),
    capture_match_snapshots: bool = False,
) -> Optional[object]:
    """P3: relocalize using Scan Context global-descriptor similarity to pick
    *which* anchor, then a narrow local ICP search only against that one
    anchor to refine the metric (dx, dy, dtheta).

    Rationale (see 2026-07-02 ep994 diagnosis): local_map_icp's per-candidate
    score (overlap ratio, residual) measures how well the current scan
    registers against ONE anchor in isolation; in open/large-feature areas a
    wrong anchor several meters away can register just as well as the correct
    one across a wide span of true positions ("sticky" false matches that
    self-reinforce through the SeqSLAM continuity check, which only compares
    against its own possibly-already-wrong history). Scan Context instead
    compares the *global* occupancy pattern against every candidate at once
    and only proceeds when the winner clearly beats the runner-up -- an
    ambiguous scene correctly returns no candidate (widening the particle
    filter) instead of committing to whichever candidate happened to edge out
    the others.

    ICP is still used for the final metric offset (Scan Context alone does not
    give a translation), but only as a narrow refinement seeded by Scan
    Context's own yaw estimate against the ONE selected anchor, not a blind
    24-seed search across every candidate.

    2026-07-02, second revision (closer to Kim & Kim 2018 + spatial
    consistency): two follow-up problems surfaced after the first fix batch,
    diagnosed by directly checking correct_anchor% (not just bearing error)
    across three validation batches -- it never rose above the pre-P3
    baseline (3.9-6.4%, vs. local_map_icp+P1+P2's 7.8-9.6%), meaning Scan
    Context's core anchor-*identity* mechanism itself hadn't demonstrated any
    improvement yet, independent of the orientation-flip issue below.
      1. Cell values were binary occupancy, not the original paper's
         max-height-per-cell -- descriptor_local_map_points_xyz now preserves
         height (previously dropped for the 2-D-only ICP path) and
         build_scan_context bins it properly, restoring real discriminative
         power the binary simplification had thrown away.
      2. Average column similarity alone rewards "diffuse" matches (many
         small scattered patches of agreement across a big open area) exactly
         as much as "concentrated" ones (one large coherent chunk of matching
         geometry) -- likely why loosening min_similarity_margin for coverage
         in the first fix directly hurt accuracy. largest_connected_agreement_
         region now finds the largest spatially-contiguous agreeing patch
         (circular on the sector axis); a real revisit should produce one
         large connected region, not scattered pixel-sized agreement. Ranking
         and the ambiguity-margin check now use combined_score = similarity *
         connected_region_fraction, not raw similarity alone.
    All three of min_similarity / min_connected_region_cells /
    min_combined_score_margin_ratio remain provisional -- no real
    similarity/region-size distributions have been inspected yet. Note the
    shift search itself now optimizes combined_score, not raw similarity, so
    the winning shift can (and, on a real synthetic check, does) report a
    *lower* raw similarity than the old pure-similarity search would have --
    it traded some similarity for a shift with actual spatial coherence.
    min_similarity was lowered from 0.3 to 0.2 accordingly; still a guess.

    ``dead_reckoning_yaw_rad``: separately, Scan Context's own column-shift
    search spans the full 360 degrees, so like local_map_icp's un-gated yaw
    search before the P1 fix, it is vulnerable to locking onto a
    180-degree-flipped orientation in corridor-like/symmetric geometry. NOTE
    (2026-07-02): this reference (route_agent.current_absolute_pose_from_
    start()) was found to drift by up to ~160 degrees during outbound in real
    data, undermining this gate independently of the two fixes above -- not
    yet re-addressed here (see the ongoing investigation into a
    local/relative consistency reference instead of this global accumulated
    one).
    """
    from route_memory_agent import AnchorRelocalization, compose_pose, inverse_delta, wrap_angle

    def _implied_absolute_yaw(anchor_pose_from_start, dx: float, dy: float, dtheta: float) -> float:
        # Same frame composition as local_map_anchor_relocalization's P1 gate:
        # (dx, dy, dtheta) is "anchor pose as seen from current", so inverting
        # it and composing onto the anchor's own absolute pose yields current's
        # absolute pose.
        source_pose_from_current = [float(dx), float(dy), float(dtheta)]
        current_pose_from_source = inverse_delta(source_pose_from_current)
        current_pose_from_start = compose_pose(anchor_pose_from_start, current_pose_from_source)
        return wrap_angle(current_pose_from_start[2])

    _diagnostic_inc(diagnostics, "attempts")
    _diagnostic_inc(diagnostics, "scan_context_attempts")
    if diagnostics is not None:
        diagnostics["matcher_backend"] = "scan_context"

    current_points_xyz = descriptor_local_map_points_xyz(current_descriptor)
    if current_points_xyz is None:
        _diagnostic_inc(diagnostics, "missing_current_local_map")
        return None
    if len(current_points_xyz) < 12:
        _diagnostic_inc(diagnostics, "too_few_current_local_map_points")
        return None
    current_sc = build_scan_context(current_points_xyz)
    num_rings, num_sectors = current_sc.shape
    grid_cells = float(num_rings * num_sectors)

    # Still needed for the ICP refinement step, which only ever registers in
    # 2-D -- not downsampled for the Scan Context grid above, since voxel
    # downsampling would pick an arbitrary point per voxel and could discard
    # exactly the tallest point max-height encoding is trying to keep.
    current_points = descriptor_local_map_points(current_descriptor)
    current_points = voxel_downsample_2d(current_points) if current_points is not None else None
    if current_points is None or len(current_points) < 12:
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

    scored: list[tuple[float, float, int, int, object, np.ndarray]] = []
    # each entry: (combined_score, raw_similarity, region_size, shift, anchor, anchor_points_2d_for_icp)
    for anchor in candidates_to_search:
        anchor_points_xyz = descriptor_local_map_points_xyz(anchor.descriptor)
        if anchor_points_xyz is None or len(anchor_points_xyz) < 12:
            _diagnostic_inc(diagnostics, "candidate_missing_local_map")
            continue
        anchor_points_2d = descriptor_local_map_points(anchor.descriptor)
        if anchor_points_2d is None:
            continue
        anchor_points_2d = voxel_downsample_2d(anchor_points_2d)
        if len(anchor_points_2d) < 12:
            _diagnostic_inc(diagnostics, "too_few_anchor_local_map_points")
            continue
        anchor_sc = build_scan_context(anchor_points_xyz)
        similarity, shift, region_size = column_shift_search_with_region(current_sc, anchor_sc)
        combined_score = float(similarity) * (region_size / grid_cells)
        scored.append((combined_score, similarity, region_size, shift, anchor, anchor_points_2d))

    if not scored:
        _diagnostic_inc(diagnostics, "no_scan_context_candidates")
        return None

    scored.sort(key=lambda item: item[0], reverse=True)
    best_combined, best_similarity, best_region_size, best_shift, best_anchor, best_anchor_points = scored[0]

    if diagnostics is not None:
        diagnostics["last_scan_context_best_similarity"] = float(best_similarity)
        diagnostics["last_scan_context_best_region_size"] = int(best_region_size)
        diagnostics["last_scan_context_runner_up_combined_score"] = (
            float(scored[1][0]) if len(scored) > 1 else None
        )

    if best_similarity < min_similarity:
        _diagnostic_inc(diagnostics, "scan_context_similarity_too_low")
        return None
    if best_region_size < min_connected_region_cells:
        # The winner's agreement is scattered across the grid rather than one
        # coherent chunk -- exactly the "diffuse match" failure mode from the
        # ep994 diagnosis. Correctly report no candidate rather than trusting
        # a high average similarity that isn't backed by real local structure.
        _diagnostic_inc(diagnostics, "scan_context_diffuse_match")
        return None
    if len(scored) > 1 and scored[1][0] > 0 and (best_combined / scored[1][0]) < min_combined_score_margin_ratio:
        # Ambiguous: winner doesn't clearly beat the runner-up on the
        # connectedness-aware score -- the "wide plausible basin" case from
        # the ep994 diagnosis. Correctly report no candidate rather than
        # guessing.
        _diagnostic_inc(diagnostics, "scan_context_ambiguous_margin")
        return None

    num_sectors = current_sc.shape[1]
    primary_seed = shift_to_yaw_rad(best_shift, num_sectors)

    # 2026-07-02, second fix: a narrow +/-20-degree search around Scan
    # Context's best shift and its exact diametric opposite was validated on a
    # clean synthetic 180-degree-symmetric shape but failed on the first real
    # batch (scan_context_p3_flipfix_187_680_994_20260702 still showed a
    # stable ~170-174 deg bearing error on "same anchor" steps). The sign
    # convention and P1-style consistency-check logic below are correct (both
    # re-derived and unit-tested against the synthetic case); the problem was
    # seed *coverage* -- real, noisier point clouds can put Scan Context's own
    # best_shift estimate more than 20 degrees from the true optimum in either
    # basin, so neither narrow window ever contained it, leaving the
    # consistency check to pick the least-bad of a bad set. Fall back to the
    # same full-360-degree, 24-seed sweep local_map_icp already uses (proven
    # robust there) against just this one Scan-Context-selected anchor --
    # still far cheaper than local_map_icp's original design, which ran this
    # same sweep against every candidate anchor instead of just one.
    refine_seeds = [math.radians(float(deg)) for deg in range(-180, 180, 15)]

    icp_results = []
    for yaw in refine_seeds:
        result = icp_rigid_transform_2d(
            best_anchor_points,
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
        icp_results.append((score, result))

    if not icp_results:
        # Scan Context is confident about *identity* but the narrow ICP
        # refinement couldn't lock a metric offset -- report the anchor with an
        # unreliable heading rather than nothing, matching the existing
        # low-confidence fallback pattern used elsewhere (e.g. LoFTR).
        _diagnostic_inc(diagnostics, "scan_context_icp_refine_failed")
        candidate = AnchorRelocalization(
            anchor_index=int(best_anchor.index),
            anchor_dx_m=0.0,
            anchor_dy_m=0.0,
            anchor_dtheta_rad=float(primary_seed),
            confidence=float(best_similarity),
            backend="scan_context_identity_only",
            inlier_count=None,
            reprojection_error_px=None,
            anchor_heading_reliable=False,
        )
        if return_candidates:
            return [candidate]
        return candidate

    icp_results.sort(key=lambda item: item[0], reverse=True)
    score = result = None
    rejected_flip_count = 0
    for candidate_score, candidate_result in icp_results:
        if dead_reckoning_yaw_rad is None:
            score, result = candidate_score, candidate_result
            break
        implied_yaw = _implied_absolute_yaw(
            best_anchor.pose_from_start,
            candidate_result["translation"][0],
            candidate_result["translation"][1],
            candidate_result["theta"],
        )
        error = abs(wrap_angle(implied_yaw - dead_reckoning_yaw_rad))
        if error > heading_consistency_max_error_rad:
            rejected_flip_count += 1
            continue
        score, result = candidate_score, candidate_result
        break
    if result is None:
        _diagnostic_inc(diagnostics, "scan_context_heading_consistency_rejected")
        return None
    if diagnostics is not None and rejected_flip_count:
        diagnostics["last_scan_context_rejected_flip_count"] = rejected_flip_count

    overlap = float(result["overlap_ratio"])
    residual = float(result["median_residual_m"])
    inlier_count = int(result["inlier_count"])
    icp_confidence = min(1.0, overlap * max(0.0, 1.0 - residual / 0.45) * 1.5)
    combined_confidence = float(min(1.0, 0.5 * best_similarity + 0.5 * icp_confidence))
    if inlier_count < 12 or overlap < 0.12 or combined_confidence < 0.15:
        _diagnostic_inc(diagnostics, "low_confidence_scan_context_pose")
        return None

    candidate = AnchorRelocalization(
        anchor_index=int(best_anchor.index),
        anchor_dx_m=float(result["translation"][0]),
        anchor_dy_m=float(result["translation"][1]),
        anchor_dtheta_rad=float(result["theta"]),
        confidence=combined_confidence,
        backend="scan_context",
        inlier_count=inlier_count,
        reprojection_error_px=None,
        anchor_heading_reliable=True,
    )
    _diagnostic_inc(diagnostics, "successful_estimates")
    if capture_match_snapshots:
        match_record = {
            "attempt": diagnostics.get("attempts") if diagnostics is not None else None,
            "anchor_index": int(best_anchor.index),
            "matcher_backend": "scan_context",
            "outcome": "pose_candidate",
            "scan_context_similarity": float(best_similarity),
            "scan_context_region_size": int(best_region_size),
            "inlier_count": inlier_count,
            "overlap_ratio": overlap,
            "median_residual_m": residual,
            "confidence": float(combined_confidence),
            "estimated_anchor_dx_m": float(result["translation"][0]),
            "estimated_anchor_dy_m": float(result["translation"][1]),
            "estimated_anchor_dtheta_deg": float(math.degrees(result["theta"])),
            "estimated_distance_to_anchor_m": float(candidate.distance_to_anchor_m),
            "estimated_bearing_to_anchor_deg": float(candidate.bearing_to_anchor_deg),
            "match_snapshot": build_local_map_match_snapshot(
                best_anchor_points, current_points, result["theta"], result["translation"]
            ),
        }
        _append_covisibility_record(diagnostics, match_record)
    if return_candidates:
        return [candidate]
    return candidate


def fused_anchor_relocalization(
    current_descriptor: object,
    anchors: list,
    max_candidates: Optional[int] = None,
    diagnostics: Optional[dict] = None,
    return_candidates: bool = False,
    dead_reckoning_yaw_rad: Optional[float] = None,
    rgbd_matcher_backend: str = "loftr",
    agreement_max_heading_disagreement_rad: float = math.radians(30.0),
    agreement_max_position_disagreement_m: float = 0.75,
    single_source_confidence_penalty: float = 0.8,
    capture_match_snapshots: bool = False,
) -> Optional[object]:
    """Cross-validate LoFTR (RGB-D) and Scan Context (LiDAR) relocalization
    against each other instead of trusting either in isolation.

    2026-07-02: every anchor's descriptor already carries RGB, depth, and
    LiDAR/local-map data together (route_memory_descriptor_from_infos in
    round_trip_eval.py packages all of them per anchor unconditionally) --
    the two backends have simply never looked at each other's answer before
    now. Literature grounding (see the RGB-D+LiDAR fusion research checked
    before implementing this): corridor-repetition geometric ambiguity is
    exactly where visual texture provides "crucial distinguishing
    information" that pure geometry lacks, and conversely LiDAR is immune to
    LoFTR's covisibility=0% failure when the camera faces the wrong way
    during return (LiDAR has no field-of-view restriction). The two
    backends' failure modes are largely disjoint, which is the precondition
    for cross-validation actually helping rather than just averaging two
    unreliable answers.

    Agreement policy:
      - Both backends silent -> no candidate.
      - Only one backend produces a candidate (e.g. LoFTR has zero
        covisibility this step but LiDAR, being omnidirectional, doesn't) ->
        use it, but at reduced (single_source_confidence_penalty) confidence,
        since it's uncorroborated.
      - Both produce a candidate for a *different* anchor, or the *same*
        anchor with a pose disagreement beyond the tolerances below -> treat
        as genuinely ambiguous and report no candidate, the same "don't guess
        when independent signals disagree" policy already used by Scan
        Context's own ambiguity-margin check and Design 2's large-jump
        confirmation gate.
      - Both agree (same anchor, pose within tolerance) -> confidence-weighted
        circular/linear fusion of the two independent estimates, confidence
        boosted since two independent modalities corroborate each other.

    Side benefit worth noting: LoFTR's own orientation estimate comes purely
    from the current pair of RGB-D frames, not from any accumulated
    dead-reckoning chain -- unlike dead_reckoning_yaw_rad (found 2026-07-02 to
    drift by up to ~160 degrees during outbound), so an agreeing LoFTR
    estimate is a meaningful independent cross-check on Scan Context's own
    orientation even though the underlying dead-reckoning-based heading gate
    inside scan_context_anchor_relocalization is not itself fixed by this.
    """
    from route_memory_agent import AnchorRelocalization, circular_weighted_mean, wrap_angle

    _diagnostic_inc(diagnostics, "attempts")
    _diagnostic_inc(diagnostics, "fused_attempts")
    if diagnostics is not None:
        diagnostics["matcher_backend"] = "fused"

    # Reuse the same nested dict across calls (via setdefault) rather than a
    # fresh {} each time: this function is called once per relocalization
    # interval for the whole episode, and a fresh dict every call meant only
    # the LAST call's per-anchor covisibility_records (and match_snapshot,
    # once capture_match_snapshots was added) ever survived into the saved
    # measurement JSON -- every earlier call's history was silently discarded
    # the instant the next call overwrote diagnostics["fused_rgbd_diagnostics"]
    # / ["fused_lidar_diagnostics"] wholesale. setdefault makes every call
    # accumulate into the same persistent sub-dict instead, so scalar counters
    # (e.g. "attempts") and covisibility_records/match_snapshot both cover the
    # full episode, not just its final relocalization attempt.
    rgbd_diag: Optional[dict] = diagnostics.setdefault("fused_rgbd_diagnostics", {}) if diagnostics is not None else None
    lidar_diag: Optional[dict] = diagnostics.setdefault("fused_lidar_diagnostics", {}) if diagnostics is not None else None

    rgbd_result = feature_depth_anchor_relocalization(
        current_descriptor,
        anchors,
        max_candidates=max_candidates,
        diagnostics=rgbd_diag,
        matcher_backend=rgbd_matcher_backend,
    )
    lidar_result = scan_context_anchor_relocalization(
        current_descriptor,
        anchors,
        max_candidates=max_candidates,
        diagnostics=lidar_diag,
        dead_reckoning_yaw_rad=dead_reckoning_yaw_rad,
        capture_match_snapshots=capture_match_snapshots,
    )

    def _single_source(result, label: str):
        _diagnostic_inc(diagnostics, f"fused_{label}_only")
        candidate = AnchorRelocalization(
            anchor_index=result.anchor_index,
            anchor_dx_m=result.anchor_dx_m,
            anchor_dy_m=result.anchor_dy_m,
            anchor_dtheta_rad=result.anchor_dtheta_rad,
            confidence=float(result.confidence) * single_source_confidence_penalty,
            backend=f"{result.backend}+fused_single",
            inlier_count=result.inlier_count,
            reprojection_error_px=result.reprojection_error_px,
            anchor_heading_reliable=result.anchor_heading_reliable,
        )
        if return_candidates:
            return [candidate]
        return candidate

    if rgbd_result is None and lidar_result is None:
        _diagnostic_inc(diagnostics, "fused_both_failed")
        return None
    if rgbd_result is None:
        return _single_source(lidar_result, "lidar")
    if lidar_result is None:
        return _single_source(rgbd_result, "rgbd")

    if rgbd_result.anchor_index != lidar_result.anchor_index:
        _diagnostic_inc(diagnostics, "fused_disagreement_different_anchor")
        return None

    heading_disagreement = abs(
        wrap_angle(rgbd_result.anchor_dtheta_rad - lidar_result.anchor_dtheta_rad)
    )
    position_disagreement = math.hypot(
        rgbd_result.anchor_dx_m - lidar_result.anchor_dx_m,
        rgbd_result.anchor_dy_m - lidar_result.anchor_dy_m,
    )
    if (
        heading_disagreement > agreement_max_heading_disagreement_rad
        or position_disagreement > agreement_max_position_disagreement_m
    ):
        _diagnostic_inc(diagnostics, "fused_disagreement_same_anchor_different_pose")
        return None

    rgbd_weight = max(1e-6, float(rgbd_result.confidence))
    lidar_weight = max(1e-6, float(lidar_result.confidence))
    fused_dx = (rgbd_result.anchor_dx_m * rgbd_weight + lidar_result.anchor_dx_m * lidar_weight) / (
        rgbd_weight + lidar_weight
    )
    fused_dy = (rgbd_result.anchor_dy_m * rgbd_weight + lidar_result.anchor_dy_m * lidar_weight) / (
        rgbd_weight + lidar_weight
    )
    fused_dtheta = circular_weighted_mean(
        [(rgbd_result.anchor_dtheta_rad, rgbd_weight), (lidar_result.anchor_dtheta_rad, lidar_weight)]
    )
    fused_confidence = min(1.0, 0.5 * (rgbd_weight + lidar_weight) + 0.15)

    candidate = AnchorRelocalization(
        anchor_index=rgbd_result.anchor_index,
        anchor_dx_m=float(fused_dx),
        anchor_dy_m=float(fused_dy),
        anchor_dtheta_rad=float(fused_dtheta) if fused_dtheta is not None else float(lidar_result.anchor_dtheta_rad),
        confidence=float(fused_confidence),
        backend="fused_loftr_scan_context",
        inlier_count=(rgbd_result.inlier_count or 0) + (lidar_result.inlier_count or 0),
        reprojection_error_px=rgbd_result.reprojection_error_px,
        anchor_heading_reliable=True,
    )
    _diagnostic_inc(diagnostics, "fused_agreement")
    if return_candidates:
        return [candidate]
    return candidate


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
