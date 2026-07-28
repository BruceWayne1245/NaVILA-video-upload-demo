import pandas as pd
import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.model_selection import GroupKFold
from sklearn.metrics import classification_report, confusion_matrix, roc_auc_score, balanced_accuracy_score
from sklearn.preprocessing import label_binarize

df = pd.read_csv('/tmp/claude-1006/-home-teambruce/1ae76ef4-cb03-4f21-9238-d1d566650215/scratchpad/dwell_dataset.csv')
print(f"loaded {len(df)} rows, {df['episode'].nunique()} episodes")

EXCLUDE = {'label', 'episode', 'dwell_id', 'gt_anchor_true_dist', 'dwell_is_episode_tail'}
feature_cols = [c for c in df.columns if c not in EXCLUDE]
print(f"n features = {len(feature_cols)}: {feature_cols}")

X = df[feature_cols].values
y = df['label'].values
groups = df['episode'].values

classes = ['wait', 'promote', 'quarantine']
class_to_idx = {c: i for i, c in enumerate(classes)}
y_idx = np.array([class_to_idx[v] for v in y])

# class weights (inverse frequency, capped) to counter 82/17/1.4 imbalance
counts = pd.Series(y).value_counts()
print("class counts:\n", counts)
weight_map = {c: len(y) / (len(classes) * counts[c]) for c in classes}
print("class weights:", weight_map)
sample_weight_all = np.array([weight_map[v] for v in y])

gkf = GroupKFold(n_splits=5)
fold_reports = []
all_true, all_pred, all_proba = [], [], []

for fold, (tr_idx, va_idx) in enumerate(gkf.split(X, y_idx, groups)):
    Xtr, Xva = X[tr_idx], X[va_idx]
    ytr, yva = y_idx[tr_idx], y_idx[va_idx]
    sw = sample_weight_all[tr_idx]

    clf = HistGradientBoostingClassifier(
        max_iter=300, learning_rate=0.08, max_depth=6,
        l2_regularization=1.0, random_state=42, early_stopping=True,
        validation_fraction=0.1,
    )
    clf.fit(Xtr, ytr, sample_weight=sw)
    pred = clf.predict(Xva)
    proba = clf.predict_proba(Xva)

    bal_acc = balanced_accuracy_score(yva, pred)
    print(f"\n=== Fold {fold} (n_val={len(va_idx)}, n_val_episodes={len(set(groups[va_idx]))}) balanced_acc={bal_acc:.3f} ===")
    print(classification_report(yva, pred, target_names=classes, digits=3, zero_division=0))
    cm = confusion_matrix(yva, pred, labels=[0, 1, 2])
    print("confusion matrix (rows=true, cols=pred), order wait/promote/quarantine:")
    print(cm)

    all_true.append(yva); all_pred.append(pred); all_proba.append(proba)
    fold_reports.append(bal_acc)

all_true = np.concatenate(all_true)
all_pred = np.concatenate(all_pred)
all_proba = np.concatenate(all_proba)

print(f"\n=== OVERALL (pooled across 5 held-out folds) ===")
print(f"mean balanced_accuracy across folds: {np.mean(fold_reports):.3f} +/- {np.std(fold_reports):.3f}")
print(classification_report(all_true, all_pred, target_names=classes, digits=3, zero_division=0))
cm = confusion_matrix(all_true, all_pred, labels=[0, 1, 2])
print("pooled confusion matrix:\n", cm)

y_true_bin = label_binarize(all_true, classes=[0, 1, 2])
for i, c in enumerate(classes):
    try:
        auc = roc_auc_score(y_true_bin[:, i], all_proba[:, i])
        print(f"AUC ({c} vs rest): {auc:.3f}")
    except Exception as e:
        print(c, "AUC failed:", e)

# --- baseline: naive "close_enough <= 0.75m -> promote, else if far & no data -> wait" ---
naive_pred = np.full(len(df), class_to_idx['wait'])
dist = df['next_estimated_distance_to_anchor_m'].values
naive_pred[dist <= 0.75] = class_to_idx['promote']
print(f"\n=== Naive close_enough<=0.75m baseline (whole dataset, not CV) ===")
print(classification_report(y_idx, naive_pred, target_names=classes, digits=3, zero_division=0))

# --- final model trained on all data, feature importance via permutation on a held-out fold not easily available in HGB; use built-in ---
final_clf = HistGradientBoostingClassifier(
    max_iter=300, learning_rate=0.08, max_depth=6,
    l2_regularization=1.0, random_state=42, early_stopping=True,
    validation_fraction=0.1,
)
final_clf.fit(X, y_idx, sample_weight=sample_weight_all)

from sklearn.inspection import permutation_importance
print("\ncomputing permutation importance on a random 5000-row subsample (final model)...")
rng = np.random.RandomState(0)
sub_idx = rng.choice(len(X), size=min(5000, len(X)), replace=False)
pi = permutation_importance(final_clf, X[sub_idx], y_idx[sub_idx], n_repeats=5, random_state=0, n_jobs=-1)
order = np.argsort(pi.importances_mean)[::-1]
print("top 20 features by permutation importance:")
for i in order[:20]:
    print(f"  {feature_cols[i]:35s} {pi.importances_mean[i]:.4f} +/- {pi.importances_std[i]:.4f}")

import pickle
with open('/tmp/claude-1006/-home-teambruce/1ae76ef4-cb03-4f21-9238-d1d566650215/scratchpad/promotion_model.pkl', 'wb') as f:
    pickle.dump({'model': final_clf, 'feature_cols': feature_cols, 'classes': classes}, f)
print("\nsaved final model to promotion_model.pkl")
