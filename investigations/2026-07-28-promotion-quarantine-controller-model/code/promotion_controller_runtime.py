"""Promotion/quarantine/wait controller runtime: causal online feature builder,
hash-versioned model bundle, tunable decision policy, and a fail-open JSONL
shadow session.

Design mirrors reliability/v11_runtime.py's CausalV11FeatureBuilder /
PortableV11Bundle / V11ShadowJsonlSession pattern (see
investigations/2026-07-28-promotion-quarantine-controller-model/INTEGRATION_PLAN.md
for why: a learned decision function needs artifact versioning, a
separately-tunable decision-policy layer, and a zero-effect shadow phase
before any live enforcement -- a bare on/off flag gets none of these).

Scope: this module owns exactly the promotion/quarantine/wait decision that
today lives in RouteMemoryAgent._select_sequential_pair_relocalization's
candidate_promote logic and _record_next_anchor_trend's quarantine check. It
does not touch stop_gate.py or hint_action_arbiter.py (mechanisms D/E/G from
2026-07-28-downgrade-batch-mechanism-failure-classification/FINDINGS.md live
there and are out of scope here).

Currently shadow-only: nothing in round_trip_eval.py acts on this module's
decisions yet (see that file's --sequential_pair_promotion_model_shadow).
"""
from __future__ import annotations

import hashlib
import json
import math
import pickle
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Optional

# Ordered, self-describing feature schema. Must match the offline training
# pipeline in investigations/2026-07-28-promotion-quarantine-controller-model/
# code/extract_dwell_dataset.py exactly -- this list (not any hardcoded
# positional assumption) is what PromotionFeatureBuilder emits and what
# PromotionModelBundle.predict_proba consumes, in this order.
RAW_FIELDS = [
    "confidence", "inlier_count", "icp_best_to_second_score_ratio",
    "icp_near_tie_basin_count", "overlap_ratio", "corridor_degeneracy_ratio",
    "mean_residual_m", "median_residual_m", "estimated_distance_to_anchor_m",
]
MATCH_CLASSES = ["clean_full_pose", "ambiguous_high_confidence", "partial_pose_degenerate"]

# z-stats for the U (reading-unreliability) score. Single source of truth --
# route_memory_agent.py's _reading_unreliability and the offline extraction
# script both currently hardcode their own copy of this; a follow-up should
# make both import this one (see INTEGRATION_PLAN.md Phase 0).
U_ZSTATS = {
    "inlier_count": (288.5561, 113.2020),
    "best_to_second_score_ratio": (0.7142, 0.2353),
    "near_tie_basin_count": (0.8686, 1.3620),
    "confidence": (0.7448, 0.2309),
}


def _zz(key: str, value: float) -> float:
    mean, std = U_ZSTATS[key]
    return (float(value) - mean) / (std if std else 1.0)


def reading_unreliability(rec: Optional[Mapping[str, Any]]) -> Optional[float]:
    if rec is None:
        return None
    inl = rec.get("inlier_count")
    ratio = rec.get("icp_best_to_second_score_ratio")
    nt = rec.get("icp_near_tie_basin_count")
    conf = rec.get("confidence")
    if inl is None or ratio is None or nt is None or conf is None:
        return None
    return (
        -_zz("inlier_count", inl)
        + _zz("best_to_second_score_ratio", ratio)
        + _zz("near_tie_basin_count", nt)
        - _zz("confidence", conf)
    )


def _raw_feats(rec: Optional[Mapping[str, Any]], prefix: str) -> dict[str, Optional[float]]:
    out: dict[str, Optional[float]] = {}
    for f in RAW_FIELDS:
        out[f"{prefix}_{f}"] = rec.get(f) if rec else None
    match_class = rec.get("match_class") if rec else None
    for mc in MATCH_CLASSES:
        out[f"{prefix}_match_{mc}"] = 1.0 if match_class == mc else 0.0
    out[f"{prefix}_U"] = reading_unreliability(rec)
    return out


