"""Causal V1.1 feature/state bridge for online shadow scoring."""

from __future__ import annotations

import json
import hashlib
import math
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from .schema import features_from_record
from .v11_dataset import (
    PAIR_SIGNALS,
    TEMPORAL_SIGNALS,
    WINDOWS,
    _rolling_slope,
    _wrap_degrees,
    add_pair_features,
    base_features,
)


@dataclass(frozen=True)
class PreparedV11Candidate:
    episode_key: str
    attempt: int
    anchor_index: int
    anchor_role: str
    features: dict[str, float]


class CausalV11FeatureBuilder:
    """Build pair and history features without crossing episode/anchor state."""

    def __init__(self, feature_names: list[str]):
        self.feature_names = list(feature_names)
        self.active_episode_key: str | None = None
        self._streams: dict[tuple[str, int], dict[str, Any]] = {}

    def start_episode(self, episode_key: str) -> None:
        self.active_episode_key = str(episode_key)
        self._streams.clear()

    def reset(self) -> None:
        self.active_episode_key = None
        self._streams.clear()

    def _temporal(self, row: dict[str, Any]) -> None:
        stream_key = (str(row["episode_key"]), int(row["anchor_index"]))
        stream = self._streams.setdefault(stream_key, {
            "previous_role": None,
            "role_age": 0,
            "previous_attempt": None,
            "histories": defaultdict(list),
        })
        features = row["features"]
        role = str(row["anchor_role"])
        previous_role = stream["previous_role"]
        role_changed = previous_role is not None and role != previous_role
        stream["role_age"] = (
            1 if role_changed or previous_role is None else int(stream["role_age"]) + 1
        )
        histories = stream["histories"]
        features["temporal_history_count_including_current"] = float(
            len(histories[TEMPORAL_SIGNALS[0]]) + 1
        )
        previous_attempt = stream["previous_attempt"]
        features["temporal_attempt_gap"] = (
            float(int(row["attempt"]) - int(previous_attempt))
            if previous_attempt is not None else float("nan")
        )
        features["temporal_role_changed"] = float(role_changed)
        features["temporal_role_age"] = float(stream["role_age"])
        for signal in TEMPORAL_SIGNALS:
            current = features.get(signal, float("nan"))
            history = histories[signal]
            features[f"temporal_{signal}_delta_1"] = (
                current - history[-1]
                if history
                and math.isfinite(current)
                and math.isfinite(history[-1])
                else float("nan")
            )
            history.append(current)
            for window in WINDOWS:
                values = np.asarray(history[-window:], dtype=float)
                finite = values[np.isfinite(values)]
                prefix = f"temporal_{signal}_w{window}"
                features[f"{prefix}_mean"] = (
                    float(np.mean(finite)) if finite.size else float("nan")
                )
                features[f"{prefix}_std"] = (
                    float(np.std(finite)) if finite.size else float("nan")
                )
                features[f"{prefix}_slope"] = _rolling_slope(values)
        stream["previous_role"] = role
        stream["previous_attempt"] = int(row["attempt"])

    def build_attempt(
        self,
        episode_key: str,
        attempt: int,
        records: list[Mapping[str, Any]],
    ) -> list[PreparedV11Candidate]:
        if self.active_episode_key != str(episode_key):
            self.start_episode(str(episode_key))
        indices = sorted(
            {int(record["anchor_index"]) for record in records}, reverse=True
        )
        roles = {
            anchor_index: (
                "current" if position == 0 else "next" if position == 1 else "other"
            )
            for position, anchor_index in enumerate(indices)
        }
        rows = []
        for record in records:
            anchor_index = int(record["anchor_index"])
            role = roles.get(anchor_index, "unknown")
            v1 = features_from_record(record)
            v1["anchor_role"] = role
            rows.append({
                "episode_key": str(episode_key),
                "attempt": int(attempt),
                "anchor_index": anchor_index,
                "anchor_role": role,
                "features": base_features(record, v1),
            })
        add_pair_features(rows)
        output = []
        for row in rows:
            self._temporal(row)
            output.append(PreparedV11Candidate(
                episode_key=str(episode_key),
                attempt=int(attempt),
                anchor_index=int(row["anchor_index"]),
                anchor_role=str(row["anchor_role"]),
                features={
                    name: float(row["features"].get(name, float("nan")))
                    for name in self.feature_names
                },
            ))
        return output


