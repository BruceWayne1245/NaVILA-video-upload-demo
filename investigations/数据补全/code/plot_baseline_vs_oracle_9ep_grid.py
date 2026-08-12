#!/usr/bin/env python3
"""3x3 route-map grids for 9 overlap episodes between pure_navila_baseline_100ep_20260810
and pure_oracle_hint_highsuccess100ep_20260811: the original 4 where oracle_hint flipped
a baseline return-fail to a return-success (episode_id 422/602/1153/1378), plus 5 more
picked for visibly different return trajectories even though both configs still fail
return (episode_id 512/1134/476/128/33 -- ranked by mean per-point divergence between
the two return paths after arc-length resampling, skipping near-duplicate mirror-route
pairs like 128/129 which share the same neighbor episode and start/goal).

Reuses the same building blocks as the 2026-06-30 hard-11 grid
(artifacts/stop_gate_r3_oracle_hard_20260630_route_maps/hard11_stop_gate_r3_hint_action_arbiter_20260630_grid.png):
topdown_route_map.render_route_overlay() for each panel, plus a header banner
with the same green/red/gray legend. Since neither pure_navila_baseline_100ep_20260810
nor pure_oracle_hint_highsuccess100ep_20260811 was run with --topdown_route_map,
there's no occupancy capture saved under their own eval_results/ — the occupancy
background is scene-fixed, so a real captured floor slice is reused from any
historical batch that did capture it for the same episode_idx
(canonical_report_next_stopgate_100ep_20260720_accumulated has all 9).

The underlying occupancy captures are native-resolution (0.05 m/px, fixed at
Isaac Sim capture time -- can't be recaptured offline). To still ship a
higher-resolution PNG, every panel's fully-rendered map (background + route
overlay, all baked into one raster by render_route_overlay) is upscaled with
cubic interpolation to a shared, deliberately-oversized cell (RESOLUTION_SCALE
x the largest native panel), and every header/legend/banner element is drawn
fresh, vector, at that same larger scale -- so text and box edges stay crisp
rather than being blurred/blocked-up by the upscale.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, "/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/scripts")
import topdown_route_map as tdm  # noqa: E402
from topdown_route_map import TopDownMap  # noqa: E402


def render_route_overlay_no_return_order(topdown_map, trajectory_records, route_memory_summary, episode):
    """Same as topdown_route_map.render_route_overlay(), minus the magenta
    numbered "return order" markers (_draw_return_timestamps) and the yellow
    A1/A2/... route-memory anchor markers -- both tended to clutter/hide the
    orange return line, and the anchors aren't needed to read baseline-vs-
    oracle_hint success/failure off these maps."""
    image = topdown_map.image.copy()
    meta = topdown_map.meta

    reference_path = [[float(p[0]), float(p[1])] for p in episode.get("reference_path", [])]
    tdm._polyline(image, reference_path, meta, (170, 170, 170), 1)

    outbound = [
        [float(r["position"][0]), float(r["position"][1])]
        for r in trajectory_records
        if r.get("phase") == "outbound" and r.get("position") is not None
    ]
    ret = [
        [float(r["position"][0]), float(r["position"][1])]
        for r in trajectory_records
        if r.get("phase") == "return" and r.get("position") is not None
    ]
    tdm._dashed_polyline(image, outbound, meta, (230, 105, 35), thickness=1, dash_px=8.0, gap_px=5.0)
    tdm._dashed_polyline(image, ret, meta, (35, 75, 230), thickness=1, dash_px=8.0, gap_px=5.0)
    # (deliberately no _draw_return_timestamps call, and no anchor markers, here)

    start = episode.get("start_position")
    goal = (episode.get("reference_path") or [None])[-1]
    if start is not None:
        tdm._draw_marker(image, start[:2], meta, (60, 180, 75), "start", radius=7)
    if goal is not None:
        tdm._draw_marker(image, goal[:2], meta, (180, 70, 180), "goal", radius=7)
    if trajectory_records:
        final_pos = trajectory_records[-1].get("position")
        if final_pos is not None:
            tdm._draw_marker(image, final_pos[:2], meta, (35, 35, 230), "final", radius=6)

    legend_x, legend_y = 12, 20
    legend = [
        ((55, 55, 55), "occupied"),
        ((230, 105, 35), "outbound"),
        ((35, 75, 230), "return"),
    ]
    for idx, (color, label) in enumerate(legend):
        y = legend_y + idx * 20
        cv2.line(image, (legend_x, y), (legend_x + 24, y), color, 4, cv2.LINE_AA)
        cv2.putText(image, label, (legend_x + 32, y + 5), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (20, 20, 20), 1, cv2.LINE_AA)
    return image

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
    (319, 512, 511),
    (653, 1134, 1133),
    (295, 476, 475),
    (88, 128, 127),
    (20, 33, 32),
]

OUT_DIR = Path("/tmp/claude-1006/-home-teambruce/8d729e83-ca24-4399-b9f8-5c9ab0940dc6/scratchpad")

GREEN = (60, 130, 30)
RED = (60, 30, 150)
GRAY = (90, 90, 90)
BANNER_BG = (35, 35, 35)

# How much bigger than the largest native (0.05 m/px) panel every tile's map
# area should be rendered at. Native panels are only ~230-460 px on a side,
# which looks blocky once tiled into a grid -- 3x with cubic interpolation
# gives a visibly sharper, higher-pixel-count image without changing any
# proportions (header/legend text is drawn fresh at the same 3x scale, not
# stretched, so it stays crisp).
RESOLUTION_SCALE = 3
HEADER_H = 54 * RESOLUTION_SCALE
BANNER_H = 54 * RESOLUTION_SCALE


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
    while scale > 0.22 * RESOLUTION_SCALE:
        w = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, thickness)[0][0]
        if w <= max_width:
            break
        scale -= 0.02 * RESOLUTION_SCALE
    cv2.putText(image, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX, scale, color, thickness, cv2.LINE_AA)


def panel(run_data: dict, topdown_map: TopDownMap, ep_id: int) -> dict:
    records = run_data["records"]
    rt = run_data["round_trip"]
    episode = {
        "start_position": records[0]["position"] if records else [0.0, 0.0, 0.0],
        "reference_path": [],
    }
    route_memory = rt.get("route_memory")
    overlay = render_route_overlay_no_return_order(topdown_map, records, route_memory, episode)

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
    interp = cv2.INTER_AREA if (width < image.shape[1] and height < image.shape[0]) else cv2.INTER_CUBIC
    return cv2.resize(image, (width, height), interpolation=interp)


def compose_tile(info: dict, cell_w: int, map_h: int) -> np.ndarray:
    """Resize this panel's map to (cell_w, map_h) and draw a fresh, undistorted header on top."""
    map_img = resize_to(info["map"], cell_w, map_h)
    tile = np.empty((HEADER_H + map_h, cell_w, 3), dtype=np.uint8)
    tile[:HEADER_H, :] = info["header_color"]
    tile[HEADER_H:, :] = map_img
    border = max(2, RESOLUTION_SCALE)
    cv2.rectangle(tile, (0, 0), (cell_w - 1, tile.shape[0] - 1), info["header_color"], border)

    avail = cell_w - 20 * RESOLUTION_SCALE
    fit_text(tile, f"Episode {info['ep_id']}", 10 * RESOLUTION_SCALE, 20 * RESOLUTION_SCALE, avail, 0.52 * RESOLUTION_SCALE, (255, 255, 255), thickness=RESOLUTION_SCALE)
    fit_text(tile, info["status"], 10 * RESOLUTION_SCALE, 42 * RESOLUTION_SCALE, avail, 0.40 * RESOLUTION_SCALE, (255, 255, 255), thickness=max(1, RESOLUTION_SCALE - 1))
    return tile


