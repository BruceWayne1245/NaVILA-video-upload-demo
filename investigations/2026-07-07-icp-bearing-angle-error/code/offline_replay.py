"""Offline replay harness: re-runs the sequential_pair two-anchor relocalization
+ promotion logic against a --capture_icp_replay_dataset capture, with no Isaac
Sim / VLM server needed. Used to A/B "immediate" vs "bounded_evidence"
promotion modes on already-captured point clouds.
"""
import json
import math
import os
import sys

SCRIPTS_DIR = "/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/scripts"
sys.path.insert(0, SCRIPTS_DIR)

import numpy as np  # noqa: E402
from relocalization import sequential_pair_anchor_relocalization  # noqa: E402
from route_memory_agent import RouteAnchor, RouteMemoryAgent  # noqa: E402

BASE = "/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/eval_results"


def find_capture_dir(batch_suffix, ep):
    dirname = f"round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_{batch_suffix}_ep{ep}"
    d = os.path.join(BASE, dirname, "icp_replay_dataset")
    return d if os.path.isdir(d) else None


def load_anchors(capture_dir):
    data = json.load(open(os.path.join(capture_dir, "anchors.json")))
    anchors = []
    for a in data["anchors"]:
        pts = a.get("local_map_points_xyz_body")
        descriptor = {"local_map_points_body": np.asarray(pts, dtype=np.float32)} if pts else None
        anchors.append(RouteAnchor(
            index=int(a["index"]),
            pose_from_start=[0.0, 0.0, 0.0],
            distance_from_start_m=float(a["distance_from_start_m"]),
            descriptor=descriptor,
            metadata={"world_pose": a.get("world_pose")},
        ))
    anchors.sort(key=lambda a: a.index)
    return anchors


def load_steps(capture_dir):
    """Skips individually corrupted per-step capture files (the same
    intermittent spliced/missing-structure JSON defect already documented for
    --capture_anchor_match_snapshots -- confirmed here to also affect
    --capture_icp_replay_dataset's per-step frames in a small minority of
    files) rather than failing the whole episode over one bad frame."""
    steps_dir = os.path.join(capture_dir, "steps")
    files = sorted(os.listdir(steps_dir))
    steps = []
    skipped = []
    for fname in files:
        try:
            d = json.load(open(os.path.join(steps_dir, fname)))
        except json.JSONDecodeError:
            skipped.append(fname)
            continue
        steps.append(d)
    if skipped:
        print(f"    [warning] {capture_dir}: skipped {len(skipped)} corrupted step file(s): {skipped}",
              flush=True)
    steps.sort(key=lambda d: d["step"])
    return steps


def attempt_schedule(num_steps, interval):
    """Same schedule as the live relocalization_interval_updates gate: attempt
    1 at step-index 0, then every `interval`-th step after."""
    idx = 0
    attempt = 1
    schedule = []
    while idx < num_steps:
        schedule.append((attempt, idx))
        attempt += 1
        idx += interval
    return schedule


def make_agent(promotion_mode, anchors, interval=5, promotion_window=5, promotion_min_votes=3,
                alias_aware=False, alias_threshold=0.6, alias_window=8, alias_min_votes=5,
                alias_stall_attempts=200):
    agent = RouteMemoryAgent(
        enabled=True,
        anchor_spacing_m=1.0,
        relocalization_interval_updates=interval,
        sequential_pair_geometry_source="oracle",  # accumulated edge_from_previous isn't in the capture
        sequential_pair_closure_check_enabled=True,
        sequential_pair_closure_mode="belief",
        sequential_pair_quarantine_enabled=True,
        sequential_pair_quarantine_mode="trend",
        sequential_pair_promotion_mode=promotion_mode,
        sequential_pair_promotion_window=promotion_window,
        sequential_pair_promotion_min_votes=promotion_min_votes,
        sequential_pair_promotion_alias_aware=alias_aware,
        sequential_pair_promotion_alias_threshold=alias_threshold,
        sequential_pair_promotion_alias_window=alias_window,
        sequential_pair_promotion_alias_min_votes=alias_min_votes,
        sequential_pair_promotion_alias_stall_attempts=alias_stall_attempts,
    )
    agent.anchors = anchors
    agent._target_anchor_index = max(a.index for a in anchors)
    agent._return_started = True
    if alias_aware:
        agent.compute_anchor_alias_scores()
    return agent


def true_xy(world_pose):
    return world_pose[0], world_pose[1]


def dist(p1, p2):
    return math.hypot(p1[0] - p2[0], p1[1] - p2[1])


def pose_yaw(pose):
    q0, q1, q2, q3 = pose[3], pose[4], pose[5], pose[6]  # wxyz, matches round_trip_eval.py's quat2eulers
    return math.atan2(2 * (q1 * q2 + q0 * q3), q0**2 + q1**2 - q2**2 - q3**2)


def wrap_angle(a):
    return math.atan2(math.sin(a), math.cos(a))


