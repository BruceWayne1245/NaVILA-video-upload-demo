"""Nested group-CV model comparison and conservative V1.1 calibration."""

from __future__ import annotations

import hashlib
import json
import math
import pickle
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from .audit import risk_coverage_curve
from .calibration import PlattCalibrator
from .diagnostics import calibration_curve_equal_mass, expected_calibration_error, _weighted_quantile
from .schema import NUMERIC_FEATURES


HEADS = ("bearing", "distance", "pose")


@dataclass(frozen=True)
class CandidateSpec:
    name: str
    family: str
    feature_set: str


CANDIDATES = (
    CandidateSpec("logistic_v1", "logistic", "v1"),
    CandidateSpec("hgb_v1", "hgb", "v1"),
    CandidateSpec("hgb_basin", "hgb", "basin"),
    CandidateSpec("hgb_basin_pair", "hgb", "basin_pair"),
    CandidateSpec("hgb_full_temporal", "hgb", "full"),
)


def load_v11_npz(path: str | Path) -> dict[str, np.ndarray]:
    with np.load(path, allow_pickle=False) as payload:
        return {name: payload[name].copy() for name in payload.files}


def physical_episode_balanced_weights(groups: np.ndarray) -> np.ndarray:
    groups = np.asarray(groups)
    unique, counts = np.unique(groups, return_counts=True)
    count_by_group = dict(zip(unique.tolist(), counts.tolist()))
    scale = len(groups) / len(unique)
    return np.asarray([scale / count_by_group[group.item() if hasattr(group, "item") else group] for group in groups])


def feature_indices(feature_names: np.ndarray, feature_set: str) -> np.ndarray:
    names = [str(name) for name in feature_names]
    v1 = set(NUMERIC_FEATURES)
    if feature_set == "v1":
        selected = [
            index for index, name in enumerate(names)
            if name in v1 or name.startswith("match_class__") or name.startswith("icp_ambiguity__")
        ]
    elif feature_set == "basin":
        selected = [
            index for index, name in enumerate(names)
            if not name.startswith("pair_") and not name.startswith("temporal_")
        ]
    elif feature_set == "basin_pair":
        selected = [index for index, name in enumerate(names) if not name.startswith("temporal_")]
    elif feature_set == "full":
        selected = list(range(len(names)))
    else:
        raise ValueError(f"unknown feature set: {feature_set}")
    if not selected:
        raise ValueError(f"feature set {feature_set} is empty")
    return np.asarray(selected, dtype=int)


def make_model(spec: CandidateSpec, seed: int):
    if spec.family == "logistic":
        from sklearn.impute import SimpleImputer
        from sklearn.linear_model import LogisticRegression
        from sklearn.pipeline import Pipeline
        from sklearn.preprocessing import StandardScaler

        return Pipeline([
            ("imputer", SimpleImputer(strategy="median", add_indicator=True, keep_empty_features=True)),
            ("scaler", StandardScaler()),
            ("classifier", LogisticRegression(
                C=0.5, max_iter=1500, solver="liblinear", random_state=seed
            )),
        ])
    if spec.family == "hgb":
        from sklearn.ensemble import HistGradientBoostingClassifier

        return HistGradientBoostingClassifier(
            max_iter=150,
            learning_rate=0.07,
            max_leaf_nodes=31,
            max_depth=6,
            min_samples_leaf=30,
            l2_regularization=1.0,
            early_stopping=False,
            random_state=seed,
        )
    raise ValueError(f"unknown family: {spec.family}")


def fit_model(model: Any, spec: CandidateSpec, x: np.ndarray, y: np.ndarray, weight: np.ndarray) -> Any:
    if spec.family == "logistic":
        model.fit(x, y, classifier__sample_weight=weight)
    else:
        model.fit(x, y, sample_weight=weight)
    return model