class V11OnlineShadowRuntime:
    """Combine causal feature construction and a locked portable scorer."""

    def __init__(self, portable_bundle: Any, feature_builder: CausalV11FeatureBuilder):
        self.bundle = portable_bundle
        self.feature_builder = feature_builder
        self.runtime = {
            "calls": 0,
            "candidates": 0,
            "total_inference_ms": 0.0,
            "max_call_ms": 0.0,
            "exceptions": 0,
            "nonfinite_outputs": 0,
            "enforcement_enabled": False,
        }

    def start_episode(self, episode_key: str) -> None:
        self.feature_builder.start_episode(episode_key)

    def score_attempt(
        self,
        episode_key: str,
        attempt: int,
        records: list[Mapping[str, Any]],
        *,
        include_features: bool = False,
    ) -> list[dict[str, Any]]:
        started = time.perf_counter()
        try:
            prepared = self.feature_builder.build_attempt(
                episode_key, attempt, records
            )
            outputs = []
            for candidate in prepared:
                result = self.bundle.predict_features(candidate.features)
                values = result.as_dict()
                probabilities = (
                    values["p_bearing_bad_30"],
                    values["p_distance_bad_0p5"],
                    values["p_pose_bad"],
                )
                if not all(math.isfinite(float(value)) for value in probabilities):
                    self.runtime["nonfinite_outputs"] += 1
                output = {
                    "episode_key": candidate.episode_key,
                    "attempt": candidate.attempt,
                    "anchor_index": candidate.anchor_index,
                    "anchor_role": candidate.anchor_role,
                    **values,
                    "enforced": False,
                }
                if include_features:
                    output["features"] = candidate.features
                outputs.append(output)
        except Exception:
            self.runtime["exceptions"] += 1
            raise
        elapsed = (time.perf_counter() - started) * 1000.0
        self.runtime["calls"] += 1
        self.runtime["candidates"] += len(outputs)
        self.runtime["total_inference_ms"] += elapsed
        self.runtime["max_call_ms"] = max(self.runtime["max_call_ms"], elapsed)
        self.runtime["mean_call_ms"] = (
            self.runtime["total_inference_ms"] / self.runtime["calls"]
        )
        self.runtime["mean_candidate_ms"] = (
            self.runtime["total_inference_ms"] / self.runtime["candidates"]
        )
        return outputs


def _json_safe(value: Any) -> Any:
    """Convert non-finite feature values to JSON null without changing inference."""
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (float, np.floating)):
        numeric = float(value)
        return numeric if math.isfinite(numeric) else None
    if isinstance(value, np.integer):
        return int(value)
    return value


DECISION_SHADOW_POLICY_SCHEMA = "navila-v11-decision-shadow-policy-v1"


