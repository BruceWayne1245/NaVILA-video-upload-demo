"""Isaac-only observer for the visual sequential-pair experiment.

Ground truth is written for analysis only.  This class deliberately exposes no
return value that the controller can consume, so simulator truth cannot leak
into visual relocalization, promotion, hint generation, or stopping.
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import asdict, dataclass
from typing import Any, Optional

import numpy as np


def _jsonable(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, (np.floating, np.integer)):
        return value.item()
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


def _yaw_from_wxyz(quat: np.ndarray) -> float:
    w, x, y, z = [float(v) for v in quat]
    return math.atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z))


@dataclass(frozen=True)
class MonitorConfig:
    schema: str = "navila-visual-sequential-pair-gt-v1"
    flush_every: int = 25


class VisualGroundTruthMonitor:
    """Append-only recorder of truth, anchors, controller state, and errors."""

    def __init__(self, output_dir: str, episode_id: int, scene_id: str,
                 config: Optional[MonitorConfig] = None):
        self.config = config or MonitorConfig()
        self.output_dir = os.path.abspath(output_dir)
        os.makedirs(self.output_dir, exist_ok=True)
        self.path = os.path.join(self.output_dir, "ground_truth_monitor.jsonl")
        self.summary_path = os.path.join(self.output_dir, "ground_truth_monitor_summary.json")
        self.anchor_dir = os.path.join(self.output_dir, "anchors")
        os.makedirs(self.anchor_dir, exist_ok=True)
        self._handle = open(self.path, "w", encoding="utf-8")
        self._rows = 0
        self._last_anchor_count = 0
        self._last_pair = None
        self._phase_counts: dict[str, int] = {}
        self._write({
            "event": "monitor_start",
            "schema": self.config.schema,
            "episode_id": int(episode_id),
            "scene_id": str(scene_id),
            "analysis_only": True,
            "controller_access_to_truth": False,
            "config": asdict(self.config),
        })

    def _write(self, row: dict) -> None:
        self._handle.write(json.dumps(_jsonable(row), sort_keys=True) + "\n")
        self._rows += 1
        if self._rows % max(1, self.config.flush_every) == 0:
            self._handle.flush()

    @staticmethod
    def _truth_pose(env) -> tuple[np.ndarray, float]:
        state = env.unwrapped.scene["robot"].data.root_state_w[0, :7]
        pose = state.detach().cpu().numpy().copy()
        return pose, _yaw_from_wxyz(pose[3:7])

    @staticmethod
    def _anchor_truth(anchor) -> Optional[dict]:
        metadata = anchor.metadata if isinstance(anchor.metadata, dict) else {}
        pose = metadata.get("world_pose")
        if not isinstance(pose, (list, tuple, np.ndarray)) or len(pose) < 7:
            return None
        pose = np.asarray(pose, dtype=np.float64)
        return {
            "index": int(anchor.index),
            "world_pose_wxyz": pose.tolist(),
            "world_xy": pose[:2].tolist(),
            "world_yaw_rad": _yaw_from_wxyz(pose[3:7]),
            "distance_from_start_m": float(anchor.distance_from_start_m),
            "route_remaining_to_start_m": float(anchor.route_remaining_to_start_m),
            "metadata": _jsonable(metadata),
        }

    def record_step(self, *, step: int, phase: str, env, route_agent,
                    progress=None, command=None, output=None) -> None:
        pose, yaw = self._truth_pose(env)
        current = getattr(route_agent, "_target_anchor_index", None)
        current_anchor, next_anchor = route_agent.sequential_target_anchor_pair()
        pair = (
            int(current_anchor.index) if current_anchor is not None else None,
            int(next_anchor.index) if next_anchor is not None else None,
        )
        row = {
            "event": "step",
            "step": int(step),
            "phase": str(phase),
            "robot_world_pose_wxyz": pose.tolist(),
            "robot_world_xy": pose[:2].tolist(),
            "robot_world_yaw_rad": float(yaw),
            "current_anchor_index": int(current) if current is not None else None,
            "pair": list(pair),
            "command": _jsonable(command),
            "vlm_output": str(output) if output is not None else None,
        }
        pair_truth = []
        for role, anchor in (("current", current_anchor), ("next", next_anchor)):
            truth = self._anchor_truth(anchor) if anchor is not None else None
            if truth is None:
                pair_truth.append({"role": role, "available": False})
                continue
            delta_w = np.asarray(truth["world_xy"], dtype=np.float64) - pose[:2]
            c, s = math.cos(yaw), math.sin(yaw)
            forward = c * delta_w[0] + s * delta_w[1]
            left = -s * delta_w[0] + c * delta_w[1]
            pair_truth.append({
                "role": role,
                "available": True,
                "anchor_index": truth["index"],
                "dx_forward_m": float(forward),
                "dy_left_m": float(left),
                "distance_m": float(np.linalg.norm(delta_w)),
                "bearing_deg": float(math.degrees(math.atan2(left, forward))),
            })
        row["pair_ground_truth"] = pair_truth
        if progress is not None:
            row["estimated_progress"] = {
                "target_anchor_index": getattr(progress, "target_anchor_index", None),
                "bearing_to_anchor_deg": getattr(progress, "bearing_to_anchor_deg", None),
                "distance_to_anchor_m": getattr(progress, "distance_to_anchor_m", None),
                "distance_to_start_m": getattr(progress, "distance_to_start_m", None),
                "confidence": getattr(progress, "confidence", None),
            }
            target_idx = getattr(progress, "target_anchor_index", None)
            estimated_bearing = getattr(progress, "bearing_to_anchor_deg", None)
            estimated_distance = getattr(progress, "distance_to_anchor_m", None)
            matching_truth = next(
                (
                    item for item in pair_truth
                    if item.get("available") and item.get("anchor_index") == target_idx
                ),
                None,
            )
            if matching_truth is not None:
                error = {"target_anchor_index": target_idx}
                if estimated_bearing is not None:
                    delta = (float(estimated_bearing) - matching_truth["bearing_deg"] + 180.0) % 360.0 - 180.0
                    error["bearing_error_deg"] = float(delta)
                    error["bearing_abs_error_deg"] = abs(float(delta))
                if estimated_distance is not None:
                    delta_d = float(estimated_distance) - matching_truth["distance_m"]
                    error["distance_error_m"] = float(delta_d)
                    error["distance_abs_error_m"] = abs(float(delta_d))
                row["online_error_against_truth"] = error
        self._write(row)
        self._phase_counts[phase] = self._phase_counts.get(phase, 0) + 1

        anchors = route_agent.anchors
        if len(anchors) > self._last_anchor_count:
            for anchor in anchors[self._last_anchor_count:]:
                descriptor = anchor.descriptor if isinstance(anchor.descriptor, dict) else {}
                arrays = {}
                for key in (
                    "rear_rgb", "rear_depth_obs", "rear_depth_depth_measurement",
                    "rear_camera_intrinsics", "rear_camera_position_w",
                    "rear_camera_quat_wxyz", "rear_camera_rotation_body",
                    "rear_camera_position_body",
                ):
                    value = descriptor.get(key)
                    if isinstance(value, np.ndarray):
                        arrays[key] = value
                asset_relpath = None
                if arrays:
                    asset_name = f"anchor_{int(anchor.index):05d}_rear_rgbd.npz"
                    np.savez_compressed(os.path.join(self.anchor_dir, asset_name), **arrays)
                    asset_relpath = os.path.join("anchors", asset_name)
                self._write({
                    "event": "anchor_created",
                    "step": int(step),
                    "phase": str(phase),
                    "anchor": self._anchor_truth(anchor),
                    "sensor_asset": asset_relpath,
                    "sensor_fields": sorted(arrays),
                })
            self._last_anchor_count = len(anchors)
        if pair != self._last_pair:
            self._write({
                "event": "pair_transition",
                "step": int(step),
                "phase": str(phase),
                "previous_pair": list(self._last_pair) if self._last_pair is not None else None,
                "new_pair": list(pair),
                "robot_world_pose_wxyz": pose.tolist(),
            })
            self._last_pair = pair

    def close(self, route_agent=None) -> None:
        if self._handle.closed:
            return
        anchors = []
        if route_agent is not None:
            anchors = [self._anchor_truth(a) for a in route_agent.anchors]
        self._write({"event": "monitor_end", "rows_before_end": self._rows})
        self._handle.flush()
        self._handle.close()
        payload = {
            "schema": self.config.schema,
            "jsonl": os.path.basename(self.path),
            "rows": self._rows,
            "phase_counts": self._phase_counts,
            "anchors": anchors,
            "analysis_only": True,
            "controller_access_to_truth": False,
        }
        tmp = self.summary_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(_jsonable(payload), handle, indent=2, sort_keys=True)
        os.replace(tmp, self.summary_path)
