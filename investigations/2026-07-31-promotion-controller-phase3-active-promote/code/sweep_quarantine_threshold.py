import sys
sys.path.insert(0, "/mnt/SSD4T/teambruce/projects/NaVILA-video-upload-demo/investigations/2026-07-28-promotion-quarantine-controller-model/code")
import csv
from promotion_controller_runtime import PromotionModelBundle
from collections import Counter

MODEL_PATH = "/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/models/promotion_controller_v2_2026-07-28_isaacenv.pkl"
SCRATCH = "/tmp/claude-1006/-home-teambruce/c26c1924-d639-4a9c-b712-10d36d74d793/scratchpad"

bundle = PromotionModelBundle.load(MODEL_PATH, mode="shadow")

def load_rows(path, tag):
    rows = []
    with open(path) as f:
        r = csv.DictReader(f)
        for row in r:
            row['_source'] = tag
            rows.append(row)
    return rows

rows = load_rows(f"{SCRATCH}/dwell_dataset_0728.csv", "0728") + load_rows(f"{SCRATCH}/dwell_dataset_reliable30v3.csv", "reliable30v3")
print("combined rows:", len(rows))
print("combined label dist:", Counter(r['label'] for r in rows))

def to_float(v):
    if v is None or v == '':
        return None
    try:
        return float(v)
    except ValueError:
        return v

feats, labels = [], []
for row in rows:
    feats.append({k: to_float(v) for k, v in row.items()})
    labels.append(row['label'])

probas = [bundle.predict_proba(feat) for feat in feats]

print()
print("=== quarantine_threshold sweep (promote = argmax(promote,wait) when not quarantined) ===")
print(f"{'thresh':>7} {'q_prec':>8} {'q_recall':>9} {'q_F1':>7} {'q_pred_n':>9} {'promote_prec':>13} {'promote_recall':>15}")
for thresh in [0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90, 0.95]:
    preds = []
    for p in probas:
        if p.get('quarantine', 0.0) >= thresh:
            preds.append('quarantine')
        elif p.get('promote', 0.0) >= p.get('wait', 0.0):
            preds.append('promote')
        else:
            preds.append('wait')
    tp = sum(1 for l,pr in zip(labels,preds) if l=='quarantine' and pr=='quarantine')
    fp = sum(1 for l,pr in zip(labels,preds) if l!='quarantine' and pr=='quarantine')
    fn = sum(1 for l,pr in zip(labels,preds) if l=='quarantine' and pr!='quarantine')
    prec = tp/(tp+fp) if (tp+fp) else float('nan')
    rec = tp/(tp+fn) if (tp+fn) else float('nan')
    f1 = 2*prec*rec/(prec+rec) if (prec+rec) else float('nan')
    n_pred_q = tp+fp

    ptp = sum(1 for l,pr in zip(labels,preds) if l=='promote' and pr=='promote')
    pfp = sum(1 for l,pr in zip(labels,preds) if l!='promote' and pr=='promote')
    pfn = sum(1 for l,pr in zip(labels,preds) if l=='promote' and pr!='promote')
    pprec = ptp/(ptp+pfp) if (ptp+pfp) else float('nan')
    prec_recall = ptp/(ptp+pfn) if (ptp+pfn) else float('nan')

    print(f"{thresh:7.2f} {prec:8.3f} {rec:9.3f} {f1:7.3f} {n_pred_q:9d} {pprec:13.3f} {prec_recall:15.3f}")

# also report at finer granularity around the knee
print()
print("=== finer sweep 0.70-0.95 ===")
for thresh in [0.70,0.72,0.74,0.76,0.78,0.80,0.82,0.84,0.86,0.88,0.90,0.92,0.94,0.96,0.98]:
    preds = ['quarantine' if p.get('quarantine',0.0)>=thresh else ('promote' if p.get('promote',0.0)>=p.get('wait',0.0) else 'wait') for p in probas]
    tp = sum(1 for l,pr in zip(labels,preds) if l=='quarantine' and pr=='quarantine')
    fp = sum(1 for l,pr in zip(labels,preds) if l!='quarantine' and pr=='quarantine')
    fn = sum(1 for l,pr in zip(labels,preds) if l=='quarantine' and pr!='quarantine')
    prec = tp/(tp+fp) if (tp+fp) else float('nan')
    rec = tp/(tp+fn) if (tp+fn) else float('nan')
    print(f"  thresh={thresh:.2f}  precision={prec:.3f}  recall={rec:.3f}  n_flagged={tp+fp}  tp={tp} fp={fp} fn={fn}")