def true_relative_pose(robot_pose, anchor_xy):
    """True (distance_m, bearing_deg) from the robot's true pose to anchor_xy,
    in the robot's own body frame -- directly comparable to an
    AnchorRelocalization estimate's own distance_to_anchor_m/bearing_to_anchor_deg."""
    rx, ry = robot_pose[0], robot_pose[1]
    yaw = pose_yaw(robot_pose)
    dx_world = anchor_xy[0] - rx
    dy_world = anchor_xy[1] - ry
    distance = math.hypot(dx_world, dy_world)
    bearing_world = math.atan2(dy_world, dx_world)
    bearing_body = wrap_angle(bearing_world - yaw)
    return distance, math.degrees(bearing_body)


def replay_episode(batch_suffix, ep, promotion_mode, interval=5, icp_objective="point_to_point",
                    promotion_window=5, promotion_min_votes=3, max_attempts=None,
                    alias_aware=False, alias_threshold=0.6, alias_window=8, alias_min_votes=5):
    capture_dir = find_capture_dir(batch_suffix, ep)
    if capture_dir is None:
        return None
    try:
        anchors = load_anchors(capture_dir)
    except json.JSONDecodeError:
        print(f"    [warning] ep{ep}: anchors.json is corrupted -- episode unusable offline, skipping", flush=True)
        return None
    anchors_by_index = {a.index: a for a in anchors}
    steps = load_steps(capture_dir)
    agent = make_agent(promotion_mode, anchors, interval=interval,
                        promotion_window=promotion_window, promotion_min_votes=promotion_min_votes,
                        alias_aware=alias_aware, alias_threshold=alias_threshold,
                        alias_window=alias_window, alias_min_votes=alias_min_votes)

    schedule = attempt_schedule(len(steps), interval)
    if max_attempts is not None:
        schedule = schedule[:max_attempts]
    results = []
    for attempt, idx in schedule:
        if attempt % 25 == 0:
            print(f"    [progress] ep{ep} mode={promotion_mode} attempt {attempt}/{len(schedule)}", flush=True)
        step = steps[idx]
        pts = step.get("local_map_points_xyz_body")
        if not pts:
            continue
        descriptor = {"local_map_points_body": np.asarray(pts, dtype=np.float32)}
        current_anchor, next_anchor = agent.sequential_target_anchor_pair()
        diagnostics = {}
        candidates = sequential_pair_anchor_relocalization(
            descriptor, current_anchor, next_anchor,
            diagnostics=diagnostics, return_candidates=True,
            icp_objective=icp_objective, voxel_size_m=0.10, max_points=512,
            quality_policy="diagnostic",
        )
        if candidates is None:
            candidates = []
        accepted = agent.update_relocalization(relocalization=candidates)
        target_idx = agent._target_anchor_index
        anchor = anchors_by_index.get(target_idx)
        true_dist = None
        true_bearing_deg = None
        reported_dist = None
        reported_bearing_deg = None
        if accepted is not None and anchor is not None and anchor.metadata.get("world_pose"):
            true_dist = dist(true_xy(anchor.metadata["world_pose"]), true_xy(step["robot_world_pose"]))
            true_dist_check, true_bearing_deg = true_relative_pose(
                step["robot_world_pose"], true_xy(anchor.metadata["world_pose"]))
            reported_dist = accepted.distance_to_anchor_m
            reported_bearing_deg = accepted.bearing_to_anchor_deg
        results.append(dict(
            attempt=attempt, step=step["step"], target_anchor_index=target_idx,
            accepted=accepted is not None, true_dist=true_dist, true_bearing_deg=true_bearing_deg,
            reported_dist=reported_dist, reported_bearing_deg=reported_bearing_deg,
        ))
    return results


def summarize(results, label):
    accepted = [r for r in results if r["accepted"]]
    seq = [(r["attempt"], r["target_anchor_index"]) for r in accepted]
    transitions = []
    prev = None
    for attempt, idx in seq:
        if idx != prev:
            transitions.append((attempt, idx))
            prev = idx
    tds = [r["true_dist"] for r in accepted if r["true_dist"] is not None]
    tds_sorted = sorted(tds)
    n = len(tds_sorted)
    print(f"--- {label} ---")
    print(f"  attempts={len(results)} accepted={len(accepted)} transitions={len(transitions)}")
    print(f"  transition schedule: {transitions}")
    if n:
        print(f"  true_dist: median={tds_sorted[n//2]:.3f}m mean={sum(tds)/n:.3f}m "
              f"max={max(tds):.3f}m frac>1m={sum(1 for t in tds if t>1.0)/n:.1%}")
    return transitions, tds


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--max_attempts", type=int, default=None)
    parser.add_argument("--episodes", type=int, nargs="+", default=[187, 5])
    args = parser.parse_args()

    batch = "icp_replay_capture_hard11_20260706_accumulated"
    for ep in args.episodes:
        print(f"\n{'='*70}\nEPISODE {ep}\n{'='*70}", flush=True)
        for mode in ["immediate", "bounded_evidence"]:
            results = replay_episode(batch, ep, promotion_mode=mode, max_attempts=args.max_attempts)
            if results is None:
                print(f"  ep{ep}: capture not found (not finished yet?)")
                continue
            summarize(results, f"ep{ep} mode={mode}")
