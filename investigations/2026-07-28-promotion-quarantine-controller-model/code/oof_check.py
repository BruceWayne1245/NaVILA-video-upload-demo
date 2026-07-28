import pandas as pd
import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.model_selection import GroupKFold

df = pd.read_csv('/tmp/claude-1006/-home-teambruce/1ae76ef4-cb03-4f21-9238-d1d566650215/scratchpad/dwell_dataset.csv')

EXCLUDE = {'label', 'episode', 'dwell_id', 'gt_anchor_true_dist', 'dwell_is_episode_tail'}
feature_cols = [c for c in df.columns if c not in EXCLUDE]
X = df[feature_cols].values
classes = ['wait', 'promote', 'quarantine']
class_to_idx = {c: i for i, c in enumerate(classes)}
y_idx = np.array([class_to_idx[v] for v in df['label'].values])
groups = df['episode'].values

counts = pd.Series(df['label'].values).value_counts()
weight_map = {c: len(y_idx) / (len(classes) * counts[c]) for c in classes}
sample_weight_all = np.array([weight_map[v] for v in df['label'].values])

oof_pred = np.full(len(df), -1)
oof_proba = np.zeros((len(df), 3))

gkf = GroupKFold(n_splits=5)
for fold, (tr_idx, va_idx) in enumerate(gkf.split(X, y_idx, groups)):
    clf = HistGradientBoostingClassifier(
        max_iter=300, learning_rate=0.08, max_depth=6,
        l2_regularization=1.0, random_state=42, early_stopping=True,
        validation_fraction=0.1,
    )
    clf.fit(X[tr_idx], y_idx[tr_idx], sample_weight=sample_weight_all[tr_idx])
    oof_pred[va_idx] = clf.predict(X[va_idx])
    oof_proba[va_idx] = clf.predict_proba(X[va_idx])
    print(f"fold {fold} done")

df['oof_pred'] = [classes[i] for i in oof_pred]
df['oof_proba_wait'] = oof_proba[:, 0]
df['oof_proba_promote'] = oof_proba[:, 1]
df['oof_proba_quarantine'] = oof_proba[:, 2]

df.to_csv('/tmp/claude-1006/-home-teambruce/1ae76ef4-cb03-4f21-9238-d1d566650215/scratchpad/dwell_dataset_with_oof.csv', index=False)
print("saved dwell_dataset_with_oof.csv")

# ---- now inspect known mechanism episodes ----
KNOWN = {
    'A': [19, 88, 95, 427],
    'B': [344, 355],
    'C': [276, 646],
}
batch = "vision_disagreement_ab_50ep_20260726_downgrade"

for mech, eps in KNOWN.items():
    print(f"\n########## MECHANISM {mech} ##########")
    for ep in eps:
        pat = f"{batch}_ep{ep}"
        sub = df[df['episode'].str.contains(pat, regex=False)].sort_values('attempt')
        if sub.empty:
            print(f"  ep{ep}: not found in dataset")
            continue
        print(f"\n--- ep{ep}: {len(sub)} attempts across {sub['dwell_id'].nunique()} dwells ---")
        # show where oof_pred disagrees with what naive close_enough<=0.75 would do, and where label==promote but heuristic never promoted
        promote_rows = sub[sub['label'] == 'promote']
        model_promote_rows = sub[sub['oof_pred'] == 'promote']
        print(f"  true 'should-promote' attempts: {len(promote_rows)} (anchors: {sorted(promote_rows['anchor_idx'].unique())})")
        print(f"  model predicted 'promote' attempts: {len(model_promote_rows)} (anchors: {sorted(model_promote_rows['anchor_idx'].unique())})")
        # overlap
        if len(promote_rows) > 0:
            hit = model_promote_rows['attempt'].isin(promote_rows['attempt']) if len(model_promote_rows) else []
            recall_here = sub[(sub['label']=='promote')]['oof_pred'].eq('promote').mean()
            print(f"  model recall on true-promote attempts in this episode: {recall_here:.2f}")
        quarantine_rows = sub[sub['label'] == 'quarantine']
        if len(quarantine_rows):
            qrecall = quarantine_rows['oof_pred'].eq('quarantine').mean()
            print(f"  true quarantine attempts: {len(quarantine_rows)}, model recall: {qrecall:.2f}")
