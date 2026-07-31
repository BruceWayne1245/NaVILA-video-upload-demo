import sys
sys.path.insert(0, "/mnt/SSD4T/teambruce/projects/NaVILA-video-upload-demo/investigations/2026-07-28-promotion-quarantine-controller-model/code")
import csv, math
from promotion_controller_runtime import PromotionModelBundle, PromotionDecisionPolicy
from collections import Counter, defaultdict

MODEL_PATH = "/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/models/promotion_controller_v2_2026-07-28_isaacenv.pkl"
CSV_PATH = "/tmp/claude-1006/-home-teambruce/c26c1924-d639-4a9c-b712-10d36d74d793/scratchpad/dwell_dataset_reliable30v3.csv"

bundle = PromotionModelBundle.load(MODEL_PATH, mode="shadow")
print("feature_names:", len(bundle.feature_names))
print("classes:", bundle.classes)
policy = PromotionDecisionPolicy(quarantine_threshold=0.65)

rows = []
with open(CSV_PATH) as f:
    r = csv.DictReader(f)
    for row in r:
        rows.append(row)
print("rows loaded:", len(rows))

def to_float(v):
    if v is None or v == '':
        return None
    try:
        return float(v)
    except ValueError:
        return v  # keep strings (episode/dwell_id) as-is, unused in feature_names anyway

feats = []
labels = []
episodes = []
for row in rows:
    feat = {k: to_float(v) for k, v in row.items()}
    feats.append(feat)
    labels.append(row['label'])
    episodes.append(row['episode'])

preds = []
probas = []
for feat in feats:
    proba = bundle.predict_proba(feat)
    dec = policy.decide(proba)
    preds.append(dec)
    probas.append(proba)

classes = ["wait", "promote", "quarantine"]
confusion = Counter()
for lab, pred in zip(labels, preds):
    confusion[(lab, pred)] += 1

print()
print("Confusion matrix (rows=true label, cols=predicted):")
print(f"{'':12}", *[f"{c:>10}" for c in classes])
for lab in classes:
    row = [confusion[(lab, pred)] for pred in classes]
    print(f"{lab:12}", *[f"{v:>10}" for v in row])

print()
for cls in classes:
    tp = confusion[(cls, cls)]
    fp = sum(confusion[(lab, cls)] for lab in classes if lab != cls)
    fn = sum(confusion[(cls, pred)] for pred in classes if pred != cls)
    prec = tp / (tp + fp) if (tp + fp) else float('nan')
    rec = tp / (tp + fn) if (tp + fn) else float('nan')
    f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else float('nan')
    print(f"{cls}: n_true={sum(confusion[(cls,p)] for p in classes)} TP={tp} FP={fp} FN={fn} precision={prec:.3f} recall={rec:.3f} F1={f1:.3f}")

# AUC (one-vs-rest) using proba
def auc_ovr(cls_name):
    pos_scores = [p[cls_name] for p, lab in zip(probas, labels) if lab == cls_name]
    neg_scores = [p[cls_name] for p, lab in zip(probas, labels) if lab != cls_name]
    if not pos_scores or not neg_scores:
        return float('nan')
    # Mann-Whitney U based AUC
    all_scores = sorted(pos_scores + neg_scores)
    ranks = {}
    # rank with average tie handling
    n = len(all_scores)
    i = 0
    rank_arr = [0.0]*n
    while i < n:
        j = i
        while j < n and all_scores[j] == all_scores[i]:
            j += 1
        avg_rank = (i + j + 1) / 2.0
        for k in range(i, j):
            rank_arr[k] = avg_rank
        i = j
    score_to_rank = {}
    for s, rk in zip(all_scores, rank_arr):
        score_to_rank.setdefault(s, []).append(rk)
    # assign ranks to pos_scores by matching (approx, ties handled via avg rank already)
    import bisect
    sorted_all = sorted(all_scores)
    rank_lookup = {}
    idx = 0
    for s in sorted(set(all_scores)):
        cnt = all_scores.count(s)
        avg_r = sum(r for r in rank_arr[idx:idx+cnt]) / cnt if cnt else 0
        rank_lookup[s] = (idx+1+idx+cnt)/2.0
        idx += cnt
    sum_ranks_pos = sum(rank_lookup[s] for s in pos_scores)
    n1, n0 = len(pos_scores), len(neg_scores)
    auc = (sum_ranks_pos - n1*(n1+1)/2.0) / (n1*n0)
    return auc

print()
for cls in classes:
    print(f"{cls} AUC (one-vs-rest): {auc_ovr(cls):.3f}")

print()
print("label distribution:", Counter(labels))
print("prediction distribution:", Counter(preds))

# per-episode breakdown for quarantine/promote to check spread not dominated by 1-2 episodes
print()
print("Per-episode row counts + label dist:")
by_ep = defaultdict(Counter)
for ep, lab in zip(episodes, labels):
    by_ep[ep][lab]+=1
for ep in sorted(by_ep):
    print(f"  {ep[-6:]}: {dict(by_ep[ep])}")
