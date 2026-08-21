"""Phase 4 v2 re-render, per the user's 2026-08-21 requests (initial pass +
two follow-ups same day):

- crop_third_person=True on the four PAIR pieces (seg3, seg4 main, seg5
  part1, closing) fixes the 2048-wide aspect problem that padded huge black
  bars top/bottom once scaled into 1920x1080.
- pause_raw_frames adds a brief freeze + a growing highlight ring + a short
  data-driven caption (see overlay_lib.event_caption) at each detected
  left/right divergence moment (an arbitration override firing, or a
  terminal state -- STOP proposed -> vetoed vs -> executed -- newly
  appearing).
- For override events where the hint's bearing and the VLM's own proposal
  genuinely disagree (>=12 deg apart), two direction arrows are drawn during
  the freeze: green = the hint's bearing (chosen as the "correct" reference
  direction per the user), red = what the VLM itself proposed instead.
- Every piece (pairs AND the two remaining singles, ep428/ep1439) now also
  carries a small top-down mini-map in its third-person view's top-left
  corner, trailing the robot's real trajectory as the episode plays --
  built from the occupancy rasters in topdown_maps/ (see
  build_topdown_maps.py) plus per-step ground-truth position from
  trajectories/output_<id>.jsonl. Pair segments give each side its own
  Minimap instance (independent trails) sharing the same background map
  (built from the union of both runs' trajectories, so both sides use an
  identical crop/scale for a fair comparison) -- see EPISODE_MAP_KEY below.

The ep1378 insert (previously in Segment 2/old Seg4) is dropped entirely per
2026-08-21 follow-up feedback -- it demonstrated a second, different failure
mode (timeout, not veto) that diluted that segment's single point.

Seg1 (ep1006 baseline alone) and Seg2 (ep1256 oracle-hint alone) are dropped
entirely per the user's 2026-08-21 request: a single failing episode with no
comparison reads as unclear on its own.

Run with the vlnce-isaac conda python (needs cv2). topdown_maps/ must already
exist -- run build_topdown_maps.py first (needs the system miniconda `base`
env instead, for USD/pxr access).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from overlay_lib import Minimap, load_positions_by_step, render_pair_side_by_side, render_single  # noqa: E402

BENCH = "/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/eval_results"
REPO = "/mnt/SSD4T/teambruce/projects/NaVILA-video-upload-demo/investigations/数据补全/video"
CSV_DIR = os.path.join(REPO, "overlay_data")
RAW_DIR = os.path.join(REPO, "_raw")
MAP_DIR = os.path.join(REPO, "topdown_maps")

RESULT_DIRS = {
    "ep1256_oracle_hint": "round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_pure_oracle_hint_highsuccess100ep_20260811_ep733",
    "ep1256_oracle_hint_action": "round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_pure_oracle_hint_action_highsuccess100ep_20260812_ep733",
    "ep33_oracle_hint_action": "round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_pure_oracle_hint_action_highsuccess100ep_20260812_ep20",
    "ep33_oracle_hint_action_stopgate": "round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_pure_oracle_hint_action_stopgate_highsuccess100ep_20260813_ep20",
    "ep1006_baseline": "round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_pure_baseline_highsuccess100ep_chronological_first50_20260818_ep579",
    "ep1006_online": "round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_policy_v2_active50_replay_on_highsuccess100ep_20260816_ep579",
    "ep1154_baseline": "round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_pure_baseline_highsuccess100ep_chronological_first50_20260818_ep670",
    "ep1154_online": "round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_policy_v2_active50_replay_on_highsuccess100ep_20260816_ep670",
    "ep428_online": "round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_policy_v2_active50_replay_on_highsuccess100ep_20260816_ep271",
    "ep1439_online": "round_trip_phase_prompt_go2_matterport_vision_loco_2024-09-25_23-22-02_policy_v2_active50_replay_on_highsuccess100ep_20260816_ep844",
}
VIDEO_OUTPUT_ID = {
    "ep1256_oracle_hint": 1255, "ep1256_oracle_hint_action": 1255,
    "ep33_oracle_hint_action": 32, "ep33_oracle_hint_action_stopgate": 32,
    "ep1006_baseline": 1005, "ep1006_online": 1005,
    "ep1154_baseline": 1153, "ep1154_online": 1153,
    "ep428_online": 427, "ep1439_online": 1438,
}
V = {k: f"{BENCH}/{RESULT_DIRS[k]}/videos/output_{VIDEO_OUTPUT_ID[k]}.mp4" for k in RESULT_DIRS}
C = {k: os.path.join(CSV_DIR, f"{k}.csv") for k in RESULT_DIRS}
TRAJ = {k: f"{BENCH}/{RESULT_DIRS[k]}/trajectories/output_{VIDEO_OUTPUT_ID[k]}.jsonl" for k in RESULT_DIRS}

# which topdown_maps/ep<N> background each config uses (see build_topdown_maps.py)
MAP_KEY = {
    "ep1256_oracle_hint": "ep1256", "ep1256_oracle_hint_action": "ep1256",
    "ep33_oracle_hint_action": "ep33", "ep33_oracle_hint_action_stopgate": "ep33",
    "ep1006_baseline": "ep1006", "ep1006_online": "ep1006",
    "ep1154_baseline": "ep1154", "ep1154_online": "ep1154",
    "ep428_online": "ep428", "ep1439_online": "ep1439",
}


def make_minimap(config_key):
    map_key = MAP_KEY[config_key]
    occ = os.path.join(MAP_DIR, f"{map_key}_occupancy.png")
    meta = os.path.join(MAP_DIR, f"{map_key}_meta.json")
    positions = load_positions_by_step(TRAJ[config_key])
    return Minimap(occ, meta, positions)


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
        minimap_l=make_minimap("ep1256_oracle_hint"), minimap_r=make_minimap("ep1256_oracle_hint_action"),
    )
    report["seg3"] = n

    n = render_pair_side_by_side(
        V["ep33_oracle_hint_action"], C["ep33_oracle_hint_action"], "Oracle hint-action -- ground-truth pose",
        V["ep33_oracle_hint_action_stopgate"], C["ep33_oracle_hint_action_stopgate"], "Oracle hint-action-stopgate -- ground-truth pose",
        os.path.join(RAW_DIR, "seg4_ep33_pair_v2.mp4"),
        pause_raw_frames=PAUSE_FRAMES["seg4_main"], max_events=2,
        minimap_l=make_minimap("ep33_oracle_hint_action"), minimap_r=make_minimap("ep33_oracle_hint_action_stopgate"),
    )
    report["seg4_main"] = n

    n = render_pair_side_by_side(
        V["ep1006_baseline"], C["ep1006_baseline"], "language-only baseline",
        V["ep1006_online"], C["ep1006_online"], "online (proposed)",
        os.path.join(RAW_DIR, "seg5_part1_ep1006_pair_v2.mp4"),
        pause_raw_frames=PAUSE_FRAMES["seg5_part1"], max_events=2,
        minimap_l=make_minimap("ep1006_baseline"), minimap_r=make_minimap("ep1006_online"),
    )
    report["seg5_part1"] = n

    n = render_single(
        V["ep428_online"], C["ep428_online"], os.path.join(RAW_DIR, "seg5_part2_ep428_v2.mp4"),
        "online (proposed) -- ep428, gate withholds 99.5% of return steps",
        minimap=make_minimap("ep428_online"),
    )
    report["seg5_part2"] = n

    n = render_single(
        V["ep1439_online"], C["ep1439_online"], os.path.join(RAW_DIR, "seg5_part3_ep1439_v2.mp4"),
        "online (proposed) -- ep1439, gate withholds 0% (contrast)",
        minimap=make_minimap("ep1439_online"),
    )
    report["seg5_part3"] = n

    n = render_pair_side_by_side(
        V["ep1154_baseline"], C["ep1154_baseline"], "language-only baseline",
        V["ep1154_online"], C["ep1154_online"], "online (proposed)",
        os.path.join(RAW_DIR, "closing_ep1154_pair_v2.mp4"),
        pause_raw_frames=PAUSE_FRAMES["closing"], max_events=3,
        minimap_l=make_minimap("ep1154_baseline"), minimap_r=make_minimap("ep1154_online"),
    )
    report["closing"] = n

    for k, v in report.items():
        print(f"{k}: {v} synced steps (excludes inserted pause frames)")


if __name__ == "__main__":
    main()
