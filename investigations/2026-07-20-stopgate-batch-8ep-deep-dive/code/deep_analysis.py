import json, math, sys
from collections import Counter, defaultdict

CONTROL_DT = 0.02

EPISODES = {
 "4":   ("/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/eval_results/round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_canonical_report_next_stopgate_50ep_20260719_accumulated_ep4/measurements/7.json",
         "/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/eval_results/round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_canonical_report_next_stopgate_50ep_20260719_accumulated_ep4/trajectories/output_7.jsonl"),
 "367": ("/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/eval_results/round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_canonical_report_next_stopgate_50ep_20260719_accumulated_ep367/measurements/601.json",
         "/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/eval_results/round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_canonical_report_next_stopgate_50ep_20260719_accumulated_ep367/trajectories/output_601.jsonl"),
 "680": ("/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/eval_results/round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_canonical_report_next_stopgate_50ep_20260719_accumulated_ep680/measurements/1166.json",
         "/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/eval_results/round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_canonical_report_next_stopgate_50ep_20260719_accumulated_ep680/trajectories/output_1166.jsonl"),
 "1040":("/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/eval_results/round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_canonical_report_next_stopgate_50ep_20260719_accumulated_ep1040/measurements/1760.json",
         "/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/eval_results/round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_canonical_report_next_stopgate_50ep_20260719_accumulated_ep1040/trajectories/output_1760.jsonl"),
 "647": ("/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/eval_results/round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_canonical_report_next_stopgate_50ep_20260719_accumulated_ep647/measurements/1118.json",
         "/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/eval_results/round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_canonical_report_next_stopgate_50ep_20260719_accumulated_ep647/trajectories/output_1118.jsonl"),
 "295": ("/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/eval_results/round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_canonical_report_next_stopgate_50ep_20260719_accumulated_ep295/measurements/475.json",
         "/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/eval_results/round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_canonical_report_next_stopgate_50ep_20260719_accumulated_ep295/trajectories/output_475.jsonl"),
 "268": ("/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/eval_results/round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_canonical_report_next_stopgate_50ep_20260719_accumulated_ep268/measurements/421.json",
         "/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/eval_results/round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_canonical_report_next_stopgate_50ep_20260719_accumulated_ep268/trajectories/output_421.jsonl"),
}

def load_traj(path):
    recs = []
    with open(path) as f:
        for line in f:
            recs.append(json.loads(line))
    recs.sort(key=lambda r: r['step'])
    return recs

def build_outbound_curve(traj):
    ob = [r for r in traj if r['phase']=='outbound']
    cum = 0.0
    curve = []  # list of (cum_dist, x, y, yaw, step)
    for r in ob:
        vx, vy, wz = r['command']
        step_dist = math.hypot(vx, vy) * CONTROL_DT
        cum += step_dist
        curve.append((cum, r['position'][0], r['position'][1], r['yaw_rad'], r['step']))
    return curve

def pos_for_distance(curve, target_dist):
    if target_dist <= curve[0][0]:
        return curve[0][1], curve[0][2]
    for i in range(1, len(curve)):
        if curve[i][0] >= target_dist:
            d0,x0,y0,_,_ = curve[i-1]
            d1,x1,y1,_,_ = curve[i]
            if d1 == d0:
                return x1,y1
            t = (target_dist-d0)/(d1-d0)
            return x0+t*(x1-x0), y0+t*(y1-y0)
    return curve[-1][1], curve[-1][2]

def pose_for_distance(curve, target_dist):
    """Return [x, y, yaw] at a given cumulative-commanded-distance along outbound."""
    if target_dist <= curve[0][0]:
        return [curve[0][1], curve[0][2], curve[0][3]]
    for i in range(1, len(curve)):
        if curve[i][0] >= target_dist:
            d0,x0,y0,yaw0,_ = curve[i-1]
            d1,x1,y1,yaw1,_ = curve[i]
            if d1 == d0:
                return [x1,y1,yaw1]
            t = (target_dist-d0)/(d1-d0)
            # yaw: just take nearer sample's yaw (steps are 0.02s apart, negligible diff)
            yaw = yaw0 if t < 0.5 else yaw1
            return [x0+t*(x1-x0), y0+t*(y1-y0), yaw]
    return [curve[-1][1], curve[-1][2], curve[-1][3]]

def nearest_s_for_point(curve, x, y, stride=1):
    best_d = None; best_s = None
    for i in range(0, len(curve), stride):
        d,cx,cy,_,_ = curve[i]
        dist2 = (cx-x)**2 + (cy-y)**2
        if best_d is None or dist2 < best_d:
            best_d = dist2; best_s = d
    return best_s, math.sqrt(best_d)

if __name__ == "__main__":
    ep = sys.argv[1] if len(sys.argv)>1 else "4"
    mpath, tpath = EPISODES[ep]
    d = json.load(open(mpath))
    rt = d['round_trip']
    traj = load_traj(tpath)
    curve = build_outbound_curve(traj)
    print(f"ep{ep}: outbound curve points={len(curve)}, total commanded dist={curve[-1][0]:.3f}m")
    # sanity: anchor0 should be near start (position of first outbound step)
    print("outbound start true pos:", traj[0]['position'][:2])
    print("outbound end true pos (should be near outbound goal):", curve[-1][1], curve[-1][2])
    # gather anchor distances seen in covisibility_records
    recs = rt['route_relocalization_diagnostics']['covisibility_records']
    anchor_dists = {}
    for r in recs:
        anchor_dists[r['anchor_index']] = r['anchor_distance_from_start_m']
    for idx in sorted(anchor_dists):
        x,y = pos_for_distance(curve, anchor_dists[idx])
        print(f"  anchor {idx}: dist_from_start={anchor_dists[idx]:.3f}m -> true_pos=({x:.3f},{y:.3f})")
