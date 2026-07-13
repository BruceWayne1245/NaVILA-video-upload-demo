import json
import numpy as np
from collections import defaultdict, Counter

rows10 = json.load(open("/tmp/claude-1006/-home-teambruce/317da1c8-fb11-4286-93b7-7e49924245bb/scratchpad/bearing_rows_20260710.json"))
rows12 = json.load(open("/tmp/claude-1006/-home-teambruce/317da1c8-fb11-4286-93b7-7e49924245bb/scratchpad/bearing_rows_20260712.json"))
for r in rows10:
    r["batch"] = "20260710"
for r in rows12:
    r["batch"] = "20260712"
all_rows = rows10 + rows12
print(f"combined n = {len(all_rows)} (07-10: {len(rows10)}, 07-12: {len(rows12)})")

errs = np.array([r["bearing_err"] for r in all_rows])
over10 = errs > 10.0
print(f"combined >10deg: {over10.sum()}/{len(errs)} = {100*over10.mean():.2f}%")
print(f"combined median={np.median(errs):.2f} mean={errs.mean():.2f} p90={np.percentile(errs,90):.2f}")
print()

bucket = [r for r in all_rows if r["bearing_err"] > 10]
clean = [r for r in all_rows if r["bearing_err"] <= 5]
print(f"bucket(>10deg) n={len(bucket)}, clean(<=5deg) n={len(clean)}")

flagged_matchclass = [r for r in bucket if r["match_class"] in ("ambiguous_high_confidence", "partial_pose_degenerate", "height_inconsistent_2p5d")]
flagged_neartie = [r for r in bucket if (r["near_tie"] or 0) > 0]
unexplained = [r for r in bucket if r["match_class"] == "clean_full_pose" and (r["near_tie"] or 0) == 0]
print()
print("--- combined breakdown of >10deg bucket ---")
print(f"match_class flagged: {len(flagged_matchclass)} ({100*len(flagged_matchclass)/len(bucket):.1f}%)")
print(f"near_tie>0: {len(flagged_neartie)} ({100*len(flagged_neartie)/len(bucket):.1f}%)")
print(f"unexplained (clean_full_pose + near_tie==0): {len(unexplained)} ({100*len(unexplained)/len(bucket):.1f}%)")
print("match_class dist in bucket:", dict(Counter(r["match_class"] for r in bucket)))
print()

# feature comparison: unexplained-bad vs clean
def stats(vals):
    vals = [v for v in vals if v is not None]
    if not vals:
        return "n/a"
    a = np.array(vals)
    return f"n={len(a)} median={np.median(a):.3f} mean={a.mean():.3f} p10={np.percentile(a,10):.3f} p90={np.percentile(a,90):.3f}"

print("--- feature comparison: UNEXPLAINED (clean_full_pose, near_tie=0, err>10) vs CLEAN (err<=5) ---")
for feat in ["overlap", "inlier", "confidence", "median_residual", "corridor", "yaw_peak_width", "yaw_norm_entropy", "true_dist"]:
    print(f"{feat}:")
    print(f"  unexplained: {stats([r.get(feat) for r in unexplained])}")
    print(f"  clean:       {stats([r.get(feat) for r in clean])}")
print()

# distribution of the actual bearing error VALUE within unexplained bucket -- clustering near specific angles?
uerrs = np.array([r["bearing_err"] for r in unexplained])
print("--- unexplained bucket bearing_err distribution (deg) ---")
for lo, hi in [(10,30),(30,60),(60,90),(90,120),(120,150),(150,180)]:
    m = (uerrs>=lo)&(uerrs<hi)
    print(f"  [{lo},{hi}): {m.sum()} ({100*m.mean():.1f}%)")
print(f"  near-180 (160-180): {((uerrs>=160)&(uerrs<=180)).sum()} ({100*((uerrs>=160)&(uerrs<=180)).mean():.1f}%)")
print(f"  near-90 (80-100 or 260-280 -- only 0-180 range stored so just 80-100): {((uerrs>=80)&(uerrs<=100)).sum()} ({100*((uerrs>=80)&(uerrs<=100)).mean():.1f}%)")
print()

# per (ep,anchor,batch) group -- is error persistent/systematic within a run?
print("--- within-run consistency: for unexplained groups with >=5 readings, is error tight (systematic) or spread (unstable)? ---")
by_group = defaultdict(list)
for r in unexplained:
    by_group[(r["batch"], r["ep"], r["anchor"])].append(r["bearing_err"])
tight, spread = 0, 0
for k, v in by_group.items():
    if len(v) < 5:
        continue
    arr = np.array(v)
    cv = arr.std() / (arr.mean() + 1e-9)
    if cv < 0.3:
        tight += 1
    else:
        spread += 1
print(f"groups(n>=5): tight(std/mean<0.3)={tight}, spread(std/mean>=0.3)={spread}")
print()
print("--- worst persistent groups (>=5 readings, sorted by mean err) ---")
scored = []
for k, v in by_group.items():
    if len(v) < 5:
        continue
    arr = np.array(v)
    scored.append((k, len(arr), arr.mean(), arr.std()))
scored.sort(key=lambda x: -x[2])
for k, n, m, s in scored[:20]:
    print(f"  batch={k[0]} ep{k[1]} anchor{k[2]}: n={n}, mean={m:.1f}, std={s:.1f}")
print()

# cross-run persistence: same (ep,anchor) appearing as a "bad" (mean>45, unexplained-dominant) group in BOTH batches
print("--- cross-run persistence: same (ep,anchor) flagged bad in BOTH the 07-10 and 07-12 batches ---")
by_ep_anchor_batch = defaultdict(list)
for r in all_rows:
    by_ep_anchor_batch[(r["batch"], r["ep"], r["anchor"])].append(r["bearing_err"])
bad_by_batch = defaultdict(set)
mean_by_key = {}
for (batch, ep, anchor), v in by_ep_anchor_batch.items():
    arr = np.array(v)
    mean_by_key[(batch, ep, anchor)] = (arr.mean(), len(arr))
    if arr.mean() > 45 and len(arr) >= 3:
        bad_by_batch[batch].add((ep, anchor))

shared_eps = {4, 367, 368, 678, 994, 1040}
bad10 = {k for k in bad_by_batch["20260710"] if k[0] in shared_eps}
bad12 = {k for k in bad_by_batch["20260712"] if k[0] in shared_eps}
persistent = bad10 & bad12
only10 = bad10 - bad12
only12 = bad12 - bad10
print(f"bad in 07-10 (shared eps only): {sorted(bad10)}")
print(f"bad in 07-12 (shared eps only): {sorted(bad12)}")
print(f"PERSISTENT in both runs: {sorted(persistent)}")
print(f"only in 07-10: {sorted(only10)}")
print(f"only in 07-12: {sorted(only12)}")
for k in sorted(persistent):
    m10 = mean_by_key.get(("20260710",)+k)
    m12 = mean_by_key.get(("20260712",)+k)
    print(f"  ep{k[0]} anchor{k[1]}: 07-10 mean={m10[0]:.1f} (n={m10[1]}), 07-12 mean={m12[0]:.1f} (n={m12[1]})")
