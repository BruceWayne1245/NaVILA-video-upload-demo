import json, csv, os, math
import numpy as np

BENCH = "/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench"
D2 = "/mnt/SSD4T/teambruce/projects/NaVILA-video-upload-demo/final_data2"

def load_tsv(path):
    with open(path) as f:
        r = csv.DictReader(f, delimiter="\t")
        return list(r)

baseline_rows = load_tsv(os.path.join(D2, "pure_baseline_highsuccess100ep_chronological_first50_20260818_matched50_full_results.tsv"))
oracle_rows = load_tsv(os.path.join(D2, "pure_oracle_hint_highsuccess100ep_20260811_matched50_full_results.tsv"))

baseline_by_id = {int(r["episode_id"]): r for r in baseline_rows}
oracle_by_id = {int(r["episode_id"]): r for r in oracle_rows}

common_ids = sorted(set(baseline_by_id) & set(oracle_by_id))
print(f"baseline rows={len(baseline_rows)} oracle rows={len(oracle_rows)} common episode_id={len(common_ids)}")

def traj_path(run_tag, episode_idx, episode_id):
    result_suffix = f"{run_tag}_ep{episode_idx}"
    result_dir = (f"round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_{result_suffix}")
    return os.path.join(BENCH, "eval_results", result_dir, "trajectories", f"output_{episode_id-1}.jsonl")

def load_phase_positions(path):
    phases = {"outbound": [], "return": [], "confirm": []}
    if not os.path.exists(path):
        return None
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            ph = rec.get("phase")
            pos = rec.get("position")
            if ph in phases and pos is not None:
                phases[ph].append((pos[0], pos[1]))
    return phases

def arc_length_resample(points, n=100):
    pts = np.asarray(points, dtype=float)
    if len(pts) < 2:
        return None
    seg = np.linalg.norm(np.diff(pts, axis=0), axis=1)
    cum = np.concatenate([[0], np.cumsum(seg)])
    total = cum[-1]
    if total < 1e-6:
        return np.repeat(pts[:1], n, axis=0)
    targets = np.linspace(0, total, n)
    out = np.zeros((n, 2))
    out[:, 0] = np.interp(targets, cum, pts[:, 0])
    out[:, 1] = np.interp(targets, cum, pts[:, 1])
    return out

def path_divergence(pts_a, pts_b, n=100):
    ra = arc_length_resample(pts_a, n)
    rb = arc_length_resample(pts_b, n)
    if ra is None or rb is None:
        return None
    d = np.linalg.norm(ra - rb, axis=1)
    length_a = float(np.sum(np.linalg.norm(np.diff(np.asarray(pts_a), axis=0), axis=1)))
    length_b = float(np.sum(np.linalg.norm(np.diff(np.asarray(pts_b), axis=0), axis=1)))
    return {
        "mean_div_m": float(np.mean(d)),
        "max_div_m": float(np.max(d)),
        "median_div_m": float(np.median(d)),
        "endpoint_div_m": float(d[-1]),
        "path_len_baseline_m": length_a,
        "path_len_oracle_m": length_b,
        "n_points_a": len(pts_a),
        "n_points_b": len(pts_b),
    }

results_outbound = []
results_return = []
missing = []

for eid in common_ids:
    brow = baseline_by_id[eid]
    orow = oracle_by_id[eid]
    b_idx = int(brow["episode_idx"])
    o_idx = int(orow["episode_idx"])
    bp = traj_path("pure_baseline_highsuccess100ep_chronological_first50_20260818", b_idx, eid)
    op = traj_path("pure_oracle_hint_highsuccess100ep_20260811", o_idx, eid)
    bph = load_phase_positions(bp)
    oph = load_phase_positions(op)
    if bph is None or oph is None:
        missing.append((eid, "traj file missing", bp if bph is None else op))
        continue

    # outbound
    if len(bph["outbound"]) >= 2 and len(oph["outbound"]) >= 2:
        r = path_divergence(bph["outbound"], oph["outbound"])
        if r:
            r["episode_id"] = eid
            r["baseline_outbound_success"] = brow["outbound_success"]
            r["oracle_outbound_success"] = orow["outbound_success"]
            results_outbound.append(r)
    else:
        missing.append((eid, "outbound too short", f"b={len(bph['outbound'])} o={len(oph['outbound'])}"))

    # return
    if len(bph["return"]) >= 2 and len(oph["return"]) >= 2:
        r = path_divergence(bph["return"], oph["return"])
        if r:
            r["episode_id"] = eid
            r["baseline_return_success"] = brow["return_success"]
            r["oracle_return_success"] = orow["return_success"]
            results_return.append(r)
    else:
        missing.append((eid, "return too short", f"b={len(bph['return'])} o={len(oph['return'])}"))