def _ranking_metrics(y: np.ndarray, probability: np.ndarray, weight: np.ndarray) -> dict[str, float | None]:
    from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score

    return {
        "roc_auc": float(roc_auc_score(y, probability, sample_weight=weight)) if np.unique(y).size > 1 else None,
        "average_precision": float(average_precision_score(y, probability, sample_weight=weight)) if np.unique(y).size > 1 else None,
        "brier": float(brier_score_loss(y, probability, sample_weight=weight)),
    }


def make_group_folds(
    labels_pose: np.ndarray,
    groups: np.ndarray,
    scenes: np.ndarray,
    n_splits: int,
    seed: int,
) -> tuple[list[tuple[np.ndarray, np.ndarray]], list[dict[str, Any]]]:
    from sklearn.model_selection import StratifiedGroupKFold

    splitter = StratifiedGroupKFold(n_splits=n_splits, shuffle=True, random_state=seed)
    folds, audit = [], []
    for fold, (train, validation) in enumerate(splitter.split(np.zeros(len(groups)), labels_pose, groups)):
        train_groups = set(groups[train].tolist())
        validation_groups = set(groups[validation].tolist())
        overlap = sorted(train_groups & validation_groups)
        if overlap:
            raise AssertionError(f"physical episode leakage in fold {fold}: {overlap}")
        folds.append((train, validation))
        audit.append({
            "fold": fold,
            "train_rows": len(train),
            "validation_rows": len(validation),
            "train_physical_episodes": len(train_groups),
            "validation_physical_episodes": len(validation_groups),
            "validation_scenes": sorted(set(scenes[validation].tolist())),
            "validation_scene_count": len(set(scenes[validation].tolist())),
            "group_overlap": overlap,
        })
    return folds, audit


def candidate_oof_predictions(
    matrix: np.ndarray,
    labels: np.ndarray,
    weight: np.ndarray,
    feature_names: np.ndarray,
    folds: list[tuple[np.ndarray, np.ndarray]],
    spec: CandidateSpec,
    seed: int,
) -> np.ndarray:
    selected = feature_indices(feature_names, spec.feature_set)
    predictions = np.full(len(labels), np.nan, dtype=float)
    covered = np.zeros(len(labels), dtype=bool)
    for fold_index, (train, validation) in enumerate(folds):
        model = make_model(spec, seed + fold_index)
        fit_model(model, spec, matrix[train][:, selected], labels[train], weight[train])
        predictions[validation] = model.predict_proba(matrix[validation][:, selected])[:, 1]
        covered[validation] = True
    if not np.isfinite(predictions[covered]).all():
        raise AssertionError(f"incomplete OOF predictions for {spec.name}")
    return predictions


def conservative_cluster_threshold(
    probability: np.ndarray,
    target: np.ndarray,
    weight: np.ndarray,
    groups: np.ndarray,
    maximum_bad_rate: float,
    bootstrap_samples: int,
    seed: int,
    minimum_coverage: float = 0.05,
) -> dict[str, Any]:
    unique_groups, inverse = np.unique(groups, return_inverse=True)
    rng = np.random.default_rng(seed)
    sampled = rng.integers(0, len(unique_groups), size=(bootstrap_samples, len(unique_groups)))
    multiplicities = np.stack([
        np.bincount(draw, minlength=len(unique_groups)) for draw in sampled
    ])
    candidates = []
    for requested_coverage in np.arange(minimum_coverage, 0.851, 0.05):
        threshold = float(_weighted_quantile(probability, weight, [requested_coverage])[0])
        trusted = probability <= threshold
        trusted_weight_by_group = np.bincount(
            inverse, weights=weight * trusted, minlength=len(unique_groups)
        )
        bad_weight_by_group = np.bincount(
            inverse, weights=weight * trusted * target, minlength=len(unique_groups)
        )
        denominators = multiplicities @ trusted_weight_by_group
        numerators = multiplicities @ bad_weight_by_group
        valid = denominators > 0
        bootstrap_risk = numerators[valid] / denominators[valid]
        empirical_coverage = float(np.average(trusted, weights=weight))
        empirical_risk = float(np.average(target[trusted], weights=weight[trusted])) if trusted.any() else None
        upper = float(np.quantile(bootstrap_risk, 0.95)) if bootstrap_risk.size else None
        candidates.append({
            "requested_coverage": float(requested_coverage),
            "threshold": threshold,
            "coverage": empirical_coverage,
            "empirical_bad_rate": empirical_risk,
            "cluster_bootstrap_upper_95": upper,
            "target_met": upper is not None and upper <= maximum_bad_rate,
        })
    valid = [candidate for candidate in candidates if candidate["target_met"]]
    selected = max(valid, key=lambda item: item["coverage"]) if valid else {
        "requested_coverage": 0.0,
        "threshold": -1.0,
        "coverage": 0.0,
        "empirical_bad_rate": None,
        "cluster_bootstrap_upper_95": None,
        "target_met": False,
    }
    return {
        "method": "physical_episode_cluster_bootstrap_one_sided_95",
        "target_bad_rate": float(maximum_bad_rate),
        "bootstrap_samples": int(bootstrap_samples),
        "minimum_coverage": float(minimum_coverage),
        "selected": selected,
        "candidates": candidates,
    }


