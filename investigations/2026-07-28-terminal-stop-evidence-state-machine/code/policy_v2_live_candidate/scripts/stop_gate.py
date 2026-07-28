"""Return-terminal evidence state machine.

The old stop gate treated a single route-memory scalar as authoritative:
``deferred`` silently passed a VLM STOP through, a confident-but-wrong
distance could veto a correct STOP indefinitely, and a veto injected motion
toward the same potentially wrong bearing.  This module deliberately does
less:

* a VLM STOP is a proposal, never terminal evidence by itself;
* only fresh, Route-2-trusted *forward/next* raw evidence may accept or force
  arrival;
* fresh bounded geometry reconstruction may reject a clearly premature STOP,
  but may not accept/force one;
* current/rear anchor identity, stale evidence and untrusted evidence have no
  direct terminal authority;
* uncertainty enters a short stationary verification barrier, then a bounded
  visual/VLM-only blind state; exhausting that state is a safe failure, never
  a claimed success.

Stopping cannot create missing information.  The verification state therefore
lasts only a small number of VLM queries.  If fresh evidence does not return,
the gate uses the last trusted distance interval expanded by actual travelled
path length, an independent A0 RGB-D callback, and repeated VLM STOP proposals.
If all of those remain unavailable, ``safe_fail`` is the explicit outcome.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple


NAVIGATING = "navigating"
TERMINAL_VERIFY = "terminal_verify"
TERMINAL_BLIND = "terminal_blind"
ARRIVED = "arrived"
SAFE_FAIL = "safe_fail"


@dataclass
class GateDecision:
    decision: str
    authority_d: Optional[float]
    conf: float
    is_teleport_frame: bool
    suggested_command: Optional[List[float]] = None
    suggested_steps: int = 10
    state: str = NAVIGATING
    reason: str = ""
    evidence_authority: str = "none"
    distance_interval_m: Optional[Tuple[float, float]] = None
    navigation_paused: bool = False
    visual_home_confirmed: Optional[bool] = None
    blind_query_count: int = 0

    @property
    def terminal(self) -> bool:
        return self.decision in {"accepted", "forced", "safe_fail"}

    def as_log_dict(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "gate_decision": self.decision,
            "gate_state": self.state,
            "gate_reason": self.reason,
            "gate_evidence_authority": self.evidence_authority,
            "gate_authority_d": self.authority_d,
            "gate_conf": round(self.conf, 4),
            "gate_teleport_filtered": self.is_teleport_frame,
            "gate_navigation_paused": self.navigation_paused,
            "gate_visual_home_confirmed": self.visual_home_confirmed,
            "gate_blind_query_count": int(self.blind_query_count),
        }
        if self.distance_interval_m is not None:
            result["gate_distance_interval_m"] = [
                round(float(self.distance_interval_m[0]), 4),
                round(float(self.distance_interval_m[1]), 4),
            ]
        if self.suggested_command is not None:
            result["gate_suggested_command"] = [
                round(float(value), 4) for value in self.suggested_command
            ]
            result["gate_suggested_steps"] = int(self.suggested_steps)
        return result


class ReturnStopGate:
    """Safety-first terminal arbiter for the return phase.

    ``evidence_trusted`` must come from Route 2's independent reliability
    assessment.  Confidence alone never upgrades an ICP reading to terminal
    authority.  Direct oracle progress is the only exception used by oracle
    evaluation runs.
    """

    _TELEPORT_JUMP_M = 3.0

    def __init__(
        self,
        r_in: float = 3.0,
        r_out: float = 3.0,
        confirm_steps: int = 3,
        min_confidence: float = 0.5,
        anchor_corroboration_enabled: bool = False,
        forced_stop_anchor_confirm_steps: int = 2,
        *,
        accept_confirm_steps: int = 2,
        verify_queries: int = 2,
        blind_max_queries: int = 8,
        max_evidence_age_updates: int = 25,
        max_reconstructed_edge_hops: int = 1,
        raw_distance_margin_m: float = 0.35,
        reconstructed_extra_margin_m: float = 0.50,
        visual_confirm_steps: int = 2,
        hold_steps: int = 10,
    ) -> None:
        if r_in > r_out:
            raise ValueError(f"r_in ({r_in}) must be <= r_out ({r_out})")
        for name, value in (
            ("confirm_steps", confirm_steps),
            ("accept_confirm_steps", accept_confirm_steps),
            ("verify_queries", verify_queries),
            ("blind_max_queries", blind_max_queries),
            ("visual_confirm_steps", visual_confirm_steps),
            ("hold_steps", hold_steps),
        ):
            if int(value) <= 0:
                raise ValueError(f"{name} must be positive")

        self.r_in = float(r_in)
        self.r_out = float(r_out)
        self.confirm_steps = int(confirm_steps)
        self.min_confidence = float(min_confidence)
        # Retained as readable compatibility metadata.  Rear/current-anchor
        # corroboration is intentionally no longer terminal authority.
        self.anchor_corroboration_enabled = bool(anchor_corroboration_enabled)
        self.forced_stop_anchor_confirm_steps = int(
            forced_stop_anchor_confirm_steps
        )
        self.accept_confirm_steps = int(accept_confirm_steps)
        self.verify_queries = int(verify_queries)
        self.blind_max_queries = int(blind_max_queries)
        self.max_evidence_age_updates = int(max_evidence_age_updates)
        self.max_reconstructed_edge_hops = int(
            max_reconstructed_edge_hops
        )
        self.raw_distance_margin_m = float(raw_distance_margin_m)
        self.reconstructed_extra_margin_m = float(
            reconstructed_extra_margin_m
        )
        self.visual_confirm_steps = int(visual_confirm_steps)
        self.hold_steps = int(hold_steps)

        self.state = NAVIGATING
        self._near_evidence_streak = 0
        self._vlm_stop_streak = 0
        self._visual_confirm_streak = 0
        self._verify_query_count = 0
        self._blind_query_count = 0
        self._resume_prompt_pending = False
        self._prev_sim_pos: Optional[List[float]] = None
        self._teleport_pending = False
        self._travel_since_trusted_m = 0.0
        self._last_trusted_interval: Optional[Tuple[float, float]] = None

    @property
    def navigation_paused(self) -> bool:
        return self.state in {TERMINAL_VERIFY, TERMINAL_BLIND, SAFE_FAIL}

    def prompt_suffix(self) -> str:
        if self.state == TERMINAL_VERIFY:
            return (
                "\n[Terminal safety: your STOP is not yet verified. Hold position "
                "while the start-location evidence is resampled. Do not claim "
                "success yet.]"
            )
        if self.state == TERMINAL_BLIND:
            return (
                "\n[Terminal safety: start-location evidence is currently "
                "unavailable. Do not stop solely from route numbers. Continue "
                "careful visual navigation toward the original start while the "
                "system probes A0 and the saved route; issue STOP again only when "
                "the start place is visually recognizable.]"
            )
        if self._resume_prompt_pending:
            return (
                "\n[Terminal safety: the previous STOP was rejected because "
                "fresh authorized evidence places the start outside the arrival "
                "radius. Continue navigation and issue a movement command.]"
            )
        return ""

    def notify_sim_step(self, current_pos) -> bool:
        """Track travelled distance for the conservative last-trust envelope."""
        x, y = float(current_pos[0]), float(current_pos[1])
        if self._prev_sim_pos is None:
            self._prev_sim_pos = [x, y]
            return False

        step_distance = math.hypot(
            x - self._prev_sim_pos[0],
            y - self._prev_sim_pos[1],
        )
        self._prev_sim_pos = [x, y]
        is_teleport = step_distance > self._TELEPORT_JUMP_M
        if is_teleport:
            self._teleport_pending = True
            self._clear_measurement_streaks()
            self._last_trusted_interval = None
            self._travel_since_trusted_m = 0.0
        elif self._last_trusted_interval is not None:
            self._travel_since_trusted_m += float(step_distance)
        return is_teleport

    def check(
        self,
        progress,
        vlm_issued_stop: bool,
        *,
        evidence_trusted: Optional[bool] = None,
        home_visual_probe: Optional[Callable[[], Optional[bool]]] = None,
    ) -> GateDecision:
        """Arbitrate one VLM query.

        Every VLM STOP that is not explicitly ``accepted``/``forced`` is
        non-terminal.  The caller must execute ``suggested_command`` (a zero
        velocity hold) for ``verifying``/``resume`` decisions and ask the VLM
        again; it must never interpret those decisions as success.
        """
        is_teleport = self._teleport_pending
        self._teleport_pending = False
        d, conf = self._extract_d_and_conf(progress)

        if self.state in {ARRIVED, SAFE_FAIL}:
            return self._decision(
                "accepted" if self.state == ARRIVED else "safe_fail",
                d,
                conf,
                is_teleport,
                reason="terminal_state_latched",
            )

        if is_teleport:
            if vlm_issued_stop:
                self._enter_verify()
                return self._hold_decision(
                    "verifying",
                    d,
                    conf,
                    True,
                    reason="teleport_frame_has_no_terminal_authority",
                )
            return self._decision(
                "pass",
                d,
                conf,
                True,
                reason="teleport_frame_ignored",
            )

        authority, interval = self._classify_evidence(
            progress,
            d,
            conf,
            evidence_trusted,
        )
        direct_raw = authority in {"trusted_next_raw", "direct_oracle"}
        bounded_derived = authority == "trusted_bounded_reconstruction"

        if direct_raw and interval is not None:
            self._last_trusted_interval = interval
            self._travel_since_trusted_m = 0.0

        if vlm_issued_stop:
            self._vlm_stop_streak += 1
            if self.state == TERMINAL_VERIFY:
                self._verify_query_count += 1
        else:
            self._resume_prompt_pending = False
            self._vlm_stop_streak = 0
            self._visual_confirm_streak = 0

        near = bool(interval is not None and interval[1] <= self.r_in)
        far = bool(interval is not None and interval[0] > self.r_out)
        if direct_raw and near:
            self._near_evidence_streak += 1
        else:
            self._near_evidence_streak = 0

        # Fresh, trusted forward/raw evidence is the only numeric positive
        # authority.  It still needs temporal confirmation.
        if direct_raw and near:
            if vlm_issued_stop:
                if (
                    self._near_evidence_streak >= self.accept_confirm_steps
                    and self._vlm_stop_streak >= self.accept_confirm_steps
                ):
                    self.state = ARRIVED
                    return self._decision(
                        "accepted",
                        d,
                        conf,
                        False,
                        authority=authority,
                        interval=interval,
                        reason="repeated_vlm_stop_and_fresh_trusted_next_near",
                    )
                self._enter_verify(preserve_streaks=True)
                return self._hold_decision(
                    "verifying",
                    d,
                    conf,
                    False,
                    authority=authority,
                    interval=interval,
                    reason="trusted_near_requires_second_query",
                )
            if self._near_evidence_streak >= self.confirm_steps:
                self.state = ARRIVED
                return self._decision(
                    "forced",
                    d,
                    conf,
                    False,
                    authority=authority,
                    interval=interval,
                    reason="fresh_trusted_next_near_streak_without_vlm_stop",
                )
            if self.state != NAVIGATING:
                self.state = NAVIGATING
                self._reset_uncertain_state()
            return self._decision(
                "pass",
                d,
                conf,
                False,
                authority=authority,
                interval=interval,
                reason="trusted_near_confirmation_accumulating",
            )

        # Fresh trusted forward/raw or bounded reconstructed evidence can
        # reject a STOP only when the entire uncertainty interval is outside.
        if vlm_issued_stop and far and (direct_raw or bounded_derived):
            self.state = NAVIGATING
            self._resume_prompt_pending = True
            self._reset_uncertain_state(preserve_vlm_stop_streak=True)
            return self._hold_decision(
                "resume",
                d,
                conf,
                False,
                authority=authority,
                interval=interval,
                reason="fresh_authorized_interval_definitely_outside",
                navigation_paused=False,
            )

        # A returned fresh authority also ends a previous blind episode even
        # when it overlaps the boundary; the ambiguous STOP remains held.
        if not vlm_issued_stop and (direct_raw or bounded_derived):
            self.state = NAVIGATING
            self._reset_uncertain_state()
            return self._decision(
                "pass",
                d,
                conf,
                False,
                authority=authority,
                interval=interval,
                reason="fresh_terminal_evidence_returned",
            )

        if not vlm_issued_stop:
            if self.state == TERMINAL_VERIFY:
                self._enter_blind()
            if self.state == TERMINAL_BLIND:
                return self._advance_blind(
                    d,
                    conf,
                    authority,
                    interval,
                    visual=None,
                )
            return self._decision(
                "pass",
                d,
                conf,
                False,
                authority=authority,
                interval=interval,
                reason="no_stop_proposal",
            )

        # From here the VLM proposed STOP without positive numeric authority.
        # A last-trusted interval expands by all travelled path length since
        # that measurement.  It can conservatively disprove arrival but can
        # never prove it.
        last_interval = self._expanded_last_trusted_interval()
        if last_interval is not None and last_interval[0] > self.r_out:
            if self.state == NAVIGATING:
                self._enter_verify()
            if (
                self.state == TERMINAL_VERIFY
                and self._verify_query_count >= self.verify_queries
            ):
                self._enter_blind()
            if self.state == TERMINAL_BLIND:
                return self._advance_blind(
                    d,
                    conf,
                    "last_trusted_motion_envelope",
                    last_interval,
                    visual=None,
                )
            return self._hold_decision(
                "resume",
                d,
                conf,
                False,
                authority="last_trusted_motion_envelope",
                interval=last_interval,
                reason="last_trusted_envelope_still_definitely_outside",
            )

        if self.state == NAVIGATING:
            self._enter_verify()

        visual = (
            home_visual_probe()
            if home_visual_probe is not None
            else None
        )
        if visual is True:
            self._visual_confirm_streak += 1
        else:
            self._visual_confirm_streak = 0

        if (
            visual is True
            and self._visual_confirm_streak >= self.visual_confirm_steps
            and self._vlm_stop_streak >= self.visual_confirm_steps
        ):
            self.state = ARRIVED
            return self._decision(
                "accepted",
                d,
                conf,
                False,
                authority="a0_rgbd_plus_repeated_vlm_stop",
                interval=last_interval,
                reason="independent_a0_visual_and_vlm_stop_confirmed",
                visual=visual,
            )

        if (
            self.state == TERMINAL_VERIFY
            and self._verify_query_count < self.verify_queries
        ):
            return self._hold_decision(
                "verifying",
                d,
                conf,
                False,
                authority=authority,
                interval=last_interval or interval,
                reason="terminal_evidence_unknown_resampling",
                visual=visual,
            )

        if self.state != TERMINAL_BLIND:
            self._enter_blind()
        return self._advance_blind(
            d,
            conf,
            authority,
            last_interval or interval,
            visual=visual,
        )

    def _advance_blind(
        self,
        d: Optional[float],
        conf: float,
        authority: str,
        interval: Optional[Tuple[float, float]],
        *,
        visual: Optional[bool],
    ) -> GateDecision:
        self._blind_query_count += 1
        if self._blind_query_count >= self.blind_max_queries:
            self.state = SAFE_FAIL
            return self._decision(
                "safe_fail",
                d,
                conf,
                False,
                authority=authority,
                interval=interval,
                reason="blind_probe_budget_exhausted_without_terminal_evidence",
                visual=visual,
            )
        return self._hold_decision(
            "resume",
            d,
            conf,
            False,
            authority=authority,
            interval=interval,
            reason="bounded_vlm_only_navigation_and_a0_route_probing",
            visual=visual,
        )

    def _classify_evidence(
        self,
        progress,
        d: Optional[float],
        conf: float,
        evidence_trusted: Optional[bool],
    ) -> Tuple[str, Optional[Tuple[float, float]]]:
        if progress is None or d is None or not math.isfinite(float(d)):
            return "none", None
        source = str(getattr(progress, "source", "") or "")
        if "oracle" in source:
            return "direct_oracle", self._interval(
                d, self.raw_distance_margin_m
            )

        age = getattr(progress, "evidence_age_updates", None)
        fresh = (
            age is not None
            and int(age) >= 0
            and int(age) <= self.max_evidence_age_updates
        )
        if evidence_trusted is not True:
            return "untrusted", None
        if not fresh:
            return "stale", None

        kind = str(getattr(progress, "estimate_kind", "raw_icp") or "raw_icp")
        role = str(getattr(progress, "estimate_role", "unknown") or "unknown")
        if kind == "raw_icp" and role == "next":
            return "trusted_next_raw", self._interval(
                d, self.raw_distance_margin_m
            )
        if kind == "geometry_reconstructed":
            hops = max(
                0,
                int(getattr(progress, "estimate_edge_hop_count", 0) or 0),
            )
            if 1 <= hops <= self.max_reconstructed_edge_hops:
                margin = (
                    self.raw_distance_margin_m
                    + hops * self.reconstructed_extra_margin_m
                )
                return (
                    "trusted_bounded_reconstruction",
                    self._interval(d, margin),
                )
            return "reconstruction_out_of_bounds", None
        if kind == "raw_icp" and role == "current":
            return "rear_current_no_terminal_authority", None
        return "unsupported_evidence_role", None

    @staticmethod
    def _interval(
        distance: float,
        margin: float,
    ) -> Tuple[float, float]:
        d = float(distance)
        width = max(0.0, float(margin))
        return max(0.0, d - width), d + width

    def _expanded_last_trusted_interval(
        self,
    ) -> Optional[Tuple[float, float]]:
        if self._last_trusted_interval is None:
            return None
        travel = max(0.0, float(self._travel_since_trusted_m))
        return (
            max(0.0, self._last_trusted_interval[0] - travel),
            self._last_trusted_interval[1] + travel,
        )

    def _enter_verify(self, *, preserve_streaks: bool = False) -> None:
        self.state = TERMINAL_VERIFY
        self._verify_query_count = 1
        self._blind_query_count = 0
        if not preserve_streaks:
            self._near_evidence_streak = 0

    def _enter_blind(self) -> None:
        self.state = TERMINAL_BLIND
        self._verify_query_count = 0
        self._blind_query_count = 0
        self._near_evidence_streak = 0

    def _reset_uncertain_state(
        self,
        *,
        preserve_vlm_stop_streak: bool = False,
    ) -> None:
        self._verify_query_count = 0
        self._blind_query_count = 0
        self._visual_confirm_streak = 0
        if not preserve_vlm_stop_streak:
            self._vlm_stop_streak = 0

    def _clear_measurement_streaks(self) -> None:
        self._near_evidence_streak = 0
        self._vlm_stop_streak = 0
        self._visual_confirm_streak = 0
        self._verify_query_count = 0
        self._blind_query_count = 0

    def _hold_decision(
        self,
        decision: str,
        d: Optional[float],
        conf: float,
        is_teleport: bool,
        *,
        authority: str = "none",
        interval: Optional[Tuple[float, float]] = None,
        reason: str,
        visual: Optional[bool] = None,
        navigation_paused: Optional[bool] = None,
    ) -> GateDecision:
        result = self._decision(
            decision,
            d,
            conf,
            is_teleport,
            authority=authority,
            interval=interval,
            reason=reason,
            visual=visual,
            navigation_paused=navigation_paused,
        )
        result.suggested_command = [0.0, 0.0, 0.0]
        result.suggested_steps = self.hold_steps
        return result

    def _decision(
        self,
        decision: str,
        d: Optional[float],
        conf: float,
        is_teleport: bool,
        *,
        authority: str = "none",
        interval: Optional[Tuple[float, float]] = None,
        reason: str,
        visual: Optional[bool] = None,
        navigation_paused: Optional[bool] = None,
    ) -> GateDecision:
        return GateDecision(
            decision=decision,
            authority_d=float(d) if d is not None else None,
            conf=float(conf),
            is_teleport_frame=bool(is_teleport),
            state=self.state,
            reason=str(reason),
            evidence_authority=str(authority),
            distance_interval_m=interval,
            navigation_paused=(
                self.navigation_paused
                if navigation_paused is None
                else bool(navigation_paused)
            ),
            visual_home_confirmed=visual,
            blind_query_count=int(self._blind_query_count),
        )

    def _extract_d_and_conf(self, progress) -> Tuple[Optional[float], float]:
        if progress is None:
            return None, 0.0
        d = getattr(progress, "distance_to_start_m", None)
        source = str(getattr(progress, "source", "") or "")
        if "oracle" in source:
            return d, 1.0
        conf = getattr(progress, "relocalization_confidence", None)
        if conf is not None:
            return d, float(conf)
        std = getattr(progress, "filter_std_m", None)
        if std is not None:
            return d, max(0.0, 1.0 - float(std) / 5.0)
        return d, 0.0