class V11DecisionShadowPolicy:
    """Compute a role-safe counterfactual consumer decision without enforcement."""

    def __init__(
        self,
        payload: Mapping[str, Any],
        *,
        policy_sha256: str | None = None,
    ):
        self.payload = dict(payload)
        if self.payload.get("schema") != DECISION_SHADOW_POLICY_SCHEMA:
            raise ValueError(
                f"unsupported decision-shadow schema: {self.payload.get('schema')}"
            )
        if self.payload.get("mode") != "shadow":
            raise ValueError("decision policy must be locked to shadow mode")
        if self.payload.get("enforcement_approved") is not False:
            raise ValueError("decision policy must explicitly forbid enforcement")
        if self.payload.get("identity_override_authorized") is not False:
            raise ValueError("decision policy must explicitly forbid identity override")
        if self.payload.get("candidate_gate") != "jointly_trusted":
            raise ValueError("only the frozen jointly_trusted gate is supported")
        if self.payload.get("alternate_rank_field") != "p_pose_bad":
            raise ValueError("only the frozen p_pose_bad alternate ranking is supported")
        expected_actions = {
            "missing_current_action":
                "would_defer_entire_relocalization_update_current_missing",
            "untrusted_current_action":
                "would_defer_entire_relocalization_update_current_untrusted",
            "trusted_current_untrusted_next_action":
                "would_forward_trusted_current_only",
            "trusted_pair_action":
                "would_forward_trusted_current_and_next",
        }
        for key, expected in expected_actions.items():
            if self.payload.get(key) != expected:
                raise ValueError(f"unsupported frozen action for {key}")
        self.policy_sha256 = policy_sha256 or hashlib.sha256(
            json.dumps(
                self.payload,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()

    @classmethod
    def load(cls, path: str | Path) -> "V11DecisionShadowPolicy":
        source = Path(path)
        raw = source.read_bytes()
        return cls(
            json.loads(raw.decode("utf-8")),
            policy_sha256=hashlib.sha256(raw).hexdigest(),
        )

    def metadata(self) -> dict[str, Any]:
        return {
            "schema": self.payload["schema"],
            "name": str(self.payload["name"]),
            "policy_sha256": self.policy_sha256,
            "mode": "shadow",
            "enforcement_approved": False,
            "identity_override_authorized": False,
            "candidate_gate": "jointly_trusted",
            "alternate_rank_field": "p_pose_bad",
            "current_role_required": True,
            "untrusted_candidates_forwarded": False,
        }

    @staticmethod
    def _candidate_assessment(output: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "anchor_index": int(output["anchor_index"]),
            "anchor_role": str(output["anchor_role"]),
            "p_bearing_bad_30": float(output["p_bearing_bad_30"]),
            "p_distance_bad_0p5": float(output["p_distance_bad_0p5"]),
            "p_pose_bad": float(output["p_pose_bad"]),
            "bearing_trusted": bool(output["bearing_trusted"]),
            "distance_trusted": bool(output["distance_trusted"]),
            "pose_trusted": bool(output["pose_trusted"]),
            "jointly_trusted": bool(output["jointly_trusted"]),
        }

    def evaluate(
        self,
        outputs: list[Mapping[str, Any]],
        *,
        accepted_event: Mapping[str, Any] | None,
        target_anchor_index: int | None,
    ) -> dict[str, Any]:
        """Return the predeclared counterfactual; never return a controller object."""
        assessments = [self._candidate_assessment(output) for output in outputs]
        by_anchor: dict[int, dict[str, Any]] = {}
        for assessment in assessments:
            anchor_index = int(assessment["anchor_index"])
            if anchor_index in by_anchor:
                raise ValueError(f"duplicate model output for anchor {anchor_index}")
            by_anchor[anchor_index] = assessment

        controller_accepted = bool(
            isinstance(accepted_event, Mapping)
            and accepted_event.get("accepted") is True
            and accepted_event.get("anchor_index") is not None
        )
        selected_anchor_index = (
            int(accepted_event["anchor_index"]) if controller_accepted else None
        )
        controller_backend = (
            str(accepted_event.get("backend"))
            if controller_accepted and accepted_event.get("backend") is not None
            else None
        )
        selected = (
            by_anchor.get(selected_anchor_index)
            if selected_anchor_index is not None
            else None
        )
        ranked_jointly_trusted = sorted(
            (
                assessment
                for assessment in assessments
                if assessment["jointly_trusted"]
            ),
            key=lambda assessment: (
                assessment["p_pose_bad"],
                assessment["p_bearing_bad_30"],
                assessment["p_distance_bad_0p5"],
                assessment["anchor_index"],
            ),
        )
        advisory_alternate = next(
            (
                assessment
                for assessment in ranked_jointly_trusted
                if assessment["anchor_index"] != selected_anchor_index
            ),
            None,
        )

        current_candidates = [
            assessment
            for assessment in assessments
            if assessment["anchor_role"] == "current"
        ]
        next_candidates = [
            assessment
            for assessment in assessments
            if assessment["anchor_role"] == "next"
        ]
        current = current_candidates[0] if len(current_candidates) == 1 else None
        next_candidate = next_candidates[0] if len(next_candidates) == 1 else None
        if current is None:
            precontroller_action = (
                "would_defer_entire_relocalization_update_current_missing"
            )
            forwarded_anchor_indices: list[int] = []
            precontroller_reasons = ["exactly_one_current_candidate_required"]
        elif not current["jointly_trusted"]:
            precontroller_action = (
                "would_defer_entire_relocalization_update_current_untrusted"
            )
            forwarded_anchor_indices = []
            precontroller_reasons = ["current_candidate_not_jointly_trusted"]
        elif next_candidate is not None and next_candidate["jointly_trusted"]:
            precontroller_action = "would_forward_trusted_current_and_next"
            forwarded_anchor_indices = [
                int(current["anchor_index"]),
                int(next_candidate["anchor_index"]),
            ]
            precontroller_reasons = ["current_and_next_jointly_trusted"]
        else:
            precontroller_action = "would_forward_trusted_current_only"
            forwarded_anchor_indices = [int(current["anchor_index"])]
            precontroller_reasons = ["current_jointly_trusted"]
            precontroller_reasons.append(
                "next_candidate_untrusted"
                if next_candidate is not None else "next_candidate_unavailable"
            )

        if not controller_accepted:
            selected_action = "would_preserve_controller_rejection"
            selected_reason_codes = ["controller_did_not_accept_candidate"]
        elif selected is None:
            selected_action = "selected_candidate_unscored"
            selected_reason_codes = ["selected_candidate_missing_model_output"]
        elif selected["jointly_trusted"]:
            selected_action = "selected_candidate_jointly_trusted"
            selected_reason_codes = ["selected_candidate_jointly_trusted"]
        else:
            selected_action = "selected_candidate_untrusted"
            selected_reason_codes = ["selected_candidate_not_jointly_trusted"]
            for head in ("bearing", "distance", "pose"):
                if not selected[f"{head}_trusted"]:
                    selected_reason_codes.append(f"{head}_untrusted")
            if advisory_alternate is not None:
                selected_reason_codes.append("jointly_trusted_alternate_observed")

        selected_pose_risk = (
            float(selected["p_pose_bad"]) if selected is not None else None
        )
        alternate_pose_risk = (
            float(advisory_alternate["p_pose_bad"])
            if advisory_alternate is not None else None
        )
        lower_pose_risk_alternate = bool(
            selected_pose_risk is not None
            and alternate_pose_risk is not None
            and alternate_pose_risk < selected_pose_risk
        )
        all_anchor_indices = sorted(by_anchor)
        forwarded_anchor_indices = sorted(forwarded_anchor_indices)
        return {
            "policy": self.metadata(),
            "baseline": {
                "controller_accepted": controller_accepted,
                "selected_anchor_index": selected_anchor_index,
                "target_anchor_index": (
                    int(target_anchor_index)
                    if target_anchor_index is not None else None
                ),
                "controller_backend": controller_backend,
                "controller_measurement_postprocessed": bool(
                    controller_backend is not None
                    and controller_backend != "sequential_pair"
                ),
            },
            "candidate_assessments": assessments,
            "counterfactual": {
                "action": precontroller_action,
                "reason_codes": precontroller_reasons,
                "integration_point":
                    "filter_raw_candidates_before_route_memory_agent",
                "input_anchor_indices": all_anchor_indices,
                "forwarded_anchor_indices": forwarded_anchor_indices,
                "would_change_candidate_set": (
                    forwarded_anchor_indices != all_anchor_indices
                ),
                "would_defer_entire_relocalization_update": (
                    not forwarded_anchor_indices
                ),
                "current_anchor_index": (
                    int(current["anchor_index"]) if current is not None else None
                ),
                "current_jointly_trusted": (
                    bool(current["jointly_trusted"])
                    if current is not None else None
                ),
                "next_anchor_index": (
                    int(next_candidate["anchor_index"])
                    if next_candidate is not None else None
                ),
                "next_jointly_trusted": (
                    bool(next_candidate["jointly_trusted"])
                    if next_candidate is not None else None
                ),
                "selected_assessment_action": selected_action,
                "selected_assessment_reason_codes": selected_reason_codes,
                "selected_candidate_scored": selected is not None,
                "selected_jointly_trusted": (
                    bool(selected["jointly_trusted"])
                    if selected is not None else None
                ),
                "would_admit_selected_raw_bearing_evidence": (
                    bool(selected["bearing_trusted"])
                    if selected is not None else False
                ),
                "would_admit_selected_raw_distance_evidence": (
                    bool(selected["distance_trusted"])
                    if selected is not None else False
                ),
                "would_admit_selected_raw_pose_evidence": (
                    bool(selected["pose_trusted"])
                    if selected is not None else False
                ),
                "advisory_alternate_anchor_index": (
                    int(advisory_alternate["anchor_index"])
                    if advisory_alternate is not None else None
                ),
                "advisory_alternate_role": (
                    str(advisory_alternate["anchor_role"])
                    if advisory_alternate is not None else None
                ),
                "alternate_is_advisory_only": True,
                "identity_override_authorized": False,
            },
            "disagreement": {
                "selected_untrusted": bool(
                    selected is not None and not selected["jointly_trusted"]
                ),
                "jointly_trusted_alternate_available": (
                    advisory_alternate is not None
                ),
                "lower_pose_risk_alternate_available": lower_pose_risk_alternate,
                "selected_anchor_differs_from_target": bool(
                    selected_anchor_index is not None
                    and target_anchor_index is not None
                    and selected_anchor_index != int(target_anchor_index)
                ),
            },
            "mode": "shadow",
            "observation_only": True,
            "activation_approved": False,
            "enforcement_enabled": False,
            "controller_effect": False,
        }

    @staticmethod
    def attach_posthoc_ground_truth(
        decision: dict[str, Any],
        raw_records: list[Mapping[str, Any]],
        ground_truth_by_anchor: Mapping[int, Mapping[str, Any]] | None,
    ) -> None:
        """Attach labels after policy evaluation; truth never enters the decision."""
        truth_by_anchor = {
            int(anchor): values
            for anchor, values in (ground_truth_by_anchor or {}).items()
        }
        rows = []
        for record in raw_records:
            anchor_index = int(record["anchor_index"])
            truth = truth_by_anchor.get(anchor_index)
            estimated_bearing = record.get("estimated_bearing_to_anchor_deg")
            estimated_distance = record.get("estimated_distance_to_anchor_m")
            if (
                truth is None
                or estimated_bearing is None
                or estimated_distance is None
                or truth.get("true_bearing_to_anchor_deg") is None
                or truth.get("true_distance_to_anchor_m") is None
            ):
                rows.append({
                    "anchor_index": anchor_index,
                    "available": False,
                })
                continue
            bearing_error = abs(_wrap_degrees(
                float(estimated_bearing)
                - float(truth["true_bearing_to_anchor_deg"])
            ))
            distance_error = abs(
                float(estimated_distance)
                - float(truth["true_distance_to_anchor_m"])
            )
            bearing_bad = bearing_error > 30.0
            distance_bad = distance_error > 0.5
            rows.append({
                "anchor_index": anchor_index,
                "available": True,
                "true_bearing_to_anchor_deg": float(
                    truth["true_bearing_to_anchor_deg"]
                ),
                "true_distance_to_anchor_m": float(
                    truth["true_distance_to_anchor_m"]
                ),
                "estimated_bearing_to_anchor_deg": float(estimated_bearing),
                "estimated_distance_to_anchor_m": float(estimated_distance),
                "bearing_error_deg": bearing_error,
                "distance_error_m": distance_error,
                "label_bearing_bad": int(bearing_bad),
                "label_distance_bad": int(distance_bad),
                "label_pose_bad": int(bearing_bad or distance_bad),
            })
        decision["posthoc_ground_truth"] = {
            "used_for_features": False,
            "used_for_scoring": False,
            "used_for_decision": False,
            "bearing_bad_threshold_deg": 30.0,
            "distance_bad_threshold_m": 0.5,
            "candidate_labels": rows,
            "available_rows": sum(bool(row["available"]) for row in rows),
            "missing_rows": sum(not bool(row["available"]) for row in rows),
        }


class V11ShadowJsonlSession:
    """Fail-open online shadow session with durable per-attempt JSONL logging."""

    def __init__(
        self,
        portable_bundle: Any,
        *,
        episode_key: str,
        log_path: str | Path,
        portable_artifact_sha256: str | None = None,
        decision_policy: V11DecisionShadowPolicy | None = None,
        physical_episode_id: int | None = None,
        scene_id: str | None = None,
    ):
        self.episode_key = str(episode_key)
        self.log_path = Path(log_path)
        self.physical_episode_id = (
            int(physical_episode_id)
            if physical_episode_id is not None else None
        )
        self.scene_id = str(scene_id) if scene_id is not None else None
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.runtime = V11OnlineShadowRuntime(
            portable_bundle,
            CausalV11FeatureBuilder(portable_bundle.feature_names),
        )
        self.runtime.start_episode(self.episode_key)
        self._handle = self.log_path.open("a", encoding="utf-8", buffering=1)
        self._latencies_ms: list[float] = []
        self._shadow_exceptions = 0
        self._controller_snapshots = 0
        self._decision_policy = decision_policy
        self._outputs_by_attempt: dict[int, list[dict[str, Any]]] = {}
        self._raw_records_by_attempt: dict[int, list[dict[str, Any]]] = {}
        self._decision_actions: Counter[str] = Counter()
        self._decision_exceptions = 0
        self._closed = False
        self._write({
            "event": "v11_shadow_session_start",
            "episode_key": self.episode_key,
            "physical_episode_id": self.physical_episode_id,
            "scene_id": self.scene_id,
            "mode": "shadow",
            "enforcement_enabled": False,
            "controller_effect": False,
            "model_format": portable_bundle.payload.get("format"),
            "source_artifact_sha256": portable_bundle.payload.get(
                "source_artifact_sha256"
            ),
            "portable_artifact_sha256": portable_artifact_sha256,
            "feature_count": len(portable_bundle.feature_names),
            "feature_names": list(portable_bundle.feature_names),
            "decision_shadow_enabled": self._decision_policy is not None,
            "decision_policy": (
                self._decision_policy.metadata()
                if self._decision_policy is not None else None
            ),
        })

    def _write(self, record: Mapping[str, Any]) -> None:
        self._handle.write(
            json.dumps(_json_safe(record), sort_keys=True, separators=(",", ":"))
            + "\n"
        )
        self._handle.flush()

    def score_records(
        self,
        records: list[Mapping[str, Any]],
        *,
        step: int,
    ) -> list[dict[str, Any]]:
        """Score one live attempt; any shadow failure is logged and swallowed."""
        started = time.perf_counter()
        attempt = None
        try:
            attempts = {int(record["attempt"]) for record in records}
            if len(attempts) != 1:
                raise ValueError(f"expected one attempt, got {sorted(attempts)}")
            attempt = attempts.pop()
            outputs = self.runtime.score_attempt(
                self.episode_key,
                attempt,
                records,
                include_features=True,
            )
            latency_ms = (time.perf_counter() - started) * 1000.0
            self._latencies_ms.append(latency_ms)
            if self._decision_policy is not None:
                self._outputs_by_attempt[int(attempt)] = outputs
                self._raw_records_by_attempt[int(attempt)] = [
                    {
                        "anchor_index": int(record["anchor_index"]),
                        "estimated_bearing_to_anchor_deg": record.get(
                            "estimated_bearing_to_anchor_deg"
                        ),
                        "estimated_distance_to_anchor_m": record.get(
                            "estimated_distance_to_anchor_m"
                        ),
                    }
                    for record in records
                ]
            self._write({
                "event": "v11_shadow_score",
                "episode_key": self.episode_key,
                "physical_episode_id": self.physical_episode_id,
                "scene_id": self.scene_id,
                "step": int(step),
                "attempt": int(attempt),
                "input_record_count": len(records),
                "latency_ms": latency_ms,
                "outputs": outputs,
                "enforcement_enabled": False,
                "controller_effect": False,
            })
            return outputs
        except Exception as exc:
            self._shadow_exceptions += 1
            self._write({
                "event": "v11_shadow_exception",
                "episode_key": self.episode_key,
                "step": int(step),
                "attempt": attempt,
                "error_type": type(exc).__name__,
                "error": str(exc),
                "enforcement_enabled": False,
                "controller_effect": False,
            })
            return []

    def record_controller_snapshot(
        self,
        *,
        step: int,
        attempt: int | None,
        accepted_event: Mapping[str, Any] | None,
        target_anchor_index: int | None,
        ground_truth_by_anchor: Mapping[int, Mapping[str, Any]] | None = None,
    ) -> None:
        """Log the existing controller outcome without feeding it back to V1.1."""
        self._controller_snapshots += 1
        self._write({
            "event": "v11_shadow_controller_snapshot",
            "episode_key": self.episode_key,
            "physical_episode_id": self.physical_episode_id,
            "scene_id": self.scene_id,
            "step": int(step),
            "attempt": int(attempt) if attempt is not None else None,
            "existing_controller_event": accepted_event,
            "existing_target_anchor_index": (
                int(target_anchor_index)
                if target_anchor_index is not None else None
            ),
            "enforcement_enabled": False,
            "controller_effect": False,
        })
        if self._decision_policy is None:
            return
        try:
            outputs = (
                self._outputs_by_attempt.pop(int(attempt), [])
                if attempt is not None else []
            )
            decision = self._decision_policy.evaluate(
                outputs,
                accepted_event=accepted_event,
                target_anchor_index=target_anchor_index,
            )
            raw_records = (
                self._raw_records_by_attempt.pop(int(attempt), [])
                if attempt is not None else []
            )
            self._decision_policy.attach_posthoc_ground_truth(
                decision,
                raw_records,
                ground_truth_by_anchor,
            )
            action = str(decision["counterfactual"]["action"])
            self._decision_actions[action] += 1
            self._write({
                "event": "v11_shadow_decision",
                "episode_key": self.episode_key,
                "physical_episode_id": self.physical_episode_id,
                "scene_id": self.scene_id,
                "step": int(step),
                "attempt": int(attempt) if attempt is not None else None,
                **decision,
            })
        except Exception as exc:
            self._decision_exceptions += 1
            self._write({
                "event": "v11_shadow_decision_exception",
                "episode_key": self.episode_key,
                "physical_episode_id": self.physical_episode_id,
                "scene_id": self.scene_id,
                "step": int(step),
                "attempt": int(attempt) if attempt is not None else None,
                "error_type": type(exc).__name__,
                "error": str(exc),
                "mode": "shadow",
                "activation_approved": False,
                "enforcement_enabled": False,
                "controller_effect": False,
            })

    def summary(self) -> dict[str, Any]:
        latencies = np.asarray(self._latencies_ms, dtype=float)
        return {
            "enabled": True,
            "mode": "shadow",
            "enforcement_enabled": False,
            "controller_effect": False,
            "episode_key": self.episode_key,
            "physical_episode_id": self.physical_episode_id,
            "scene_id": self.scene_id,
            "log_path": str(self.log_path),
            "calls": int(self.runtime.runtime["calls"]),
            "candidates": int(self.runtime.runtime["candidates"]),
            "runtime_exceptions": int(self.runtime.runtime["exceptions"]),
            "shadow_exceptions": int(self._shadow_exceptions),
            "nonfinite_outputs": int(self.runtime.runtime["nonfinite_outputs"]),
            "controller_snapshots": int(self._controller_snapshots),
            "decision_shadow_enabled": self._decision_policy is not None,
            "decision_policy": (
                self._decision_policy.metadata()
                if self._decision_policy is not None else None
            ),
            "decision_count": int(sum(self._decision_actions.values())),
            "decision_actions": dict(sorted(self._decision_actions.items())),
            "decision_exceptions": int(self._decision_exceptions),
            "mean_call_ms": (
                float(np.mean(latencies)) if latencies.size else None
            ),
            "p95_call_ms": (
                float(np.quantile(latencies, 0.95)) if latencies.size else None
            ),
            "p99_call_ms": (
                float(np.quantile(latencies, 0.99)) if latencies.size else None
            ),
            "maximum_call_ms": (
                float(np.max(latencies)) if latencies.size else None
            ),
        }

    def close(self) -> None:
        if self._closed:
            return
        self._write({
            "event": "v11_shadow_session_end",
            **self.summary(),
        })
        self._handle.close()
        self._closed = True
