"""Shadow-only per-anchor state transitions for Scheme-1 integration."""

from __future__ import annotations

import hashlib
import json
from collections import deque
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Mapping


POLICY_SCHEMA = "navila-v11-integrated-anchor-state-shadow-v1"


@dataclass
class AnchorEvidenceState:
    trusted_streak: int = 0
    last_seen_sequence: int = 0
    observations: deque[bool] = field(default_factory=deque)
    pose_bad_probabilities: deque[float] = field(default_factory=deque)

    @property
    def trusted_observations(self) -> int:
        return sum(self.observations)

    @property
    def trusted_fraction(self) -> float | None:
        if not self.observations:
            return None
        return self.trusted_observations / len(self.observations)

    def strong_untrusted_count(self, threshold: float) -> int:
        return sum(
            probability >= threshold
            for probability in self.pose_bad_probabilities
        )

    def strong_untrusted_fraction(self, threshold: float) -> float | None:
        if not self.pose_bad_probabilities:
            return None
        return (
            self.strong_untrusted_count(threshold)
            / len(self.pose_bad_probabilities)
        )


@dataclass(frozen=True)
class AnchorStateShadowDecision:
    sequence: int
    attempt: int | None
    step: int | None
    current_anchor_index: int
    next_anchor_index: int
    current_state: str
    next_state: str
    action: str
    reason: str
    controller_effect: bool
    requires_expanded_candidates: bool
    would_suppress_precise_hint: bool
    current_changed: bool
    expired_quarantines: tuple[int, ...]
    released_quarantines: tuple[int, ...]
    shadow_quarantined_anchors: tuple[int, ...]
    quarantine_chain_anchors: tuple[int, ...]
    quarantine_cycles_for_next: int
    next_quarantine_until_sequence: int | None
    current_evidence_window_size: int
    next_evidence_window_size: int
    current_trusted_fraction: float | None
    next_trusted_fraction: float | None
    current_pose_bad_window_size: int
    next_pose_bad_window_size: int
    current_strong_untrusted_count: int
    next_strong_untrusted_count: int
    current_strong_untrusted_fraction: float | None
    next_strong_untrusted_fraction: float | None
    active_scan_latched: bool
    active_scan_trigger_action: str | None
    active_scan_trigger_reason: str | None
    active_scan_recovery_streak: int
    cancelled_active_scan_trigger_action: str | None
    baseline_vote: bool
    pre_closure_vote: bool
    geometry_fallback_streak: int
    geometry_fallback_attempt_limit: int
    geometry_fallback_active: bool

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class V11IntegratedAnchorStateShadow:
    """Temporal, reversible state recommendations with no controller effect."""

    def __init__(
        self,
        payload: Mapping[str, Any],
        *,
        policy_sha256: str | None = None,
    ) -> None:
        self.payload = dict(payload)
        self._validate_payload()
        self.policy_sha256 = policy_sha256 or hashlib.sha256(
            json.dumps(
                self.payload,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        self._episode_key: str | None = None
        self._sequence = 0
        self._last_current_index: int | None = None
        self._evidence: dict[int, AnchorEvidenceState] = {}
        self._quarantine_until: dict[int, int] = {}
        self._quarantine_chain_anchors: set[int] = set()
        self._quarantine_cycles: dict[int, int] = {}
        self._both_untrusted_streak = 0
        self._active_scan_trigger_action: str | None = None
        self._active_scan_trigger_reason: str | None = None
        self._active_scan_recovery_streak = 0
        self._geometry_fallback_pair: tuple[int, int] | None = None
        self._geometry_fallback_streak = 0
        self._events: list[dict[str, Any]] = []

    @classmethod
    def load(cls, path: str | Path) -> "V11IntegratedAnchorStateShadow":
        source = Path(path)
        raw = source.read_bytes()
        return cls(
            json.loads(raw.decode("utf-8")),
            policy_sha256=hashlib.sha256(raw).hexdigest(),
        )

    def _validate_payload(self) -> None:
        if self.payload.get("schema") != POLICY_SCHEMA:
            raise ValueError(
                f"unsupported integrated anchor-state schema: "
                f"{self.payload.get('schema')}"
            )
        if self.payload.get("mode") != "shadow":
            raise ValueError("integrated anchor state is shadow-only")
        if self.payload.get("enforcement_approved") is not False:
            raise ValueError("shadow policy must forbid enforcement")
        if self.payload.get("identity_override_authorized") is not False:
            raise ValueError("shadow policy must forbid identity override")
        if self.payload.get("candidate_direction") != "descending_anchor_index":
            raise ValueError("unsupported candidate direction")
        for key in (
            "trusted_confirm_attempts",
            "both_untrusted_scan_attempts",
            "quarantine_ttl_attempts",
            "max_quarantine_chain",
            "max_quarantine_cycles_per_anchor",
            "trust_window_attempts",
            "active_scan_cancel_trusted_attempts",
            "strong_untrusted_window_attempts",
            "strong_untrusted_min_observations",
            "strong_untrusted_min_count",
        ):
            if int(self.payload.get(key, 0)) <= 0:
                raise ValueError(f"invalid positive integer policy field: {key}")
        if int(self.payload["trust_window_attempts"]) < int(
            self.payload["trusted_confirm_attempts"]
        ):
            raise ValueError(
                "trust_window_attempts must cover trusted confirmation"
            )
        trusted_fraction = float(
            self.payload.get("trusted_fraction_threshold", 0.0)
        )
        if not 0.5 < trusted_fraction <= 1.0:
            raise ValueError(
                "trusted_fraction_threshold must be greater than 0.5 "
                "and at most 1.0"
            )
        strong_threshold = float(
            self.payload.get(
                "strong_untrusted_pose_probability_threshold", -1.0
            )
        )
        if not 0.5 < strong_threshold <= 1.0:
            raise ValueError(
                "strong_untrusted_pose_probability_threshold must be "
                "greater than 0.5 and at most 1.0"
            )
        if int(self.payload["strong_untrusted_window_attempts"]) < int(
            self.payload["strong_untrusted_min_observations"]
        ):
            raise ValueError(
                "strong-untrusted window must cover minimum observations"
            )
        if int(self.payload["strong_untrusted_min_observations"]) < int(
            self.payload["strong_untrusted_min_count"]
        ):
            raise ValueError(
                "strong-untrusted observations must cover minimum count"
            )
        if self.payload.get(
            "trusted_current_geometry_fallback_enabled", False
        ):
            if int(self.payload.get(
                "trusted_current_geometry_fallback_attempts", 0
            )) <= 0:
                raise ValueError(
                    "trusted-current geometry fallback needs a positive "
                    "attempt budget"
                )

    def metadata(self) -> dict[str, Any]:
        return {
            **self.payload,
            "policy_sha256": self.policy_sha256,
        }

    @property
    def events(self) -> tuple[dict[str, Any], ...]:
        return tuple(self._events)

    def start_episode(self, episode_key: str) -> None:
        self._episode_key = str(episode_key)
        self._sequence = 0
        self._last_current_index = None
        self._evidence.clear()
        self._quarantine_until.clear()
        self._quarantine_chain_anchors.clear()
        self._quarantine_cycles.clear()
        self._both_untrusted_streak = 0
        self._active_scan_trigger_action = None
        self._active_scan_trigger_reason = None
        self._active_scan_recovery_streak = 0
        self._geometry_fallback_pair = None
        self._geometry_fallback_streak = 0
        self._events.clear()

    @staticmethod
    def _field(decision: object, name: str) -> Any:
        if isinstance(decision, Mapping):
            return decision[name]
        return getattr(decision, name)

    def _update_evidence(
        self,
        anchor_index: int,
        *,
        available: bool,
        trusted: bool | None,
        pose_bad_probability: float | None,
    ) -> AnchorEvidenceState:
        state = self._evidence.setdefault(int(anchor_index), AnchorEvidenceState())
        state.last_seen_sequence = self._sequence
        if not available or trusted is None:
            state.trusted_streak = 0
        elif bool(trusted):
            state.trusted_streak += 1
        else:
            state.trusted_streak = 0
        if available and trusted is not None:
            state.observations.append(bool(trusted))
            window = int(self.payload["trust_window_attempts"])
            while len(state.observations) > window:
                state.observations.popleft()
        if available and pose_bad_probability is not None:
            probability = float(pose_bad_probability)
            if not 0.0 <= probability <= 1.0:
                raise ValueError("pose-bad probability must be in [0, 1]")
            state.pose_bad_probabilities.append(probability)
            strong_window = int(
                self.payload["strong_untrusted_window_attempts"]
            )
            while len(state.pose_bad_probabilities) > strong_window:
                state.pose_bad_probabilities.popleft()
        return state

    def _classification(
        self,
        state: AnchorEvidenceState,
        *,
        available: bool,
    ) -> str:
        if not available:
            return "missing"
        observation_count = len(state.observations)
        probability_count = len(state.pose_bad_probabilities)
        if observation_count == 0 and probability_count == 0:
            return "uncertain"
        strong_threshold = float(
            self.payload[
                "strong_untrusted_pose_probability_threshold"
            ]
        )
        if (
            probability_count
            >= int(self.payload["strong_untrusted_min_observations"])
            and state.strong_untrusted_count(strong_threshold)
            >= int(self.payload["strong_untrusted_min_count"])
        ):
            return "strongly_untrusted"
        trusted_fraction = state.trusted_fraction
        if (
            trusted_fraction is not None
            and observation_count
            >= int(self.payload["trusted_confirm_attempts"])
            and trusted_fraction
            >= float(self.payload["trusted_fraction_threshold"])
        ):
            return "trusted"
        return "uncertain"

    def _request_active_scan(
        self,
        *,
        trigger_action: str,
        trigger_reason: str,
    ) -> tuple[str, str]:
        if self._active_scan_trigger_action is None:
            self._active_scan_trigger_action = trigger_action
            self._active_scan_trigger_reason = trigger_reason
            self._active_scan_recovery_streak = 0
            return trigger_action, trigger_reason
        return (
            "hold_active_scan_request",
            "active_scan_request_already_latched",
        )

    def observe(self, promotion_decision: object) -> AnchorStateShadowDecision:
        """Record one counterfactual state transition recommendation."""
        self._sequence += 1
        current_index = int(self._field(
            promotion_decision, "current_anchor_index"
        ))
        next_index = int(self._field(promotion_decision, "next_anchor_index"))
        current_changed = bool(
            self._last_current_index is not None
            and current_index != self._last_current_index
        )
        if current_changed:
            # Reliability observations are conditional on the current camera
            # pose and route phase.  Reusing a candidate's old probability
            # window after Route1 advances current can immediately quarantine
            # a now-correct anchor from stale evidence.
            self._evidence.clear()
            self._quarantine_until.clear()
            self._quarantine_chain_anchors.clear()
            self._quarantine_cycles.clear()
            self._both_untrusted_streak = 0
            self._active_scan_trigger_action = None
            self._active_scan_trigger_reason = None
            self._active_scan_recovery_streak = 0
            self._geometry_fallback_pair = None
            self._geometry_fallback_streak = 0
        self._last_current_index = current_index

        expired = tuple(sorted(
            anchor
            for anchor, until in self._quarantine_until.items()
            if self._sequence >= until
        ))
        for anchor in expired:
            del self._quarantine_until[anchor]

        current_available = bool(self._field(
            promotion_decision, "current_assessment_available"
        ))
        next_available = bool(self._field(
            promotion_decision, "next_assessment_available"
        ))
        current_trusted = self._field(
            promotion_decision, "current_jointly_trusted"
        )
        next_trusted = self._field(
            promotion_decision, "next_jointly_trusted"
        )
        current_pose_bad_probability = self._field(
            promotion_decision, "current_p_pose_bad"
        )
        next_pose_bad_probability = self._field(
            promotion_decision, "next_p_pose_bad"
        )
        current_evidence = self._update_evidence(
            current_index,
            available=current_available,
            trusted=current_trusted,
            pose_bad_probability=current_pose_bad_probability,
        )
        next_evidence = self._update_evidence(
            next_index,
            available=next_available,
            trusted=next_trusted,
            pose_bad_probability=next_pose_bad_probability,
        )
        current_state = self._classification(
            current_evidence,
            available=current_available,
        )
        next_state = self._classification(
            next_evidence,
            available=next_available,
        )
        if not (
            current_state == "trusted"
            and next_state == "strongly_untrusted"
        ):
            self._geometry_fallback_pair = None
            self._geometry_fallback_streak = 0

        released: list[int] = []
        if (
            next_index in self._quarantine_until
            and next_state == "trusted"
        ):
            del self._quarantine_until[next_index]
            released.append(next_index)

        if (
            current_state == "strongly_untrusted"
            and next_state == "strongly_untrusted"
        ):
            self._both_untrusted_streak += 1
        else:
            self._both_untrusted_streak = 0

        cancelled_scan_trigger: str | None = None
        if self._active_scan_trigger_action is not None:
            if (
                self._active_scan_trigger_action
                == "request_active_scan_both_untrusted"
            ):
                scan_recovery_observed = (
                    current_state == "trusted" or next_state == "trusted"
                )
            else:
                scan_recovery_observed = next_state == "trusted"
            if scan_recovery_observed:
                self._active_scan_recovery_streak += 1
            else:
                self._active_scan_recovery_streak = 0
            if (
                self._active_scan_recovery_streak
                >= int(self.payload["active_scan_cancel_trusted_attempts"])
            ):
                cancelled_scan_trigger = self._active_scan_trigger_action
                self._active_scan_trigger_action = None
                self._active_scan_trigger_reason = None
                self._active_scan_recovery_streak = 0

        action = "accumulate_evidence"
        reason = "trust_confirmation_pending"
        requires_expanded = False
        suppress_hint = False

        if cancelled_scan_trigger is not None:
            action = "cancel_active_scan_on_trust_recovery"
            reason = "trusted_anchor_recovery_confirmed"
        elif self._active_scan_trigger_action is not None:
            action = "hold_active_scan_request"
            reason = "active_scan_request_already_latched"
            requires_expanded = True
            suppress_hint = (
                current_state == "strongly_untrusted"
                and next_state == "strongly_untrusted"
            )
        elif released:
            action = "release_quarantine_on_trusted_reentry"
            reason = "next_reestablished_trust_with_hysteresis"
        elif current_state == "missing" or next_state == "missing":
            action = "hold_missing_assessment"
            reason = "current_or_next_assessment_missing"
        elif (
            current_state == "strongly_untrusted"
            and next_state == "strongly_untrusted"
            and self._both_untrusted_streak
            >= int(self.payload["both_untrusted_scan_attempts"])
        ):
            action, reason = self._request_active_scan(
                trigger_action="request_active_scan_both_untrusted",
                trigger_reason="both_anchors_confirmed_untrusted",
            )
            requires_expanded = True
            suppress_hint = True
        elif (
            next_state == "strongly_untrusted"
            and current_state != "trusted"
        ):
            action = "hold_strong_next_without_current_authority"
            reason = "strong_next_requires_trusted_current_for_quarantine"
            requires_expanded = True
            suppress_hint = True
        elif next_state == "strongly_untrusted":
            geometry_fallback_enabled = bool(self.payload.get(
                "trusted_current_geometry_fallback_enabled", False
            ))
            if geometry_fallback_enabled and current_state == "trusted":
                pair = (current_index, next_index)
                if self._geometry_fallback_pair == pair:
                    self._geometry_fallback_streak += 1
                else:
                    self._geometry_fallback_pair = pair
                    self._geometry_fallback_streak = 1
                fallback_limit = int(self.payload[
                    "trusted_current_geometry_fallback_attempts"
                ])
                if self._geometry_fallback_streak <= fallback_limit:
                    action = "use_trusted_current_geometry_fallback"
                    reason = (
                        "trusted_current_projects_strongly_untrusted_next"
                    )
                else:
                    action, reason = self._request_active_scan(
                        trigger_action=(
                            "request_active_scan_geometry_fallback_exhausted"
                        ),
                        trigger_reason=(
                            "trusted_current_geometry_fallback_budget_exhausted"
                        ),
                    )
                    requires_expanded = True
            elif next_index in self._quarantine_until:
                action = "hold_temporary_quarantine"
                reason = "next_anchor_quarantine_active"
                requires_expanded = True
            elif (
                len(self._quarantine_chain_anchors)
                >= int(self.payload["max_quarantine_chain"])
                and next_index not in self._quarantine_chain_anchors
            ):
                action, reason = self._request_active_scan(
                    trigger_action="request_active_scan_chain_budget_exhausted",
                    trigger_reason="quarantine_chain_budget_exhausted",
                )
                requires_expanded = True
                suppress_hint = current_state != "trusted"
            elif (
                self._quarantine_cycles.get(next_index, 0)
                >= int(self.payload["max_quarantine_cycles_per_anchor"])
            ):
                action, reason = self._request_active_scan(
                    trigger_action="request_active_scan_repeated_quarantine",
                    trigger_reason="same_anchor_quarantine_cycles_exhausted",
                )
                requires_expanded = True
                suppress_hint = current_state != "trusted"
            else:
                self._quarantine_until[next_index] = (
                    self._sequence + int(self.payload["quarantine_ttl_attempts"])
                )
                self._quarantine_chain_anchors.add(next_index)
                self._quarantine_cycles[next_index] = (
                    self._quarantine_cycles.get(next_index, 0) + 1
                )
                action = "temporarily_quarantine_next"
                reason = "next_confirmed_untrusted"
                requires_expanded = True
        elif (
            current_state == "strongly_untrusted"
            and next_state == "trusted"
        ):
            if (
                bool(self._field(promotion_decision, "pre_closure_vote"))
                and not bool(self._field(promotion_decision, "baseline_vote"))
            ):
                action = "admit_next_evidence_without_current_veto"
                reason = "current_untrusted_next_trusted_closure_veto"
            else:
                action = "preserve_next_gate_without_current_authority"
                reason = "trusted_next_has_no_positive_pre_closure_vote"
        elif current_state == "trusted" and next_state == "trusted":
            action = "preserve_route1_vote"
            reason = "both_anchors_confirmed_trusted"

        decision = AnchorStateShadowDecision(
            sequence=self._sequence,
            attempt=self._field(promotion_decision, "attempt"),
            step=self._field(promotion_decision, "step"),
            current_anchor_index=current_index,
            next_anchor_index=next_index,
            current_state=current_state,
            next_state=next_state,
            action=action,
            reason=reason,
            controller_effect=False,
            requires_expanded_candidates=requires_expanded,
            would_suppress_precise_hint=suppress_hint,
            current_changed=current_changed,
            expired_quarantines=expired,
            released_quarantines=tuple(released),
            shadow_quarantined_anchors=tuple(sorted(self._quarantine_until)),
            quarantine_chain_anchors=tuple(
                sorted(self._quarantine_chain_anchors)
            ),
            quarantine_cycles_for_next=self._quarantine_cycles.get(
                next_index, 0
            ),
            next_quarantine_until_sequence=self._quarantine_until.get(
                next_index
            ),
            current_evidence_window_size=len(current_evidence.observations),
            next_evidence_window_size=len(next_evidence.observations),
            current_trusted_fraction=current_evidence.trusted_fraction,
            next_trusted_fraction=next_evidence.trusted_fraction,
            current_pose_bad_window_size=len(
                current_evidence.pose_bad_probabilities
            ),
            next_pose_bad_window_size=len(
                next_evidence.pose_bad_probabilities
            ),
            current_strong_untrusted_count=(
                current_evidence.strong_untrusted_count(
                    float(self.payload[
                        "strong_untrusted_pose_probability_threshold"
                    ])
                )
            ),
            next_strong_untrusted_count=(
                next_evidence.strong_untrusted_count(
                    float(self.payload[
                        "strong_untrusted_pose_probability_threshold"
                    ])
                )
            ),
            current_strong_untrusted_fraction=(
                current_evidence.strong_untrusted_fraction(
                    float(self.payload[
                        "strong_untrusted_pose_probability_threshold"
                    ])
                )
            ),
            next_strong_untrusted_fraction=(
                next_evidence.strong_untrusted_fraction(
                    float(self.payload[
                        "strong_untrusted_pose_probability_threshold"
                    ])
                )
            ),
            active_scan_latched=self._active_scan_trigger_action is not None,
            active_scan_trigger_action=self._active_scan_trigger_action,
            active_scan_trigger_reason=self._active_scan_trigger_reason,
            active_scan_recovery_streak=self._active_scan_recovery_streak,
            cancelled_active_scan_trigger_action=cancelled_scan_trigger,
            baseline_vote=bool(self._field(
                promotion_decision, "baseline_vote"
            )),
            pre_closure_vote=bool(self._field(
                promotion_decision, "pre_closure_vote"
            )),
            geometry_fallback_streak=self._geometry_fallback_streak,
            geometry_fallback_attempt_limit=int(self.payload.get(
                "trusted_current_geometry_fallback_attempts", 0
            )),
            geometry_fallback_active=(
                action == "use_trusted_current_geometry_fallback"
            ),
        )
        self._events.append({
            "event": "v11_integrated_anchor_state_shadow_decision",
            "episode_key": self._episode_key,
            **decision.as_dict(),
        })
        return decision
