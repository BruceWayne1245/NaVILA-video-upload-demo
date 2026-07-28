"""
Build a labeled dataset for a promotion/quarantine/wait decision controller.

For every episode with saved covisibility_records + ground-truth anchors.json + trajectory,
reconstruct current/next dwell sequences (grouping covisibility_records by attempt, taking
the two highest anchor_index values present as current/next), compute ground-truth
anchor_true_dist at each attempt (robot's true position vs. the candidate anchor's true
world position), and emit one row per (dwell, attempt) with:
  - causal-only raw + rolling features (current AND next role diagnostics)
  - a hindsight label: promote / quarantine / wait

Output: dwell_dataset.csv
"""
import json, os, glob, collections, math, csv, re, sys

BASE = "/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/eval_results"
OUT_CSV = "/tmp/claude-1006/-home-teambruce/1ae76ef4-cb03-4f21-9238-d1d566650215/scratchpad/dwell_dataset.csv"

CLOSE_THRESH_M = 0.75  # matches promotion_close_radius_m in route_memory_agent.py

FEATURE_FIELDS_RAW = [
    "confidence", "inlier_count", "icp_best_to_second_score_ratio",
    "icp_near_tie_basin_count", "overlap_ratio", "corridor_degeneracy_ratio",
    "mean_residual_m", "median_residual_m", "estimated_distance_to_anchor_m",
]
MATCH_CLASSES = ["clean_full_pose", "ambiguous_high_confidence", "partial_pose_degenerate"]

ZSTATS = {
    "inlier_count": (288.5561, 113.2020),
    "best_to_second_score_ratio": (0.7142, 0.2353),
    "near_tie_basin_count": (0.8686, 1.3620),
    "confidence": (0.7448, 0.2309),
}
def zz(key, v):
    m, s = ZSTATS[key]
    return (float(v) - m) / (s if s else 1.0)

def U_score(rec):
    inl = rec.get('inlier_count'); ratio = rec.get('icp_best_to_second_score_ratio')
    nt = rec.get('icp_near_tie_basin_count'); conf = rec.get('confidence')
    if inl is None or ratio is None or nt is None or conf is None:
        return None
    return -zz("inlier_count", inl) + zz("best_to_second_score_ratio", ratio) + zz("near_tie_basin_count", nt) - zz("confidence", conf)

def dist2(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])

def raw_feats(rec, prefix):
    out = {}
    for f in FEATURE_FIELDS_RAW:
        out[f"{prefix}_{f}"] = rec.get(f) if rec else None
    mc = rec.get("match_class") if rec else None
    for mcname in MATCH_CLASSES:
        out[f"{prefix}_match_{mcname}"] = 1.0 if mc == mcname else 0.0
    out[f"{prefix}_U"] = U_score(rec) if rec else None
    return out

