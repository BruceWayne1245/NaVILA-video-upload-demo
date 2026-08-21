"""Pre-renders one top-down occupancy map per episode used in the
supplementary video, for the mini-map inset added in the 2026-08-21 v2
follow-up. Reuses the exact USD-mesh occupancy extraction from
final_data2/code/plot_figure2_hint_trajectory_effect_20260818.py (same
scene_world_triangles / triangle_is_floor / build_occupancy logic) rather
than re-deriving it.

For a paired episode (shown as two configs side by side, e.g. ep1256
hint vs hint-action) the crop bounds are the UNION of both configs' full
trajectories, so both sides of a pair render on an identical map (same
scale/crop) for a fair visual comparison. Single-clip episodes use just
their own trajectory.

Needs `pxr` (USD) + cv2 + numpy -- not available in the vlnce-isaac conda
env used for the rest of the render pipeline, but is in the system
miniconda `base` env (confirmed 2026-08-21). Run with:
  /home/teambruce/miniconda3/bin/python build_topdown_maps.py

Output: video/topdown_maps/ep<N>_occupancy.png + ep<N>_meta.json
(gitignored, regenerate from this script -- not committed, matching the
_raw/ and figures_raster/ convention).
"""
import glob
import json
import math
import os

import cv2
import numpy as np
from pxr import Usd, UsdGeom

BENCH = "/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench"
USD_ROOT = os.path.join(BENCH, "isaaclab_exts/omni.isaac.vlnce/assets/matterport_usd")
REPO = "/mnt/SSD4T/teambruce/projects/NaVILA-video-upload-demo/investigations/数据补全/video"
OUT_DIR = os.path.join(REPO, "topdown_maps")
os.makedirs(OUT_DIR, exist_ok=True)

RESOLUTION_M_PER_PX = 0.05
Z_MIN_ABOVE_FLOOR_M = 0.08
Z_MAX_ABOVE_FLOOR_M = 2.2
OBSTACLE_DILATION_PX = 2
MAX_SIZE_PX = 900  # smaller than the paper figure's 2400 -- this is a tiny video inset
NORMAL_FLOOR_THRESHOLD = 0.90
CROP_MARGIN_M = 1.0

# episode_key -> (scene_id, [result_dir names whose trajectories/*.jsonl to union])
EPISODES = {
    "ep1256": ("2azQ1b91cZZ", [
        "round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_pure_oracle_hint_highsuccess100ep_20260811_ep733",
        "round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_pure_oracle_hint_action_highsuccess100ep_20260812_ep733",
    ]),
    "ep33": ("x8F5xyUWy9e", [
        "round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_pure_oracle_hint_action_highsuccess100ep_20260812_ep20",
        "round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_pure_oracle_hint_action_stopgate_highsuccess100ep_20260813_ep20",
    ]),
    "ep1006": ("2azQ1b91cZZ", [
        "round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_pure_baseline_highsuccess100ep_chronological_first50_20260818_ep579",
        "round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_policy_v2_active50_replay_on_highsuccess100ep_20260816_ep579",
    ]),
    "ep428": ("QUCTc6BB5sX", [
        "round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_policy_v2_active50_replay_on_highsuccess100ep_20260816_ep271",
    ]),
    "ep1439": ("zsNo4HB9uLZ", [
        "round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_policy_v2_active50_replay_on_highsuccess100ep_20260816_ep844",
    ]),
}


def find_traj_file(result_dir):
    matches = glob.glob(os.path.join(BENCH, "eval_results", result_dir, "trajectories", "*.jsonl"))
    if not matches:
        raise FileNotFoundError(result_dir)
    return matches[0]


def load_all_positions(traj_file):
    xs, ys, zs = [], [], []
    with open(traj_file) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            x, y, z = rec["position"]
            xs.append(x)
            ys.append(y)
            zs.append(z)
    return xs, ys, zs


def scene_world_triangles(usd_path):
    stage = Usd.Stage.Open(usd_path)
    xform_cache = UsdGeom.XformCache()
    triangles = []
    for prim in stage.Traverse():
        if not prim.IsA(UsdGeom.Mesh):
            continue
        mesh = UsdGeom.Mesh(prim)
        points_value = mesh.GetPointsAttr().Get()
        points = np.asarray(points_value if points_value is not None else [], dtype=np.float32)
        if points.size == 0:
            continue
        counts = np.asarray(mesh.GetFaceVertexCountsAttr().Get() or [], dtype=np.int32)
        indices = np.asarray(mesh.GetFaceVertexIndicesAttr().Get() or [], dtype=np.int32)
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
            for i in range(1, face_indices.size - 1):
                tri = world_points[[face_indices[0], face_indices[i], face_indices[i + 1]]]
                triangles.append(tri)
    return triangles


