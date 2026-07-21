import json, math
from collections import Counter, defaultdict
from deep_analysis import EPISODES, load_traj, build_outbound_curve, pos_for_distance, pose_for_distance, nearest_s_for_point
from se2 import closure_precheck, wrap_angle

def wrap180(a):
    while a > 180: a -= 360
    while a < -180: a += 360
    return a

def body_frame_bearing_distance(robot_x, robot_y, robot_yaw, tx, ty):
    dxw = tx - robot_x
    dyw = ty - robot_y
    c, s = math.cos(robot_yaw), math.sin(robot_yaw)
    dxb = dxw*c + dyw*s
    dyb = -dxw*s + dyw*c
    bearing = math.degrees(math.atan2(dyb, dxb))
    dist = math.hypot(dxb, dyb)
    return bearing, dist

def analyze_episode(ep):
    mpath, tpath = EPISODES[ep]
    d = json.load(open(mpath))
    rt = d['round_trip']
    traj = load_traj(tpath)
    traj_by_step = {r['step']: r for r in traj}
    curve = build_outbound_curve(traj)

    recs = rt['route_relocalization_diagnostics']['covisibility_records']
    anchor_dist = {}
    for r in recs:
        anchor_dist[r['anchor_index']] = r['anchor_distance_from_start_m']
    anchor_true_pos = {idx: pos_for_distance(curve, dist) for idx, dist in anchor_dist.items()}
    anchor_true_pose = {idx: pose_for_distance(curve, dist) for idx, dist in anchor_dist.items()}
    sorted_anchor_idx = sorted(anchor_dist, key=lambda i: anchor_dist[i])

    return_steps_sorted = sorted(r['step'] for r in traj if r['phase']=='return')
    return_start = return_steps_sorted[0]

    by_attempt = defaultdict(list)
    for r in recs:
        by_attempt[r['attempt']].append(r)

    n_attempts = max(by_attempt)
    per_attempt = []
    icp_errors = []  # (distance_error_m, angle_error_deg) for every single-role record
    for att in range(1, n_attempts+1):
        step = return_start + (att-1)*5
        if step not in traj_by_step:
            continue
        tr = traj_by_step[step]
        rx, ry = tr['position'][0], tr['position'][1]
        ryaw = tr['yaw_rad']
        s_true, proj_err = nearest_s_for_point(curve, rx, ry, stride=1)

        pair = by_attempt.get(att, [])

        # ICP accuracy: every record in this attempt, vs its OWN claimed anchor's ground truth
        for r in pair:
            idx = r['anchor_index']
            if idx not in anchor_true_pos:
                continue
            tx, ty = anchor_true_pos[idx]
            true_bear, true_dist = body_frame_bearing_distance(rx, ry, ryaw, tx, ty)
            est_bear = r['estimated_bearing_to_anchor_deg']
            est_dist = r['estimated_distance_to_anchor_m']
            dist_err = abs(est_dist - true_dist)
            ang_err = abs(wrap180(est_bear - true_bear))
            icp_errors.append(dict(attempt=att, step=step, role_anchor=idx,
                                    dist_err=dist_err, ang_err=ang_err,
                                    match_class=r.get('match_class'), confidence=r.get('confidence')))

        if len(pair) != 2:
            continue
        pair_sorted = sorted(pair, key=lambda r: r['anchor_index'])
        next_rec, current_rec = pair_sorted[0], pair_sorted[1]  # lower idx = next, higher = current

        below_or_eq = [i for i in sorted_anchor_idx if anchor_dist[i] <= s_true]
        true_current_idx = below_or_eq[-1] if below_or_eq else sorted_anchor_idx[0]
        tc_pos = sorted_anchor_idx.index(true_current_idx)
        true_next_idx = sorted_anchor_idx[tc_pos-1] if tc_pos > 0 else true_current_idx

        rep_current_idx = current_rec['anchor_index']
        rep_next_idx = next_rec['anchor_index']

        def rank(idx):
            return sorted_anchor_idx.index(idx) if idx in sorted_anchor_idx else None

        cur_rank_true, cur_rank_rep = rank(true_current_idx), rank(rep_current_idx)
        next_rank_true, next_rank_rep = rank(true_next_idx), rank(rep_next_idx)
        current_anchor_offset = (cur_rank_rep - cur_rank_true) if None not in (cur_rank_rep, cur_rank_true) else None
        next_anchor_offset = (next_rank_rep - next_rank_true) if None not in (next_rank_rep, next_rank_true) else None
        current_dist_err_m = abs(anchor_dist[rep_current_idx] - anchor_dist[true_current_idx])
        next_dist_err_m = abs(anchor_dist[rep_next_idx] - anchor_dist[true_next_idx])

        # faithful closure-check replay using oracle anchor edges
        closure = None
        if rep_current_idx in anchor_true_pose and rep_next_idx in anchor_true_pose:
            try:
                closure = closure_precheck(anchor_true_pose, next_rec, current_rec)
            except Exception as e:
                closure = dict(action='error', err=str(e))

        per_attempt.append(dict(
            attempt=att, step=step, s_true=s_true, proj_err=proj_err,
            robot_true=(rx,ry,ryaw),
            true_current_idx=true_current_idx, true_next_idx=true_next_idx,
            rep_current_idx=rep_current_idx, rep_next_idx=rep_next_idx,
            current_anchor_offset=current_anchor_offset, next_anchor_offset=next_anchor_offset,
            current_dist_err_m=current_dist_err_m, next_dist_err_m=next_dist_err_m,
            current_rec=current_rec, next_rec=next_rec,
            closure=closure,
        ))
    return dict(rt=rt, traj=traj, traj_by_step=traj_by_step, curve=curve,
                anchor_dist=anchor_dist, anchor_true_pos=anchor_true_pos, anchor_true_pose=anchor_true_pose,
                sorted_anchor_idx=sorted_anchor_idx, per_attempt=per_attempt, icp_errors=icp_errors,
                return_start=return_start)