def _trusted_metrics(
    target: np.ndarray,
    probability: np.ndarray,
    weight: np.ndarray,
    trusted: np.ndarray,
) -> dict[str, Any]:
    result = _ranking_metrics(target, probability, weight)
    curve = calibration_curve_equal_mass(target, probability, weight)
    result.update({
        "rows": len(target),
        "positive_rate": float(np.average(target, weights=weight)),
        "mean_probability": float(np.average(probability, weights=weight)),
        "calibration_bias": float(np.average(probability - target, weights=weight)),
        "ece_equal_mass_10": expected_calibration_error(curve),
        "trusted_coverage": float(np.average(trusted, weights=weight)),
        "trusted_bad_rate": (
            float(np.average(target[trusted], weights=weight[trusted])) if trusted.any() else None
        ),
    })
    return result


def _macro_metrics(
    target: np.ndarray,
    probability: np.ndarray,
    trusted: np.ndarray,
    group_values: np.ndarray,
) -> dict[str, Any]:
    per_group = []
    for group in sorted(np.unique(group_values).tolist()):
        selected = group_values == group
        metrics = _trusted_metrics(
            target[selected], probability[selected], np.ones(int(selected.sum())), trusted[selected]
        )
        per_group.append({"group": str(group), **metrics})
    output = {"groups": len(per_group), "per_group": per_group}
    for name in (
        "roc_auc", "average_precision", "brier", "positive_rate",
        "ece_equal_mass_10", "trusted_coverage", "trusted_bad_rate",
    ):
        values = [item[name] for item in per_group if item.get(name) is not None]
        output[name] = float(np.mean(values)) if values else None
        output[f"{name}_groups"] = len(values)
    return output


