"""Route 2 core consumer policy for frozen Reliability V1.1.

V1.1 is the mandatory observation-quality layer.  Raw candidates are kept for
reversible state estimation, while every high-consequence ICP-derived action
uses the task-specific V1.1 head.  Invalid or missing V1.1 evidence never
falls back to raw ICP confidence authority.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence


POLICY_SCHEMA = "navila-v11-consumer-policy-v3-core"
OPERATION_HEAD = {
    "anchor_promotion": "pose",
    "route_hint": "bearing",
    "hint_action_override": "bearing",
    "forced_stop": "distance",
    "vlm_stop_veto": "distance",
}
HEAD_PROBABILITY = {
    "bearing": "p_bearing_bad_30",
    "distance": "p_distance_bad_0p5",
    "pose": "p_pose_bad",
}
GUARDED_OPERATIONS = frozenset(OPERATION_HEAD)


@dataclass(frozen=True)
class ConsumerGuardDecision:
    operation: str
    anchor_index: int | None
    baseline_requested: bool
    assessment_available: bool
    jointly_trusted: bool | None
    head_trusted: bool | None
    head_probability: float | None
    reliability_envelope_id: str | None
    assessment_attempt: int | None
    assessment_step: int | None
    counterfactual_allow: bool
    executed_allow: bool
    reason: str
    mode: str
    enforcement_enabled: bool
    controller_effect: bool
    fail_open: bool
    episode_disabled: bool
    attempt: int | None
    step: int | None
    authority_anchor_index: int | None = None
    evidence_kind: str = "raw_icp"
    edge_hop_count: int = 0
    evidence_age_updates: int | None = None
    trust_field_used: str | None = None
    derived_evidence_mode: str = "off"
    legacy_counterfactual_allow: bool | None = None
    recovery_required: bool = False

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class IntegratedPromotionDecision:
    current_anchor_index: int
    next_anchor_index: int
    pre_closure_vote: bool
    baseline_vote: bool
    closure_rejected: bool
    current_assessment_available: bool
    next_assessment_available: bool
    current_pose_trusted: bool | None
    next_pose_trusted: bool | None
    current_p_pose_bad: float | None
    next_p_pose_bad: float | None
    counterfactual_vote: bool
    executed_vote: bool
    reason: str
    mode: str
    controller_effect: bool
    episode_disabled: bool
    attempt: int | None
    step: int | None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class V11ConsumerGuardV3:
    """Head-specific active guard with safe degradation and full telemetry."""

    def __init__(
        self,
        payload: Mapping[str, Any],
        *,
        mode: str = "active",
        policy_sha256: str | None = None,
    ) -> None:
        self.payload = dict(payload)
        self._validate_payload(mode)
        self.mode = str(mode)
        self.enforcement_enabled = self.mode == "active"
        self.policy_sha256 = policy_sha256 or hashlib.sha256(
            json.dumps(self.payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        self._episode_key: str | None = None
        self._assessments: dict[int, dict[str, Any]] = {}
        self._attempt: int | None = None
        self._step: int | None = None
        self._invalid = False
        self._disable_reason: str | None = None
        self._promotion_veto_streak = 0
        self._events: list[dict[str, Any]] = []

    @classmethod
    def load(
        cls, path: str | Path, *, mode: str = "active"
    ) -> "V11ConsumerGuardV3":
        source = Path(path)
        raw = source.read_bytes()
        return cls(
            json.loads(raw.decode("utf-8")),
            mode=mode,
            policy_sha256=hashlib.sha256(raw).hexdigest(),
        )

    def _validate_payload(self, mode: str) -> None:
        if self.payload.get("schema") != POLICY_SCHEMA:
            raise ValueError("unsupported Route 2 V1.1 core policy schema")
        if mode not in {"shadow", "active"}:
            raise ValueError(f"unsupported consumer mode: {mode}")
        if self.payload.get("identity_override_authorized") is not False:
            raise ValueError("Route 2 core policy forbids identity override")
        if self.payload.get("candidate_flow") != "preserve_reversible_candidates":
            raise ValueError("Route 2 core policy must preserve raw candidates")
        if self.payload.get("operation_heads") != OPERATION_HEAD:
            raise ValueError("operation/head mapping differs from core contract")
        if self.payload.get("missing_assessment_action") != "deny_guarded_operation":
            raise ValueError("missing V1.1 evidence must deny guarded operations")
        if self.payload.get("invalid_model_action") != "deny_guarded_operations_preserve_observation":
            raise ValueError("invalid V1.1 behavior violates safe degradation")
        warning = int(self.payload.get("promotion_veto_warning_streak", 0))
        recovery = int(self.payload.get("promotion_veto_recovery_streak", 0))
        if warning <= 0 or recovery < warning:
            raise ValueError("invalid promotion recovery bounds")
        if mode == "active":
            if self.payload.get("mode") != "active":
                raise RuntimeError("active mode requires an active artifact")
            if self.payload.get("enforcement_approved") is not True:
                raise RuntimeError("active Route 2 core policy is not approved")
        elif self.payload.get("mode") != "shadow" or self.payload.get(
            "enforcement_approved"
        ) is not False:
            raise ValueError("shadow mode requires a locked shadow artifact")

    def metadata(self) -> dict[str, Any]:
        return {
            "schema": POLICY_SCHEMA,
            "name": str(self.payload["name"]),
            "policy_sha256": self.policy_sha256,
            "mode": self.mode,
            "enforcement_enabled": self.enforcement_enabled,
            "root_model": "reliability_v1_1",
            "operation_heads": dict(OPERATION_HEAD),
            "raw_icp_quality_authority": False,
            "candidate_flow": "preserve_reversible_candidates",
            "identity_override_authorized": False,
        }

    @property
    def episode_disabled(self) -> bool:
        return self._invalid

    @property
    def disable_reason(self) -> str | None:
        return self._disable_reason

    @property
    def events(self) -> tuple[dict[str, Any], ...]:
        return tuple(self._events)

    def start_episode(self, episode_key: str) -> None:
        self._episode_key = str(episode_key)
        self._assessments.clear()
        self._attempt = None
        self._step = None
        self._invalid = False
        self._disable_reason = None
        self._promotion_veto_streak = 0
        self._events.clear()

    def disable_fail_open(self, reason: str) -> None:
        """Compatibility name; guarded actions actually fail closed.

        Reversible relocalization remains available, so this is a safe
        degradation rather than a motion deadlock.
        """
        if not self._invalid:
            self._invalid = True
            self._disable_reason = str(reason)
            self._events.append({
                "event": "v11_core_invalid_safe_degradation",
                "episode_key": self._episode_key,
                "reason": self._disable_reason,
                "reversible_observation_preserved": True,
                "guarded_operations_denied": True,
                "attempt": self._attempt,
                "step": self._step,
            })

    @staticmethod
    def _assessment(output: Mapping[str, Any]) -> dict[str, Any]:
        probabilities = {
            "p_bearing_bad_30": float(output["p_bearing_bad_30"]),
            "p_distance_bad_0p5": float(output["p_distance_bad_0p5"]),
            "p_pose_bad": float(output["p_pose_bad"]),
        }
        if not all(math.isfinite(value) for value in probabilities.values()):
            raise ValueError("non-finite V1.1 probability")
        if not all(0.0 <= value <= 1.0 for value in probabilities.values()):
            raise ValueError("V1.1 probability outside [0,1]")
        return {
            "anchor_index": int(output["anchor_index"]),
            "anchor_role": str(output["anchor_role"]),
            **probabilities,
            "bearing_trusted": bool(output["bearing_trusted"]),
            "distance_trusted": bool(output["distance_trusted"]),
            "pose_trusted": bool(output["pose_trusted"]),
            "jointly_trusted": bool(output["jointly_trusted"]),
        }

    def observe_scores(
        self,
        outputs: Sequence[Mapping[str, Any]],
        *,
        attempt: int,
        step: int,
    ) -> None:
        try:
            values = [self._assessment(output) for output in outputs]
            for value in values:
                value["assessment_attempt"] = int(attempt)
                value["assessment_step"] = int(step)
                value["reliability_envelope_id"] = (
                    f"{self._episode_key}:a{int(attempt)}:s{int(step)}:"
                    f"anchor{int(value['anchor_index'])}"
                )
            by_anchor = {value["anchor_index"]: value for value in values}
            if not values or len(values) != len(by_anchor):
                raise ValueError("empty or duplicate V1.1 assessment set")
            self._assessments = by_anchor
            self._attempt = int(attempt)
            self._step = int(step)
        except Exception as exc:
            self.disable_fail_open(
                f"model_output_invalid:{type(exc).__name__}:{exc}"
            )

    def anchor_assessment(self, anchor_index: int) -> dict[str, Any] | None:
        value = self._assessments.get(int(anchor_index))
        return dict(value) if value is not None else None

    def head_trusted(self, anchor_index: int, head: str) -> bool | None:
        if head not in {"bearing", "distance", "pose"}:
            raise ValueError(f"unsupported V1.1 head: {head}")
        value = self._assessments.get(int(anchor_index))
        if value is None or self._invalid:
            return None
        return bool(value[f"{head}_trusted"])

    def _record(self, decision: ConsumerGuardDecision) -> ConsumerGuardDecision:
        self._events.append({
            "event": "v11_consumer_v3_core_decision",
            "episode_key": self._episode_key,
            **decision.as_dict(),
        })
        return decision

    def evaluate(
        self,
        operation: str,
        *,
        anchor_index: int | None,
        baseline_requested: bool = True,
        evidence_kind: str = "raw_icp",
        source_anchor_index: int | None = None,
        edge_hop_count: int = 0,
        evidence_age_updates: int | None = None,
        derived_evidence_mode: str = "off",
        derived_max_age_updates: int = 25,
        derived_max_edge_hops: int = 1,
    ) -> ConsumerGuardDecision:
        operation = str(operation)
        if operation not in GUARDED_OPERATIONS and operation != "relocalization_update":
            raise ValueError(f"unsupported consumer operation: {operation}")
        if derived_evidence_mode not in {"off", "shadow", "active"}:
            raise ValueError("invalid derived evidence mode")

        requested = bool(baseline_requested)
        kind = str(evidence_kind or "raw_icp")
        hop_count = max(0, int(edge_hop_count))
        age = max(0, int(evidence_age_updates)) if evidence_age_updates is not None else None
        head = OPERATION_HEAD.get(operation)
        authority_index = anchor_index
        recovery_required = False

        if operation == "relocalization_update":
            allow = requested
            reason = "reversible_observation_preserved"
            assessment = None
            head = None
        elif not requested:
            allow = False
            reason = "baseline_did_not_request"
            assessment = None
        elif kind == "geometry_reconstructed":
            authority_index = source_anchor_index
            assessment = (
                self._assessments.get(int(source_anchor_index))
                if source_anchor_index is not None else None
            )
            if operation not in {"route_hint", "hint_action_override"}:
                allow = False
                reason = "derived_distance_has_no_terminal_authority"
            elif derived_evidence_mode == "off":
                allow = False
                reason = "derived_evidence_not_enabled"
            elif hop_count != 1 or hop_count > int(derived_max_edge_hops):
                allow = False
                reason = "derived_bearing_requires_bounded_one_hop_source"
            elif age is None or age > int(derived_max_age_updates):
                allow = False
                reason = "derived_bearing_missing_or_expired"
            elif self._invalid:
                allow = False
                reason = "v11_invalid_no_raw_fallback"
            elif assessment is None:
                allow = False
                reason = "derived_source_assessment_missing"
            else:
                allow = bool(assessment["bearing_trusted"])
                reason = (
                    "derived_source_bearing_trusted"
                    if allow else "derived_source_bearing_untrusted"
                )
        else:
            assessment = (
                self._assessments.get(int(anchor_index))
                if anchor_index is not None else None
            )
            if self._invalid:
                allow = False
                reason = "v11_invalid_no_raw_fallback"
            elif self._attempt is None:
                allow = False
                reason = "bootstrap_wait_for_v11_assessment"
            elif assessment is None:
                allow = False
                reason = "authoritative_anchor_assessment_missing"
            else:
                allow = bool(assessment[f"{head}_trusted"])
                reason = (
                    f"authoritative_anchor_{head}_trusted"
                    if allow else f"authoritative_anchor_{head}_untrusted"
                )

        if operation == "anchor_promotion" and requested:
            if allow:
                self._promotion_veto_streak = 0
            else:
                self._promotion_veto_streak += 1
                warning = int(self.payload["promotion_veto_warning_streak"])
                recovery = int(self.payload["promotion_veto_recovery_streak"])
                if self._promotion_veto_streak == warning:
                    self._events.append({
                        "event": "v11_core_promotion_veto_warning",
                        "episode_key": self._episode_key,
                        "streak": self._promotion_veto_streak,
                        "attempt": self._attempt,
                        "step": self._step,
                    })
                if self._promotion_veto_streak >= recovery:
                    recovery_required = True
                    reason = "promotion_denied_recovery_required"

        counterfactual = bool(allow)
        executed = counterfactual if self.enforcement_enabled else requested
        available = assessment is not None and not self._invalid
        head_trusted = (
            bool(assessment[f"{head}_trusted"])
            if assessment is not None and head is not None and not self._invalid
            else None
        )
        joint = (
            bool(assessment["jointly_trusted"])
            if assessment is not None and not self._invalid else None
        )
        head_probability = (
            float(assessment[HEAD_PROBABILITY[head]])
            if assessment is not None and head is not None and not self._invalid
            else None
        )
        return self._record(ConsumerGuardDecision(
            operation=operation,
            anchor_index=int(anchor_index) if anchor_index is not None else None,
            baseline_requested=requested,
            assessment_available=available,
            jointly_trusted=joint,
            head_trusted=head_trusted,
            head_probability=head_probability,
            reliability_envelope_id=(
                str(assessment["reliability_envelope_id"])
                if assessment is not None and not self._invalid else None
            ),
            assessment_attempt=(
                int(assessment["assessment_attempt"])
                if assessment is not None and not self._invalid else None
            ),
            assessment_step=(
                int(assessment["assessment_step"])
                if assessment is not None and not self._invalid else None
            ),
            counterfactual_allow=counterfactual,
            executed_allow=bool(executed),
            reason=reason,
            mode=self.mode,
            enforcement_enabled=self.enforcement_enabled,
            controller_effect=bool(self.enforcement_enabled and executed != requested),
            fail_open=False,
            episode_disabled=self._invalid,
            attempt=self._attempt,
            step=self._step,
            authority_anchor_index=(
                int(authority_index) if authority_index is not None else None
            ),
            evidence_kind=kind,
            edge_hop_count=hop_count,
            evidence_age_updates=age,
            trust_field_used=f"{head}_trusted" if head is not None else None,
            derived_evidence_mode=derived_evidence_mode,
            recovery_required=recovery_required,
        ))

    def evaluate_promotion_evidence(
        self,
        *,
        current_anchor_index: int,
        next_anchor_index: int,
        pre_closure_vote: bool,
        baseline_vote: bool,
        closure_rejected: bool,
        mode: str = "shadow",
    ) -> IntegratedPromotionDecision:
        if mode != "shadow":
            raise ValueError("integrated pre-vote observer remains shadow-only")
        current = self._assessments.get(int(current_anchor_index))
        next_value = self._assessments.get(int(next_anchor_index))
        next_pose = (
            bool(next_value["pose_trusted"])
            if next_value is not None and not self._invalid else None
        )
        vote = bool(baseline_vote and next_pose is True)
        reason = (
            "next_pose_trusted_preserve_baseline_vote"
            if next_pose is True else "next_pose_missing_or_untrusted_do_not_admit_vote"
        )
        decision = IntegratedPromotionDecision(
            current_anchor_index=int(current_anchor_index),
            next_anchor_index=int(next_anchor_index),
            pre_closure_vote=bool(pre_closure_vote),
            baseline_vote=bool(baseline_vote),
            closure_rejected=bool(closure_rejected),
            current_assessment_available=current is not None,
            next_assessment_available=next_value is not None,
            current_pose_trusted=(
                bool(current["pose_trusted"]) if current is not None else None
            ),
            next_pose_trusted=next_pose,
            current_p_pose_bad=(
                float(current["p_pose_bad"]) if current is not None else None
            ),
            next_p_pose_bad=(
                float(next_value["p_pose_bad"]) if next_value is not None else None
            ),
            counterfactual_vote=vote,
            executed_vote=bool(baseline_vote),
            reason=reason,
            mode=mode,
            controller_effect=False,
            episode_disabled=self._invalid,
            attempt=self._attempt,
            step=self._step,
        )
        self._events.append({
            "event": "v11_integrated_promotion_v3_shadow_decision",
            "episode_key": self._episode_key,
            **decision.as_dict(),
        })
        return decision
