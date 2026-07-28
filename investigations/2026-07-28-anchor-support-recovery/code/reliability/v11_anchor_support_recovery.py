"""Active Route-2 recovery for the sequential support-anchor pair.

The pair is guidance state, not a claim that the robot is physically between
two adjacent anchors.  ``current`` is a rear support and ``next`` is the
forward guide.  Either role may therefore skip anchors independently.

Active-scan is deliberately absent from the transition function.  The
``shadow_scan_recommended`` output is an observer-only diagnostic: removing
or enabling a scan logger cannot change any field that controls navigation.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import deque
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence


POLICY_SCHEMA = "navila-v11-anchor-support-recovery-active-v1"


@dataclass
class _Evidence:
    trusted: deque[bool] = field(default_factory=deque)
    pose_bad: deque[float] = field(default_factory=deque)


@dataclass(frozen=True)
class AnchorSupportDirective:
    sequence: int
    attempt: int
    step: int
    mode: str
    action: str
    reason: str
    current_anchor_index: int
    next_anchor_index: int
    reconstruct_next_from_current: bool
    promotion_blocked_anchors: tuple[int, ...]
    raw_hint_blocked_anchors: tuple[int, ...]
    probe_anchor_indices: tuple[int, ...]
    route_consumers_enabled: bool
    vlm_only: bool
    shadow_scan_recommended: bool
    current_state: str
    next_state: str
    recovery_stage: int

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class V11AnchorSupportRecovery:
    """Maintain independent rear support and forward guidance anchors."""

    def __init__(
        self,
        payload: Mapping[str, Any],
        *,
        policy_sha256: str | None = None,
    ) -> None:
        self.payload = dict(payload)
        self._validate()
        self.policy_sha256 = policy_sha256 or hashlib.sha256(
            json.dumps(self.payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        self._evidence: dict[int, _Evidence] = {}
        self._sequence = 0
        self._episode_key: str | None = None
        self._current: int | None = None
        self._next: int | None = None
        self._failed_origin_current: int | None = None
        self._failed_origin_next: int | None = None
        self._recovery_stage = -1
        self._vlm_only = False
        self._promotion_blocks: set[int] = set()
        self._raw_hint_blocks: set[int] = set()
        self._events: list[dict[str, Any]] = []

    @classmethod
    def load(cls, path: str | Path) -> "V11AnchorSupportRecovery":
        source = Path(path)
        raw = source.read_bytes()
        return cls(
            json.loads(raw.decode("utf-8")),
            policy_sha256=hashlib.sha256(raw).hexdigest(),
        )

    def _validate(self) -> None:
        if self.payload.get("schema") != POLICY_SCHEMA:
            raise ValueError("unsupported anchor-support recovery schema")
        if self.payload.get("mode") != "active":
            raise ValueError("anchor-support recovery policy must be active")
        if self.payload.get("enforcement_approved") is not True:
            raise ValueError("active policy is not approved")
        if self.payload.get("identity_semantics") != "guidance_support_not_localization":
            raise ValueError("wrong sequential-pair identity semantics")
        for key in (
            "trust_window_attempts",
            "trusted_min_observations",
            "trusted_min_count",
            "strong_untrusted_window_attempts",
            "strong_untrusted_min_observations",
            "strong_untrusted_min_count",
        ):
            if int(self.payload.get(key, 0)) <= 0:
                raise ValueError(f"invalid positive policy field: {key}")
        threshold = float(self.payload.get("strong_untrusted_pose_probability_threshold", 0))
        if not 0.5 < threshold <= 1.0:
            raise ValueError("invalid strong-untrusted probability threshold")
        offsets = self.payload.get("pair_recovery_offsets")
        expected = [[1, 0], [1, -1], [2, -1], [2, -2], [2, -3]]
        if offsets != expected:
            raise ValueError(
                "pair_recovery_offsets must preserve the approved alternating sequence"
            )
        if self.payload.get("probe_direction") != "failed_next_minus_one_to_anchor_zero":
            raise ValueError("unsupported VLM-only probe direction")
        if self.payload.get("scan_role") != "shadow_observer_only":
            raise ValueError("scan must be shadow-observer-only")

    def metadata(self) -> dict[str, Any]:
        return {**self.payload, "policy_sha256": self.policy_sha256}

    @property
    def events(self) -> tuple[dict[str, Any], ...]:
        return tuple(self._events)

    def start_episode(self, episode_key: str) -> None:
        self._episode_key = str(episode_key)
        self._evidence.clear()
        self._sequence = 0
        self._current = None
        self._next = None
        self._failed_origin_current = None
        self._failed_origin_next = None
        self._recovery_stage = -1
        self._vlm_only = False
        self._promotion_blocks.clear()
        self._raw_hint_blocks.clear()
        self._events.clear()

    def _observe(self, output: Mapping[str, Any]) -> None:
        anchor = int(output["anchor_index"])
        evidence = self._evidence.setdefault(anchor, _Evidence())
        evidence.trusted.append(bool(output["jointly_trusted"]))
        probability = float(output["p_pose_bad"])
        if not math.isfinite(probability):
            raise ValueError("non-finite p_pose_bad")
        evidence.pose_bad.append(probability)
        while len(evidence.trusted) > int(self.payload["trust_window_attempts"]):
            evidence.trusted.popleft()
        while len(evidence.pose_bad) > int(
            self.payload["strong_untrusted_window_attempts"]
        ):
            evidence.pose_bad.popleft()

    def _state(self, anchor: int) -> str:
        evidence = self._evidence.get(int(anchor))
        if evidence is None:
            return "missing"
        trusted_min_obs = int(self.payload["trusted_min_observations"])
        trusted_min_count = int(self.payload["trusted_min_count"])
        if (
            len(evidence.trusted) >= trusted_min_obs
            and sum(evidence.trusted) >= trusted_min_count
        ):
            return "trusted"
        bad_threshold = float(
            self.payload["strong_untrusted_pose_probability_threshold"]
        )
        bad_count = sum(value >= bad_threshold for value in evidence.pose_bad)
        if (
            len(evidence.pose_bad)
            >= int(self.payload["strong_untrusted_min_observations"])
            and bad_count >= int(self.payload["strong_untrusted_min_count"])
        ):
            return "strongly_untrusted"
        return "uncertain"

    def _pair_for_stage(self, stage: int) -> tuple[int, int] | None:
        if self._failed_origin_current is None or self._failed_origin_next is None:
            return None
        offsets = self.payload["pair_recovery_offsets"]
        if not 0 <= stage < len(offsets):
            return None
        current_offset, next_offset = offsets[stage]
        current = int(self._failed_origin_current) + int(current_offset)
        next_anchor = int(self._failed_origin_next) + int(next_offset)
        if current < 0 or next_anchor < 0:
            return None
        return current, next_anchor

    def _probe_pool(self) -> tuple[int, ...]:
        if self._failed_origin_next is None:
            return ()
        return tuple(range(int(self._failed_origin_next) - 1, -1, -1))

    def _set_pair_recovery_origin(self, current: int, next_anchor: int) -> None:
        if self._failed_origin_current is None:
            self._failed_origin_current = int(current)
            self._failed_origin_next = int(next_anchor)
            self._recovery_stage = -1

    def _clear_pair_recovery(self) -> None:
        self._failed_origin_current = None
        self._failed_origin_next = None
        self._recovery_stage = -1

    def _directive(
        self,
        *,
        attempt: int,
        step: int,
        mode: str,
        action: str,
        reason: str,
        current_state: str,
        next_state: str,
        reconstruct: bool = False,
        probes: tuple[int, ...] = (),
        consumers: bool = True,
        shadow_scan: bool = False,
    ) -> AnchorSupportDirective:
        assert self._current is not None and self._next is not None
        directive = AnchorSupportDirective(
            sequence=self._sequence,
            attempt=int(attempt),
            step=int(step),
            mode=mode,
            action=action,
            reason=reason,
            current_anchor_index=int(self._current),
            next_anchor_index=int(self._next),
            reconstruct_next_from_current=bool(reconstruct),
            promotion_blocked_anchors=tuple(sorted(self._promotion_blocks)),
            raw_hint_blocked_anchors=tuple(sorted(self._raw_hint_blocks)),
            probe_anchor_indices=tuple(int(index) for index in probes if index >= 0),
            route_consumers_enabled=bool(consumers),
            vlm_only=not consumers,
            shadow_scan_recommended=bool(shadow_scan),
            current_state=current_state,
            next_state=next_state,
            recovery_stage=int(self._recovery_stage),
        )
        self._events.append({
            "event": "v11_anchor_support_recovery",
            "episode_key": self._episode_key,
            **directive.as_dict(),
        })
        return directive

    def observe_scores(
        self,
        outputs: Sequence[Mapping[str, Any]],
        *,
        requested_current_index: int,
        requested_next_index: int,
        attempt: int,
        step: int,
    ) -> AnchorSupportDirective:
        """Observe Route-2 judgements and choose the next support pair.

        Extra outputs are probe-only.  They can restore a forward guide in
        VLM-only mode, but can never silently become ``current``.
        """
        self._sequence += 1
        if self._current is None:
            self._current = int(requested_current_index)
        if self._next is None:
            self._next = int(requested_next_index)
        for output in outputs:
            self._observe(output)
        # A raw ICP reading is barred from hint authority while Route-2 still
        # considers that anchor bad.  Promotion blocks remain persistent, but
        # raw-hint blocks must clear when later robot motion produces enough
        # trusted evidence; otherwise VLM-only probing could discover a good
        # forward guide and then be unable to use it.
        for output in outputs:
            anchor_index = int(output["anchor_index"])
            if self._state(anchor_index) == "trusted":
                self._raw_hint_blocks.discard(anchor_index)

        requested_current = int(requested_current_index)
        requested_next = int(requested_next_index)
        current_state = self._state(requested_current)
        next_state = self._state(requested_next)

        if self._vlm_only:
            if (
                current_state == "trusted"
                and next_state == "strongly_untrusted"
            ):
                self._current = requested_current
                self._next = requested_next
                self._promotion_blocks.add(requested_next)
                self._raw_hint_blocks.add(requested_next)
                self._vlm_only = False
                self._clear_pair_recovery()
                return self._directive(
                    attempt=attempt,
                    step=step,
                    mode="reconstruct_next",
                    action="resume_from_recovered_current_and_reconstruct_next",
                    reason="rear_support_became_trusted_after_robot_motion",
                    current_state=current_state,
                    next_state=next_state,
                    reconstruct=True,
                )
            if next_state == "trusted":
                self._current = requested_current
                self._next = requested_next
                self._vlm_only = False
                self._clear_pair_recovery()
                return self._directive(
                    attempt=attempt,
                    step=step,
                    mode="next_only",
                    action="resume_from_recovered_requested_next",
                    reason="requested_forward_guide_became_trusted_after_robot_motion",
                    current_state=current_state,
                    next_state=next_state,
                )
            recovered = [
                index for index in self._probe_pool()
                if self._state(index) == "trusted"
            ]
            if recovered:
                self._next = max(recovered)
                self._vlm_only = False
                self._clear_pair_recovery()
                return self._directive(
                    attempt=attempt,
                    step=step,
                    mode="next_only",
                    action="resume_from_trusted_forward_probe",
                    reason="forward_anchor_became_trusted_after_robot_motion",
                    current_state=self._state(self._current),
                    next_state=self._state(self._next),
                )
            return self._directive(
                attempt=attempt,
                step=step,
                mode="vlm_only_probing",
                action="continue_vlm_only_and_probe_forward_anchors",
                reason="no_trusted_support_anchor_available",
                current_state=self._state(self._current),
                next_state=self._state(self._next),
                probes=self._probe_pool(),
                consumers=False,
                shadow_scan=True,
            )

        if current_state == "trusted" and next_state == "trusted":
            self._current = requested_current
            self._next = requested_next
            self._clear_pair_recovery()
            return self._directive(
                attempt=attempt,
                step=step,
                mode="normal",
                action="keep_trusted_support_pair",
                reason="both_support_roles_trusted",
                current_state=current_state,
                next_state=next_state,
            )

        if current_state == "trusted" and next_state == "strongly_untrusted":
            self._current = requested_current
            self._next = requested_next
            self._promotion_blocks.add(requested_next)
            self._raw_hint_blocks.add(requested_next)
            self._clear_pair_recovery()
            return self._directive(
                attempt=attempt,
                step=step,
                mode="reconstruct_next",
                action="reconstruct_bad_next_from_trusted_current",
                reason="trusted_rear_support_replaces_bad_forward_icp",
                current_state=current_state,
                next_state=next_state,
                reconstruct=True,
            )

        if next_state == "trusted":
            self._current = requested_current
            self._next = requested_next
            self._clear_pair_recovery()
            return self._directive(
                attempt=attempt,
                step=step,
                mode="next_only",
                action="use_trusted_next_without_current_veto",
                reason="forward_guide_is_sufficient_for_navigation",
                current_state=current_state,
                next_state=next_state,
            )

        if (
            current_state == "strongly_untrusted"
            and next_state == "strongly_untrusted"
        ):
            self._promotion_blocks.update((requested_current, requested_next))
            self._raw_hint_blocks.update((requested_current, requested_next))
            self._set_pair_recovery_origin(requested_current, requested_next)
            self._recovery_stage += 1
            pair = self._pair_for_stage(self._recovery_stage)
            if pair is not None:
                self._current, self._next = pair
                return self._directive(
                    attempt=attempt,
                    step=step,
                    mode="pair_recovery",
                    action="advance_alternating_support_search",
                    reason="both_requested_support_anchors_untrusted",
                    current_state=current_state,
                    next_state=next_state,
                    shadow_scan=True,
                )
            self._vlm_only = True
            return self._directive(
                attempt=attempt,
                step=step,
                mode="vlm_only_probing",
                action="suspend_route_consumers_and_probe_forward_anchors",
                reason="bounded_bidirectional_support_search_exhausted",
                current_state=current_state,
                next_state=next_state,
                probes=self._probe_pool(),
                consumers=False,
                shadow_scan=True,
            )

        return self._directive(
            attempt=attempt,
            step=step,
            mode="evidence_pending",
            action="hold_pair_while_evidence_accumulates",
            reason="neither_trust_nor_strong_failure_confirmed",
            current_state=current_state,
            next_state=next_state,
        )