def nested_compare(
    data: Mapping[str, np.ndarray],
    outer_splits: int,
    inner_splits: int,
    bootstrap_samples: int,
    seed: int,
    risk_targets: Mapping[str, float],
) -> dict[str, Any]:
    matrix = np.asarray(data["features"], dtype=np.float32)
    labels_all = np.asarray(data["labels"], dtype=np.int8)
    feature_names = data["feature_names"]
    groups = np.asarray(data["episode_id"])
    scenes = np.asarray(data["scene_id"])
    weight = physical_episode_balanced_weights(groups)
    outer_folds, fold_audit = make_group_folds(
        labels_all[:, 2], groups, scenes, outer_splits, seed
    )
    output: dict[str, Any] = {
        "outer_splits": outer_splits,
        "inner_splits": inner_splits,
        "physical_episodes": int(len(np.unique(groups))),
        "scenes": int(len(np.unique(scenes))),
        "fold_audit": fold_audit,
        "heads": {},
    }
    for head_index, head in enumerate(HEADS):
        target = labels_all[:, head_index]
        outer_probability = np.full(len(target), np.nan)
        outer_trusted = np.zeros(len(target), dtype=bool)
        fold_reports = []
        candidate_evidence: dict[str, list[float]] = defaultdict(list)
        for outer_index, (outer_train, outer_test) in enumerate(outer_folds):
            print(
                f"nested head={head} outer={outer_index + 1}/{len(outer_folds)} "
                f"train_rows={len(outer_train)} test_rows={len(outer_test)}",
                flush=True,
            )
            inner_relative, inner_audit = make_group_folds(
                labels_all[outer_train, 2], groups[outer_train], scenes[outer_train],
                inner_splits, seed + 100 + outer_index,
            )
            inner_folds = [
                (outer_train[train], outer_train[validation])
                for train, validation in inner_relative
            ]
            candidates = {}
            for spec in CANDIDATES:
                prediction = candidate_oof_predictions(
                    matrix, target, weight, feature_names, inner_folds, spec,
                    seed + 1000 * (head_index + 1) + 10 * outer_index,
                )
                # candidate_oof_predictions fills only outer_train when folds
                # are absolute; retain that leakage-safe subset.
                inner_probability = prediction[outer_train]
                metrics = _ranking_metrics(target[outer_train], inner_probability, weight[outer_train])
                candidates[spec.name] = {
                    "spec": spec,
                    "probability": inner_probability,
                    "metrics": metrics,
                }
                candidate_evidence[spec.name].append(float(metrics["roc_auc"]))
            selected_name = max(candidates, key=lambda name: candidates[name]["metrics"]["roc_auc"])
            print(
                f"nested head={head} outer={outer_index + 1} selected={selected_name} "
                f"auc={candidates[selected_name]['metrics']['roc_auc']:.4f}",
                flush=True,
            )
            selected_spec = next(spec for spec in CANDIDATES if spec.name == selected_name)
            selected_inner = candidates[selected_name]["probability"]
            calibrator = PlattCalibrator().fit(
                selected_inner, target[outer_train], weight[outer_train]
            )
            calibrated_inner = calibrator.predict(selected_inner)
            threshold = conservative_cluster_threshold(
                calibrated_inner, target[outer_train], weight[outer_train], groups[outer_train],
                float(risk_targets[head]), bootstrap_samples,
                seed + 10000 * (head_index + 1) + outer_index,
            )
            selected_features = feature_indices(feature_names, selected_spec.feature_set)
            model = make_model(selected_spec, seed + outer_index)
            fit_model(
                model, selected_spec, matrix[outer_train][:, selected_features],
                target[outer_train], weight[outer_train],
            )
            raw_test = model.predict_proba(matrix[outer_test][:, selected_features])[:, 1]
            calibrated_test = calibrator.predict(raw_test)
            outer_probability[outer_test] = calibrated_test
            selected_threshold = float(threshold["selected"]["threshold"])
            outer_trusted[outer_test] = calibrated_test <= selected_threshold
            fold_reports.append({
                "outer_fold": outer_index,
                "selected_candidate": selected_name,
                "candidate_metrics": {
                    name: values["metrics"] for name, values in candidates.items()
                },
                "calibrator": {"slope": calibrator.slope, "intercept": calibrator.intercept},
                "threshold": threshold,
                "inner_fold_audit": inner_audit,
                "outer_test_rows": len(outer_test),
                "outer_test_physical_episodes": len(np.unique(groups[outer_test])),
            })
        if not np.isfinite(outer_probability).all():
            raise AssertionError(f"nested outer OOF is incomplete for {head}")
        output["heads"][head] = {
            "nested_oof": _trusted_metrics(target, outer_probability, weight, outer_trusted),
            "episode_macro": _macro_metrics(target, outer_probability, outer_trusted, groups),
            "scene_macro": _macro_metrics(target, outer_probability, outer_trusted, scenes),
            "risk_coverage": risk_coverage_curve(target, outer_probability, weight),
            "folds": fold_reports,
            "candidate_mean_inner_auc": {
                name: float(np.mean(values)) for name, values in candidate_evidence.items()
            },
            "candidate_selection_counts": dict(Counter(
                fold["selected_candidate"] for fold in fold_reports
            )),
        }
    return output


