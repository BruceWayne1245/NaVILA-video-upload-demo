# Copyright (c) 2022-2024, The lab Project Developers.
# All rights reserved.
#
# SPDX-License-Identifier: BSD-3-Clause

"""Script to play a checkpoint if an RL agent from RSL-RL."""

"""Launch Isaac Sim Simulator first."""

import argparse
import gymnasium as gym
import os
import json
import math
import torch
import numpy as np
import imageio
from PIL import Image
import cv2
import time
import base64
import io
import socket
import json

from omni.isaac.lab.app import AppLauncher

# local imports
import cli_args  # isort: skip
from instruction_rewriter import InstructionRewriteError, InstructionRewriter
from hint_action_arbiter import HintActionArbiter, HintActionArbiterConfig
from route_memory_agent import (
    AnchorRelocalization,
    RelativeStartProgress,
    RouteMemoryAgent,
    diagnostic_frame_thresholds_to_fire,
)
from stop_gate import GateDecision, ReturnStopGate
from topdown_route_map import capture_occupancy_floor_slice, save_topdown_route_map
from relocalization import (
    backproject_points as _backproject_points,
    camera_point_to_body as _camera_point_to_body,
    create_feature_detector as _create_feature_detector,
    descriptor_camera_pose as _descriptor_camera_pose,
    descriptor_camera_to_body as _descriptor_camera_to_body,
    descriptor_depth as _descriptor_depth,
    descriptor_intrinsics as _descriptor_intrinsics,
    descriptor_local_map_points,
    descriptor_local_map_points_xyz,
    descriptor_rgb_gray as _descriptor_rgb_gray,
    feature_depth_anchor_relocalization,
    feature_matcher_config as _feature_matcher_config,
    fused_anchor_relocalization,
    gt_covisibility,
    local_map_anchor_relocalization,
    loftr_match_points as _loftr_match_points,
    matched_uv_points as _matched_uv_points,
    quat_wxyz_to_matrix as _quat_wxyz_to_matrix,
    ransac_rigid_transform as _ransac_rigid_transform,
    rigid_transform_3d as _rigid_transform_3d,
    scan_context_anchor_relocalization,
    sequential_pair_anchor_relocalization,
    voxel_downsample_2d,
    _append_covisibility_record,
    _diagnostic_inc,
)

# isaaclab argparse arguments
parser = argparse.ArgumentParser(description="Run a single-episode outbound-confirm-return VLN benchmark.")
parser.add_argument(
    "--disable_fabric", action="store_true", default=False, help="Disable fabric and use USD I/O operations."
)
parser.add_argument("--num_envs", type=int, default=None, help="Number of environments to simulate.")
parser.add_argument("--task", type=str, default=None, help="Name of the task.")
parser.add_argument("--seed", type=int, default=None, help="Seed used for the environment")

parser.add_argument("--history_length", default=0, type=int, help="Length of history buffer.")
parser.add_argument("--use_cnn", action="store_true", default=None, help="Name of the run folder to resume from.")
parser.add_argument("--use_rnn", action="store_true", default=False, help="Use RNN in the actor-critic model.")
parser.add_argument("--visualize_path", action="store_true", default=False, help="Visualize the path in the simulator.")

