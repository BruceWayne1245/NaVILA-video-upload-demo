#!/usr/bin/env python3
"""2x2 route-map grids for the 4 overlap episodes where oracle_hint returned
successfully but the pure baseline did not (episode_id 422/602/1153/1378).

Reuses the same building blocks as the 2026-06-30 hard-11 grid
(artifacts/stop_gate_r3_oracle_hard_20260630_route_maps/hard11_stop_gate_r3_hint_action_arbiter_20260630_grid.png):
topdown_route_map.render_route_overlay() for each panel, plus a header banner
with the same green/red/gray legend. Since neither pure_navila_baseline_100ep_20260810
nor pure_oracle_hint_highsuccess100ep_20260811 was run with --topdown_route_map,
there's no occupancy capture saved under their own eval_results/ — the occupancy
background is scene-fixed, so a real captured floor slice is reused from any
historical batch that did capture it for the same episode_idx
(canonical_report_next_stopgate_100ep_20260720_accumulated has all 4).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, "/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/scripts")
from topdown_route_map import TopDownMap, render_route_overlay  # noqa: E402

BENCH = Path("/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench")
RUN_PREFIX = "round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02"
BASELINE_TAG = "pure_navila_baseline_100ep_20260810"
ORACLE_TAG = "pure_oracle_hint_highsuccess100ep_20260811"
OCCUPANCY_SOURCE_TAG = "canonical_report_next_stopgate_100ep_20260720_accumulated"

# (episode_idx, episode_id, occupancy_output_id) -- occupancy_output_id is the
# route_maps/output_<id> file basename saved by that historical batch.
EPISODES = [
    (268, 422, 421),
    (367, 602, 601),
    (669, 1153, 1152),
    (813, 1378, 1377),
]

OUT_DIR = Path("/tmp/claude-1006/-home-teambruce/1b3ab78e-16b9-404a-820f-7d54ceb5d8c9/scratchpad")

GREEN = (60, 130, 30)
RED = (60, 30, 150)
GRAY = (90, 90, 90)
BANNER_BG = (35, 35, 35)


def result_dir(run_tag: str, ep_idx: int) -> Path:
    return BENCH / "eval_results" / f"{RUN_PREFIX}_{run_tag}_ep{ep_idx}"


def load_run(run_tag: str, ep_idx: int) -> dict:
    root = result_dir(run_tag, ep_idx)
    measurement_paths = sorted((root / "measurements").glob("*.json"))
    trajectory_paths = sorted((root / "trajectories").glob("*.jsonl"))
    with measurement_paths[-1].open("r", encoding="utf-8") as f:
        measurement = json.load(f)
    records = [
        json.loads(line)
        for line in trajectory_paths[-1].read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return {"round_trip": measurement.get("round_trip", {}), "records": records}


def load_occupancy(ep_idx: int, output_id: int) -> TopDownMap:
    root = result_dir(OCCUPANCY_SOURCE_TAG, ep_idx) / "route_maps"
    image = cv2.imread(str(root / f"output_{output_id}_occupancy.png"))
    with (root / f"output_{output_id}_map_meta.json").open("r", encoding="utf-8") as f:
        meta = json.load(f)
    return TopDownMap(image=image, meta=meta)


def fit_text(image: np.ndarray, text: str, x: int, y: int, max_width: int, base_scale: float, color, thickness: int = 1) -> None:
    scale = base_scale
    while scale > 0.22:
        w = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, thickness)[0][0]
        if w <= max_width:
            break
        scale -= 0.02
    cv2.putText(image, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX, scale, color, thickness, cv2.LINE_AA)


def panel(run_data: dict, topdown_map: TopDownMap, ep_id: int) -> dict:
    records = run_data["records"]
    rt = run_data["round_trip"]
    episode = {
        "start_position": records[0]["position"] if records else [0.0, 0.0, 0.0],
        "reference_path": [],
    }
    route_memory = rt.get("route_memory")
    overlay = render_route_overlay(topdown_map, records, route_memory, episode)

    dist = float(rt.get("distance_to_start", float("nan")))
    if rt.get("round_trip_success"):
        header_color = GREEN
        status = f"OK round-trip | dist {dist:.2f}m"
    elif rt.get("outbound_success") is None and not records:
        header_color = GRAY
        status = "not executed"
    else:
        header_color = RED
        if rt.get("outbound_success"):
            status = f"FAIL return | dist {dist:.2f}m"
        else:
            status = f"FAIL outbound | dist {dist:.2f}m"

    return {"map": overlay, "ep_id": ep_id, "header_color": header_color, "status": status}


def resize_to(image: np.ndarray, width: int, height: int) -> np.ndarray:
    interp = cv2.INTER_AREA if (width < image.shape[1] or height < image.shape[0]) else cv2.INTER_LINEAR
    return cv2.resize(image, (width, height), interpolation=interp)


def compose_tile(info: dict, cell_w: int, header_h: int, map_h: int) -> np.ndarray:
    """Resize this panel's map to (cell_w, map_h) and draw a fresh, undistorted header on top."""
    map_img = resize_to(info["map"], cell_w, map_h)
    tile = np.empty((header_h + map_h, cell_w, 3), dtype=np.uint8)
    tile[:header_h, :] = info["header_color"]
    tile[header_h:, :] = map_img
    cv2.rectangle(tile, (0, 0), (cell_w - 1, tile.shape[0] - 1), info["header_color"], 3)

    avail = cell_w - 20
    fit_text(tile, f"Episode {info['ep_id']}", 10, 20, avail, 0.52, (255, 255, 255))
    fit_text(tile, info["status"], 10, 42, avail, 0.40, (255, 255, 255))
    return tile


