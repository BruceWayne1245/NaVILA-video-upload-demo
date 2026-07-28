"""2-D Scan Context descriptor (Kim & Kim, IROS 2018) adapted for the local-map
point clouds already used by ``relocalization.py``'s ICP backend.

2026-07-02: switched to the original paper's max-height-per-cell encoding.
Local-map point clouds were previously read via ``descriptor_local_map_points``
(relocalization.py), which drops the z coordinate entirely, leaving nothing to
encode but binary occupancy -- a real simplification versus the paper. Callers
should now build the descriptor from ``descriptor_local_map_points_xyz``
instead, which retains height. ``build_scan_context`` still degrades
gracefully to a flat (uninformative) height channel for any 2-D-only input,
so it remains usable standalone/in tests without requiring height data.

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
    height_min_m: float = -0.20,
    height_max_m: float = 1.80,
) -> np.ndarray:
    """Bin a body-frame point cloud into a polar grid, storing the *maximum*
    point height per (ring, sector) cell -- the original Kim & Kim (2018)
    encoding, restored 2026-07-02 (this project initially used binary
    occupancy per cell because the point clouds it had access to had already
    been stripped of height; see module docstring).

    Row = radial ring (0 = closest to sensor origin), column = angular sector
    (0 = +x/forward axis, increasing counter-clockwise). Height values are
    normalized to [0, 1] over [height_min_m, height_max_m] (the same obstacle
    band descriptor_local_map_points_xyz already filters to in
    relocalization.py), matching that existing convention rather than
    introducing a second one.

    If ``points`` has only 2 columns (no height available), every present
    cell gets value 1.0 -- the old binary-occupancy behavior -- so this
    function still degrades gracefully rather than requiring height data.
    """
    grid = np.zeros((num_rings, num_sectors), dtype=np.float32)
    points = np.asarray(points, dtype=np.float64)
    if points.ndim != 2 or points.shape[1] < 2 or points.shape[0] == 0:
        return grid
    xs = points[:, 0]
    ys = points[:, 1]
    if points.shape[1] >= 3:
        height_span = max(1e-6, float(height_max_m) - float(height_min_m))
        cell_values = np.clip((points[:, 2] - float(height_min_m)) / height_span, 0.0, 1.0)
    else:
        cell_values = np.ones_like(xs)
    r = np.hypot(xs, ys)
    theta = np.mod(np.arctan2(ys, xs), 2.0 * math.pi)
    valid = (r <= max_radius_m) & np.isfinite(r) & np.isfinite(theta) & np.isfinite(cell_values)
    r = r[valid]
    theta = theta[valid]
    cell_values = cell_values[valid]
    if len(r) == 0:
        return grid
    ring_idx = np.clip((r / max_radius_m * num_rings).astype(np.int32), 0, num_rings - 1)
    sector_idx = np.clip((theta / (2.0 * math.pi) * num_sectors).astype(np.int32), 0, num_sectors - 1)
    # Scatter-max reduction: np.maximum.at handles repeated (ring, sector)
    # indices correctly (keeps the tallest point per cell), unlike a plain
    # fancy-index assignment which would just keep whichever point happened
    # to be written last.
    np.maximum.at(grid, (ring_idx, sector_idx), cell_values.astype(np.float32))
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


def _largest_connected_region_in_mask(agree: np.ndarray) -> tuple[int, np.ndarray]:
    """Size and boolean mask of the largest 4-connected True region in a
    boolean grid, with the column (sector) axis treated as circular. Shared
    core of largest_connected_agreement_region, column_shift_search_with_region,
    and largest_connected_agreement_mask (the mask is returned alongside the
    size so the mask-returning public function doesn't need a second,
    separately-maintained flood fill)."""
    agree_grid = np.asarray(agree, dtype=np.bool_)
    if agree_grid.ndim != 2:
        raise ValueError(
            "connected-region agreement mask must be two-dimensional, "
            f"got shape={agree_grid.shape!r}"
        )
    num_rings, num_sectors = agree_grid.shape
    # This routine previously used a NumPy ``zeros_like`` visited mask.  Live
    # runs (ep187, ep368 and ep420) intermittently reached this flood fill with
    # ``visited`` behaving as an integer and crashed at ``visited[r0, c0]``.
    # The grid is tiny, so a Python set is both cheap and removes that mutable
    # NumPy scratch-array failure mode from the evaluator's hot path.
    visited: set[tuple[int, int]] = set()
    best_size = 0
    best_cells: list[tuple[int, int]] = []
    for r0 in range(num_rings):
        for c0 in range(num_sectors):
            if not bool(agree_grid[r0, c0]) or (r0, c0) in visited:
                continue
            stack = [(r0, c0)]
            visited.add((r0, c0))
            cells = [(r0, c0)]
            while stack:
                r, c = stack.pop()
                for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nr = r + dr
                    nc = (c + dc) % num_sectors  # circular sector axis
                    if nr < 0 or nr >= num_rings:
                        continue
                    if (
                        bool(agree_grid[nr, nc])
                        and (nr, nc) not in visited
                    ):
                        visited.add((nr, nc))
                        stack.append((nr, nc))
                        cells.append((nr, nc))
            if len(cells) > best_size:
                best_size = len(cells)
                best_cells = cells
    best_mask = np.zeros(
        (num_rings, num_sectors),
        dtype=np.bool_,
    )
    for r, c in best_cells:
        best_mask[r, c] = True
    return int(best_size), best_mask


def largest_connected_agreement_region(
    sc_a: np.ndarray,
    sc_b: np.ndarray,
    shift: int,
    height_tolerance: float = 0.15,
    presence_threshold: float = 0.05,
) -> int:
    """Size (cell count) of the largest spatially-contiguous region where
    ``sc_a`` and ``sc_b`` (rotated by ``shift`` sectors) agree.

    2026-07-02, motivated directly by the ep994 diagnosis: a big open area
    (or any other large, generic feature) can make the *average* column
    similarity look decent across a wide span of true positions -- lots of
    small, scattered cells each agree a little, but no single coherent chunk
    of geometry actually lines up. A genuine revisit of the same physical
    place instead produces one large, spatially *connected* patch of
    agreement. This distinguishes "concentrated" from "diffuse" matches (see
    ROVER, arXiv 2508.13488) the same way point-cloud registration literature
    uses maximum-clique spatial-consistency filtering (PointDSC, CVPR 2021)
    to reject correspondences that don't form one coherent group.

    Two cells "agree" if both are present (value above ``presence_threshold``,
    i.e. not empty space) and their heights differ by no more than
    ``height_tolerance``. Connectivity is 4-neighbor, with the sector
    (column) axis treated as circular -- sector ``num_sectors - 1`` is
    adjacent to sector ``0``, matching the polar grid's actual topology
    (an ordinary flood fill would incorrectly treat the two edges of the
    grid as unconnected).
    """
    shifted_b = np.roll(sc_b, shift, axis=1)
    agree = (
        (sc_a > presence_threshold)
        & (shifted_b > presence_threshold)
        & (np.abs(sc_a - shifted_b) <= height_tolerance)
    )
    size, _mask = _largest_connected_region_in_mask(agree)
    return size


def largest_connected_agreement_mask(
    sc_a: np.ndarray,
    sc_b: np.ndarray,
    shift: int,
    height_tolerance: float = 0.15,
    presence_threshold: float = 0.05,
) -> np.ndarray:
    """Boolean (num_rings, num_sectors) mask of the largest spatially-contiguous
    agreeing region -- same agreement/connectivity definition as
    largest_connected_agreement_region, but returns the mask itself instead of
    just its size, for visualizing *which* cells the match considers matched
    (added 2026-07-04 for plot_route_memory_diagnostic_frames.py's Scan
    Context match plot)."""
    shifted_b = np.roll(sc_b, shift, axis=1)
    agree = (
        (sc_a > presence_threshold)
        & (shifted_b > presence_threshold)
        & (np.abs(sc_a - shifted_b) <= height_tolerance)
    )
    _size, mask = _largest_connected_region_in_mask(agree)
    return mask


def column_shift_search_with_region(
    sc_a: np.ndarray,
    sc_b: np.ndarray,
    height_tolerance: float = 0.15,
    presence_threshold: float = 0.05,
) -> tuple[float, int, int]:
    """Like column_shift_similarity, but picks the shift that maximizes a
    connectivity-aware score instead of raw average column similarity alone.

    2026-07-02: average column similarity has a real blind spot for sparse
    point clouds -- a column with only one occupied ring has cosine
    similarity exactly 1.0 against any other single-occupied-ring column
    *regardless of which ring or what height value*, since cosine similarity
    is direction-only and a single-nonzero-entry vector's "direction" is
    fully determined by which index is nonzero, not its value. This produces
    near-ties across many shifts for sparse scans, and picking the shift by
    raw similarity alone can land on one with terrible (even zero) actual
    spatial connectivity -- defeating the point of adding
    largest_connected_agreement_region if it's only ever checked *after* an
    already-committed similarity-best shift that was never a good candidate
    to begin with. Denser real point clouds are less prone to this exact
    degeneracy, but there's no reason to leave it as a latent trap: search
    for the best shift using both signals jointly instead of sequentially.

    Returns (similarity, shift, region_size) for the shift maximizing
    similarity * (region_size / grid_cells).
    """
    num_rings, num_sectors = sc_a.shape
    grid_cells = float(num_rings * num_sectors)
    best_combined = -1.0
    best_similarity = 0.0
    best_shift = 0
    best_region = 0
    for shift in range(num_sectors):
        shifted = np.roll(sc_b, shift, axis=1)
        similarity = _mean_column_cosine_similarity(sc_a, shifted)
        agree = (
            (sc_a > presence_threshold)
            & (shifted > presence_threshold)
            & (np.abs(sc_a - shifted) <= height_tolerance)
        )
        region, _mask = _largest_connected_region_in_mask(agree)
        combined = similarity * (region / grid_cells)
        if combined > best_combined:
            best_combined = combined
            best_similarity = similarity
            best_shift = shift
            best_region = region
    return float(best_similarity), int(best_shift), int(best_region)


def shift_to_yaw_rad(shift: int, num_sectors: int) -> float:
    """Convert a column-shift (sector units) to a relative yaw in radians,
    wrapped to (-pi, pi]."""
    raw = shift * (2.0 * math.pi / num_sectors)
    return float(math.atan2(math.sin(raw), math.cos(raw)))