# navila argparse arguments
parser.add_argument("--device", type=str, default="cuda")
parser.add_argument("--vlm_host", type=str, default="localhost")
parser.add_argument("--vlm_port", type=int, default=54321)
parser.add_argument(
    "--round_trip_mode",
    type=str,
    default="static_long_instruction",
    choices=("static_long_instruction", "phase_prompt"),
    help=(
        "static_long_instruction: always query NaVILA with the full outbound-confirm-return instruction. "
        "phase_prompt: use phase-specific language prompts while still providing no route-memory hints."
    ),
)
parser.add_argument("--confirm_turn_seconds", type=float, default=6.0)
parser.add_argument(
    "--success_radius",
    type=float,
    default=None,
    help="Success radius for outbound and return. Defaults to episode['goals'][0]['radius'].",
)
parser.add_argument(
    "--return_success_radius",
    type=float,
    default=None,
    help="Deprecated alias for --success_radius.",
)
parser.add_argument("--max_return_seconds", type=float, default=100.0)
parser.add_argument(
    "--instruction_rewriter_provider",
    choices=("legacy", "cache_only", "ollama", "openai_compatible"),
    default="legacy",
    help=(
        "legacy preserves the original abstract return prompt. Other modes use a generated, "
        "explicit reverse instruction. Use cache_only for reproducible benchmark runs."
    ),
)
parser.add_argument("--instruction_rewriter_model", default="reviewed")
parser.add_argument(
    "--instruction_rewriter_cache",
    default=os.path.join(os.path.dirname(__file__), "generated", "reversed_instructions.json"),
)
parser.add_argument("--instruction_llm_endpoint", default=None)
parser.add_argument("--instruction_llm_api_key_env", default="OPENAI_API_KEY")
parser.add_argument("--instruction_llm_timeout", type=float, default=120.0)
parser.add_argument(
    "--return_instruction_override",
    default="",
    help="Human-authored return instruction used instead of the generated return instruction.",
)
parser.add_argument(
    "--return_instruction_file",
    default="",
    help="Path to a UTF-8 text file containing a human-authored return instruction.",
)
parser.add_argument(
    "--oracle_return_pose",
    action="store_true",
    default=False,
    help="At the start of return, place the robot at the expert goal facing the reversed reference path.",
)
parser.add_argument(
    "--oracle_align_return_yaw_to_anchor_segment",
    action="store_true",
    default=False,
    help="At the start of return, keep position fixed but align yaw to the nearest outbound anchor segment reversed.",
)
parser.add_argument(
    "--result_suffix",
    default="",
    help="Optional suffix for the result directory, used to preserve prior runs.",
)
parser.add_argument(
    "--route_memory",
    action="store_true",
    default=False,
    help="Enable return-stage relative-start hints during round-trip evaluation.",
)
parser.add_argument(
    "--route_hint_mode",
    choices=("none", "compact", "verbose"),
    default="compact",
    help="Prompt-hint verbosity for route memory.",
)
parser.add_argument(
    "--route_hint_source",
    choices=("integrated", "isaac", "oracle"),
    default="integrated",
    help="Source for return-stage route hints. 'oracle' injects exact simulator bearing to the next reverse-route anchor.",
)
parser.add_argument("--route_anchor_spacing_m", type=float, default=1.0, help=argparse.SUPPRESS)
parser.add_argument("--route_min_relocalization_confidence", type=float, default=0.35, help=argparse.SUPPRESS)
parser.add_argument(
    "--route_relocalization_backend",
    choices=("none", "oracle_anchor", "feature_depth", "sift_depth", "loftr_depth", "lidar_local_map", "scan_context", "fused", "sequential_pair"),
    default="none",
    help=argparse.SUPPRESS,
)
parser.add_argument("--route_relocalization_window", type=int, default=0, help=argparse.SUPPRESS)
parser.add_argument("--route_relocalization_interval_updates", type=int, default=25, help=argparse.SUPPRESS)
parser.add_argument("--route_fallback", action="store_true", default=False, help=argparse.SUPPRESS)
parser.add_argument(
    "--sequential_pair_anchor_geometry_source",
    choices=("accumulated", "oracle"),
    default="accumulated",
    help=(
        "Anchor-to-anchor geometry used to reproject/cross-check sequential_pair "
        "estimates (RouteMemoryAgent._reproject_delta_to_anchor). 'accumulated' "
        "(default) uses the non-privileged edge_from_previous chain, preserving "
        "existing behavior. 'oracle' is an ablation-only switch to ground-truth "
        "world_pose, to isolate whether anchor-to-anchor geometry error (as "
        "opposed to ICP/odometry error) explains a given failure -- run both on "
        "the same episodes to compare."
    ),
)
parser.add_argument(
    "--sequential_pair_closure_check",
    action="store_true",
    default=False,
    help=(
        "sequential_pair only: cross-check the current-anchor and next-anchor ICP "
        "fits against each other every attempt (their difference should reproduce "
        "the true current-to-next anchor displacement); reconstruct the weaker "
        "side from the stronger one on a one-sided mismatch, or reject the "
        "attempt if both sides are comparably wrong. Off by default to preserve "
        "existing accept/reject behavior for prior validated batches."
    ),
)
parser.add_argument(
    "--sequential_pair_closure_mode",
    choices=("threshold", "belief"),
    default="threshold",
    help=(
        "Only used when --sequential_pair_closure_check is on. 'threshold' "
        "(default) is the original 2026-07-04 design: reconstruct the weaker "
        "side on a 1.5x quality-ratio mismatch, else reject the attempt "
        "outright. 'belief' (2026-07-05) replaces both the ratio and the "
        "reject with a continuous, quality-weighted fusion of current+next "
        "that always yields a (possibly low-confidence) usable estimate -- "
        "confirmed against real batch data that outright rejects can starve "
        "_distance_since_sequence_observation_m's reset and cascade into a "
        "permanent stall on episodes that were otherwise fine."
    ),
)
parser.add_argument(
    "--sequential_pair_closure_belief_trust_aware_guard",
    action="store_true",
    default=False,
    help=(
        "Only used when --sequential_pair_closure_mode=belief. belief mode "
        "always blends current+next via a confidence-weighted circular mean, "
        "no matter how large the disagreement is -- confirmed (2026-07-07, "
        "ICP bearing-error investigation) that this is unsafe when the "
        "disagreement is large enough to be a categorical mismatch (one side "
        "is just wrong) rather than plausible ICP noise: averaging two "
        "angles ~150 deg apart is numerically unstable (the weighted vector "
        "sum nearly cancels), so even a minority-weighted wrong reading can "
        "swing the fused bearing by 100+ degrees. When this flag is on and a "
        "disagreement exceeds --sequential_pair_closure_belief_large_"
        "position_disagreement_m / --sequential_pair_closure_belief_large_"
        "heading_disagreement_deg, match_class/near_tie_basin_count (not "
        "just the confidence*sqrt(inlier_count) quality score, which "
        "already saturates near 1.0 even for anchors match_class flags as "
        "degenerate/ambiguous) decide which side is trustworthy; the other "
        "side is reconstructed from it via the known anchor-to-anchor edge "
        "geometry (pure geometry, no odometry involved), mirroring "
        "'threshold' mode's original dominant-side substitution. Falls back "
        "to the normal belief blend when the disagreement is below the "
        "large thresholds, or when trust is ambiguous (both or neither side "
        "looks clean). Off by default to preserve existing validated "
        "belief-mode behavior."
    ),
)
parser.add_argument(
    "--sequential_pair_closure_belief_large_position_disagreement_m",
    type=float,
    default=1.5,
    help="Only used when --sequential_pair_closure_belief_trust_aware_guard is on. "
         "Position disagreement (meters) above which belief mode treats the "
         "current/next mismatch as categorical rather than noise-level (see "
         "--sequential_pair_closure_belief_trust_aware_guard).",
)
parser.add_argument(
    "--sequential_pair_closure_belief_large_heading_disagreement_deg",
    type=float,
    default=90.0,
    help="Only used when --sequential_pair_closure_belief_trust_aware_guard is on. "
         "Heading disagreement (degrees) above which belief mode treats the "
         "current/next mismatch as categorical rather than noise-level (see "
         "--sequential_pair_closure_belief_trust_aware_guard).",
)
parser.add_argument(
    "--sequential_pair_quarantine",
    action="store_true",
    default=False,
    help=(
        "sequential_pair only: permanently skip an anchor as a 'next' candidate "
        "once its ICP fit is observed bouncing beyond tolerance across "
        "consecutive attempts while still unpromoted, so it can never become "
        "'current' either. Does not catch an anchor whose fit only degrades at "
        "the moment of promotion itself. Off by default."
    ),
)
parser.add_argument(
    "--sequential_pair_quarantine_mode",
    choices=("window", "trend"),
    default="window",
    help=(
        "Only used when --sequential_pair_quarantine is on. 'window' "
        "(default) is the original 2026-07-04 design: flag an anchor from a "
        "small (3-6 sample) window's raw position/heading spread. 'trend' "
        "(2026-07-05) instead judges each reading against the simultaneously "
        "-read current anchor across the anchor's entire dwell time as "
        "'next', quarantining only if a majority of that whole history "
        "disagrees and the disagreement is not shrinking as the robot draws "
        "closer -- confirmed against real batch data that 'window' mostly "
        "false-positives on anchors an independent baseline/off run showed "
        "were perfectly fine."
    ),
)
parser.add_argument(
    "--sequential_pair_quarantine_next_quality",
    action="store_true",
    default=False,
    help=(
        "sequential_pair only (2026-07-15, opt-in, off by default): quarantine "
        "a 'next' candidate based on its OWN per-attempt ICP ambiguity signal "
        "(icp_best_to_second_score_ratio -- how close the runner-up yaw-seed "
        "hypothesis scored to the winner in that single attempt's 24-seed "
        "sweep), independent of --sequential_pair_quarantine/_mode above, which "
        "both judge 'next' only relative to the simultaneously-read 'current' "
        "anchor. See investigations/2026-07-15-50ep-batch-current-next-"
        "simultaneous-failure/FINDINGS.md: that relative check is blind to the "
        "case where current and next are BOTH bad together (confirmed on real "
        "batch data), which this flag targets. Data-validated to separate "
        "known-bad stuck anchors from legitimate slow ones better than raw "
        "wait-time or promotion-vote pass-fraction (both tested and rejected "
        "first), but with real residual error either way -- roughly a third of "
        "legitimate slow anchors would still be quarantined at the default "
        "threshold. Turn this back off if live results are unsatisfactory; it "
        "does not change any other quarantine/promotion behavior when off."
    ),
)
parser.add_argument(
    "--sequential_pair_quarantine_next_quality_threshold",
    type=float,
    default=0.75,
    help=(
        "Only used when --sequential_pair_quarantine_next_quality is on. "
        "Quarantines a 'next' candidate once the mean "
        "icp_best_to_second_score_ratio over its whole dwell (after at least "
        "--sequential_pair_quarantine_next_quality_min_samples attempts) "
        "exceeds this. 0.75 was the best-separating threshold found in this "
        "session's offline analysis (~89% of known-bad anchors caught vs. "
        "~34% of legitimate slow anchors incorrectly flagged)."
    ),
)
parser.add_argument(
    "--sequential_pair_quarantine_next_quality_min_samples",
    type=int,
    default=5,
    help=(
        "Only used when --sequential_pair_quarantine_next_quality is on. "
        "Minimum number of attempts observed for a 'next' candidate before its "
        "mean icp_best_to_second_score_ratio is judged against the threshold."
    ),
)
parser.add_argument(
    "--sequential_pair_promotion_mode",
    choices=("immediate", "bounded_evidence"),
    default="immediate",
    help=(
        "sequential_pair only: how a single attempt's 'next looks promotable' "
        "result (close_enough/trend_ok + quality_ok, unchanged) turns into an "
        "actual current<-next promotion. 'immediate' (default) is the original "
        "design: promotes on the very first attempt that passes. "
        "'bounded_evidence' (2026-07-06) instead requires that same per-attempt "
        "test to pass on --sequential_pair_promotion_min_votes of the last "
        "--sequential_pair_promotion_window attempts against this candidate "
        "anchor before committing -- forensic replay of hard-11 data found "
        "'immediate' lets a chain of single-step promotions race through many "
        "anchors within a short attempt window whenever local structure repeats "
        "along the route (high-overlap, low-residual, many-inlier ICP fits "
        "against the wrong anchor). The vote window is keyed per candidate "
        "anchor and discarded on promotion, so it can only delay a promotion "
        "within one anchor's dwell time, never lock anything permanently. Off "
        "by default to preserve existing accept/promote behavior for prior "
        "validated batches."
    ),
)
parser.add_argument(
    "--sequential_pair_promotion_window",
    type=int,
    default=5,
    help="Only used when --sequential_pair_promotion_mode=bounded_evidence. Size of the rolling "
         "per-candidate-anchor vote window (see --sequential_pair_promotion_mode).",
)
parser.add_argument(
    "--sequential_pair_promotion_min_votes",
    type=int,
    default=3,
    help="Only used when --sequential_pair_promotion_mode=bounded_evidence. Minimum number of "
         "passing votes (out of --sequential_pair_promotion_window) required before a promotion "
         "commits (see --sequential_pair_promotion_mode).",
)
parser.add_argument(
    "--sequential_pair_promotion_alias_aware",
    action="store_true",
    default=False,
    help=(
        "sequential_pair + bounded_evidence only: right after finalize_outbound(), precompute a "
        "per-anchor 'alias_score' (best ICP overlap this anchor achieves against any other anchor "
        "2-5 route-positions away, excluding the immediate neighbor which is expected to overlap by "
        "construction) via RouteMemoryAgent.compute_anchor_alias_scores. A candidate anchor whose "
        "score is at or above --sequential_pair_promotion_alias_threshold then requires "
        "--sequential_pair_promotion_alias_window/--sequential_pair_promotion_alias_min_votes instead "
        "of the flat --sequential_pair_promotion_window/--sequential_pair_promotion_min_votes -- "
        "confirmed against real hard-11 data that plain bounded_evidence's flat requirement still gets "
        "raced through on anchors whose local structure repeats persistently enough to fool several "
        "consecutive ICP reads in a row. A one-time cost after outbound (roughly anchor_count * 4 ICP "
        "calls), not part of return-phase live-matching latency. Off by default."
    ),
)
parser.add_argument(
    "--sequential_pair_promotion_alias_threshold",
    type=float,
    default=0.6,
    help="Only used when --sequential_pair_promotion_alias_aware is on. ICP overlap_ratio at or above "
         "this against a non-adjacent anchor flags the candidate as alias-prone.",
)
parser.add_argument(
    "--sequential_pair_promotion_alias_window",
    type=int,
    default=8,
    help="Only used when --sequential_pair_promotion_alias_aware is on. Promotion vote window for "
         "candidate anchors flagged alias-prone (see --sequential_pair_promotion_alias_aware).",
)
parser.add_argument(
    "--sequential_pair_promotion_alias_min_votes",
    type=int,
    default=5,
    help="Only used when --sequential_pair_promotion_alias_aware is on. Minimum passing votes required "
         "for candidate anchors flagged alias-prone (see --sequential_pair_promotion_alias_aware).",
)
parser.add_argument(
    "--sequential_pair_promotion_alias_stall_attempts",
    type=int,
    default=200,
    help="Only used when --sequential_pair_promotion_alias_aware is on. If a flagged candidate anchor "
         "has been voted on this many times without ever promoting, fall back to the flat "
         "--sequential_pair_promotion_window/--sequential_pair_promotion_min_votes for it -- confirmed "
         "necessary against real hard-11 data: a route that is uniformly self-similar end to end (not "
         "just a couple of hot-spot anchors) can otherwise make the stricter alias requirement never get "
         "satisfied at all, permanently freezing promotion for the rest of the episode. Chosen above the "
         "largest gap between two legitimate alias-aware promotions observed (130 attempts).",
)
parser.add_argument(
    "--sequential_pair_promotion_use_pre_closure_estimates",
    action="store_true",
    default=False,
    help="(2026-07-10) Off by default. When --sequential_pair_closure_check is on, the promotion-vote "
         "gates (close_enough/trend_ok/quality_ok) normally evaluate current/next AFTER "
         "_sequential_pair_closure_precheck has already run -- in belief mode with "
         "--sequential_pair_closure_belief_trust_aware_guard, a large disagreement rewrites next's own "
         "dx/dy/confidence before promotion ever sees it, even when next's own raw ICP reading was fine. "
         "Confirmed against real hard11 covisibility_records: pooled across the "
         "hard11_live_trust_aware_guard_20260707_accumulated batch, a meaningful share of 'next looks "
         "healthy but never promotes' attempts pass every vote gate on their raw, pre-closure-check "
         "reading but not on the post-fusion one. This flag makes the vote gates look at each side's raw "
         "estimate instead; the reported bearing/distance hint (once a side is selected) is unaffected -- "
         "it still goes through the unchanged closure-check/fusion pipeline.",
)
parser.add_argument(
    "--sequential_pair_short_baseline_disambiguation",
    action="store_true",
    default=False,
    help="(2026-07-12) Off by default. Cross-checks EVERY next-candidate's ICP reading against a second "
         "reading of the SAME candidate anchor taken once the robot has moved "
         "--sequential_pair_short_baseline_min_travel_m, exploiting real parallax between two genuinely "
         "different vantage points. Deliberately NOT gated on match_class being flagged ambiguous: an "
         "offline check on ep1040 (this project's own flagship confidently-wrong-rotation example) found "
         "86.5%% of its worst bearing errors carry match_class=clean_full_pose, which is the whole reason "
         "they were unexplained by any existing diagnostic in the first place -- gating this check behind "
         "that same diagnostic would miss almost all of the cases it exists to catch. Unlike "
         "--route_memory_multiframe_anchor_window (merges several OUTBOUND frames captured at the SAME "
         "location into one denser anchor descriptor -- confirmed 2026-07-08 to regress results, since a "
         "genuinely symmetric structure looks symmetric no matter how densely it's sampled from one "
         "viewpoint). If the two readings' implied absolute anchor poses disagree in rotation by more than "
         "--sequential_pair_short_baseline_max_rotation_disagreement_deg, the reported estimate's "
         "anchor_heading_reliable is set to False (translation is left untouched) instead of trusting a "
         "single-viewpoint reading that may be a genuine, self-consistent-but-wrong local optimum -- see "
         "investigations/2026-07-09-.../route_memory_literature_survey.md §2.1/§4 and step 4's negative "
         "result (an independent-ALGORITHM cross-check on the same single scan, Scan Context vs ICP, "
         "showed no reliable discrimination -- both algorithms are drawn to the same wrong solution when "
         "the ambiguity is genuine physical symmetry in the scene, not an ICP-specific quirk).",
)
parser.add_argument(
    "--sequential_pair_short_baseline_min_travel_m",
    type=float,
    default=0.3,
    help="Minimum robot travel (m) between the two cross-checked readings for "
         "--sequential_pair_short_baseline_disambiguation. Below this, the first ambiguous reading is kept "
         "pending (not overwritten) until enough baseline accumulates.",
)
parser.add_argument(
    "--sequential_pair_short_baseline_max_rotation_disagreement_deg",
    type=float,
    default=20.0,
    help="Rotation disagreement (deg) between the two cross-checked readings' implied absolute anchor "
         "poses, above which --sequential_pair_short_baseline_disambiguation flags anchor_heading_reliable "
         "as False.",
)
parser.add_argument(
    "--sequential_pair_loftr_rear_yaw_check",
    action="store_true",
    default=False,
    help="(2026-07-13) Off by default, expensive (runs a GPU LoFTR match per candidate per attempt) -- "
         "only intended for small validation runs, not routine batches. Cross-checks each current/next "
         "candidate's ICP-estimated rotation against an INDEPENDENT yaw estimate from a different sensing "
         "MODALITY: LoFTR visual feature matching + 3-D RANSAC between the current front-camera RGB-D view "
         "and the anchor's saved rear-camera RGB-D view (reuses the retired feature_depth_loftr_3d3d_rear "
         "backend's own matching pipeline, never before wired in as a per-attempt cross-check). Motivated by "
         "investigations/2026-07-13-icp-bearing-error-cross-batch-deep-dive/CORRELATIVE_VERIFIER_CHECK.md, "
         "which found a structurally different LiDAR-only scoring function (occupancy-grid correlation) does "
         "not reliably disagree with ICP where ICP is wrong -- both are fooled by the same LiDAR-visible "
         "geometric self-similarity. RGB texture is information LiDAR shape cannot see, so a disagreement "
         "here is evidence a same-modality check cannot produce. Diagnostic-only: never gates or rejects.",
)
parser.add_argument(
    "--sequential_pair_disable_temporal_smoothing",
    action="store_true",
    default=False,
    help="(2026-07-13) Off by default (temporal smoothing stays on, unchanged behavior). Per "
         "investigations/2026-07-13-icp-bearing-error-cross-batch-deep-dive/FUSION_MECHANISM_ANALYSIS.md: "
         "_temporally_smooth_relocalization (the '+ema' backend suffix) is called unconditionally on every "
         "accepted sequential_pair estimate and is responsible for 93.5%% of measured fusion-corruption in "
         "that analysis, with no trust_aware_guard-style match_class check at all -- only a blunt 60deg "
         "disagreement cutoff. Combined with leaving --sequential_pair_closure_check off, this reports each "
         "accepted attempt's raw selected (dx,dy,dtheta) completely unmodified -- 'no fusion at all'.",
)
parser.add_argument(
    "--sequential_pair_closure_reconciliation_signal",
    choices=["dtheta", "bearing"],
    default="dtheta",
    help="(2026-07-13) 'dtheta' (default) preserves existing behavior: both "
         "_sequential_pair_closure_belief_fusion and _temporally_smooth_relocalization measure "
         "disagreement/trust via the two readings' rotation (dtheta) difference, and blend dtheta via "
         "circular_weighted_mean when fusing. 'bearing' instead measures disagreement/trust via the two "
         "readings' direction-to-anchor (bearing, atan2(dy,dx) -- the quantity this project's hint/arbiter "
         "actually consumes) and NEVER blends dtheta via circular_weighted_mean (the specific operation "
         "confirmed unstable for large disagreements, investigations/2026-07-07-icp-bearing-angle-error/); "
         "the fused/smoothed output's dtheta is simply carried through unchanged from whichever side is "
         "dominant (fusion) or freshest (temporal smoothing), never averaged. Position blending (which "
         "determines the reported bearing) is unchanged in both modes.",
)
parser.add_argument(
    "--route_memory_multiframe_anchor_window",
    type=int,
    default=1,
    help="Number of consecutive outbound LiDAR frames to merge into each anchor's stored local map "
         "(2026-07-08). Default 1 preserves the original single-instantaneous-frame behavior exactly. "
         "A value >1 merges the last N outbound frames -- each reprojected from its own capture-time "
         "pose into the anchor's own final frame -- into one richer submap before storage. Aimed at "
         "genuine rotational self-similarity/aliasing (anchor-15-style, and the 2026-07-08 hard11 "
         "cases), which raising point density on a single frame alone does not fix -- confirmed offline: "
         "the self-alias overlap gap was essentially unchanged at 2x point density on every confirmed-"
         "symmetric anchor tested. A wider merged submap may include geometry (further down the "
         "corridor) that breaks the local symmetry a single viewpoint cannot see.",
)
parser.add_argument(
    "--capture_anchor_match_snapshots",
    action="store_true",
    default=False,
    help="Attach small anchor-vs-current local-map point-cloud snapshots (ICP alignment + inlier "
         "mask) to route_relocalization_diagnostics for the lidar_local_map/scan_context/fused "
         "backends, for offline visualization via plot_anchor_match_diagnostics.py. Off by default "
         "since it grows the measurement JSON.",
)
parser.add_argument(
    "--capture_route_memory_diagnostic_frames",
    action="store_true",
    default=False,
    help="At ~4 fixed fractions of return-journey progress remaining (75%%/50%%/25%%/5%%), dump a "
         "diagnostic frame: robot world pose, current local-map points, and every recorded anchor's "
         "world pose + local-map points -- to result_dir/route_memory_diagnostic_frames/. Rendered "
         "offline via plot_route_memory_diagnostic_frames.py (occupancy-map overview, clean per-anchor "
         "and current local maps, and a current-vs-every-anchor ICP match plot). Works best paired "
         "with --topdown_route_map. Off by default.",
)
parser.add_argument(
    "--capture_icp_replay_dataset",
    action="store_true",
    default=False,
    help="Dump a full offline-replayable dataset for this episode's return phase: every anchor's "
         "raw (undownsampled) local-map xyz points + ground-truth world pose once (right after "
         "finalize_outbound), and the robot's raw local-map xyz points + ground-truth world pose at "
         "every return-phase environment step, to result_dir/icp_replay_dataset/ (anchors.json + "
         "steps/frame_step{N:06d}.json, one small file per step -- same safe pattern as "
         "--capture_route_memory_diagnostic_frames, not embedded in the big measurement JSON). "
         "Since return-phase robot motion is oracle-controlled regardless of this flag, replaying ICP "
         "or a new LiDAR-matching method offline against this dataset reproduces the exact same "
         "candidate geometry as a live rerun would, without needing Isaac Sim. Off by default since "
         "it writes one file per environment step.",
)
parser.add_argument(
    "--route_local_map_icp_objective",
    choices=("point_to_point", "point_to_line", "point_to_line_2p5d", "ndt_2d"),
    default="point_to_point",
    help=(
        "LiDAR local-map ICP objective for lidar_local_map/sequential_pair. "
        "point_to_line is the stage-3.1 switch; point_to_line_2p5d and ndt_2d "
        "are separate A/B switches."
    ),
)
parser.add_argument(
    "--route_local_map_voxel_size_m",
    type=float,
    default=0.10,
    help="Voxel size for LiDAR local-map relocalization. Default is stage-4A.",
)
parser.add_argument(
    "--route_local_map_max_points",
    type=int,
    default=512,
    help="Maximum downsampled points per local map. Default is stage-4A.",
)
parser.add_argument(
    "--route_local_map_profile",
    choices=("default", "dense"),
    default="default",
    help="Use 'dense' for stage-4B (0.05m voxels, 2048 points).",
)
parser.add_argument(
    "--route_local_map_quality_policy",
    choices=("diagnostic", "strict"),
    default="diagnostic",
    help="Whether ICP ambiguity/localizability/2.5D diagnostics only log or reject matches.",
)
parser.add_argument(
    "--measured_odometry",
    action="store_true",
    default=False,
    help="Integrate route-memory's dead-reckoning (action_delta fed to update_outbound_motion/"
         "update_return_motion) from the robot's own true position/orientation change each step "
         "(pose_delta_body on root_state_w) instead of assuming the commanded vlm_vel_commands "
         "were achieved exactly. Still reads Isaac's exact, noise-free simulator state -- see "
         "--leg_odometry for a version built from the robot's own noisy sensors instead. Off by "
         "default to preserve existing behavior.",
)
parser.add_argument(
    "--leg_odometry",
    action="store_true",
    default=False,
    help="Like --measured_odometry, but estimates body velocity from Go2's own noisy joint "
         "encoders + IMU gyro + height-scanner-based ground-clearance stance detection "
         "(stance-leg Jacobian method) instead of reading Isaac's privileged root_vel_w/"
         "root_state_w -- see get_leg_odometry_action_delta's docstring (contact-force-based "
         "stance detection was tried first and abandoned: PhysX contact reporting reads exactly "
         "0 N for every body in this scene, a Matterport-terrain-collision-setup gap, not "
         "fixable with threshold tuning). Takes precedence over --measured_odometry if both are "
         "set. Off by default; unvalidated as of 2026-07-04.",
)
parser.add_argument(
    "--vio_bridge",
    action="store_true",
    default=True,
    help="Enable VIO bridge: suppress visual particle-filter updates in the corridor dead zone "
         "(filter std > vio_bridge_std_m) away from path feature anchors (corners/doorways).",
)
parser.add_argument("--no_vio_bridge", action="store_false", dest="vio_bridge", help=argparse.SUPPRESS)
parser.add_argument("--vio_bridge_std_m", type=float, default=2.5, help=argparse.SUPPRESS)
parser.add_argument("--vio_bridge_feature_radius_m", type=float, default=2.0, help=argparse.SUPPRESS)
parser.add_argument(
    "--stop_gate",
    action="store_true",
    default=False,
    help=(
        "Enable the return-phase stop-gate arbiter.  Vetoes premature stops "
        "(d > r_out, high conf) and forces terminal when robot stays within "
        "r_in for confirm_steps consecutive VLM steps.  Off by default."
    ),
)
parser.add_argument("--stop_gate_r_in", type=float, default=3.0, help=argparse.SUPPRESS)
parser.add_argument("--stop_gate_r_out", type=float, default=3.0, help=argparse.SUPPRESS)
parser.add_argument("--stop_gate_confirm_steps", type=int, default=3, help=argparse.SUPPRESS)
parser.add_argument("--stop_gate_min_confidence", type=float, default=0.5, help=argparse.SUPPRESS)
parser.add_argument(
    "--hint_action_arbiter",
    action="store_true",
    default=False,
    help=(
        "Enable return-phase hint-following action arbitration. If the VLM action clearly conflicts "
        "with the next-anchor route hint and the hinted local path is clear, replace the VLM output "
        "with a matching NaVILA action string."
    ),
)
parser.add_argument("--hint_arbiter_forward_cone_deg", type=float, default=15.0, help=argparse.SUPPRESS)
parser.add_argument("--hint_arbiter_forward_conflict_bearing_deg", type=float, default=30.0, help=argparse.SUPPRESS)
parser.add_argument("--hint_arbiter_turn_step_deg", type=float, default=45.0, help=argparse.SUPPRESS)
parser.add_argument("--hint_arbiter_forward_distance_cm", type=int, default=75, help=argparse.SUPPRESS)
parser.add_argument("--hint_arbiter_max_clear_path_distance_m", type=float, default=1.0, help=argparse.SUPPRESS)
parser.add_argument("--hint_arbiter_robot_radius_m", type=float, default=0.30, help=argparse.SUPPRESS)
parser.add_argument("--hint_arbiter_clearance_margin_m", type=float, default=0.12, help=argparse.SUPPRESS)
parser.add_argument(
    "--hint_arbiter_min_relocalization_confidence",
    type=float,
    default=0.0,
    help="(2026-07-13) Minimum relocalization_confidence the current hint must carry before "
         "--hint_action_arbiter is allowed to override the VLM's action. Default 0.0 preserves the "
         "arbiter's original behavior exactly (every confidence value passes) -- this previously had NO "
         "confidence gate at all, safe only because the only real hint source was the ground-truth "
         "oracle (which always reports relocalization_confidence=1.0). Needs a real threshold calibrated "
         "via offline replay before being used with a non-oracle (e.g. sequential_pair shadow) hint source.",
)
parser.add_argument(
    "--hint_arbiter_allow_without_clear_path",
    action="store_true",
    default=False,
    help=argparse.SUPPRESS,
)
parser.add_argument("--route_fallback_window", type=int, default=4, help=argparse.SUPPRESS)
parser.add_argument("--route_fallback_duration_seconds", type=float, default=0.5, help=argparse.SUPPRESS)
parser.add_argument(
    "--topdown_route_map",
    action="store_true",
    default=False,
    help="Save a USD floor-slice occupancy map with outbound/return trajectories and route anchors.",
)
parser.add_argument("--topdown_map_resolution", type=float, default=0.05, help=argparse.SUPPRESS)
parser.add_argument("--topdown_map_padding_m", type=float, default=3.0, help=argparse.SUPPRESS)
parser.add_argument("--topdown_map_z_min", type=float, default=0.08, help=argparse.SUPPRESS)
parser.add_argument("--topdown_map_z_max", type=float, default=2.2, help=argparse.SUPPRESS)
parser.add_argument("--topdown_map_max_size_px", type=int, default=2400, help=argparse.SUPPRESS)


# r2r argparse arguments
parser.add_argument("--episode_idx", type=int, default=0)

# RSL-RL cli arguments
cli_args.add_rsl_rl_args(parser)
# append AppLauncher cli args
AppLauncher.add_app_launcher_args(parser)
args_cli = parser.parse_args()


# launch omniverse app
app_launcher = AppLauncher(args_cli)
simulation_app = app_launcher.app

from rsl_rl.runners import OnPolicyRunner