print(f"\nOutbound comparisons: {len(results_outbound)} episodes")
print(f"Return comparisons: {len(results_return)} episodes")
print(f"Missing/skipped: {len(missing)}")
for m in missing[:20]:
    print("  skip:", m)

def summarize(results, label):
    if not results:
        print(f"{label}: no data")
        return
    means = np.array([r["mean_div_m"] for r in results])
    maxs = np.array([r["max_div_m"] for r in results])
    endpoints = np.array([r["endpoint_div_m"] for r in results])
    print(f"\n=== {label} (n={len(results)}) ===")
    print(f"  mean-of-per-episode-mean-divergence: {means.mean():.3f} m")
    print(f"  median-of-per-episode-mean-divergence: {np.median(means):.3f} m")
    print(f"  std: {means.std():.3f} m")
    print(f"  min/max per-episode mean-div: {means.min():.3f} / {means.max():.3f} m")
    print(f"  mean of per-episode MAX divergence: {maxs.mean():.3f} m")
    print(f"  mean endpoint (final-position) divergence: {endpoints.mean():.3f} m")

summarize(results_outbound, "OUTBOUND divergence (baseline vs oracle_hint, same episodes)")
summarize(results_return, "RETURN divergence (baseline vs oracle_hint, same episodes)")

# Save detailed CSV
import csv as csvmod
with open("/tmp/claude-1006/-home-teambruce/659d4e63-016b-46aa-a801-390b26e3e0da/scratchpad/outbound_divergence.csv", "w", newline="") as f:
    if results_outbound:
        w = csvmod.DictWriter(f, fieldnames=list(results_outbound[0].keys()))
        w.writeheader()
        w.writerows(results_outbound)

with open("/tmp/claude-1006/-home-teambruce/659d4e63-016b-46aa-a801-390b26e3e0da/scratchpad/return_divergence.csv", "w", newline="") as f:
    if results_return:
        w = csvmod.DictWriter(f, fieldnames=list(results_return[0].keys()))
        w.writeheader()
        w.writerows(results_return)

print("\nSaved detail CSVs to scratchpad.")

print("\n=== RETURN divergence broken down by (baseline_return_success, oracle_return_success) ===")
from collections import defaultdict
groups = defaultdict(list)
for r in results_return:
    key = (r["baseline_return_success"], r["oracle_return_success"])
    groups[key].append(r["mean_div_m"])
for key in sorted(groups):
    vals = np.array(groups[key])
    print(f"  baseline_ret={key[0]:5s} oracle_ret={key[1]:5s}  n={len(vals):2d}  mean={vals.mean():.3f}m  median={np.median(vals):.3f}m")

print("\n=== per-episode outbound table (episode_id: mean_div, max_div) sorted desc ===")
for r in sorted(results_outbound, key=lambda x: -x["mean_div_m"])[:10]:
    print(f"  ep{r['episode_id']:>5}: mean={r['mean_div_m']:.3f}m max={r['max_div_m']:.3f}m")

print("\n=== per-episode return table (episode_id: mean_div, max_div) sorted desc ===")
for r in sorted(results_return, key=lambda x: -x["mean_div_m"])[:10]:
    print(f"  ep{r['episode_id']:>5}: mean={r['mean_div_m']:.3f}m max={r['max_div_m']:.3f}m base_ret={r['baseline_return_success']} oracle_ret={r['oracle_return_success']}")