def triangle_is_floor(tri, floor_z, normal_floor_threshold):
    normal = np.cross(tri[1] - tri[0], tri[2] - tri[0])
    norm = float(np.linalg.norm(normal))
    if norm < 1e-6:
        return False
    normal = normal / norm
    mean_z = float(np.mean(tri[:, 2]))
    return abs(float(normal[2])) >= normal_floor_threshold and abs(mean_z - floor_z) <= 0.25


def world_to_pixel(x, y, meta):
    px = int(round((x - meta["min_x"]) / meta["resolution_m_per_px"]))
    py = int(round((meta["max_y"] - y) / meta["resolution_m_per_px"]))
    return px, py


def build_occupancy(scene_triangles, floor_z, min_x, max_x, min_y, max_y):
    resolution = RESOLUTION_M_PER_PX
    width = int(math.ceil((max_x - min_x) / resolution)) + 1
    height = int(math.ceil((max_y - min_y) / resolution)) + 1
    if max(width, height) > MAX_SIZE_PX:
        scale = float(max(width, height)) / float(MAX_SIZE_PX)
        resolution *= scale
        width = int(math.ceil((max_x - min_x) / resolution)) + 1
        height = int(math.ceil((max_y - min_y) / resolution)) + 1

    meta = {"min_x": min_x, "max_x": max_x, "min_y": min_y, "max_y": max_y,
            "resolution_m_per_px": resolution, "width_px": width, "height_px": height}
    z_min = floor_z + Z_MIN_ABOVE_FLOOR_M
    z_max = floor_z + Z_MAX_ABOVE_FLOOR_M

    image = np.full((height, width, 3), 245, dtype=np.uint8)
    obstacle_layer = np.zeros((height, width), dtype=np.uint8)
    for tri in scene_triangles:
        if float(np.max(tri[:, 2])) < z_min or float(np.min(tri[:, 2])) > z_max:
            continue
        tri_xy = tri[:, :2]
        if (
            float(np.max(tri_xy[:, 0])) < min_x or float(np.min(tri_xy[:, 0])) > max_x
            or float(np.max(tri_xy[:, 1])) < min_y or float(np.min(tri_xy[:, 1])) > max_y
        ):
            continue
        if triangle_is_floor(tri, floor_z, NORMAL_FLOOR_THRESHOLD):
            continue
        pts = np.asarray([world_to_pixel(x, y, meta) for x, y in tri_xy], dtype=np.int32)
        pts[:, 0] = np.clip(pts[:, 0], 0, width - 1)
        pts[:, 1] = np.clip(pts[:, 1], 0, height - 1)
        cv2.fillPoly(obstacle_layer, [pts], 255)

    if OBSTACLE_DILATION_PX > 0:
        k = 2 * OBSTACLE_DILATION_PX + 1
        kernel = np.ones((k, k), dtype=np.uint8)
        obstacle_layer = cv2.dilate(obstacle_layer, kernel, iterations=1)

    image[obstacle_layer > 0] = (60, 60, 60)
    return image, meta


def main():
    scene_tri_cache = {}
    for ep_key, (scene, result_dirs) in EPISODES.items():
        all_x, all_y, floor_z = [], [], None
        for rd in result_dirs:
            traj = find_traj_file(rd)
            xs, ys, zs = load_all_positions(traj)
            all_x += xs
            all_y += ys
            if floor_z is None:
                floor_z = zs[0]  # first outbound frame's z, same convention as the figure script

        min_x, max_x = min(all_x) - CROP_MARGIN_M, max(all_x) + CROP_MARGIN_M
        min_y, max_y = min(all_y) - CROP_MARGIN_M, max(all_y) + CROP_MARGIN_M

        if scene not in scene_tri_cache:
            usd_path = os.path.join(USD_ROOT, scene, f"{scene}.usd")
            print(f"[{ep_key}] loading USD mesh for scene {scene} ...")
            scene_tri_cache[scene] = scene_world_triangles(usd_path)
        occ_img, meta = build_occupancy(scene_tri_cache[scene], floor_z, min_x, max_x, min_y, max_y)

        cv2.imwrite(os.path.join(OUT_DIR, f"{ep_key}_occupancy.png"), occ_img)
        with open(os.path.join(OUT_DIR, f"{ep_key}_meta.json"), "w") as f:
            json.dump(meta, f, indent=2)
        print(f"[{ep_key}] {meta['width_px']}x{meta['height_px']}px, "
              f"{len(all_x)} traj points across {len(result_dirs)} run(s)")


if __name__ == "__main__":
    main()
