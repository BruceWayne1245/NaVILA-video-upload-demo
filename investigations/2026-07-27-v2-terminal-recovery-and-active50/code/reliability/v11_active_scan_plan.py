"""Default-closed, rotation-only Active Scan V1 plan generator.

This module defines the motor interface and bounded scan geometry without
executing simulator actions.  Shadow plans are emitted once per latched scan
request; a later, separately approved executor can consume the same plan.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping


POLICY_SCHEMA = "navila-v11-active-scan-plan-v1"


@dataclass(frozen=True)
class ActiveScanRotation:
    index: int
    target_offset_deg: float
    delta_yaw_deg: float
    angular_velocity_deg_s: float
    duration_s: float
    capture_after_rotation: bool


@dataclass(frozen=True)
class ActiveScanPlan:
    sequence: int
    attempt: int | None
    step: int | None
    current_anchor_index: int
    next_anchor_index: int
    trigger_action: str
    trigger_reason: str
    rotations: tuple[ActiveScanRotation, ...]
    recovery_confirm_assessments: int
    max_scan_cycles: int
    translation_authorized: bool
    stop_authorized: bool
    motor_effect: bool
    failure_action: str

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["rotations"] = [
            asdict(rotation) for rotation in self.rotations
        ]
        return payload


class V11ActiveScanPlanShadow:
    """Emit one finite yaw-sweep plan per state-machine scan latch."""

    def __init__(
        self,
        payload: Mapping[str, Any],
        *,
        policy_sha256: str | None = None,
    ) -> None:
        self.payload = dict(payload)
        self._validate()
        self.policy_sha256 = policy_sha256 or hashlib.sha256(
            json.dumps(
                self.payload,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        self._episode_key: str | None = None
        self._latched = False
        self._events: list[dict[str, Any]] = []

    @classmethod
    def load(cls, path: str | Path) -> "V11ActiveScanPlanShadow":
        source = Path(path)
        raw = source.read_bytes()
        return cls(
            json.loads(raw.decode("utf-8")),
            policy_sha256=hashlib.sha256(raw).hexdigest(),
        )

    def _validate(self) -> None:
        if self.payload.get("schema") != POLICY_SCHEMA:
            raise ValueError("invalid active-scan plan schema")
        if self.payload.get("mode") != "shadow":
            raise ValueError("active-scan plan is shadow-only")
        if self.payload.get("enforcement_approved") is not False:
            raise ValueError("shadow scan plan cannot be approved")
        if self.payload.get("motor_rotation_authorized") is not False:
            raise ValueError("shadow scan plan cannot rotate the robot")
        if self.payload.get("motor_translation_authorized") is not False:
            raise ValueError("scan V1 forbids translation")
        if self.payload.get("stop_authorized") is not False:
            raise ValueError("scan V1 forbids stop decisions")
        offsets = self.payload.get("target_yaw_offsets_deg")
        if (
            not isinstance(offsets, list)
            or not offsets
            or len(offsets) > 8
            or any(abs(float(offset)) > 180.0 for offset in offsets)
            or abs(float(offsets[-1])) > 1e-9
        ):
            raise ValueError(
                "scan offsets must be a bounded list ending at zero"
            )
        if float(self.payload.get("angular_velocity_deg_s", 0.0)) <= 0.0:
            raise ValueError("scan angular velocity must be positive")
        if int(self.payload.get("recovery_confirm_assessments", 0)) <= 0:
            raise ValueError("scan recovery confirmation must be positive")
        if int(self.payload.get("max_scan_cycles", 0)) != 1:
            raise ValueError("scan V1 permits exactly one yaw-sweep cycle")

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
        self._latched = False
        self._events.clear()

    @staticmethod
    def _field(value: object, name: str) -> Any:
        if isinstance(value, Mapping):
            return value[name]
        return getattr(value, name)

    def observe_proposal(self, proposal: object) -> ActiveScanPlan | None:
        state_action = str(self._field(proposal, "state_action"))
        if state_action == "cancel_active_scan_on_trust_recovery":
            self._latched = False
            return None
        proposal_action = str(self._field(proposal, "proposal_action"))
        if (
            proposal_action not in {
                "request_active_scan",
                "request_active_scan_budget_exhausted",
                "request_active_scan_no_candidate",
            }
            or self._latched
        ):
            return None
        self._latched = True
        rate = float(self.payload["angular_velocity_deg_s"])
        offsets = [
            float(offset)
            for offset in self.payload["target_yaw_offsets_deg"]
        ]
        previous = 0.0
        rotations = []
        for index, target in enumerate(offsets):
            delta = target - previous
            rotations.append(ActiveScanRotation(
                index=index,
                target_offset_deg=target,
                delta_yaw_deg=delta,
                angular_velocity_deg_s=(
                    rate if delta >= 0.0 else -rate
                ),
                duration_s=abs(delta) / rate,
                capture_after_rotation=True,
            ))
            previous = target
        plan = ActiveScanPlan(
            sequence=int(self._field(proposal, "sequence")),
            attempt=self._field(proposal, "attempt"),
            step=self._field(proposal, "step"),
            current_anchor_index=int(self._field(
                proposal, "current_anchor_index"
            )),
            next_anchor_index=int(self._field(
                proposal, "route1_next_anchor_index"
            )),
            trigger_action=proposal_action,
            trigger_reason=str(self._field(proposal, "reason")),
            rotations=tuple(rotations),
            recovery_confirm_assessments=int(
                self.payload["recovery_confirm_assessments"]
            ),
            max_scan_cycles=1,
            translation_authorized=False,
            stop_authorized=False,
            motor_effect=False,
            failure_action=str(self.payload["failure_action"]),
        )
        self._events.append({
            "event": "v11_active_scan_shadow_plan",
            "episode_key": self._episode_key,
            **plan.as_dict(),
        })
        return plan