import omni.isaac.lab_tasks  # noqa: F401
from omni.isaac.lab_tasks.utils import get_checkpoint_path, parse_env_cfg
from omni.isaac.lab.utils.io import load_yaml
import omni.isaac.lab.utils.math as math_utils
from omni.isaac.lab.markers import VisualizationMarkers, VisualizationMarkersCfg
from omni.isaac.lab.utils import update_class_from_dict
from omni.isaac.lab_tasks.utils.wrappers.rsl_rl import (
    RslRlOnPolicyRunnerCfg,
    RslRlVecEnvWrapper,
)
import omni.isaac.lab.sim as sim_utils

from omni.isaac.vlnce.config import *
from omni.isaac.vlnce.utils import ASSETS_DIR, RslRlVecEnvHistoryWrapper, VLNEnvWrapper
from omni.isaac.vlnce.utils.eval_utils import (
    get_vel_command, 
    read_episodes, 
    add_instruction_on_img,
    InstructionData, 
)
from omni.isaac.vlnce.utils.measures import PathLength, DistanceToGoal, Success, SPL, OracleNavigationError, OracleSuccess, MeasureManager


def quat2eulers(q0, q1, q2, q3):
    """
    Calculates the roll, pitch, and yaw angles from a quaternion.

    Args:
        q0: The scalar component of the quaternion.
        q1: The x-component of the quaternion.
        q2: The y-component of the quaternion.
        q3: The z-component of the quaternion.

    Returns:
        A tuple containing the roll, pitch, and yaw angles in radians.
    """

    roll = math.atan2(2 * (q2 * q3 + q0 * q1), q0**2 - q1**2 - q2**2 + q3**2)
    pitch = math.asin(2 * (q1 * q3 - q0 * q2))
    yaw = math.atan2(2 * (q1 * q2 + q0 * q3), q0**2 + q1**2 - q2**2 - q3**2)

    return roll, pitch, yaw


def define_markers() -> VisualizationMarkers:
    """Define path markers with various different shapes."""
    marker_cfg = VisualizationMarkersCfg(
        prim_path="/Visuals/pathMarkers",
        markers={
            "waypoint": sim_utils.SphereCfg(
                radius=0.1,
                visual_material=sim_utils.PreviewSurfaceCfg(diffuse_color=(0.0, 1.0, 0.0)),
            ),
        },
    )
    return VisualizationMarkers(marker_cfg)


def reset_start_pos_rot(env_cfg, args_cli, episode):
    scene_id = os.path.splitext(os.path.basename(episode["scene_id"]))[0]
    env_cfg.scene.terrain.obj_filepath = os.path.join(ASSETS_DIR, f"matterport_usd/{scene_id}/{scene_id}.usd")
    
    start_pos, start_rot, goal_pos = episode["start_position"], episode["start_rotation"], episode["reference_path"][-1]
    env_cfg.scene.robot.init_state.rot = start_rot

    if "go2" in args_cli.task:
        env_cfg.scene.robot.init_state.pos = (start_pos[0], start_pos[1], start_pos[2]+0.4)
    elif "h1" in args_cli.task:
        env_cfg.scene.robot.init_state.pos = (start_pos[0], start_pos[1], start_pos[2]+1.0)
    else:
        env_cfg.scene.robot.init_state.pos = (start_pos[0], start_pos[1], start_pos[2]+0.5)

    env_cfg.scene.terrain.origins = env_cfg.scene.robot.init_state.pos

    env_cfg.scene.disk_1.init_state.pos = ([start_pos[0], start_pos[1], start_pos[2] + 2.5])
    env_cfg.scene.disk_2.init_state.pos = ([goal_pos[0], goal_pos[1], goal_pos[2] + 2.5])

    return env_cfg


def add_measurement(env, episode):
    measure_manager = MeasureManager()
    measure_names = ["PathLength", "DistanceToGoal", "Success", "SPL", "OracleNavigationError", "OracleSuccess"]
    for measure_name in measure_names:
        measure = eval(measure_name)(env, episode, measure_manager)
        measure_manager.register_measure(measure)
    
    env.measure_manager = measure_manager
    return


def sample_images_and_send_to_vlm(image_list, vlm_host, vlm_port, query):
    if len(image_list) == 0:
        print("Did not receive any images.")
        return None
    elif len(image_list) < 8:
        print("Not enough images received, padding.")
        image_list = image_list.copy()
        # append image value=0, in front of the existing images, image size equal to the last one
        for _ in range(8 - len(image_list)):
            image_list.insert(0, Image.new('RGB', image_list[-1].size, (0, 0, 0)))
    else:
        image_list = image_list.copy()
        
    num_images = len(image_list)
    indices = [int(i * (num_images - 1) / 7) for i in range(7)]
    sampled_images = [image_list[i] for i in indices]
    sampled_images.append(image_list[-1])

    # save sampled images
    # time_stamp = time.strftime("%Y%m%d-%H%M%S")
    # if not os.path.exists("test_images"):
    #     os.makedirs("test_images")
    # for i, img in enumerate(sampled_images):
    #     # convert to PIL Image
    #     img = Image.fromarray(img)
    #     img.save(os.path.join("test_images", f"{time_stamp}_image_{i}.jpg"))

    # Convert images to base64 for transmission
    encoded_images = []
    for image in sampled_images:
        # Ensure PIL Image for JPEG encoding
        if isinstance(image, np.ndarray):
            array_image = image
            if array_image.dtype != np.uint8:
                # Convert to uint8. If values are 0-1, scale; otherwise clip to 0-255
                if array_image.max() <= 1.0:
                    array_image = (array_image * 255.0).clip(0, 255).astype(np.uint8)
                else:
                    array_image = array_image.clip(0, 255).astype(np.uint8)
            pil_image = Image.fromarray(array_image)
        elif isinstance(image, Image.Image):
            pil_image = image
        else:
            # Fallback: try to construct a PIL image from whatever object is provided
            pil_image = Image.fromarray(np.array(image, dtype=np.uint8))

        np_image = np.array(pil_image)
        np_bgr = cv2.cvtColor(np_image, cv2.COLOR_RGB2BGR)
        _, buf = cv2.imencode(".jpg", np_bgr)
        encoded_images.append(base64.b64encode(buf.tobytes()).decode())

    # Prepare request data
    request_data = {
        'images': encoded_images,
        'query': query
    }

    # Send to VLM server
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.connect((vlm_host, vlm_port))
        
        # Send data
        data_bytes = json.dumps(request_data).encode()
        s.sendall(len(data_bytes).to_bytes(8, 'big'))
        s.sendall(data_bytes)
        
        # Receive response
        size_data = s.recv(8)
        size = int.from_bytes(size_data, 'big')
        
        response_data = b''
        while len(response_data) < size:
            packet = s.recv(4096)
            if not packet:
                break
            response_data += packet
            
        response = json.loads(response_data.decode())
        return response


def get_robot_position(env):
    return env.unwrapped.scene["robot"].data.root_pos_w[0].detach().cpu().numpy().copy()


def get_robot_pose(env):
    root_pose = env.unwrapped.scene["robot"].data.root_state_w[0, :7]
    return root_pose.detach().cpu().numpy().copy()


def get_oracle_return_pose(env, episode):
    reference_path = np.asarray(episode["reference_path"], dtype=np.float32)
    if len(reference_path) < 2:
        raise RuntimeError("Oracle return pose requires at least two reference path points.")

    current_pose = get_robot_pose(env)
    goal = reference_path[-1]
    previous = reference_path[-2]
    reverse_direction = previous[:2] - goal[:2]
    yaw = math.atan2(float(reverse_direction[1]), float(reverse_direction[0]))

    pose = current_pose.copy()
    pose[:2] = goal[:2]
    pose[2] = goal[2] + max(float(current_pose[2] - goal[2]), 0.25)
    pose[3:] = np.array(
        [math.cos(yaw / 2.0), 0.0, 0.0, math.sin(yaw / 2.0)],
        dtype=np.float32,
    )
    return pose


def oracle_anchor_segment_return_yaw(env, route_agent):
    route_anchors = [
        anchor for anchor in route_agent.anchors
        if anchor.metadata.get("world_pose") is not None
    ]
    if len(route_anchors) < 2:
        return None

    pose_xy = np.asarray(get_robot_position(env)[:2], dtype=np.float32)
    best_distance2 = None
    best_segment = None
    for a, b in zip(route_anchors[:-1], route_anchors[1:]):
        a_xy = np.asarray(a.metadata["world_pose"][:2], dtype=np.float32)
        b_xy = np.asarray(b.metadata["world_pose"][:2], dtype=np.float32)
        segment = b_xy - a_xy
        denom = float(np.dot(segment, segment))
        if denom <= 1e-9:
            continue
        t = float(np.clip(np.dot(pose_xy - a_xy, segment) / denom, 0.0, 1.0))
        projected = a_xy + t * segment
        distance2 = float(np.dot(pose_xy - projected, pose_xy - projected))
        if best_distance2 is None or distance2 < best_distance2:
            best_distance2 = distance2
            best_segment = (a, b)

    if best_segment is None:
        return None
    a, b = best_segment
    a_xy = np.asarray(a.metadata["world_pose"][:2], dtype=np.float32)
    b_xy = np.asarray(b.metadata["world_pose"][:2], dtype=np.float32)
    # Outbound segment direction is A_low -> A_high. Return direction is reversed.
    reverse_direction = a_xy - b_xy
    if float(np.dot(reverse_direction, reverse_direction)) <= 1e-9:
        return None
    yaw = math.atan2(float(reverse_direction[1]), float(reverse_direction[0]))
    return {
        "yaw_rad": float(yaw),
        "yaw_deg": float(math.degrees(yaw)),
        "segment_anchor_indices": [int(a.index), int(b.index)],
        "distance_to_segment_m": float(math.sqrt(max(0.0, best_distance2 or 0.0))),
    }


def align_return_yaw_to_anchor_segment(env, route_agent):
    alignment = oracle_anchor_segment_return_yaw(env, route_agent)
    if alignment is None:
        return None
    pose = get_robot_pose(env)
    before_yaw = pose_yaw(pose)
    yaw = alignment["yaw_rad"]
    aligned_pose = pose.copy()
    aligned_pose[3:] = np.asarray(
        [math.cos(yaw / 2.0), 0.0, 0.0, math.sin(yaw / 2.0)],
        dtype=np.float32,
    )
    reset_navigation_memory(env, aligned_pose)
    after_pose = get_robot_pose(env)
    yaw_delta_rad = float(signed_angle_diff(yaw, before_yaw))
    # 2026-07-04: this snap physically rotates the robot in place -- the
    # shadow/non-oracle dead-reckoning reference frozen by finalize_outbound()
    # just before this call must be rotated by the same amount, or it silently
    # disagrees with the robot's real orientation for the rest of the episode.
    # See RouteMemoryAgent.correct_return_start_yaw's docstring.
    route_agent.correct_return_start_yaw(yaw_delta_rad)
    alignment.update({
        "before_yaw_rad": float(before_yaw),
        "before_yaw_deg": float(math.degrees(before_yaw)),
        "after_yaw_rad": float(pose_yaw(after_pose)),
        "after_yaw_deg": float(math.degrees(pose_yaw(after_pose))),
        "yaw_delta_rad": yaw_delta_rad,
        "yaw_delta_deg": float(math.degrees(yaw_delta_rad)),
        "pose_after_alignment": [float(x) for x in after_pose],
    })
    return alignment


def pose_yaw(pose):
    quat = pose[3:]
    _, _, yaw = quat2eulers(float(quat[0]), float(quat[1]), float(quat[2]), float(quat[3]))
    return yaw


def signed_angle_diff(a, b):
    return math.atan2(math.sin(a - b), math.cos(a - b))


def pose_delta_body(previous_pose, current_pose):
    previous_pose = np.asarray(previous_pose, dtype=np.float32)
    current_pose = np.asarray(current_pose, dtype=np.float32)
    previous_yaw = pose_yaw(previous_pose)
    current_yaw = pose_yaw(current_pose)
    delta_world = current_pose[:2] - previous_pose[:2]
    cos_yaw = math.cos(previous_yaw)
    sin_yaw = math.sin(previous_yaw)
    return [
        float(cos_yaw * delta_world[0] + sin_yaw * delta_world[1]),
        float(-sin_yaw * delta_world[0] + cos_yaw * delta_world[1]),
        float(signed_angle_diff(current_yaw, previous_yaw)),
    ]


def isaac_relative_start_progress(env, start_pos):
    pose = get_robot_pose(env)
    position = get_robot_position(env)
    yaw = pose_yaw(pose)
    dx_world = float(start_pos[0] - position[0])
    dy_world = float(start_pos[1] - position[1])
    cos_yaw = math.cos(yaw)
    sin_yaw = math.sin(yaw)
    target_dx = float(cos_yaw * dx_world + sin_yaw * dy_world)
    target_dy = float(-sin_yaw * dx_world + cos_yaw * dy_world)
    distance = float(math.hypot(target_dx, target_dy))
    bearing = float(math.degrees(math.atan2(target_dy, target_dx))) if distance > 1e-6 else 0.0
    current_pose_from_start = [
        float(position[0] - start_pos[0]),
        float(position[1] - start_pos[1]),
        float(yaw),
    ]
    return RelativeStartProgress(
        target_dx_m=target_dx,
        target_dy_m=target_dy,
        distance_to_start_m=distance,
        bearing_to_start_deg=bearing,
        current_pose_from_start=current_pose_from_start,
        return_pose_from_return_start=[],
        return_start_pose_from_start=[],
    )


def direct_oracle_start_progress(env, start_pos):
    progress = isaac_relative_start_progress(env, start_pos)
    progress.source = "direct_oracle_start"
    progress.relocalization_backend = "oracle_direct"
    progress.relocalization_confidence = 1.0
    progress.filter_std_m = None
    return progress


def _body_frame_vector_to_world_point(env, start_pos, target_xy):
    pose = get_robot_pose(env)
    position = get_robot_position(env)
    yaw = pose_yaw(pose)
    dx_world = float(target_xy[0] - position[0])
    dy_world = float(target_xy[1] - position[1])
    cos_yaw = math.cos(yaw)
    sin_yaw = math.sin(yaw)
    target_dx = float(cos_yaw * dx_world + sin_yaw * dy_world)
    target_dy = float(-sin_yaw * dx_world + cos_yaw * dy_world)
    distance = float(math.hypot(target_dx, target_dy))
    bearing = float(math.degrees(math.atan2(target_dy, target_dx))) if distance > 1e-6 else 0.0
    current_pose_from_start = [
        float(position[0] - start_pos[0]),
        float(position[1] - start_pos[1]),
        float(yaw),
    ]
    return target_dx, target_dy, distance, bearing, current_pose_from_start


def _project_current_position_to_oracle_route(env, anchors):
    pose_xy = np.asarray(get_robot_position(env)[:2], dtype=np.float32)
    route_anchors = [
        anchor for anchor in anchors
        if anchor.metadata.get("world_pose") is not None
    ]
    if not route_anchors:
        return None
    if len(route_anchors) == 1:
        return float(route_anchors[0].distance_from_start_m)

    best_distance2 = None
    best_route_s = float(route_anchors[-1].distance_from_start_m)
    for a, b in zip(route_anchors[:-1], route_anchors[1:]):
        a_xy = np.asarray(a.metadata["world_pose"][:2], dtype=np.float32)
        b_xy = np.asarray(b.metadata["world_pose"][:2], dtype=np.float32)
        segment = b_xy - a_xy
        denom = float(np.dot(segment, segment))
        if denom <= 1e-9:
            t = 0.0
        else:
            t = float(np.clip(np.dot(pose_xy - a_xy, segment) / denom, 0.0, 1.0))
        projected = a_xy + t * segment
        distance2 = float(np.dot(pose_xy - projected, pose_xy - projected))
        route_s = float(
            a.distance_from_start_m
            + t * (b.distance_from_start_m - a.distance_from_start_m)
        )
        if best_distance2 is None or distance2 < best_distance2:
            best_distance2 = distance2
            best_route_s = route_s
    return best_route_s


def direct_oracle_route_anchor_progress(env, start_pos, route_agent):
    if route_agent is None or not route_agent.anchors:
        return direct_oracle_start_progress(env, start_pos)

    current_s = _project_current_position_to_oracle_route(env, route_agent.anchors)
    if current_s is None:
        return direct_oracle_start_progress(env, start_pos)

    # Return follows the outbound route in reverse. Use the simulator/global
    # route position to pick an anchor ahead along that reverse route, not the
    # nearest/sideways anchor that can make the VLM spin in place.
    target_lookahead_m = max(
        1.0,
        float(getattr(route_agent, "route_progress_lookahead_m", getattr(route_agent, "anchor_spacing_m", 1.0))),
    )
    target_s = max(0.0, current_s - target_lookahead_m)
    target_anchor = route_agent.target_anchor_for_route_position(
        target_s,
        require_world_pose=True,
    )
    if target_anchor is None:
        return direct_oracle_start_progress(env, start_pos)

    target_xy = np.asarray(target_anchor.metadata["world_pose"][:2], dtype=np.float32)
    target_dx, target_dy, anchor_distance, anchor_bearing, current_pose_from_start = (
        _body_frame_vector_to_world_point(env, start_pos, target_xy)
    )
    anchor_remaining = float(target_anchor.route_remaining_to_start_m)
    return RelativeStartProgress(
        target_dx_m=target_dx,
        target_dy_m=target_dy,
        distance_to_start_m=float(anchor_distance + anchor_remaining),
        bearing_to_start_deg=anchor_bearing,
        current_pose_from_start=current_pose_from_start,
        return_pose_from_return_start=[],
        return_start_pose_from_start=[],
        source="direct_oracle_route_anchor",
        target_anchor_index=int(target_anchor.index),
        anchor_dx_m=target_dx,
        anchor_dy_m=target_dy,
        distance_to_anchor_m=anchor_distance,
        bearing_to_anchor_deg=anchor_bearing,
        anchor_route_remaining_m=anchor_remaining,
        anchor_heading_reliable=True,
        relocalization_confidence=1.0,
        relocalization_backend="oracle_direct_route_anchor",
        filter_std_m=None,
        oracle_route_current_s_m=float(current_s),
        oracle_route_target_s_m=float(target_s),
        oracle_route_lookahead_m=float(target_lookahead_m),
    )


