"""Bounded active guard for Anchor Transition V1.

The learned model is deliberately not an anchor selector.  A complete model
observation from attempt ``t`` may only defer a baseline promotion proposed on
attempt ``t + 1`` when it reports a high-confidence over-advance risk.  The
guard never creates a promotion, changes either anchor index, or suppresses a
promotion indefinitely.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Optional


SCHEMA = "navila-anchor-transition-promotion-guard-v1"
KNOWN_ACTIONS = frozenset(
    {"advance_one", "hold", "rebase", "rollback", "skip_or_rebase"}
)
OVER_ADVANCE_RISK_ACTIONS = frozenset({"rollback", "skip_or_rebase"})


@dataclass(frozen=True)
class AnchorTransitionSignal:
    attempt: int
    action: str
    confidence: float
    model_sha256: str
    feature_timing: str = "previous_complete_attempt"


@dataclass(frozen=True)
class PromotionGuardDecision:
    current_anchor_index: int
    next_anchor_index: int
    proposal_attempt: int
    baseline_vote: bool
    executed_vote: bool
    controller_effect: str
    reason: str
    deferrals_used: int
    deferral_limit: int
    signal_attempt: Optional[int]
    signal_action: Optional[str]
    signal_confidence: Optional[float]
    model_sha256: Optional[str]

    def as_dict(self) -> dict:
        return {"schema": SCHEMA, **asdict(self)}


class AnchorTransitionPromotionGuard:
    """Fail-open, bounded veto around an existing promotion decision."""

    def __init__(
        self,
        *,
        confidence_threshold: float = 0.90,
        max_deferrals_per_candidate: int = 2,
        required_signal_age_attempts: int = 1,
        expected_model_sha256: str | None = None,
    ) -> None:
        if not 0.0 <= float(confidence_threshold) <= 1.0:
            raise ValueError("confidence_threshold must be in [0, 1]")
        if int(max_deferrals_per_candidate) < 0:
            raise ValueError("max_deferrals_per_candidate must be non-negative")
        if int(required_signal_age_attempts) != 1:
            raise ValueError(
                "v1 requires exactly one complete-attempt of causal lag"
            )
        self.confidence_threshold = float(confidence_threshold)
        self.max_deferrals_per_candidate = int(max_deferrals_per_candidate)
        self.required_signal_age_attempts = int(
            required_signal_age_attempts
        )
        self.expected_model_sha256 = expected_model_sha256
        self.events: list[dict] = []
        self._latest_signal: AnchorTransitionSignal | None = None
        self._last_observed_attempt: int | None = None
        self._deferrals_by_candidate: dict[int, int] = {}

    def start_episode(self) -> None:
        self.events.clear()
        self._latest_signal = None
        self._last_observed_attempt = None
        self._deferrals_by_candidate.clear()

    def observe(
        self,
        *,
        attempt: int,
        action: str,
        confidence: float,
        model_sha256: str,
        feature_timing: str = "previous_complete_attempt",
    ) -> AnchorTransitionSignal:
        attempt = int(attempt)
        action = str(action)
        confidence = float(confidence)
        model_sha256 = str(model_sha256)
        if action not in KNOWN_ACTIONS:
            raise ValueError(f"unknown anchor transition action: {action}")
        if not 0.0 <= confidence <= 1.0:
            raise ValueError("confidence must be in [0, 1]")
        if (
            self._last_observed_attempt is not None
            and attempt <= self._last_observed_attempt
        ):
            raise ValueError("anchor transition attempts must be increasing")
        if (
            self.expected_model_sha256 is not None
            and model_sha256 != self.expected_model_sha256
        ):
            raise ValueError("anchor transition model hash mismatch")
        if feature_timing != "previous_complete_attempt":
            raise ValueError("non-causal anchor feature timing is forbidden")
        signal = AnchorTransitionSignal(
            attempt=attempt,
            action=action,
            confidence=confidence,
            model_sha256=model_sha256,
            feature_timing=feature_timing,
        )
        self._latest_signal = signal
        self._last_observed_attempt = attempt
        self.events.append(
            {
                "schema": SCHEMA,
                "event": "anchor_transition_signal",
                **asdict(signal),
            }
        )
        return signal

    def evaluate(
        self,
        *,
        current_anchor_index: int,
        next_anchor_index: int,
        proposal_attempt: int,
        baseline_vote: bool,
        kill_switch_engaged: bool = False,
    ) -> PromotionGuardDecision:
        current_anchor_index = int(current_anchor_index)
        next_anchor_index = int(next_anchor_index)
        proposal_attempt = int(proposal_attempt)
        baseline_vote = bool(baseline_vote)
        signal = self._latest_signal
        used = self._deferrals_by_candidate.get(next_anchor_index, 0)

        executed_vote = baseline_vote
        effect = "none"
        reason = "baseline_not_promoting"

        if baseline_vote:
            reason = "fail_open_no_signal"
            if kill_switch_engaged:
                reason = "fail_open_kill_switch"
            elif next_anchor_index != current_anchor_index - 1:
                reason = "fail_open_non_adjacent_identity"
            elif signal is None:
                reason = "fail_open_no_signal"
            elif (
                proposal_attempt - signal.attempt
                != self.required_signal_age_attempts
            ):
                reason = "fail_open_stale_or_same_attempt_signal"
            elif signal.action not in OVER_ADVANCE_RISK_ACTIONS:
                reason = "allow_no_over_advance_risk"
            elif signal.confidence < self.confidence_threshold:
                reason = "allow_below_confidence_threshold"
            elif used >= self.max_deferrals_per_candidate:
                reason = "fail_open_deferral_cap"
            else:
                used += 1
                self._deferrals_by_candidate[next_anchor_index] = used
                executed_vote = False
                effect = "defer_promotion"
                reason = "bounded_previous_attempt_over_advance_veto"

        decision = PromotionGuardDecision(
            current_anchor_index=current_anchor_index,
            next_anchor_index=next_anchor_index,
            proposal_attempt=proposal_attempt,
            baseline_vote=baseline_vote,
            executed_vote=executed_vote,
            controller_effect=effect,
            reason=reason,
            deferrals_used=used,
            deferral_limit=self.max_deferrals_per_candidate,
            signal_attempt=signal.attempt if signal is not None else None,
            signal_action=signal.action if signal is not None else None,
            signal_confidence=(
                signal.confidence if signal is not None else None
            ),
            model_sha256=signal.model_sha256 if signal is not None else None,
        )
        self.events.append(
            {
                "schema": SCHEMA,
                "event": "anchor_transition_promotion_decision",
                **asdict(decision),
            }
        )
        return decision
