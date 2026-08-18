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
    # 2026-08-03 (line-2 Phase 1.2, mechanism E -- investigations/2026-07-28-
    # downgrade-batch-mechanism-failure-classification/FINDINGS.md/
    # MODIFICATION_PLAN.md): min_relocalization_confidence above gates TWO
    # different-risk actions under one bar -- overriding the VLM's chosen
    # movement direction (genuinely risky under uncertainty, 0.90 is
    # appropriate) and suppressing a voluntary `stop` (a much lower-stakes,
    # more conservative action -- only needs "probably still far", not
    # "confidently know which way to go"). Below 0.90 the arbiter previously
    # went silent on BOTH, so an erroneous stop under low confidence sailed
    # through unchallenged unless stop_gate's own (separately gapped, see
    # mechanism D) corroboration happened to catch it (ep368 in that audit).
    # When stop_veto_enabled, a `stop` output specifically gets its own,
    # independently-gated suppression path using stop_veto_min_confidence
    # (typically well below min_relocalization_confidence) and the anchor's
    # own static route_remaining (not the noisy live distance) -- the same
    # anchor-corroboration idea stop_gate itself already uses. Off by
    # default; direction-override behavior above is completely unchanged.
    stop_veto_enabled: bool = False
    stop_veto_min_confidence: float = 0.5
    stop_veto_anchor_remaining_min_m: float = 3.0
    # 2026-08-15 (investigations/2026-08-15-hint-action-turn-gate-fix). Off by
    # default. Root-caused via real ground-truth data on batch
    # line2_closure_off_cooldown_kdtree_100ep_20260815 (ep646/ep889): the hint
    # bearing was verified accurate to within 0.6-12 deg of the true direction
    # at every checked step, but the required correction was a large
    # (~110-150 deg) in-place turn. The arbiter forced it at most once, then
    # spent the next many VLM queries either declining
    # (occupied_in_local_map_path -- the clear-path check tests the
    # STRAIGHT-LINE path toward the anchor, which is a meaningful safety
    # question for a `forward` override but physically meaningless for a
    # turn-in-place command that involves zero translation) or simply never
    # getting re-gated before relocalization confidence degraded (a real but
    # LATER, downstream consequence of the uncorrected drift, not the
    # trigger) and hint guidance went silent for the rest of the episode.
    # When true: (1) skip the clear-path gate entirely for `left`/`right`
    # overrides (kept unchanged for `forward`, which does carry real
    # collision risk if executed open-loop); (2) the resulting turn command
    # rotates by the ACTUAL bearing-derived angle in one shot. Computed and
    # returned as a structured (velocity command, duration) pair on
    # HintActionDecision (override_command/override_duration_s) rather than
    # as text routed through get_vel_command() (eval_utils.py, called on
    # every VLM output project-wide, deliberately left completely untouched
    # -- an earlier attempt to have this emit literal-angle TEXT and let
    # get_vel_command parse it was reverted after a real-data audit found
    # that function's text parsing unsafe to generalize, see its 2026-08-15
    # revert note; round_trip_eval.py uses these structured fields directly
    # instead of re-parsing replacement_output when they are present, so
    # get_vel_command's own logic/behavior is provably unaffected for every
    # other caller). replacement_output still carries the real angle in text
    # form for human-readable logging only. Estimated to directly explain ep646, ep889, ep1062, ep829 (and
    # partially ep366) on the above batch; NOT the dominant failure pattern
    # among hint-related failures overall -- see
    # investigations/2026-08-15-hint-confidence-collapse-patterns for the
    # larger group this does not address.
    turn_override_completes_full_angle: bool = False
    # 2026-08-15 (investigations/2026-08-15-hint-confidence-collapse-patterns).
    # Off by default. Ports stop_gate.py's already-implemented/tested
    # trend_confidence mechanism (same window/vote/spread parameters, same
    # _trend_confidence_trusts logic) to this arbiter's own
    # relocalization_confidence gate. Root-caused via real per-attempt ICP
    # diagnostics (not the production log, which only records the selected
    # current-role estimate -- recomputed fresh against the real captured
    # point cloud) on batch line2_closure_off_cooldown_kdtree_100ep_20260815:
    # a single low-confidence reading permanently silences all hint guidance
    # for the rest of the episode (this check has no window/trend of its
    # own), for two different reasons that get conflated under one symptom --
    # (a) genuine, persistent ICP ambiguity at a specific anchor (stable
    # match_class="ambiguous_high_confidence" over 175 real steps, e.g.
    # ep814's anchor4) -- this fix does NOT resolve that case, a persistent
    # ambiguity does not average out; (b) a reading that is actually accurate
    # (estimated distance close to ground truth) but whose raw confidence
    # noisily dips below the 0.90 threshold, sometimes on the very FIRST
    # attempt of the whole return phase (e.g. ep484: true=0.54m, est=0.59m,
    # confidence=0.887 -- 0.013 below the cutoff). Case (b) is what this
    # specifically targets: a reading repeatedly close to (or just under) the
    # threshold, with agreeing distance estimates, should not permanently cut
    # off guidance over one noisy dip.
    trend_confidence_enabled: bool = False
    trend_confidence_window: int = 5
    trend_confidence_min_samples: int = 3
    trend_confidence_min_high_conf_votes: int = 3
    trend_confidence_max_distance_spread_m: float = 1.0


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
    # 2026-08-15 (turn_override_completes_full_angle): structured (velocity
    # command, duration) pair, set ONLY for full-angle turn overrides -- see
    # that flag's docstring on HintActionArbiterConfig for why this bypasses
    # get_vel_command's text parsing instead of extending it. None for every
    # other decision path (unchanged, still driven by replacement_output
    # text through the existing parse_vlm_command/get_vel_command route).
    override_command: Optional[list] = None
    override_duration_s: Optional[float] = None

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
            "override_command": self.override_command,
            "override_duration_s": self.override_duration_s,
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