def route_progress_override(source, env, start_pos, route_agent=None):
    if source == "isaac":
        return isaac_relative_start_progress(env, start_pos)
    if source == "oracle":
        return direct_oracle_route_anchor_progress(env, start_pos, route_agent)
    return None


def oracle_anchor_relocalization(env, route_agent):
    current_pose = get_robot_pose(env)
    current_yaw = pose_yaw(current_pose)
    best_anchor = None
    best_distance = None
    best_pose = None
    for anchor in route_agent.anchors:
        world_pose = anchor.metadata.get("world_pose")
        if world_pose is None:
            continue
        anchor_pose = np.asarray(world_pose, dtype=np.float32)
        distance = float(np.linalg.norm(anchor_pose[:2] - current_pose[:2]))
        if best_distance is None or distance < best_distance:
            best_anchor = anchor
            best_distance = distance
            best_pose = anchor_pose
    if best_anchor is None or best_pose is None:
        return None

    dx_world = float(best_pose[0] - current_pose[0])
    dy_world = float(best_pose[1] - current_pose[1])
    cos_yaw = math.cos(current_yaw)
    sin_yaw = math.sin(current_yaw)
    anchor_dx = float(cos_yaw * dx_world + sin_yaw * dy_world)
    anchor_dy = float(-sin_yaw * dx_world + cos_yaw * dy_world)
    anchor_dtheta = float(signed_angle_diff(pose_yaw(best_pose), current_yaw))
    return AnchorRelocalization(
        anchor_index=int(best_anchor.index),
        anchor_dx_m=anchor_dx,
        anchor_dy_m=anchor_dy,
        anchor_dtheta_rad=anchor_dtheta,
        confidence=1.0,
        backend="oracle_anchor",
    )




def summarize_pose_error(pose, reference_pose):
    if pose is None or reference_pose is None:
        return None
    pose = np.asarray(pose, dtype=np.float32)
    reference_pose = np.asarray(reference_pose, dtype=np.float32)
    return {
        "xy_error_m": float(np.linalg.norm(pose[:2] - reference_pose[:2])),
        "z_error_m": float(abs(float(pose[2]) - float(reference_pose[2]))),
        "yaw_error_rad": float(signed_angle_diff(pose_yaw(pose), pose_yaw(reference_pose))),
        "yaw_error_deg": float(math.degrees(signed_angle_diff(pose_yaw(pose), pose_yaw(reference_pose)))),
    }


def get_robot_velocity(env):
    return env.unwrapped.scene["robot"].data.root_vel_w[0].detach().cpu().numpy().copy()


def get_measured_action_delta(pose_before, pose_after):
    """Body-frame planar (dx, dy, dtheta) directly measured from the robot's
    actual position/orientation change over one control step, instead of
    assuming the commanded vlm_vel_commands were achieved exactly for the
    full step.

    2026-07-04: replaces the original 2026-07-03 implementation, which
    sampled root_vel_w once at the *end* of the control step and multiplied
    by control_dt -- implicitly assuming the robot's true velocity was
    constant across the whole ~20ms window (sim.dt=0.005, decimation=4).
    Gait dynamics (foot-strike transients, locomotion-policy tracking lag)
    routinely violate that assumption, and a 2026-07-04 ep187/680/994
    comparison against the commanded-velocity baseline showed 2 of 3
    episodes had *worse* dead-reckoning drift under the velocity-sampling
    version -- the single-instant sample was a noisier proxy for this
    step's displacement than the thing it was trying to approximate. A
    direct before/after pose difference (via the pre-existing, previously
    unused pose_delta_body helper) captures whatever actually happened
    during the step regardless of the true velocity profile inside it,
    removing that proxy error at the source. Still non-privileged in the
    sense that matters here: it's the same rigid-body pose a real onboard
    state estimator (IMU + leg odometry) would track, not information about
    the environment/route the agent isn't supposed to have.

    2026-07-04 correction: pose_before/pose_after are still read from Isaac's
    exact, noise-free root_state_w -- this is a reasonable stand-in for a
    *perfect* state estimator, but it is not actually derived from anything
    Go2's own sensors report. See get_leg_odometry_action_delta below for a
    version built from the robot's own noisy joint encoders + IMU + contact
    sensor instead, for when the distinction matters.
    """
    return pose_delta_body(pose_before, pose_after)


_LEG_ODOMETRY_INDEX_CACHE: dict = {}


def _leg_odometry_indices(env):
    """One-time lookup of the body/joint indices get_leg_odometry_action_delta
    needs, cached by env id since these never change during an episode.

    Returns a dict with, per leg (FL/FR/RL/RR): the foot's index into the
    articulation's own body list (for Jacobian indexing and body_pos_w
    lookup), and the 3 joint indices (hip/thigh/calf) into
    robot.data.joint_vel's own ordering (which mdp.joint_vel_rel preserves
    into the noisy "proprio" observation this function reads).
    """
    key = id(env)
    cached = _LEG_ODOMETRY_INDEX_CACHE.get(key)
    if cached is not None:
        return cached
    robot = env.unwrapped.scene["robot"]
    legs = {}
    for leg in ("FL", "FR", "RL", "RR"):
        body_ids, _ = robot.find_bodies(f"{leg}_foot")
        joint_ids, joint_names = robot.find_joints(
            [f"{leg}_hip_joint", f"{leg}_thigh_joint", f"{leg}_calf_joint"],
            preserve_order=True,
        )
        legs[leg] = {
            "body_id": int(body_ids[0]),
            "joint_ids": [int(i) for i in joint_ids],
        }
    result = {
        "legs": legs,
        "is_fixed_base": bool(robot.is_fixed_base),
    }
    _LEG_ODOMETRY_INDEX_CACHE[key] = result
    if os.environ.get("ROUTE_MEMORY_LEG_ODOMETRY_DEBUG"):
        print(f"[leg_odometry_debug] is_fixed_base={result['is_fixed_base']}", flush=True)
        for leg_name, leg in legs.items():
            print(
                f"[leg_odometry_debug] leg={leg_name} body_id={leg['body_id']} joint_ids={leg['joint_ids']}",
                flush=True,
            )
        print(f"[leg_odometry_debug] robot.body_names={robot.body_names}", flush=True)
        print(f"[leg_odometry_debug] robot.joint_names={robot.joint_names}", flush=True)
    return result


def get_leg_odometry_action_delta(
    env,
    control_dt,
    infos,
    ground_clearance_threshold_m: float = 0.05,
):
    """Body-frame planar (dx, dy, dtheta) estimated from Go2's own onboard-
    realistic sensing -- noisy joint velocities (leg encoders) run through
    each stance leg's Jacobian, fused with noisy base angular velocity (IMU
    gyro) for yaw rate -- instead of reading Isaac's privileged root_vel_w/
    root_state_w the way get_measured_action_delta does.

    2026-07-04: this is the first action_delta source that is genuinely not
    reading from Isaac's exact simulator state for the linear-velocity part.
    go2_matterport_vision_cfg.py's PolicyCfg/ProprioCfg groups apply Unoise
    to base_ang_vel/base_rpy/joint_pos/joint_vel before the policy (or this
    function) ever sees them -- read from infos["observations"]["proprio"],
    NOT robot.data.joint_vel directly, which stays exact/noise-free and would
    silently defeat the point. base_lin_vel is deliberately never observed
    by the policy at all (commented out in that same config) -- matching a
    real robot, which has no direct body linear-velocity sensor -- so linear
    velocity has no shortcut here and must be estimated from stance-leg
    kinematics, the same "zero-slip stance foot" assumption every real
    legged-robot state estimator (Cheetah-3, ANYmal, etc.) relies on: if a
    foot is in contact, treat it as stationary in the world, so the body's
    velocity (in its own frame) is the negative of that foot's velocity
    relative to the body. Feet currently in swing phase contribute nothing
    (their motion relative to the body reflects the gait, not the body's own
    travel) and are excluded; if all 4 feet are briefly airborne (a bound/
    jump gait transient), this falls back to zero velocity for that one step
    rather than guessing.

    Each stance foot's body-frame velocity comes from
    ``root_physx_view.get_jacobians()`` (PhysX's own geometric Jacobian for
    that body, computed from the actual loaded URDF/USD leg geometry -- no
    hand-derived Go2 kinematics needed, and already used elsewhere in this
    same IsaacLab checkout for differential IK) applied to that leg's 3
    noisy joint velocities.

    2026-07-04, second revision -- stance detection switched from contact
    force to ground-clearance height: a live all-bodies diagnostic (every
    body's net_forces_w, not just feet) showed PhysX contact-force reporting
    reads exactly 0 N for literally every body on this articulation,
    throughout an entire episode -- not a feet-specific issue, not a
    threshold-tuning issue. Root cause (found by reading
    matterport_importer.py): the Matterport terrain only gets
    ``define_collision_properties`` (collision *response*, why the robot
    doesn't fall through the floor) at load time, never
    ``activate_contact_sensors``/``PhysxContactReportAPI`` (collision
    *reporting*) -- and that latter helper only patches prims that already
    have ``UsdPhysics.RigidBodyAPI``, which static terrain collision
    geometry normally doesn't have, so it's not a one-line fix on the
    terrain side either. Contact force is a dead signal in this environment
    end to end; this function no longer depends on it.

    Ground clearance is instead estimated purely kinematically: each foot's
    world position comes from ``robot.data.body_pos_w`` (Isaac's computed
    forward kinematics from the articulation's actual joint angles -- a
    fixed, deterministic geometric function of joint angles, not a
    privileged *dynamics* shortcut the way root_vel_w is, so this is the
    same thing a real onboard computer would get from its own known leg
    geometry plus its own measured joint angles). Local ground height at
    that foot's (x, y) comes from the ``height_scanner`` RayCaster already
    in this scene (a downward-facing rangefinder grid -- 10 cm resolution,
    1.6x1.0 m footprint centered on the base -- exactly the kind of sensor a
    real legged robot uses for terrain-relative state estimation, already
    read elsewhere in this codebase for the locomotion policy's own height-
    map observation): nearest-neighbor match each foot's (x, y) to a ray
    hit, and treat the foot as in stance if it is within
    ``ground_clearance_threshold_m`` of that ray's hit height. Provisional
    and not yet validated end to end (this replaces, rather than fixes, the
    contact-force version that was tested and found wanting).
    """
    idx = _leg_odometry_indices(env)
    robot = env.unwrapped.scene["robot"]
    height_scanner = env.unwrapped.scene["height_scanner"]

    proprio = infos["observations"]["proprio"][0].detach().cpu().numpy()
    # Order fixed by go2_matterport_vision_cfg.py's PolicyCfg/ProprioCfg group
    # (verified against the printed "Active Observation Terms" table):
    # base_ang_vel(3), base_rpy(3), velocity_commands(3), joint_pos(12), joint_vel(12), actions(12).
    noisy_base_ang_vel_z = float(proprio[2])
    noisy_joint_vel = proprio[21:33]

    jacobians = robot.root_physx_view.get_jacobians()[0]  # (num_bodies[-1 if floating], 6, num_dofs)
    body_pos_w = robot.data.body_pos_w[0].detach().cpu().numpy()  # (num_bodies, 3)
    ray_hits_w = height_scanner.data.ray_hits_w[0].detach().cpu().numpy()  # (num_rays, 3)
    ray_xy = ray_hits_w[:, :2]

    stance_body_vels = []
    ground_clearances = {}
    for leg_name, leg in idx["legs"].items():
        foot_pos = body_pos_w[leg["body_id"]]
        dist2 = np.sum((ray_xy - foot_pos[:2]) ** 2, axis=1)
        nearest_ray = int(np.argmin(dist2))
        ground_z = float(ray_hits_w[nearest_ray, 2])
        clearance = float(foot_pos[2]) - ground_z
        ground_clearances[leg_name] = clearance
        if clearance > ground_clearance_threshold_m:
            continue  # swing phase: foot is above the locally-estimated ground
        jacobi_body_idx = leg["body_id"] - 1 if idx["is_fixed_base"] else leg["body_id"]
        joint_ids = leg["joint_ids"]
        j_linear = jacobians[jacobi_body_idx, 0:3, :][:, joint_ids].detach().cpu().numpy()
        leg_joint_vel = noisy_joint_vel[joint_ids]
        foot_vel_body = j_linear @ leg_joint_vel
        stance_body_vels.append(-foot_vel_body[:2])

    if stance_body_vels:
        vx, vy = np.mean(stance_body_vels, axis=0)
    else:
        # No leg currently passes the stance-dwell gate (e.g. a brief all-feet-
        # airborne instant). Hold the previous estimate rather than snapping to
        # zero -- a zero-velocity step here would be a real, systematic
        # under-count of distance travelled if this fires often, not just a
        # one-off approximation.
        vx, vy = get_leg_odometry_action_delta._last_vel.get(id(env), (0.0, 0.0))

    get_leg_odometry_action_delta._last_vel[id(env)] = (vx, vy)

    # Lightweight diagnostic, gated by ROUTE_MEMORY_LEG_ODOMETRY_DEBUG so it
    # doesn't spam every run: stance-leg count, per-leg ground clearance, and
    # the estimate vs. Isaac's exact root_vel_w for the *same instant*
    # (ground truth, printed for comparison only -- never fed back into the
    # returned estimate).
    if os.environ.get("ROUTE_MEMORY_LEG_ODOMETRY_DEBUG") and get_leg_odometry_action_delta._debug_step[0] % 50 == 0:
        true_pose = get_robot_pose(env)
        true_yaw = pose_yaw(true_pose)
        true_vel_w = robot.data.root_vel_w[0, :2].detach().cpu().numpy()
        cos_y, sin_y = math.cos(true_yaw), math.sin(true_yaw)
        true_vx_body = cos_y * float(true_vel_w[0]) + sin_y * float(true_vel_w[1])
        true_vy_body = -sin_y * float(true_vel_w[0]) + cos_y * float(true_vel_w[1])
        true_yaw_rate = float(robot.data.root_vel_w[0, 5])
        n_stance = len(stance_body_vels)
        print(
            f"[leg_odometry_debug] ground_clearances_m={{{', '.join(f'{k}: {v:.4f}' for k, v in ground_clearances.items())}}}",
            flush=True,
        )
        print(
            f"[leg_odometry_debug] step={get_leg_odometry_action_delta._debug_step[0]} "
            f"n_stance={n_stance} est_vxvy_body=({vx:.3f},{vy:.3f}) true_vxvy_body=({true_vx_body:.3f},{true_vy_body:.3f}) "
            f"est_yaw_rate={noisy_base_ang_vel_z:.3f} true_yaw_rate={true_yaw_rate:.3f}",
            flush=True,
        )
    get_leg_odometry_action_delta._debug_step[0] += 1

    return [
        float(vx) * control_dt,
        float(vy) * control_dt,
        noisy_base_ang_vel_z * control_dt,
    ]


get_leg_odometry_action_delta._last_vel = {}
get_leg_odometry_action_delta._debug_step = [0]


def capture_route_memory_diagnostic_frame(env, route_agent, current_descriptor, step, output_dir):
    """Dump one diagnostic frame for offline rendering by
    plot_route_memory_diagnostic_frames.py: the robot's current world pose
    and local-map points, plus every recorded anchor's world pose and
    local-map points. No ICP/matching is computed here -- that's pure numpy
    with no Isaac Sim dependency, so it's deferred entirely to the offline
    script, keeping this live-capture hook as small as possible.

    2026-07-03: replaces the old capture-only-the-anchor-Scan-Context-picked
    approach (plot_anchor_match_diagnostics.py) for cases where you want to
    see the match against *every* recorded anchor, not just the one the
    live backend happened to select.

    2026-07-04: also saves the height-preserving xyz points (undownsampled),
    since Scan Context needs height for a non-degenerate descriptor and
    would otherwise silently fall back to its flat/uninformative height
    channel -- see descriptor_local_map_points_xyz's docstring. Not
    voxel-downsampled, matching how scan_context_anchor_relocalization itself
    builds the descriptor (downsampling would discard exactly the
    tallest-point-per-cell information Scan Context relies on).
    """
    current_points = descriptor_local_map_points(current_descriptor)
    current_points = voxel_downsample_2d(current_points) if current_points is not None else None
    current_points_xyz = descriptor_local_map_points_xyz(current_descriptor)
    frame = {
        "step": int(step),
        "robot_world_pose": [float(x) for x in get_robot_pose(env)],
        "current_local_map_points_body": current_points.tolist() if current_points is not None else None,
        "current_local_map_points_xyz_body": (
            current_points_xyz.tolist() if current_points_xyz is not None else None
        ),
        "anchors": [],
    }
    for anchor in route_agent.anchors:
        anchor_points = descriptor_local_map_points(anchor.descriptor)
        anchor_points = voxel_downsample_2d(anchor_points) if anchor_points is not None else None
        anchor_points_xyz = descriptor_local_map_points_xyz(anchor.descriptor)
        world_pose = anchor.metadata.get("world_pose")
        frame["anchors"].append({
            "index": int(anchor.index),
            "distance_from_start_m": float(anchor.distance_from_start_m),
            "world_pose": [float(x) for x in world_pose] if world_pose is not None else None,
            "local_map_points_body": anchor_points.tolist() if anchor_points is not None else None,
            "local_map_points_xyz_body": (
                anchor_points_xyz.tolist() if anchor_points_xyz is not None else None
            ),
        })
    os.makedirs(output_dir, exist_ok=True)
    with open(os.path.join(output_dir, f"frame_step{int(step):06d}.json"), "w", encoding="utf-8") as f:
        json.dump(frame, f)