def fit_final_development_bundle(
    data: Mapping[str, np.ndarray],
    nested_report: Mapping[str, Any],
    folds: int,
    bootstrap_samples: int,
    seed: int,
    risk_targets: Mapping[str, float],
) -> tuple[dict[str, Any], dict[str, Any]]:
    matrix = np.asarray(data["features"], dtype=np.float32)
    labels_all = np.asarray(data["labels"], dtype=np.int8)
    feature_names = np.asarray(data["feature_names"])
    groups = np.asarray(data["episode_id"])
    scenes = np.asarray(data["scene_id"])
    weight = physical_episode_balanced_weights(groups)
    cv_folds, fold_audit = make_group_folds(labels_all[:, 2], groups, scenes, folds, seed + 50000)
    bundle: dict[str, Any] = {
        "schema_version": str(data["schema_version"]),
        "feature_names": feature_names.tolist(),
        "development_only": True,
        "prospective_validation_passed": False,
        "heads": {},
    }
    report = {"folds": folds, "fold_audit": fold_audit, "heads": {}}
    for head_index, head in enumerate(HEADS):
        evidence = nested_report["heads"][head]["candidate_mean_inner_auc"]
        selected_name = max(evidence, key=evidence.get)
        print(f"final head={head} selected={selected_name}", flush=True)
        spec = next(candidate for candidate in CANDIDATES if candidate.name == selected_name)
        raw_oof = candidate_oof_predictions(
            matrix, labels_all[:, head_index], weight, feature_names,
            cv_folds, spec, seed + 60000 + head_index,
        )
        calibrator = PlattCalibrator().fit(
            raw_oof, labels_all[:, head_index], weight
        )
        calibrated_oof = calibrator.predict(raw_oof)
        threshold = conservative_cluster_threshold(
            calibrated_oof, labels_all[:, head_index], weight, groups,
            float(risk_targets[head]), bootstrap_samples,
            seed + 70000 + head_index,
        )
        selected_features = feature_indices(feature_names, spec.feature_set)
        final_model = make_model(spec, seed + 80000 + head_index)
        fit_model(
            final_model, spec, matrix[:, selected_features], labels_all[:, head_index], weight
        )
        trusted = calibrated_oof <= float(threshold["selected"]["threshold"])
        bundle["heads"][head] = {
            "candidate": selected_name,
            "feature_set": spec.feature_set,
            "feature_indices": selected_features.tolist(),
            "model": final_model,
            "calibrator": calibrator,
            "trusted_threshold": float(threshold["selected"]["threshold"]),
        }
        report["heads"][head] = {
            "selected_candidate": selected_name,
            "selection_evidence_mean_inner_auc": evidence,
            "development_oof": _trusted_metrics(
                labels_all[:, head_index], calibrated_oof, weight, trusted
            ),
            "episode_macro": _macro_metrics(
                labels_all[:, head_index], calibrated_oof, trusted, groups
            ),
            "scene_macro": _macro_metrics(
                labels_all[:, head_index], calibrated_oof, trusted, scenes
            ),
            "threshold": threshold,
        }
    return bundle, report


def save_bundle(bundle: Mapping[str, Any], path: str | Path) -> dict[str, Any]:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with open(output, "wb") as handle:
        pickle.dump(dict(bundle), handle, protocol=pickle.HIGHEST_PROTOCOL)
    return {
        "artifact": str(output),
        "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        "size_bytes": output.stat().st_size,
        "development_only": True,
        "prospective_validation_passed": False,
    }


