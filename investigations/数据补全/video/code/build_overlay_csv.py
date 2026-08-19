#!/usr/bin/env python3
"""Build per-frame overlay CSVs for the supplementary video (Phase 3 of
investigations/数据补全/video_production_spec.md).

Source of truth is the per-control-step trajectory log written by
round_trip_eval.py at ``trajectories/output_<id>.jsonl`` inside each run's
eval_results directory -- one JSON object per control step, with row index
== step (confirmed empirically for every clip below). This is far more
robust than regex-scraping the eval logs, since stop_gate / hint_action_arbiter
/ route_memory state is already structured per step.

Video frames are captured every ~5 control steps (steps_per_viz_image =
0.1s / (sim.dt=0.005 * decimation=4) = 5, at fps=10). The exact stride is
recomputed per clip from n_steps / n_frames (via ffprobe) rather than
hardcoded, in case any clip deviates.
"""
import csv
import json
import os
import subprocess
import sys

BENCH = "/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench"
REPO = "/mnt/SSD4T/teambruce/projects/NaVILA-video-upload-demo"
OUT_DIR = os.path.join(REPO, "investigations/数据补全/video/overlay_data")

RESULT_DIR_TMPL = (
    "round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_{tag}_ep{idx}"
)

# (output_csv_name, tag, idx, trajectory_jsonl_basename, video_basename)
CLIPS = [
    ("ep1006_baseline.csv", "pure_baseline_highsuccess100ep_chronological_first50_20260818", 579, "output_1005.jsonl", "output_1005.mp4"),
    ("ep1006_online.csv", "policy_v2_active50_replay_on_highsuccess100ep_20260816", 579, "output_1005.jsonl", "output_1005.mp4"),
    ("ep1256_oracle_hint.csv", "pure_oracle_hint_highsuccess100ep_20260811", 733, "output_1255.jsonl", "output_1255.mp4"),
    ("ep1256_oracle_hint_action.csv", "pure_oracle_hint_action_highsuccess100ep_20260812", 733, "output_1255.jsonl", "output_1255.mp4"),
    ("ep33_oracle_hint_action.csv", "pure_oracle_hint_action_highsuccess100ep_20260812", 20, "output_32.jsonl", "output_32.mp4"),
    ("ep33_oracle_hint_action_stopgate.csv", "pure_oracle_hint_action_stopgate_highsuccess100ep_20260813", 20, "output_32.jsonl", "output_32.mp4"),
    ("ep1378_oracle_hint_action.csv", "pure_oracle_hint_action_highsuccess100ep_20260812", 813, "output_1377.jsonl", "output_1377.mp4"),
    ("ep428_online.csv", "policy_v2_active50_replay_on_highsuccess100ep_20260816", 271, "output_427.jsonl", "output_427.mp4"),
    ("ep1439_online.csv", "policy_v2_active50_replay_on_highsuccess100ep_20260816", 844, "output_1438.jsonl", "output_1438.mp4"),
    ("ep1154_baseline.csv", "pure_baseline_highsuccess100ep_chronological_first50_20260818", 670, "output_1153.jsonl", "output_1153.mp4"),
    ("ep1154_online.csv", "policy_v2_active50_replay_on_highsuccess100ep_20260816", 670, "output_1153.jsonl", "output_1153.mp4"),
]

RELOC_CONF_WITHHOLD_THRESHOLD = 0.90  # per spec text: "r_bearing 0.41 < 0.90"


