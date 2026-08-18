"""Top-down occupancy map rendering for round-trip VLN episodes.

The map is generated from the loaded USD stage, not from an overhead camera.
Meshes intersecting a height band above the episode floor are projected into a
2-D occupancy grid, then outbound/return trajectories and route anchors can be
overlaid in world coordinates.
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from typing import Iterable, Optional

import cv2
import numpy as np


@dataclass
class TopDownMap:
    image: np.ndarray
    meta: dict


def _xy_bounds(points_xy: Iterable[Iterable[float]], padding_m: float) -> tuple[float, float, float, float]:
    pts = np.asarray(list(points_xy), dtype=np.float32)
    pts = pts[np.isfinite(pts).all(axis=1)]
    if pts.size == 0:
        raise ValueError("Cannot build top-down map without finite XY bounds.")
    min_x, min_y = np.min(pts[:, :2], axis=0)
    max_x, max_y = np.max(pts[:, :2], axis=0)
    if max_x - min_x < 1.0:
        min_x -= 0.5
        max_x += 0.5
    if max_y - min_y < 1.0:
        min_y -= 0.5
        max_y += 0.5
    return (
        float(min_x - padding_m),
        float(max_x + padding_m),
        float(min_y - padding_m),
        float(max_y + padding_m),
    )


def world_to_pixel(xy: Iterable[float], meta: dict) -> tuple[int, int]:
    x, y = float(xy[0]), float(xy[1])
    px = int(round((x - meta["min_x"]) / meta["resolution_m_per_px"]))
    py = int(round((meta["max_y"] - y) / meta["resolution_m_per_px"]))
    return px, py


def _triangle_is_floor(tri: np.ndarray, floor_z: float, normal_floor_threshold: float) -> bool:
    if tri.shape != (3, 3):
        return False
    normal = np.cross(tri[1] - tri[0], tri[2] - tri[0])
    norm = float(np.linalg.norm(normal))
    if norm < 1e-6:
        return False
    normal /= norm
    mean_z = float(np.mean(tri[:, 2]))
    return abs(float(normal[2])) >= normal_floor_threshold and abs(mean_z - floor_z) <= 0.25


def _mesh_world_triangles(stage, floor_z: float, z_min: float, z_max: float, normal_floor_threshold: float):
    from pxr import UsdGeom

    xform_cache = UsdGeom.XformCache()
    for prim in stage.Traverse():
        if not prim.IsA(UsdGeom.Mesh):
            continue
        mesh = UsdGeom.Mesh(prim)
        points_value = mesh.GetPointsAttr().Get()
        points = np.asarray(points_value if points_value is not None else [], dtype=np.float32)
        if points.size == 0:
            continue
        counts_value = mesh.GetFaceVertexCountsAttr().Get()
        indices_value = mesh.GetFaceVertexIndicesAttr().Get()
        counts = np.asarray(counts_value if counts_value is not None else [], dtype=np.int32)
        indices = np.asarray(indices_value if indices_value is not None else [], dtype=np.int32)
        if counts.size == 0 or indices.size == 0:
            continue

        transform = np.asarray(xform_cache.GetLocalToWorldTransform(prim), dtype=np.float64).T
        homog = np.concatenate([points.astype(np.float64), np.ones((points.shape[0], 1))], axis=1)
        world_points = (homog @ transform)[:, :3].astype(np.float32)

        cursor = 0
        for count in counts:
            face_indices = indices[cursor:cursor + int(count)]
            cursor += int(count)
            if face_indices.size < 3:
                continue
            # Fan-triangulate n-gons. This is sufficient for occupancy projection.
            for i in range(1, face_indices.size - 1):
                tri = world_points[[face_indices[0], face_indices[i], face_indices[i + 1]]]
                if float(np.max(tri[:, 2])) < z_min or float(np.min(tri[:, 2])) > z_max:
                    continue
                if _triangle_is_floor(tri, floor_z, normal_floor_threshold):
                    continue
                yield tri


def capture_occupancy_floor_slice(
    episode: dict,
    resolution_m_per_px: float = 0.05,
    padding_m: float = 3.0,
    z_min_above_floor_m: float = 0.08,
    z_max_above_floor_m: float = 2.2,
    obstacle_dilation_px: int = 2,
    max_size_px: int = 2400,
    normal_floor_threshold: float = 0.90,
) -> TopDownMap:
    """Build a 2-D occupancy map from the currently loaded USD stage."""
    try:
        import omni.usd
    except Exception as exc:  # pragma: no cover - only available inside Isaac.
        raise RuntimeError("omni.usd is required to build the occupancy map inside Isaac Sim.") from exc

    reference_path = episode.get("reference_path") or []
    start = episode.get("start_position")
    bounds_points = []
    if start is not None:
        bounds_points.append(start[:2])
    bounds_points.extend([p[:2] for p in reference_path])
    min_x, max_x, min_y, max_y = _xy_bounds(bounds_points, padding_m=padding_m)

    width = int(math.ceil((max_x - min_x) / resolution_m_per_px)) + 1
    height = int(math.ceil((max_y - min_y) / resolution_m_per_px)) + 1
    scale = 1.0
    if max(width, height) > max_size_px:
        scale = float(max(width, height)) / float(max_size_px)
        resolution_m_per_px *= scale
        width = int(math.ceil((max_x - min_x) / resolution_m_per_px)) + 1
        height = int(math.ceil((max_y - min_y) / resolution_m_per_px)) + 1

    image = np.full((height, width, 3), 245, dtype=np.uint8)
    floor_z = float(start[2] if start is not None and len(start) >= 3 else 0.0)
    z_min = floor_z + float(z_min_above_floor_m)
    z_max = floor_z + float(z_max_above_floor_m)
    meta = {
        "type": "usd_floor_slice_occupancy",
        "min_x": float(min_x),
        "max_x": float(max_x),
        "min_y": float(min_y),
        "max_y": float(max_y),
        "floor_z": floor_z,
        "z_min": z_min,
        "z_max": z_max,
        "resolution_m_per_px": float(resolution_m_per_px),
        "width_px": int(width),
        "height_px": int(height),
        "obstacle_dilation_px": int(obstacle_dilation_px),
    }

    stage = omni.usd.get_context().get_stage()
    obstacle_layer = np.zeros((height, width), dtype=np.uint8)
    triangle_count = 0
    rasterized_count = 0
    for tri in _mesh_world_triangles(stage, floor_z, z_min, z_max, normal_floor_threshold):
        triangle_count += 1
        tri_xy = tri[:, :2]
        if (
            float(np.max(tri_xy[:, 0])) < min_x or float(np.min(tri_xy[:, 0])) > max_x
            or float(np.max(tri_xy[:, 1])) < min_y or float(np.min(tri_xy[:, 1])) > max_y
        ):
            continue
        pts = np.asarray([world_to_pixel(xy, meta) for xy in tri_xy], dtype=np.int32)
        pts[:, 0] = np.clip(pts[:, 0], 0, width - 1)
        pts[:, 1] = np.clip(pts[:, 1], 0, height - 1)
        cv2.fillPoly(obstacle_layer, [pts], 255)
        rasterized_count += 1

    if obstacle_dilation_px > 0:
        kernel_size = 2 * int(obstacle_dilation_px) + 1
        kernel = np.ones((kernel_size, kernel_size), dtype=np.uint8)
        obstacle_layer = cv2.dilate(obstacle_layer, kernel, iterations=1)

    image[obstacle_layer > 0] = (55, 55, 55)
    meta["mesh_triangles_considered"] = int(triangle_count)
    meta["mesh_triangles_rasterized"] = int(rasterized_count)
    return TopDownMap(image=image, meta=meta)


def _polyline(image: np.ndarray, points_xy: list[list[float]], meta: dict, color: tuple[int, int, int], thickness: int) -> None:
    if len(points_xy) < 2:
        return
    pts = np.asarray([world_to_pixel(p, meta) for p in points_xy], dtype=np.int32)
    cv2.polylines(image, [pts], isClosed=False, color=color, thickness=thickness, lineType=cv2.LINE_AA)


def _dashed_polyline(
    image: np.ndarray,
    points_xy: list[list[float]],
    meta: dict,
    color: tuple[int, int, int],
    thickness: int = 1,
    dash_px: float = 7.0,
    gap_px: float = 5.0,
) -> None:
    if len(points_xy) < 2:
        return
    pts = [np.asarray(world_to_pixel(p, meta), dtype=np.float32) for p in points_xy]
    period = float(dash_px + gap_px)
    cursor = 0.0
    for start, end in zip(pts[:-1], pts[1:]):
        delta = end - start
        length = float(np.linalg.norm(delta))
        if length < 1e-6:
            continue
        direction = delta / length
        local = 0.0
        while local < length:
            phase = cursor % period
            if phase < dash_px:
                draw_len = min(dash_px - phase, length - local)
                p0 = start + direction * local
                p1 = start + direction * (local + draw_len)
                cv2.line(
                    image,
                    tuple(np.round(p0).astype(int)),
                    tuple(np.round(p1).astype(int)),
                    color,
                    thickness,
                    cv2.LINE_AA,
                )
            else:
                draw_len = min(period - phase, length - local)
            local += draw_len
            cursor += draw_len


def _draw_return_timestamps(
    image: np.ndarray,
    return_records: list[dict],
    meta: dict,
    color: tuple[int, int, int],
    max_labels: int = 10,
) -> None:
    if len(return_records) < 2 or max_labels <= 0:
        return
    first_step = int(return_records[0].get("step", 0))
    pixel_points: list[tuple[int, int]] = []
    valid_records: list[dict] = []
    for record in return_records:
        pos = record.get("position")
        if pos is None:
            continue
        px, py = world_to_pixel(pos[:2], meta)
        if 0 <= px < image.shape[1] and 0 <= py < image.shape[0]:
            pixel_points.append((px, py))
            valid_records.append(record)
    if len(pixel_points) < 2:
        return
    cumulative = [0.0]
    for a, b in zip(pixel_points[:-1], pixel_points[1:]):
        cumulative.append(cumulative[-1] + float(math.hypot(b[0] - a[0], b[1] - a[1])))
    total_distance = cumulative[-1]
    if total_distance < 1.0:
        return
    sample_count = min(max_labels, max(1, int(total_distance // 12)))
    targets = np.linspace(
        total_distance / float(sample_count + 1),
        total_distance * sample_count / float(sample_count + 1),
        sample_count,
        dtype=np.float32,
    )
    sample_indices = [int(np.searchsorted(cumulative, float(target))) for target in targets]
    for label_idx, record_idx in enumerate(sample_indices):
        px, py = pixel_points[min(int(record_idx), len(pixel_points) - 1)]
        label = str(label_idx + 1)
        radius = 4
        cv2.circle(image, (px, py), radius + 2, (255, 255, 255), -1, lineType=cv2.LINE_AA)
        cv2.circle(image, (px, py), radius + 2, (20, 20, 20), 1, lineType=cv2.LINE_AA)
        cv2.circle(image, (px, py), radius, color, -1, lineType=cv2.LINE_AA)
        cv2.putText(
            image,
            label,
            (px - 3 if len(label) == 1 else px - 6, py + 4),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.30,
            (255, 255, 255),
            1,
            cv2.LINE_AA,
        )


def _draw_marker(
    image: np.ndarray,
    xy: Iterable[float],
    meta: dict,
    color: tuple[int, int, int],
    label: Optional[str] = None,
    radius: int = 5,
) -> None:
    px, py = world_to_pixel(xy, meta)
    if px < 0 or py < 0 or px >= image.shape[1] or py >= image.shape[0]:
        return
    cv2.circle(image, (px, py), radius, color, -1, lineType=cv2.LINE_AA)
    cv2.circle(image, (px, py), radius + 1, (20, 20, 20), 1, lineType=cv2.LINE_AA)
    if label:
        cv2.putText(
            image,
            label,
            (px + radius + 3, py - radius - 3),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.38,
            (20, 20, 20),
            2,
            cv2.LINE_AA,
        )
        cv2.putText(
            image,
            label,
            (px + radius + 3, py - radius - 3),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.38,
            color,
            1,
            cv2.LINE_AA,
        )


def _anchor_world_xy(anchor: dict) -> Optional[list[float]]:
    metadata = anchor.get("metadata") or {}
    pose = metadata.get("world_pose")
    if pose is not None and len(pose) >= 2:
        return [float(pose[0]), float(pose[1])]
    return None


def render_route_overlay(
    topdown_map: TopDownMap,
    trajectory_records: list[dict],
    route_memory_summary: Optional[dict],
    episode: dict,
) -> np.ndarray:
    image = topdown_map.image.copy()
    meta = topdown_map.meta

    reference_path = [[float(p[0]), float(p[1])] for p in episode.get("reference_path", [])]
    _polyline(image, reference_path, meta, (170, 170, 170), 1)

    outbound = [
        [float(r["position"][0]), float(r["position"][1])]
        for r in trajectory_records
        if r.get("phase") == "outbound" and r.get("position") is not None
    ]
    return_records = [
        r for r in trajectory_records
        if r.get("phase") == "return" and r.get("position") is not None
    ]
    ret = [
        [float(r["position"][0]), float(r["position"][1])]
        for r in return_records
    ]
    _dashed_polyline(image, outbound, meta, (230, 105, 35), thickness=1, dash_px=8.0, gap_px=5.0)
    _dashed_polyline(image, ret, meta, (35, 75, 230), thickness=1, dash_px=8.0, gap_px=5.0)
    _draw_return_timestamps(image, return_records, meta, (200, 40, 200))

    anchors = (route_memory_summary or {}).get("anchors") or []
    for anchor in anchors:
        xy = _anchor_world_xy(anchor)
        if xy is None:
            continue
        _draw_marker(image, xy, meta, (0, 220, 255), f"A{int(anchor.get('index', 0))}", radius=4)

    start = episode.get("start_position")
    goal = (episode.get("reference_path") or [None])[-1]
    if start is not None:
        _draw_marker(image, start[:2], meta, (60, 180, 75), "start", radius=7)
    if goal is not None:
        _draw_marker(image, goal[:2], meta, (180, 70, 180), "goal", radius=7)
    if trajectory_records:
        final_pos = trajectory_records[-1].get("position")
        if final_pos is not None:
            _draw_marker(image, final_pos[:2], meta, (35, 35, 230), "final", radius=6)

    legend_x, legend_y = 12, 20
    legend = [
        ((55, 55, 55), "occupied"),
        ((230, 105, 35), "outbound"),
        ((35, 75, 230), "return"),
        ((200, 40, 200), "return order"),
        ((0, 220, 255), "anchor"),
    ]
    for idx, (color, label) in enumerate(legend):
        y = legend_y + idx * 20
        cv2.line(image, (legend_x, y), (legend_x + 24, y), color, 4, cv2.LINE_AA)
        cv2.putText(image, label, (legend_x + 32, y + 5), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (20, 20, 20), 1, cv2.LINE_AA)
    return image


def save_topdown_route_map(
    result_dir: str,
    episode_output_id: int,
    topdown_map: TopDownMap,
    trajectory_records: list[dict],
    route_memory_summary: Optional[dict],
    episode: dict,
) -> dict:
    map_dir = os.path.join(result_dir, "route_maps")
    os.makedirs(map_dir, exist_ok=True)
    base = f"output_{int(episode_output_id)}"
    occupancy_relpath = os.path.join("route_maps", f"{base}_occupancy.png")
    overlay_relpath = os.path.join("route_maps", f"{base}_routes.png")
    meta_relpath = os.path.join("route_maps", f"{base}_map_meta.json")

    overlay = render_route_overlay(topdown_map, trajectory_records, route_memory_summary, episode)
    cv2.imwrite(os.path.join(result_dir, occupancy_relpath), topdown_map.image)
    cv2.imwrite(os.path.join(result_dir, overlay_relpath), overlay)
    with open(os.path.join(result_dir, meta_relpath), "w", encoding="utf-8") as f:
        json.dump(topdown_map.meta, f, indent=2, sort_keys=True)
    return {
        "enabled": True,
        "occupancy_map_file": occupancy_relpath,
        "route_overlay_file": overlay_relpath,
        "map_meta_file": meta_relpath,
        "meta": dict(topdown_map.meta),
    }
