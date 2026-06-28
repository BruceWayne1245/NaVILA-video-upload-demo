"""Route-memory support for round-trip VLN evaluation.

The default progress estimate still uses action-integrated motion to preserve
the existing benchmark behavior.  The anchor path below adds a map-free
relocalization interface: an external visual backend may estimate the pose of a
saved outbound anchor from the current return frame, and the agent turns that
into a metric Return hint before the robot physically reaches the anchor.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
import math
from typing import Callable, Iterable, Optional


def wrap_angle(angle: float) -> float:
    return math.atan2(math.sin(angle), math.cos(angle))


def compose_pose(pose: Iterable[float], delta: Iterable[float]) -> list[float]:
    """Compose an SE(2) pose with a body-frame motion delta."""
    x, y, theta = [float(v) for v in pose]
    dx, dy, dtheta = [float(v) for v in delta]
    cos_t = math.cos(theta)
    sin_t = math.sin(theta)
    return [
        x + cos_t * dx - sin_t * dy,
        y + sin_t * dx + cos_t * dy,
        wrap_angle(theta + dtheta),
    ]


def inverse_delta(delta: Iterable[float]) -> list[float]:
    """Return the body-frame motion that undoes ``delta`` from the arrival pose."""
    end_pose = compose_pose([0.0, 0.0, 0.0], delta)
    x, y, theta = end_pose
    cos_t = math.cos(theta)
    sin_t = math.sin(theta)
    dx_world = -x
    dy_world = -y
    return [
        cos_t * dx_world + sin_t * dy_world,
        -sin_t * dx_world + cos_t * dy_world,
        wrap_angle(-theta),
    ]


def relative_delta(previous_pose: Iterable[float], current_pose: Iterable[float]) -> list[float]:
    """Compute the body-frame delta from ``previous_pose`` to ``current_pose``."""
    px, py, ptheta = [float(v) for v in previous_pose]
    cx, cy, ctheta = [float(v) for v in current_pose]
    dx_world = cx - px
    dy_world = cy - py
    cos_t = math.cos(ptheta)
    sin_t = math.sin(ptheta)
    return [
        cos_t * dx_world + sin_t * dy_world,
        -sin_t * dx_world + cos_t * dy_world,
        wrap_angle(ctheta - ptheta),
    ]


@dataclass
class RelativeStartProgress:
    target_dx_m: float
    target_dy_m: float
    distance_to_start_m: float
    bearing_to_start_deg: float
    current_pose_from_start: list[float]
    return_pose_from_return_start: list[float]
    return_start_pose_from_start: list[float]
    source: str = "action_integrated_relative_start"
    target_anchor_index: Optional[int] = None
    anchor_dx_m: Optional[float] = None
    anchor_dy_m: Optional[float] = None
    distance_to_anchor_m: Optional[float] = None
    bearing_to_anchor_deg: Optional[float] = None
    anchor_route_remaining_m: Optional[float] = None
    anchor_heading_reliable: Optional[bool] = None
    relocalization_confidence: Optional[float] = None
    relocalization_backend: Optional[str] = None


@dataclass
class RouteAnchor:
    index: int
    pose_from_start: list[float]
    distance_from_start_m: float
    route_remaining_to_start_m: float = 0.0
    descriptor: Optional[object] = None
    metadata: dict = field(default_factory=dict)


@dataclass
class AnchorRelocalization:
    anchor_index: int
    anchor_dx_m: float
    anchor_dy_m: float
    anchor_dtheta_rad: float = 0.0
    confidence: float = 1.0
    backend: str = "external"
    inlier_count: Optional[int] = None
    reprojection_error_px: Optional[float] = None
    anchor_heading_reliable: bool = True

    @property
    def distance_to_anchor_m(self) -> float:
        return float(math.hypot(self.anchor_dx_m, self.anchor_dy_m))

    @property
    def bearing_to_anchor_deg(self) -> float:
        if self.distance_to_anchor_m <= 1e-6:
            return 0.0
        return float(math.degrees(math.atan2(self.anchor_dy_m, self.anchor_dx_m)))


@dataclass
class FallbackDecision:
    triggered: bool
    reason: str = ""
    command: Optional[list[float]] = None
    duration_seconds: float = 0.0


class RouteMemoryAgent:
    def __init__(
        self,
        enabled: bool = False,
        hint_mode: str = "compact",
        fallback_enabled: bool = False,
        anchor_spacing_m: float = 1.0,
        min_relocalization_confidence: float = 0.35,
        relocalization_interval_updates: int = 1,
        max_relocalization_consistency_error_m: float = 5.0,
        relocalizer: Optional[Callable[[object, list[RouteAnchor]], Optional[AnchorRelocalization]]] = None,
        **_: object,
    ):
        self.enabled = bool(enabled)
        self.hint_mode = hint_mode
        self.fallback_enabled = False
        self.anchor_spacing_m = float(anchor_spacing_m)
        self.min_relocalization_confidence = float(min_relocalization_confidence)
        self.relocalization_interval_updates = max(1, int(relocalization_interval_updates))
        self.max_relocalization_consistency_error_m = float(max_relocalization_consistency_error_m)
        self.relocalizer = relocalizer
        self.hint_events: list[dict] = []
        self.fallback_events: list[dict] = []
        self.anchors: list[RouteAnchor] = []
        self.relocalization_events: list[dict] = []
        self._outbound_pose_from_start = [0.0, 0.0, 0.0]
        self._return_start_pose_from_start = [0.0, 0.0, 0.0]
        self._return_pose_from_return_start = [0.0, 0.0, 0.0]
        self._return_started = False
        self._outbound_distance_m = 0.0
        self._last_anchor_distance_m = -float("inf")
        self._latest_relocalization: Optional[AnchorRelocalization] = None
        self._target_anchor_index: Optional[int] = None
        self._target_anchor_min_distance_m: Optional[float] = None
        self.anchor_pass_radius_m = 0.8
        self.anchor_pass_hysteresis_m = 0.6
        self.anchor_pass_max_min_distance_m = max(2.0 * self.anchor_spacing_m, self.anchor_pass_radius_m)
        self._return_update_count = 0
        if self.enabled:
            self._append_anchor(descriptor=None, metadata={"event": "start"})

    def update_outbound_odometry(self, delta: Iterable[float], **kwargs: object) -> None:
        self.update_outbound_motion(delta, **kwargs)

    def update_outbound_motion(
        self,
        delta: Iterable[float],
        descriptor: Optional[object] = None,
        metadata: Optional[dict] = None,
    ) -> None:
        if not self.enabled:
            return
        self._outbound_pose_from_start = compose_pose(self._outbound_pose_from_start, delta)
        dx, dy, _ = [float(v) for v in delta]
        self._outbound_distance_m += float(math.hypot(dx, dy))
        if self._should_save_anchor():
            self._append_anchor(descriptor=descriptor, metadata=metadata)

    def update_return_odometry(self, delta: Iterable[float], **kwargs: object) -> None:
        self.update_return_motion(delta, **kwargs)

    def update_return_motion(
        self,
        delta: Iterable[float],
        local_descriptor: Optional[object] = None,
        relocalization: Optional[AnchorRelocalization | dict] = None,
        **_: object,
    ) -> None:
        if not self.enabled or not self._return_started:
            return
        self._return_pose_from_return_start = compose_pose(self._return_pose_from_return_start, delta)
        self._propagate_latest_relocalization(delta)
        self._return_update_count += 1
        self.update_relocalization(local_descriptor=local_descriptor, relocalization=relocalization)

    def finalize_outbound(self) -> None:
        if self.enabled and (not self.anchors or self.anchors[-1].distance_from_start_m < self._outbound_distance_m):
            self._append_anchor(descriptor=None, metadata={"event": "outbound_final"})
        self._finalize_anchor_route_lengths()
        self._return_start_pose_from_start = list(self._outbound_pose_from_start)
        self._return_pose_from_return_start = [0.0, 0.0, 0.0]
        self._return_started = True

    def update_relocalization(
        self,
        local_descriptor: Optional[object] = None,
        relocalization: Optional[AnchorRelocalization | dict] = None,
    ) -> Optional[AnchorRelocalization]:
        if not self.enabled or not self._return_started:
            return None
        estimate = self._coerce_relocalization(relocalization)
        if estimate is None and self.relocalizer is not None:
            if self._return_update_count % self.relocalization_interval_updates != 0:
                return None
            estimate = self.relocalizer(local_descriptor, self.anchors)
        if estimate is None or estimate.confidence < self.min_relocalization_confidence:
            return None
        if not self._anchor_by_index(estimate.anchor_index):
            return None
        estimate, reject_reason = self._apply_monotonic_anchor_policy(estimate)
        if estimate is None:
            self.relocalization_events.append({
                "accepted": False,
                "reject_reason": reject_reason,
                "target_anchor_index": self._target_anchor_index,
            })
            return None
        consistency_error = self._relocalization_consistency_error(estimate)
        if consistency_error is not None:
            self.relocalization_events.append({
                "anchor_index": int(estimate.anchor_index),
                "anchor_dx_m": float(estimate.anchor_dx_m),
                "anchor_dy_m": float(estimate.anchor_dy_m),
                "anchor_dtheta_rad": float(estimate.anchor_dtheta_rad),
                "distance_to_anchor_m": estimate.distance_to_anchor_m,
                "bearing_to_anchor_deg": estimate.bearing_to_anchor_deg,
                "confidence": float(estimate.confidence),
                "backend": estimate.backend,
                "inlier_count": estimate.inlier_count,
                "reprojection_error_px": estimate.reprojection_error_px,
                "anchor_heading_reliable": bool(estimate.anchor_heading_reliable),
                "accepted": False,
                "reject_reason": "inconsistent_with_integrated_progress",
                "consistency_error_m": float(consistency_error),
            })
            return None
        self._latest_relocalization = estimate
        self.relocalization_events.append({
            "anchor_index": int(estimate.anchor_index),
            "anchor_dx_m": float(estimate.anchor_dx_m),
            "anchor_dy_m": float(estimate.anchor_dy_m),
            "anchor_dtheta_rad": float(estimate.anchor_dtheta_rad),
            "distance_to_anchor_m": estimate.distance_to_anchor_m,
            "bearing_to_anchor_deg": estimate.bearing_to_anchor_deg,
            "confidence": float(estimate.confidence),
            "backend": estimate.backend,
            "inlier_count": estimate.inlier_count,
            "reprojection_error_px": estimate.reprojection_error_px,
            "anchor_heading_reliable": bool(estimate.anchor_heading_reliable),
            "target_anchor_index": self._target_anchor_index,
            "accepted": True,
        })
        return estimate

    def update_latest_anchor_metadata(self, metadata: dict) -> None:
        if not self.enabled or not self.anchors:
            return
        self.anchors[-1].metadata.update(dict(metadata))

    def progress(self) -> Optional[RelativeStartProgress]:
        if not self.enabled or not self._return_started:
            return None
        anchor_progress = self._anchor_progress()
        if anchor_progress is not None:
            return anchor_progress
        current_pose = compose_pose(self._return_start_pose_from_start, self._return_pose_from_return_start)
        target_delta = relative_delta(current_pose, [0.0, 0.0, 0.0])
        dx, dy, _ = target_delta
        distance = float(math.hypot(dx, dy))
        bearing = math.degrees(math.atan2(dy, dx)) if distance > 1e-6 else 0.0
        return RelativeStartProgress(
            target_dx_m=float(dx),
            target_dy_m=float(dy),
            distance_to_start_m=distance,
            bearing_to_start_deg=float(bearing),
            current_pose_from_start=[float(x) for x in current_pose],
            return_pose_from_return_start=[float(x) for x in self._return_pose_from_return_start],
            return_start_pose_from_start=[float(x) for x in self._return_start_pose_from_start],
        )

    def make_hint(self, progress: Optional[RelativeStartProgress]) -> str:
        if not self.enabled or self.hint_mode == "none" or progress is None:
            return ""
        if progress.target_anchor_index is not None:
            return self._make_anchor_hint(progress)
        if progress.distance_to_start_m < 0.35:
            direction = "at the outbound start"
        elif abs(progress.bearing_to_start_deg) <= 10.0:
            direction = "ahead"
        elif progress.bearing_to_start_deg > 0.0:
            direction = f"{abs(progress.bearing_to_start_deg):.0f} deg to your left"
        else:
            direction = f"{abs(progress.bearing_to_start_deg):.0f} deg to your right"

        if self.hint_mode == "verbose":
            return (
                "[System Hint: The return-stage terminal goal is the original outbound start. "
                f"Relative to your current pose, the start is {progress.distance_to_start_m:.2f} m away, "
                f"{direction}. In body-frame coordinates it is "
                f"dx={progress.target_dx_m:.2f} m forward, dy={progress.target_dy_m:.2f} m left. "
                "Use the visual instruction, but stop only when you believe you are back at that start location.]"
            )
        return (
            "[System Hint: return goal is the original start; "
            f"start is {progress.distance_to_start_m:.2f} m away, {direction} "
            f"(dx={progress.target_dx_m:.2f} m forward, dy={progress.target_dy_m:.2f} m left).]"
        )

    def inject_hint(
        self,
        base_instruction: str,
        step: int,
        progress_override: Optional[RelativeStartProgress] = None,
    ) -> tuple[str, Optional[dict]]:
        progress = progress_override if progress_override is not None else self.progress()
        hint = self.make_hint(progress)
        if not hint:
            return base_instruction, None
        event = {
            "step": int(step),
            "hint": hint,
            "progress": asdict(progress) if progress is not None else None,
        }
        self.hint_events.append(event)
        return f"{hint}\n{base_instruction}", event

    def update_action_history(self, command: Iterable[float]) -> None:
        return None

    def correction_decision(self, step: int) -> FallbackDecision:
        return FallbackDecision(False)

    def fallback_decision(self, step: int, is_parseable: bool) -> FallbackDecision:
        return FallbackDecision(False)

    def current_return_pose(self) -> list[float]:
        return list(self._return_pose_from_return_start)

    def summary(self) -> dict:
        progress = self.progress()
        return {
            "enabled": self.enabled,
            "localizer": (
                "anchor_relocalization"
                if progress is not None and progress.target_anchor_index is not None
                else "action_integrated_relative_start"
            ),
            "hint_mode": self.hint_mode,
            "fallback_enabled": False,
            "anchor_spacing_m": self.anchor_spacing_m,
            "min_relocalization_confidence": self.min_relocalization_confidence,
            "relocalization_interval_updates": self.relocalization_interval_updates,
            "max_relocalization_consistency_error_m": self.max_relocalization_consistency_error_m,
            "anchors": [self._anchor_summary(anchor) for anchor in self.anchors],
            "latest_relocalization": (
                asdict(self._latest_relocalization)
                if self._latest_relocalization is not None else None
            ),
            "outbound_pose_from_start": [float(x) for x in self._outbound_pose_from_start],
            "return_start_pose_from_start": [float(x) for x in self._return_start_pose_from_start],
            "return_pose_from_return_start": [float(x) for x in self._return_pose_from_return_start],
            "relative_start_progress": asdict(progress) if progress is not None else None,
            "hint_events": self.hint_events,
            "relocalization_events": self.relocalization_events,
            "fallback_events": self.fallback_events,
        }

    def _should_save_anchor(self) -> bool:
        if self.anchor_spacing_m <= 0.0:
            return False
        return self._outbound_distance_m - self._last_anchor_distance_m >= self.anchor_spacing_m

    def _append_anchor(self, descriptor: Optional[object], metadata: Optional[dict]) -> None:
        anchor = RouteAnchor(
            index=len(self.anchors),
            pose_from_start=[float(x) for x in self._outbound_pose_from_start],
            distance_from_start_m=float(self._outbound_distance_m),
            descriptor=descriptor,
            metadata=dict(metadata or {}),
        )
        self.anchors.append(anchor)
        self._last_anchor_distance_m = self._outbound_distance_m

    def _anchor_summary(self, anchor: RouteAnchor) -> dict:
        return {
            "index": int(anchor.index),
            "pose_from_start": [float(x) for x in anchor.pose_from_start],
            "distance_from_start_m": float(anchor.distance_from_start_m),
            "route_remaining_to_start_m": float(anchor.route_remaining_to_start_m),
            "descriptor": self._descriptor_summary(anchor.descriptor),
            "metadata": dict(anchor.metadata),
        }

    def _descriptor_summary(self, descriptor: Optional[object]) -> Optional[object]:
        if descriptor is None:
            return None
        if isinstance(descriptor, dict):
            summary = {}
            for key, value in descriptor.items():
                summary[key] = self._descriptor_value_summary(value)
            return summary
        return self._descriptor_value_summary(descriptor)

    def _descriptor_value_summary(self, value: object) -> object:
        shape = getattr(value, "shape", None)
        if shape is not None:
            result = {"shape": [int(dim) for dim in shape]}
            try:
                result["min"] = float(value.min())
                result["max"] = float(value.max())
            except Exception:
                pass
            return result
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        if isinstance(value, (list, tuple)) and len(value) <= 8:
            return [self._descriptor_value_summary(item) for item in value]
        return {"type": type(value).__name__}

    def _finalize_anchor_route_lengths(self) -> None:
        total = float(self._outbound_distance_m)
        for anchor in self.anchors:
            anchor.route_remaining_to_start_m = float(anchor.distance_from_start_m)
            anchor.metadata["route_distance_from_anchor_to_return_start_m"] = max(
                0.0,
                total - anchor.distance_from_start_m,
            )

    def _anchor_by_index(self, index: int) -> Optional[RouteAnchor]:
        for anchor in self.anchors:
            if anchor.index == index:
                return anchor
        return None

    def _coerce_relocalization(
        self,
        relocalization: Optional[AnchorRelocalization | dict],
    ) -> Optional[AnchorRelocalization]:
        if relocalization is None:
            return None
        if isinstance(relocalization, AnchorRelocalization):
            return relocalization
        backend = str(relocalization.get("backend", "external"))
        return AnchorRelocalization(
            anchor_index=int(relocalization["anchor_index"]),
            anchor_dx_m=float(relocalization["anchor_dx_m"]),
            anchor_dy_m=float(relocalization["anchor_dy_m"]),
            anchor_dtheta_rad=float(relocalization.get("anchor_dtheta_rad", 0.0)),
            confidence=float(relocalization.get("confidence", 1.0)),
            backend=backend,
            inlier_count=relocalization.get("inlier_count"),
            reprojection_error_px=relocalization.get("reprojection_error_px"),
            anchor_heading_reliable=bool(
                relocalization.get(
                    "anchor_heading_reliable",
                    not backend.startswith("feature_depth_"),
                )
            ),
        )

    def _propagate_latest_relocalization(self, delta: Iterable[float]) -> None:
        if self._latest_relocalization is None:
            return
        new_current_pose_in_previous = compose_pose([0.0, 0.0, 0.0], delta)
        previous_anchor_pose = [
            self._latest_relocalization.anchor_dx_m,
            self._latest_relocalization.anchor_dy_m,
            self._latest_relocalization.anchor_dtheta_rad,
        ]
        propagated = relative_delta(new_current_pose_in_previous, previous_anchor_pose)
        self._latest_relocalization = replace(
            self._latest_relocalization,
            anchor_dx_m=float(propagated[0]),
            anchor_dy_m=float(propagated[1]),
            anchor_dtheta_rad=float(propagated[2]),
        )
        self._maybe_advance_passed_anchor()

    def _apply_monotonic_anchor_policy(
        self,
        estimate: AnchorRelocalization,
    ) -> tuple[Optional[AnchorRelocalization], Optional[str]]:
        if self._target_anchor_index is None:
            self._target_anchor_index = int(estimate.anchor_index)
            self._target_anchor_min_distance_m = estimate.distance_to_anchor_m
            return estimate, None

        if estimate.anchor_index > self._target_anchor_index:
            return None, "anchor_index_would_move_away_from_start"

        if estimate.anchor_index < self._target_anchor_index:
            self._target_anchor_index = int(estimate.anchor_index)
            self._target_anchor_min_distance_m = estimate.distance_to_anchor_m
            return estimate, None

        self._target_anchor_min_distance_m = (
            estimate.distance_to_anchor_m
            if self._target_anchor_min_distance_m is None
            else min(self._target_anchor_min_distance_m, estimate.distance_to_anchor_m)
        )
        return self._project_to_next_anchor_if_passed(estimate), None

    def _maybe_advance_passed_anchor(self) -> None:
        if self._latest_relocalization is None:
            return
        self._latest_relocalization = self._project_to_next_anchor_if_passed(
            self._latest_relocalization
        )

    def _project_to_next_anchor_if_passed(
        self,
        estimate: AnchorRelocalization,
    ) -> AnchorRelocalization:
        if self._target_anchor_index is None or estimate.anchor_index != self._target_anchor_index:
            return estimate
        if self._target_anchor_index <= 0:
            return estimate
        distance = estimate.distance_to_anchor_m
        self._target_anchor_min_distance_m = (
            distance
            if self._target_anchor_min_distance_m is None
            else min(self._target_anchor_min_distance_m, distance)
        )
        if self._target_anchor_min_distance_m > self.anchor_pass_max_min_distance_m:
            return estimate
        if distance < self._target_anchor_min_distance_m + self.anchor_pass_hysteresis_m:
            return estimate

        next_index = self._target_anchor_index - 1
        projected = self._project_estimate_to_anchor(estimate, next_index)
        if projected is None:
            return estimate
        self._target_anchor_index = next_index
        self._target_anchor_min_distance_m = projected.distance_to_anchor_m
        return projected

    def _project_estimate_to_anchor(
        self,
        estimate: AnchorRelocalization,
        target_anchor_index: int,
    ) -> Optional[AnchorRelocalization]:
        source_anchor = self._anchor_by_index(estimate.anchor_index)
        target_anchor = self._anchor_by_index(target_anchor_index)
        if source_anchor is None or target_anchor is None:
            return None
        source_pose_from_current = [
            estimate.anchor_dx_m,
            estimate.anchor_dy_m,
            estimate.anchor_dtheta_rad,
        ]
        current_pose_from_source = inverse_delta(source_pose_from_current)
        current_pose_from_start = compose_pose(source_anchor.pose_from_start, current_pose_from_source)
        target_pose_from_current = relative_delta(current_pose_from_start, target_anchor.pose_from_start)
        backend = estimate.backend
        if not backend.endswith("+monotonic"):
            backend = f"{backend}+monotonic"
        return replace(
            estimate,
            anchor_index=int(target_anchor.index),
            anchor_dx_m=float(target_pose_from_current[0]),
            anchor_dy_m=float(target_pose_from_current[1]),
            anchor_dtheta_rad=float(target_pose_from_current[2]),
            backend=backend,
        )

    def _action_integrated_progress(self) -> RelativeStartProgress:
        current_pose = compose_pose(self._return_start_pose_from_start, self._return_pose_from_return_start)
        target_delta = relative_delta(current_pose, [0.0, 0.0, 0.0])
        dx, dy, _ = target_delta
        distance = float(math.hypot(dx, dy))
        bearing = math.degrees(math.atan2(dy, dx)) if distance > 1e-6 else 0.0
        return RelativeStartProgress(
            target_dx_m=float(dx),
            target_dy_m=float(dy),
            distance_to_start_m=distance,
            bearing_to_start_deg=float(bearing),
            current_pose_from_start=[float(x) for x in current_pose],
            return_pose_from_return_start=[float(x) for x in self._return_pose_from_return_start],
            return_start_pose_from_start=[float(x) for x in self._return_start_pose_from_start],
        )

    def _relocalization_consistency_error(self, estimate: AnchorRelocalization) -> Optional[float]:
        if estimate.backend == "oracle_anchor" or self.max_relocalization_consistency_error_m <= 0.0:
            return None
        if not estimate.anchor_heading_reliable:
            return None
        anchor_progress = self._anchor_progress_from_estimate(estimate)
        if anchor_progress is None:
            return None
        integrated_progress = self._action_integrated_progress()
        error = math.hypot(
            anchor_progress.target_dx_m - integrated_progress.target_dx_m,
            anchor_progress.target_dy_m - integrated_progress.target_dy_m,
        )
        if error <= self.max_relocalization_consistency_error_m:
            return None
        return float(error)

    def _anchor_progress_from_estimate(self, estimate: AnchorRelocalization) -> Optional[RelativeStartProgress]:
        anchor = self._anchor_by_index(estimate.anchor_index)
        if anchor is None:
            return None
        integrated_progress = self._action_integrated_progress()
        if estimate.anchor_heading_reliable:
            anchor_to_start = relative_delta(anchor.pose_from_start, [0.0, 0.0, 0.0])
            anchor_pose_from_current = [estimate.anchor_dx_m, estimate.anchor_dy_m, estimate.anchor_dtheta_rad]
            start_pose_from_current = compose_pose(anchor_pose_from_current, anchor_to_start)
            dx, dy, _ = start_pose_from_current
        else:
            dx = integrated_progress.target_dx_m
            dy = integrated_progress.target_dy_m
        distance_to_start = float(estimate.distance_to_anchor_m + anchor.route_remaining_to_start_m)
        bearing_to_start = float(math.degrees(math.atan2(dy, dx))) if distance_to_start > 1e-6 else 0.0
        return RelativeStartProgress(
            target_dx_m=float(dx),
            target_dy_m=float(dy),
            distance_to_start_m=distance_to_start,
            bearing_to_start_deg=bearing_to_start,
            current_pose_from_start=[float(x) for x in integrated_progress.current_pose_from_start],
            return_pose_from_return_start=[float(x) for x in self._return_pose_from_return_start],
            return_start_pose_from_start=[float(x) for x in self._return_start_pose_from_start],
            source="anchor_relocalization",
            target_anchor_index=int(anchor.index),
            anchor_dx_m=float(estimate.anchor_dx_m),
            anchor_dy_m=float(estimate.anchor_dy_m),
            distance_to_anchor_m=estimate.distance_to_anchor_m,
            bearing_to_anchor_deg=estimate.bearing_to_anchor_deg,
            anchor_route_remaining_m=float(anchor.route_remaining_to_start_m),
            anchor_heading_reliable=bool(estimate.anchor_heading_reliable),
            relocalization_confidence=float(estimate.confidence),
            relocalization_backend=estimate.backend,
        )

    def _anchor_progress(self) -> Optional[RelativeStartProgress]:
        estimate = self._latest_relocalization
        if estimate is None:
            return None
        return self._anchor_progress_from_estimate(estimate)

    def _make_anchor_hint(self, progress: RelativeStartProgress) -> str:
        assert progress.target_anchor_index is not None
        anchor_distance = progress.distance_to_anchor_m or 0.0
        anchor_bearing = progress.bearing_to_anchor_deg or 0.0
        if anchor_distance < 0.35:
            anchor_direction = "at your current position"
        elif abs(anchor_bearing) <= 10.0:
            anchor_direction = "ahead"
        elif anchor_bearing > 0.0:
            anchor_direction = f"{abs(anchor_bearing):.0f} deg to your left"
        else:
            anchor_direction = f"{abs(anchor_bearing):.0f} deg to your right"
        remaining = (
            anchor_distance + (progress.anchor_route_remaining_m or 0.0)
            if progress.anchor_route_remaining_m is not None else progress.distance_to_start_m
        )
        vector_label = "odometry start vector" if progress.anchor_heading_reliable is False else "start vector"
        if self.hint_mode == "verbose":
            return (
                "[System Hint: Route memory matched outbound anchor "
                f"A{progress.target_anchor_index}. The anchor is estimated {anchor_distance:.2f} m away, "
                f"{anchor_direction}, from map-free relocalization. The {vector_label} is estimated "
                f"{progress.distance_to_start_m:.2f} m away in body-frame coordinates "
                f"dx={progress.target_dx_m:.2f} m forward, dy={progress.target_dy_m:.2f} m left. "
                f"Approximate remaining route distance through that anchor is {remaining:.2f} m. "
                "Move toward the anchor when it is visually consistent, then continue retracing toward the start.]"
            )
        return (
            "[System Hint: route anchor "
            f"A{progress.target_anchor_index} is {anchor_distance:.2f} m away, {anchor_direction}; "
            f"estimated remaining route via anchor is {remaining:.2f} m; "
            f"{vector_label} dx={progress.target_dx_m:.2f} m, dy={progress.target_dy_m:.2f} m.]"
        )