def ffprobe_frame_count(video_path):
    out = subprocess.run(
        [
            "ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0",
            "-show_entries", "stream=nb_read_frames", "-of", "csv=p=0", video_path,
        ],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    return int(out)


def load_trajectory(path):
    rows = []
    with open(path) as f:
        for line in f:
            rows.append(json.loads(line))
    # Confirm the row-index == step invariant this script relies on; if it
    # ever breaks for a new clip, fail loudly instead of silently misaligning.
    for i, r in enumerate(rows):
        if r["step"] != i:
            raise AssertionError(f"{path}: row {i} has step={r['step']} (row_index==step invariant broken)")
    return rows


def simplify_vlm_action(raw):
    if raw is None:
        return ""
    t = raw.lower()
    if "stop" in t:
        return "VLM: stop"
    if "turn left" in t:
        return "VLM: turn left"
    if "turn right" in t:
        return "VLM: turn right"
    if "forward" in t or "move forward" in t:
        return "VLM: forward"
    if "backward" in t or "move back" in t:
        return "VLM: backward"
    if "scan" in t:
        return "VLM: scan"
    return f"VLM: {raw.strip()[:40]}"


def hint_text(row):
    """Build the on-screen hint string, or the grey withheld variant."""
    haa = row.get("hint_action_arbiter")
    rm = row.get("route_memory")

    conf = None
    reason = None
    if haa:
        conf = haa.get("relocalization_confidence")
        reason = haa.get("reason")
    elif rm:
        conf = rm.get("relocalization_confidence")

    withheld = False
    if reason and ("low_relocalization" in reason or "withhold" in reason or "withheld" in reason):
        withheld = True
    elif conf is not None and conf < RELOC_CONF_WITHHOLD_THRESHOLD and haa is not None:
        # Only apply the numeric threshold when an arbiter is actually gating
        # on it (plain oracle-hint runs have conf==1.0 always and no gating).
        withheld = True

    if withheld and conf is not None:
        return f"— hint withheld (r_bearing {conf:.2f} < {RELOC_CONF_WITHHOLD_THRESHOLD:.2f})"

    # Prefer the arbiter's "desired" fields (this is what the hint actually
    # told the robot to do); fall back to route_memory's anchor fields.
    if haa and haa.get("desired_kind") is not None:
        anchor = haa.get("target_anchor_index")
        dist = haa.get("desired_distance_m")
        bearing = haa.get("desired_bearing_deg")
        kind = haa.get("desired_kind")
        return f"[Hint: anchor A{anchor} · {dist:.1f} m · {kind} {abs(bearing):.0f}°]"
    if rm and rm.get("target_anchor_index") is not None:
        anchor = rm.get("target_anchor_index")
        dist = rm.get("distance_to_anchor_m")
        bearing = rm.get("bearing_to_anchor_deg")
        kind = "left" if bearing is not None and bearing > 0 else "right"
        if dist is not None and bearing is not None:
            return f"[Hint: anchor A{anchor} · {dist:.1f} m · {kind} {abs(bearing):.0f}°]"
    return ""


def arbitration_text(row):
    haa = row.get("hint_action_arbiter")
    if not haa or not haa.get("enabled"):
        return ""
    if haa.get("override"):
        target = haa.get("desired_kind") or (haa.get("replacement_output") or "")[:30]
        return f"→ OVERRIDDEN ({target})"
    return "→ EXECUTED"


def terminal_state_text(row, next_row):
    raw = (row.get("last_vlm_output") or "").lower()
    sg = row.get("stop_gate")
    is_stop_utterance = "stop" in raw
    if not is_stop_utterance and not (sg and sg.get("gate_decision") == "vetoed"):
        return ""
    if sg and sg.get("gate_decision") == "vetoed":
        return "STOP proposed → VETOED"
    if is_stop_utterance and next_row is None:
        return "STOP proposed → EXECUTED (episode ends)"
    if is_stop_utterance:
        return "STOP proposed"
    return ""


def build_csv(name, tag, idx, traj_name, video_name):
    result_dir = os.path.join(BENCH, "eval_results", RESULT_DIR_TMPL.format(tag=tag, idx=idx))
    traj_path = os.path.join(result_dir, "trajectories", traj_name)
    video_path = os.path.join(result_dir, "videos", video_name)

    rows = load_trajectory(traj_path)
    n_steps = len(rows)
    n_frames = ffprobe_frame_count(video_path)
    stride = round(n_steps / n_frames) if n_frames else 5
    stride = max(stride, 1)

    out_path = os.path.join(OUT_DIR, name)
    withheld_return_count = 0
    total_return_count = 0
    with open(out_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "frame_index", "step", "phase", "hint", "vlm_action", "vlm_action_raw",
            "arbitration", "terminal_state", "distance_to_start",
        ])
        for frame_index in range(n_frames):
            step = min(frame_index * stride, n_steps - 1)
            row = rows[step]
            next_row = rows[step + 1] if step + 1 < n_steps else None
            h = hint_text(row)
            if row.get("phase") == "return":
                total_return_count += 1
                if h.startswith("—"):
                    withheld_return_count += 1
            writer.writerow([
                frame_index,
                step,
                row.get("phase"),
                h,
                simplify_vlm_action(row.get("last_vlm_output")),
                row.get("last_vlm_output") or "",
                arbitration_text(row),
                terminal_state_text(row, next_row),
                f"{row.get('distance_to_start_m', float('nan')):.3f}",
            ])

    withhold_pct = (100.0 * withheld_return_count / total_return_count) if total_return_count else 0.0
    return {
        "name": name,
        "n_steps": n_steps,
        "n_frames": n_frames,
        "stride": stride,
        "return_steps": total_return_count,
        "withheld_return_pct": withhold_pct,
    }


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    results = []
    for clip in CLIPS:
        r = build_csv(*clip)
        results.append(r)
        print(
            f"{r['name']:38s} steps={r['n_steps']:5d} frames={r['n_frames']:5d} "
            f"stride={r['stride']} return_withheld={r['withheld_return_pct']:.1f}% "
            f"(n_return_steps={r['return_steps']})"
        )
    return results


if __name__ == "__main__":
    main()
