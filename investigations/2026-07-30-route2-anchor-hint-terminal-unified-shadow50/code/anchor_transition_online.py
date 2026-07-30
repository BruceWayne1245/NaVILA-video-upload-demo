"""Online, causal wrapper around the frozen Anchor Transition V1 bundle."""

from __future__ import annotations

import hashlib
import math
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import joblib
import numpy as np

from .anchor_transition_promotion_guard import (
    AnchorTransitionPromotionGuard,
)


SCHEMA = "navila-anchor-transition-online-v1"
RAW_CANDIDATE_FIELDS = (
    "anchor_index",
    "anchor_distance_from_start_m",
    "route_remaining_to_start_m",
    "outcome",
    "confidence",
    "inlier_count",
    "overlap_ratio",
    "median_residual_m",
    "mean_residual_m",
    "estimated_anchor_dx_m",
    "estimated_anchor_dy_m",
    "estimated_anchor_dtheta_deg",
    "estimated_distance_to_anchor_m",
    "estimated_bearing_to_anchor_deg",
    "corridor_degeneracy_ratio",
    "icp_basin_count",
    "icp_near_tie_basin_count",
    "icp_ambiguity",
    "icp_best_to_second_score_ratio",
    "icp_best_to_second_translation_delta_m",
    "icp_best_to_second_rotation_delta_deg",
    "match_class",
)
ROUTE_MEMORY_FIELDS = (
    "source",
    "configured_source",
    "target_dx_m",
    "target_dy_m",
    "distance_to_start_m",
    "bearing_to_start_deg",
    "target_anchor_index",
    "anchor_dx_m",
    "anchor_dy_m",
    "distance_to_anchor_m",
    "bearing_to_anchor_deg",
    "anchor_route_remaining_m",
    "anchor_heading_reliable",
    "relocalization_confidence",
    "relocalization_backend",
    "filter_std_m",
    "estimate_kind",
    "estimate_source_anchor_index",
    "estimate_edge_hop_count",
    "estimate_source_confidence",
    "estimate_target_raw_confidence",
    "evidence_age_updates",
    "estimate_role",
)
SUPPORT_FIELDS = (
    "mode",
    "action",
    "current_anchor_index",
    "next_anchor_index",
    "reconstruct_next_from_current",
    "vlm_only",
    "probe_anchor_indices",
    "promotion_blocked_anchor_indices",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _calibrate(probabilities: np.ndarray, temperature: float) -> np.ndarray:
    clipped = np.clip(probabilities, 1e-9, 1.0)
    logits = np.log(clipped) / float(temperature)
    logits -= logits.max(axis=1, keepdims=True)
    exponent = np.exp(logits)
    return exponent / exponent.sum(axis=1, keepdims=True)


def _compact_candidate(
    record: dict[str, Any], v11_output: dict[str, Any] | None
) -> dict[str, Any]:
    value = {field: record.get(field) for field in RAW_CANDIDATE_FIELDS}
    value["yaw_curve"] = {
        field: (record.get("yaw_curve") or {}).get(field)
        for field in (
            "available",
            "yaw_score_entropy",
            "yaw_score_normalized_entropy",
            "yaw_peak_width_deg",
            "yaw_top1_next_distinct_gap_deg",
            "yaw_top1_next_distinct_score_ratio",
        )
    }
    value["localizability"] = {
        field: (record.get("localizability") or {}).get(field)
        for field in (
            "available",
            "condition_number",
            "min_normalized_eigenvalue",
            "weak_direction_count",
            "yaw_normalized_marginal_information",
        )
    }
    value["scan_context"] = {
        field: (record.get("scan_context_yaw_check") or {}).get(field)
        for field in (
            "available",
            "scan_context_similarity",
            "scan_context_region_ratio",
            "icp_scan_context_yaw_agreement_deg",
        )
    }
    value["v11"] = {
        field: (v11_output or {}).get(field)
        for field in (
            "anchor_role",
            "p_pose_bad",
            "p_distance_bad_0p5",
            "p_bearing_bad_30",
            "pose_trusted",
            "distance_trusted",
            "bearing_trusted",
            "jointly_trusted",
        )
    }
    return value


def build_runtime_anchor_row(
    *,
    episode_key: str,
    physical_episode_id: int,
    scene_id: str,
    attempt: int,
    step: int,
    movement: dict[str, Any],
    route_memory: dict[str, Any] | None,
    support: dict[str, Any] | None,
    raw_candidates: list[dict[str, Any]],
    v11_outputs: list[dict[str, Any]],
) -> dict[str, Any]:
    """Construct the same runtime-only input shape used during training."""
    outputs = {
        int(output["anchor_index"]): output
        for output in v11_outputs
        if output.get("anchor_index") is not None
    }
    candidates = [
        _compact_candidate(
            record,
            outputs.get(int(record["anchor_index"]))
            if record.get("anchor_index") is not None
            else None,
        )
        for record in raw_candidates
    ]
    return {
        "schema": "navila-anchor-terminal-training-v1",
        "task": "anchor_state",
        "episode": {
            "episode_key": str(episode_key),
            "physical_episode_id": int(physical_episode_id),
            "scene_id": str(scene_id),
            "split": "active_canary",
        },
        "time": {
            "attempt": int(attempt),
            "step": int(step),
            "attempt_step_alignment": "online_exact_step",
        },
        "inputs": {
            "movement": dict(movement),
            "route_memory": {
                field: (route_memory or {}).get(field)
                for field in ROUTE_MEMORY_FIELDS
            },
            "support": {
                field: (support or {}).get(field)
                for field in SUPPORT_FIELDS
            },
            "candidates": candidates,
        },
    }


@dataclass(frozen=True)
class OnlineAnchorPrediction:
    attempt: int
    action: str
    confidence: float
    probabilities: dict[str, float]
    model_sha256: str
    feature_timing: str = "previous_complete_attempt"

    def as_dict(self) -> dict[str, Any]:
        return {"schema": SCHEMA, **asdict(self)}


class OnlineAnchorTransitionV1:
    """Scores only complete attempt rows, then arms a t+1 bounded guard."""

    def __init__(
        self,
        *,
        model_path: str | Path,
        feature_module_root: str | Path,
        expected_model_sha256: str,
        confidence_threshold: float = 0.90,
        max_deferrals_per_candidate: int = 2,
    ) -> None:
        self.model_path = Path(model_path).resolve()
        actual_hash = _sha256(self.model_path)
        if actual_hash != str(expected_model_sha256):
            raise RuntimeError(
                "Anchor Transition V1 hash mismatch: "
                f"expected={expected_model_sha256} actual={actual_hash}"
            )
        feature_root = str(Path(feature_module_root).resolve())
        if feature_root not in sys.path:
            sys.path.insert(0, feature_root)
        from model_features import (  # pylint: disable=import-outside-toplevel
            CausalFeatureState,
            assert_runtime_only,
        )

        self._assert_runtime_only = assert_runtime_only
        self._state_type = CausalFeatureState
        self._bundle = joblib.load(self.model_path)
        if self._bundle.get("task") != "anchor_transition":
            raise RuntimeError("unexpected model task")
        self.classes = tuple(str(x) for x in self._bundle["classes"])
        self.model_sha256 = actual_hash
        self.guard = AnchorTransitionPromotionGuard(
            confidence_threshold=confidence_threshold,
            max_deferrals_per_candidate=max_deferrals_per_candidate,
            expected_model_sha256=actual_hash,
        )
        self.events: list[dict[str, Any]] = []
        self._state = self._state_type()
        self._last_attempt: int | None = None

    def start_episode(self) -> None:
        self._state = self._state_type()
        self._last_attempt = None
        self.events.clear()
        self.guard.start_episode()

    def observe_complete_attempt(
        self, row: dict[str, Any]
    ) -> OnlineAnchorPrediction:
        if row.get("task") != "anchor_state":
            raise ValueError("expected task=anchor_state")
        forbidden = {"labels", "oracle_alignment", "historical_policy"}
        leaked = forbidden.intersection(row)
        if leaked:
            raise ValueError(
                f"non-runtime fields supplied to online model: {sorted(leaked)}"
            )
        attempt = int(row["time"]["attempt"])
        if self._last_attempt is not None and attempt <= self._last_attempt:
            raise ValueError("complete attempts must be strictly increasing")
        feature = self._state.transform(row)
        self._assert_runtime_only(feature)
        matrix = self._bundle["vectorizer"].transform([feature])
        order = [
            list(self._bundle["model"].classes_).index(label)
            for label in self.classes
        ]
        raw = self._bundle["model"].predict_proba(matrix)[:, order]
        probability = _calibrate(
            raw, float(self._bundle["temperature"])
        )[0]
        if not np.isfinite(probability).all():
            raise RuntimeError("non-finite Anchor V1 probability")
        best = int(np.argmax(probability))
        prediction = OnlineAnchorPrediction(
            attempt=attempt,
            action=self.classes[best],
            confidence=float(probability[best]),
            probabilities={
                label: float(value)
                for label, value in zip(self.classes, probability)
            },
            model_sha256=self.model_sha256,
        )
        if not math.isclose(
            sum(prediction.probabilities.values()), 1.0, abs_tol=1e-8
        ):
            raise RuntimeError("Anchor V1 probabilities do not sum to one")
        self.guard.observe(
            attempt=attempt,
            action=prediction.action,
            confidence=prediction.confidence,
            model_sha256=self.model_sha256,
        )
        self._last_attempt = attempt
        self.events.append(
            {
                "event": "anchor_transition_online_prediction",
                **prediction.as_dict(),
            }
        )
        return prediction
