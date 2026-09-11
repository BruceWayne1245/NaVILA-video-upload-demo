"""Local traversability checks for route-memory action arbitration.

Descriptors are intentionally simple so they can be backed by a real LiDAR,
Isaac RayCaster hits, or a precomputed local occupancy grid:

``local_map_points_body`` / ``lidar_points_body``
    Nx2 or Nx3 points in robot body coordinates.

``local_occupancy_grid``
    2-D boolean/int grid with ``local_occupancy_meta`` containing
    ``min_x``, ``min_y``, and ``resolution_m_per_px`` in body coordinates.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import math
import numpy as np


@dataclass
class LocalMapClearPathResult:
    available: bool
    clear: Optional[bool]
    min_clearance_m: Optional[float]
    reason: str


@dataclass
class LocalMapClearPathConfig:
    max_distance_m: float = 1.0
    robot_radius_m: float = 0.30
    clearance_margin_m: float = 0.12
    sample_step_m: float = 0.05
    min_obstacle_height_m: float = -0.10
    max_obstacle_height_m: float = 1.50


def _descriptor_points_body(descriptor: object) -> Optional[np.ndarray]:
    if not isinstance(descriptor, dict):
        return None
    for key in ("local_map_points_body", "lidar_points_body", "scan_points_body", "height_scan_points_body"):
        points = descriptor.get(key)
        if isinstance(points, np.ndarray):
            arr = np.asarray(points, dtype=np.float32)
            if arr.ndim == 2 and arr.shape[1] >= 2 and arr.shape[0] > 0:
                return arr
    return None


def _point_cloud_clear_path(
    points_body: np.ndarray,
    target_dx_m: float,
    target_dy_m: float,
    cfg: LocalMapClearPathConfig,
) -> LocalMapClearPathResult:
    target_len = float(math.hypot(target_dx_m, target_dy_m))
    if target_len <= 1e-6:
        return LocalMapClearPathResult(True, True, None, "zero_length_target")
    check_len = min(target_len, float(cfg.max_distance_m))
    direction = np.asarray([target_dx_m / target_len, target_dy_m / target_len], dtype=np.float32)
    points = np.asarray(points_body, dtype=np.float32)
    xy = points[:, :2]
    if points.shape[1] >= 3:
        z = points[:, 2]
        height_ok = (z >= cfg.min_obstacle_height_m) & (z <= cfg.max_obstacle_height_m)
        xy = xy[height_ok]
    if len(xy) == 0:
        return LocalMapClearPathResult(True, True, None, "no_obstacle_points")

    along = xy @ direction
    lateral_vec = xy - along[:, None] * direction[None, :]
    lateral = np.linalg.norm(lateral_vec, axis=1)
    corridor_radius = float(cfg.robot_radius_m + cfg.clearance_margin_m)
    in_front = (along >= 0.0) & (along <= check_len)
    if not np.any(in_front):
        return LocalMapClearPathResult(True, True, None, "clear")
    min_clearance = float(np.min(lateral[in_front]))
    if min_clearance < corridor_radius:
        return LocalMapClearPathResult(True, False, min_clearance, "occupied_in_local_map_path")
    return LocalMapClearPathResult(True, True, min_clearance, "clear")


def _occupancy_grid_clear_path(
    descriptor: dict,
    target_dx_m: float,
    target_dy_m: float,
    cfg: LocalMapClearPathConfig,
) -> Optional[LocalMapClearPathResult]:
    grid = descriptor.get("local_occupancy_grid")
    meta = descriptor.get("local_occupancy_meta")
    if not isinstance(grid, np.ndarray) or not isinstance(meta, dict):
        return None
    occ = np.asarray(grid)
    if occ.ndim != 2 or occ.size == 0:
        return LocalMapClearPathResult(False, None, None, "invalid_local_occupancy_grid")
    target_len = float(math.hypot(target_dx_m, target_dy_m))
    if target_len <= 1e-6:
        return LocalMapClearPathResult(True, True, None, "zero_length_target")
    resolution = float(meta.get("resolution_m_per_px", meta.get("resolution", 0.05)))
    min_x = float(meta.get("min_x", -occ.shape[1] * resolution / 2.0))
    min_y = float(meta.get("min_y", -occ.shape[0] * resolution / 2.0))
    check_len = min(target_len, float(cfg.max_distance_m))
    radius_px = max(1, int(math.ceil((cfg.robot_radius_m + cfg.clearance_margin_m) / max(resolution, 1e-6))))
    samples = max(2, int(math.ceil(check_len / max(cfg.sample_step_m, 1e-3))) + 1)
    direction = np.asarray([target_dx_m / target_len, target_dy_m / target_len], dtype=np.float32)
    occupied = occ.astype(bool)
    min_clearance_px = None
    for t in np.linspace(0.0, check_len, samples, dtype=np.float32):
        x, y = direction * float(t)
        px = int(round((float(x) - min_x) / resolution))
        py = int(round((float(y) - min_y) / resolution))
        if px < 0 or py < 0 or px >= occupied.shape[1] or py >= occupied.shape[0]:
            return LocalMapClearPathResult(True, False, 0.0, "path_leaves_local_map")
        x0 = max(0, px - radius_px)
        x1 = min(occupied.shape[1], px + radius_px + 1)
        y0 = max(0, py - radius_px)
        y1 = min(occupied.shape[0], py + radius_px + 1)
        local = occupied[y0:y1, x0:x1]
        if np.any(local):
            yy, xx = np.nonzero(local)
            clear_px = float(np.min(np.hypot(xx + x0 - px, yy + y0 - py)))
        else:
            clear_px = float(radius_px)
        min_clearance_px = clear_px if min_clearance_px is None else min(min_clearance_px, clear_px)
        if clear_px < radius_px:
            return LocalMapClearPathResult(
                True, False, clear_px * resolution, "occupied_in_local_map_path"
            )
    return LocalMapClearPathResult(True, True, (min_clearance_px or 0.0) * resolution, "clear")


def local_map_clear_path(
    descriptor: object,
    target_dx_m: float,
    target_dy_m: float,
    cfg: LocalMapClearPathConfig,
) -> LocalMapClearPathResult:
    if not isinstance(descriptor, dict):
        return LocalMapClearPathResult(False, None, None, "no_local_map")
    grid_result = _occupancy_grid_clear_path(descriptor, target_dx_m, target_dy_m, cfg)
    if grid_result is not None:
        return grid_result
    points = _descriptor_points_body(descriptor)
    if points is None:
        return LocalMapClearPathResult(False, None, None, "no_local_map")
    return _point_cloud_clear_path(points, target_dx_m, target_dy_m, cfg)