def make_grid(panels: list[dict], title: str) -> np.ndarray:
    # Every tile gets the SAME cell_w x map_h map area (largest across all 4,
    # maps stretched to fit) plus a fixed, undistorted header -- so all 4
    # tiles are pixel-identical in size and the grid has zero gaps/padding.
    header_h = 54
    cell_w = max(p["map"].shape[1] for p in panels)
    map_h = max(p["map"].shape[0] for p in panels)
    tiles = [compose_tile(p, cell_w, header_h, map_h) for p in panels]
    cell_h = header_h + map_h

    cols, rows = 2, 2
    grid_w = cols * cell_w
    grid_h = rows * cell_h
    grid = np.zeros((grid_h, grid_w, 3), dtype=np.uint8)
    for i, t in enumerate(tiles):
        r, c = divmod(i, cols)
        y0 = r * cell_h
        x0 = c * cell_w
        grid[y0 : y0 + cell_h, x0 : x0 + cell_w] = t

    banner_h = 54
    out = np.full((grid_h + banner_h, grid_w, 3), BANNER_BG, dtype=np.uint8)
    out[banner_h:, :] = grid

    legend = [(GREEN, "Round-trip success"), (RED, "Failure (outbound or return)")]
    lx, ly = 14, 20
    for color, label in legend:
        cv2.rectangle(out, (lx, ly - 10), (lx + 18, ly + 3), color, -1)
        cv2.putText(out, label, (lx + 24, ly + 1), cv2.FONT_HERSHEY_SIMPLEX, 0.40, (255, 255, 255), 1, cv2.LINE_AA)
        text_w = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.40, 1)[0][0]
        lx += 18 + 8 + text_w + 24

    cv2.putText(out, title, (14, 44), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (210, 210, 210), 1, cv2.LINE_AA)
    return out


def build(run_tag: str, out_name: str, title: str) -> Path:
    panels = []
    for ep_idx, ep_id, output_id in EPISODES:
        run_data = load_run(run_tag, ep_idx)
        topdown_map = load_occupancy(ep_idx, output_id)
        panels.append(panel(run_data, topdown_map, ep_id))
    grid = make_grid(panels, title)
    grid = cv2.resize(grid, (grid.shape[1] * UPSCALE, grid.shape[0] * UPSCALE), interpolation=cv2.INTER_NEAREST)
    out_path = OUT_DIR / out_name
    cv2.imwrite(str(out_path), grid)
    return out_path


UPSCALE = 2


def main() -> None:
    p1 = build(BASELINE_TAG, "baseline_4ep_return_grid_20260812.png", "pure NaVILA baseline -- 20260810")
    print(p1)
    p2 = build(ORACLE_TAG, "oracle_hint_4ep_return_grid_20260812.png", "oracle_hint highsuccess100ep -- 20260811")
    print(p2)


if __name__ == "__main__":
    main()