if __name__ == "__main__":
    import sys
    ep = sys.argv[1] if len(sys.argv)>1 else "4"
    data = analyze_episode(ep)
    pa = data['per_attempt']
    print(f"ep{ep}: n_attempts_with_pair={len(pa)}, n_icp_readings={len(data['icp_errors'])}")

    # item1 summary
    cur_off = [a['current_anchor_offset'] for a in pa if a['current_anchor_offset'] is not None]
    next_off = [a['next_anchor_offset'] for a in pa if a['next_anchor_offset'] is not None]
    def pct(lst, cond):
        return 100.0*sum(1 for x in lst if cond(x))/len(lst) if lst else float('nan')
    print(f"current anchor: exact={pct(cur_off, lambda x: x==0):.1f}% off1={pct(cur_off, lambda x: abs(x)==1):.1f}% off>=2={pct(cur_off, lambda x: abs(x)>=2):.1f}%")
    print(f"next anchor: exact={pct(next_off, lambda x: x==0):.1f}% off1={pct(next_off, lambda x: abs(x)==1):.1f}% off>=2={pct(next_off, lambda x: abs(x)>=2):.1f}%")
    cur_m = [a['current_dist_err_m'] for a in pa]
    next_m = [a['next_dist_err_m'] for a in pa]
    import statistics
    print(f"current meters-off: mean={statistics.mean(cur_m):.2f} median={statistics.median(cur_m):.2f}")
    print(f"next meters-off: mean={statistics.mean(next_m):.2f} median={statistics.median(next_m):.2f}")

    # item5 ICP accuracy
    de = [e['dist_err'] for e in data['icp_errors']]
    ae = [e['ang_err'] for e in data['icp_errors']]
    both = sum(1 for e in data['icp_errors'] if e['dist_err']<0.5 and e['ang_err']<30)
    ang10 = sum(1 for e in data['icp_errors'] if e['ang_err']<10)
    n = len(data['icp_errors'])
    print(f"ICP: dist<0.5m & ang<30deg = {100*both/n:.1f}%  |  ang<10deg = {100*ang10/n:.1f}%  (n={n})")

    # item3 closure actions
    actions = Counter(a['closure']['action'] for a in pa if a['closure'])
    print("closure actions:", dict(actions))
