import glob, re, os, json

RUN_DIR = "/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/batch_logs/pure_oracle_hint_action_highsuccess100ep_20260812"
EVAL_RESULTS = "/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/eval_results"
PREFIX = "round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_pure_oracle_hint_action_highsuccess100ep_20260812_ep"

arbiter_re = re.compile(r"\[hint_arbiter\] step=(\d+) override=(\w+) reason=(\S+)")

all_dists = []
missing = 0
for logf in sorted(glob.glob(f"{RUN_DIR}/ep*_eval.log")):
    ep = re.search(r"ep(\d+)_eval\.log", logf).group(1)
    steps = []
    for line in open(logf, errors="replace"):
        m = arbiter_re.search(line)
        if m and m.group(3) == "target_too_close":
            steps.append(int(m.group(1)))
    if not steps:
        continue
    ep_dir = f"{EVAL_RESULTS}/{PREFIX}{ep}"
    traj_files = glob.glob(f"{ep_dir}/trajectories/*.jsonl")
    if not traj_files:
        missing += len(steps)
        continue
    traj_by_step = {}
    for line in open(traj_files[0]):
        d = json.loads(line)
        traj_by_step[d.get("step")] = d
    for s in steps:
        d = traj_by_step.get(s)
        if d is None:
            missing += 1
            continue
        rm = d.get("route_memory") or {}
        dist = rm.get("distance_to_anchor_m")
        if dist is not None:
            all_dists.append((ep, s, dist))
        else:
            missing += 1

print(f"target_too_close decisions matched to a distance_to_anchor_m value: {len(all_dists)}  (missing/unmatched: {missing})")
if all_dists:
    vals = [d for _,_,d in all_dists]
    print(f"max={max(vals):.5f}  min={min(vals):.5f}")
    top5 = sorted(all_dists, key=lambda x: -x[2])[:5]
    print("top 5 largest distance_to_anchor_m among target_too_close decisions:")
    for ep,s,d in top5:
        print(f"  ep{ep} step={s} distance_to_anchor_m={d:.5f}")
    n_over_threshold = sum(1 for v in vals if v >= 0.35)
    print(f"\ncode threshold min_anchor_distance_m=0.35m; decisions with distance>=0.35 (would violate the code's own threshold): {n_over_threshold}")
