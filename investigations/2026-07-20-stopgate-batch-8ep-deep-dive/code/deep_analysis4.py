import json, math
from collections import Counter
from deep_analysis import EPISODES, load_traj, build_outbound_curve, pos_for_distance
from deep_analysis2 import body_frame_bearing_distance, wrap180

def classify_action(text):
    if text is None:
        return 'none'
    t = text.lower()
    if 'forward' in t:
        return 'forward'
    if 'right' in t:
        return 'right'
    if 'left' in t:
        return 'left'
    if 'stop' in t:
        return 'stop'
    return 'other'

def classify_bearing(bearing_deg, fwd_thresh=20.0):
    if abs(bearing_deg) <= fwd_thresh:
        return 'forward'
    return 'right' if bearing_deg < 0 else 'left'

def item2_arbiter(ep):
    mpath, tpath = EPISODES[ep]
    d = json.load(open(mpath))
    rt = d['round_trip']
    traj = load_traj(tpath)
    traj_by_step = {r['step']: r for r in traj}
    curve = build_outbound_curve(traj)
    recs = rt['route_relocalization_diagnostics']['covisibility_records']
    anchor_dist = {r['anchor_index']: r['anchor_distance_from_start_m'] for r in recs}
    anchor_true_pos = {idx: pos_for_distance(curve, dist) for idx, dist in anchor_dist.items()}

    pe = rt['phase_events']
    events = [e for e in pe if e.get('event')=='hint_action_arbiter']
    n_forced = 0
    n_gated = 0
    n_noop = 0
    forced_correct = 0
    gated_executed_correct = 0
    gated_should_have_overridden = 0
    rows = []
    for e in events:
        step = e['step']
        if step not in traj_by_step:
            continue
        tr = traj_by_step[step]
        rx, ry, ryaw = tr['position'][0], tr['position'][1], tr['yaw_rad']
        idx = e.get('target_anchor_index')
        if idx not in anchor_true_pos:
            continue
        tx, ty = anchor_true_pos[idx]
        true_bear, true_dist = body_frame_bearing_distance(rx, ry, ryaw, tx, ty)
        true_cat = classify_bearing(true_bear)

        orig_cat = classify_action(e.get('original_output'))
        override = e.get('override')
        reason = e.get('reason')

        if override:
            n_forced += 1
            exec_cat = classify_action(e.get('replacement_output'))
            correct = (exec_cat == true_cat)
            if correct: forced_correct += 1
            rows.append(dict(step=step, kind='forced', reason=reason, orig=orig_cat, exec=exec_cat,
                              true_cat=true_cat, true_bear=true_bear, correct=correct))
        elif reason in ('low_relocalization_confidence', 'occupied_in_local_map_path') and orig_cat != e.get('desired_kind'):
            n_gated += 1
            exec_cat = orig_cat  # gate declined, VLM's own action executes
            correct = (exec_cat == true_cat)
            if correct: gated_executed_correct += 1
            desired_cat = e.get('desired_kind')
            should_have = (desired_cat == true_cat) and not correct
            if should_have: gated_should_have_overridden += 1
            rows.append(dict(step=step, kind='gated', reason=reason, orig=orig_cat, exec=exec_cat,
                              desired=desired_cat, true_cat=true_cat, true_bear=true_bear, correct=correct,
                              should_have_overridden=should_have))
        else:
            n_noop += 1
    return dict(n_forced=n_forced, forced_correct=forced_correct,
                n_gated=n_gated, gated_executed_correct=gated_executed_correct,
                gated_should_have_overridden=gated_should_have_overridden,
                n_noop=n_noop, rows=rows)

def item4_stopgate(ep):
    mpath, tpath = EPISODES[ep]
    d = json.load(open(mpath))
    rt = d['round_trip']
    traj = load_traj(tpath)
    traj_by_step = {r['step']: r for r in traj}
    pe = rt['phase_events']
    gate_events = [e for e in pe if e.get('event')=='stop_gate']
    vlm_by_step = {}
    for e in pe:
        if e.get('event')=='vlm_command' and e.get('phase')=='return':
            vlm_by_step[e['step']] = e.get('output')
    decisions = Counter(e['gate_decision'] for e in gate_events)
    final = gate_events[-1] if gate_events else None
    final_true_dist = None
    if final:
        step = final['step']
        if step in traj_by_step:
            # true distance to start = true position at step 0 (outbound start) vs this step
            start_pos = traj[0]['position'][:2]
            p = traj_by_step[step]['position'][:2]
            final_true_dist = math.hypot(p[0]-start_pos[0], p[1]-start_pos[1])
    return dict(decisions=dict(decisions), final=final, final_true_dist=final_true_dist,
                n_events=len(gate_events))

if __name__ == "__main__":
    for ep in EPISODES:
        r2 = item2_arbiter(ep)
        r4 = item4_stopgate(ep)
        print(f"ep{ep}: hint_action forced={r2['n_forced']}(correct={r2['forced_correct']})  "
              f"gated={r2['n_gated']}(executed_correct={r2['gated_executed_correct']}, "
              f"should_have_overridden={r2['gated_should_have_overridden']})  noop={r2['n_noop']}")
        print(f"       stop_gate decisions={r4['decisions']} final_true_dist={r4['final_true_dist']}")
