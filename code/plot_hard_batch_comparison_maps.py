#!/usr/bin/env python3
"""Draw side-by-side route comparison maps for the hard 11-episode batch."""

from __future__ import annotations

import csv
import json
import os
from pathlib import Path

import cv2
import numpy as np

from topdown_route_map import TopDownMap, render_route_overlay, world_to_pixel


BENCH = Path("/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench")
RUN_PREFIX = "round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02"
NO_HINT = "no_hint_hard_fresh_20260629"
STOP_GATE = "stop_gate_oracle_hard_fresh_20260629"
EPISODES = [4, 5, 134, 187, 367, 368, 408, 678, 680, 994, 1040]


def read_summary(run_tag: str) -> dict[int, dict]:
    path = BENCH / "batch_logs" / run_tag / "summary.tsv"
    rows: dict[int, dict] = {}
    with path.open("r", encoding="utf-8") as f:
        for row in csv.DictReader(f, delimiter="\t"):
            if not row.get("episode_idx"):
                continue
            ep = int(row["episode_idx"])
            rows[ep] = row
    return rows


def result_dir(run_tag: str, ep: int) -> Path:
    return BENCH / "eval_results" / f"{RUN_PREFIX}_{run_tag}_ep{ep}"


def load_run(run_tag: str, ep: int) -> dict:
    root = result_dir(run_tag, ep)
    measurement_paths = sorted((root / "measurements").glob("*.json"))
    trajectory_paths = sorted((root / "trajectories").glob("*.jsonl"))
    if not measurement_paths or not trajectory_paths:
        raise FileNotFoundError(f"Missing measurement or trajectory for {run_tag} ep{ep}")
    with measurement_paths[-1].open("r", encoding="utf-8") as f:
        measurement = json.load(f)
    records = [
        json.loads(line)
        for line in trajectory_paths[-1].read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return {
        "root": root,
        "measurement": measurement,
        "round_trip": measurement.get("round_trip", {}),
        "records": records,
    }


def collect_xy(run_data: dict) -> list[list[float]]:
    points: list[list[float]] = []
    for record in run_data["records"]:
        pos = record.get("position")
        if pos is not None and len(pos) >= 2:
            points.append([float(pos[0]), float(pos[1])])
    anchors = ((run_data["round_trip"].get("route_memory") or {}).get("anchors") or [])
    for anchor in anchors:
        pose = (anchor.get("metadata") or {}).get("world_pose")
        if pose is not None and len(pose) >= 2:
            points.append([float(pose[0]), float(pose[1])])
    return points


def make_meta(
    all_points: list[list[float]],
    resolution_m_per_px: float = 0.05,
    padding_m: float = 1.5,
    min_width_px: int = 320,
    min_height_px: int = 360,
) -> dict:
    pts = np.asarray(all_points, dtype=np.float32)
    min_x, min_y = np.min(pts, axis=0)
    max_x, max_y = np.max(pts, axis=0)
    min_x -= padding_m
    min_y -= padding_m
    max_x += padding_m
    max_y += padding_m
    width_m = float(max_x - min_x)
    height_m = float(max_y - min_y)
    min_width_m = float(min_width_px) * resolution_m_per_px
    min_height_m = float(min_height_px) * resolution_m_per_px
    if width_m < min_width_m:
        extra = 0.5 * (min_width_m - width_m)
        min_x -= extra
        max_x += extra
    if height_m < min_height_m:
        extra = 0.5 * (min_height_m - height_m)
        min_y -= extra
        max_y += extra
    width = int(np.ceil((max_x - min_x) / resolution_m_per_px)) + 1
    height = int(np.ceil((max_y - min_y) / resolution_m_per_px)) + 1
    return {
        "type": "trajectory_comparison_blank_grid",
        "min_x": float(min_x),
        "max_x": float(max_x),
        "min_y": float(min_y),
        "max_y": float(max_y),
        "resolution_m_per_px": float(resolution_m_per_px),
        "width_px": int(width),
        "height_px": int(height),
    }


def blank_grid(meta: dict) -> np.ndarray:
    image = np.full((meta["height_px"], meta["width_px"], 3), 246, dtype=np.uint8)
    min_x = int(np.floor(meta["min_x"]))
    max_x = int(np.ceil(meta["max_x"]))
    min_y = int(np.floor(meta["min_y"]))
    max_y = int(np.ceil(meta["max_y"]))
    for x in range(min_x, max_x + 1):
        p0 = world_to_pixel([x, meta["min_y"]], meta)
        p1 = world_to_pixel([x, meta["max_y"]], meta)
        cv2.line(image, p0, p1, (226, 226, 226), 1)
    for y in range(min_y, max_y + 1):
        p0 = world_to_pixel([meta["min_x"], y], meta)
        p1 = world_to_pixel([meta["max_x"], y], meta)
        cv2.line(image, p0, p1, (226, 226, 226), 1)
    return image


def panel(run_data: dict, meta: dict, title: str) -> np.ndarray:
    base = blank_grid(meta)
    records = run_data["records"]
    episode = {
        "start_position": records[0]["position"] if records else [0.0, 0.0, 0.0],
        "reference_path": [],
    }
    route_memory = run_data["round_trip"].get("route_memory")
    image = render_route_overlay(TopDownMap(base, meta), records, route_memory, episode)
    header_h = 54
    out = np.full((image.shape[0] + header_h, image.shape[1], 3), 255, dtype=np.uint8)
    out[header_h:, :] = image
    rt = run_data["round_trip"]
    status = (
        f"out={rt.get('outbound_success')} ret={rt.get('return_success')} "
        f"d={float(rt.get('distance_to_start', float('nan'))):.2f}m"
    )
    cv2.putText(out, title, (8, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (20, 20, 20), 1, cv2.LINE_AA)
    cv2.putText(out, status, (8, 42), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (20, 20, 20), 1, cv2.LINE_AA)
    return out


def hstack_with_gap(left: np.ndarray, right: np.ndarray, gap: int = 18) -> np.ndarray:
    height = max(left.shape[0], right.shape[0])
    width = left.shape[1] + gap + right.shape[1]
    out = np.full((height, width, 3), 255, dtype=np.uint8)
    out[: left.shape[0], : left.shape[1]] = left
    out[: right.shape[0], left.shape[1] + gap:] = right
    return out


def main() -> None:
    out_dir = BENCH / "results" / "hard11_no_hint_vs_stop_gate_maps_20260630"
    out_dir.mkdir(parents=True, exist_ok=True)
    no_hint_summary = read_summary(NO_HINT)
    stop_gate_summary = read_summary(STOP_GATE)
    manifest = []
    for ep in EPISODES:
        no_hint = load_run(NO_HINT, ep)
        stop_gate = load_run(STOP_GATE, ep)
        all_points = collect_xy(no_hint) + collect_xy(stop_gate)
        meta = make_meta(all_points)
        left = panel(no_hint, meta, f"ep{ep} no-oracle baseline")
        right = panel(stop_gate, meta, f"ep{ep} oracle+yaw+stop-gate")
        comparison = hstack_with_gap(left, right)
        out_path = out_dir / f"ep{ep}_no_oracle_vs_oracle_yaw_stop_gate.png"
        cv2.imwrite(str(out_path), comparison)
        manifest.append({
            "episode": ep,
            "scene": no_hint_summary.get(ep, {}).get("scene") or stop_gate_summary.get(ep, {}).get("scene"),
            "output": str(out_path),
            "no_hint_distance_to_start": no_hint["round_trip"].get("distance_to_start"),
            "stop_gate_distance_to_start": stop_gate["round_trip"].get("distance_to_start"),
            "no_hint_round_trip_success": no_hint["round_trip"].get("round_trip_success"),
            "stop_gate_round_trip_success": stop_gate["round_trip"].get("round_trip_success"),
        })
        print(out_path)
    with (out_dir / "manifest.json").open("w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)


if __name__ == "__main__":
    main()
