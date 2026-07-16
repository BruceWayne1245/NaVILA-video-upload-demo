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

import numpy as np


def wrap_angle(angle: float) -> float:
    return math.atan2(math.sin(angle), math.cos(angle))


DIAGNOSTIC_FRAME_FRACTIONS_REMAINING: tuple[float, ...] = (0.75, 0.5, 0.25, 0.05)
"""Fixed fractions of return-journey progress remaining at which
round_trip_eval.py's --capture_route_memory_diagnostic_frames captures a full
diagnostic frame (occupancy overview + clean local maps + current-vs-every-
anchor match). Tied to route progress rather than step count or
relocalization_interval_updates so the number of captured frames stays ~4 per
episode regardless of episode length or how often relocalization runs."""


def diagnostic_frame_thresholds_to_fire(
    fraction_remaining: float,
    already_fired: Iterable[float],
    thresholds: Iterable[float] = DIAGNOSTIC_FRAME_FRACTIONS_REMAINING,
) -> list[float]:
    """Which threshold(s) in ``thresholds`` does ``fraction_remaining`` newly
    cross (i.e. fall at-or-below), that aren't already in ``already_fired``?

    Pure function so the sampling logic is unit-testable without Isaac Sim;
    round_trip_eval.py owns the actual capture side effect and threshold
    bookkeeping (accumulating fired thresholds into a set across steps).
    """
    already_fired = set(already_fired)
    return [t for t in thresholds if t not in already_fired and fraction_remaining <= t]


def circular_weighted_mean(pairs: Iterable[tuple[float, float]]) -> Optional[float]:
    """Confidence-weighted circular mean of (angle_rad, weight) pairs.

    Ordinary weighted averaging of angles breaks across the +/-pi wraparound
    (e.g. mean of -179 deg and +179 deg should be 180 deg, not 0 deg); summing
    on the unit circle and taking atan2 of the resultant handles this correctly.
    """
    sin_sum = 0.0
    cos_sum = 0.0
    weight_sum = 0.0
    for angle, weight in pairs:
        if weight <= 0.0:
            continue
        sin_sum += weight * math.sin(angle)
        cos_sum += weight * math.cos(angle)
        weight_sum += weight
    if weight_sum <= 1e-9:
        return None
    return math.atan2(sin_sum, cos_sum)


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


