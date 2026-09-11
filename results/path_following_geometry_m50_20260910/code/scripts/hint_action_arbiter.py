"""Hint-following action arbiter for return-stage VLN evaluation.

The arbiter is intentionally narrow: it only overrides a VLM action when the
route-memory hint gives a clear next-anchor direction, the VLM action points in
the opposite direction, and the hint direction is locally collision-free.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

import numpy as np

from local_map import LocalMapClearPathConfig, local_map_clear_path


@dataclass
class HintActionArbiterConfig:
    forward_cone_deg: float = 15.0
    forward_conflict_bearing_deg: float = 30.0
    turn_step_deg: float = 45.0
    forward_distance_cm: int = 75
    min_anchor_distance_m: float = 0.35
    max_clear_path_distance_m: float = 1.0
    robot_radius_m: float = 0.30
    clearance_margin_m: float = 0.12
    sample_step_m: float = 0.05
    allow_without_clear_path: bool = False
    # 2026-07-13, per the Oracle-to-shadow hint-source swap plan: this arbiter
    # previously had NO confidence gate at all -- it unconditionally trusted
    # whatever bearing/distance `progress` carried, which was always safe
    # while the only hint source in real navigation was the ground-truth
    # oracle. Default 0.0 preserves that exact prior behavior (every
    # confidence value passes) until a real threshold is calibrated via
    # offline replay against relocalization_confidence's known distribution
    # for the shadow (sequential_pair) hint source.
    min_relocalization_confidence: float = 0.0


@dataclass
class HintActionDecision:
    enabled: bool
    override: bool
    reason: str
    original_output: Optional[str] = None
    replacement_output: Optional[str] = None
    desired_kind: Optional[str] = None
    desired_bearing_deg: Optional[float] = None
    desired_distance_m: Optional[float] = None
    target_anchor_index: Optional[int] = None
    clear_path_available: bool = False
    clear_path: Optional[bool] = None
    clear_path_source: Optional[str] = None
    min_clearance_m: Optional[float] = None
    relocalization_confidence: Optional[float] = None

    def as_log_dict(self) -> dict:
        return {
            "enabled": self.enabled,
            "override": self.override,
            "reason": self.reason,
            "original_output": self.original_output,
            "replacement_output": self.replacement_output,
            "desired_kind": self.desired_kind,
            "desired_bearing_deg": self.desired_bearing_deg,
            "desired_distance_m": self.desired_distance_m,
            "target_anchor_index": self.target_anchor_index,
            "clear_path_available": self.clear_path_available,
            "clear_path": self.clear_path,
            "clear_path_source": self.clear_path_source,
            "min_clearance_m": self.min_clearance_m,
            "relocalization_confidence": self.relocalization_confidence,
        }


def _vlm_action_kind(text: object) -> str:
    lower = "" if text is None else str(text).lower()
    if "stop" in lower:
        return "stop"
    if "turn left" in lower:
        return "left"
    if "turn right" in lower:
        return "right"
    if "move forward" in lower or "move" in lower:
        return "forward"
    return "unknown"


def _hint_direction(progress: object) -> tuple[Optional[float], Optional[float], Optional[int]]:
    if progress is None:
        return None, None, None
    anchor_bearing = getattr(progress, "bearing_to_anchor_deg", None)
    anchor_distance = getattr(progress, "distance_to_anchor_m", None)
    target_anchor_index = getattr(progress, "target_anchor_index", None)
    if anchor_bearing is not None and anchor_distance is not None:
        return float(anchor_bearing), float(anchor_distance), target_anchor_index
    bearing = getattr(progress, "bearing_to_start_deg", None)
    distance = getattr(progress, "distance_to_start_m", None)
    if bearing is None or distance is None:
        return None, None, target_anchor_index
    return float(bearing), float(distance), target_anchor_index


def _desired_kind(bearing_deg: float, cfg: HintActionArbiterConfig) -> str:
    if abs(bearing_deg) <= cfg.forward_cone_deg:
        return "forward"
    return "left" if bearing_deg > 0.0 else "right"


def _replacement_output(kind: str, cfg: HintActionArbiterConfig) -> str:
    if kind == "forward":
        return f"The next action is move forward {int(cfg.forward_distance_cm)} cm."
    if kind == "left":
        return f"The next action is turn left {int(cfg.turn_step_deg)} degree."
    if kind == "right":
        return f"The next action is turn right {int(cfg.turn_step_deg)} degree."
    return "The next action is stop."


def _conflicts_with_hint(vlm_kind: str, desired_kind: str, bearing_deg: float, cfg: HintActionArbiterConfig) -> bool:
    if vlm_kind in ("unknown", "stop"):
        return True
    if desired_kind == "forward":
        return vlm_kind in ("left", "right")
    if desired_kind == "left":
        if vlm_kind == "right":
            return True
        return vlm_kind == "forward" and abs(bearing_deg) >= cfg.forward_conflict_bearing_deg
    if desired_kind == "right":
        if vlm_kind == "left":
            return True
        return vlm_kind == "forward" and abs(bearing_deg) >= cfg.forward_conflict_bearing_deg
    return False


def _world_to_pixel(x: float, y: float, meta: dict) -> tuple[int, int]:
    px = int(round((x - float(meta["min_x"])) / float(meta["resolution_m_per_px"])))
    py = int(round((float(meta["max_y"]) - y) / float(meta["resolution_m_per_px"])))
    return px, py


def _body_vector_to_world(position_xy: np.ndarray, yaw_rad: float, dx: float, dy: float) -> np.ndarray:
    c = math.cos(yaw_rad)
    s = math.sin(yaw_rad)
    return np.asarray(
        [
            float(position_xy[0]) + c * dx - s * dy,
            float(position_xy[1]) + s * dx + c * dy,
        ],
        dtype=np.float32,
    )


def _topdown_clear_path(
    topdown_map: object,
    position_xy: object,
    yaw_rad: float,
    target_dx_m: float,
    target_dy_m: float,
    cfg: HintActionArbiterConfig,
) -> tuple[bool, Optional[float], str]:
    if topdown_map is None or getattr(topdown_map, "image", None) is None or getattr(topdown_map, "meta", None) is None:
        return False, None, "no_topdown_map"
    image = np.asarray(topdown_map.image)
    meta = dict(topdown_map.meta)
    if image.ndim != 3 or image.shape[0] == 0 or image.shape[1] == 0:
        return False, None, "invalid_topdown_map"

    target_len = float(math.hypot(target_dx_m, target_dy_m))
    if target_len <= 1e-6:
        return True, None, "zero_length_target"
    check_len = min(target_len, float(cfg.max_clear_path_distance_m))
    direction_body = np.asarray([target_dx_m / target_len, target_dy_m / target_len], dtype=np.float32)
    position_xy = np.asarray(position_xy, dtype=np.float32).reshape(2)
    resolution = float(meta["resolution_m_per_px"])
    radius_m = float(cfg.robot_radius_m + cfg.clearance_margin_m)
    radius_px = max(1, int(math.ceil(radius_m / max(resolution, 1e-6))))
    samples = max(2, int(math.ceil(check_len / max(float(cfg.sample_step_m), 1e-3))) + 1)

    obstacle = np.mean(image[:, :, :3].astype(np.float32), axis=2) < 100.0
    min_clearance_px = None
    for t in np.linspace(0.0, check_len, samples, dtype=np.float32):
        body = direction_body * float(t)
        world = _body_vector_to_world(position_xy, yaw_rad, float(body[0]), float(body[1]))
        px, py = _world_to_pixel(float(world[0]), float(world[1]), meta)
        if px < 0 or py < 0 or px >= obstacle.shape[1] or py >= obstacle.shape[0]:
            return False, 0.0, "path_leaves_topdown_map"
        x0 = max(0, px - radius_px)
        x1 = min(obstacle.shape[1], px + radius_px + 1)
        y0 = max(0, py - radius_px)
        y1 = min(obstacle.shape[0], py + radius_px + 1)
        local_obstacle = obstacle[y0:y1, x0:x1]
        if np.any(local_obstacle):
            yy, xx = np.nonzero(local_obstacle)
            clear_px = float(np.min(np.hypot(xx + x0 - px, yy + y0 - py)))
        else:
            clear_px = float(radius_px)
        min_clearance_px = clear_px if min_clearance_px is None else min(min_clearance_px, clear_px)
        if clear_px < radius_px:
            return False, clear_px * resolution, "occupied_in_hint_path"
    return True, (min_clearance_px or 0.0) * resolution, "clear"


class HintActionArbiter:
    def __init__(self, cfg: HintActionArbiterConfig):
        self.cfg = cfg

    def check(
        self,
        *,
        progress: object,
        vlm_output: object,
        robot_position: object,
        robot_yaw_rad: float,
        topdown_map: object = None,
        local_map_descriptor: object = None,
    ) -> HintActionDecision:
        bearing, distance, target_anchor_index = _hint_direction(progress)
        relocalization_confidence = getattr(progress, "relocalization_confidence", None)
        base = {
            "enabled": True,
            "original_output": None if vlm_output is None else str(vlm_output),
            "desired_bearing_deg": bearing,
            "desired_distance_m": distance,
            "target_anchor_index": target_anchor_index,
            "relocalization_confidence": relocalization_confidence,
        }
        if bearing is None or distance is None:
            return HintActionDecision(override=False, reason="missing_hint_direction", **base)
        if distance < self.cfg.min_anchor_distance_m:
            return HintActionDecision(override=False, reason="target_too_close", **base)
        # 2026-07-13: only override the VLM when this reading is itself
        # trustworthy -- previously ungated (see min_relocalization_confidence's
        # docstring). A missing confidence value (older/oracle-only progress
        # objects that never set the field) is treated as "no reason to
        # distrust it", not as untrustworthy -- mirrors
        # RouteMemoryAgent._candidate_is_trustworthy's same convention for
        # match_class.
        if relocalization_confidence is not None and relocalization_confidence < self.cfg.min_relocalization_confidence:
            return HintActionDecision(override=False, reason="low_relocalization_confidence", **base)

        desired = _desired_kind(bearing, self.cfg)
        vlm_kind = _vlm_action_kind(vlm_output)
        replacement = _replacement_output(desired, self.cfg)
        base.update({"desired_kind": desired, "replacement_output": replacement})
        if not _conflicts_with_hint(vlm_kind, desired, bearing, self.cfg):
            return HintActionDecision(override=False, reason="vlm_action_consistent", **base)

        target_dx = getattr(progress, "anchor_dx_m", None)
        target_dy = getattr(progress, "anchor_dy_m", None)
        if target_dx is None or target_dy is None:
            target_dx = getattr(progress, "target_dx_m", None)
            target_dy = getattr(progress, "target_dy_m", None)

        clear_path_available = False
        clear_path = None
        min_clearance = None
        clear_path_source = None
        reason = "clear_path_unavailable"
        if target_dx is not None and target_dy is not None:
            local_result = local_map_clear_path(
                local_map_descriptor,
                float(target_dx),
                float(target_dy),
                LocalMapClearPathConfig(
                    max_distance_m=float(self.cfg.max_clear_path_distance_m),
                    robot_radius_m=float(self.cfg.robot_radius_m),
                    clearance_margin_m=float(self.cfg.clearance_margin_m),
                    sample_step_m=float(self.cfg.sample_step_m),
                ),
            )
            if local_result.available:
                clear_path_available = True
                clear_path = local_result.clear
                min_clearance = local_result.min_clearance_m
                reason = local_result.reason
                clear_path_source = "local_map"
        if not clear_path_available and target_dx is not None and target_dy is not None and topdown_map is not None:
            clear_path_available = True
            clear_path, min_clearance, reason = _topdown_clear_path(
                topdown_map,
                np.asarray(robot_position, dtype=np.float32)[:2],
                float(robot_yaw_rad),
                float(target_dx),
                float(target_dy),
                self.cfg,
            )
            clear_path_source = "topdown_map"
        if not clear_path_available and not self.cfg.allow_without_clear_path:
            return HintActionDecision(
                override=False,
                reason=reason,
                clear_path_available=False,
                clear_path=None,
                clear_path_source=None,
                min_clearance_m=None,
                **base,
            )
        if clear_path_available and not clear_path:
            return HintActionDecision(
                override=False,
                reason=reason,
                clear_path_available=True,
                clear_path=False,
                clear_path_source=clear_path_source,
                min_clearance_m=min_clearance,
                **base,
            )
        return HintActionDecision(
            override=True,
            reason="vlm_conflicts_with_clear_hint",
            clear_path_available=clear_path_available,
            clear_path=clear_path if clear_path_available else None,
            clear_path_source=clear_path_source,
            min_clearance_m=min_clearance,
            **base,
        )