def make_grid(panels: list[dict], title: str) -> np.ndarray:
    # Every tile gets the SAME cell_w x map_h map area (RESOLUTION_SCALE x the
    # largest native panel, maps upscaled with cubic interpolation) plus a
    # fixed, undistorted header -- so all 4 tiles are pixel-identical in size
    # and the grid has zero gaps/padding.
    cell_w = max(p["map"].shape[1] for p in panels) * RESOLUTION_SCALE
    map_h = max(p["map"].shape[0] for p in panels) * RESOLUTION_SCALE
    tiles = [compose_tile(p, cell_w, map_h) for p in panels]
    cell_h = HEADER_H + map_h

    cols, rows = 3, 3
    grid_w = cols * cell_w
    grid_h = rows * cell_h
    grid = np.zeros((grid_h, grid_w, 3), dtype=np.uint8)
    for i, t in enumerate(tiles):
        r, c = divmod(i, cols)
        y0 = r * cell_h
        x0 = c * cell_w
        grid[y0 : y0 + cell_h, x0 : x0 + cell_w] = t

    out = np.full((grid_h + BANNER_H, grid_w, 3), BANNER_BG, dtype=np.uint8)
    out[BANNER_H:, :] = grid

    legend = [(GREEN, "Round-trip success"), (RED, "Failure (outbound or return)")]
    lx, ly = 14 * RESOLUTION_SCALE, 20 * RESOLUTION_SCALE
    legend_font = 0.40 * RESOLUTION_SCALE
    legend_thick = max(1, RESOLUTION_SCALE - 1)
    for color, label in legend:
        cv2.rectangle(out, (lx, ly - 10 * RESOLUTION_SCALE), (lx + 18 * RESOLUTION_SCALE, ly + 3 * RESOLUTION_SCALE), color, -1)
        cv2.putText(out, label, (lx + 24 * RESOLUTION_SCALE, ly + 1 * RESOLUTION_SCALE), cv2.FONT_HERSHEY_SIMPLEX, legend_font, (255, 255, 255), legend_thick, cv2.LINE_AA)
        text_w = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, legend_font, legend_thick)[0][0]
        lx += 18 * RESOLUTION_SCALE + 8 * RESOLUTION_SCALE + text_w + 40 * RESOLUTION_SCALE

    cv2.putText(
        out, title, (14 * RESOLUTION_SCALE, 44 * RESOLUTION_SCALE), cv2.FONT_HERSHEY_SIMPLEX,
        0.42 * RESOLUTION_SCALE, (210, 210, 210), legend_thick, cv2.LINE_AA,
    )
    return out


def build(run_tag: str, out_name: str, title: str) -> Path:
    panels = []
    for ep_idx, ep_id, output_id in EPISODES:
        run_data = load_run(run_tag, ep_idx)
        topdown_map = load_occupancy(ep_idx, output_id)
        panels.append(panel(run_data, topdown_map, ep_id))
    grid = make_grid(panels, title)
    out_path = OUT_DIR / out_name
    cv2.imwrite(str(out_path), grid, [cv2.IMWRITE_PNG_COMPRESSION, 6])
    return out_path


def main() -> None:
    p1 = build(BASELINE_TAG, "baseline_9ep_return_grid_20260812.png", "pure NaVILA baseline -- 20260810")
    print(p1)
    p2 = build(ORACLE_TAG, "oracle_hint_9ep_return_grid_20260812.png", "oracle_hint highsuccess100ep -- 20260811")
    print(p2)


if __name__ == "__main__":
    main()
