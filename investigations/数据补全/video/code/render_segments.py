"""Phase 4 step 1: render overlaid raw pieces (native 10fps, native resolution)
for every segment. Run with the vlnce-isaac conda python (needs cv2).

Output: video/_raw/*.mp4 — one file per piece, consumed by compose_final.py
which handles speed-up / scale / title cards / concatenation via ffmpeg.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from overlay_lib import render_single, render_pair_side_by_side  # noqa: E402

BENCH = "/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/eval_results"
REPO = "/mnt/SSD4T/teambruce/projects/NaVILA-video-upload-demo/investigations/数据补全/video"
CSV_DIR = os.path.join(REPO, "overlay_data")
RAW_DIR = os.path.join(REPO, "_raw")

V = {
    "ep1006_baseline": f"{BENCH}/round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_pure_baseline_highsuccess100ep_chronological_first50_20260818_ep579/videos/output_1005.mp4",
    "ep1006_online": f"{BENCH}/round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_policy_v2_active50_replay_on_highsuccess100ep_20260816_ep579/videos/output_1005.mp4",
    "ep1256_oracle_hint": f"{BENCH}/round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_pure_oracle_hint_highsuccess100ep_20260811_ep733/videos/output_1255.mp4",
    "ep1256_oracle_hint_action": f"{BENCH}/round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_pure_oracle_hint_action_highsuccess100ep_20260812_ep733/videos/output_1255.mp4",
    "ep33_oracle_hint_action": f"{BENCH}/round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_pure_oracle_hint_action_highsuccess100ep_20260812_ep20/videos/output_32.mp4",
    "ep33_oracle_hint_action_stopgate": f"{BENCH}/round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_pure_oracle_hint_action_stopgate_highsuccess100ep_20260813_ep20/videos/output_32.mp4",
    "ep1378_oracle_hint_action": f"{BENCH}/round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_pure_oracle_hint_action_highsuccess100ep_20260812_ep813/videos/output_1377.mp4",
    "ep428_online": f"{BENCH}/round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_policy_v2_active50_replay_on_highsuccess100ep_20260816_ep271/videos/output_427.mp4",
    "ep1439_online": f"{BENCH}/round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_policy_v2_active50_replay_on_highsuccess100ep_20260816_ep844/videos/output_1438.mp4",
    "ep1154_baseline": f"{BENCH}/round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_pure_baseline_highsuccess100ep_chronological_first50_20260818_ep670/videos/output_1153.mp4",
    "ep1154_online": f"{BENCH}/round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_policy_v2_active50_replay_on_highsuccess100ep_20260816_ep670/videos/output_1153.mp4",
}

C = {k: os.path.join(CSV_DIR, f"{k}.csv") for k in V}

os.makedirs(RAW_DIR, exist_ok=True)


def main():
    report = {}

    # Seg 1: ep1006 baseline (single)
    n = render_single(V["ep1006_baseline"], C["ep1006_baseline"],
                       os.path.join(RAW_DIR, "seg1_ep1006_baseline.mp4"),
                       "language-only baseline")
    report["seg1"] = n

    # Seg 2: ep1256 oracle_hint (single)
    n = render_single(V["ep1256_oracle_hint"], C["ep1256_oracle_hint"],
                       os.path.join(RAW_DIR, "seg2_ep1256_hint.mp4"),
                       "Oracle hint -- ground-truth pose")
    report["seg2"] = n

    # Seg 3: ep1256 hint (left) vs hint-action (right), synced by step
    n = render_pair_side_by_side(
        V["ep1256_oracle_hint"], C["ep1256_oracle_hint"], "Oracle hint -- ground-truth pose",
        V["ep1256_oracle_hint_action"], C["ep1256_oracle_hint_action"], "Oracle hint-action -- ground-truth pose",
        os.path.join(RAW_DIR, "seg3_ep1256_pair.mp4"),
    )
    report["seg3"] = n

    # Seg 4 main: ep33 hint-action (left) vs hint-action-stopgate (right)
    n = render_pair_side_by_side(
        V["ep33_oracle_hint_action"], C["ep33_oracle_hint_action"], "Oracle hint-action -- ground-truth pose",
        V["ep33_oracle_hint_action_stopgate"], C["ep33_oracle_hint_action_stopgate"], "Oracle hint-action-stopgate -- ground-truth pose",
        os.path.join(RAW_DIR, "seg4_ep33_pair.mp4"),
    )
    report["seg4_main"] = n

    # Seg 4 insert: ep1378 hint-action (single, timeout not veto)
    n = render_single(V["ep1378_oracle_hint_action"], C["ep1378_oracle_hint_action"],
                       os.path.join(RAW_DIR, "seg4_ep1378_insert.mp4"),
                       "Oracle hint-action -- ground-truth pose (insert: ep1378)")
    report["seg4_insert"] = n

    # Seg 5 part 1: ep1006 baseline (left) vs online (right), synced by step
    n = render_pair_side_by_side(
        V["ep1006_baseline"], C["ep1006_baseline"], "language-only baseline",
        V["ep1006_online"], C["ep1006_online"], "online (proposed)",
        os.path.join(RAW_DIR, "seg5_part1_ep1006_pair.mp4"),
    )
    report["seg5_part1"] = n

    # Seg 5 part 2: ep428 online (single) -- gate withholds ~99.5% of return steps
    n = render_single(V["ep428_online"], C["ep428_online"],
                       os.path.join(RAW_DIR, "seg5_part2_ep428.mp4"),
                       "online (proposed) -- ep428, gate withholds 99.5% of return steps")
    report["seg5_part2"] = n

    # Seg 5 part 3: ep1439 online (single) -- gate withholds 0% (contrast)
    n = render_single(V["ep1439_online"], C["ep1439_online"],
                       os.path.join(RAW_DIR, "seg5_part3_ep1439.mp4"),
                       "online (proposed) -- ep1439, gate withholds 0% (contrast)")
    report["seg5_part3"] = n

    # Closing: ep1154 baseline (left) vs online (right), synced by step
    n = render_pair_side_by_side(
        V["ep1154_baseline"], C["ep1154_baseline"], "language-only baseline",
        V["ep1154_online"], C["ep1154_online"], "online (proposed)",
        os.path.join(RAW_DIR, "closing_ep1154_pair.mp4"),
    )
    report["closing"] = n

    for k, v in report.items():
        print(f"{k}: {v} frames rendered")


if __name__ == "__main__":
    main()