def world_pose_7_to_2d(world_pose: Iterable[float]) -> list[float]:
    """Convert a 7-vector ``[x, y, z, qw, qx, qy, qz]`` (as captured into
    RouteAnchor.metadata["world_pose"] via isaac_oracle_for_relocalization_eval)
    into a planar ``[x, y, yaw]`` pose, discarding height/roll/pitch."""
    x, y, _z, qw, qx, qy, qz = [float(v) for v in world_pose]
    yaw = math.atan2(2.0 * (qw * qz + qx * qy), 1.0 - 2.0 * (qy * qy + qz * qz))
    return [x, y, yaw]


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
    # Relative-edge pose graph (2026-07-02): the body-frame delta from the
    # previous anchor to this one, recorded once at creation time. Reprojecting
    # between two nearby anchors should compose only the short chain of these
    # edges between them (see RouteMemoryAgent._compose_edges_between), not
    # difference their two pose_from_start values -- the latter each carry the
    # FULL outbound dead-reckoning drift accumulated from anchor 0, so
    # differencing two long chains does not cancel that drift, it compounds it.
    # pose_from_start is kept only for the few queries that inherently need a
    # literal distance to the route start (see _anchor_progress_from_estimate).
    edge_from_previous: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])
    # Anchor-distinctiveness precompute (2026-07-06, see
    # RouteMemoryAgent.compute_anchor_alias_scores): best ICP overlap this
    # anchor achieves against any other non-adjacent anchor on the route.
    # None until compute_anchor_alias_scores() has been run.
    alias_score: Optional[float] = None


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
    degeneracy_ratio: Optional[float] = None
    # 2026-07-07 (ICP bearing-error investigation): the sequential_pair backend
    # already computes match_class/near_tie_basin_count per candidate
    # (relocalization.py) but previously discarded them once past the
    # strict-mode reject check -- carried through here so closure-check's
    # trust-aware guard (see _sequential_pair_closure_precheck) can tell which
    # side of a current/next disagreement is actually trustworthy instead of
    # only using the confidence*sqrt(inlier_count) quality score, which is
    # known to saturate near 1.0 even for anchors match_class already flags
    # as degenerate/ambiguous.
    match_class: Optional[str] = None
    near_tie_basin_count: Optional[int] = None
    # 2026-07-15 (current+next simultaneous-failure investigation,
    # investigations/2026-07-15-50ep-batch-current-next-simultaneous-failure):
    # ratio of the second-best-scoring ICP yaw-seed hypothesis to the best one,
    # from the same single attempt's own 24-seed sweep (relocalization.py's
    # icp_seed_sweep_2d/basin_metrics) -- a per-attempt, live ambiguity signal,
    # NOT a precomputed cross-anchor similarity like alias_score. Tested against
    # this project's own 50-episode batch data: mean value over a "next"
    # candidate's whole dwell separates known-bad stuck anchors from legitimate
    # slow-but-fine ones far better than raw attempt-count or promotion-vote
    # pass-fraction did (both of those were tested and found not to separate
    # at all). See quarantine_next_quality_enabled for the consumer.
    best_to_second_score_ratio: Optional[float] = None

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

    def seed(self, observed_s_m: float, confidence: float = 1.0, sigma_m: float = 0.35) -> None:
        observed_s = min(self.total_length_m, max(0.0, float(observed_s_m)))
        confidence = min(1.0, max(0.0, float(confidence)))
        sigma = max(0.10, float(sigma_m))
        inv_two_sigma2 = 1.0 / (2.0 * sigma * sigma)
        floor = max(0.0, 1.0 - confidence)
        self.weights = [
            floor + confidence * math.exp(-((p - observed_s) ** 2) * inv_two_sigma2)
            for p in self.particles
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
        route_progress_lookahead_m: Optional[float] = None,
        relocalizer: Optional[Callable[[object, list[RouteAnchor]], Optional[AnchorRelocalization]]] = None,
        sequential_pair_geometry_source: str = "accumulated",
        sequential_pair_closure_check_enabled: bool = False,
        sequential_pair_closure_mode: str = "threshold",
        sequential_pair_closure_max_position_disagreement_m: float = 0.75,
        sequential_pair_closure_max_heading_disagreement_rad: float = math.radians(30.0),
        sequential_pair_closure_belief_trust_aware_guard: bool = False,
        sequential_pair_closure_belief_large_position_disagreement_m: float = 1.5,
        sequential_pair_closure_belief_large_heading_disagreement_rad: float = math.radians(90.0),
        sequential_pair_quarantine_enabled: bool = False,
        sequential_pair_quarantine_mode: str = "window",
        sequential_pair_promotion_mode: str = "immediate",
        sequential_pair_promotion_window: int = 5,
        sequential_pair_promotion_min_votes: int = 3,
        sequential_pair_promotion_alias_aware: bool = False,
        sequential_pair_promotion_alias_threshold: float = 0.6,
        sequential_pair_promotion_alias_window: int = 8,
        sequential_pair_promotion_alias_min_votes: int = 5,
        sequential_pair_promotion_alias_stall_attempts: int = 200,
        sequential_pair_promotion_use_pre_closure_estimates: bool = False,
        sequential_pair_short_baseline_disambiguation: bool = False,
        sequential_pair_short_baseline_min_travel_m: float = 0.3,
        sequential_pair_short_baseline_max_rotation_disagreement_deg: float = 20.0,
        sequential_pair_short_baseline_require_resolution: bool = False,
        sequential_pair_short_baseline_stall_attempts: int = 60,
        sequential_pair_disable_temporal_smoothing: bool = False,
        sequential_pair_closure_reconciliation_signal: str = "dtheta",
        quarantine_window_size: int = 6,
        quarantine_min_samples: int = 3,
        quarantine_distance_spread_m: float = 0.5,
        quarantine_heading_spread_rad: float = math.radians(25.0),
        quarantine_trend_bad_fraction: float = 0.5,
        quarantine_trend_min_history: int = 6,
        quarantine_trend_z_threshold: float = 1.5,
        quarantine_next_quality_enabled: bool = False,
        quarantine_next_quality_threshold: float = 0.75,
        quarantine_next_quality_min_samples: int = 5,
        current_confidence_ambiguity_gate_enabled: bool = False,
        current_confidence_ambiguity_gate_threshold: float = 0.75,
        current_confidence_ambiguity_gate_floor: float = 0.5,
        multiframe_anchor_window: int = 1,
        **_: object,
    ):
        self.enabled = bool(enabled)
        self.hint_mode = hint_mode
        self.fallback_enabled = False
        self.anchor_spacing_m = float(anchor_spacing_m)
        self.min_relocalization_confidence = float(min_relocalization_confidence)
        self.relocalization_interval_updates = max(1, int(relocalization_interval_updates))
        self.max_relocalization_consistency_error_m = float(max_relocalization_consistency_error_m)
        self.route_progress_lookahead_m = (
            float(route_progress_lookahead_m)
            if route_progress_lookahead_m is not None else max(1.0, self.anchor_spacing_m)
        )
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
        # Multi-frame anchor submap (2026-07-08): anchors default to a single
        # instantaneous LiDAR frame captured exactly when the anchor-spacing
        # threshold is crossed. window=1 preserves that behavior exactly. A
        # window>1 instead merges the last `window` outbound frames -- each
        # transformed from its own capture-time pose into the anchor's final
        # frame via relative_delta/compose_pose -- into one richer submap
        # before storage, so a genuinely symmetric/self-similar local segment
        # has a chance of being disambiguated by geometry seen a little
        # further down the corridor, which a single-viewpoint scan (at any
        # point density) structurally cannot provide. See
        # investigations/2026-07-03 (deferred pending cheaper fixes first)
        # and the 2026-07-08 rotational-self-alias findings that directly
        # motivated revisiting it: raising point density alone on a single
        # frame left the self-alias "bump" (peak-vs-baseline overlap gap)
        # essentially unchanged on every confirmed-symmetric anchor tested.
        self.multiframe_anchor_window: int = max(1, int(multiframe_anchor_window))
        self._outbound_frame_buffer: list[tuple[list[float], object]] = []
        self._latest_relocalization: Optional[AnchorRelocalization] = None
        self._arc_length_filter: Optional[ArcLengthParticleFilter] = None
        self._arc_observation: Optional[dict] = None
        self._sequence_observation: Optional[SequenceArcObservation] = None
        self._sequence_observation_history: list[dict] = []
        self._distance_since_sequence_observation_m = 0.0
        self._sequence_current_s_m: Optional[float] = None
        self._promotion_distance_history: dict[int, list[float]] = {}
        self._promotion_score_history: dict[int, list[float]] = {}
        self.promotion_window: int = 4
        self.promotion_min_improving_samples: int = 3
        self.promotion_score_ratio: float = 0.85
        self.promotion_close_radius_m: float = max(0.75, 0.75 * self.anchor_spacing_m)
        # Bounded-evidence promotion gate (2026-07-06): see _record_promotion_vote's
        # docstring. 'immediate' (default) preserves the original single-attempt
        # promotion behavior exactly, for every prior validated batch.
        self.sequential_pair_promotion_mode: str = sequential_pair_promotion_mode
        self.sequential_pair_promotion_window: int = max(1, int(sequential_pair_promotion_window))
        self.sequential_pair_promotion_min_votes: int = max(1, int(sequential_pair_promotion_min_votes))
        self._promotion_vote_history: dict[int, list[bool]] = {}
        # Anchor-distinctiveness-aware promotion (2026-07-06): see
        # compute_anchor_alias_scores' and _promotion_requirement_for_anchor's
        # docstrings. Off by default -- requires compute_anchor_alias_scores()
        # to have been called (typically right after finalize_outbound()) to
        # have any effect; otherwise every anchor's alias_score is None and
        # the flat window/min_votes above apply regardless of this flag.
        self.sequential_pair_promotion_alias_aware: bool = bool(sequential_pair_promotion_alias_aware)
        self.sequential_pair_promotion_alias_threshold: float = float(sequential_pair_promotion_alias_threshold)
        self.sequential_pair_promotion_alias_window: int = max(1, int(sequential_pair_promotion_alias_window))
        self.sequential_pair_promotion_alias_min_votes: int = max(1, int(sequential_pair_promotion_alias_min_votes))
        self.sequential_pair_promotion_alias_stall_attempts: int = max(
            1, int(sequential_pair_promotion_alias_stall_attempts)
        )
        # 2026-07-10 (next-behind gate-vs-fusion investigation): off by default,
        # matching this project's convention of every mechanism change being
        # opt-in. When True, _select_sequential_pair_relocalization evaluates
        # close_enough/trend_ok/quality_ok (the actual promotion-vote gates)
        # against each side's raw, pre-closure-check ICP estimate instead of
        # the (possibly belief-fusion-blended/trust-aware-reconstructed)
        # post-closure-check estimate -- see docstring note in that method.
        self.sequential_pair_promotion_use_pre_closure_estimates: bool = bool(
            sequential_pair_promotion_use_pre_closure_estimates
        )
        self._promotion_alias_stall_counter: dict[int, int] = {}
        # Short-baseline yaw disambiguation (2026-07-12, problem-2 step 5, per
        # investigations/2026-07-09-.../route_memory_literature_survey.md
        # §2.1/§4 and step 4's negative result -- see
        # _check_short_baseline_yaw_disambiguation's docstring): off by
        # default. NOT the same mechanism as the already-tried-and-regressed
        # 2026-07-08 `multiframe_anchor_window` (which merges several OUTBOUND
        # frames captured at the *same* physical location into one denser
        # anchor descriptor -- confirmed not to help rotational self-alias,
        # since a genuinely symmetric structure looks symmetric no matter how
        # densely it's sampled from the same vantage point). This instead
        # compares two RETURN-phase observations of the *same* candidate
        # anchor taken from two genuinely different robot positions, using the
        # short (bounded, single-candidate-dwell-time-only, never accumulated
        # across the whole episode) relative motion between them as a
        # consistency constraint -- exploiting real parallax, not sample count.
        self.sequential_pair_short_baseline_disambiguation: bool = bool(
            sequential_pair_short_baseline_disambiguation
        )
        self.sequential_pair_short_baseline_min_travel_m: float = float(
            sequential_pair_short_baseline_min_travel_m
        )
        self.sequential_pair_short_baseline_max_rotation_disagreement_rad: float = math.radians(
            float(sequential_pair_short_baseline_max_rotation_disagreement_deg)
        )
        self._yaw_disambiguation_pending: dict[int, dict] = {}
        # 2026-07-16 (investigations/2026-07-16-.../CODE_CHANGE_short_baseline_
        # require_resolution.md): fixes short-baseline disambiguation's
        # measured 0.1% fire rate / 0% recall (investigations/2026-07-13-.../
        # FINDINGS.md), root-caused to two structural races: (1) promotion can
        # commit before enough travel accumulates to ever resolve the pending
        # check, and (2) the pending entry for a just-promoted anchor is
        # deleted unconditionally regardless of resolution. This flag makes a
        # "next" candidate's promotion wait while its disambiguation entry is
        # still unresolved, bounded by sequential_pair_short_baseline_stall_
        # attempts (a release valve -- default 60, set just above the worst
        # directly-measured real attempts-to-accumulate-0.3m-travel case
        # (57, ep408) across 4 real capture episodes, same methodology used
        # for sequential_pair_promotion_alias_stall_attempts=200 -- so a route
        # segment where the robot genuinely doesn't move near a candidate,
        # e.g. the separately-documented "robot physically stops moving" bug,
        # cannot freeze promotion forever). No-op unless
        # sequential_pair_short_baseline_disambiguation is also on. Off by
        # default; does not change any other behavior when off.
        self.sequential_pair_short_baseline_require_resolution: bool = bool(
            sequential_pair_short_baseline_require_resolution
        )
        self.sequential_pair_short_baseline_stall_attempts: int = max(
            1, int(sequential_pair_short_baseline_stall_attempts)
        )
        self._short_baseline_stall_counter: dict[int, int] = {}
        self.sequence_window = 8
        self.sequence_motion_sigma_m = 1.0
        self.sequence_forward_tolerance_m = 0.4
        self.sequence_max_anchor_distance_m = max(6.0, 4.0 * self.anchor_spacing_m)
        self._target_anchor_index: Optional[int] = None
        self._target_anchor_min_distance_m: Optional[float] = None
        self._force_next_relocalization = False
        self.anchor_pass_radius_m = 0.8
        self.anchor_pass_hysteresis_m = 0.6
        self.anchor_pass_max_min_distance_m = max(2.0 * self.anchor_spacing_m, self.anchor_pass_radius_m)
        self._return_update_count = 0
        # VIO bridge: suppress visual observations in the corridor dead zone;
        # only accept updates when the filter is confident OR near a path feature
        # (a turn or doorway where geometry disambiguates position along the route).
        self.vio_bridge_enabled: bool = True
        self.vio_bridge_std_threshold_m: float = 2.5
        self.vio_bridge_feature_radius_m: float = 2.0
        self._feature_anchor_indices: set = set()
        # VIO bridge relaxation: the flat threshold above is what caused the
        # 2026-07-02 ep680 permanent lock (once std crosses it, every subsequent
        # correction is suppressed forever unless near a feature anchor). Widen
        # the effective threshold the longer we go without an accepted
        # observation, so a stuck filter can eventually accept a re-acquisition
        # candidate instead of being frozen for the rest of the episode.
        self.vio_bridge_relaxation_grace_m: float = 3.0
        self.vio_bridge_relaxation_rate: float = 0.3
        # Large-forward-jump confirmation gate: sequence_forward_tolerance_m below
        # only guards against motion_error > 0 (looks like we moved backward). It
        # never guarded the opposite case (s collapsing implausibly far forward in
        # one step, e.g. a single confident-but-wrong ICP match claiming
        # "arrived"), which is exactly the 2026-07-02 ep680 failure: one match at
        # s~=0 was trusted instantly and then protected by the VIO bridge for the
        # rest of the episode. Require a second, independent observation to land
        # near the same s before committing a jump this large.
        self.sequence_large_forward_jump_m: float = 2.0 * self.anchor_spacing_m
        self.sequence_large_jump_confirm_tolerance_m: float = 0.5
        self.sequence_large_jump_confirm_window_m: float = self.anchor_spacing_m
        self._pending_jump_observed_s_m: Optional[float] = None
        self._pending_jump_distance_marker_m: Optional[float] = None
        # Corridor-degeneracy handling (P2): an accepted relocalization estimate whose
        # source anchor point cloud was geometrically degenerate (see
        # relocalization.corridor_degeneracy_ratio) is still used, but the arc-length
        # filter should trust it less — see the inflate below the skip threshold check
        # in _estimate_arc_observation.
        self.corridor_degeneracy_inflate_threshold: float = 0.30
        # Direction 2 (persistent-error fix): fuse near-tied relocalization
        # candidates from the same query instead of keeping only the top-scored
        # one. Candidates must be reprojected to the same anchor as the top pick
        # and agree within these tolerances to be fused in — this is a spatial
        # (single-timestep) average across candidates, not a temporal filter.
        self.fusion_candidate_pool_size: int = 6
        self.fusion_min_score_ratio: float = 0.6
        self.fusion_max_heading_disagreement_rad: float = math.radians(30.0)
        self.fusion_max_position_disagreement_m: float = 0.75
        # Direction 1 (persistent-error fix): temporally smooth the anchor-relative
        # pose across successive accepted relocalization events (reprojecting the
        # previous filtered belief onto whichever anchor the new estimate matches),
        # mirroring ArcLengthParticleFilter's predict/observe split but for the 2-D
        # pose instead of 1-D arc length. _orientation_filter_weight is a running
        # pseudo-confidence that decays each update so stale beliefs fade out.
        self._orientation_filter_weight: float = 0.0
        self.orientation_filter_decay: float = 0.5
        self.orientation_filter_max_weight: float = 3.0
        self.orientation_filter_max_disagreement_rad: float = math.radians(60.0)
        # 2026-07-04 (continued): anchor-to-anchor geometry source used by
        # _reproject_delta_to_anchor (temporal smoothing, candidate fusion, the
        # sequential_pair closure check below). "accumulated" (default) uses
        # edge_from_previous, i.e. non-privileged outbound dead-reckoning between
        # adjacent anchors -- preserves existing behavior. "oracle" is an
        # ablation-only switch to metadata["world_pose"] ground truth, to isolate
        # whether anchor-to-anchor geometry error (as opposed to ICP/odometry
        # error) explains a given sequential_pair failure. Both must be runnable
        # side by side on the same data for that comparison to be meaningful.
        self.sequential_pair_geometry_source: str = str(sequential_pair_geometry_source)
        # sequential_pair closure check (user-proposed 2026-07-04, verified against
        # real overshoot data before implementation): sequential_pair_anchor_relocalization
        # returns an independent ICP fit against BOTH the current and next anchor
        # every attempt. The two implied robot-to-anchor vectors, differenced,
        # should reproduce the true current-to-next anchor displacement (from
        # _anchor_edge_between); a mismatch beyond tolerance means at least one
        # side's ICP fit is unreliable. Verified empirically (this session) to
        # catch 3 of 4 known overshoot-triggering single bad ICP reads; does not
        # catch cases where both anchors' fits are simultaneously, correlatedly
        # wrong (e.g. ep368 anchor 3/2, both heading_consistency_error ~1.5 rad) --
        # that residual failure mode is out of scope here, left to the bad-anchor
        # quarantine mechanism instead. Off by default to preserve existing
        # accept/reject behavior for prior validated batches.
        self.sequential_pair_closure_check_enabled: bool = bool(sequential_pair_closure_check_enabled)
        # Belief-curve closure mode (user-proposed 2026-07-05): the "threshold"
        # mode above decides trust-one-side-vs-reject-outright from a single
        # magic ratio (1.5x quality) and fixed disagreement caps. "belief"
        # replaces both with a continuous fusion: current and next are always
        # blended, weighted by their own ICP quality, and disagreement (scaled
        # by the same distance-dependent sigma _estimate_arc_observation
        # already uses -- no new magic number) discounts the fused confidence
        # smoothly instead of ever hard-rejecting the attempt outright. This
        # matters because sequence_forward_tolerance_m's "no_sequence_
        # candidates" gate below depends on _distance_since_sequence_
        # observation_m staying near zero (it only resets on an accepted
        # observation) -- a hard reject skips that reset and, verified against
        # real batch data (2026-07-05), can cascade into a permanent,
        # unrecoverable stall once dead-reckoning drift compounds past the
        # gate's own tolerance. Always producing a (possibly low-confidence)
        # fused estimate avoids that cascade. "threshold" (default) preserves
        # all prior validated behavior exactly.
        self.sequential_pair_closure_mode: str = str(sequential_pair_closure_mode)
        self.sequential_pair_closure_max_position_disagreement_m: float = (
            float(sequential_pair_closure_max_position_disagreement_m)
        )
        self.sequential_pair_closure_max_heading_disagreement_rad: float = (
            float(sequential_pair_closure_max_heading_disagreement_rad)
        )
        # Trust-aware belief guard (2026-07-07, ICP bearing-error investigation
        # follow-on): "belief" mode above always blends current+next via a
        # confidence-weighted circular mean, no matter how large the
        # disagreement is. Confirmed against real data (ep187 anchor14) that
        # this is unsafe specifically when the disagreement is large enough to
        # be categorically "one side is wrong" rather than plausible ICP
        # noise: circular-weighted-mean of two angles ~150 deg apart is
        # numerically unstable (the resultant vector nearly cancels), so even
        # a minority-weighted wrong contribution can swing the fused bearing
        # by 100+ degrees -- confirmed anchor14's own raw ICP was accurate
        # (~4 deg mean error) the whole time; the corruption was introduced
        # entirely by blending in anchor13's own bimodal/unstable reading.
        # When enabled and a disagreement exceeds the "large" thresholds
        # below, match_class/near_tie_basin_count (not just the
        # confidence*sqrt(inlier_count) quality score, which is already known
        # to saturate near 1.0 even for anchors match_class flags as
        # degenerate/ambiguous) decide which side is trustworthy; the
        # untrustworthy side is reconstructed from the trustworthy side + the
        # known anchor-to-anchor edge geometry via _reproject_delta_to_anchor
        # (pure geometry, no accumulating odometry/dead-reckoning involved --
        # mirrors "threshold" mode's original dominant-side substitution,
        # just with a better trust signal). Falls back to the existing
        # continuous belief blend when disagreement is below the large
        # thresholds (genuinely noise-level, blending is meaningful) or when
        # trust is ambiguous (both or neither side's own diagnostics look
        # clean). Off by default to preserve existing validated behavior.
        self.sequential_pair_closure_belief_trust_aware_guard: bool = (
            bool(sequential_pair_closure_belief_trust_aware_guard)
        )
        self.sequential_pair_closure_belief_large_position_disagreement_m: float = (
            float(sequential_pair_closure_belief_large_position_disagreement_m)
        )
        self.sequential_pair_closure_belief_large_heading_disagreement_rad: float = (
            float(sequential_pair_closure_belief_large_heading_disagreement_rad)
        )
        # 2026-07-13, per user's proposal following the fusion-mechanism audit
        # (investigations/2026-07-13-icp-bearing-error-cross-batch-deep-dive/
        # FUSION_MECHANISM_ANALYSIS.md): two independent knobs to test against
        # the fusion-corruption finding (7.13% corrupted vs 0.48% fixed, even
        # with trust_aware_guard on).
        #
        # (1) sequential_pair_disable_temporal_smoothing: when True,
        # _temporally_smooth_relocalization (the "+ema" backend suffix,
        # responsible for 93.5% of measured corruption -- it has no
        # trust_aware_guard-style check at all) is skipped entirely in
        # update_relocalization(); combined with leaving
        # sequential_pair_closure_check off, this reports each accepted
        # attempt's raw selected estimate completely unmodified ("no fusion
        # at all").
        #
        # (2) sequential_pair_closure_reconciliation_signal: "dtheta"
        # (default, unchanged behavior) or "bearing". In "bearing" mode, both
        # _sequential_pair_closure_belief_fusion and
        # _temporally_smooth_relocalization measure disagreement/trust using
        # the two sides' BEARING (atan2(dy,dx), the direction-to-anchor
        # quantity this project's hint/arbiter actually consumes) instead of
        # their dtheta (rotation) difference, and never blend dtheta via
        # circular_weighted_mean (the specific operation proven unstable for
        # large disagreements) -- the fused/smoothed output's dtheta is
        # simply carried through unchanged from whichever side is dominant
        # (fusion: higher confidence*sqrt(inlier_count)) or freshest
        # (temporal smoothing: the new reading), never averaged.
        self.sequential_pair_disable_temporal_smoothing: bool = (
            bool(sequential_pair_disable_temporal_smoothing)
        )
        self.sequential_pair_closure_reconciliation_signal: str = str(
            sequential_pair_closure_reconciliation_signal
        )
        # Bad-anchor quarantine (user-proposed 2026-07-04): an anchor whose ICP
        # fit bounces around wildly across consecutive attempts while it is still
        # "next" (not yet promoted to _target_anchor_index) is flagged and
        # permanently skipped by sequential_target_anchor_pair() -- it is never
        # offered as a matching candidate again, so it can never be promoted to
        # "current" either. The trust chain hops to the nearest un-flagged
        # anchor instead, however many flagged anchors are in a row. Verified
        # against real data before implementation: catches anchors that are
        # genuinely unstable before promotion (ep368 anchor 2, ep187 anchor 1 --
        # both visibly noisy for many attempts pre-promotion). Confirmed BLIND to
        # an anchor whose own fit only degrades at the instant of promotion
        # itself (ep368 anchor 3: stable and good for 20 straight attempts as
        # "next", then a sudden step-change failure right at promotion) -- the
        # user explicitly scoped that residual case as a separate, later
        # problem, not something this mechanism is meant to solve. Thresholds
        # below are provisional (not yet tuned against a real batch).
        self.sequential_pair_quarantine_enabled: bool = bool(sequential_pair_quarantine_enabled)
        self.quarantine_window_size: int = max(2, int(quarantine_window_size))
        self.quarantine_min_samples: int = max(2, int(quarantine_min_samples))
        self.quarantine_distance_spread_m: float = float(quarantine_distance_spread_m)
        self.quarantine_heading_spread_rad: float = float(quarantine_heading_spread_rad)
        self._quarantined_anchor_indices: set[int] = set()
        self._next_anchor_observation_window: dict[int, list[tuple[float, float, float]]] = {}
        # Trend-aware quarantine (user-proposed 2026-07-05): "window" above
        # flags an anchor from a small (3-6 sample) window's raw spread, which
        # a single unlucky ICP read can trip on its own -- confirmed against
        # real batch data (2026-07-05) to false-positive on anchors that an
        # independent baseline/off run showed were perfectly fine (100% accept,
        # <0.15m error) in most cases checked. "trend" instead judges each
        # reading against the simultaneously-read "current" anchor (the same
        # triangle cross-check the belief closure mode uses) across the
        # anchor's ENTIRE dwell time as "next", and only quarantines if a
        # majority of that whole history disagrees AND the disagreement is not
        # shrinking as the robot's own ICP-measured distance to this anchor
        # shrinks -- i.e. it never gets a chance to look better on approach,
        # which is the one thing this project can assume never changes (the
        # robot only ever draws closer to "next"). "window" (default)
        # preserves all prior validated behavior exactly.
        self.sequential_pair_quarantine_mode: str = str(sequential_pair_quarantine_mode)
        self.quarantine_trend_bad_fraction: float = float(quarantine_trend_bad_fraction)
        self.quarantine_trend_min_history: int = max(2, int(quarantine_trend_min_history))
        self.quarantine_trend_z_threshold: float = float(quarantine_trend_z_threshold)
        self._next_anchor_trend_history: dict[int, list[tuple[float, float]]] = {}
        # Quality-based "next"-role quarantine (2026-07-15, opt-in, off by
        # default -- see investigations/2026-07-15-50ep-batch-current-next-
        # simultaneous-failure/FINDINGS.md). Independent of and stacks with
        # both quarantine modes above: those judge a "next" candidate against
        # the simultaneously-read "current" anchor (a relative cross-check),
        # which this session found can itself be unreliable when current is
        # ALSO bad (the "pincer" failure mode -- both roles degrade together
        # on some corridor stretches, so a check that only ever compares next
        # against current cannot detect it). This instead uses each attempt's
        # OWN internal ICP ambiguity signal (best_to_second_score_ratio: how
        # close the runner-up yaw-seed hypothesis scored to the winner, from
        # that one attempt's 24-seed sweep, independent of any other anchor).
        # Data-validated (not just reasoned about) on the 2026-07-14
        # 50-episode batch: mean value over a candidate's whole "next" dwell
        # separates known-bad stuck anchors from legitimate slow ones with a
        # ~55-point gap between true-positive and false-positive rates at
        # threshold 0.75 -- the best of several signals tested (raw wait-time
        # window and promotion-vote pass-fraction were both tested first and
        # found not to separate the two populations at all). Real residual
        # error either way: roughly a third of legitimate slow-but-fine
        # candidates would still be quarantined at this threshold. Default
        # OFF; flip quarantine_next_quality_enabled to try it, and revert by
        # flipping it back off if live results are unsatisfactory -- this does
        # not change any other quarantine/promotion behavior when off.
        self.quarantine_next_quality_enabled: bool = bool(quarantine_next_quality_enabled)
        self.quarantine_next_quality_threshold: float = float(quarantine_next_quality_threshold)
        self.quarantine_next_quality_min_samples: int = max(2, int(quarantine_next_quality_min_samples))
        self._next_anchor_quality_history: dict[int, list[float]] = {}
        # 2026-07-16 (investigations/2026-07-16-.../CODE_CHANGE_current_confidence_gate.md):
        # deliberately NOT a quarantine -- no persistent per-anchor state, no
        # blacklisting, nothing to cascade. quarantine_next_quality_enabled
        # (above) permanently bans a "next" candidate once its mean ratio
        # crosses the threshold over several samples, which this project found
        # (2026-07-15 live batch) can cascade through an entire self-similar
        # route's candidate chain with no release valve. This gate instead
        # only ever looks at the CURRENT role's OWN single most recent
        # estimate's best_to_second_score_ratio (the same signal, reused for a
        # different, softer purpose): if ambiguous, it caps the *reported*
        # relocalization_confidence for this one attempt only, so the
        # already-existing hint_action_arbiter/stop_gate confidence gates
        # (built 2026-07-13 for the oracle-to-shadow swap) naturally defer to
        # the VLM's own judgement instead of acting on a possibly-wrong hint.
        # Next attempt re-evaluates completely fresh -- there is no state here
        # to carry over, ban, or release. This does not fix a stuck/wrong
        # current anchor (it cannot promote past it or replace it -- that
        # remains a genuine open problem, see FINDINGS.md Part 6), it only
        # stops the shadow from actively misleading the VLM while current is
        # bad. Off by default; does not touch anything when disabled.
        self.current_confidence_ambiguity_gate_enabled: bool = bool(
            current_confidence_ambiguity_gate_enabled
        )
        self.current_confidence_ambiguity_gate_threshold: float = float(
            current_confidence_ambiguity_gate_threshold
        )
        self.current_confidence_ambiguity_gate_floor: float = float(
            current_confidence_ambiguity_gate_floor
        )
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
        if self.multiframe_anchor_window > 1 and descriptor is not None:
            self._outbound_frame_buffer.append((list(self._outbound_pose_from_start), descriptor))
            if len(self._outbound_frame_buffer) > self.multiframe_anchor_window:
                del self._outbound_frame_buffer[: len(self._outbound_frame_buffer) - self.multiframe_anchor_window]
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
        self._return_update_count += 1
        self.update_relocalization(local_descriptor=local_descriptor, relocalization=relocalization)

    def finalize_outbound(
        self,
        descriptor: Optional[object] = None,
        metadata: Optional[dict] = None,
    ) -> None:
        if self.enabled and (not self.anchors or self.anchors[-1].distance_from_start_m < self._outbound_distance_m):
            final_metadata = {"event": "outbound_final"}
            if metadata:
                final_metadata.update(dict(metadata))
            self._append_anchor(descriptor=descriptor, metadata=final_metadata)
        self._finalize_anchor_route_lengths()
        self._return_start_pose_from_start = list(self._outbound_pose_from_start)
        self._return_pose_from_return_start = [0.0, 0.0, 0.0]
        self._arc_length_filter = None
        self._arc_observation = None
        final_anchor_index = self.anchors[-1].index if self.anchors else 0
        self._sequence_observation = None
        self._sequence_observation_history = []
        self._distance_since_sequence_observation_m = 0.0
        self._sequence_current_s_m = None
        self._pending_jump_observed_s_m = None
        self._pending_jump_distance_marker_m = None
        self._target_anchor_index = int(final_anchor_index)
        self._target_anchor_min_distance_m = None
        self._promotion_distance_history = {}
        self._promotion_score_history = {}
        self._return_started = True
        self._return_update_count = 0
        self._force_next_relocalization = True
        self._compute_feature_anchors()

    def correct_return_start_yaw(self, yaw_delta_rad: float) -> None:
        """Rotate the frozen return-start reference pose by ``yaw_delta_rad``
        in place (no translation).

        2026-07-04: fixes a reference-frame bug found while investigating why
        --measured_odometry showed no improvement in dead-reckoning drift over
        the default action_delta path (both were equally affected, ruling out
        the odometry integration method itself -- see round_trip_eval.py's
        align_return_yaw_to_anchor_segment for the caller). finalize_outbound()
        freezes return_start_pose_from_start *before*
        --oracle_align_return_yaw_to_anchor_segment physically snaps the
        robot's real orientation to a new yaw via reset_navigation_memory --
        without this correction, the shadow/non-oracle dead-reckoning
        reference silently disagrees with the robot's true orientation from
        the very first step of return, and no amount of per-step integration
        accuracy afterward can undo a wrong starting reference. Call this with
        the actual before/after yaw delta of that snap immediately after
        applying it, so the shadow's belief tracks the robot's real physical
        state the same way a real onboard state estimator would observe any
        actual rotation of the body it's attached to, regardless of what
        caused it.
        """
        x, y, theta = self._return_start_pose_from_start
        self._return_start_pose_from_start = [x, y, wrap_angle(theta + float(yaw_delta_rad))]

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
            # Already a local (single-edge) comparison -- use the edge directly
            # rather than differencing two pose_from_start values.
            dtheta = abs(wrap_angle(curr.edge_from_previous[2]))
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
            if (
                not self._force_next_relocalization
                and self._return_update_count % self.relocalization_interval_updates != 0
            ):
                return None
            self._force_next_relocalization = False
            estimates = self._coerce_relocalizations(
                self.relocalizer(local_descriptor, self.anchors)
            )
        elif estimates:
            self._force_next_relocalization = False
        estimates = [
            estimate for estimate in estimates
            if estimate.confidence >= self.min_relocalization_confidence
            and self._anchor_by_index(estimate.anchor_index) is not None
        ]
        if not estimates:
            return None
        self._record_next_anchor_stability(estimates)
        self._record_next_anchor_quality(estimates)

        estimate, observation, reject_reason = self._select_sequential_pair_relocalization(estimates)
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

        # Direction 1 (persistent-error fix): blend with the previous filtered
        # belief instead of a hard overwrite, damping single-observation jitter.
        # 2026-07-13: sequential_pair_disable_temporal_smoothing skips this
        # entirely -- see FUSION_MECHANISM_ANALYSIS.md, this step is
        # responsible for 93.5% of measured fusion-corruption and has no
        # trust_aware_guard-style check at all.
        if not self.sequential_pair_disable_temporal_smoothing:
            estimate = self._temporally_smooth_relocalization(estimate)
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
            "candidate_count": len(estimates),
            "sequence_observation": asdict(observation),
            "target_anchor_index": self._target_anchor_index,
            "accepted": True,
        })
        return estimate

    def _record_next_anchor_stability(self, estimates: list[AnchorRelocalization]) -> None:
        """Bad-anchor quarantine (user-proposed 2026-07-04): accumulate a rolling
        window of ICP readings for any anchor still in the "next" role (i.e. not
        yet promoted to _target_anchor_index) and flag it permanently unstable
        if its implied position/heading bounce beyond tolerance across
        consecutive attempts. See sequential_pair_quarantine_enabled's docstring
        at __init__ for what this does and does not catch. Deliberately does NOT
        track the anchor currently in the "current" role (idx ==
        _target_anchor_index) -- quality degradation only after promotion is a
        separate, out-of-scope problem (see docstring).
        """
        if not self.sequential_pair_quarantine_enabled:
            return
        if self.sequential_pair_quarantine_mode == "trend":
            self._record_next_anchor_trend(estimates)
            return
        for estimate in estimates:
            idx = int(estimate.anchor_index)
            if idx == self._target_anchor_index or idx in self._quarantined_anchor_indices:
                continue
            window = self._next_anchor_observation_window.setdefault(idx, [])
            window.append(
                (float(estimate.anchor_dx_m), float(estimate.anchor_dy_m), float(estimate.anchor_dtheta_rad))
            )
            if len(window) > self.quarantine_window_size:
                del window[: len(window) - self.quarantine_window_size]
            if len(window) < self.quarantine_min_samples:
                continue
            distances = [math.hypot(dx, dy) for dx, dy, _dtheta in window]
            thetas = [dtheta for _dx, _dy, dtheta in window]
            distance_spread = max(distances) - min(distances)
            heading_spread = max(
                (abs(wrap_angle(a - b)) for i, a in enumerate(thetas) for b in thetas[i + 1:]),
                default=0.0,
            )
            if (
                distance_spread > self.quarantine_distance_spread_m
                or heading_spread > self.quarantine_heading_spread_rad
            ):
                self._quarantined_anchor_indices.add(idx)

    def _record_next_anchor_trend(self, estimates: list[AnchorRelocalization]) -> None:
        """Trend-aware quarantine (user-proposed 2026-07-05): the "window" mode
        above can flag an anchor from a single unlucky read inside a 3-6
        sample window (a fixed spread cap has no way to tell "one bad sample
        among good ones" apart from "genuinely unstable"). Confirmed against
        real batch data (2026-07-05): of 8 anchors "window" mode quarantined in
        one A/B batch, only anchors tied to one already-confirmed permanent-
        lock episode had independent baseline/off evidence of real difficulty;
        the rest were anchors an independent run showed were perfectly fine
        (100% accept, <0.15 m error) -- i.e. mostly false positives.

        This instead judges each reading against the simultaneously-read
        "current" anchor (the same triangle cross-check the belief closure
        mode uses -- see _closure_disagreement_sigma_m) across this anchor's
        entire dwell time as "next" (not a small fixed window), and only
        quarantines once a majority of that whole history disagrees AND the
        disagreement is not shrinking as the robot's own ICP-measured distance
        to this anchor shrinks. The one thing this project can assume never
        changes is that the robot only ever draws closer to "next" -- so a
        genuinely fine anchor should look at least as good up close as it did
        far away; a genuinely bad one has no reason to improve just because
        the robot got nearer.
        """
        by_anchor = {int(e.anchor_index): e for e in estimates}
        current_idx = self._target_anchor_index
        current_est = by_anchor.get(current_idx) if current_idx is not None else None
        if current_est is None:
            return
        for estimate in estimates:
            idx = int(estimate.anchor_index)
            if idx == current_idx or idx in self._quarantined_anchor_indices:
                continue
            reprojected = self._reproject_delta_to_anchor(
                idx, estimate.anchor_dx_m, estimate.anchor_dy_m, estimate.anchor_dtheta_rad, current_idx,
            )
            if reprojected is None:
                continue
            dx, dy, _dtheta = reprojected
            position_disagreement = math.hypot(dx - current_est.anchor_dx_m, dy - current_est.anchor_dy_m)
            sigma_next = self._closure_disagreement_sigma_m(estimate)
            sigma_current = self._closure_disagreement_sigma_m(current_est)
            z = position_disagreement / max(1e-6, math.hypot(sigma_next, sigma_current))
            history = self._next_anchor_trend_history.setdefault(idx, [])
            history.append((float(estimate.distance_to_anchor_m), float(z)))
            if len(history) < self.quarantine_trend_min_history:
                continue
            bad_fraction = sum(1 for _dist, zz in history if zz > self.quarantine_trend_z_threshold) / len(history)
            if bad_fraction <= self.quarantine_trend_bad_fraction:
                continue
            by_distance = sorted(history, key=lambda item: item[0])
            half = len(by_distance) // 2
            closer_half, farther_half = by_distance[:half], by_distance[half:]
            closer_bad = sum(
                1 for _dist, zz in closer_half if zz > self.quarantine_trend_z_threshold
            ) / max(1, len(closer_half))
            farther_bad = sum(
                1 for _dist, zz in farther_half if zz > self.quarantine_trend_z_threshold
            ) / max(1, len(farther_half))
            improving = closer_bad < farther_bad - 1e-9
            if improving:
                continue
            self._quarantined_anchor_indices.add(idx)

    def _record_next_anchor_quality(self, estimates: list[AnchorRelocalization]) -> None:
        """Quality-based "next"-role quarantine (2026-07-15, opt-in) -- see
        quarantine_next_quality_enabled's docstring at __init__ for the full
        rationale and validation. Unlike _record_next_anchor_stability/
        _record_next_anchor_trend (which both explicitly skip the "current"
        role and judge "next" only relative to current), this uses each
        attempt's own single-attempt ICP ambiguity signal
        (best_to_second_score_ratio), so it does not depend on current being
        trustworthy -- it is meant to catch exactly the case those two modes
        cannot: current and next both degraded together.
        """
        if not self.quarantine_next_quality_enabled:
            return
        current_idx = self._target_anchor_index
        for estimate in estimates:
            idx = int(estimate.anchor_index)
            if idx == current_idx or idx in self._quarantined_anchor_indices:
                continue
            if estimate.best_to_second_score_ratio is None:
                continue
            history = self._next_anchor_quality_history.setdefault(idx, [])
            history.append(float(estimate.best_to_second_score_ratio))
            if len(history) < self.quarantine_next_quality_min_samples:
                continue
            mean_ratio = sum(history) / len(history)
            if mean_ratio > self.quarantine_next_quality_threshold:
                self._quarantined_anchor_indices.add(idx)

    def _current_reported_confidence(self, estimate: AnchorRelocalization) -> float:
        """The confidence value reported downstream (hint_action_arbiter /
        stop_gate) for the CURRENT-role estimate, after the optional
        ambiguity gate (see current_confidence_ambiguity_gate_enabled's
        docstring at __init__). Does NOT touch estimate.confidence itself --
        that field is still used unmodified everywhere else (promotion
        voting, closure-check quality comparisons, quarantine, ...); this
        only affects what gets reported as this one attempt's trustworthiness
        to the navigation-facing hint. Stateless: every call re-derives the
        result purely from this single estimate, nothing is remembered
        between attempts.
        """
        confidence = float(estimate.confidence)
        if not self.current_confidence_ambiguity_gate_enabled:
            return confidence
        ratio = estimate.best_to_second_score_ratio
        if ratio is None:
            return confidence
        if float(ratio) >= self.current_confidence_ambiguity_gate_threshold:
            return min(confidence, self.current_confidence_ambiguity_gate_floor)
        return confidence

    def _relocalization_quality(self, estimate: AnchorRelocalization) -> float:
        return float(estimate.confidence) * math.sqrt(max(1, int(estimate.inlier_count or 1)))

    def _record_promotion_sample(self, estimate: AnchorRelocalization, quality: float) -> None:
        idx = int(estimate.anchor_index)
        distances = self._promotion_distance_history.setdefault(idx, [])
        scores = self._promotion_score_history.setdefault(idx, [])
        distances.append(float(estimate.distance_to_anchor_m))
        scores.append(float(quality))
        if len(distances) > self.promotion_window:
            del distances[: len(distances) - self.promotion_window]
        if len(scores) > self.promotion_window:
            del scores[: len(scores) - self.promotion_window]

    def _promotion_trend_improving(self, anchor_index: int) -> bool:
        distances = self._promotion_distance_history.get(int(anchor_index), [])
        if len(distances) < self.promotion_min_improving_samples:
            return False
        recent = distances[-self.promotion_min_improving_samples:]
        if recent[-1] > recent[0] - 0.05:
            return False
        decreasing = sum(1 for a, b in zip(recent, recent[1:]) if b <= a + 0.05)
        return decreasing >= len(recent) - 1

    def _record_promotion_vote(self, anchor_index: int, vote: bool) -> bool:
        """Bounded-evidence promotion gate (user-proposed 2026-07-06, off by
        default via sequential_pair_promotion_mode="immediate"): the original
        design promotes "next" to "current" the instant a single attempt looks
        good (close enough, or the existing distance-trend check, per
        _promotion_trend_improving). Forensic replay of real hard-11 data found
        this lets a single-step promotion chain race through many anchors in a
        short attempt window whenever local structure repeats along the route
        (high-overlap, low-residual, many-inlier ICP fits that are nonetheless
        against the wrong anchor -- "confidently wrong", not low-confidence
        noise) -- see investigations/2026-07-06-anchor-selection-and-icp-aliasing.
        This does not change the single-attempt "does this attempt look
        promotable" test at all (still the same close_enough/trend_ok/quality_ok
        computed by the caller) -- it only requires that test to keep passing
        across sequential_pair_promotion_min_votes of the last
        sequential_pair_promotion_window attempts against this same candidate
        anchor before the promotion actually commits, instead of committing on
        attempt one.

        Deliberately NOT an unbounded accumulator like the deleted VIO
        bridge/arc-length odometer: the window is a fixed size, keyed by
        candidate anchor index, and is discarded entirely the moment that
        anchor is promoted (by the caller, mirroring how
        _promotion_distance_history/_promotion_score_history are already
        pruned on promotion) -- so a bad read can only ever delay a promotion
        within this one anchor's dwell time, never veto or lock anything
        permanently, and nothing here can carry over past a promotion the way
        the removed odometry gates used to.
        """
        self._promotion_alias_stall_counter[anchor_index] = (
            self._promotion_alias_stall_counter.get(anchor_index, 0) + 1
        )
        window, min_votes = self._promotion_requirement_for_anchor(anchor_index)
        history = self._promotion_vote_history.setdefault(anchor_index, [])
        history.append(bool(vote))
        if len(history) > window:
            del history[: len(history) - window]
        votes = sum(1 for cast in history if cast)
        return votes >= min_votes

    def _promotion_requirement_for_anchor(self, anchor_index: int) -> tuple[int, int]:
        """Anchor-distinctiveness-aware promotion requirement (user-proposed
        2026-07-06, see compute_anchor_alias_scores' docstring and
        investigations/2026-07-06-anchor-selection-and-icp-aliasing): a
        candidate anchor flagged as self-similar to others on the route
        (alias_score at or above sequential_pair_promotion_alias_threshold)
        needs more sustained evidence before promotion commits than a normal,
        distinctive anchor -- the flat bounded_evidence window/min_votes
        otherwise still promotes on this class of anchor, because a
        genuinely repeating local structure can fool several consecutive,
        slightly-different-viewpoint ICP reads in a row, not just one.
        Confirmed directly against real hard-11 replay data: episodes where
        the racing survived plain bounded_evidence (ep187, ep408) are exactly
        the ones whose stuck anchor shows a flat, non-decaying overlap
        against anchors several route-positions away, instead of a normal
        falloff.

        Falls back to the flat window/min_votes whenever alias-aware mode is
        off, alias scores were never computed for this episode, or this
        anchor's own score came out below threshold.

        Stall relief (found necessary against real data, not just reasoned
        about): a route that is *uniformly* self-similar end to end (ep5 of
        the hard-11 set -- every single anchor scored above threshold, 0.61
        to 0.91, not just a couple of hot spots) can make the stricter
        window/min_votes never get satisfied at all, permanently freezing
        promotion for the rest of the episode (confirmed directly: ep5 with
        alias-aware on promoted once, then sat on the same anchor for the
        remaining 357 of 381 attempts, actively worse than plain
        bounded_evidence). If this anchor has been voted on
        sequential_pair_promotion_alias_stall_attempts times without ever
        promoting, this falls back to the flat requirement for it -- chosen
        well above the largest gap between two *legitimate* alias-aware
        promotions seen in ep187 (130 attempts, itself part of why ep187 saw
        its largest improvement) so a genuinely hard-but-solvable case is not
        cut short, while a truly runaway stall like ep5's still gets relief
        long before the end of the episode.
        """
        if not self.sequential_pair_promotion_alias_aware:
            return self.sequential_pair_promotion_window, self.sequential_pair_promotion_min_votes
        anchor = self._anchor_by_index(anchor_index)
        alias_score = anchor.alias_score if anchor is not None else None
        if alias_score is None or alias_score < self.sequential_pair_promotion_alias_threshold:
            return self.sequential_pair_promotion_window, self.sequential_pair_promotion_min_votes
        stall = self._promotion_alias_stall_counter.get(anchor_index, 0)
        if stall >= self.sequential_pair_promotion_alias_stall_attempts:
            return self.sequential_pair_promotion_window, self.sequential_pair_promotion_min_votes
        return self.sequential_pair_promotion_alias_window, self.sequential_pair_promotion_alias_min_votes

    def compute_anchor_alias_scores(
        self,
        min_neighbor_offset: int = 2,
        max_neighbor_offset: int = 5,
        voxel_size_m: float = 0.10,
        max_points: int = 512,
        icp_objective: str = "point_to_point",
    ) -> None:
        """Runs relocalization.compute_anchor_alias_scores against
        self.anchors and stores the result on each RouteAnchor's alias_score
        field. Call once, right after finalize_outbound() (every anchor's
        point cloud is fixed by then) -- a one-time offline cost, not part of
        return-phase live-matching latency. No-op if there are no anchors."""
        if not self.anchors:
            return
        from relocalization import compute_anchor_alias_scores as _compute_anchor_alias_scores
        scores = _compute_anchor_alias_scores(
            self.anchors, min_neighbor_offset=min_neighbor_offset, max_neighbor_offset=max_neighbor_offset,
            voxel_size_m=voxel_size_m, max_points=max_points, icp_objective=icp_objective,
        )
        for anchor in self.anchors:
            anchor.alias_score = scores.get(int(anchor.index))

    def _best_estimate_by_anchor(self, estimates: list[AnchorRelocalization]) -> dict[int, AnchorRelocalization]:
        best: dict[int, AnchorRelocalization] = {}
        for estimate in estimates:
            idx = int(estimate.anchor_index)
            if idx not in best or self._relocalization_quality(estimate) > self._relocalization_quality(best[idx]):
                best[idx] = estimate
        return best

    def _check_short_baseline_yaw_disambiguation(
        self, anchor_index: int, raw_estimate: AnchorRelocalization,
    ) -> Optional[bool]:
        """2026-07-12, problem-2 step 5: cross-check a single ambiguous ICP
        reading against a second, later reading of the *same* candidate
        anchor taken once the robot has genuinely moved
        (`sequential_pair_short_baseline_min_travel_m`, default 0.3m) --
        exploiting real parallax between two different vantage points, not
        more points from the same one (see the constructor's comment on why
        this differs from the already-tried-and-regressed
        `multiframe_anchor_window`).

        Geometry: each raw ICP reading gives the anchor's pose *relative to
        the robot* at capture time. Composing that relative pose onto the
        robot's own absolute pose (`current_absolute_pose_from_start()`)
        gives the anchor's absolute pose as implied by that one reading --
        if two readings, taken from different robot positions, really are
        the same fixed anchor, their implied absolute poses should agree
        regardless of where the robot stood for each one. Reuses
        `compose_pose`/`relative_delta` (this file's existing SE(2) utilities,
        already used by `_oracle_edge_between`/`_compose_edges_between`) --
        deliberately not a new transform convention.

        Returns `None` while still waiting (first reading just stored, or not
        enough travel yet since it -- the stored first reading is kept
        as-is, not overwritten, until enough baseline accumulates), `True`
        once two readings agree (rotation disagreement within
        `sequential_pair_short_baseline_max_rotation_disagreement_rad`), or
        `False` once they confirm a genuine disagreement.

        Bounded by construction, not a reintroduced accumulator: at most one
        pending reading is ever held per candidate anchor index, consumed
        (deleted) the moment a second reading resolves it one way or the
        other, and the whole dict is pruned on promotion exactly like
        `_promotion_distance_history`/etc. -- never grows across an episode.
        """
        if not self.sequential_pair_short_baseline_disambiguation:
            return None
        current_pose = self.current_absolute_pose_from_start()
        anchor_abs_pose = compose_pose(
            current_pose,
            [raw_estimate.anchor_dx_m, raw_estimate.anchor_dy_m, raw_estimate.anchor_dtheta_rad],
        )

        pending = self._yaw_disambiguation_pending.get(anchor_index)
        if pending is None:
            self._yaw_disambiguation_pending[anchor_index] = {
                "pose": current_pose,
                "anchor_abs_pose": anchor_abs_pose,
            }
            return None

        travel = relative_delta(pending["pose"], current_pose)
        travel_dist_m = math.hypot(travel[0], travel[1])
        if travel_dist_m < self.sequential_pair_short_baseline_min_travel_m:
            return None

        diff = relative_delta(pending["anchor_abs_pose"], anchor_abs_pose)
        rotation_disagreement_rad = abs(wrap_angle(diff[2]))
        del self._yaw_disambiguation_pending[anchor_index]
        return rotation_disagreement_rad <= self.sequential_pair_short_baseline_max_rotation_disagreement_rad

    def _select_sequential_pair_relocalization(
        self,
        estimates: list[AnchorRelocalization],
    ) -> tuple[Optional[AnchorRelocalization], Optional[SequenceArcObservation], Optional[str]]:
        # 2026-07-10: when sequential_pair_promotion_use_pre_closure_estimates is
        # set, the promotion-vote gates (close_enough/trend_ok/quality_ok, just
        # below) are evaluated against each side's raw, pre-closure-check ICP
        # estimate rather than the version _sequential_pair_closure_precheck
        # produces (which, in belief mode, blends/reconstructs both sides
        # toward each other -- see that method's docstring). Investigation
        # (2026-07-10, next-behind gate-breakdown replay against real hard-11
        # covisibility_records) found ~39/2788 attempts pooled where next's own
        # raw ICP reading already clearing every vote gate, but the version the
        # live promotion logic actually saw (post-closure-fusion) did not,
        # delaying promotion. This does NOT change which two anchors are ever
        # compared (_next_candidate_index is untouched) and does NOT change the
        # bounded_evidence/alias_aware vote-window mechanism itself -- only
        # which values are compared against close_enough/trend_ok/quality_ok.
        # The actual reported hint (selected/observation below) still goes
        # through the closure-check/belief-fusion/trust_aware_guard pipeline
        # exactly as before, unaffected by this flag.
        raw_by_anchor = (
            self._best_estimate_by_anchor(estimates)
            if self.sequential_pair_promotion_use_pre_closure_estimates
            else None
        )
        # 2026-07-12: always available (independent of the flag above), since
        # short-baseline disambiguation needs the raw pre-closure-fusion
        # match_class regardless of whether promotion gating itself uses raw
        # estimates.
        raw_by_anchor_for_disambiguation = self._best_estimate_by_anchor(estimates)

        estimates, closure_reject_reason = self._sequential_pair_closure_precheck(estimates)
        if closure_reject_reason is not None:
            return None, None, closure_reject_reason
        if not estimates:
            return None, None, "no_pair_candidates"
        if self._target_anchor_index is None:
            self._target_anchor_index = int(self.anchors[-1].index) if self.anchors else None
        if self._target_anchor_index is None:
            return None, None, "no_target_anchor"

        current_idx = int(self._target_anchor_index)
        next_idx = self._next_candidate_index(current_idx)
        by_anchor = self._best_estimate_by_anchor(estimates)
        current_est = by_anchor.get(current_idx)
        next_est = by_anchor.get(next_idx) if next_idx >= 0 else None
        if current_est is None and next_est is None:
            return None, None, "no_current_or_next_anchor_candidates"

        # Short-baseline yaw disambiguation (2026-07-12): runs on EVERY next
        # candidate reading, not gated on match_class being flagged ambiguous
        # -- an offline smoke test on ep1040 (this project's own flagship
        # "confidently wrong rotation" example, investigations/2026-07-09-
        # .../FINDINGS.md §3.5) found 45/52 (86.5%) of its >45deg bearing
        # errors carry match_class="clean_full_pose", not "ambiguous_*" --
        # the whole reason these readings are in the "69% unexplained"
        # bucket in the first place is that they look clean by every
        # existing per-attempt diagnostic. Gating this check behind that same
        # diagnostic would have missed almost all of the cases it exists to
        # catch. Downgrades next_est.anchor_heading_reliable (propagates to
        # whatever ends up `selected` below, current_retained or
        # next_promoted) once two readings from genuinely different robot
        # positions confirm real disagreement; leaves next_est untouched
        # while still waiting for a second observation.
        # 2026-07-16: withhold promotion while a "next" candidate's
        # short-baseline check is still pending (created but not yet
        # resolved) -- see sequential_pair_short_baseline_require_resolution's
        # docstring at __init__ for the full rationale (this project's own
        # 2026-07-13 investigation found the mechanism above resolves on only
        # 0.1% of live events, root-caused to promotion routinely committing
        # before enough travel accumulates to ever resolve the pending entry).
        # Bounded by sequential_pair_short_baseline_stall_attempts -- a release
        # valve, not a permanent block, per this project's established
        # "abstain, don't ban" convention.
        withhold_for_unresolved_short_baseline = False
        if next_idx >= 0 and next_est is not None:
            raw_next = raw_by_anchor_for_disambiguation.get(next_idx)
            if raw_next is not None:
                disambiguation_result = self._check_short_baseline_yaw_disambiguation(next_idx, raw_next)
                if disambiguation_result is False:
                    next_est = replace(next_est, anchor_heading_reliable=False)
            if self.sequential_pair_short_baseline_require_resolution and next_idx in self._yaw_disambiguation_pending:
                stall = self._short_baseline_stall_counter.get(next_idx, 0) + 1
                self._short_baseline_stall_counter[next_idx] = stall
                withhold_for_unresolved_short_baseline = stall <= self.sequential_pair_short_baseline_stall_attempts

        if raw_by_anchor is not None:
            gate_current_est = raw_by_anchor.get(current_idx)
            gate_next_est = raw_by_anchor.get(next_idx) if next_idx >= 0 else None
            if gate_current_est is None and gate_next_est is None:
                gate_current_est, gate_next_est = current_est, next_est
        else:
            gate_current_est, gate_next_est = current_est, next_est

        current_quality = self._relocalization_quality(gate_current_est) if gate_current_est is not None else 0.0
        next_quality = self._relocalization_quality(gate_next_est) if gate_next_est is not None else 0.0
        if gate_next_est is not None:
            self._record_promotion_sample(gate_next_est, next_quality)

        promote = False
        if gate_next_est is not None and next_est is not None:
            close_enough = gate_next_est.distance_to_anchor_m <= self.promotion_close_radius_m
            trend_ok = self._promotion_trend_improving(next_idx)
            quality_ok = (
                gate_current_est is None
                or next_quality >= self.promotion_score_ratio * max(current_quality, 1e-9)
            )
            candidate_promote = bool(quality_ok and (close_enough or trend_ok or gate_current_est is None))
            if gate_current_est is None or self.sequential_pair_promotion_mode != "bounded_evidence":
                # Nothing to hold onto (current has no estimate at all) -- or
                # bounded-evidence voting is off -- promote on this attempt alone,
                # exactly like the original design.
                promote = candidate_promote
            else:
                promote = self._record_promotion_vote(next_idx, candidate_promote)
            # 2026-07-16: applied AFTER both paths above -- offline measurement
            # (investigations/2026-07-16-.../CODE_CHANGE_short_baseline_
            # require_resolution.md Step 0) found the under-resolution problem
            # is dominated by promotions completing via the NORMAL
            # bounded_evidence vote path (19.8% of all promotions lacked 0.3m
            # of travel), not the rarer single-attempt bypass above (4.4%) --
            # so this must gate both paths, not just the bypass.
            # _record_promotion_vote's own bookkeeping (vote history, window,
            # alias-aware stall counter) always runs unmodified above; only the
            # final decision is overridden here.
            if withhold_for_unresolved_short_baseline:
                promote = False

        if promote and next_est is not None:
            selected = next_est
            self._target_anchor_index = int(next_idx)
            self._target_anchor_min_distance_m = next_est.distance_to_anchor_m
            self._promotion_distance_history = {
                k: v for k, v in self._promotion_distance_history.items() if k < next_idx
            }
            self._promotion_score_history = {
                k: v for k, v in self._promotion_score_history.items() if k < next_idx
            }
            self._promotion_vote_history = {
                k: v for k, v in self._promotion_vote_history.items() if k < next_idx
            }
            self._promotion_alias_stall_counter = {
                k: v for k, v in self._promotion_alias_stall_counter.items() if k < next_idx
            }
            self._yaw_disambiguation_pending = {
                k: v for k, v in self._yaw_disambiguation_pending.items() if k < next_idx
            }
            self._short_baseline_stall_counter = {
                k: v for k, v in self._short_baseline_stall_counter.items() if k < next_idx
            }
            self._next_anchor_quality_history = {
                k: v for k, v in self._next_anchor_quality_history.items() if k < next_idx
            }
            selection_reason = "next_promoted"
        else:
            selected = current_est if current_est is not None else next_est
            selection_reason = "current_retained" if current_est is not None else "next_selected_without_current"

        if selected is None:
            return None, None, "no_selected_pair_candidate"
        observation = self._estimate_arc_observation(selected)
        if observation is None:
            return None, None, "no_sequence_observation"
        observation.selected_score = self._relocalization_quality(selected)
        observation.candidate_count = len(estimates)
        observation.expected_s_m = None
        observation.motion_error_m = None
        self._sequence_observation = observation
        self._sequence_current_s_m = float(observation.observed_s_m)
        self._sequence_observation_history.append(asdict(observation))
        if len(self._sequence_observation_history) > self.sequence_window:
            self._sequence_observation_history = self._sequence_observation_history[-self.sequence_window:]
        self._distance_since_sequence_observation_m = 0.0
        self._pending_jump_observed_s_m = None
        self._pending_jump_distance_marker_m = None
        self._target_anchor_min_distance_m = (
            selected.distance_to_anchor_m
            if self._target_anchor_min_distance_m is None
            else min(self._target_anchor_min_distance_m, selected.distance_to_anchor_m)
        )
        observation.source = f"{observation.source}:{selection_reason}"
        return selected, observation, None

    def update_latest_anchor_metadata(self, metadata: dict) -> None:
        if not self.enabled or not self.anchors:
            return
        self.anchors[-1].metadata.update(dict(metadata))

    @property
    def total_route_length_m(self) -> float:
        """Total outbound route length (meters), finalized once return starts.

        Used by round_trip_eval.py to trigger diagnostic-frame captures at
        fixed *fractions* of the return journey (e.g. 75%/50%/25%/5%
        remaining) regardless of relocalization_interval_updates or episode
        step count, so the number of captured frames stays ~3-4 per episode.
        """
        return float(self._outbound_distance_m)

    def sequential_target_anchor_pair(self) -> tuple[Optional[RouteAnchor], Optional[RouteAnchor]]:
        """(current, next) anchor pair for the sequential_pair relocalization
        backend (relocalization.py::sequential_pair_anchor_relocalization).

        Before any relocalization has been accepted yet (right after
        finalize_outbound(), which appends a final anchor exactly at the
        return-start position), "current" is the last outbound anchor and
        "next" is the one before it. Once a match against either of these two
        anchors is accepted, _sequence_match_observation's existing scoring
        (unchanged by this method) sets _target_anchor_index to whichever one
        won, so the pair naturally slides forward one anchor at a time as a
        side effect -- there's no separate index to advance here, since the
        candidate set offered to matching is always exactly these two anchors
        and _target_anchor_index can only ever land on one of them.

        Bad-anchor quarantine (2026-07-04): if quarantining is enabled and one
        or more anchors immediately below "current" have been flagged unstable
        by _record_next_anchor_stability, "next" skips past all of them to the
        nearest un-flagged anchor -- a flagged anchor is therefore never offered
        as a matching candidate again and can never be promoted to "current".
        """
        if self._target_anchor_index is not None:
            current_index = self._target_anchor_index
        elif self.anchors:
            current_index = self.anchors[-1].index
        else:
            return None, None
        current = self._anchor_by_index(current_index)
        next_anchor = self._anchor_by_index(self._next_candidate_index(current_index))
        return current, next_anchor

    def _next_candidate_index(self, current_index: int) -> int:
        """The "next" candidate index for current_index, skipping past any
        quarantined anchors -- shared by sequential_target_anchor_pair()
        (which offers this index's anchor to the live ICP call) and
        _select_sequential_pair_relocalization (which must look up that same
        anchor's estimate in the returned candidates, not some other index).

        Found necessary against real data (2026-07-06, while debugging why
        bounded_evidence + alias-aware promotion could freeze permanently on
        some episodes): before this fix, _select_sequential_pair_relocalization
        independently recomputed next_idx = current_idx - 1 without the
        quarantine skip below, so whenever quarantine skipped past more than
        the immediate neighbor (confirmed on ep5: anchors 10 and 9 both
        quarantined in sequence), the live ICP call correctly matched against
        the real next candidate (anchor8) but _select_sequential_pair_relocalization
        went looking for anchor10's estimate -- which was never computed,
        since quarantine skipped it at the call site -- so next_est was
        always None and promotion could never be recorded again for the rest
        of the episode. This bug predates bounded_evidence/alias-aware
        entirely (quarantine shipped 2026-07-04): it went unnoticed because
        "immediate" mode promotes within just a few attempts, rarely giving
        an anchor enough dwell time as "next" for
        _record_next_anchor_trend's quarantine_trend_min_history samples to
        accumulate and trigger quarantine in the first place. bounded_evidence
        (and especially alias-aware's stricter requirement) made anchors
        dwell as "next" far longer, which is what first gave quarantine the
        opportunity to fire mid-promotion and expose the mismatch.
        """
        next_index = current_index - 1
        # 2026-07-15: quarantine_next_quality_enabled populates the same
        # _quarantined_anchor_indices set via a different mechanism (see
        # _record_next_anchor_quality) and must also trigger skip-ahead here
        # even if sequential_pair_quarantine_enabled itself is off.
        if self.sequential_pair_quarantine_enabled or self.quarantine_next_quality_enabled:
            while next_index in self._quarantined_anchor_indices and next_index >= 0:
                next_index -= 1
        return next_index

    def progress(self) -> Optional[RelativeStartProgress]:
        if not self.enabled or not self._return_started:
            return None
        anchor_progress = self._anchor_progress()
        if anchor_progress is not None:
            return anchor_progress
        arc_progress = self._arc_length_progress()
        if arc_progress is not None:
            return arc_progress
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

    def current_absolute_pose_from_start(self) -> list[float]:
        """Action-integrated (non-oracle) current pose relative to the outbound start.

        Composes the return-start absolute pose with the return-phase odometry
        delta accumulated so far. Only valid once ``finalize_outbound()`` has run
        (guaranteed for any caller reachable from ``update_return_motion``, which
        guards on ``self._return_started``). Used to feed a dead-reckoning yaw
        reference into non-oracle relocalization backends (P1 heading-consistency
        gate) without leaking Isaac's privileged ground-truth pose.
        """
        return compose_pose(self._return_start_pose_from_start, self._return_pose_from_return_start)

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
        previous_pose = self.anchors[-1].pose_from_start if self.anchors else [0.0, 0.0, 0.0]
        edge_from_previous = relative_delta(previous_pose, self._outbound_pose_from_start)
        if self.multiframe_anchor_window > 1:
            merged = self._merge_outbound_frame_buffer(self._outbound_pose_from_start)
            if merged is not None:
                descriptor = merged
        anchor = RouteAnchor(
            index=len(self.anchors),
            pose_from_start=[float(x) for x in self._outbound_pose_from_start],
            distance_from_start_m=float(self._outbound_distance_m),
            descriptor=descriptor,
            metadata=dict(metadata or {}),
            edge_from_previous=[float(x) for x in edge_from_previous],
        )
        self.anchors.append(anchor)
        self._last_anchor_distance_m = self._outbound_distance_m

    def _merge_outbound_frame_buffer(self, anchor_pose: list[float]) -> Optional[dict]:
        """Merge self._outbound_frame_buffer's per-frame descriptors into one
        submap expressed in anchor_pose's own body frame. Each buffered
        frame's own points are transformed body(old-capture) -> world ->
        body(anchor) via the same SE(2) composition compose_pose/
        relative_delta already use elsewhere in this file, just applied to a
        point array instead of a single pose. Tries the same descriptor keys
        _descriptor_local_map_points_raw (relocalization.py) checks, in the
        same priority order, so this matches whatever key this project's
        live LiDAR pipeline actually populates."""
        ax, ay, atheta = [float(v) for v in anchor_pose]
        cos_a, sin_a = math.cos(atheta), math.sin(atheta)
        merged_points: list[np.ndarray] = []
        used_key: Optional[str] = None
        for pose_at_capture, desc in self._outbound_frame_buffer:
            if not isinstance(desc, dict):
                continue
            points = None
            for key in ("local_map_points_body", "lidar_points_body", "scan_points_body", "height_scan_points_body"):
                candidate = desc.get(key)
                if candidate is not None:
                    points = candidate
                    used_key = used_key or key
                    break
            if points is None:
                continue
            arr = np.asarray(points, dtype=np.float32)
            if arr.ndim == 3 and arr.shape[0] == 1:
                arr = arr[0]
            if arr.ndim != 2 or arr.shape[1] < 2 or arr.shape[0] == 0:
                continue
            ox, oy, otheta = [float(v) for v in pose_at_capture]
            cos_o, sin_o = math.cos(otheta), math.sin(otheta)
            world_x = ox + cos_o * arr[:, 0] - sin_o * arr[:, 1]
            world_y = oy + sin_o * arr[:, 0] + cos_o * arr[:, 1]
            dx_w, dy_w = world_x - ax, world_y - ay
            anchor_x = dx_w * cos_a + dy_w * sin_a
            anchor_y = -dx_w * sin_a + dy_w * cos_a
            if arr.shape[1] >= 3:
                transformed = np.stack([anchor_x, anchor_y, arr[:, 2]], axis=1)
            else:
                transformed = np.stack([anchor_x, anchor_y], axis=1)
            merged_points.append(transformed.astype(np.float32))
        if not merged_points:
            return None
        return {(used_key or "local_map_points_body"): np.concatenate(merged_points, axis=0)}

    def _anchor_summary(self, anchor: RouteAnchor) -> dict:
        return {
            "index": int(anchor.index),
            "pose_from_start": [float(x) for x in anchor.pose_from_start],
            "distance_from_start_m": float(anchor.distance_from_start_m),
            "route_remaining_to_start_m": float(anchor.route_remaining_to_start_m),
            "descriptor": self._descriptor_summary(anchor.descriptor),
            "metadata": dict(anchor.metadata),
            # 2026-07-10: previously dropped here, so offline analyses could never
            # check alias_score against other diagnostics after the fact (see
            # investigations/2026-07-09-.../DATA.md §G and
            # investigations/2026-07-10-.../FINDINGS.md's methodology notes).
            # None until compute_anchor_alias_scores() has run (alias_aware off).
            "alias_score": (float(anchor.alias_score) if anchor.alias_score is not None else None),
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

    def _temporally_smooth_relocalization(self, new_estimate: AnchorRelocalization) -> AnchorRelocalization:
        """Direction 1 (persistent-error fix): blend a fresh accepted estimate with
        the previous filtered belief (reprojected onto the new estimate's anchor)
        instead of overwriting it outright, so single-observation heading/position
        jitter is damped across successive relocalization events. Mirrors
        ArcLengthParticleFilter's predict/observe split, but for the 2-D
        anchor-relative pose rather than 1-D arc length.

        _orientation_filter_weight decays each update (orientation_filter_decay)
        so a stale belief's influence fades out as new evidence arrives, and a
        fresh estimate that disagrees sharply with the carried belief is trusted
        outright rather than averaged toward a stale value.
        """
        if not new_estimate.anchor_heading_reliable:
            self._orientation_filter_weight = float(new_estimate.confidence)
            return new_estimate
        previous = self._latest_relocalization
        if previous is None or not previous.anchor_heading_reliable:
            self._orientation_filter_weight = float(new_estimate.confidence)
            return new_estimate
        projected = self._reproject_delta_to_anchor(
            previous.anchor_index,
            previous.anchor_dx_m,
            previous.anchor_dy_m,
            previous.anchor_dtheta_rad,
            new_estimate.anchor_index,
        )
        if projected is None:
            self._orientation_filter_weight = float(new_estimate.confidence)
            return new_estimate
        prev_dx, prev_dy, prev_dtheta = projected
        disagreement = self._reconciliation_disagreement(
            prev_dx, prev_dy, prev_dtheta,
            new_estimate.anchor_dx_m, new_estimate.anchor_dy_m, new_estimate.anchor_dtheta_rad,
        )
        if disagreement > self.orientation_filter_max_disagreement_rad:
            self._orientation_filter_weight = float(new_estimate.confidence)
            return new_estimate
        old_weight = self._orientation_filter_weight * self.orientation_filter_decay
        new_weight = float(new_estimate.confidence)
        total_weight = old_weight + new_weight
        if total_weight <= 1e-9:
            self._orientation_filter_weight = new_weight
            return new_estimate
        if self.sequential_pair_closure_reconciliation_signal == "bearing":
            # 2026-07-13: never circular-mean dtheta across time in this mode
            # -- trust the fresh reading's own raw dtheta unchanged, matching
            # the same "never blend rotation" rule applied in
            # _sequential_pair_closure_belief_fusion.
            blended_dtheta = new_estimate.anchor_dtheta_rad
        else:
            blended_dtheta = circular_weighted_mean(
                [(prev_dtheta, old_weight), (new_estimate.anchor_dtheta_rad, new_weight)]
            )
            if blended_dtheta is None:
                self._orientation_filter_weight = new_weight
                return new_estimate
        blended_dx = (old_weight * prev_dx + new_weight * new_estimate.anchor_dx_m) / total_weight
        blended_dy = (old_weight * prev_dy + new_weight * new_estimate.anchor_dy_m) / total_weight
        self._orientation_filter_weight = min(self.orientation_filter_max_weight, total_weight)
        return replace(
            new_estimate,
            anchor_dx_m=float(blended_dx),
            anchor_dy_m=float(blended_dy),
            anchor_dtheta_rad=float(blended_dtheta),
            backend=f"{new_estimate.backend}+ema",
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
            # Relative-edge pose graph (2026-07-02): current_pose_from_anchor[0]
            # is the forward offset of current within the matched anchor's OWN
            # locally-recorded frame, which approximates the route's local
            # tangent at that anchor (the robot generally faces along its path
            # while navigating outbound). Combined with the anchor's own robust
            # scalar distance_from_start_m, this avoids the old global
            # nearest-segment search over every anchor pair's pose_from_start
            # (drift-prone -- see _project_pose_to_route_distance); this hot
            # path (every accepted relocalization) now touches only the ONE
            # matched anchor's local data, nothing chained from anchor 0.
            observed_s = anchor.distance_from_start_m + current_pose_from_anchor[0]
            observed_s = float(max(0.0, min(self._outbound_distance_m, observed_s)))
            sigma = max(0.45, min(2.0, estimate.distance_to_anchor_m + 0.5 * self.anchor_spacing_m))
            if (
                estimate.degeneracy_ratio is not None
                and estimate.degeneracy_ratio < self.corridor_degeneracy_inflate_threshold
            ):
                # P2: the accepted candidate came from a geometrically weak (near-corridor)
                # anchor patch even though it passed the harder skip threshold upstream in
                # relocalization.py. Trust it less instead of feeding the filter a falsely
                # tight sigma, so std widens rather than collapsing onto a shaky estimate.
                sigma *= 2.0
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

    def _reconciliation_disagreement(
        self,
        a_dx: float, a_dy: float, a_dtheta: float,
        b_dx: float, b_dy: float, b_dtheta: float,
    ) -> float:
        """Disagreement metric used by both the closure-check cross-anchor
        fusion and the temporal-smoothing EMA to decide how much two readings
        of (implicitly) the same physical situation conflict -- 2026-07-13,
        see sequential_pair_closure_reconciliation_signal's docstring in
        __init__. "dtheta" (default) compares the two readings' rotation
        estimates directly, same as this project's original design. "bearing"
        instead compares the two readings' direction-to-anchor (the quantity
        this project's hint/arbiter actually consumes), sidestepping dtheta
        entirely for the trust/disagreement decision.
        """
        if self.sequential_pair_closure_reconciliation_signal == "bearing":
            bearing_a = math.atan2(a_dy, a_dx)
            bearing_b = math.atan2(b_dy, b_dx)
            return abs(wrap_angle(bearing_b - bearing_a))
        return abs(wrap_angle(b_dtheta - a_dtheta))

    def _sequential_pair_closure_precheck(
        self,
        estimates: list[AnchorRelocalization],
    ) -> tuple[list[AnchorRelocalization], Optional[str]]:
        """User-proposed cross-check (2026-07-04): sequential_pair_anchor_relocalization
        returns an independent ICP fit against BOTH the current and next anchor
        every attempt. The two implied robot-to-anchor vectors, reprojected into
        a common anchor frame via _reproject_delta_to_anchor, should agree with
        each other up to the true current-to-next anchor displacement -- a
        mismatch means at least one side's ICP fit is unreliable.

        Verified against this project's own real overshoot data before being
        wired in: catches 3 of 4 known single-bad-ICP-read overshoot triggers
        (ep4, ep5, ep678), where one side's raw reading was badly wrong while the
        other was clean. Confirmed NOT to catch the case where both anchors'
        fits are simultaneously, correlatedly wrong (ep368 anchor 3/2, both
        heading_consistency_error ~1.5 rad already at the time) -- that residual
        failure mode is explicitly out of scope here (left to a separate
        bad-anchor-quarantine mechanism); this check cannot distinguish "both
        wrong the same way" from "both right", so it is not expected to help
        there, and does not need to.

        Returns (possibly-reconstructed estimates, reject_reason). The estimate
        list is returned unmodified with reject_reason=None when there is
        nothing to cross-check (fewer than two distinct anchors) or the two
        sides already agree. When they disagree and one side's quality
        (confidence * sqrt(inlier_count)) clearly dominates, the weaker side's
        (dx, dy, dtheta) is replaced with a value reprojected from the stronger
        side (this is the "recompute the disagreeing line from the other two
        knowns" reconstruction) rather than discarded outright, so a
        persistently noisy anchor does not have to independently pass its own
        acceptance gate to let progress continue. When neither side clearly
        dominates, this returns reject_reason="sequential_pair_closure_mismatch"
        -- mirroring this project's existing "genuinely ambiguous, no candidate"
        policy for other backends (fused/scan_context margin checks) rather than
        guessing which side to trust.
        """
        if not self.sequential_pair_closure_check_enabled or len(estimates) < 2:
            return estimates, None
        by_anchor: dict[int, AnchorRelocalization] = {}
        for est in estimates:
            by_anchor.setdefault(int(est.anchor_index), est)
        if len(by_anchor) < 2:
            return estimates, None
        # sequential_pair only ever offers exactly {current, next}; if that ever
        # changes this simply cross-checks the first two distinct anchors seen.
        a_idx, b_idx = sorted(by_anchor)[:2]
        a, b = by_anchor[a_idx], by_anchor[b_idx]
        reprojected_b = self._reproject_delta_to_anchor(
            b.anchor_index, b.anchor_dx_m, b.anchor_dy_m, b.anchor_dtheta_rad, a.anchor_index,
        )
        if reprojected_b is None:
            return estimates, None
        dx, dy, dtheta = reprojected_b
        position_disagreement = math.hypot(dx - a.anchor_dx_m, dy - a.anchor_dy_m)
        heading_disagreement = self._reconciliation_disagreement(
            a.anchor_dx_m, a.anchor_dy_m, a.anchor_dtheta_rad, dx, dy, dtheta,
        )
        if (
            position_disagreement <= self.sequential_pair_closure_max_position_disagreement_m
            and heading_disagreement <= self.sequential_pair_closure_max_heading_disagreement_rad
        ):
            return estimates, None

        if self.sequential_pair_closure_mode == "belief":
            if (
                self.sequential_pair_closure_belief_trust_aware_guard
                and (
                    position_disagreement > self.sequential_pair_closure_belief_large_position_disagreement_m
                    or heading_disagreement > self.sequential_pair_closure_belief_large_heading_disagreement_rad
                )
            ):
                guarded = self._sequential_pair_closure_belief_trust_aware_reconstruct(
                    estimates, a, b, dx, dy, dtheta,
                )
                if guarded is not None:
                    return guarded
            return self._sequential_pair_closure_belief_fusion(
                estimates, a, b, dx, dy, dtheta, position_disagreement,
            )

        a_quality = float(a.confidence) * math.sqrt(max(1, int(a.inlier_count or 1)))
        b_quality = float(b.confidence) * math.sqrt(max(1, int(b.inlier_count or 1)))
        if b_quality > 1.5 * a_quality:
            reconstructed_a = replace(
                a,
                anchor_dx_m=float(dx),
                anchor_dy_m=float(dy),
                anchor_dtheta_rad=float(dtheta),
                confidence=float(min(a.confidence, b.confidence)),
                backend=f"{a.backend}+closure_reconstructed",
            )
            return [reconstructed_a if e is a else e for e in estimates], None
        if a_quality > 1.5 * b_quality:
            reprojected_a = self._reproject_delta_to_anchor(
                a.anchor_index, a.anchor_dx_m, a.anchor_dy_m, a.anchor_dtheta_rad, b.anchor_index,
            )
            if reprojected_a is None:
                return estimates, None
            rdx, rdy, rdtheta = reprojected_a
            reconstructed_b = replace(
                b,
                anchor_dx_m=float(rdx),
                anchor_dy_m=float(rdy),
                anchor_dtheta_rad=float(rdtheta),
                confidence=float(min(a.confidence, b.confidence)),
                backend=f"{b.backend}+closure_reconstructed",
            )
            return [reconstructed_b if e is b else e for e in estimates], None
        return estimates, "sequential_pair_closure_mismatch"

    def _candidate_is_trustworthy(self, estimate: AnchorRelocalization) -> bool:
        """Whether a candidate's own per-attempt diagnostics (not just its
        confidence*sqrt(inlier_count) quality score, which is already known
        to saturate near 1.0 even for anchors match_class flags as degenerate/
        ambiguous -- see ep680 anchor7) say its own ICP match is clean and
        unambiguous. match_class is only populated by the sequential_pair
        backend (relocalization.py); estimates from other sources leave it
        None, which is treated as "no reason to distrust it" rather than
        "trustworthy" or "untrustworthy" -- see
        _sequential_pair_closure_belief_trust_aware_reconstruct's handling of
        that case."""
        if estimate.match_class not in (None, "clean_full_pose"):
            return False
        if estimate.near_tie_basin_count and estimate.near_tie_basin_count > 0:
            return False
        return True

    def _sequential_pair_closure_belief_trust_aware_reconstruct(
        self,
        estimates: list[AnchorRelocalization],
        a: AnchorRelocalization,
        b: AnchorRelocalization,
        b_dx_in_a_frame: float,
        b_dy_in_a_frame: float,
        b_dtheta_in_a_frame: float,
    ) -> Optional[tuple[list[AnchorRelocalization], Optional[str]]]:
        """Guard against belief-mode's circular_weighted_mean blend being
        numerically unstable when a and b disagree by a large (near-
        antipodal) amount -- confirmed on real data (2026-07-07, ep187
        anchor14) that blending in a bimodal/unstable partner reading can
        swing the fused bearing by 100+ degrees even while the partner holds
        a minority fusion weight, because two angle vectors ~150 deg apart
        nearly cancel in the weighted sum, making the resultant direction
        hypersensitive to the exact weight split. anchor14's own raw ICP was
        accurate (~4 deg mean error) the entire time; the corruption was
        introduced entirely by blending in anchor13's own bimodal reading.

        When the disagreement is this large, treat it as a categorical
        mismatch (one side is just wrong, not "noisy enough to average out")
        rather than something to blend: if exactly one side's own
        diagnostics say it is trustworthy, keep that side's own reading
        unchanged and reconstruct the other purely from the known, fixed
        anchor-to-anchor edge geometry (_reproject_delta_to_anchor -- pure
        geometry composed from the once-recorded outbound edge chain, no
        accumulating odometry/dead-reckoning involved). This mirrors
        "threshold" mode's original dominant-side substitution above, just
        keyed off match_class/near_tie_basin_count instead of the
        confidence*sqrt(inlier_count) ratio.

        Returns None (signalling "fall through to the normal belief blend")
        when trust is ambiguous -- both or neither side's own diagnostics
        look clean -- since there is no principled way to pick a side from
        this signal in that case.
        """
        a_trustworthy = self._candidate_is_trustworthy(a)
        b_trustworthy = self._candidate_is_trustworthy(b)
        if a_trustworthy == b_trustworthy:
            return None
        discounted_confidence = float(min(a.confidence, b.confidence))
        if b_trustworthy:
            reconstructed_a = replace(
                a,
                anchor_dx_m=float(b_dx_in_a_frame),
                anchor_dy_m=float(b_dy_in_a_frame),
                anchor_dtheta_rad=float(b_dtheta_in_a_frame),
                confidence=discounted_confidence,
                backend=f"{a.backend}+belief_trust_aware_reconstructed",
            )
            return [reconstructed_a if e is a else e for e in estimates], None
        reprojected_a = self._reproject_delta_to_anchor(
            a.anchor_index, a.anchor_dx_m, a.anchor_dy_m, a.anchor_dtheta_rad, b.anchor_index,
        )
        if reprojected_a is None:
            return None
        rdx, rdy, rdtheta = reprojected_a
        reconstructed_b = replace(
            b,
            anchor_dx_m=float(rdx),
            anchor_dy_m=float(rdy),
            anchor_dtheta_rad=float(rdtheta),
            confidence=discounted_confidence,
            backend=f"{b.backend}+belief_trust_aware_reconstructed",
        )
        return [reconstructed_b if e is b else e for e in estimates], None

    def _closure_disagreement_sigma_m(self, estimate: AnchorRelocalization) -> float:
        """Distance-dependent noise scale for one side of a closure cross-check,
        reusing the exact formula _estimate_arc_observation already applies to
        ICP-derived arc-length observations -- deliberately not a new magic
        number, just the project's existing "how much to trust an ICP read at
        this distance" belief applied to the closure comparison too."""
        return max(0.45, min(2.0, estimate.distance_to_anchor_m + 0.5 * self.anchor_spacing_m))

    def _sequential_pair_closure_belief_fusion(
        self,
        estimates: list[AnchorRelocalization],
        a: AnchorRelocalization,
        b: AnchorRelocalization,
        b_dx_in_a_frame: float,
        b_dy_in_a_frame: float,
        b_dtheta_in_a_frame: float,
        position_disagreement_m: float,
    ) -> tuple[list[AnchorRelocalization], Optional[str]]:
        """Belief-curve closure check (user-proposed 2026-07-05): replaces the
        "threshold" mode's magic 1.5x quality ratio and fixed disagreement caps
        with a continuous fusion. Two things are known for certain -- the
        anchor-to-anchor geometry (already folded into b_dx/dy/dtheta_in_a_frame
        via _reproject_delta_to_anchor) and that the robot only ever draws
        closer to "next" -- everything else (current's and next's own
        anchor-relative readings) can be off by an amount that is either normal
        ICP noise or a real failure; this function's job is only to weigh the
        two readings against each other, never to declare the attempt a total
        loss.

        current and next are always blended, weighted by their own ICP quality
        (confidence * sqrt(inlier_count), same quality score "threshold" mode
        already computes), and the disagreement (scaled by the same
        distance-dependent sigma _estimate_arc_observation uses -- see
        _closure_disagreement_sigma_m) discounts the fused confidence smoothly
        rather than ever rejecting the attempt outright. This matters because
        _sequence_match_observation's "no_sequence_candidates" gate depends on
        _distance_since_sequence_observation_m staying near zero (it only
        resets on an accepted observation); an outright reject skips that
        reset and, confirmed against real batch data (2026-07-05), can cascade
        into a permanent, unrecoverable stall once dead-reckoning drift
        compounds past that gate's own tolerance -- five of seven regressed
        episodes in that batch showed exactly this signature. Always producing
        a (possibly low-confidence) fused estimate lets _sequence_match_
        observation's existing score-based competition deprioritize a bad
        fusion naturally, instead of a second, redundant hard gate deciding it
        in advance.
        """
        a_quality = float(a.confidence) * math.sqrt(max(1, int(a.inlier_count or 1)))
        b_quality = float(b.confidence) * math.sqrt(max(1, int(b.inlier_count or 1)))
        total_quality = a_quality + b_quality
        if total_quality <= 1e-9:
            weight_a = weight_b = 0.5
        else:
            weight_a = a_quality / total_quality
            weight_b = b_quality / total_quality

        fused_dx = weight_a * a.anchor_dx_m + weight_b * b_dx_in_a_frame
        fused_dy = weight_a * a.anchor_dy_m + weight_b * b_dy_in_a_frame
        if self.sequential_pair_closure_reconciliation_signal == "bearing":
            # 2026-07-13: never circular-mean dtheta in this mode (the exact
            # operation proven unstable for large disagreements) -- carry
            # through whichever side's own raw dtheta is dominant by quality,
            # unblended. Position (which determines bearing, the quantity
            # actually consumed downstream) is still fused above as usual.
            fused_dtheta = a.anchor_dtheta_rad if weight_a >= weight_b else b_dtheta_in_a_frame
        else:
            fused_dtheta = circular_weighted_mean(
                [(a.anchor_dtheta_rad, weight_a), (b_dtheta_in_a_frame, weight_b)]
            )
            if fused_dtheta is None:
                fused_dtheta = a.anchor_dtheta_rad

        sigma_a = self._closure_disagreement_sigma_m(a)
        sigma_b = self._closure_disagreement_sigma_m(b)
        z = position_disagreement_m / max(1e-6, math.hypot(sigma_a, sigma_b))
        # z <= 1 (disagreement within what ICP's own expected noise at this
        # distance would predict) leaves confidence essentially untouched;
        # confidence decays smoothly beyond that but never reaches zero, so a
        # fused-but-uncertain reading can still win the sequence filter's score
        # against dead reckoning alone when nothing better is available this
        # attempt -- there is deliberately no second, harder cutoff back to an
        # outright reject here (see docstring).
        disagreement_discount = 1.0 / (1.0 + max(0.0, z - 1.0))
        fused_confidence = max(0.05, float(min(a.confidence, b.confidence)) * disagreement_discount)

        fused_a = replace(
            a,
            anchor_dx_m=float(fused_dx), anchor_dy_m=float(fused_dy), anchor_dtheta_rad=float(fused_dtheta),
            confidence=float(fused_confidence), backend=f"{a.backend}+belief_fused",
        )
        reprojected_to_b = self._reproject_delta_to_anchor(
            a.anchor_index, fused_dx, fused_dy, fused_dtheta, b.anchor_index,
        )
        if reprojected_to_b is None:
            fused_b = replace(b, confidence=float(fused_confidence), backend=f"{b.backend}+belief_fused")
        else:
            bdx, bdy, bdtheta = reprojected_to_b
            fused_b = replace(
                b,
                anchor_dx_m=float(bdx), anchor_dy_m=float(bdy), anchor_dtheta_rad=float(bdtheta),
                confidence=float(fused_confidence), backend=f"{b.backend}+belief_fused",
            )
        replacements = {id(a): fused_a, id(b): fused_b}
        return [replacements.get(id(e), e) for e in estimates], None

    def _sequence_match_observation(
        self,
        estimates: list[AnchorRelocalization],
    ) -> tuple[Optional[AnchorRelocalization], Optional[SequenceArcObservation], Optional[str]]:
        estimates, closure_reject_reason = self._sequential_pair_closure_precheck(estimates)
        if closure_reject_reason is not None:
            return None, None, closure_reject_reason
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

        # Direction 2 (persistent-error fix): blend in other candidates from this
        # same query that agree with the top pick instead of discarding them.
        estimate = self._fuse_candidate_cluster(score, estimate, candidates)

        # Large-forward-jump confirmation gate (2026-07-02 ep680 fix, part 1/2):
        # sequence_forward_tolerance_m above only guards motion_error > 0 (looks
        # like we moved backward). It never guarded the opposite case -- s
        # collapsing implausibly far forward in one step, e.g. a single
        # confident-but-wrong ICP match claiming "arrived". Require a second,
        # independent observation to land near the same s before trusting a jump
        # this large; otherwise fall back to dead reckoning for this step.
        motion_error = observation.motion_error_m
        if (
            self._sequence_observation is not None
            and self._sequence_observation.source != "return_start_prior"
            and motion_error is not None
            and motion_error < -self.sequence_large_forward_jump_m
        ):
            pending = self._pending_jump_observed_s_m
            if (
                pending is not None
                and abs(observation.observed_s_m - pending) <= self.sequence_large_jump_confirm_tolerance_m
            ):
                # Second observation corroborates the first -- proceed to commit below.
                self._pending_jump_observed_s_m = None
                self._pending_jump_distance_marker_m = None
            else:
                self._pending_jump_observed_s_m = float(observation.observed_s_m)
                self._pending_jump_distance_marker_m = float(self._distance_since_sequence_observation_m)
                return None, None, "large_forward_jump_pending_confirmation"
        elif (
            self._pending_jump_observed_s_m is not None
            and self._distance_since_sequence_observation_m - (self._pending_jump_distance_marker_m or 0.0)
            > self.sequence_large_jump_confirm_window_m
        ):
            # Pending candidate never got corroborated within the window -- drop it as noise.
            self._pending_jump_observed_s_m = None
            self._pending_jump_distance_marker_m = None

        # VIO bridge (2026-07-02 ep680 fix, part 2/2): in the corridor dead zone
        # the arc-length position is ambiguous, so suppress updates when the
        # filter is uncertain and the candidate lands away from a feature anchor
        # (corner, doorway). The effective threshold widens the longer we go
        # without an accepted observation, so a filter that got stuck (e.g. by
        # a bad match that slipped past the gate above) can still eventually
        # accept a re-acquisition candidate instead of being frozen forever.
        effective_vio_threshold = self.vio_bridge_std_threshold_m + self.vio_bridge_relaxation_rate * max(
            0.0, self._distance_since_sequence_observation_m - self.vio_bridge_relaxation_grace_m
        )
        if (
            self.vio_bridge_enabled
            and self._arc_length_filter is not None
            and self._arc_length_filter.std() > effective_vio_threshold
            and not self._is_near_feature_anchor(observation.observed_s_m)
        ):
            return None, None, "vio_bridge_suppressed"

        self._sequence_observation = observation
        self._sequence_current_s_m = float(observation.observed_s_m)
        self._sequence_observation_history.append(asdict(observation))
        if len(self._sequence_observation_history) > self.sequence_window:
            self._sequence_observation_history = self._sequence_observation_history[-self.sequence_window:]
        self._distance_since_sequence_observation_m = 0.0
        self._pending_jump_observed_s_m = None
        self._pending_jump_distance_marker_m = None
        self._target_anchor_index = int(observation.anchor_index)
        self._target_anchor_min_distance_m = estimate.distance_to_anchor_m
        return estimate, observation, None

    def _fuse_candidate_cluster(
        self,
        top_score: float,
        top_estimate: AnchorRelocalization,
        scored_candidates: list[tuple[float, AnchorRelocalization, SequenceArcObservation]],
    ) -> AnchorRelocalization:
        """Direction 2 (persistent-error fix): average the top pick with other
        candidates from the *same* relocalization query that plausibly measure
        the same true pose, instead of keeping only the single highest-scored
        candidate. Reduces single-candidate noise in anchor_dtheta_rad/dx/dy.

        This must not reintroduce the P1 ambiguity in reverse: a candidate is
        only folded in if it is reprojected onto the top pick's own anchor and
        found to agree within tight heading/position tolerances. A genuinely
        competing hypothesis (e.g. the LoFTR +1-anchor bias) disagrees and is
        left out rather than averaged into a worse compromise estimate.
        """
        if not top_estimate.anchor_heading_reliable:
            return top_estimate
        weight_sum = max(1e-9, float(top_score))
        dx_sum = top_estimate.anchor_dx_m * top_score
        dy_sum = top_estimate.anchor_dy_m * top_score
        angle_pool = [(top_estimate.anchor_dtheta_rad, float(top_score))]
        fused_count = 1
        for score, estimate, _observation in scored_candidates[1:self.fusion_candidate_pool_size]:
            if score < self.fusion_min_score_ratio * top_score:
                continue
            if not estimate.anchor_heading_reliable:
                continue
            if estimate.anchor_index == top_estimate.anchor_index:
                dx, dy, dtheta = estimate.anchor_dx_m, estimate.anchor_dy_m, estimate.anchor_dtheta_rad
            else:
                projected = self._reproject_delta_to_anchor(
                    estimate.anchor_index,
                    estimate.anchor_dx_m,
                    estimate.anchor_dy_m,
                    estimate.anchor_dtheta_rad,
                    top_estimate.anchor_index,
                )
                if projected is None:
                    continue
                dx, dy, dtheta = projected
            heading_disagreement = abs(wrap_angle(dtheta - top_estimate.anchor_dtheta_rad))
            if heading_disagreement > self.fusion_max_heading_disagreement_rad:
                continue
            position_disagreement = math.hypot(dx - top_estimate.anchor_dx_m, dy - top_estimate.anchor_dy_m)
            if position_disagreement > self.fusion_max_position_disagreement_m:
                continue
            weight_sum += score
            dx_sum += dx * score
            dy_sum += dy * score
            angle_pool.append((dtheta, float(score)))
            fused_count += 1
        if fused_count == 1:
            return top_estimate
        fused_dtheta = circular_weighted_mean(angle_pool)
        if fused_dtheta is None:
            return top_estimate
        return replace(
            top_estimate,
            anchor_dx_m=float(dx_sum / weight_sum),
            anchor_dy_m=float(dy_sum / weight_sum),
            anchor_dtheta_rad=float(fused_dtheta),
            backend=f"{top_estimate.backend}+fused{fused_count}",
        )

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

    def _compose_edges_between(self, from_index: int, to_index: int) -> Optional[list[float]]:
        """Relative-edge pose graph (2026-07-02): compose only the local
        edge_from_previous deltas strictly between from_index and to_index (never
        routing through anchor 0), returning "to_index as seen from from_index".

        This bounds compounding error to the number of hops actually separating
        the two anchors (usually 1-2 for the P1/Direction-1/Direction-2 callers
        below), instead of each anchor's full outbound-accumulated
        pose_from_start -- differencing two long independent chains does not
        cancel their drift, it adds it.
        """
        if from_index == to_index:
            return [0.0, 0.0, 0.0]
        if self._anchor_by_index(from_index) is None or self._anchor_by_index(to_index) is None:
            return None
        step = 1 if to_index > from_index else -1
        pose = [0.0, 0.0, 0.0]
        idx = from_index
        while idx != to_index:
            nxt = idx + step
            edge_anchor = self._anchor_by_index(nxt if step > 0 else idx)
            if edge_anchor is None:
                return None
            edge = edge_anchor.edge_from_previous if step > 0 else inverse_delta(edge_anchor.edge_from_previous)
            pose = compose_pose(pose, edge)
            idx = nxt
        return pose

    def _oracle_edge_between(self, from_index: int, to_index: int) -> Optional[list[float]]:
        """Ground-truth counterpart to _compose_edges_between: "to_index as seen
        from from_index", computed directly from both anchors'
        metadata["world_pose"] (isaac_oracle_for_relocalization_eval) instead of
        chaining the accumulated, outbound-odometry-derived edge_from_previous
        deltas. Unlike the accumulated version this needs no hop-chaining -- both
        endpoints carry an absolute ground-truth pose already -- and it does not
        accumulate drift with hop count. Used only when
        sequential_pair_geometry_source == "oracle", an explicit ablation flag to
        isolate whether anchor-to-anchor geometry error (not ICP/odometry error)
        explains a given failure; never active by default.
        """
        if from_index == to_index:
            return [0.0, 0.0, 0.0]
        from_anchor = self._anchor_by_index(from_index)
        to_anchor = self._anchor_by_index(to_index)
        if from_anchor is None or to_anchor is None:
            return None
        from_pose = from_anchor.metadata.get("world_pose") if from_anchor.metadata else None
        to_pose = to_anchor.metadata.get("world_pose") if to_anchor.metadata else None
        if from_pose is None or to_pose is None:
            return None
        return relative_delta(world_pose_7_to_2d(from_pose), world_pose_7_to_2d(to_pose))

    def _anchor_edge_between(self, from_index: int, to_index: int) -> Optional[list[float]]:
        """Dispatch to the configured anchor-to-anchor geometry source
        (sequential_pair_geometry_source: "accumulated" [default, non-privileged
        edge_from_previous chain] or "oracle" [ground-truth world_pose diff,
        ablation-only])."""
        if self.sequential_pair_geometry_source == "oracle":
            return self._oracle_edge_between(from_index, to_index)
        return self._compose_edges_between(from_index, to_index)

    def _reproject_delta_to_anchor(
        self,
        source_anchor_index: int,
        dx: float,
        dy: float,
        dtheta: float,
        target_anchor_index: int,
    ) -> Optional[list[float]]:
        """Re-express a (dx, dy, dtheta) delta "anchor as seen from current" so it
        is relative to a different anchor, by composing the short local edge
        chain between the two anchors (see _compose_edges_between /
        _anchor_edge_between) rather than differencing their two full
        outbound-accumulated poses. Pure geometry, no AnchorRelocalization
        bookkeeping — shared by _project_estimate_to_anchor and the Direction 1/2
        fusion helpers below."""
        target_pose_in_source_frame = self._anchor_edge_between(source_anchor_index, target_anchor_index)
        if target_pose_in_source_frame is None:
            return None
        current_pose_in_source_frame = inverse_delta([dx, dy, dtheta])
        return relative_delta(current_pose_in_source_frame, target_pose_in_source_frame)

    def _project_estimate_to_anchor(
        self,
        estimate: AnchorRelocalization,
        target_anchor_index: int,
    ) -> Optional[AnchorRelocalization]:
        target_pose_from_current = self._reproject_delta_to_anchor(
            estimate.anchor_index,
            estimate.anchor_dx_m,
            estimate.anchor_dy_m,
            estimate.anchor_dtheta_rad,
            target_anchor_index,
        )
        if target_pose_from_current is None:
            return None
        backend = estimate.backend
        if not backend.endswith("+monotonic"):
            backend = f"{backend}+monotonic"
        return replace(
            estimate,
            anchor_index=int(target_anchor_index),
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

    def target_anchor_for_route_position(
        self,
        route_s_m: float,
        *,
        require_world_pose: bool = False,
    ) -> Optional[RouteAnchor]:
        if not self.anchors:
            return None
        route_s = float(route_s_m)
        candidates = [
            anchor for anchor in self.anchors
            if not require_world_pose or anchor.metadata.get("world_pose") is not None
        ]
        if not candidates:
            return None
        eligible = [
            anchor for anchor in candidates
            if anchor.distance_from_start_m <= route_s + 1e-6
        ]
        if eligible:
            return max(eligible, key=lambda anchor: anchor.distance_from_start_m)
        return min(candidates, key=lambda anchor: anchor.distance_from_start_m)

    def _target_anchor_for_remaining_distance(self, remaining_m: float) -> Optional[RouteAnchor]:
        return self.target_anchor_for_route_position(remaining_m)

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
        target_s = max(0.0, float(remaining) - max(0.0, self.route_progress_lookahead_m))
        target_anchor = self._target_anchor_for_remaining_distance(target_s)

        estimate = self._latest_relocalization
        dx = integrated_progress.target_dx_m
        dy = integrated_progress.target_dy_m
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
            target_estimate = None
            if estimate is not None and estimate.anchor_heading_reliable:
                target_estimate = (
                    estimate
                    if estimate.anchor_index == target_anchor.index
                    else self._project_estimate_to_anchor(estimate, target_anchor.index)
                )
            if target_estimate is not None:
                anchor_dx = float(target_estimate.anchor_dx_m)
                anchor_dy = float(target_estimate.anchor_dy_m)
                distance_to_anchor = target_estimate.distance_to_anchor_m
                bearing_to_anchor = target_estimate.bearing_to_anchor_deg
                dx = anchor_dx
                dy = anchor_dy
            elif estimate is not None and estimate.anchor_index == target_anchor.index:
                anchor_dx = float(estimate.anchor_dx_m)
                anchor_dy = float(estimate.anchor_dy_m)
                distance_to_anchor = estimate.distance_to_anchor_m
                bearing_to_anchor = estimate.bearing_to_anchor_deg
                dx = anchor_dx
                dy = anchor_dy
            else:
                along_route_gap = max(0.0, remaining - target_anchor.distance_from_start_m)
                distance_to_anchor = float(along_route_gap)
                bearing_to_anchor = 0.0
                dx = float(along_route_gap)
                dy = 0.0

        distance_for_bearing = distance_to_anchor if distance_to_anchor is not None else remaining
        bearing = float(math.degrees(math.atan2(dy, dx))) if distance_for_bearing > 1e-6 else 0.0

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
        # 2026-07-14: previously composed anchor_dtheta_rad with the anchor's
        # recorded pose_from_start to point straight at the (possibly distant)
        # start -- a straight-line vector blind to corridor shape (cuts
        # through walls on an L-turn) and vulnerable to raw ICP dtheta being
        # confidently wrong by ~180 deg on symmetric corridors. Mirror
        # direct_oracle_route_anchor_progress's convention instead: point at
        # the nearby tracked anchor via plain ICP translation, no dtheta.
        dx = estimate.anchor_dx_m
        dy = estimate.anchor_dy_m
        distance_to_start = float(estimate.distance_to_anchor_m + anchor.route_remaining_to_start_m)
        bearing_to_start = float(math.degrees(math.atan2(dy, dx))) if distance_to_start > 1e-6 else 0.0
        # 2026-07-13, per the Oracle-to-shadow hint-source swap plan: this path
        # (anchor/sequential_pair-sourced progress) never populated
        # filter_std_m, so _filter_lost() always returned False here -- the
        # "suppress arrival claims when uncertain" wording gate only ever
        # worked on the legacy arc-length-filter progress path. Approximate an
        # equivalent positional-uncertainty proxy by inflating the same
        # distance-dependent ICP noise scale _closure_disagreement_sigma_m
        # already uses elsewhere by how far below full confidence this
        # estimate is -- confidence=1.0 keeps std at the plain ICP noise floor
        # (well under _filter_lost's >=2.5m threshold, i.e. "not lost");
        # confidence near 0 inflates it well past that threshold. Not a
        # rigorously calibrated filter (there's no real particle filter on
        # this path to measure), just enough for the existing wording gate to
        # actually engage instead of being silently dead code on this path.
        reported_confidence = self._current_reported_confidence(estimate)
        filter_std_m = self._closure_disagreement_sigma_m(estimate) / max(0.05, reported_confidence)
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
            relocalization_confidence=float(reported_confidence),
            relocalization_backend=estimate.backend,
            filter_std_m=float(filter_std_m),
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
        if progress.source == "direct_oracle_route_anchor" or progress.anchor_dx_m is not None:
            vector_label = "next-anchor vector"
        else:
            vector_label = "odometry next-anchor vector" if progress.anchor_heading_reliable is False else "next-anchor vector"

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