def capture_icp_replay_anchors(route_agent, output_dir):
    """Dump every recorded anchor's ground-truth world pose + raw (undownsampled)
    local-map xyz points once, right after finalize_outbound() (anchors never
    change again during return). Paired with capture_icp_replay_step's
    per-return-step robot captures, this is enough to replay any ICP/LiDAR-
    matching method offline against the exact same point clouds a live rerun
    would see -- return-phase robot motion is oracle-controlled regardless of
    this flag, so the recorded ground-truth trajectory is the real one, not an
    approximation. Written to output_dir/anchors.json, a single small file
    (anchor count is small, unlike the per-step captures) -- not embedded in
    the big measurement JSON.
    """
    anchors = []
    for anchor in route_agent.anchors:
        anchor_points_xyz = descriptor_local_map_points_xyz(anchor.descriptor)
        world_pose = anchor.metadata.get("world_pose")
        anchors.append({
            "index": int(anchor.index),
            "distance_from_start_m": float(anchor.distance_from_start_m),
            "world_pose": [float(x) for x in world_pose] if world_pose is not None else None,
            "local_map_points_xyz_body": (
                anchor_points_xyz.tolist() if anchor_points_xyz is not None else None
            ),
        })
    os.makedirs(output_dir, exist_ok=True)
    with open(os.path.join(output_dir, "anchors.json"), "w", encoding="utf-8") as f:
        json.dump({"anchors": anchors}, f)


def capture_icp_replay_step(env, current_descriptor, step, output_dir):
    """Dump the robot's ground-truth world pose + raw (undownsampled) local-map
    xyz points for one return-phase environment step, to
    output_dir/steps/frame_step{N:06d}.json. Called every return step when
    --capture_icp_replay_dataset is on -- one small file per step, same safe
    pattern as capture_route_memory_diagnostic_frame, so a full episode's
    worth of frames never needs to be held in memory or embedded in the big
    measurement JSON at once.
    """
    current_points_xyz = descriptor_local_map_points_xyz(current_descriptor)
    frame = {
        "step": int(step),
        "robot_world_pose": [float(x) for x in get_robot_pose(env)],
        "local_map_points_xyz_body": (
            current_points_xyz.tolist() if current_points_xyz is not None else None
        ),
    }
    steps_dir = os.path.join(output_dir, "steps")
    os.makedirs(steps_dir, exist_ok=True)
    with open(os.path.join(steps_dir, f"frame_step{int(step):06d}.json"), "w", encoding="utf-8") as f:
        json.dump(frame, f)


def nearest_path_point(position_xy, path_xy):
    if len(path_xy) == 0:
        return {"index": None, "distance_m": None}
    deltas = path_xy - np.asarray(position_xy, dtype=np.float32)[None, :]
    distances = np.linalg.norm(deltas, axis=1)
    index = int(np.argmin(distances))
    return {
        "index": index,
        "distance_m": float(distances[index]),
    }


def make_trajectory_record(
    step,
    phase,
    env,
    command,
    stream_output,
    start_pos,
    goal_pos,
    reference_path_xy,
    return_path_xy,
    last_vlm_step,
    route_memory_progress=None,
):
    pose = get_robot_pose(env)
    position = get_robot_position(env)
    velocity = get_robot_velocity(env)
    yaw = pose_yaw(pose)
    return {
        "step": int(step),
        "phase": phase,
        "position": [float(x) for x in position],
        "quaternion_wxyz": [float(x) for x in pose[3:]],
        "yaw_rad": float(yaw),
        "yaw_deg": float(math.degrees(yaw)),
        "root_velocity": [float(x) for x in velocity],
        "speed_mps": float(np.linalg.norm(velocity[:2])),
        "command": [float(x) for x in command],
        "last_vlm_step": int(last_vlm_step) if last_vlm_step is not None else None,
        "last_vlm_output": stream_output,
        "distance_to_start_m": float(np.linalg.norm(position[:2] - start_pos[:2])),
        "distance_to_outbound_goal_m": float(np.linalg.norm(position[:2] - goal_pos[:2])),
        "nearest_reference_path": nearest_path_point(position[:2], reference_path_xy),
        "nearest_return_path": nearest_path_point(position[:2], return_path_xy),
        "route_memory": route_memory_progress,
    }


def route_progress_to_record(progress, configured_source):
    if progress is None:
        return None
    return {
        "source": progress.source,
        "configured_source": configured_source,
        "target_dx_m": progress.target_dx_m,
        "target_dy_m": progress.target_dy_m,
        "distance_to_start_m": progress.distance_to_start_m,
        "bearing_to_start_deg": progress.bearing_to_start_deg,
        "current_pose_from_start": progress.current_pose_from_start,
        "return_pose_from_return_start": progress.return_pose_from_return_start,
        "return_start_pose_from_start": progress.return_start_pose_from_start,
        "target_anchor_index": progress.target_anchor_index,
        "anchor_dx_m": progress.anchor_dx_m,
        "anchor_dy_m": progress.anchor_dy_m,
        "distance_to_anchor_m": progress.distance_to_anchor_m,
        "bearing_to_anchor_deg": progress.bearing_to_anchor_deg,
        "anchor_route_remaining_m": progress.anchor_route_remaining_m,
        "anchor_heading_reliable": progress.anchor_heading_reliable,
        "relocalization_confidence": progress.relocalization_confidence,
        "relocalization_backend": progress.relocalization_backend,
        "filter_std_m": progress.filter_std_m,
        "oracle_route_current_s_m": progress.oracle_route_current_s_m,
        "oracle_route_target_s_m": progress.oracle_route_target_s_m,
        "oracle_route_lookahead_m": progress.oracle_route_lookahead_m,
    }


def route_progress_alignment_record(primary, shadow):
    if primary is None or shadow is None:
        return None
    primary_anchor = primary.target_anchor_index
    shadow_anchor = shadow.target_anchor_index
    anchor_index_error = (
        None if primary_anchor is None or shadow_anchor is None
        else int(shadow_anchor) - int(primary_anchor)
    )
    bearing_error = None
    if primary.bearing_to_anchor_deg is not None and shadow.bearing_to_anchor_deg is not None:
        bearing_error = float(
            math.degrees(math.atan2(
                math.sin(math.radians(shadow.bearing_to_anchor_deg - primary.bearing_to_anchor_deg)),
                math.cos(math.radians(shadow.bearing_to_anchor_deg - primary.bearing_to_anchor_deg)),
            ))
        )
    distance_error = None
    if primary.distance_to_anchor_m is not None and shadow.distance_to_anchor_m is not None:
        distance_error = float(shadow.distance_to_anchor_m - primary.distance_to_anchor_m)
    target_vector_error = None
    if (
        primary.target_dx_m is not None and primary.target_dy_m is not None
        and shadow.target_dx_m is not None and shadow.target_dy_m is not None
    ):
        target_vector_error = float(math.hypot(
            shadow.target_dx_m - primary.target_dx_m,
            shadow.target_dy_m - primary.target_dy_m,
        ))
    return {
        "primary_source": primary.source,
        "shadow_source": shadow.source,
        "anchor_index_error": anchor_index_error,
        "bearing_to_anchor_error_deg": bearing_error,
        "distance_to_anchor_error_m": distance_error,
        "target_vector_error_m": target_vector_error,
        "shadow_confidence": shadow.relocalization_confidence,
        "shadow_filter_std_m": shadow.filter_std_m,
        "shadow_backend": shadow.relocalization_backend,
    }


def _to_numpy_descriptor(value):
    if hasattr(value, "detach"):
        value = value.detach().cpu().numpy()
    if isinstance(value, np.ndarray) and value.shape[0] == 1:
        value = value[0]
    if isinstance(value, np.ndarray):
        return value.copy()
    return value


def denormalize_depth_obs(value, near_clip=0.3, far_clip=5.0):
    depth = _to_numpy_descriptor(value)
    if isinstance(depth, np.ndarray):
        depth = np.asarray(depth, dtype=np.float32)
        depth = np.squeeze(depth)
        if depth.size > 0 and np.nanmin(depth) >= -0.55 and np.nanmax(depth) <= 0.55:
            depth = (depth + 0.5) * (far_clip - near_clip) + near_clip
    return depth


def camera_intrinsics_from_env(env, width=512, height=512):
    try:
        sensor = env.unwrapped.scene.sensors["rgbd_camera"]
        matrix = sensor.data.intrinsic_matrices.detach().cpu().numpy()[0]
        return matrix.astype(np.float32).copy()
    except Exception:
        focal = 0.5 * float(width) / math.tan(math.radians(90.0) / 2.0)
        return np.asarray(
            [[focal, 0.0, width / 2.0], [0.0, focal, height / 2.0], [0.0, 0.0, 1.0]],
            dtype=np.float32,
        )


def camera_pose_from_env(env):
    try:
        sensor = env.unwrapped.scene.sensors["rgbd_camera"]
        position = sensor.data.pos_w.detach().cpu().numpy()[0]
        quat = sensor.data.quat_w_world.detach().cpu().numpy()[0]
        return {
            "position_w": position.astype(np.float32).copy(),
            "quat_wxyz": quat.astype(np.float32).copy(),
        }
    except Exception:
        return None


def camera_extrinsic_body_from_env(env):
    try:
        camera_pose = camera_pose_from_env(env)
        if camera_pose is None:
            return None
        robot_pose = get_robot_pose(env)
        robot_position = np.asarray(robot_pose[:3], dtype=np.float32)
        robot_quat = np.asarray(robot_pose[3:7], dtype=np.float32)
        robot_rotation = _quat_wxyz_to_matrix(robot_quat)
        camera_rotation = _quat_wxyz_to_matrix(camera_pose["quat_wxyz"])
        rotation_body_camera = robot_rotation.T @ camera_rotation
        position_body = robot_rotation.T @ (camera_pose["position_w"] - robot_position)
        return {
            "rotation_body_camera": rotation_body_camera.astype(np.float32).copy(),
            "position_body": position_body.astype(np.float32).copy(),
        }
    except Exception:
        return None


def rear_camera_intrinsics_from_env(env, width=512, height=512):
    try:
        sensor = env.unwrapped.scene.sensors["rear_rgbd_camera"]
        matrix = sensor.data.intrinsic_matrices.detach().cpu().numpy()[0]
        return matrix.astype(np.float32).copy()
    except Exception:
        return camera_intrinsics_from_env(env, width, height)


def rear_camera_pose_from_env(env):
    try:
        sensor = env.unwrapped.scene.sensors["rear_rgbd_camera"]
        position = sensor.data.pos_w.detach().cpu().numpy()[0]
        quat = sensor.data.quat_w_world.detach().cpu().numpy()[0]
        return {
            "position_w": position.astype(np.float32).copy(),
            "quat_wxyz": quat.astype(np.float32).copy(),
        }
    except Exception:
        return None


def rear_camera_extrinsic_body_from_env(env):
    try:
        rear_pose = rear_camera_pose_from_env(env)
        if rear_pose is None:
            return None
        robot_pose = get_robot_pose(env)
        robot_position = np.asarray(robot_pose[:3], dtype=np.float32)
        robot_quat = np.asarray(robot_pose[3:7], dtype=np.float32)
        robot_rotation = _quat_wxyz_to_matrix(robot_quat)
        rear_rotation = _quat_wxyz_to_matrix(rear_pose["quat_wxyz"])
        rotation_body_rear = robot_rotation.T @ rear_rotation
        position_body_rear = robot_rotation.T @ (rear_pose["position_w"] - robot_position)
        return {
            "rotation_body_camera": rotation_body_rear.astype(np.float32).copy(),
            "position_body": position_body_rear.astype(np.float32).copy(),
        }
    except Exception:
        return None


def local_map_descriptor_from_env(env):
    """Best-effort local map extraction from Isaac sensors.

    Real LiDAR/RayCaster integrations should expose body-frame obstacle points
    as ``local_map_points_body``.  The fallback below handles common IsaacLab
    RayCaster data fields and filters ground hits later in ``local_map.py``.

    2026-07-02 fix: the scene's actual room-mapping sensor is registered as
    ``lidar_sensor`` (32-channel, 360-degree horizontal FOV, ~2880 rays/scan --
    see go2_matterport_vision_cfg.py) but this lookup never included that exact
    name, only "lidar"/"local_lidar"/"ray_caster"/"height_scanner". Confirmed
    via a live diagnostic run that this silently fell through to
    "height_scanner" instead -- a small downward-facing 1.6x1.0 m gait/terrain
    RayCaster (~160 rays, meant for locomotion, mounted 20 m above the robot
    and cast straight down) that was never intended for room-scale geometry.
    Every LiDAR-based anchor-matching backend this project has built
    (local_map_icp, Scan Context and everything layered on top of them) has
    therefore been running on a ~2 m-radius, ~560-point foot-terrain scan
    instead of the intended room-scale LiDAR. ``lidar_sensor`` now takes
    priority; ``height_scanner`` is kept only as a last-resort fallback for
    scene configs that genuinely lack a dedicated LiDAR sensor.
    """
    try:
        sensors = getattr(env.unwrapped.scene, "sensors", {})
    except Exception:
        return None
    sensor = None
    sensor_name_used = None
    # 2026-07-03: route_memory_lidar (a dedicated RayCaster, separate from
    # lidar_sensor) now takes priority. lidar_sensor is also the locomotion
    # policy's height-map observation input (ObservationsCfg.PolicyCfg in
    # go2_matterport_vision_cfg.py) and must keep the ray geometry its
    # checkpoint was trained on -- narrowing its vertical_fov_range to fix
    # route-memory's obstacle-band coverage caused reproducible early falls
    # (see that file's comment on lidar_sensor). route_memory_lidar carries
    # the improved (symmetric, higher-resolution) geometry instead; scenes
    # without it fall back to lidar_sensor unchanged.
    for name in ("route_memory_lidar", "lidar_sensor", "lidar", "local_lidar", "ray_caster", "height_scanner"):
        try:
            if name in sensors:
                sensor = sensors[name]
                sensor_name_used = name
                break
        except Exception:
            continue
    if not getattr(local_map_descriptor_from_env, "_diag_sensor_printed", False):
        print(f"[DIAG] local_map_descriptor_from_env: using sensor name='{sensor_name_used}' (available: {list(sensors.keys())})")
        local_map_descriptor_from_env._diag_sensor_printed = True
    if sensor is None:
        return None
    hits = None
    try:
        data = sensor.data
        for attr in ("ray_hits_w", "pointcloud_w", "points_w"):
            value = getattr(data, attr, None)
            if value is not None:
                hits = _to_numpy_descriptor(value)
                break
    except Exception:
        hits = None
    if not isinstance(hits, np.ndarray):
        return None
    hits = np.asarray(hits, dtype=np.float32)
    if hits.ndim == 3:
        hits = hits[0]
    if hits.ndim != 2 or hits.shape[1] < 3:
        return None
    if not getattr(local_map_descriptor_from_env, "_diag_per_channel_printed", False):
        # 2026-07-03: sanity-check vertical_fov_range=(0.0, 90.0) on go2_matterport_vision_cfg.py's
        # lidar_sensor -- read literally (0deg=horizontal, 90deg=straight up, per IsaacLab's
        # linspace(vertical_fov_range[0], vertical_fov_range[1], channels) convention), every
        # channel would sit between horizontal and straight-up with none pointed down, which would
        # be a bad match for the height-band obstacle filter (z in [-0.20, 1.80] m) this pipeline
        # relies on. The sensor offset carries a non-identity rotation quaternion that could
        # compensate for this, so check the RAW per-channel ray hits directly instead of trusting
        # the two config numbers.
        try:
            channels = int(getattr(sensor.cfg.pattern_cfg, "channels", 32))
        except Exception:
            channels = 32
        try:
            robot_pose_diag = get_robot_pose(env)
            robot_position_diag = np.asarray(robot_pose_diag[:3], dtype=np.float32)
            robot_rotation_diag = _quat_wxyz_to_matrix(np.asarray(robot_pose_diag[3:7], dtype=np.float32))
            if hits.shape[0] % channels == 0:
                per_channel = hits.reshape(channels, -1, hits.shape[1])
                lines = []
                for ch in range(channels):
                    ch_hits = per_channel[ch]
                    ch_valid = np.isfinite(ch_hits).all(axis=1)
                    ch_finite = ch_hits[ch_valid]
                    if len(ch_finite) == 0:
                        lines.append(f"  channel {ch:>2}: 0/{ch_hits.shape[0]} finite hits")
                        continue
                    ch_body = (robot_rotation_diag.T @ (ch_finite[:, :3] - robot_position_diag).T).T
                    z_body = ch_body[:, 2]
                    in_band = int(((z_body >= -0.20) & (z_body <= 1.80)).sum())
                    lines.append(
                        f"  channel {ch:>2}: {len(ch_finite)}/{ch_hits.shape[0]} finite hits, "
                        f"z_body range=({float(z_body.min()):.2f},{float(z_body.max()):.2f}), "
                        f"in_obstacle_band[-0.20,1.80]={in_band}"
                    )
                print(f"[DIAG] local_map_descriptor_from_env: per-channel breakdown (channels={channels}):")
                print("\n".join(lines))
            else:
                print(
                    f"[DIAG] local_map_descriptor_from_env: raw hit count {hits.shape[0]} not divisible "
                    f"by channels={channels}, skipping per-channel breakdown"
                )
        except Exception as exc:
            print(f"[DIAG] local_map_descriptor_from_env: per-channel breakdown failed: {exc}")
        local_map_descriptor_from_env._diag_per_channel_printed = True
    valid = np.isfinite(hits).all(axis=1)
    hits = hits[valid]
    if len(hits) == 0:
        return None
    robot_pose = get_robot_pose(env)
    robot_position = np.asarray(robot_pose[:3], dtype=np.float32)
    robot_rotation = _quat_wxyz_to_matrix(np.asarray(robot_pose[3:7], dtype=np.float32))
    points_body = (robot_rotation.T @ (hits[:, :3] - robot_position).T).T.astype(np.float32)
    if not getattr(local_map_descriptor_from_env, "_diag_points_printed", False):
        xy = points_body[:, :2]
        z = points_body[:, 2]
        print(
            f"[DIAG] local_map_descriptor_from_env: points_body count={len(points_body)} "
            f"x_range=({float(xy[:,0].min()):.2f},{float(xy[:,0].max()):.2f}) "
            f"y_range=({float(xy[:,1].min()):.2f},{float(xy[:,1].max()):.2f}) "
            f"z_range=({float(z.min()):.2f},{float(z.max()):.2f}) "
            f"radius_max={float(np.hypot(xy[:,0], xy[:,1]).max()):.2f}"
        )
        local_map_descriptor_from_env._diag_points_printed = True
    return {
        "local_map_points_body": points_body,
        "local_map_source": "isaac_sensor",
    }


