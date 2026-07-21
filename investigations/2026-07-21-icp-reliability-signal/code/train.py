import numpy as np, pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.model_selection import GroupKFold, cross_val_predict
from sklearn.metrics import roc_auc_score, average_precision_score, precision_recall_curve

df = pd.read_csv("/home/teambruce/scratch_inv/an/icp_dataset.csv")
print(f"总样本: {len(df)}  来自 {df['episode'].astype(str).add(df['tag']).nunique()} 个(tag,episode)")
print(f"坏读数(bearing误差>30°)占比: {df['label_bad_bearing'].mean()*100:.1f}%")
print(f"按批次样本数:\n{df.groupby('tag').size()}")

y = df["label_bad_bearing"].values
groups = (df["tag"] + "_" + df["episode"].astype(str)).values

NUMERIC = ["overlap_ratio","corridor_degeneracy_ratio","icp_near_tie_basin_count","icp_basin_count",
    "icp_best_to_second_score_ratio","icp_best_to_second_rotation_delta_deg","icp_best_to_second_translation_delta_m",
    "confidence","inlier_count","mean_residual_m","median_residual_m","anchor_points","current_points",
    "anchor_z_span_m","current_z_span_m","estimated_distance_to_anchor_m","loc_min_eig","loc_cond"]
for c in NUMERIC:
    df[c] = pd.to_numeric(df[c], errors="coerce")

print("\n===== (1) 单信号判别力 (AUC, 已对称到>0.5) =====")
single = []
for c in NUMERIC:
    v = df[c].values.astype(float)
    mask = ~np.isnan(v)
    if mask.sum() < 100 or len(np.unique(y[mask])) < 2:
        continue
    auc = roc_auc_score(y[mask], v[mask])
    auc = max(auc, 1 - auc)
    single.append((c, auc))
for c, auc in sorted(single, key=lambda x: -x[1]):
    bar = "#" * int((auc - 0.5) * 100)
    print(f"  {c:<38} AUC={auc:.3f} {bar}")
best_single = max(a for _, a in single) if single else 0.5
print(f"  --> 最强单信号 AUC = {best_single:.3f}")

# categorical one-hot
cat = pd.get_dummies(df[["match_class","icp_ambiguity"]].astype(str), prefix=["mc","amb"])
X = pd.concat([df[NUMERIC], cat], axis=1)
print(f"\n特征维度: {X.shape[1]} (数值{len(NUMERIC)} + 类别独热{cat.shape[1]})")

print("\n===== (2) 监督模型 (HistGBDT, 按episode分组5折CV) =====")
gkf = GroupKFold(n_splits=5)
clf = HistGradientBoostingClassifier(max_iter=300, learning_rate=0.08, max_depth=6,
                                     l2_regularization=1.0, random_state=0)
proba = cross_val_predict(clf, X.values, y, cv=gkf, groups=groups,
                          method="predict_proba", n_jobs=5)[:, 1]
auc = roc_auc_score(y, proba)
ap = average_precision_score(y, proba)
print(f"  交叉验证 AUC = {auc:.3f}   PR-AUC(AP) = {ap:.3f}   (基线正类率 {y.mean():.3f})")
prec, rec, thr = precision_recall_curve(y, proba)
for target_rec in (0.9, 0.8, 0.7, 0.5):
    idx = np.argmin(np.abs(rec - target_rec))
    print(f"    召回坏读数 {rec[idx]*100:.0f}% 时, 精度 = {prec[idx]*100:.0f}%")
# 反过来: 想干净放行好读数(拉黑坏读数时误伤少)
print("  若把'高分'判为坏并拉黑, 在不同阈值下 (坏读数=正类):")
for q in (0.5, 0.7, 0.9):
    t = np.quantile(proba, q)
    pred = proba >= t
    if pred.sum() == 0: continue
    p = y[pred].mean()  # 被判坏的里面真坏比例
    r = pred[y == 1].mean()
    print(f"    阈值={q:.0%}分位: 判坏{pred.sum()}条, 其中真坏{p*100:.0f}%, 覆盖了{r*100:.0f}%的真坏")

print(f"\n===== 结论 =====")
print(f"  最强单信号 AUC={best_single:.3f}  vs  监督模型 AUC={auc:.3f}  (提升 {auc-best_single:+.3f})")

# 特征重要性(用一次train/test近似: 单折)
print("\n===== (3) 特征重要性 (permutation, 单折) =====")
from sklearn.inspection import permutation_importance
tr, te = next(gkf.split(X.values, y, groups))
clf.fit(X.values[tr], y[tr])
r = permutation_importance(clf, X.values[te], y[te], n_repeats=5, random_state=0, n_jobs=5, scoring="roc_auc")
imp = sorted(zip(X.columns, r.importances_mean), key=lambda x: -x[1])[:15]
for name, val in imp:
    print(f"  {name:<40} {val:+.4f}")