FEATURE_NAMES = (
    [f"next_{f}" for f in RAW_FIELDS] + [f"next_match_{m}" for m in MATCH_CLASSES] + ["next_U"]
    + [f"cur_{f}" for f in RAW_FIELDS] + [f"cur_match_{m}" for m in MATCH_CLASSES] + ["cur_U"]
    + [
        "attempt", "attempt_in_dwell", "n_prior_in_dwell", "anchor_idx",
        "cur_bad_fraction_hist",
        "next_dist_rollmean", "next_dist_rollstd",
        "next_conf_rollmean", "next_conf_rollstd",
        "next_ratio_rollmean", "next_ratio_rollstd",
    ]
)


@dataclass
class _DwellStream:
    """Causal per-(episode, next-anchor-index) rolling state -- resets
    naturally whenever a new anchor index takes the 'next' role, since
    anchor indices in this project's route are visited at most once as
    'next' under today's (no-eviction) promotion mechanics. If/when
    sequential_pair_evict_unreliable_current (line-2 mechanism-B fix,
    MODIFICATION_PLAN.md Phase 0.2) ships, an evicted current could in
    principle re-expose an anchor index as 'next' a second time -- revisit
    this keying assumption if that happens; today it's fine to key by
    anchor_idx alone within an episode."""
    attempt_in_dwell: int = -1
    current_reliability_hist: list[float] = field(default_factory=list)
    dist_hist: list[float] = field(default_factory=list)
    conf_hist: list[float] = field(default_factory=list)
    ratio_hist: list[float] = field(default_factory=list)


def _roll_stat(hist: list[float]) -> tuple[Optional[float], Optional[float]]:
    if not hist:
        return None, None
    m = sum(hist) / len(hist)
    if len(hist) < 2:
        return m, 0.0
    var = sum((x - m) ** 2 for x in hist) / len(hist)
    return m, math.sqrt(var)


class PromotionFeatureBuilder:
    """Causal online equivalent of extract_dwell_dataset.py's per-attempt
    feature computation. Call build_attempt() once per relocalization
    attempt with the SAME record shape covisibility_records already uses
    (dicts with anchor_index/confidence/inlier_count/...). Never uses
    information from attempts after the current one -- safe to call live."""

    def __init__(self) -> None:
        self._episode_key: Optional[str] = None
        self._streams: dict[int, _DwellStream] = {}

    def start_episode(self, episode_key: str) -> None:
        if self._episode_key != str(episode_key):
            self._episode_key = str(episode_key)
            self._streams = {}

    def build_attempt(
        self,
        episode_key: str,
        attempt: int,
        records: list[Mapping[str, Any]],
    ) -> Optional[dict[str, Optional[float]]]:
        """records: this attempt's covisibility_records entries (>=1 of them,
        current + next roles inferred from anchor_index, highest = current).
        Returns None if there's no 'next' candidate this attempt (e.g. only
        one anchor left, or records empty)."""
        self.start_episode(episode_key)
        by_idx = {int(r["anchor_index"]): r for r in records}
        idxs = sorted(by_idx.keys(), reverse=True)
        if len(idxs) < 2:
            return None
        cur_idx, next_idx = idxs[0], idxs[1]
        cur_rec, next_rec = by_idx.get(cur_idx), by_idx.get(next_idx)

        stream = self._streams.setdefault(next_idx, _DwellStream())
        stream.attempt_in_dwell += 1
        n_prior = stream.attempt_in_dwell  # attempts strictly before this one, in this dwell

        feat: dict[str, Optional[float]] = {
            "attempt": float(attempt),
            "attempt_in_dwell": float(n_prior),
            "n_prior_in_dwell": float(n_prior),
            "anchor_idx": float(next_idx),
        }
        feat.update(_raw_feats(next_rec, "next"))
        feat.update(_raw_feats(cur_rec, "cur"))

        cu = reading_unreliability(cur_rec)
        hist_for_frac = list(stream.current_reliability_hist)  # PRIOR history only (causal)
        feat["cur_bad_fraction_hist"] = (
            sum(1 for u in hist_for_frac if u >= 2.5) / len(hist_for_frac)
            if len(hist_for_frac) >= 3 else None
        )
        if cu is not None:
            stream.current_reliability_hist.append(cu)

        d_mean, d_std = _roll_stat(stream.dist_hist)
        c_mean, c_std = _roll_stat(stream.conf_hist)
        r_mean, r_std = _roll_stat(stream.ratio_hist)
        feat["next_dist_rollmean"], feat["next_dist_rollstd"] = d_mean, d_std
        feat["next_conf_rollmean"], feat["next_conf_rollstd"] = c_mean, c_std
        feat["next_ratio_rollmean"], feat["next_ratio_rollstd"] = r_mean, r_std

        if next_rec is not None:
            dv = next_rec.get("estimated_distance_to_anchor_m")
            if dv is not None:
                stream.dist_hist.append(dv)
            cv = next_rec.get("confidence")
            if cv is not None:
                stream.conf_hist.append(cv)
            rv = next_rec.get("icp_best_to_second_score_ratio")
            if rv is not None:
                stream.ratio_hist.append(rv)

        return feat