def route_memory_descriptor_from_infos(infos, env=None):
    observations = infos.get("observations", {}) if isinstance(infos, dict) else {}
    descriptor = {}
    rgb_obs = observations.get("camera_obs")
    if isinstance(rgb_obs, dict):
        rgb_obs = rgb_obs.get("rgb_measurement")
    if rgb_obs is not None:
        rgb = _to_numpy_descriptor(rgb_obs)
        if isinstance(rgb, np.ndarray):
            rgb = np.asarray(rgb)
            if rgb.ndim == 3:
                descriptor["rgb"] = rgb[:, :, :3].copy()

    route_obs = observations.get("route_memory_obs")
    if isinstance(route_obs, dict):
        for key, value in route_obs.items():
            descriptor[key] = _to_numpy_descriptor(value)
    elif route_obs is not None:
        descriptor["route_memory_obs"] = _to_numpy_descriptor(route_obs)

    local_map_obs = observations.get("local_map_obs")
    if isinstance(local_map_obs, dict):
        for key, value in local_map_obs.items():
            descriptor[f"local_map_{key}"] = _to_numpy_descriptor(value)
    elif local_map_obs is not None:
        descriptor["local_map_obs"] = _to_numpy_descriptor(local_map_obs)

    depth_obs = observations.get("depth_obs")
    if isinstance(depth_obs, dict):
        for key, value in depth_obs.items():
            descriptor[f"depth_{key}"] = denormalize_depth_obs(value)
    elif depth_obs is not None:
        descriptor["depth_obs"] = denormalize_depth_obs(depth_obs)

    # Rear camera RGB
    rear_rgb_obs = observations.get("rear_camera_obs")
    if isinstance(rear_rgb_obs, dict):
        rear_rgb_obs = rear_rgb_obs.get("rgb_measurement")
    if rear_rgb_obs is not None:
        rear_rgb = _to_numpy_descriptor(rear_rgb_obs)
        if isinstance(rear_rgb, np.ndarray) and rear_rgb.ndim == 3:
            descriptor["rear_rgb"] = rear_rgb[:, :, :3].copy()

    # Rear camera depth
    rear_depth_obs = observations.get("rear_depth_obs")
    if isinstance(rear_depth_obs, dict):
        for key, value in rear_depth_obs.items():
            descriptor[f"rear_depth_{key}"] = denormalize_depth_obs(value)
    elif rear_depth_obs is not None:
        descriptor["rear_depth_obs"] = denormalize_depth_obs(rear_depth_obs)

    if env is not None:
        descriptor["camera_intrinsics"] = camera_intrinsics_from_env(env)
        camera_pose = camera_pose_from_env(env)
        if camera_pose is not None:
            descriptor["camera_position_w"] = camera_pose["position_w"]
            descriptor["camera_quat_wxyz"] = camera_pose["quat_wxyz"]
        camera_extrinsic = camera_extrinsic_body_from_env(env)
        if camera_extrinsic is not None:
            descriptor["camera_rotation_body"] = camera_extrinsic["rotation_body_camera"]
            descriptor["camera_position_body"] = camera_extrinsic["position_body"]

        descriptor["rear_camera_intrinsics"] = rear_camera_intrinsics_from_env(env)
        rear_pose = rear_camera_pose_from_env(env)
        if rear_pose is not None:
            descriptor["rear_camera_position_w"] = rear_pose["position_w"]
            descriptor["rear_camera_quat_wxyz"] = rear_pose["quat_wxyz"]
        rear_extrinsic = rear_camera_extrinsic_body_from_env(env)
        if rear_extrinsic is not None:
            descriptor["rear_camera_rotation_body"] = rear_extrinsic["rotation_body_camera"]
            descriptor["rear_camera_position_body"] = rear_extrinsic["position_body"]
        local_map = local_map_descriptor_from_env(env)
        if local_map is not None:
            descriptor.update(local_map)

    return descriptor or None


def refresh_low_level_observation(env):
    with torch.inference_mode(False):
        if isinstance(env.env, RslRlVecEnvHistoryWrapper):
            if hasattr(env.env.unwrapped, "observation_manager"):
                obs_dict = env.env.unwrapped.observation_manager.compute()
            else:
                obs_dict = env.env.unwrapped._get_observations()
            proprio_obs, obs = obs_dict["proprio"], obs_dict["policy"]
            env.env.proprio_obs_buf.zero_()
            zero_history = env.env.proprio_obs_buf.view(env.env.num_envs, -1)
            env.low_level_obs = torch.cat([obs, zero_history], dim=1).detach().clone()
        else:
            env.low_level_obs, _ = env.env.get_observations()
            env.low_level_obs = env.low_level_obs.detach().clone()
    env.low_level_action = None


def set_robot_pose(env, pose):
    robot = env.unwrapped.scene["robot"]
    pose_tensor = torch.as_tensor(pose, dtype=robot.data.root_state_w.dtype, device=robot.device).unsqueeze(0)
    velocity = torch.zeros((1, 6), dtype=robot.data.root_state_w.dtype, device=robot.device)
    robot.write_root_pose_to_sim(pose_tensor)
    robot.write_root_velocity_to_sim(velocity)
    if hasattr(env.unwrapped.sim, "write_data_to_sim"):
        env.unwrapped.sim.write_data_to_sim()

    if isinstance(env.env, RslRlVecEnvHistoryWrapper):
        env.env.proprio_obs_buf.zero_()


def reset_navigation_memory(env, pose):
    set_robot_pose(env, pose)
    env.prev_pos = torch.as_tensor(pose[:3], dtype=env.unwrapped.scene["robot"].data.root_state_w.dtype, device=env.unwrapped.device)
    env.same_pos_count = 0
    env.set_stop_called(False)
    refresh_low_level_observation(env)


def parse_vlm_command(text):
    text = "" if text is None else str(text)
    lower_text = text.lower()
    is_valid = any(keyword in lower_text for keyword in ("turn left", "turn right", "move forward", "move", "stop"))
    command, duration = get_vel_command(text)
    return command, duration, is_valid


def build_round_trip_instruction(episode):
    original_instruction = InstructionData(**episode["instruction"]).instruction_text.strip()
    return (
        f"{original_instruction} "
        "After confirming the target, turn around and return to the original starting point by retracing the same route in reverse. "
        "Stop when you are back at the starting point."
    )


def build_phase_instruction(episode, phase):
    original_instruction = InstructionData(**episode["instruction"]).instruction_text.strip()
    if phase == "outbound":
        return (
            f"{original_instruction} "
            "This is the outbound phase of a round-trip task. Stop at the described target before returning."
        )
    if phase == "return":
        return (
            "Return to the original starting point by retracing the route you just traveled in reverse. "
            "Use the visual scene to go back through the same rooms and corridors, then stop at the starting point. "
            f"The outbound instruction was: {original_instruction}"
        )
    return "Confirm the target by scanning in place."


def get_query_instruction(episode, phase, round_trip_instruction):
    if args_cli.round_trip_mode == "static_long_instruction":
        return round_trip_instruction
    return build_phase_instruction(episode, phase)


def build_episode_instructions(episode, dataset_path):
    if args_cli.instruction_rewriter_provider == "legacy":
        return {
            "round_trip": build_round_trip_instruction(episode),
            "outbound": build_phase_instruction(episode, "outbound"),
            "return": build_phase_instruction(episode, "return"),
            "source": "legacy",
            "model": "",
        }

    original_instruction = InstructionData(**episode["instruction"]).instruction_text.strip()
    rewriter = InstructionRewriter(
        provider=args_cli.instruction_rewriter_provider,
        model=args_cli.instruction_rewriter_model,
        cache_path=args_cli.instruction_rewriter_cache,
        endpoint=args_cli.instruction_llm_endpoint,
        api_key=os.getenv(args_cli.instruction_llm_api_key_env),
        timeout=args_cli.instruction_llm_timeout,
        dataset_path=dataset_path,
        episode_index=args_cli.episode_idx,
    )
    try:
        instructions = rewriter.rewrite(original_instruction)
    except InstructionRewriteError as exc:
        raise RuntimeError(f"Unable to prepare round-trip instruction: {exc}") from exc
    return {
        "round_trip": instructions.round_trip_instruction,
        "outbound": instructions.outbound_instruction,
        "return": instructions.return_instruction,
        "source": instructions.provider,
        "model": instructions.model,
    }


