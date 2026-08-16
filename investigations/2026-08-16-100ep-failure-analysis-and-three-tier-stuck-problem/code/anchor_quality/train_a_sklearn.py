"""Approach A: train a gradient-boosted regressor on hand-crafted geometric
features (features_a.json) to predict good_fraction. No augmentation/capacity
control requested for approach B applies in spirit here too -- use a
reasonably-sized GBM and just report both train-fit and held-out numbers
honestly (episode-level split, same split logic as approach B for a fair
side-by-side)."""
from __future__ import annotations

import json
import os

import numpy as np
from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor
from sklearn.metrics import mean_absolute_error

OUT_DIR = os.path.dirname(os.path.abspath(__file__))
FEATURES_PATH = os.path.join(OUT_DIR, "features_a.json")

FEATURE_COLS = [
    "n_points", "distance_from_start_m", "pca_lambda_min", "pca_lambda_max",
    "pca_condition_number", "pca_elongation", "bbox_x", "bbox_y", "bbox_z",
    "bbox_aspect", "point_density", "radius_p90", "z_std", "z_range",
    "corridor_degeneracy_ratio", "corridor_degeneracy_available",
    "normal_direction_entropy", "normal_direction_entropy_available",
    "self_alias_score", "self_alias_score_available",
]


def main():
    with open(FEATURES_PATH) as f:
        rows = json.load(f)
    print(f"loaded {len(rows)} feature rows")

    episodes = sorted({r["episode_idx"] for r in rows})
    rng = np.random.RandomState(0)  # same seed/logic as approach B for comparability
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

    results = {}
    for name, model in [
        ("gbm", GradientBoostingRegressor(n_estimators=300, max_depth=3, learning_rate=0.05, random_state=0)),
        ("rf", RandomForestRegressor(n_estimators=500, max_depth=None, random_state=0, n_jobs=-1)),
    ]:
        model.fit(X_train, y_train)
        train_pred = model.predict(X_train)
        val_pred = model.predict(X_val)
        train_mae = mean_absolute_error(y_train, train_pred)
        val_mae = mean_absolute_error(y_val, val_pred)
        val_corr = float(np.corrcoef(val_pred, y_val)[0, 1]) if y_val.std() > 1e-6 else float("nan")
        val_acc05 = float(np.mean((val_pred >= 0.5) == (y_val >= 0.5)))
        train_acc05 = float(np.mean((train_pred >= 0.5) == (y_train >= 0.5)))
        majority_baseline_acc = max(float(np.mean(y_val >= 0.5)), float(np.mean(y_val < 0.5)))
        print(f"\n=== {name} ===")
        print(f"train_mae={train_mae:.4f} val_mae={val_mae:.4f} val_corr={val_corr:.3f} "
              f"val_acc05={val_acc05:.3f} train_acc05={train_acc05:.3f} majority_baseline_acc={majority_baseline_acc:.3f}")
        if hasattr(model, "feature_importances_"):
            importances = sorted(zip(FEATURE_COLS, model.feature_importances_), key=lambda kv: -kv[1])
            print("top features:", [(c, round(float(v), 3)) for c, v in importances[:8]])
        results[name] = dict(
            train_mae=train_mae, val_mae=val_mae, val_corr=val_corr, val_acc05=val_acc05,
            train_acc05=train_acc05, majority_baseline_acc=majority_baseline_acc,
            top_features=[(c, float(v)) for c, v in importances[:10]] if hasattr(model, "feature_importances_") else None,
        )

    with open(os.path.join(OUT_DIR, "sklearn_result.json"), "w") as f:
        json.dump(dict(n_train=len(train_rows), n_val=len(val_rows), results=results), f, indent=2)
    print("\nDONE. saved sklearn_result.json")


if __name__ == "__main__":
    main()