class PromotionDecisionPolicy:
    """Thresholds live separately from the model bundle so they can be
    retuned without retraining (see FINDINGS.md section 4.1 -- raw argmax on
    quarantine is not the right operating point; 0.6-0.7 is)."""

    def __init__(self, quarantine_threshold: float = 0.65):
        self.quarantine_threshold = float(quarantine_threshold)

    def decide(self, proba: dict[str, float]) -> str:
        if proba.get("quarantine", 0.0) >= self.quarantine_threshold:
            return "quarantine"
        return "promote" if proba.get("promote", 0.0) >= proba.get("wait", 0.0) else "wait"

    def metadata(self) -> dict[str, Any]:
        return {"quarantine_threshold": self.quarantine_threshold}


class PromotionModelBundle:
    """Hash-versioned, self-describing model artifact. Not a bare pickle:
    carries its own feature schema and z-stats so a mismatch between
    training-time and inference-time feature computation fails loudly
    (KeyError on a missing feature) instead of silently misaligning
    columns."""

    FORMAT = "promotion_controller_v1"

    def __init__(self, model: Any, feature_names: list[str], classes: list[str], metadata: dict[str, Any]):
        self.model = model
        self.feature_names = list(feature_names)
        self.classes = list(classes)
        self.metadata = dict(metadata)

    def predict_proba(self, feat: dict[str, Optional[float]]) -> dict[str, float]:
        row = [
            feat.get(name) if feat.get(name) is not None else float("nan")
            for name in self.feature_names
        ]
        proba = self.model.predict_proba([row])[0]
        return {c: float(p) for c, p in zip(self.classes, proba)}

    def save(self, path: str | Path) -> str:
        path = Path(path)
        payload = {
            "format": self.FORMAT,
            "model": self.model,
            "feature_names": self.feature_names,
            "classes": self.classes,
            "metadata": self.metadata,
        }
        with open(path, "wb") as f:
            pickle.dump(payload, f)
        return self.sha256_of(path)

    @staticmethod
    def sha256_of(path: str | Path) -> str:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()

    @classmethod
    def load(cls, path: str | Path, mode: str = "shadow") -> "PromotionModelBundle":
        if mode != "shadow":
            raise ValueError(
                f"PromotionModelBundle.load(mode={mode!r}): only 'shadow' is "
                "implemented -- there is no enforcement/active loader yet "
                "(see INTEGRATION_PLAN.md Phase 3, not started)."
            )
        with open(path, "rb") as f:
            payload = pickle.load(f)
        if payload.get("format") != cls.FORMAT:
            raise ValueError(f"unexpected bundle format: {payload.get('format')!r}")
        bundle = cls(payload["model"], payload["feature_names"], payload["classes"], payload["metadata"])
        bundle.source_artifact_sha256 = cls.sha256_of(path)
        return bundle


def _json_safe(value: Any) -> Any:
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    return value


