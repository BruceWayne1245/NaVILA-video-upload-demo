"""2-D Scan Context descriptor (Kim & Kim, IROS 2018) adapted for the local-map
point clouds already used by ``relocalization.py``'s ICP backend.

The original Scan Context bins a 3-D LiDAR scan into a polar grid (rings x
sectors) and stores the maximum point height per cell. Our local-map point
clouds are already height-filtered down to an obstacle band before we ever see
them (see ``descriptor_local_map_points`` in relocalization.py, which keeps
only points with ``z in [-0.20, 1.80]`` and drops the z coordinate entirely),
so there is no per-point height left to encode. This variant stores binary
occupancy per cell instead, which is the standard adaptation for 2-D/height-
filtered scans.

Kept in a separate module (depends only on numpy) so it can be unit-tested
without Isaac Sim, matching relocalization.py's own convention.
"""

from __future__ import annotations

import math
from typing import Optional

import numpy as np


def build_scan_context(
    points: np.ndarray,
    num_rings: int = 20,
    num_sectors: int = 60,
    max_radius_m: float = 6.0,
) -> np.ndarray:
    """Bin a body-frame 2-D point cloud into a polar occupancy grid.

    Row = radial ring (0 = closest to sensor origin), column = angular sector
    (0 = +x/forward axis, increasing counter-clockwise). Cell value is 1.0 if
    any point falls in that (ring, sector), else 0.0.
    """
    grid = np.zeros((num_rings, num_sectors), dtype=np.float32)
    points = np.asarray(points, dtype=np.float64)
    if points.ndim != 2 or points.shape[1] < 2 or points.shape[0] == 0:
        return grid
    xs = points[:, 0]
    ys = points[:, 1]
    r = np.hypot(xs, ys)
    theta = np.mod(np.arctan2(ys, xs), 2.0 * math.pi)
    valid = (r <= max_radius_m) & np.isfinite(r) & np.isfinite(theta)
    r = r[valid]
    theta = theta[valid]
    if len(r) == 0:
        return grid
    ring_idx = np.clip((r / max_radius_m * num_rings).astype(np.int32), 0, num_rings - 1)
    sector_idx = np.clip((theta / (2.0 * math.pi) * num_sectors).astype(np.int32), 0, num_sectors - 1)
    grid[ring_idx, sector_idx] = 1.0
    return grid


def _mean_column_cosine_similarity(sc_a: np.ndarray, sc_b: np.ndarray) -> float:
    """Average cosine similarity across columns present in both matrices.

    Columns that are all-zero in either matrix are skipped rather than scored
    as a match -- an empty-vs-empty column carries no information about
    whether the two scans actually agree there.
    """
    total = 0.0
    valid_columns = 0
    num_sectors = sc_a.shape[1]
    for j in range(num_sectors):
        col_a = sc_a[:, j]
        col_b = sc_b[:, j]
        norm_a = float(np.linalg.norm(col_a))
        norm_b = float(np.linalg.norm(col_b))
        if norm_a < 1e-9 or norm_b < 1e-9:
            continue
        total += float(np.dot(col_a, col_b) / (norm_a * norm_b))
        valid_columns += 1
    if valid_columns == 0:
        return 0.0
    return total / valid_columns


def column_shift_similarity(sc_a: np.ndarray, sc_b: np.ndarray) -> tuple[float, int]:
    """Compare two scan-context matrices via column-shift search.

    A yaw rotation of the sensor corresponds exactly to a circular shift of
    the sector (column) axis, so trying every shift and keeping the
    best-scoring one makes the comparison rotation-invariant and yields an
    implied relative yaw for free -- this is the core trick from Kim & Kim
    2018 and is what makes Scan Context robust to the current view not facing
    the same way the anchor was recorded.

    Returns (best_similarity, best_shift) where ``best_shift`` is in sector
    units. Rotating ``sc_b`` by ``best_shift`` sectors (``np.roll(sc_b,
    best_shift, axis=1)``) aligns it with ``sc_a``, i.e. the relative yaw
    needed to bring sc_b's frame into sc_a's frame is
    ``best_shift * (2*pi / num_sectors)``.
    """
    num_sectors = sc_a.shape[1]
    best_similarity = -1.0
    best_shift = 0
    for shift in range(num_sectors):
        shifted = np.roll(sc_b, shift, axis=1)
        similarity = _mean_column_cosine_similarity(sc_a, shifted)
        if similarity > best_similarity:
            best_similarity = similarity
            best_shift = shift
    return float(best_similarity), int(best_shift)


def shift_to_yaw_rad(shift: int, num_sectors: int) -> float:
    """Convert a column-shift (sector units) to a relative yaw in radians,
    wrapped to (-pi, pi]."""
    raw = shift * (2.0 * math.pi / num_sectors)
    return float(math.atan2(math.sin(raw), math.cos(raw)))
