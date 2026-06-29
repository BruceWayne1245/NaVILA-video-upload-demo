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
    filter_std_m: Optional[float] = None
    oracle_route_current_s_m: Optional[float] = None
    oracle_route_target_s_m: Optional[float] = None
    oracle_route_lookahead_m: Optional[float] = None


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
class SequenceArcObservation:
    observed_s_m: float
    confidence: float
    sigma_m: float
    anchor_index: int
    backend: str
    source: str
    selected_score: float
    candidate_count: int
    expected_s_m: Optional[float] = None
    motion_error_m: Optional[float] = None


@dataclass
class ArcLengthParticleFilter:
    """One-dimensional Bayesian filter over route distance remaining to start."""

    total_length_m: float
    particle_count: int = 256
    process_noise_m: float = 0.20
    resample_uniform_mix: float = 0.02
    particles: list[float] = field(default_factory=list)
    weights: list[float] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.total_length_m = max(0.0, float(self.total_length_m))
        self.particle_count = max(8, int(self.particle_count))
        if not self.particles:
            if self.particle_count == 1:
                self.particles = [self.total_length_m]
            else:
                step = self.total_length_m / float(self.particle_count - 1)
                self.particles = [i * step for i in range(self.particle_count)]
        if not self.weights:
            sigma = max(0.35, self.process_noise_m * 2.0)
            self.weights = [
                math.exp(-0.5 * ((p - self.total_length_m) / sigma) ** 2)
                for p in self.particles
            ]
            self._normalize()

    def std(self) -> float:
        mean = self.estimate()
        variance = sum(w * ((p - mean) ** 2) for p, w in zip(self.particles, self.weights))
        return float(math.sqrt(max(0.0, variance)))

    def predict(self, travel_distance_m: float, extra_process_noise_m: float = 0.0) -> None:
        travel = max(0.0, float(travel_distance_m))
        extra = max(0.0, float(extra_process_noise_m))
        if travel <= 1e-9 and extra <= 1e-9:
            return
        sigma = max(0.05, self.process_noise_m + 0.08 * travel + extra)
        inv_two_sigma2 = 1.0 / (2.0 * sigma * sigma)
        predicted = [0.0 for _ in self.particles]
        for prev_s, prev_w in zip(self.particles, self.weights):
            if prev_w <= 0.0:
                continue
            expected_s = max(0.0, prev_s - travel)
            for j, new_s in enumerate(self.particles):
                if new_s > prev_s + sigma:
                    continue
                error = new_s - expected_s
                predicted[j] += prev_w * math.exp(-(error * error) * inv_two_sigma2)
        self.weights = predicted
        self._normalize()

    def observe(self, observed_s_m: float, confidence: float = 1.0, sigma_m: float = 1.0) -> None:
        observed_s = min(self.total_length_m, max(0.0, float(observed_s_m)))
        confidence = min(1.0, max(0.0, float(confidence)))
        if confidence <= 0.0:
            return
        sigma = max(0.25, float(sigma_m))
        inv_two_sigma2 = 1.0 / (2.0 * sigma * sigma)
        floor = max(0.0, 1.0 - confidence)
        self.weights = [
            w * (floor + confidence * math.exp(-((p - observed_s) ** 2) * inv_two_sigma2))
            for p, w in zip(self.particles, self.weights)
        ]
        self._normalize()

    def estimate(self) -> float:
        return float(sum(p * w for p, w in zip(self.particles, self.weights)))

    def confidence(self) -> float:
        mean = self.estimate()
        variance = sum(w * ((p - mean) ** 2) for p, w in zip(self.particles, self.weights))
        sigma = math.sqrt(max(0.0, variance))
        scale = max(0.5, self.total_length_m * 0.25)
        return float(1.0 / (1.0 + sigma / scale))

    def summary(self) -> dict:
        mean = self.estimate()
        variance = sum(w * ((p - mean) ** 2) for p, w in zip(self.particles, self.weights))
        max_i = max(range(len(self.weights)), key=lambda i: self.weights[i])
        return {
            "total_length_m": float(self.total_length_m),
            "particle_count": int(self.particle_count),
            "mean_remaining_m": float(mean),
            "mode_remaining_m": float(self.particles[max_i]),
            "std_remaining_m": float(math.sqrt(max(0.0, variance))),
            "confidence": self.confidence(),
        }

    def _normalize(self) -> None:
        total = float(sum(self.weights))
        if not math.isfinite(total) or total <= 0.0:
            self.weights = [1.0 / len(self.particles) for _ in self.particles]
            return
        uniform = 1.0 / len(self.weights)
        mix = min(0.25, max(0.0, self.resample_uniform_mix))
        self.weights = [
            (1.0 - mix) * (w / total) + mix * uniform
            for w in self.weights
        ]


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
        self._arc_length_filter: Optional[ArcLengthParticleFilter] = None
        self._arc_observation: Optional[dict] = None
        self._sequence_observation: Optional[SequenceArcObservation] = None
        self._sequence_observation_history: list[dict] = []
        self._distance_since_sequence_observation_m = 0.0
        self._sequence_current_s_m: Optional[float] = None
        self.sequence_window = 8
        self.sequence_motion_sigma_m = 1.0
        self.sequence_forward_tolerance_m = 0.4
        self.sequence_max_anchor_distance_m = max(6.0, 4.0 * self.anchor_spacing_m)
        self._target_anchor_index: Optional[int] = None
        self._target_anchor_min_distance_m: Optional[float] = None
        self.anchor_pass_radius_m = 0.8
        self.anchor_pass_hysteresis_m = 0.6
        self.anchor_pass_max_min_distance_m = max(2.0 * self.anchor_spacing_m, self.anchor_pass_radius_m)
        self._return_update_count = 0
        # VIO bridge: suppress visual observations in the corridor dead zone;
        # only accept updates when the filter is confident OR near a path feature
        # (a turn or doorway where geometry disambiguates position along the route).
        self.vio_bridge_enabled: bool = False
        self.vio_bridge_std_threshold_m: float = 2.5
        self.vio_bridge_feature_radius_m: float = 2.0
        self._feature_anchor_indices: set = set()
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
        dx, dy, _ = [float(v) for v in delta]
        # Project onto forward/backward axis only — lateral (dy) motion is not arc progress.
        forward_distance = abs(float(dx))
        if self._arc_length_filter is not None:
            # Accelerate uncertainty inflation proportionally to observation gap.
            blackout_m = self._distance_since_sequence_observation_m
            extra_noise = max(0.0, (blackout_m - 3.0) * 0.015) if blackout_m > 3.0 else 0.0
            self._arc_length_filter.predict(forward_distance, extra_process_noise_m=extra_noise)
        if self._sequence_current_s_m is not None:
            self._sequence_current_s_m = max(0.0, self._sequence_current_s_m - forward_distance)
        self._distance_since_sequence_observation_m += forward_distance
        self._propagate_latest_relocalization(delta)
        self._return_update_count += 1
        self.update_relocalization(local_descriptor=local_descriptor, relocalization=relocalization)

    def finalize_outbound(self) -> None:
        if self.enabled and (not self.anchors or self.anchors[-1].distance_from_start_m < self._outbound_distance_m):
            self._append_anchor(descriptor=None, metadata={"event": "outbound_final"})
        self._finalize_anchor_route_lengths()
        self._return_start_pose_from_start = list(self._outbound_pose_from_start)
        self._return_pose_from_return_start = [0.0, 0.0, 0.0]
        self._arc_length_filter = ArcLengthParticleFilter(total_length_m=self._outbound_distance_m)
        self._arc_observation = None
        self._sequence_observation = None
        self._sequence_observation_history = []
        self._distance_since_sequence_observation_m = 0.0
        self._sequence_current_s_m = None
        self._return_started = True
        self._compute_feature_anchors()

    def _compute_feature_anchors(self, heading_change_threshold_deg: float = 15.0) -> None:
        """Mark anchors where the outbound path turns sharply (corners / doorways).
        These positions have geometry that disambiguates arc-length, so the VIO
        bridge allows visual observations only near them when the filter is uncertain.
        """
        self._feature_anchor_indices = set()
        threshold_rad = math.radians(heading_change_threshold_deg)
        for i in range(1, len(self.anchors)):
            prev = self.anchors[i - 1]
            curr = self.anchors[i]
            if prev.pose_from_start is None or curr.pose_from_start is None:
                continue
            dtheta = abs(wrap_angle(curr.pose_from_start[2] - prev.pose_from_start[2]))
            if dtheta > threshold_rad:
                self._feature_anchor_indices.add(prev.index)
                self._feature_anchor_indices.add(curr.index)

    def _is_near_feature_anchor(self, arc_length_s_m: float) -> bool:
        """Return True if ``arc_length_s_m`` is within ``vio_bridge_feature_radius_m``
        of any feature anchor (path corner / doorway)."""
        for idx in self._feature_anchor_indices:
            anchor = self._anchor_by_index(idx)
            if anchor is None:
                continue
            if abs(anchor.distance_from_start_m - arc_length_s_m) <= self.vio_bridge_feature_radius_m:
                return True
        return False

    def update_relocalization(
        self,
        local_descriptor: Optional[object] = None,
        relocalization: Optional[AnchorRelocalization | dict] = None,
    ) -> Optional[AnchorRelocalization]:
        if not self.enabled or not self._return_started:
            return None
        estimates = self._coerce_relocalizations(relocalization)
        if not estimates and self.relocalizer is not None:
            if self._return_update_count % self.relocalization_interval_updates != 0:
                return None
            estimates = self._coerce_relocalizations(
                self.relocalizer(local_descriptor, self.anchors)
            )
        estimates = [
            estimate for estimate in estimates
            if estimate.confidence >= self.min_relocalization_confidence
            and self._anchor_by_index(estimate.anchor_index) is not None
        ]
        if not estimates:
            return None

        estimate, observation, reject_reason = self._sequence_match_observation(estimates)
        if estimate is None:
            self.relocalization_events.append({
                "accepted": False,
                "reject_reason": reject_reason,
                "candidate_count": len(estimates),
                "sequence_observation": (
                    asdict(self._sequence_observation)
                    if self._sequence_observation is not None else None
                ),
            })
            return None

        self._latest_relocalization = estimate
        self._update_arc_filter_from_sequence(observation)
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
            "candidate_count": len(estimates),
            "sequence_observation": asdict(observation),
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
        arc_progress = self._arc_length_progress()
        if arc_progress is not None:
            return arc_progress
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
        if progress.distance_to_start_m < 0.35 and self._filter_lost(progress):
            # Filter has lost lock — do not claim arrival.
            std = progress.filter_std_m or 0.0
            return (
                f"[System Hint: position uncertain (σ≈{std:.1f} m, filter lost lock); "
                "continue toward the outbound start using the visual instruction — "
                "do NOT stop until you visually confirm you are back at the starting location.]"
            )
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
            "arc_length_filter": (
                self._arc_length_filter.summary()
                if self._arc_length_filter is not None else None
            ),
            "arc_length_observation": self._arc_observation,
            "sequence_observation": (
                asdict(self._sequence_observation)
                if self._sequence_observation is not None else None
            ),
            "sequence_current_s_m": self._sequence_current_s_m,
            "sequence_observation_history": list(self._sequence_observation_history),
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

    def _coerce_relocalizations(self, relocalization: object) -> list[AnchorRelocalization]:
        if relocalization is None:
            return []
        if isinstance(relocalization, (list, tuple)):
            estimates = []
            for item in relocalization:
                estimate = self._coerce_relocalization(item)
                if estimate is not None:
                    estimates.append(estimate)
            return estimates
        estimate = self._coerce_relocalization(relocalization)  # type: ignore[arg-type]
        return [estimate] if estimate is not None else []

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

    def _estimate_arc_observation(
        self,
        estimate: AnchorRelocalization,
    ) -> Optional[SequenceArcObservation]:
        anchor = self._anchor_by_index(estimate.anchor_index)
        if anchor is None:
            return None
        if estimate.anchor_heading_reliable:
            anchor_pose_from_current = [
                estimate.anchor_dx_m,
                estimate.anchor_dy_m,
                estimate.anchor_dtheta_rad,
            ]
            current_pose_from_anchor = inverse_delta(anchor_pose_from_current)
            current_pose_from_start = compose_pose(anchor.pose_from_start, current_pose_from_anchor)
            observed_s = self._project_pose_to_route_distance(current_pose_from_start)
            sigma = max(0.45, min(2.0, estimate.distance_to_anchor_m + 0.5 * self.anchor_spacing_m))
            source = "seqslam_pose_projection"
        else:
            observed_s = float(anchor.distance_from_start_m)
            sigma = max(1.5, estimate.distance_to_anchor_m + 2.0 * self.anchor_spacing_m)
            source = "seqslam_anchor_similarity"
        confidence = max(
            0.05,
            min(1.0, (estimate.confidence - self.min_relocalization_confidence) /
                max(1e-6, 1.0 - self.min_relocalization_confidence)),
        )
        return SequenceArcObservation(
            observed_s_m=float(observed_s),
            confidence=float(confidence),
            sigma_m=float(sigma),
            anchor_index=int(anchor.index),
            backend=estimate.backend,
            source=source,
            selected_score=0.0,
            candidate_count=1,
        )

    def _sequence_match_observation(
        self,
        estimates: list[AnchorRelocalization],
    ) -> tuple[Optional[AnchorRelocalization], Optional[SequenceArcObservation], Optional[str]]:
        candidates: list[tuple[float, AnchorRelocalization, SequenceArcObservation]] = []
        if self._sequence_observation is not None:
            expected_s = max(
                0.0,
                self._sequence_observation.observed_s_m - self._distance_since_sequence_observation_m,
            )
        else:
            expected_s = None

        for estimate in estimates:
            if estimate.distance_to_anchor_m > self.sequence_max_anchor_distance_m:
                continue
            observation = self._estimate_arc_observation(estimate)
            if observation is None:
                continue
            motion_error = 0.0 if expected_s is None else observation.observed_s_m - expected_s
            if self._sequence_observation is not None and motion_error > self.sequence_forward_tolerance_m:
                continue
            monotonic_penalty = 1.0
            abs_motion_error = 0.0 if expected_s is None else abs(motion_error)
            continuity = math.exp(
                -(abs_motion_error ** 2)
                / (2.0 * max(0.25, self.sequence_motion_sigma_m) ** 2)
            )
            inlier_bonus = math.sqrt(max(1, int(estimate.inlier_count or 1))) / math.sqrt(30.0)
            score = observation.confidence * continuity * monotonic_penalty * inlier_bonus
            observation.expected_s_m = None if expected_s is None else float(expected_s)
            observation.motion_error_m = None if expected_s is None else float(motion_error)
            observation.selected_score = float(score)
            observation.candidate_count = len(estimates)
            candidates.append((score, estimate, observation))

        if not candidates:
            return None, None, "no_sequence_candidates"
        candidates.sort(key=lambda item: item[0], reverse=True)
        score, estimate, observation = candidates[0]
        min_score = 0.02 if self._sequence_observation is None else 0.005
        if score < min_score:
            return None, None, "sequence_candidate_score_too_low"

        # VIO bridge: in the corridor dead zone the arc-length position is ambiguous.
        # If the filter is uncertain AND the candidate lands away from a feature anchor
        # (corner, doorway), reject the visual update and rely on dead reckoning instead.
        if (
            self.vio_bridge_enabled
            and self._arc_length_filter is not None
            and self._arc_length_filter.std() > self.vio_bridge_std_threshold_m
            and not self._is_near_feature_anchor(observation.observed_s_m)
        ):
            return None, None, "vio_bridge_suppressed"

        self._sequence_observation = observation
        self._sequence_current_s_m = float(observation.observed_s_m)
        self._sequence_observation_history.append(asdict(observation))
        if len(self._sequence_observation_history) > self.sequence_window:
            self._sequence_observation_history = self._sequence_observation_history[-self.sequence_window:]
        self._distance_since_sequence_observation_m = 0.0
        self._target_anchor_index = int(observation.anchor_index)
        self._target_anchor_min_distance_m = estimate.distance_to_anchor_m
        return estimate, observation, None

    def _update_arc_filter_from_sequence(self, observation: SequenceArcObservation) -> None:
        if self._arc_length_filter is None:
            return
        self._arc_length_filter.observe(
            observation.observed_s_m,
            confidence=observation.confidence,
            sigma_m=observation.sigma_m,
        )
        self._arc_observation = asdict(observation)

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

    def _update_arc_filter_observation(self, estimate: AnchorRelocalization) -> None:
        if self._arc_length_filter is None:
            return
        anchor = self._anchor_by_index(estimate.anchor_index)
        if anchor is None:
            return

        if estimate.anchor_heading_reliable:
            anchor_pose_from_current = [
                estimate.anchor_dx_m,
                estimate.anchor_dy_m,
                estimate.anchor_dtheta_rad,
            ]
            current_pose_from_anchor = inverse_delta(anchor_pose_from_current)
            current_pose_from_start = compose_pose(anchor.pose_from_start, current_pose_from_anchor)
            observed_s = self._project_pose_to_route_distance(current_pose_from_start)
            sigma = max(0.45, min(2.0, estimate.distance_to_anchor_m + 0.5 * self.anchor_spacing_m))
            source = "pose_projection"
        else:
            observed_s = float(anchor.distance_from_start_m)
            sigma = max(1.5, estimate.distance_to_anchor_m + 2.0 * self.anchor_spacing_m)
            source = "anchor_similarity"

        confidence = max(
            0.05,
            min(1.0, (estimate.confidence - self.min_relocalization_confidence) /
                max(1e-6, 1.0 - self.min_relocalization_confidence)),
        )
        self._arc_length_filter.observe(observed_s, confidence=confidence, sigma_m=sigma)
        self._arc_observation = {
            "source": source,
            "anchor_index": int(anchor.index),
            "observed_remaining_m": float(observed_s),
            "sigma_m": float(sigma),
            "confidence": float(confidence),
        }

    def _project_pose_to_route_distance(self, pose_from_start: Iterable[float]) -> float:
        px, py, _ = [float(v) for v in pose_from_start]
        if not self.anchors:
            return 0.0
        if len(self.anchors) == 1:
            return float(self.anchors[0].distance_from_start_m)

        best_distance2 = float("inf")
        best_route_distance = 0.0
        for a, b in zip(self.anchors[:-1], self.anchors[1:]):
            ax, ay, _ = a.pose_from_start
            bx, by, _ = b.pose_from_start
            vx = bx - ax
            vy = by - ay
            segment_len2 = vx * vx + vy * vy
            if segment_len2 <= 1e-9:
                t = 0.0
            else:
                t = ((px - ax) * vx + (py - ay) * vy) / segment_len2
                t = max(0.0, min(1.0, t))
            cx = ax + t * vx
            cy = ay + t * vy
            distance2 = (px - cx) ** 2 + (py - cy) ** 2
            route_distance = (
                a.distance_from_start_m
                + t * (b.distance_from_start_m - a.distance_from_start_m)
            )
            if distance2 < best_distance2:
                best_distance2 = distance2
                best_route_distance = route_distance
        return float(max(0.0, min(self._outbound_distance_m, best_route_distance)))

    def _target_anchor_for_remaining_distance(self, remaining_m: float) -> Optional[RouteAnchor]:
        if not self.anchors:
            return None
        eligible = [
            anchor for anchor in self.anchors
            if anchor.distance_from_start_m <= remaining_m + 1e-6
        ]
        if eligible:
            return max(eligible, key=lambda anchor: anchor.distance_from_start_m)
        return self.anchors[0]

    def _arc_length_progress(self) -> Optional[RelativeStartProgress]:
        if self._arc_length_filter is None:
            return None
        if self._arc_observation is None:
            return None
        integrated_progress = self._action_integrated_progress()
        remaining = (
            self._sequence_current_s_m
            if self._sequence_current_s_m is not None
            else self._arc_length_filter.estimate()
        )
        target_anchor = self._target_anchor_for_remaining_distance(remaining)

        estimate = self._latest_relocalization
        dx = integrated_progress.target_dx_m
        dy = integrated_progress.target_dy_m
        if estimate is not None and estimate.anchor_heading_reliable:
            anchor = self._anchor_by_index(estimate.anchor_index)
            if anchor is not None:
                anchor_to_start = relative_delta(anchor.pose_from_start, [0.0, 0.0, 0.0])
                anchor_pose_from_current = [
                    estimate.anchor_dx_m,
                    estimate.anchor_dy_m,
                    estimate.anchor_dtheta_rad,
                ]
                start_pose_from_current = compose_pose(anchor_pose_from_current, anchor_to_start)
                dx, dy, _ = start_pose_from_current

        bearing = float(math.degrees(math.atan2(dy, dx))) if remaining > 1e-6 else 0.0
        anchor_dx = None
        anchor_dy = None
        distance_to_anchor = None
        bearing_to_anchor = None
        anchor_heading_reliable = None
        relocalization_backend = None
        filter_std_m = self._arc_length_filter.std()
        relocalization_confidence = self._arc_length_filter.confidence()
        if self._sequence_observation is not None:
            odom_decay = math.exp(-self._distance_since_sequence_observation_m / 5.0)
            relocalization_confidence = min(
                relocalization_confidence,
                self._sequence_observation.confidence * odom_decay,
            )
        if estimate is not None:
            relocalization_backend = estimate.backend
            anchor_heading_reliable = bool(estimate.anchor_heading_reliable)
        if target_anchor is not None:
            if estimate is not None and estimate.anchor_index == target_anchor.index:
                anchor_dx = float(estimate.anchor_dx_m)
                anchor_dy = float(estimate.anchor_dy_m)
                distance_to_anchor = estimate.distance_to_anchor_m
                bearing_to_anchor = estimate.bearing_to_anchor_deg
            else:
                along_route_gap = max(0.0, remaining - target_anchor.distance_from_start_m)
                distance_to_anchor = float(along_route_gap)
                bearing_to_anchor = 0.0

        return RelativeStartProgress(
            target_dx_m=float(dx),
            target_dy_m=float(dy),
            distance_to_start_m=float(remaining),
            bearing_to_start_deg=bearing,
            current_pose_from_start=[float(x) for x in integrated_progress.current_pose_from_start],
            return_pose_from_return_start=[float(x) for x in self._return_pose_from_return_start],
            return_start_pose_from_start=[float(x) for x in self._return_start_pose_from_start],
            source="arc_length_particle_filter",
            target_anchor_index=int(target_anchor.index) if target_anchor is not None else None,
            anchor_dx_m=anchor_dx,
            anchor_dy_m=anchor_dy,
            distance_to_anchor_m=distance_to_anchor,
            bearing_to_anchor_deg=bearing_to_anchor,
            anchor_route_remaining_m=(
                float(target_anchor.route_remaining_to_start_m)
                if target_anchor is not None else None
            ),
            anchor_heading_reliable=anchor_heading_reliable,
            relocalization_confidence=float(relocalization_confidence),
            relocalization_backend=relocalization_backend,
            filter_std_m=float(filter_std_m),
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

    def _filter_lost(self, progress: RelativeStartProgress) -> bool:
        if progress.filter_std_m is None:
            return False
        route_len = (
            self._arc_length_filter.total_length_m
            if self._arc_length_filter is not None else 10.0
        )
        threshold = max(2.5, 0.20 * route_len)
        return progress.filter_std_m > threshold

    def _make_anchor_hint(self, progress: RelativeStartProgress) -> str:
        assert progress.target_anchor_index is not None
        anchor_distance = progress.distance_to_anchor_m or 0.0
        anchor_bearing = progress.bearing_to_anchor_deg or 0.0
        remaining = (
            anchor_distance + (progress.anchor_route_remaining_m or 0.0)
            if progress.anchor_route_remaining_m is not None else progress.distance_to_start_m
        )
        if progress.source == "direct_oracle_route_anchor":
            vector_label = "next-anchor vector"
        else:
            vector_label = "odometry start vector" if progress.anchor_heading_reliable is False else "start vector"

        # When the particle filter has lost lock (high std), suppress arrival claims.
        if self._filter_lost(progress):
            std = progress.filter_std_m or 0.0
            if abs(progress.target_dx_m) < 1e-6 and abs(progress.target_dy_m) < 1e-6:
                direction_clause = ""
            else:
                bearing = float(math.degrees(math.atan2(progress.target_dy_m, progress.target_dx_m)))
                if abs(bearing) <= 10.0:
                    direction_clause = f"; {vector_label} points ahead"
                elif bearing > 0.0:
                    direction_clause = f"; {vector_label} points {abs(bearing):.0f} deg to your left"
                else:
                    direction_clause = f"; {vector_label} points {abs(bearing):.0f} deg to your right"
            return (
                f"[System Hint: position uncertain (σ≈{std:.1f} m, filter lost lock); "
                f"route anchor A{progress.target_anchor_index} is near but position estimate unreliable"
                f"{direction_clause}. "
                "Continue toward the outbound start using the visual instruction — do NOT stop until you visually confirm you are back at the starting location.]"
            )

        if anchor_distance < 0.35:
            anchor_direction = "at your current position"
        elif abs(anchor_bearing) <= 10.0:
            anchor_direction = "ahead"
        elif anchor_bearing > 0.0:
            anchor_direction = f"{abs(anchor_bearing):.0f} deg to your left"
        else:
            anchor_direction = f"{abs(anchor_bearing):.0f} deg to your right"
        if self.hint_mode == "verbose":
            vector_distance = (
                anchor_distance
                if progress.source == "direct_oracle_route_anchor"
                else progress.distance_to_start_m
            )
            return (
                "[System Hint: Route memory matched outbound anchor "
                f"A{progress.target_anchor_index}. The anchor is estimated {anchor_distance:.2f} m away, "
                f"{anchor_direction}, from map-free relocalization. The {vector_label} is estimated "
                f"{vector_distance:.2f} m away in body-frame coordinates "
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
