"""
Two follow-up analyses on top of dwell_dataset_with_oof.csv (produced by oof_check.py):

1. Precision/recall/F1 tradeoff for the quarantine class at different
   oof_proba_quarantine thresholds (the raw argmax operating point turned out to have
   high recall but low precision on this 1.35%-base-rate class).
2. Whether ep355's fully-missed promote window (a next_estimated_distance_to_anchor_m
   that swings between ~0.8m and ~8.9m across consecutive attempts while ground truth
   stays a stable ~0.43m) is a general model weakness or a one-off.
"""
import pandas as pd
import numpy as np
from sklearn.metrics import (
    precision_recall_curve, average_precision_score, precision_score,
    recall_score, f1_score, classification_report,
)

df = pd.read_csv('dwell_dataset_with_oof.csv')

# --- 1. quarantine threshold calibration ---
y_true_q = (df['label'] == 'quarantine').astype(int)
proba_q = df['oof_proba_quarantine'].values
ap = average_precision_score(y_true_q, proba_q)
print(f"quarantine PR-AUC (average precision): {ap:.3f} (base rate {y_true_q.mean():.4f})")
print("\nthreshold  precision  recall  f1   n_predicted_quarantine")
for t in [0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.50, 0.60, 0.70, 0.80, 0.90]:
    pred = (proba_q >= t).astype(int)
    p = precision_score(y_true_q, pred, zero_division=0)
    r = recall_score(y_true_q, pred, zero_division=0)
    f1 = f1_score(y_true_q, pred, zero_division=0)
    print(f"  {t:.2f}      {p:.3f}      {r:.3f}   {f1:.3f}   {pred.sum()}")

classes = ['wait', 'promote', 'quarantine']
proba_all = df[['oof_proba_wait', 'oof_proba_promote', 'oof_proba_quarantine']].values
y_true = df['label'].values
for t in [0.6, 0.7]:
    pred = np.where(
        proba_all[:, 2] >= t, 'quarantine',
        np.where(proba_all[:, 1] >= proba_all[:, 0], 'promote', 'wait'),
    )
    print(f"\n=== full 3-way rule, quarantine threshold = {t} ===")
    print(classification_report(y_true, pred, labels=classes, digits=3, zero_division=0))

# --- 2. is ep355's extreme-swing pattern a general weakness? ---
df['is_impossible_outlier'] = (df['next_estimated_distance_to_anchor_m'] > 5.0) & (df['gt_anchor_true_dist'] < 2.0)
print(f"\n'impossible outlier' readings: {df['is_impossible_outlier'].sum()} / {len(df)} "
      f"({100*df['is_impossible_outlier'].mean():.2f}%)")

dwell_flag = df.groupby('dwell_id')['is_impossible_outlier'].max()
print(f"dwells containing >=1 such reading: {dwell_flag.sum()} / {dwell_flag.shape[0]} "
      f"({100*dwell_flag.sum()/dwell_flag.shape[0]:.2f}%)")
df['dwell_has_outlier'] = df['dwell_id'].map(dwell_flag)

promote_rows = df[df['label'] == 'promote']
r_with = promote_rows[promote_rows['dwell_has_outlier']]['oof_pred'].eq('promote').mean()
r_without = promote_rows[~promote_rows['dwell_has_outlier']]['oof_pred'].eq('promote').mean()
print(f"\nmodel recall on true-promote attempts:")
print(f"  dwells WITH impossible-outlier readings:    {r_with:.3f} (n={promote_rows['dwell_has_outlier'].sum()})")
print(f"  dwells WITHOUT such readings:                {r_without:.3f} (n={(~promote_rows['dwell_has_outlier']).sum()})")