def process_episode(ep_dir):
    anchors_path = os.path.join(ep_dir, "icp_replay_dataset", "anchors.json")
    meas_files = glob.glob(os.path.join(ep_dir, "measurements", "*.json"))
    if not os.path.exists(anchors_path) or not meas_files:
        return []
    with open(anchors_path) as f:
        anchors = {a['index']: a for a in json.load(f)['anchors']}
    with open(meas_files[0]) as f:
        meas = json.load(f)
    rt = meas.get('round_trip', {})
    diag = rt.get('route_relocalization_diagnostics') or {}
    recs = diag.get('covisibility_records') or []
    if not recs:
        return []
    traj_file = rt.get('trajectory_file')
    if not traj_file:
        return []
    traj_path = os.path.join(ep_dir, traj_file)
    if not os.path.exists(traj_path):
        return []

    # load return-phase trajectory positions keyed by step
    return_steps = []
    with open(traj_path) as f:
        for line in f:
            rec = json.loads(line)
            if rec.get('phase') == 'return':
                return_steps.append((rec['step'], rec['position'][:2]))
    if not return_steps:
        return []
    first_step, last_step = return_steps[0][0], return_steps[-1][0]

    def true_pos_at_step(step):
        # nearest by binary-search-ish linear scan (return_steps sorted by step)
        lo, hi = 0, len(return_steps) - 1
        while lo < hi:
            mid = (lo + hi) // 2
            if return_steps[mid][0] < step:
                lo = mid + 1
            else:
                hi = mid
        return return_steps[lo][1]

    by_attempt = collections.OrderedDict()
    for r in recs:
        by_attempt.setdefault(r['attempt'], []).append(r)
    n_attempts = len(by_attempt)
    if n_attempts < 2:
        return []

    items = list(by_attempt.items())

    def approx_step(attempt):
        return first_step + (attempt / n_attempts) * (last_step - first_step)

    def anchor_true_dist(anchor_idx, attempt):
        if anchor_idx not in anchors:
            return None
        step = approx_step(attempt)
        pos = true_pos_at_step(step)
        return dist2(pos, anchors[anchor_idx]['world_pose'][:2])

    # --- pass 1: reconstruct current/next per attempt, split into dwell segments (by next index) ---
    dwells = []  # list of dicts: {anchor_idx, attempts: [(attempt, cur_rec, next_rec, gt_dist)]}
    cur_dwell = None
    for attempt, group in items:
        by_idx = {g['anchor_index']: g for g in group}
        idxs = sorted(by_idx.keys(), reverse=True)
        if not idxs:
            continue
        cur_idx = idxs[0]
        next_idx = idxs[1] if len(idxs) > 1 else None
        if next_idx is None:
            continue
        next_rec = by_idx.get(next_idx)
        cur_rec = by_idx.get(cur_idx)
        gt = anchor_true_dist(next_idx, attempt)
        if cur_dwell is None or cur_dwell['anchor_idx'] != next_idx:
            if cur_dwell is not None:
                dwells.append(cur_dwell)
            cur_dwell = {'anchor_idx': next_idx, 'attempts': []}
        cur_dwell['attempts'].append((attempt, cur_rec, next_rec, gt))
    if cur_dwell is not None:
        dwells.append(cur_dwell)

    # --- pass 2: for each dwell, decide terminal type (resolved by promote/quarantine, or ran off the end of the episode) ---
    rows = []
    scene_tag = os.path.basename(ep_dir)
    for di, dw in enumerate(dwells):
        atts = dw['attempts']
        is_last_dwell = (di == len(dwells) - 1)
        # ever-close-in-hindsight (within this whole dwell window)
        any_close = any(gt is not None and gt <= CLOSE_THRESH_M for (_a, _c, _n, gt) in atts)

        current_reliability_hist = []  # for rolling "current persistently unreliable" feature
        dist_hist = []
        conf_hist = []
        ratio_hist = []

        for i, (attempt, cur_rec, next_rec, gt) in enumerate(atts):
            if next_rec is None or gt is None:
                continue
            # rolling causal features BEFORE including this attempt's own next-role reading in "history" stats
            n_so_far = i  # attempts strictly before this one, in this dwell
            feat = {
                'episode': scene_tag,
                'dwell_id': f"{scene_tag}__d{di}",
                'anchor_idx': dw['anchor_idx'],
                'attempt': attempt,
                'attempt_in_dwell': i,
                'n_prior_in_dwell': n_so_far,
            }
            feat.update(raw_feats(next_rec, 'next'))
            feat.update(raw_feats(cur_rec, 'cur'))
            # current reliability rolling (mirrors _current_persistently_unreliable, causal)
            cu = U_score(cur_rec) if cur_rec else None
            if cu is not None:
                current_reliability_hist.append(cu)
            hist_for_frac = current_reliability_hist[:-1] if cu is not None else current_reliability_hist
            feat['cur_bad_fraction_hist'] = (
                sum(1 for u in hist_for_frac if u >= 2.5) / len(hist_for_frac) if len(hist_for_frac) >= 3 else None
            )
            # dwell rolling stats over PRIOR attempts only (causal)
            def roll_stat(hist):
                if len(hist) == 0:
                    return None, None
                m = sum(hist) / len(hist)
                if len(hist) < 2:
                    return m, 0.0
                var = sum((x - m) ** 2 for x in hist) / len(hist)
                return m, math.sqrt(var)
            d_mean, d_std = roll_stat(dist_hist)
            c_mean, c_std = roll_stat(conf_hist)
            r_mean, r_std = roll_stat(ratio_hist)
            feat['next_dist_rollmean'] = d_mean
            feat['next_dist_rollstd'] = d_std
            feat['next_conf_rollmean'] = c_mean
            feat['next_conf_rollstd'] = c_std
            feat['next_ratio_rollmean'] = r_mean
            feat['next_ratio_rollstd'] = r_std

            # update history AFTER computing rolling (causal)
            dv = next_rec.get('estimated_distance_to_anchor_m')
            if dv is not None:
                dist_hist.append(dv)
            cv = next_rec.get('confidence')
            if cv is not None:
                conf_hist.append(cv)
            rv = next_rec.get('icp_best_to_second_score_ratio')
            if rv is not None:
                ratio_hist.append(rv)

            # --- label ---
            is_last_attempt_in_dwell = (i == len(atts) - 1)
            if gt <= CLOSE_THRESH_M:
                label = 'promote'
            elif is_last_attempt_in_dwell and not is_last_dwell and not any_close:
                # dwell resolved via a real transition (not episode end) and NEVER got close -> legit quarantine
                label = 'quarantine'
            else:
                label = 'wait'
            feat['label'] = label
            feat['gt_anchor_true_dist'] = gt
            feat['dwell_is_episode_tail'] = int(is_last_dwell)
            rows.append(feat)
    return rows


def main():
    anchor_dirs = glob.glob(f"{BASE}/*/icp_replay_dataset/anchors.json")
    ep_dirs = sorted(set(os.path.dirname(os.path.dirname(p)) for p in anchor_dirs))
    print(f"{len(ep_dirs)} candidate episode dirs")

    all_rows = []
    n_ok, n_err, n_empty = 0, 0, 0
    for i, ep_dir in enumerate(ep_dirs):
        try:
            rows = process_episode(ep_dir)
            if rows:
                all_rows.extend(rows)
                n_ok += 1
            else:
                n_empty += 1
        except Exception as e:
            n_err += 1
        if (i + 1) % 50 == 0:
            print(f"  processed {i+1}/{len(ep_dirs)} dirs, rows so far={len(all_rows)}", flush=True)

    print(f"episodes ok={n_ok} empty={n_empty} err={n_err}")
    print(f"total rows={len(all_rows)}")

    if not all_rows:
        print("NO ROWS -- aborting")
        sys.exit(1)

    fieldnames = sorted(set().union(*[r.keys() for r in all_rows]))
    with open(OUT_CSV, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in all_rows:
            w.writerow(r)
    print(f"wrote {OUT_CSV}")

    from collections import Counter
    print("label distribution:", Counter(r['label'] for r in all_rows))

if __name__ == '__main__':
    main()