def _replacement_output(kind: str, cfg: HintActionArbiterConfig, bearing_deg: Optional[float] = None) -> str:
    if kind == "forward":
        return f"The next action is move forward {int(cfg.forward_distance_cm)} cm."
    if kind in ("left", "right"):
        # 2026-08-15: when turn_override_completes_full_angle is set, this
        # TEXT carries the real bearing-derived angle for human-readable
        # logging only -- it is NOT parsed by get_vel_command for this path
        # (see check()'s use of _turn_override_command below, and that
        # config flag's docstring for why: an earlier attempt routed this
        # text through get_vel_command and was reverted as unsafe for that
        # widely-shared, every-VLM-output-in-the-project function). Off (or
        # bearing_deg not supplied), text is unchanged from before: the fixed
        # turn_step_deg increment.
        step_deg = cfg.turn_step_deg
        if cfg.turn_override_completes_full_angle and bearing_deg is not None:
            step_deg = abs(float(bearing_deg))
        word = "left" if kind == "left" else "right"
        return f"The next action is turn {word} {int(round(step_deg))} degree."
    return "The next action is stop."


def _turn_override_command(kind: str, bearing_deg: float) -> tuple[list, float]:
    """2026-08-15: structured (velocity command, duration) for a full-angle
    turn override, computed directly rather than routed through
    get_vel_command's text parser -- see turn_override_completes_full_angle's
    docstring on HintActionArbiterConfig. Mirrors get_vel_command's own
    implicit rate for turns exactly (pi/6 rad/s, i.e. 30 deg/s -- the rate
    its 15->0.5s/30->1.0s/45->1.5s table already encodes), so behavior for
    the values that DO happen to be a round 15/30/45 is identical to routing
    through get_vel_command; this only generalizes to angles outside that
    set, and only for this one caller."""
    duration = abs(float(bearing_deg)) / 30.0
    omega = math.pi / 6.0 if kind == "left" else -math.pi / 6.0
    return [0.0, 0.0, omega], duration


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
        # 2026-08-15: rolling (distance, confidence) history for
        # trend_confidence_enabled, ported directly from stop_gate.py's
        # ReturnStopGate. A single global window (not keyed per target
        # anchor), mirroring stop_gate's own convention.
        self._trend_history: list[tuple[float, float]] = []

    def _trend_confidence_trusts(self, distance: float) -> bool:
        """2026-08-15: ported verbatim (same two-condition logic) from
        stop_gate.py's ReturnStopGate._trend_confidence_trusts -- see that
        docstring for the full rationale. True when a rolling window of
        recent (distance, confidence) readings corroborates trusting THIS
        attempt's distance even though its own single-reading confidence
        just failed the min_relocalization_confidence bar.

        2026-08-16 REVERTED: per-firing ground-truth verification against
        v11veto_turngate_trendconf_100ep_20260815 found this grants trust
        based on DISTANCE agreement only -- it never checks bearing/direction
        agreement, yet the trust it grants is spent on hint_action_arbiter's
        DIRECTION-override decision. Of 127 rescues that actually changed the
        executed command, 79.5% pointed the wrong direction (median error
        84.0deg); 74% of those fired on raw confidence below 0.50 (83.0% bad
        there), far outside this mechanism's intended narrow target (a single
        noisy dip just under 0.90, e.g. ep484's 0.887 -- that band alone,
        [0.85,0.90), was fine: 25% bad on n=4). Hard-disabled below rather
        than deleted so the CLI flag and its already-running callers keep
        working unchanged (this returns False unconditionally now, so
        trend_confidence_enabled has no effect regardless of whether the
        flag is passed) -- and so the original logic stays visible for
        whoever fixes it (needs a bearing-agreement check added alongside
        the existing distance-agreement check before re-enabling)."""
        return False
        if distance is None or len(self._trend_history) < self.cfg.trend_confidence_min_samples:
            return False
        window = self._trend_history[-self.cfg.trend_confidence_window:]
        trusted_ds = sorted(hd for hd, hc in window if hc >= self.cfg.min_relocalization_confidence)
        if len(trusted_ds) < self.cfg.trend_confidence_min_high_conf_votes:
            return False
        median_trusted_d = trusted_ds[len(trusted_ds) // 2]
        return abs(distance - median_trusted_d) <= self.cfg.trend_confidence_max_distance_spread_m

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

        vlm_kind = _vlm_action_kind(vlm_output)
        # 2026-08-03 (line-2 Phase 1.2, mechanism E): stop-suppression gets its
        # own, independently-gated action, separate from (and BEFORE) the
        # direction-override confidence bar below -- see stop_veto_enabled's
        # docstring on HintActionArbiterConfig. Only engages when the anchor's
        # own static route_remaining (not this attempt's noisy live distance)
        # says the anchor itself isn't close, mirroring stop_gate's own
        # anchor-corroboration veto so a genuinely-close anchor can never be
        # overridden into an unwanted forward command by this path.
        if (
            self.cfg.stop_veto_enabled
            and vlm_kind == "stop"
            and relocalization_confidence is not None
            and relocalization_confidence < self.cfg.stop_veto_min_confidence
        ):
            anchor_route_remaining = getattr(progress, "anchor_route_remaining_m", None)
            if (
                anchor_route_remaining is not None
                and anchor_route_remaining > self.cfg.stop_veto_anchor_remaining_min_m
            ):
                desired = _desired_kind(bearing, self.cfg)
                replacement = _replacement_output(desired, self.cfg, bearing_deg=bearing)
                base.update({"desired_kind": desired, "replacement_output": replacement})
                return HintActionDecision(override=True, reason="stop_veto_anchor_far", **base)

        # 2026-07-13: only override the VLM when this reading is itself
        # trustworthy -- previously ungated (see min_relocalization_confidence's
        # docstring). A missing confidence value (older/oracle-only progress
        # objects that never set the field) is treated as "no reason to
        # distrust it", not as untrustworthy -- mirrors
        # RouteMemoryAgent._candidate_is_trustworthy's same convention for
        # match_class.
        # 2026-08-15 (trend_confidence_enabled, see its docstring on
        # HintActionArbiterConfig): record this attempt in the rolling window
        # BEFORE deciding whether to grant trend-based trust, so a single
        # attempt can never vote for its own trust using only itself --
        # mirrors stop_gate.py's own trend_confidence ordering exactly.
        effective_confidence = relocalization_confidence
        if self.cfg.trend_confidence_enabled and relocalization_confidence is not None:
            self._trend_history.append((distance, relocalization_confidence))
            if len(self._trend_history) > self.cfg.trend_confidence_window:
                del self._trend_history[: len(self._trend_history) - self.cfg.trend_confidence_window]
            if (
                relocalization_confidence < self.cfg.min_relocalization_confidence
                and self._trend_confidence_trusts(distance)
            ):
                effective_confidence = self.cfg.min_relocalization_confidence
        if effective_confidence is not None and effective_confidence < self.cfg.min_relocalization_confidence:
            return HintActionDecision(override=False, reason="low_relocalization_confidence", **base)

        desired = _desired_kind(bearing, self.cfg)
        replacement = _replacement_output(desired, self.cfg, bearing_deg=bearing)
        base.update({"desired_kind": desired, "replacement_output": replacement})
        if not _conflicts_with_hint(vlm_kind, desired, bearing, self.cfg):
            return HintActionDecision(override=False, reason="vlm_action_consistent", **base)

        # 2026-08-15 (investigations/2026-08-15-hint-action-turn-gate-fix):
        # turning in place involves zero translation, so the clear-path check
        # below -- which tests whether the STRAIGHT-LINE path toward the
        # anchor is obstacle-free -- is not a meaningful safety question for
        # it (unlike `forward`, which is left going through the check
        # unchanged). See turn_override_completes_full_angle's docstring on
        # HintActionArbiterConfig for the real-data root cause this fixes.
        if desired in ("left", "right") and self.cfg.turn_override_completes_full_angle:
            _cmd, _duration = _turn_override_command(desired, bearing)
            return HintActionDecision(
                override=True,
                reason="vlm_conflicts_with_clear_hint",
                clear_path_available=False,
                clear_path=None,
                clear_path_source=None,
                min_clearance_m=None,
                override_command=_cmd,
                override_duration_s=_duration,
                **base,
            )

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
