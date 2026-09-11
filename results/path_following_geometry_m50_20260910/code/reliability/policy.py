"""Bounded temporal evidence layer; all enforcement switches default off."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .bundle import ReliabilityResult


@dataclass
class _CandidateState:
    observations: int = 0
    consecutive_pose_untrusted: int = 0
    consecutive_pose_trusted: int = 0
    observations_since_pose_trusted: int = 0


@dataclass
class ReliabilityPolicyDecision:
    anchor_index: int
    anchor_role: str
    recommend_block_hint_override: bool
    recommend_defer_anchor_stop_authority: bool
    recommend_block_promotion: bool
    recommend_current_eviction: bool
    enforced_block_hint_override: bool
    enforced_defer_anchor_stop_authority: bool
    enforced_block_promotion: bool
    enforced_current_eviction: bool
    consecutive_pose_untrusted: int
    reason: str
    reliability: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ReliabilityTemporalController:
    mode: str = "shadow"
    pose_high_risk_threshold: float = 0.7
    high_risk_consecutive: int = 10
    trusted_consecutive: int = 2
    release_after_attempts: int = 25
    enable_hint_arbiter: bool = False
    enable_stop_gate: bool = False
    enable_promotion: bool = False
    enable_current_eviction: bool = False
    states: dict[int, _CandidateState] = field(default_factory=dict)

    def observe(self, anchor_index: int, anchor_role: str, result: ReliabilityResult) -> ReliabilityPolicyDecision:
        state = self.states.setdefault(int(anchor_index), _CandidateState())
        state.observations += 1
        high_pose_risk = result.status != "trusted" or result.p_pose_bad >= self.pose_high_risk_threshold
        if not high_pose_risk:
            state.consecutive_pose_trusted += 1
            state.consecutive_pose_untrusted = 0
            state.observations_since_pose_trusted = 0
        else:
            state.consecutive_pose_untrusted += 1
            state.consecutive_pose_trusted = 0
            state.observations_since_pose_trusted += 1
        persistent_pose_risk = state.consecutive_pose_untrusted >= self.high_risk_consecutive
        release_valve = state.observations_since_pose_trusted >= self.release_after_attempts
        block_hint = not result.bearing_trusted
        defer_stop = not result.distance_trusted
        block_promotion = anchor_role == "next" and persistent_pose_risk
        evict_current = anchor_role == "current" and (persistent_pose_risk or release_valve)
        enforce = self.mode == "enforce"
        reasons = []
        if result.status != "trusted":
            reasons.append(result.status)
        if persistent_pose_risk:
            reasons.append("persistent_pose_risk")
        if release_valve:
            reasons.append("bounded_release_valve")
        if not reasons:
            reasons.append("reading_observed")
        return ReliabilityPolicyDecision(
            anchor_index=int(anchor_index),
            anchor_role=str(anchor_role),
            recommend_block_hint_override=block_hint,
            recommend_defer_anchor_stop_authority=defer_stop,
            recommend_block_promotion=block_promotion,
            recommend_current_eviction=evict_current,
            enforced_block_hint_override=enforce and self.enable_hint_arbiter and block_hint,
            enforced_defer_anchor_stop_authority=enforce and self.enable_stop_gate and defer_stop,
            enforced_block_promotion=enforce and self.enable_promotion and block_promotion,
            enforced_current_eviction=enforce and self.enable_current_eviction and evict_current,
            consecutive_pose_untrusted=state.consecutive_pose_untrusted,
            reason="+".join(reasons),
            reliability=result.as_dict(),
        )