def _fmt(value: Any) -> str:
    return "n/a" if value is None else f"{float(value):.4f}"


def training_report_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# Reliability V1.1 nested development report",
        "",
        "## Status",
        "",
        "Development-only shadow candidate. All 89 historical runs are development data; no prospective validation has occurred and enforcement is prohibited.",
        "",
        "## Leakage controls",
        "",
        f"- Outer CV: {report['nested']['outer_splits']} folds; inner model selection: {report['nested']['inner_splits']} folds.",
        f"- Group unit: physical CLI episode ID across all batches ({report['nested']['physical_episodes']} unique), not episode-run.",
        f"- Scene count: {report['nested']['scenes']}; every fold records its scene composition.",
        "- Current and next candidates from one attempt remain together because the entire physical episode is held out.",
        "- Calibration and conservative threshold selection use inner OOF predictions only; outer-fold rows remain untouched.",
        "",
        "## Nested outer-OOF performance",
        "",
        "| Head | AUC | AP | Brier | ECE | Trusted coverage | Trusted bad | Episode-macro AUC | Scene-macro AUC |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for head, values in report["nested"]["heads"].items():
        metrics = values["nested_oof"]
        lines.append(
            f"| {head} | {_fmt(metrics['roc_auc'])} | {_fmt(metrics['average_precision'])} | "
            f"{_fmt(metrics['brier'])} | {_fmt(metrics['ece_equal_mass_10'])} | "
            f"{_fmt(metrics['trusted_coverage'])} | {_fmt(metrics['trusted_bad_rate'])} | "
            f"{_fmt(values['episode_macro']['roc_auc'])} | {_fmt(values['scene_macro']['roc_auc'])} |"
        )
    lines.extend([
        "",
        "## Candidate evidence and final development choice",
        "",
        "| Head | Final candidate | Logistic V1 AUC | HGB V1 AUC | Basin AUC | Basin+pair AUC | Full temporal AUC | Final threshold target met |",
        "|---|---|---:|---:|---:|---:|---:|:---:|",
    ])
    for head, values in report["final_development"]["heads"].items():
        evidence = values["selection_evidence_mean_inner_auc"]
        lines.append(
            f"| {head} | `{values['selected_candidate']}` | {_fmt(evidence['logistic_v1'])} | "
            f"{_fmt(evidence['hgb_v1'])} | {_fmt(evidence['hgb_basin'])} | "
            f"{_fmt(evidence['hgb_basin_pair'])} | {_fmt(evidence['hgb_full_temporal'])} | "
            f"{'YES' if values['threshold']['selected']['target_met'] else 'NO'} |"
        )
    lines.extend([
        "",
        "## Final all-development OOF characterization",
        "",
        "This section is selection-biased and is provided only to characterize the frozen candidate. The nested table above is the less-biased model-selection estimate.",
        "",
        "| Head | AUC | AP | Brier | ECE | Conservative coverage | Empirical trusted bad | Bootstrap upper 95% | Target |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ])
    for head, values in report["final_development"]["heads"].items():
        metrics = values["development_oof"]
        threshold = values["threshold"]["selected"]
        target = values["threshold"]["target_bad_rate"]
        lines.append(
            f"| {head} | {_fmt(metrics['roc_auc'])} | {_fmt(metrics['average_precision'])} | "
            f"{_fmt(metrics['brier'])} | {_fmt(metrics['ece_equal_mass_10'])} | "
            f"{_fmt(threshold['coverage'])} | {_fmt(threshold['empirical_bad_rate'])} | "
            f"{_fmt(threshold['cluster_bootstrap_upper_95'])} | {_fmt(target)} |"
        )
    lines.extend([
        "",
        "## Decision",
        "",
        "The artifact may be used only for offline replay and future shadow integration. It must be frozen before the next batch is opened, and it cannot unlock any consumer until a new prospective batch clears the predeclared risk and runtime gates.",
        "",
    ])
    return "\n".join(lines)
