"""
2b: calibrate reliability_quarantine_threshold (Injection A) against ground truth.

Injection A quarantines a `next` anchor when, over >= min_history readings, the
fraction whose per-reading unreliability U >= threshold exceeds bad_fraction.
U = -z(inlier_count) + z(best_to_second_score_ratio) + z(near_tie) - z(confidence),
same embedded z-stats as route_memory_agent._RELIABILITY_ZSTATS.

We replay that EXACT anchor-level decision at a sweep of thresholds over the
90k labeled dataset (grouped by tag+episode+anchor), scoring:
  - anchor-level recall   = of genuinely-degenerate anchors, how many get quarantined
  - anchor-level precision= of quarantined anchors, how many are genuinely degenerate
  - false-quarantine rate = of GOOD anchors, how many get wrongly quarantined
    (the dangerous error: starves promotion; 2026-07-15's cascade came from this)

Ground-truth anchor label (two variants reported):
  truth_majbad = majority of the anchor's readings have bearing error > 30°
  truth_nearbad= at the anchor's closest approaches (true_dist<1.5m), majority bad
                 (isolates genuine degeneracy from merely-far readings)
"""
import csv, statistics
from collections import defaultdict

CSV = "/home/teambruce/scratch_inv/an/icp_dataset.csv"

# EXACT z-stats from route_memory_agent._RELIABILITY_ZSTATS (Injection A diff)
Z = {
    "inlier_count": (288.5561, 113.2020),
    "best_to_second_score_ratio": (0.7142, 0.2353),
    "near_tie_basin_count": (0.8686, 1.3620),
    "confidence": (0.7448, 0.2309),
}
# Injection A defaults for the persistence logic (we calibrate ONLY the threshold)
MIN_HISTORY = 6
BAD_FRACTION = 0.5
NEAR_M = 1.5
PIN_TAG = "canonical_report_next_stopgate_100ep_20260720"
PIN = {5:11,20:8,319:4,367:11,498:5,500:10,680:6,813:6,889:9,994:6,1038:4,653:10}

def z(key, v):
    m, s = Z[key]
    return (v - m) / (s if s else 1.0)

def U_of(row):
    try:
        inl = float(row["inlier_count"]); ratio = float(row["icp_best_to_second_score_ratio"])
        nt = float(row["icp_near_tie_basin_count"]); conf = float(row["confidence"])
    except (ValueError, KeyError):
        return None
    return (-z("inlier_count", inl) + z("best_to_second_score_ratio", ratio)
            + z("near_tie_basin_count", nt) - z("confidence", conf))

# group readings by anchor
groups = defaultdict(list)   # (tag,ep,anchor) -> list of dict(U, bad, near, ang)
for r in csv.DictReader(open(CSV)):
    u = U_of(r)
    if u is None:
        continue
    try:
        ang = float(r["ang_err"]); td = float(r["true_dist"]); bad = int(r["label_bad_bearing"])
    except ValueError:
        continue
    groups[(r["tag"], r["episode"], int(r["anchor_index"]))].append(
        dict(U=u, bad=bad, near=(td < NEAR_M), ang=ang))

# build per-anchor summaries (only anchors with enough history to be quarantinable)
anchors = []
for key, rr in groups.items():
    if len(rr) < MIN_HISTORY:
        continue
    n = len(rr)
    frac_bad = sum(x["bad"] for x in rr) / n
    near = [x for x in rr if x["near"]]
    frac_near_bad = (sum(x["bad"] for x in near) / len(near)) if len(near) >= 3 else None
    anchors.append(dict(key=key, rr=rr, n=n, truth_majbad=(frac_bad > 0.5),
                        truth_nearbad=(frac_near_bad > 0.5 if frac_near_bad is not None else None),
                        frac_bad=frac_bad, frac_near_bad=frac_near_bad))

def quarantined(a, thr):
    return sum(1 for x in a["rr"] if x["U"] >= thr) / a["n"] > BAD_FRACTION

def score(thr, truth_field, subset=None):
    A = subset if subset is not None else anchors
    A = [a for a in A if a[truth_field] is not None]
    tp = fp = fn = tn = 0
    for a in A:
        q = quarantined(a, thr); t = a[truth_field]
        if q and t: tp += 1
        elif q and not t: fp += 1
        elif (not q) and t: fn += 1
        else: tn += 1
    n_bad = tp + fn; n_good = fp + tn
    recall = tp / n_bad if n_bad else 0.0
    prec = tp / (tp + fp) if (tp + fp) else 0.0
    fqr = fp / n_good if n_good else 0.0
    return dict(thr=thr, tp=tp, fp=fp, fn=fn, tn=tn, recall=recall, prec=prec, fqr=fqr,
                n_bad=n_bad, n_good=n_good, n_quar=tp+fp)