def main():
    """IsaacSim round-trip evaluation using NaVILA and trained low-level policy."""

    # read R2R test episodes
    r2r_data_path = os.path.join(ASSETS_DIR, "vln_ce_isaac_v1.json.gz")
    all_episodes = read_episodes(r2r_data_path)
    episode = all_episodes[args_cli.episode_idx]

    env_cfg = parse_env_cfg(args_cli.task, num_envs=args_cli.num_envs)

    # reset the position and rotation of the robot
    env_cfg = reset_start_pos_rot(env_cfg, args_cli, episode)

    agent_cfg: RslRlOnPolicyRunnerCfg = cli_args.parse_rsl_rl_cfg(
        args_cli.task, args_cli, play=True
    )

    # specify directory for logging experiments
    log_root_path = os.path.join(os.path.dirname(__file__),"../logs", "rsl_rl", agent_cfg.experiment_name)
    log_root_path = os.path.abspath(log_root_path)
    log_dir = os.path.join(log_root_path, args_cli.load_run)
    print(f"[INFO] Loading run from directory: {log_dir}")

    # update agent config with the one from the loaded run
    log_agent_cfg_file_path = os.path.join(log_dir, "params", "agent.yaml")
    assert os.path.exists(log_agent_cfg_file_path), f"Agent config file not found: {log_agent_cfg_file_path}"
    log_agent_cfg_dict = load_yaml(log_agent_cfg_file_path)
    update_class_from_dict(agent_cfg, log_agent_cfg_dict)

    # specify directory for logging experiments
    resume_path = get_checkpoint_path(log_root_path, args_cli.load_run, agent_cfg.load_checkpoint)
    print(f"[INFO]: Loading model checkpoint from: {resume_path}")

    # create isaac environment
    env = gym.make(args_cli.task, cfg=env_cfg, render_mode=None)
    # wrap around environment for rsl-rl
    if args_cli.history_length > 0:
        env = RslRlVecEnvHistoryWrapper(env, history_length=args_cli.history_length)
    else:
        env = RslRlVecEnvWrapper(env)

    # load previously trained model
    ppo_runner = OnPolicyRunner(env, agent_cfg.to_dict(), log_dir=None, device=agent_cfg.device)
    ppo_runner.load(resume_path)
    print(f"[INFO]: Loading model checkpoint from: {resume_path}")
    policy = ppo_runner.get_inference_policy(device=env.unwrapped.device)

    all_measures = ["PathLength", "DistanceToGoal", "Success", "SPL", "OracleNavigationError", "OracleSuccess"]
    env = VLNEnvWrapper(env, policy, args_cli.task, episode, high_level_obs_key="camera_obs",
                        measure_names=all_measures)
    
    # set view pos and target
    robot_pos_w = env.unwrapped.scene["robot"].data.root_pos_w[0].detach().cpu().numpy()
    robot_quat_w = env.unwrapped.scene["robot"].data.root_quat_w[0].detach().cpu().numpy()
    roll, pitch, yaw = quat2eulers(robot_quat_w[0], robot_quat_w[1], robot_quat_w[2], robot_quat_w[3])
    cam_eye = (robot_pos_w[0] - 0.8 * math.sin(-yaw), robot_pos_w[1] - 0.8 * math.cos(-yaw), robot_pos_w[2] + 0.8)
    cam_target = (robot_pos_w[0], robot_pos_w[1], robot_pos_w[2])
    # set the camera view
    env.unwrapped.sim.set_camera_view(eye=cam_eye, target=cam_target)
    
    # step with zeros actions to get the initial frame
    obs, infos = env.reset()

    # NaViLA training gets image observations each 0.5s, visualize every 0.1s
    steps_per_image = 0.5 / (env.unwrapped.cfg.sim.dt * env.unwrapped.cfg.decimation)
    steps_per_viz_image = 0.1 / (env.unwrapped.cfg.sim.dt * env.unwrapped.cfg.decimation)

    rgb_obs = infos["observations"]["camera_obs"]
    init_frame = rgb_obs[0, :, :, :3].cpu().numpy()
    # init_frame = cv2.rotate(init_frame, cv2.ROTATE_90_CLOCKWISE)
    instruction = InstructionData(**episode["instruction"])
    episode_instructions = build_episode_instructions(episode, r2r_data_path)
    round_trip_instruction = episode_instructions["round_trip"]
    outbound_instruction = episode_instructions["outbound"]
    return_instruction = episode_instructions["return"]
    if args_cli.return_instruction_file:
        with open(args_cli.return_instruction_file, "r", encoding="utf-8") as instruction_file:
            return_instruction = instruction_file.read().strip()
        if not return_instruction:
            raise RuntimeError("Return instruction file is empty.")
    elif args_cli.return_instruction_override.strip():
        return_instruction = args_cli.return_instruction_override.strip()
    current_instruction_text = (
        round_trip_instruction
        if args_cli.round_trip_mode == "static_long_instruction"
        else outbound_instruction
    )
    image_observations = []
    image_observations.append(Image.fromarray(init_frame))

    add_instruction_on_img(init_frame, f"[outbound] {current_instruction_text}")
    vis_frame = infos["observations"]["viz_camera_obs"][0, :, :, :3].cpu().numpy()
    # vis_frame = cv2.rotate(vis_frame, cv2.ROTATE_90_CLOCKWISE)
    add_instruction_on_img(vis_frame, "")
    rgb_obses = [np.concatenate([init_frame, vis_frame], axis=1)]

    num_steps = 0
    target_steps = 0
    same_pos_count = 0
    diagnostic_frames_fired = set()
    prev_pos = env.unwrapped.scene["robot"].data.root_pos_w[0].detach().cpu().numpy()
    control_dt = env.unwrapped.cfg.sim.dt * env.unwrapped.cfg.decimation
    max_episode_steps = 100 * 0.5 / control_dt
    max_return_steps = args_cli.max_return_seconds / control_dt
    confirm_turn_steps = int(args_cli.confirm_turn_seconds / control_dt)
    start_pos = np.array(episode["start_position"], dtype=np.float32)
    goal_pos = np.array(episode["reference_path"][-1], dtype=np.float32)
    episode_goal_radius = float(episode["goals"][0]["radius"])
    success_radius = (
        float(args_cli.success_radius)
        if args_cli.success_radius is not None
        else (
            float(args_cli.return_success_radius)
            if args_cli.return_success_radius is not None
            else episode_goal_radius
        )
    )
    reference_path_xy = np.asarray([[p[0], p[1]] for p in episode["reference_path"]], dtype=np.float32)
    return_path_xy = np.asarray([[p[0], p[1]] for p in reversed(episode["reference_path"])], dtype=np.float32)
    result_suffix = f"_{args_cli.result_suffix}" if args_cli.result_suffix else ""
    result_dir = (
        f"eval_results/round_trip_{args_cli.round_trip_mode}_{args_cli.task}_"
        f"loco_{args_cli.load_run}{result_suffix}"
    )
    diagnostic_frames_dir = os.path.join(result_dir, "route_memory_diagnostic_frames")
    icp_replay_dataset_dir = os.path.join(result_dir, "icp_replay_dataset")
    icp_replay_anchors_captured = False
    episode_output_id = int(episode["episode_id"]) - 1
    trajectory_relpath = f"trajectories/output_{episode_output_id}.jsonl"
    if not os.path.exists(result_dir):
        os.makedirs(result_dir)
    topdown_route_map = None
    topdown_route_map_summary = {"enabled": False}
    if args_cli.topdown_route_map:
        try:
            topdown_route_map = capture_occupancy_floor_slice(
                episode,
                resolution_m_per_px=args_cli.topdown_map_resolution,
                padding_m=args_cli.topdown_map_padding_m,
                z_min_above_floor_m=args_cli.topdown_map_z_min,
                z_max_above_floor_m=args_cli.topdown_map_z_max,
                max_size_px=args_cli.topdown_map_max_size_px,
            )
            print(
                "[INFO] Captured USD floor-slice occupancy map: "
                f"{topdown_route_map.meta['width_px']}x{topdown_route_map.meta['height_px']} px, "
                f"{topdown_route_map.meta['mesh_triangles_rasterized']} rasterized triangles"
            )
        except Exception as exc:
            topdown_route_map_summary = {
                "enabled": True,
                "error": str(exc),
            }
            print(f"[WARN] Unable to capture top-down occupancy map: {exc}")
    stream_output = ""
    vlm_vel_commands = [0.0, 0.0, 0.0]
    route_relocalizer = None
    route_relocalization_diagnostics = {}
    local_map_voxel_size_m = float(args_cli.route_local_map_voxel_size_m)
    local_map_max_points = int(args_cli.route_local_map_max_points)
    if args_cli.route_local_map_profile == "dense":
        local_map_voxel_size_m = 0.05
        local_map_max_points = 2048
    feature_relocalization_backends = {
        "feature_depth": "orb",
        "sift_depth": "sift",
        "loftr_depth": "loftr",
    }
    if args_cli.route_relocalization_backend in feature_relocalization_backends:
        matcher_backend = feature_relocalization_backends[args_cli.route_relocalization_backend]
        route_relocalizer = lambda descriptor, anchors: feature_depth_anchor_relocalization(
            descriptor,
            anchors,
            max_candidates=args_cli.route_relocalization_window,
            diagnostics=route_relocalization_diagnostics,
            matcher_backend=matcher_backend,
            return_candidates=True,
        )
    elif args_cli.route_relocalization_backend == "lidar_local_map":
        # route_agent is assigned right below; Python closures resolve the name at
        # call time (late binding), so by the time this lambda actually runs
        # (during return-phase steps, long after construction) route_agent is
        # already bound. current_absolute_pose_from_start()[2] is the robot's own
        # action-integrated yaw (non-oracle) used by the P1 heading-consistency gate.
        route_relocalizer = lambda descriptor, anchors: local_map_anchor_relocalization(
            descriptor,
            anchors,
            max_candidates=args_cli.route_relocalization_window,
            diagnostics=route_relocalization_diagnostics,
            return_candidates=True,
            dead_reckoning_yaw_rad=route_agent.current_absolute_pose_from_start()[2],
            capture_match_snapshots=args_cli.capture_anchor_match_snapshots,
            icp_objective=args_cli.route_local_map_icp_objective,
            voxel_size_m=local_map_voxel_size_m,
            max_points=local_map_max_points,
            quality_policy=args_cli.route_local_map_quality_policy,
        )
    elif args_cli.route_relocalization_backend == "scan_context":
        # P3: Scan Context picks *which* anchor via global descriptor
        # similarity, then a narrow local ICP refines the metric offset --
        # see relocalization.scan_context_anchor_relocalization docstring.
        # dead_reckoning_yaw_rad (2026-07-02 fix): guards the ICP refinement
        # against Scan Context's own 180-degree shift ambiguity, same pattern
        # as lidar_local_map's P1 gate above.
        route_relocalizer = lambda descriptor, anchors: scan_context_anchor_relocalization(
            descriptor,
            anchors,
            max_candidates=args_cli.route_relocalization_window,
            diagnostics=route_relocalization_diagnostics,
            return_candidates=True,
            capture_match_snapshots=args_cli.capture_anchor_match_snapshots,
            icp_objective=args_cli.route_local_map_icp_objective,
            voxel_size_m=local_map_voxel_size_m,
            max_points=local_map_max_points,
            quality_policy=args_cli.route_local_map_quality_policy,
        )
    elif args_cli.route_relocalization_backend == "fused":
        # Cross-validates LoFTR (RGB-D) against Scan Context (LiDAR) each
        # relocalization attempt instead of trusting either alone -- see
        # relocalization.fused_anchor_relocalization docstring for the
        # agreement policy and the literature/failure-mode reasoning behind
        # combining the two. Both backends' own descriptor/window/dead-
        # reckoning-yaw arguments are threaded through unchanged; this option
        # only adds the cross-check on top.
        route_relocalizer = lambda descriptor, anchors: fused_anchor_relocalization(
            descriptor,
            anchors,
            max_candidates=args_cli.route_relocalization_window,
            diagnostics=route_relocalization_diagnostics,
            return_candidates=True,
            dead_reckoning_yaw_rad=route_agent.current_absolute_pose_from_start()[2],
            capture_match_snapshots=args_cli.capture_anchor_match_snapshots,
        )
    elif args_cli.route_relocalization_backend == "sequential_pair":
        # 2026-07-04, per the user's design: return always starts standing
        # exactly on the last outbound anchor (finalize_outbound() guarantees
        # this), so anchor *identity* is known by construction the whole way
        # back -- match only against the current and next anchor (route_agent.
        # sequential_target_anchor_pair(), late-bound like the other closures
        # above), never search the full anchor list. See
        # relocalization.sequential_pair_anchor_relocalization's docstring for
        # why this makes the existing sequence-observation scoring advance
        # target_anchor_index monotonically with no separate state machine.
        route_relocalizer = lambda descriptor, anchors: sequential_pair_anchor_relocalization(
            descriptor,
            *route_agent.sequential_target_anchor_pair(),
            diagnostics=route_relocalization_diagnostics,
            return_candidates=True,
            capture_match_snapshots=args_cli.capture_anchor_match_snapshots,
            icp_objective=args_cli.route_local_map_icp_objective,
            voxel_size_m=local_map_voxel_size_m,
            max_points=local_map_max_points,
            quality_policy=args_cli.route_local_map_quality_policy,
            loftr_rear_yaw_check=args_cli.sequential_pair_loftr_rear_yaw_check,
        )
    relocalization_interval_backends = set(feature_relocalization_backends) | {
        "lidar_local_map", "scan_context", "fused", "sequential_pair",
    }
    route_agent = RouteMemoryAgent(
        enabled=args_cli.route_memory,
        hint_mode=args_cli.route_hint_mode,
        anchor_spacing_m=args_cli.route_anchor_spacing_m,
        min_relocalization_confidence=args_cli.route_min_relocalization_confidence,
        relocalization_interval_updates=(
            args_cli.route_relocalization_interval_updates
            if args_cli.route_relocalization_backend in relocalization_interval_backends
            else 1
        ),
        relocalizer=route_relocalizer,
        sequential_pair_geometry_source=args_cli.sequential_pair_anchor_geometry_source,
        sequential_pair_closure_check_enabled=bool(args_cli.sequential_pair_closure_check),
        sequential_pair_closure_mode=args_cli.sequential_pair_closure_mode,
        sequential_pair_closure_belief_trust_aware_guard=bool(
            args_cli.sequential_pair_closure_belief_trust_aware_guard
        ),
        sequential_pair_closure_belief_large_position_disagreement_m=(
            args_cli.sequential_pair_closure_belief_large_position_disagreement_m
        ),
        sequential_pair_closure_belief_large_heading_disagreement_rad=math.radians(
            args_cli.sequential_pair_closure_belief_large_heading_disagreement_deg
        ),
        sequential_pair_quarantine_enabled=bool(args_cli.sequential_pair_quarantine),
        sequential_pair_quarantine_mode=args_cli.sequential_pair_quarantine_mode,
        quarantine_next_quality_enabled=bool(args_cli.sequential_pair_quarantine_next_quality),
        quarantine_next_quality_threshold=args_cli.sequential_pair_quarantine_next_quality_threshold,
        quarantine_next_quality_min_samples=args_cli.sequential_pair_quarantine_next_quality_min_samples,
        sequential_pair_promotion_mode=args_cli.sequential_pair_promotion_mode,
        sequential_pair_promotion_window=args_cli.sequential_pair_promotion_window,
        sequential_pair_promotion_min_votes=args_cli.sequential_pair_promotion_min_votes,
        sequential_pair_promotion_alias_aware=bool(args_cli.sequential_pair_promotion_alias_aware),
        sequential_pair_promotion_alias_threshold=args_cli.sequential_pair_promotion_alias_threshold,
        sequential_pair_promotion_alias_window=args_cli.sequential_pair_promotion_alias_window,
        sequential_pair_promotion_alias_min_votes=args_cli.sequential_pair_promotion_alias_min_votes,
        sequential_pair_promotion_alias_stall_attempts=args_cli.sequential_pair_promotion_alias_stall_attempts,
        sequential_pair_promotion_use_pre_closure_estimates=bool(
            args_cli.sequential_pair_promotion_use_pre_closure_estimates
        ),
        sequential_pair_short_baseline_disambiguation=bool(
            args_cli.sequential_pair_short_baseline_disambiguation
        ),
        sequential_pair_short_baseline_min_travel_m=args_cli.sequential_pair_short_baseline_min_travel_m,
        sequential_pair_short_baseline_max_rotation_disagreement_deg=(
            args_cli.sequential_pair_short_baseline_max_rotation_disagreement_deg
        ),
        sequential_pair_disable_temporal_smoothing=bool(
            args_cli.sequential_pair_disable_temporal_smoothing
        ),
        sequential_pair_closure_reconciliation_signal=args_cli.sequential_pair_closure_reconciliation_signal,
        multiframe_anchor_window=args_cli.route_memory_multiframe_anchor_window,
    )
    route_agent.vio_bridge_enabled = bool(getattr(args_cli, "vio_bridge", False))
    route_agent.vio_bridge_std_threshold_m = float(getattr(args_cli, "vio_bridge_std_m", 2.5))
    route_agent.vio_bridge_feature_radius_m = float(getattr(args_cli, "vio_bridge_feature_radius_m", 2.0))
    stop_gate = None
    if getattr(args_cli, "stop_gate", False):
        stop_gate = ReturnStopGate(
            r_in=float(getattr(args_cli, "stop_gate_r_in", 3.0)),
            r_out=float(getattr(args_cli, "stop_gate_r_out", 3.0)),
            confirm_steps=int(getattr(args_cli, "stop_gate_confirm_steps", 3)),
            min_confidence=float(getattr(args_cli, "stop_gate_min_confidence", 0.5)),
        )
        print(
            f"[stop_gate] enabled: r_in={stop_gate.r_in} r_out={stop_gate.r_out} "
            f"confirm_steps={stop_gate.confirm_steps} "
            f"min_confidence={stop_gate.min_confidence}",
            flush=True,
        )
    hint_action_arbiter = None
    _last_hint_action_decision = None
    if getattr(args_cli, "hint_action_arbiter", False):
        hint_action_arbiter = HintActionArbiter(HintActionArbiterConfig(
            forward_cone_deg=float(getattr(args_cli, "hint_arbiter_forward_cone_deg", 15.0)),
            forward_conflict_bearing_deg=float(
                getattr(args_cli, "hint_arbiter_forward_conflict_bearing_deg", 30.0)
            ),
            turn_step_deg=float(getattr(args_cli, "hint_arbiter_turn_step_deg", 45.0)),
            forward_distance_cm=int(getattr(args_cli, "hint_arbiter_forward_distance_cm", 75)),
            max_clear_path_distance_m=float(
                getattr(args_cli, "hint_arbiter_max_clear_path_distance_m", 1.0)
            ),
            robot_radius_m=float(getattr(args_cli, "hint_arbiter_robot_radius_m", 0.30)),
            clearance_margin_m=float(getattr(args_cli, "hint_arbiter_clearance_margin_m", 0.12)),
            allow_without_clear_path=bool(
                getattr(args_cli, "hint_arbiter_allow_without_clear_path", False)
            ),
            min_relocalization_confidence=float(
                getattr(args_cli, "hint_arbiter_min_relocalization_confidence", 0.0)
            ),
        ))
        print(
            "[hint_arbiter] enabled: "
            f"topdown_map_available={topdown_route_map is not None} "
            f"allow_without_clear_path={hint_action_arbiter.cfg.allow_without_clear_path}",
            flush=True,
        )
    if args_cli.route_memory:
        route_agent.update_latest_anchor_metadata({
            "world_pose": [float(x) for x in get_robot_pose(env)],
            "world_pose_source": "isaac_oracle_for_relocalization_eval",
        })
    phase_events = []
    stop_events = []
    trajectory_records = []
    phase = "outbound"
    return_start_step = None
    outbound_stop_output = None
    outbound_measurements = None
    outbound_stop_distance_to_goal = None
    outbound_success = False
    return_success = False
    return_pose_before_oracle = None
    return_pose_after_oracle = None
    oracle_return_pose = None
    return_yaw_alignment = None
    return_pose_error_before_oracle = None
    return_pose_error_after_oracle = None
    last_vlm_step = None
    force_capture_next_image = False
    _gate_vlm_progress = None     # progress used at the last VLM query step
    _last_gate_decision: GateDecision = None  # gate decision from the last VLM query
    current_route_descriptor = None
    # visualizer = define_markers()
    # simulate environment
    while simulation_app.is_running():
        # run everything in inference mode
        with torch.inference_mode():
            if num_steps == target_steps:
                if phase in ("outbound", "return"):
                    query_instruction_text = current_instruction_text
                    route_hint_event = None
                    _gate_vlm_progress = None   # reset each VLM step
                    if phase == "return" and args_cli.route_memory:
                        progress_override = route_progress_override(
                            args_cli.route_hint_source,
                            env,
                            start_pos,
                            route_agent,
                        )
                        route_query_progress = (
                            progress_override
                            if progress_override is not None else route_agent.progress()
                        )
                        route_shadow_progress = (
                            route_agent.progress()
                            if progress_override is not None else None
                        )
                        _gate_vlm_progress = route_query_progress   # capture for stop gate / action arbiter
                        query_instruction_text, route_hint_event = route_agent.inject_hint(
                            current_instruction_text,
                            num_steps,
                            progress_override=route_query_progress,
                        )
                        if route_hint_event is not None:
                            route_hint_event["source"] = args_cli.route_hint_source
                            route_hint_event["shadow_progress"] = route_progress_to_record(
                                route_shadow_progress,
                                "shadow_non_oracle",
                            )
                            route_hint_event["shadow_alignment"] = route_progress_alignment_record(
                                route_query_progress,
                                route_shadow_progress,
                            )
                            phase_events.append({
                                "step": int(num_steps),
                                "phase": phase,
                                "event": "route_memory_hint",
                                **route_hint_event,
                            })
                    stream_output = sample_images_and_send_to_vlm(
                        image_observations,
                        args_cli.vlm_host,
                        args_cli.vlm_port,
                        query_instruction_text,
                    )
                    vlm_vel_commands, time_to_go, is_parseable = parse_vlm_command(stream_output)
                    _last_hint_action_decision = None
                    if hint_action_arbiter is not None and phase == "return":
                        _last_hint_action_decision = hint_action_arbiter.check(
                            progress=_gate_vlm_progress,
                            vlm_output=stream_output,
                            robot_position=get_robot_position(env),
                            robot_yaw_rad=pose_yaw(get_robot_pose(env)),
                            topdown_map=topdown_route_map,
                            local_map_descriptor=current_route_descriptor,
                        )
                        phase_events.append({
                            "step": int(num_steps),
                            "phase": phase,
                            "event": "hint_action_arbiter",
                            **_last_hint_action_decision.as_log_dict(),
                        })
                        if _last_hint_action_decision.override:
                            stream_output = _last_hint_action_decision.replacement_output
                            vlm_vel_commands, time_to_go, is_parseable = parse_vlm_command(stream_output)
                        print(
                            f"[hint_arbiter] step={num_steps} "
                            f"override={_last_hint_action_decision.override} "
                            f"reason={_last_hint_action_decision.reason} "
                            f"desired={_last_hint_action_decision.desired_kind} "
                            f"bearing={_last_hint_action_decision.desired_bearing_deg} "
                            f"clear={_last_hint_action_decision.clear_path}",
                            flush=True,
                        )
                    route_agent.update_action_history(vlm_vel_commands)
                    env_steps_to_go = int(time_to_go / (
                        env.unwrapped.cfg.sim.dt * env.unwrapped.cfg.decimation
                    ))
                    if env_steps_to_go <= 0 and "stop" not in str(stream_output).lower():
                        env_steps_to_go = 1
                    target_steps = num_steps + env_steps_to_go
                    phase_events.append({
                        "step": int(num_steps),
                        "phase": phase,
                        "event": "vlm_command",
                        "output": stream_output,
                        "parseable": bool(is_parseable),
                        "command": [float(x) for x in vlm_vel_commands],
                        "duration_seconds": float(time_to_go),
                    })
                    last_vlm_step = num_steps
                    print(
                        f"[{phase}] VLM output: {stream_output}\n"
                        f"Vel Command: {vlm_vel_commands}, Env Steps to go: {env_steps_to_go}, "
                        f"Parseable: {is_parseable}\n",
                        flush=True,
                    )

                    # --- Stop-gate arbiter (return phase only, no-op when disabled) ---
                    _vlm_stop_requested = (
                        env_steps_to_go == 0 and "stop" in str(stream_output).lower()
                    )
                    if stop_gate is not None and phase == "return":
                        _last_gate_decision = stop_gate.check(
                            progress=_gate_vlm_progress,
                            vlm_issued_stop=_vlm_stop_requested,
                        )
                        phase_events.append({
                            "step": int(num_steps),
                            "phase": phase,
                            "event": "stop_gate",
                            **_last_gate_decision.as_log_dict(),
                        })
                        if _last_gate_decision.decision == "vetoed":
                            vlm_vel_commands = list(_last_gate_decision.suggested_command)
                            route_agent.update_action_history(vlm_vel_commands)
                            env_steps_to_go = _last_gate_decision.suggested_steps
                            target_steps = num_steps + env_steps_to_go
                            _vlm_stop_requested = False
                        elif _last_gate_decision.decision == "forced":
                            _vlm_stop_requested = True
                        print(
                            f"[stop_gate] step={num_steps} "
                            f"decision={_last_gate_decision.decision} "
                            f"d={_last_gate_decision.authority_d} "
                            f"conf={_last_gate_decision.conf:.3f} "
                            f"teleport={_last_gate_decision.is_teleport_frame}",
                            flush=True,
                        )

                    if _vlm_stop_requested:
                        stop_events.append({
                            "step": int(num_steps),
                            "phase": phase,
                            "output": stream_output,
                            "position": [float(x) for x in get_robot_position(env)],
                        })
                        if phase == "outbound":
                            outbound_stop_output = stream_output
                            outbound_measurements = infos["measurements"]
                            outbound_stop_distance_to_goal = float(
                                np.linalg.norm(get_robot_position(env)[:2] - goal_pos[:2])
                            )
                            outbound_success = outbound_stop_distance_to_goal < success_radius
                            phase = "confirm"
                            phase_events.append({
                                "step": int(num_steps),
                                "phase": phase,
                                "event": "outbound_stop_to_confirm",
                                "distance_to_goal": outbound_stop_distance_to_goal,
                                "success": bool(outbound_success),
                            })
                            vlm_vel_commands = [0.0, 0.0, np.pi / 6.0]
                            target_steps = num_steps + confirm_turn_steps
                            stream_output = "[Confirm] scripted 360-degree scan"
                            image_observations = []
                        else:
                            return_stop_distance_to_start = float(
                                np.linalg.norm(get_robot_position(env)[:2] - start_pos[:2])
                            )
                            return_success = return_stop_distance_to_start < success_radius
                            phase_events.append({
                                "step": int(num_steps),
                                "phase": phase,
                                "event": "return_stop",
                                "distance_to_start": return_stop_distance_to_start,
                                "success": bool(return_success),
                            })
                            env.set_stop_called(True)

                elif phase == "confirm":
                    phase = "return"
                    return_start_step = num_steps
                    previous_anchor_count = len(route_agent.anchors)
                    route_agent.finalize_outbound(
                        descriptor=current_route_descriptor,
                        metadata={
                            "world_pose": [float(x) for x in get_robot_pose(env)],
                            "world_pose_source": "isaac_oracle_for_relocalization_eval",
                        },
                    )
                    if args_cli.route_memory and len(route_agent.anchors) > previous_anchor_count:
                        route_agent.update_latest_anchor_metadata({
                            "world_pose": [float(x) for x in get_robot_pose(env)],
                            "world_pose_source": "isaac_oracle_for_relocalization_eval",
                        })
                    if args_cli.capture_icp_replay_dataset and not icp_replay_anchors_captured:
                        capture_icp_replay_anchors(route_agent, icp_replay_dataset_dir)
                        icp_replay_anchors_captured = True
                    if args_cli.sequential_pair_promotion_alias_aware:
                        route_agent.compute_anchor_alias_scores(
                            voxel_size_m=local_map_voxel_size_m,
                            max_points=local_map_max_points,
                            icp_objective=args_cli.route_local_map_icp_objective,
                        )
                    return_pose_before_oracle = get_robot_pose(env)
                    oracle_return_pose = get_oracle_return_pose(env, episode)
                    return_pose_error_before_oracle = summarize_pose_error(
                        return_pose_before_oracle,
                        oracle_return_pose,
                    )
                    if args_cli.oracle_return_pose:
                        reset_navigation_memory(env, oracle_return_pose)
                    if args_cli.oracle_align_return_yaw_to_anchor_segment:
                        return_yaw_alignment = align_return_yaw_to_anchor_segment(env, route_agent)
                    return_pose_after_oracle = get_robot_pose(env)
                    return_pose_error_after_oracle = summarize_pose_error(
                        return_pose_after_oracle,
                        oracle_return_pose,
                    )
                    current_instruction_text = (
                        round_trip_instruction
                        if args_cli.round_trip_mode == "static_long_instruction"
                        else return_instruction
                    )
                    phase_events.append({
                        "step": int(num_steps),
                        "phase": phase,
                        "event": "confirm_complete_to_return",
                        "instruction": current_instruction_text,
                        "oracle_return_pose_enabled": bool(args_cli.oracle_return_pose),
                        "oracle_align_return_yaw_to_anchor_segment": bool(
                            args_cli.oracle_align_return_yaw_to_anchor_segment
                        ),
                        "return_yaw_alignment": return_yaw_alignment,
                        "pose_before_oracle": [float(x) for x in return_pose_before_oracle],
                        "pose_after_oracle": [float(x) for x in return_pose_after_oracle],
                        "pose_error_before_oracle": return_pose_error_before_oracle,
                        "pose_error_after_oracle": return_pose_error_after_oracle,
                    })
                    vlm_vel_commands = [0.0, 0.0, 0.0]
                    target_steps = num_steps + 1
                    image_observations = []
                    force_capture_next_image = True
                    stream_output = "[Return] query NaVILA with return instruction"
                    print(
                        f"[return] start step={num_steps}, oracle={bool(args_cli.oracle_return_pose)}, "
                        f"pose_error_after_oracle={return_pose_error_after_oracle}",
                        flush=True,
                    )

        pose_before_step = (
            get_robot_pose(env)
            if (args_cli.route_memory and args_cli.measured_odometry and not args_cli.leg_odometry)
            else None
        )
        obs, _, done, infos = env.step(torch.tensor(vlm_vel_commands, device = obs.device))

        if stop_gate is not None and phase == "return":
            stop_gate.notify_sim_step(get_robot_position(env))

        if args_cli.route_memory:
            if args_cli.leg_odometry:
                action_delta = get_leg_odometry_action_delta(env, control_dt, infos)
            elif args_cli.measured_odometry:
                action_delta = get_measured_action_delta(pose_before_step, get_robot_pose(env))
            else:
                action_delta = [
                    float(vlm_vel_commands[0]) * control_dt,
                    float(vlm_vel_commands[1]) * control_dt,
                    float(vlm_vel_commands[2]) * control_dt,
                ]
            route_descriptor = route_memory_descriptor_from_infos(infos, env)
            current_route_descriptor = route_descriptor
            if phase in ("outbound", "confirm"):
                previous_anchor_count = len(route_agent.anchors)
                route_agent.update_outbound_motion(action_delta, descriptor=route_descriptor)
                if len(route_agent.anchors) > previous_anchor_count:
                    route_agent.update_latest_anchor_metadata({
                        "world_pose": [float(x) for x in get_robot_pose(env)],
                        "world_pose_source": "isaac_oracle_for_relocalization_eval",
                    })
            elif phase == "return":
                if args_cli.capture_icp_replay_dataset:
                    capture_icp_replay_step(env, route_descriptor, num_steps, icp_replay_dataset_dir)
                relocalization = (
                    oracle_anchor_relocalization(env, route_agent)
                    if args_cli.route_relocalization_backend == "oracle_anchor"
                    else None
                )
                route_agent.update_return_motion(
                    action_delta,
                    local_descriptor=route_descriptor,
                    relocalization=relocalization,
                )

        route_memory_progress = None
        route_memory_shadow_progress = None
        route_memory_alignment = None
        if args_cli.route_memory and phase == "return":
            progress = route_progress_override(args_cli.route_hint_source, env, start_pos, route_agent)
            shadow_progress = route_agent.progress() if progress is not None else None
            if progress is None:
                progress = route_agent.progress()
            if progress is not None:
                route_memory_progress = route_progress_to_record(progress, args_cli.route_hint_source)
                route_memory_shadow_progress = route_progress_to_record(
                    shadow_progress,
                    "shadow_non_oracle",
                )
                route_memory_alignment = route_progress_alignment_record(progress, shadow_progress)

            if args_cli.capture_route_memory_diagnostic_frames and shadow_progress is not None:
                total_length = route_agent.total_route_length_m
                if total_length > 1e-6:
                    fraction_remaining = max(0.0, min(1.0, shadow_progress.distance_to_start_m / total_length))
                    for threshold in diagnostic_frame_thresholds_to_fire(fraction_remaining, diagnostic_frames_fired):
                        capture_route_memory_diagnostic_frame(
                            env, route_agent, current_route_descriptor, num_steps, diagnostic_frames_dir,
                        )
                        diagnostic_frames_fired.add(threshold)

        _traj_record = make_trajectory_record(
            num_steps,
            phase,
            env,
            vlm_vel_commands,
            stream_output,
            start_pos,
            goal_pos,
            reference_path_xy,
            return_path_xy,
            last_vlm_step,
            route_memory_progress,
        )
        if stop_gate is not None and _last_gate_decision is not None:
            _traj_record["stop_gate"] = _last_gate_decision.as_log_dict()
        if hint_action_arbiter is not None and _last_hint_action_decision is not None:
            _traj_record["hint_action_arbiter"] = _last_hint_action_decision.as_log_dict()
        if route_memory_shadow_progress is not None:
            _traj_record["route_memory_shadow"] = route_memory_shadow_progress
        if route_memory_alignment is not None:
            _traj_record["route_memory_alignment"] = route_memory_alignment
        trajectory_records.append(_traj_record)

        distance_to_start = float(np.linalg.norm(get_robot_position(env)[:2] - start_pos[:2]))
        if phase == "return" and return_start_step is not None and num_steps - return_start_step > max_return_steps:
            phase_events.append({
                "step": int(num_steps),
                "phase": phase,
                "event": "return_timeout",
                "distance_to_start": distance_to_start,
            })
            break

        if phase == "return" and return_start_step is not None and (num_steps - return_start_step) % 500 == 0:
            print(
                f"[return] step={num_steps}, elapsed_return_steps={num_steps - return_start_step}, "
                f"distance_to_start={distance_to_start:.3f}",
                flush=True,
            )

        if done or env.is_stop_called or (phase == "outbound" and num_steps > max_episode_steps):
            break

        cur_pos = env.unwrapped.scene["robot"].data.root_pos_w[0].detach().cpu().numpy()
        robot_vel = np.linalg.norm(env.unwrapped.scene["robot"].data.root_vel_w[0].detach().cpu().numpy())
        if np.linalg.norm(cur_pos - prev_pos) < 0.01 and robot_vel < 0.01:
            same_pos_count += 1
        else:
            same_pos_count = 0
        prev_pos = cur_pos

        # Break out of the loop if the robot has stayed in the same location for 500 steps
        if same_pos_count >= 1000:
            print("Robot has stayed in the same location for 1000 steps. Breaking out of the loop.")
            break

        if force_capture_next_image or num_steps % steps_per_image == 0:
            curr_frame = infos["observations"]["camera_obs"][0, :, :, :3].cpu().numpy()
            image_observations.append(Image.fromarray(curr_frame))
            curr_frame_copy = curr_frame.copy()
            add_instruction_on_img(curr_frame_copy, f"[{phase}] {current_instruction_text}")
            force_capture_next_image = False
            
        if num_steps % steps_per_viz_image == 0:
            curr_vis_frame = infos["observations"]["viz_camera_obs"][0, :, :, :3].cpu().numpy()
            add_instruction_on_img(curr_vis_frame, stream_output)
            rgb_obses.append(np.concatenate([curr_frame_copy, curr_vis_frame], axis=1))

        num_steps += 1

        # if args_cli.visualize_path:
        #     visualizer.visualize(reference_path_isaac)
    measurements = infos["measurements"]
    final_pos = get_robot_position(env)
    distance_to_start = float(np.linalg.norm(final_pos[:2] - start_pos[:2]))
    distance_to_goal = float(np.linalg.norm(final_pos[:2] - goal_pos[:2]))
    route_memory_summary = route_agent.summary()
    if topdown_route_map is not None:
        try:
            topdown_route_map_summary = save_topdown_route_map(
                result_dir,
                episode_output_id,
                topdown_route_map,
                trajectory_records,
                route_memory_summary,
                episode,
            )
            print(
                "[INFO] Saved top-down route map: "
                f"{topdown_route_map_summary['route_overlay_file']}"
            )
        except Exception as exc:
            topdown_route_map_summary = {
                "enabled": True,
                "error": str(exc),
                "meta": dict(topdown_route_map.meta),
            }
            print(f"[WARN] Unable to save top-down route map: {exc}")
    measurements["round_trip"] = {
        "mode": args_cli.round_trip_mode,
        "completed_phase": phase,
        "outbound_success": outbound_success,
        "return_success": bool(return_success),
        "round_trip_success": bool(outbound_success and return_success),
        "distance_to_start": distance_to_start,
        "distance_to_goal": distance_to_goal,
        "round_trip_instruction": round_trip_instruction,
        "outbound_instruction": outbound_instruction,
        "return_instruction": return_instruction,
        "instruction_rewriter_provider": episode_instructions["source"],
        "instruction_rewriter_model": episode_instructions["model"],
        "return_instruction_override": bool(
            args_cli.return_instruction_override.strip() or args_cli.return_instruction_file
        ),
        "return_instruction_file": args_cli.return_instruction_file or None,
        "oracle_return_pose_enabled": bool(args_cli.oracle_return_pose),
        "oracle_align_return_yaw_to_anchor_segment": bool(args_cli.oracle_align_return_yaw_to_anchor_segment),
        "return_yaw_alignment": return_yaw_alignment,
        "return_pose_before_oracle": (
            [float(x) for x in return_pose_before_oracle]
            if return_pose_before_oracle is not None else None
        ),
        "return_pose_after_oracle": (
            [float(x) for x in return_pose_after_oracle]
            if return_pose_after_oracle is not None else None
        ),
        "oracle_return_pose": (
            [float(x) for x in oracle_return_pose]
            if oracle_return_pose is not None else None
        ),
        "return_pose_error_before_oracle": return_pose_error_before_oracle,
        "return_pose_error_after_oracle": return_pose_error_after_oracle,
        "outbound_stop_output": outbound_stop_output,
        "outbound_stop_distance_to_goal": outbound_stop_distance_to_goal,
        "episode_goal_radius": episode_goal_radius,
        "success_radius": success_radius,
        "success_requires_stop": True,
        "trajectory_file": trajectory_relpath,
        "trajectory_record_count": len(trajectory_records),
        "stop_events": stop_events,
        "phase_events": phase_events,
        "route_hint_source": args_cli.route_hint_source,
        "route_relocalization_backend": args_cli.route_relocalization_backend,
        "route_local_map_icp_objective": args_cli.route_local_map_icp_objective,
        "route_local_map_voxel_size_m": float(local_map_voxel_size_m),
        "route_local_map_max_points": int(local_map_max_points),
        "route_local_map_profile": args_cli.route_local_map_profile,
        "route_local_map_quality_policy": args_cli.route_local_map_quality_policy,
        "capture_icp_replay_dataset": bool(args_cli.capture_icp_replay_dataset),
        "sequential_pair_anchor_geometry_source": args_cli.sequential_pair_anchor_geometry_source,
        "sequential_pair_closure_check": bool(args_cli.sequential_pair_closure_check),
        "sequential_pair_closure_mode": args_cli.sequential_pair_closure_mode,
        "sequential_pair_closure_belief_trust_aware_guard": bool(
            args_cli.sequential_pair_closure_belief_trust_aware_guard
        ),
        "sequential_pair_closure_belief_large_position_disagreement_m": float(
            args_cli.sequential_pair_closure_belief_large_position_disagreement_m
        ),
        "sequential_pair_closure_belief_large_heading_disagreement_deg": float(
            args_cli.sequential_pair_closure_belief_large_heading_disagreement_deg
        ),
        "sequential_pair_quarantine": bool(args_cli.sequential_pair_quarantine),
        "sequential_pair_quarantine_mode": args_cli.sequential_pair_quarantine_mode,
        "sequential_pair_quarantine_next_quality": bool(args_cli.sequential_pair_quarantine_next_quality),
        "sequential_pair_quarantine_next_quality_threshold": float(
            args_cli.sequential_pair_quarantine_next_quality_threshold
        ),
        "sequential_pair_quarantine_next_quality_min_samples": int(
            args_cli.sequential_pair_quarantine_next_quality_min_samples
        ),
        "sequential_pair_promotion_mode": args_cli.sequential_pair_promotion_mode,
        "sequential_pair_promotion_window": int(args_cli.sequential_pair_promotion_window),
        "sequential_pair_promotion_min_votes": int(args_cli.sequential_pair_promotion_min_votes),
        "sequential_pair_promotion_alias_aware": bool(args_cli.sequential_pair_promotion_alias_aware),
        "sequential_pair_promotion_alias_threshold": float(args_cli.sequential_pair_promotion_alias_threshold),
        "sequential_pair_promotion_alias_window": int(args_cli.sequential_pair_promotion_alias_window),
        "sequential_pair_promotion_alias_min_votes": int(args_cli.sequential_pair_promotion_alias_min_votes),
        "sequential_pair_promotion_alias_stall_attempts": int(args_cli.sequential_pair_promotion_alias_stall_attempts),
        "sequential_pair_promotion_use_pre_closure_estimates": bool(
            args_cli.sequential_pair_promotion_use_pre_closure_estimates
        ),
        "sequential_pair_short_baseline_disambiguation": bool(
            args_cli.sequential_pair_short_baseline_disambiguation
        ),
        "sequential_pair_short_baseline_min_travel_m": float(args_cli.sequential_pair_short_baseline_min_travel_m),
        "sequential_pair_short_baseline_max_rotation_disagreement_deg": float(
            args_cli.sequential_pair_short_baseline_max_rotation_disagreement_deg
        ),
        "sequential_pair_loftr_rear_yaw_check": bool(args_cli.sequential_pair_loftr_rear_yaw_check),
        "sequential_pair_disable_temporal_smoothing": bool(args_cli.sequential_pair_disable_temporal_smoothing),
        "sequential_pair_closure_reconciliation_signal": args_cli.sequential_pair_closure_reconciliation_signal,
        "route_relocalization_diagnostics": route_relocalization_diagnostics,
        "route_memory": route_memory_summary,
        "topdown_route_map": topdown_route_map_summary,
        "stop_gate": {
            "enabled": stop_gate is not None,
            "r_in": stop_gate.r_in if stop_gate is not None else None,
            "r_out": stop_gate.r_out if stop_gate is not None else None,
            "confirm_steps": stop_gate.confirm_steps if stop_gate is not None else None,
            "min_confidence": stop_gate.min_confidence if stop_gate is not None else None,
        },
    }

    trajectory_dir = os.path.join(result_dir, "trajectories")
    if not os.path.exists(trajectory_dir):
        os.makedirs(trajectory_dir)
    trajectory_path = os.path.join(result_dir, trajectory_relpath)
    with open(trajectory_path, "w", encoding="utf-8") as f:
        for record in trajectory_records:
            f.write(json.dumps(record) + "\n")

    measurement_dir = os.path.join(result_dir, "measurements")
    if not os.path.exists(measurement_dir):
        os.makedirs(measurement_dir)
    with open(f"{measurement_dir}/{episode_output_id}.json", "w") as f:
        json.dump(measurements, f, indent=4)


    video_dir = os.path.join(result_dir, "videos")
    if not os.path.exists(video_dir):
        os.makedirs(video_dir)

    writer = imageio.get_writer(f"{video_dir}/output_{episode_output_id}.mp4", fps=10)
    for frame in rgb_obses:
        frame = frame.astype(np.uint8)
        writer.append_data(frame)

    writer.close()

    # close the simulator
    env.close()



if __name__ == "__main__":
    # run the main function
    main()
    # close sim app
    simulation_app.close()
