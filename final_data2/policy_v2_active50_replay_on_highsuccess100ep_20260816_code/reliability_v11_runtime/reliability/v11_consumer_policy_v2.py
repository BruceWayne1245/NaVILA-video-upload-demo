"""Bounded V1.1 guard for irreversible Route-1 consumers.

Policy V1 hard-filtered raw candidates before RouteMemoryAgent and could starve
the controller of every relocalization update.  Policy V2 preserves the exact
baseline candidate flow.  It uses the frozen V1.1 trust labels only when a
downstream consumer proposes a high-consequence action.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence


POLICY_SCHEMA = "navila-v11-consumer-policy-v2"
GUARDED_OPERATIONS = frozenset({
    "anchor_promotion",
    "route_hint",
    "hint_action_override",
    "forced_stop",
    "vlm_stop_veto",
})


@dataclass(frozen=True)
class ConsumerGuardDecision:
    operation: str
    anchor_index: int | None
    baseline_requested: bool
    assessment_available: bool
    jointly_trusted: bool | None
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

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class V11ConsumerGuardV2:
    """Stateful, fail-open consumer guard with a hard shadow/active lock."""

    def __init__(
        self,
        payload: Mapping[str, Any],
        *,
        mode: str = "shadow",
        policy_sha256: str | None = None,
    ) -> None:
        self.payload = dict(payload)
        self._validate_payload(mode)
        self.mode = mode
        self.enforcement_enabled = mode == "active"
        self.policy_sha256 = policy_sha256 or hashlib.sha256(
            json.dumps(
                self.payload,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        self._episode_key: str | None = None
        self._assessments: dict[int, dict[str, Any]] = {}
        self._attempt: int | None = None
        self._step: int | None = None
        self._disabled = False
        self._disable_reason: str | None = None
        self._promotion_veto_streak = 0
        self._events: list[dict[str, Any]] = []

    @classmethod
    def load(
        cls,
        path: str | Path,
        *,
        mode: str = "shadow",
    ) -> "V11ConsumerGuardV2":
        source = Path(path)
        raw = source.read_bytes()
        return cls(
            json.loads(raw.decode("utf-8")),
            mode=mode,
            policy_sha256=hashlib.sha256(raw).hexdigest(),
        )

    def _validate_payload(self, mode: str) -> None:
        if self.payload.get("schema") != POLICY_SCHEMA:
            raise ValueError(f"unsupported consumer policy schema: {self.payload.get('schema')}")
        if mode not in {"shadow", "active"}:
            raise ValueError(f"unsupported consumer policy mode: {mode}")
        if self.payload.get("identity_override_authorized") is not False:
            raise ValueError("Policy V2 must explicitly forbid identity override")
        if self.payload.get("candidate_flow") != "preserve_baseline_candidates":
            raise ValueError("Policy V2 must preserve baseline candidates")
        if self.payload.get("trust_field") != "jointly_trusted":
            raise ValueError("Policy V2 supports only the frozen jointly_trusted label")
        if set(self.payload.get("guarded_operations", [])) != GUARDED_OPERATIONS:
            raise ValueError("guarded operation set differs from frozen Policy V2")
        if self.payload.get("untrusted_action") != "veto_guarded_operation":
            raise ValueError("unsupported untrusted action")
        if self.payload.get("bootstrap_action") != "preserve_baseline_until_first_score":
            raise ValueError("unsupported bootstrap action")
        if self.payload.get("missing_assessment_action") != "veto_guarded_operation":
            raise ValueError("missing assessment must veto only the guarded operation")
        if self.payload.get("model_exception_action") != "fail_open_disable_episode":
            raise ValueError("model exceptions must fail open and disable the episode")
        warning = int(self.payload.get("promotion_veto_warning_streak", 0))
        fallback = int(self.payload.get("promotion_veto_fallback_streak", 0))
        if warning <= 0 or fallback < warning:
            raise ValueError("invalid promotion veto streak limits")
        if mode == "active":
            if self.payload.get("mode") != "active":
                raise RuntimeError("active mode requires an active policy artifact")
            if self.payload.get("enforcement_approved") is not True:
                raise RuntimeError("active mode requires explicit enforcement approval")
        else:
            if self.payload.get("mode") != "shadow":
                raise ValueError("shadow mode requires a shadow policy artifact")
            if self.payload.get("enforcement_approved") is not False:
                raise ValueError("shadow policy must explicitly forbid enforcement")

    def metadata(self) -> dict[str, Any]:
        return {
            "schema": POLICY_SCHEMA,
            "name": str(self.payload["name"]),
            "policy_sha256": self.policy_sha256,
            "mode": self.mode,
            "enforcement_enabled": self.enforcement_enabled,
            "enforcement_approved": bool(self.payload["enforcement_approved"]),
            "identity_override_authorized": False,
            "candidate_flow": "preserve_baseline_candidates",
            "guarded_operations": sorted(GUARDED_OPERATIONS),
        }

    @property
    def episode_disabled(self) -> bool:
        return self._disabled

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
        self._disabled = False
        self._disable_reason = None
        self._promotion_veto_streak = 0
        self._events.clear()

    def disable_fail_open(self, reason: str) -> None:
        if not self._disabled:
            self._disabled = True
            self._disable_reason = str(reason)
            self._events.append({
                "event": "v11_consumer_v2_disabled",
                "episode_key": self._episode_key,
                "reason": self._disable_reason,
                "attempt": self._attempt,
                "step": self._step,
                "fail_open": True,
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
        """Replace the current attempt's assessments without touching candidates."""
        try:
            assessments = [self._assessment(output) for output in outputs]
            by_anchor = {
                int(assessment["anchor_index"]): assessment
                for assessment in assessments
            }
            if len(by_anchor) != len(assessments):
                raise ValueError("duplicate V1.1 assessment for one anchor")
            if not by_anchor:
                raise ValueError("no V1.1 assessments")
            self._assessments = by_anchor
            self._attempt = int(attempt)
            self._step = int(step)
        except Exception as exc:
            self.disable_fail_open(f"model_output_invalid:{type(exc).__name__}:{exc}")

    def _record(self, decision: ConsumerGuardDecision) -> ConsumerGuardDecision:
        self._events.append({
            "event": "v11_consumer_v2_decision",
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
    ) -> ConsumerGuardDecision:
        """Evaluate one downstream proposal.

        Reversible candidate/relocalization flow is outside the guarded set and
        is always preserved.  In shadow mode ``executed_allow`` always equals
        the baseline request while ``counterfactual_allow`` records Policy V2.
        """
        operation = str(operation)
        if operation not in GUARDED_OPERATIONS and operation != "relocalization_update":
            raise ValueError(f"unsupported consumer operation: {operation}")

        assessment = (
            self._assessments.get(int(anchor_index))
            if anchor_index is not None else None
        )
        available = assessment is not None
        trusted = (
            bool(assessment["jointly_trusted"])
            if assessment is not None else None
        )
        fail_open = False

        if not baseline_requested:
            counterfactual_allow = False
            reason = "baseline_did_not_request"
        elif operation == "relocalization_update":
            counterfactual_allow = True
            reason = "baseline_relocalization_flow_preserved"
        elif self._disabled:
            counterfactual_allow = True
            reason = f"episode_disabled_fail_open:{self._disable_reason}"
            fail_open = True
        elif self._attempt is None:
            counterfactual_allow = True
            reason = "bootstrap_before_first_score_preserve_baseline"
        elif not available:
            counterfactual_allow = False
            reason = "authoritative_anchor_assessment_missing"
        elif trusted:
            counterfactual_allow = True
            reason = "authoritative_anchor_jointly_trusted"
        else:
            counterfactual_allow = False
            reason = "authoritative_anchor_not_jointly_trusted"

        if operation == "anchor_promotion" and baseline_requested:
            if not counterfactual_allow and not self._disabled:
                self._promotion_veto_streak += 1
                warning = int(self.payload["promotion_veto_warning_streak"])
                fallback = int(self.payload["promotion_veto_fallback_streak"])
                if self._promotion_veto_streak == warning:
                    self._events.append({
                        "event": "v11_consumer_v2_promotion_veto_warning",
                        "episode_key": self._episode_key,
                        "streak": self._promotion_veto_streak,
                        "attempt": self._attempt,
                        "step": self._step,
                    })
                if self._promotion_veto_streak >= fallback:
                    self.disable_fail_open(
                        f"promotion_veto_streak_reached:{fallback}"
                    )
                    counterfactual_allow = True
                    reason = "promotion_veto_fallback_fail_open"
                    fail_open = True
            else:
                self._promotion_veto_streak = 0

        executed_allow = (
            bool(baseline_requested and counterfactual_allow)
            if self.enforcement_enabled and not self._disabled
            else bool(baseline_requested)
        )
        return self._record(ConsumerGuardDecision(
            operation=operation,
            anchor_index=(int(anchor_index) if anchor_index is not None else None),
            baseline_requested=bool(baseline_requested),
            assessment_available=available,
            jointly_trusted=trusted,
            counterfactual_allow=bool(counterfactual_allow),
            executed_allow=executed_allow,
            reason=reason,
            mode=self.mode,
            enforcement_enabled=self.enforcement_enabled,
            controller_effect=(
                self.enforcement_enabled
                and executed_allow != bool(baseline_requested)
            ),
            fail_open=fail_open,
            episode_disabled=self._disabled,
            attempt=self._attempt,
            step=self._step,
        ))
