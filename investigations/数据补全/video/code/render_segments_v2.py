"""Phase 4 v2 re-render: only the four side-by-side PAIR pieces need new raw
footage (seg3, seg4 main, seg5 part1, closing) -- crop_third_person=True
fixes the 2048-wide aspect problem that padded huge black bars top/bottom
once scaled into 1920x1080, and pause_raw_frames adds a brief freeze + a
growing highlight ring at each detected left/right divergence moment
(arbitration override firing, or a terminal state -- STOP proposed -> vetoed
vs -> executed -- newly appearing).

Single-clip pieces (seg4 insert ep1378, seg5 part2 ep428, seg5 part3 ep1439)
are unchanged and reused as-is from the original _raw/ render -- no aspect
problem (they were already 1024 wide) and no left/right divergence to flag.

Seg1 (ep1006 baseline alone) and Seg2 (ep1256 oracle-hint alone) are dropped
entirely per the user's 2026-08-21 request: a single failing episode with no
comparison reads as unclear on its own.

Run with the vlnce-isaac conda python (needs cv2), same as render_segments.py.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from overlay_lib import render_pair_side_by_side  # noqa: E402

BENCH = "/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/eval_results"
REPO = "/mnt/SSD4T/teambruce/projects/NaVILA-video-upload-demo/investigations/数据补全/video"
CSV_DIR = os.path.join(REPO, "overlay_data")
RAW_DIR = os.path.join(REPO, "_raw")

V = {
    "ep1256_oracle_hint": f"{BENCH}/round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_pure_oracle_hint_highsuccess100ep_20260811_ep733/videos/output_1255.mp4",
    "ep1256_oracle_hint_action": f"{BENCH}/round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_pure_oracle_hint_action_highsuccess100ep_20260812_ep733/videos/output_1255.mp4",
    "ep33_oracle_hint_action": f"{BENCH}/round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_pure_oracle_hint_action_highsuccess100ep_20260812_ep20/videos/output_32.mp4",
    "ep33_oracle_hint_action_stopgate": f"{BENCH}/round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_pure_oracle_hint_action_stopgate_highsuccess100ep_20260813_ep20/videos/output_32.mp4",
    "ep1006_baseline": f"{BENCH}/round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_pure_baseline_highsuccess100ep_chronological_first50_20260818_ep579/videos/output_1005.mp4",
    "ep1006_online": f"{BENCH}/round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_policy_v2_active50_replay_on_highsuccess100ep_20260816_ep579/videos/output_1005.mp4",
    "ep1154_baseline": f"{BENCH}/round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_pure_baseline_highsuccess100ep_chronological_first50_20260818_ep670/videos/output_1153.mp4",
    "ep1154_online": f"{BENCH}/round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_policy_v2_active50_replay_on_highsuccess100ep_20260816_ep670/videos/output_1153.mp4",
}
C = {k: os.path.join(CSV_DIR, f"{k}.csv") for k in V}

# pause_raw_frames chosen so a ~1.5s real-time freeze survives this piece's
# *unchanged* ffmpeg speed-up factor from compose_final.py (factor =
# native_content_frames/10/TARGET_seconds, both unchanged by this re-render --
# see the module docstring in compose_final_v2.py for the derivation).
PAUSE_S = 1.5
PAUSE_FRAMES = {
    "seg3": round(PAUSE_S * (962 / 10 / 50.0) * 10),   # 29
    "seg4_main": round(PAUSE_S * (584 / 10 / 35.0) * 10),   # 25
    "seg5_part1": round(PAUSE_S * (1432 / 10 / 30.0) * 10),  # 72
    "closing": round(PAUSE_S * (1312 / 10 / 20.0) * 10),  # 98
}


def main():
    report = {}

    n = render_pair_side_by_side(
        V["ep1256_oracle_hint"], C["ep1256_oracle_hint"], "Oracle hint -- ground-truth pose",
        V["ep1256_oracle_hint_action"], C["ep1256_oracle_hint_action"], "Oracle hint-action -- ground-truth pose",
        os.path.join(RAW_DIR, "seg3_ep1256_pair_v2.mp4"),
        pause_raw_frames=PAUSE_FRAMES["seg3"], max_events=4,
    )
    report["seg3"] = n

    n = render_pair_side_by_side(
        V["ep33_oracle_hint_action"], C["ep33_oracle_hint_action"], "Oracle hint-action -- ground-truth pose",
        V["ep33_oracle_hint_action_stopgate"], C["ep33_oracle_hint_action_stopgate"], "Oracle hint-action-stopgate -- ground-truth pose",
        os.path.join(RAW_DIR, "seg4_ep33_pair_v2.mp4"),
        pause_raw_frames=PAUSE_FRAMES["seg4_main"], max_events=2,
    )
    report["seg4_main"] = n

    n = render_pair_side_by_side(
        V["ep1006_baseline"], C["ep1006_baseline"], "language-only baseline",
        V["ep1006_online"], C["ep1006_online"], "online (proposed)",
        os.path.join(RAW_DIR, "seg5_part1_ep1006_pair_v2.mp4"),
        pause_raw_frames=PAUSE_FRAMES["seg5_part1"], max_events=2,
    )
    report["seg5_part1"] = n

    n = render_pair_side_by_side(
        V["ep1154_baseline"], C["ep1154_baseline"], "language-only baseline",
        V["ep1154_online"], C["ep1154_online"], "online (proposed)",
        os.path.join(RAW_DIR, "closing_ep1154_pair_v2.mp4"),
        pause_raw_frames=PAUSE_FRAMES["closing"], max_events=3,
    )
    report["closing"] = n

    for k, v in report.items():
        print(f"{k}: {v} synced steps (excludes inserted pause frames)")


if __name__ == "__main__":
    main()