class PromotionShadowJsonlSession:
    """Fail-open online shadow session with durable per-attempt JSONL
    logging -- mirrors reliability/v11_runtime.py's V11ShadowJsonlSession.
    enforcement_enabled/controller_effect are always False here; nothing
    in round_trip_eval.py acts on score_attempt's return value yet."""

    def __init__(
        self,
        bundle: PromotionModelBundle,
        *,
        episode_key: str,
        log_path: str | Path,
        decision_policy: Optional[PromotionDecisionPolicy] = None,
        physical_episode_id: Optional[int] = None,
        scene_id: Optional[str] = None,
    ):
        self.bundle = bundle
        self.episode_key = str(episode_key)
        self.log_path = Path(log_path)
        self.physical_episode_id = int(physical_episode_id) if physical_episode_id is not None else None
        self.scene_id = str(scene_id) if scene_id is not None else None
        self.decision_policy = decision_policy or PromotionDecisionPolicy()
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._feature_builder = PromotionFeatureBuilder()
        self._feature_builder.start_episode(self.episode_key)
        self._handle = open(self.log_path, "a", encoding="utf-8", buffering=1)
        self._shadow_exceptions = 0
        self._closed = False
        self._write({
            "event": "promotion_shadow_session_start",
            "episode_key": self.episode_key,
            "physical_episode_id": self.physical_episode_id,
            "scene_id": self.scene_id,
            "mode": "shadow",
            "enforcement_enabled": False,
            "controller_effect": False,
            "model_format": self.bundle.metadata.get("format", self.bundle.FORMAT),
            "source_artifact_sha256": getattr(self.bundle, "source_artifact_sha256", None),
            "feature_count": len(self.bundle.feature_names),
            "decision_policy": self.decision_policy.metadata(),
        })

    def _write(self, record: Mapping[str, Any]) -> None:
        self._handle.write(json.dumps(_json_safe(dict(record)), sort_keys=True) + "\n")
        self._handle.flush()

    def score_attempt(
        self,
        *,
        step: int,
        attempt: int,
        records: list[Mapping[str, Any]],
        existing_heuristic_decision: Optional[Mapping[str, Any]] = None,
    ) -> Optional[dict[str, Any]]:
        """Score one live relocalization attempt. Any failure is caught,
        logged, and swallowed -- returns None on failure, never raises, so a
        bug in this shadow path can never take down a real episode."""
        started = time.perf_counter()
        try:
            feat = self._feature_builder.build_attempt(self.episode_key, attempt, records)
            if feat is None:
                return None
            proba = self.bundle.predict_proba(feat)
            decision = self.decision_policy.decide(proba)
            latency_ms = (time.perf_counter() - started) * 1000.0
            output = {
                "decision": decision,
                "proba": proba,
                "anchor_idx": feat.get("anchor_idx"),
                "attempt_in_dwell": feat.get("attempt_in_dwell"),
            }
            self._write({
                "event": "promotion_shadow_score",
                "episode_key": self.episode_key,
                "step": int(step),
                "attempt": int(attempt),
                "latency_ms": latency_ms,
                "output": output,
                "existing_heuristic_decision": (
                    dict(existing_heuristic_decision) if existing_heuristic_decision else None
                ),
                "enforcement_enabled": False,
                "controller_effect": False,
            })
            return output
        except Exception as exc:  # fail-open: never let shadow scoring break a real episode
            self._shadow_exceptions += 1
            self._write({
                "event": "promotion_shadow_exception",
                "episode_key": self.episode_key,
                "step": int(step),
                "attempt": int(attempt),
                "error_type": type(exc).__name__,
                "error": str(exc),
                "enforcement_enabled": False,
                "controller_effect": False,
            })
            return None

    def close(self) -> dict[str, Any]:
        if self._closed:
            return {}
        summary = {
            "event": "promotion_shadow_session_end",
            "episode_key": self.episode_key,
            "shadow_exceptions": self._shadow_exceptions,
        }
        self._write(summary)
        self._handle.close()
        self._closed = True
        return summary
