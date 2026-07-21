"""Isolated shadow-only bridge between candidate NaVILA and reliability v1."""

from __future__ import annotations

import time
from typing import Any

from reliability_portable_runtime import PortableReliabilityBundle, PortableTemporalController


class ReliabilityShadowRuntime:
    """Score candidates and emit recommendations without changing behavior."""

    def __init__(
        self,
        artifact_path: str,
        *,
        mode: str = "shadow",
        pose_high_risk_threshold: float = 0.7,
        high_risk_consecutive: int = 10,
        release_after_attempts: int = 200,
    ) -> None:
        if mode != "shadow":
            raise RuntimeError(
                "Reliability V1 enforcement is intentionally locked: the 2026-07-21 "
                "offline replay recovered 0/8 missed-stop cases. Use mode=shadow."
            )
        self.bundle = PortableReliabilityBundle.load(artifact_path)
        self.controller = PortableTemporalController(
            pose_high_risk_threshold=float(pose_high_risk_threshold),
            high_risk_consecutive=int(high_risk_consecutive),
            release_after_attempts=int(release_after_attempts),
        )

    @property
    def model_version(self) -> str:
        return self.bundle.model_version

    def score_candidates(self, candidates: Any, diagnostics: dict[str, Any]) -> Any:
        started_at = time.perf_counter()
        if candidates is None:
            return None
        sequence = list(candidates) if isinstance(candidates, (list, tuple)) else [candidates]
        indices = sorted({int(candidate.anchor_index) for candidate in sequence}, reverse=True)
        roles = {
            anchor_index: "current" if position == 0 else "next" if position == 1 else "other"
            for position, anchor_index in enumerate(indices)
        }
        reliability_records = diagnostics.setdefault("reliability_records", [])
        for candidate in sequence:
            role = roles.get(int(candidate.anchor_index), "unknown")
            result = self.bundle.predict_reading(candidate)
            decision = self.controller.observe(int(candidate.anchor_index), role, result)
            candidate.reliability_bearing_bad_probability = result.p_bearing_bad_30
            candidate.reliability_distance_bad_probability = result.p_distance_bad_0p5
            candidate.reliability_pose_bad_probability = result.p_pose_bad
            candidate.reliability_bearing_trusted = result.bearing_trusted
            candidate.reliability_distance_trusted = result.distance_trusted
            candidate.reliability_pose_trusted = result.pose_trusted
            candidate.reliability_status = result.status
            candidate.reliability_model_version = result.model_version
            candidate.reliability_policy = decision
            reliability_records.append({
                "attempt": diagnostics.get("attempts"),
                "anchor_index": int(candidate.anchor_index),
                "anchor_role": role,
                **decision,
            })
        elapsed_ms = (time.perf_counter() - started_at) * 1000.0
        runtime = diagnostics.setdefault(
            "reliability_runtime",
            {"calls": 0, "candidates": 0, "total_inference_ms": 0.0, "max_call_ms": 0.0},
        )
        runtime["calls"] += 1
        runtime["candidates"] += len(sequence)
        runtime["total_inference_ms"] += elapsed_ms
        runtime["max_call_ms"] = max(float(runtime["max_call_ms"]), elapsed_ms)
        runtime["mean_call_ms"] = runtime["total_inference_ms"] / runtime["calls"]
        runtime["mean_candidate_ms"] = runtime["total_inference_ms"] / runtime["candidates"]
        if isinstance(candidates, tuple):
            return tuple(sequence)
        if isinstance(candidates, list):
            return sequence
        return sequence[0]