print(f"quarantinable anchor groups (>= {MIN_HISTORY} readings): {len(anchors)}")
maj = [a for a in anchors if a['truth_majbad']]
nb = [a for a in anchors if a['truth_nearbad']]
print(f"  ground-truth degenerate (majority bad-bearing):        {len(maj)}/{len(anchors)}")
print(f"  ground-truth degenerate (majority bad AT CLOSE range): {len(nb)}/{len([a for a in anchors if a['truth_nearbad'] is not None])}\n")

THRS = [5.05, 4.5, 4.0, 3.5, 3.0, 2.5, 2.0, 1.5, 1.0, 0.5, 0.0, -0.5, -1.0]
for truth_field, lbl in [("truth_majbad", "majority-bad-bearing"), ("truth_nearbad", "majority-bad-AT-CLOSE")]:
    print(f"{'='*92}\nSWEEP vs ground truth = {lbl}\n{'='*92}")
    print(f"{'thr':>6} | {'#quar':>5} | {'recall':>6} {'prec':>6} | {'false-quar rate (good anchors wrongly skipped)':>12}")
    for thr in THRS:
        s = score(thr, truth_field)
        star = "  <- Injection A default" if abs(thr - 5.05) < 1e-6 else ""
        print(f"{thr:>6.2f} | {s['n_quar']:>5} | {s['recall']:>6.1%} {s['prec']:>6.1%} | {s['fqr']:>11.1%}   (TP={s['tp']} FP={s['fp']} FN={s['fn']}){star}")
    print()

# ---- focused check: the pin episodes' next-role anchors (what quarantine must act on) ----
print(f"{'='*92}\nFOCUSED: pin-episode anchors at/below the pin (the stuck `next` chain)\n{'='*92}")
print("For each captured pin episode, the anchors near the pin that Injection A would score as `next`.")
print(f"{'ep':>5} {'pin':>4} | per-anchor: idx(frac_bad, n, U@thr-quarantined?) at a few thresholds")
pin_anchor_rows = []
for ep, pin in PIN.items():
    for a in anchors:
        tag, e, idx = a["key"]
        if tag == PIN_TAG and e == str(ep) and idx <= pin:
            pin_anchor_rows.append((ep, pin, idx, a))
# print compact per-episode
by_ep = defaultdict(list)
for ep, pin, idx, a in pin_anchor_rows:
    by_ep[(ep, pin)].append((idx, a))
CHECK_THRS = [5.05, 3.0, 2.0, 1.0]
for (ep, pin), items in sorted(by_ep.items()):
    items.sort()
    print(f"ep{ep:<4} a{pin}:")
    for idx, a in items:
        role = "PIN(current)" if idx == pin else "next"
        flags = " ".join(f"t{t}:{'Q' if quarantined(a,t) else '.'}" for t in CHECK_THRS)
        truth = "BAD" if a["truth_majbad"] else "ok "
        print(f"    a{idx:<3}[{role:>12}] n={a['n']:>4} frac_bad={a['frac_bad']:.2f} gt={truth} | quar@[{'/'.join(map(str,CHECK_THRS))}]= {flags}")

# ---- principled pick: anchor-level Youden J (recall - false-quar rate) on majbad ----
print(f"\n{'='*92}\nRECOMMENDATION\n{'='*92}")
best = None
for i in range(0, 61):
    thr = 5.0 - i*0.1
    s = score(thr, "truth_majbad")
    J = s["recall"] - s["fqr"]
    if best is None or J > best[0]:
        best = (J, thr, s)
J, thr, s = best
print(f"Max anchor-level Youden J (recall - false-quar) at thr={thr:.2f}: "
      f"J={J:.3f}  recall={s['recall']:.1%} false-quar={s['fqr']:.1%} prec={s['prec']:.1%}")

# U distribution of the actual pin `next` anchors (pin-1), split detectable vs confidently-wrong
print("\nPin `next` anchors (idx=pin-1), ground-truth degenerate ones only:")
print(f"{'ep':>5} {'next':>4} {'frac_bad':>8} {'medianU':>7} {'p75U':>6} | catchable?")
import statistics as st
for ep, pin in sorted(PIN.items()):
    a = next((x for x in anchors if x["key"]==(PIN_TAG, str(ep), pin-1)), None)
    if a is None or not a["truth_majbad"]:
        continue
    us = sorted(x["U"] for x in a["rr"])
    med = us[len(us)//2]; p75 = us[int(len(us)*0.75)]
    # detectable if a threshold in [2,3] would quarantine it
    det = quarantined(a, 3.0) or quarantined(a, 2.5)
    tag = "U-detectable (thr~2.5-3)" if det else "CONFIDENTLY-WRONG (U clean; no safe thr → vision residual)"
    print(f"{ep:>5} a{pin-1:<3} {a['frac_bad']:>8.2f} {med:>7.2f} {p75:>6.2f} | {tag}")
