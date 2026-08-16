"""Retrain on features_a_v2.json (adds real cross-anchor alias_score +
nearest-neighbor-anchor spacing). Also adds sample_weight=log1p(n_observations)
to downweight noisy low-observation-count labels, and reports accuracy both
on the full val set and on a "reliable-label-only" val subset (n_observations
>= 20) to separate "model is bad" from "label is noisy" as causes of the
accuracy ceiling."""
from __future__ import annotations

import json
import os

import numpy as np
from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor
from sklearn.metrics import mean_absolute_error

OUT_DIR = os.path.dirname(os.path.abspath(__file__))
FEATURES_PATH = os.path.join(OUT_DIR, "features_a_v2.json")

FEATURE_COLS = [
    "n_points", "distance_from_start_m", "pca_lambda_min", "pca_lambda_max",
    "pca_condition_number", "pca_elongation", "bbox_x", "bbox_y", "bbox_z",
    "bbox_aspect", "point_density", "radius_p90", "z_std", "z_range",
    "corridor_degeneracy_ratio", "corridor_degeneracy_available",
    "normal_direction_entropy", "normal_direction_entropy_available",
    "self_alias_score", "self_alias_score_available",
    "cross_anchor_alias_score", "cross_anchor_alias_available",
    "nearest_neighbor_anchor_dist_m",
]


def report(name, model, X_train, y_train, X_val, y_val, val_nobs, weight_train=None):
    model.fit(X_train, y_train, sample_weight=weight_train) if weight_train is not None else model.fit(X_train, y_train)
    train_pred = model.predict(X_train)
    val_pred = model.predict(X_val)
    train_mae = mean_absolute_error(y_train, train_pred)
    val_mae = mean_absolute_error(y_val, val_pred)
    val_corr = float(np.corrcoef(val_pred, y_val)[0, 1]) if y_val.std() > 1e-6 else float("nan")
    val_acc05 = float(np.mean((val_pred >= 0.5) == (y_val >= 0.5)))
    majority = max(float(np.mean(y_val >= 0.5)), float(np.mean(y_val < 0.5)))

    reliable = val_nobs >= 20
    if reliable.sum() > 5:
        rel_acc05 = float(np.mean((val_pred[reliable] >= 0.5) == (y_val[reliable] >= 0.5)))
        rel_corr = float(np.corrcoef(val_pred[reliable], y_val[reliable])[0, 1])
        rel_majority = max(float(np.mean(y_val[reliable] >= 0.5)), float(np.mean(y_val[reliable] < 0.5)))
    else:
        rel_acc05 = rel_corr = rel_majority = float("nan")

    print(f"\n=== {name} ===")
    print(f"train_mae={train_mae:.4f} val_mae={val_mae:.4f} val_corr={val_corr:.3f} "
          f"val_acc05={val_acc05:.3f} (majority={majority:.3f})")
    print(f"  reliable-label-only (n_obs>=20, {reliable.sum()}/{len(val_nobs)} val rows): "
          f"acc05={rel_acc05:.3f} corr={rel_corr:.3f} (majority={rel_majority:.3f})")
    if hasattr(model, "feature_importances_"):
        importances = sorted(zip(FEATURE_COLS, model.feature_importances_), key=lambda kv: -kv[1])
        print("top features:", [(c, round(float(v), 3)) for c, v in importances[:10]])
    return dict(train_mae=train_mae, val_mae=val_mae, val_corr=val_corr, val_acc05=val_acc05,
                majority=majority, rel_acc05=rel_acc05, rel_corr=rel_corr, rel_majority=rel_majority)


def main():
    with open(FEATURES_PATH) as f:
        rows = json.load(f)
    print(f"loaded {len(rows)} feature rows (v2, with cross-anchor alias)")

    episodes = sorted({r["episode_idx"] for r in rows})
    rng = np.random.RandomState(0)
    rng.shuffle(episodes)
    n_val_eps = max(1, int(0.15 * len(episodes)))
    val_eps = set(episodes[:n_val_eps])
    train_rows = [r for r in rows if r["episode_idx"] not in val_eps]
    val_rows = [r for r in rows if r["episode_idx"] in val_eps]
    print(f"train rows: {len(train_rows)} ({len(episodes)-n_val_eps} eps), "
          f"val rows: {len(val_rows)} ({n_val_eps} eps)")

    X_train = np.array([[r[c] for c in FEATURE_COLS] for r in train_rows])
    y_train = np.array([r["good_fraction"] for r in train_rows])
    X_val = np.array([[r[c] for c in FEATURE_COLS] for r in val_rows])
    y_val = np.array([r["good_fraction"] for r in val_rows])
    val_nobs = np.array([r["n_observations"] for r in val_rows])
    w_train = np.log1p(np.array([r["n_observations"] for r in train_rows]))

    results = {}
    results["gbm_v2"] = report("gbm_v2 (+ cross-anchor alias, unweighted)",
        GradientBoostingRegressor(n_estimators=300, max_depth=3, learning_rate=0.05, random_state=0),
        X_train, y_train, X_val, y_val, val_nobs)
    results["gbm_v2_weighted"] = report("gbm_v2_weighted (+ cross-anchor alias, sample_weight=log1p(n_obs))",
        GradientBoostingRegressor(n_estimators=300, max_depth=3, learning_rate=0.05, random_state=0),
        X_train, y_train, X_val, y_val, val_nobs, weight_train=w_train)
    results["rf_v2"] = report("rf_v2 (+ cross-anchor alias, unweighted)",
        RandomForestRegressor(n_estimators=500, max_depth=None, random_state=0, n_jobs=-1),
        X_train, y_train, X_val, y_val, val_nobs)
    results["rf_v2_weighted"] = report("rf_v2_weighted (+ cross-anchor alias, sample_weight=log1p(n_obs))",
        RandomForestRegressor(n_estimators=500, max_depth=None, random_state=0, n_jobs=-1),
        X_train, y_train, X_val, y_val, val_nobs, weight_train=w_train)

    with open(os.path.join(OUT_DIR, "sklearn_v2_result.json"), "w") as f:
        json.dump(dict(n_train=len(train_rows), n_val=len(val_rows), results=results), f, indent=2)
    print("\nDONE. saved sklearn_v2_result.json")


if __name__ == "__main__":
    main()
