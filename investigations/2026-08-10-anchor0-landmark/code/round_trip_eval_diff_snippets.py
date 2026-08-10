# Anchor0-landmark shadow instrumentation, extracted from
# navila-route2-v11-core-20260801/runtime_candidate/scripts/round_trip_eval.py
# (that file is not tracked whole in this repo -- see 2026-08-08-anchor-v3/
# LIVE_SHADOW_SMOKE_TEST_20260809.md for the same convention).
#
# This is the exact code added on 2026-08-09 for the user's outbound-ICP
# landmark idea, plus the 2026-08-09 fix (adding
# --route_memory_capture_start_anchor_descriptor to the launch command) that
# made it actually fire. Line numbers below refer to the 2026-08-10 state of
# the live file.

# ---------------------------------------------------------------------------
# argparse additions (~line 1272)
# ---------------------------------------------------------------------------
"""
parser.add_argument(
    "--anchor0_landmark_shadow",
    action="store_true",
    default=False,
    help=(
        "Shadow-only (2026-08-09), independent of --anchor_v3_shadow. During "
        "OUTBOUND, repeatedly ICP-matches the current local map against "
        "anchor 0's saved map, scores each match through a dedicated V1.1 "
        "reliability session, and -- on the first V1.1-trusted reading whose "
        "estimated distance crosses --anchor0_landmark_trigger_distance_m -- "
        "saves a one-off 'landmark' local map at the robot's current pose. "
        "This landmark is never inserted into route_agent.anchors and never "
        "participates in sequential_pair/promotion/hint/stop_gate matching. "
        "During RETURN, repeatedly attempts to re-match the current local map "
        "against the saved landmark the same way, to see whether recognizing "
        "it lines up with genuinely crossing back inside the same radius. "
        "Everything here uses its own isolated diagnostics dict and its own "
        "V11ShadowJsonlSession instance (never the real "
        "route_relocalization_diagnostics or v11_shadow_session) and is pure "
        "logging -- nothing here is read by any real decision."
    ),
)
parser.add_argument(
    "--anchor0_landmark_v11_runtime_root",
    type=str,
    default="/home/teambruce/navila-reliability-v1_1-anchor-support-recovery-20260728",
    help="Root of the frozen V1.1 runtime package, for the anchor0-landmark detector's own session.",
)
parser.add_argument(
    "--anchor0_landmark_v11_portable_artifact",
    type=str,
    default="/home/teambruce/navila-reliability-v1_1-anchor-support-recovery-20260728/artifacts/reliability_v1_1_portable_shadow.json",
    help="Frozen portable V1.1 JSON artifact, for the anchor0-landmark detector's own session.",
)
parser.add_argument(
    "--anchor0_landmark_trigger_distance_m",
    type=float,
    default=3.0,
    help="Landmark is placed on the first V1.1-trusted anchor-0 ICP reading at or below this distance.",
)
parser.add_argument(
    "--anchor0_landmark_interval_env_steps",
    type=int,
    default=25,
    help="How often (real env steps) to run the outbound anchor0-vs-current ICP check.",
)
"""

# ---------------------------------------------------------------------------
# OUTBOUND check (fires every anchor0_landmark_interval_env_steps steps,
# stops firing once a landmark has been placed) -- ~line 5508
# ---------------------------------------------------------------------------
"""
if (
    anchor0_landmark_v11_session is not None
    and not anchor0_landmark_state["placed"]
    and phase == "outbound"
    and (
        anchor0_landmark_state["last_outbound_check_step"] is None
        or int(num_steps) - anchor0_landmark_state["last_outbound_check_step"]
        >= args_cli.anchor0_landmark_interval_env_steps
    )
):
    anchor0_landmark_state["last_outbound_check_step"] = int(num_steps)
    try:
        anchor0 = next(
            (a for a in route_agent.anchors if int(a.index) == 0), None
        )
        # BUG (found 2026-08-10): anchor0.descriptor is None here unless the
        # evaluator was launched with --route_memory_capture_start_anchor_descriptor
        # (a separate, unrelated 2026-07-27 flag; default off). Without it this
        # whole block silently no-ops every single interval check, for the
        # entire episode -- no exception, no log line, landmark never placed.
        if anchor0 is not None and anchor0.descriptor is not None:
            landmark_diag = {}
            sequential_pair_anchor_relocalization(
                route_descriptor,
                anchor0,
                anchor0,
                additional_anchors=(),
                diagnostics=landmark_diag,
                return_candidates=True,
                capture_match_snapshots=False,
                icp_objective=args_cli.route_local_map_icp_objective,
                voxel_size_m=local_map_voxel_size_m,
                max_points=local_map_max_points,
                quality_policy=args_cli.route_local_map_quality_policy,
            )
            landmark_records = landmark_diag.get("covisibility_records", [])
            if landmark_records:
                landmark_outputs = anchor0_landmark_v11_session.score_records(
                    landmark_records, step=int(num_steps)
                )
                landmark_record = landmark_records[0]
                landmark_output = landmark_outputs[0] if landmark_outputs else {}
                est_distance = landmark_record.get("estimated_distance_to_anchor_m")
                pose_trusted = bool(landmark_output.get("pose_trusted"))
                with open(anchor0_landmark_log_path, "a") as landmark_handle:
                    landmark_handle.write(json.dumps({
                        "event": "outbound_check",
                        "step": int(num_steps),
                        "estimated_distance_to_anchor0_m": est_distance,
                        "pose_trusted": pose_trusted,
                    }) + "\\n")
                if (
                    pose_trusted
                    and est_distance is not None
                    and float(est_distance) <= args_cli.anchor0_landmark_trigger_distance_m
                ):
                    anchor0_landmark_state["placed"] = True
                    anchor0_landmark_state["placed_step"] = int(num_steps)
                    anchor0_landmark_state["descriptor"] = route_descriptor
                    with open(anchor0_landmark_log_path, "a") as landmark_handle:
                        landmark_handle.write(json.dumps({
                            "event": "landmark_placed",
                            "step": int(num_steps),
                            "estimated_distance_to_anchor0_m": est_distance,
                        }) + "\\n")
    except Exception as exc:
        print(f"[anchor0-landmark] WARNING: outbound check failed at step {num_steps}: {exc}", flush=True)
"""

# ---------------------------------------------------------------------------
# RETURN check (fires every real relocalization update once a landmark has
# been placed and not yet recognized) -- ~line 4507
# ---------------------------------------------------------------------------
"""
if (
    anchor0_landmark_v11_session is not None
    and anchor0_landmark_state["placed"]
    and not anchor0_landmark_state["recognized"]
):
    try:
        from route_memory_agent import RouteAnchor

        landmark_anchor = RouteAnchor(
            index=-1,
            pose_from_start=[0.0, 0.0, 0.0],
            distance_from_start_m=0.0,
            route_remaining_to_start_m=0.0,
            descriptor=anchor0_landmark_state["descriptor"],
        )
        landmark_diag = {}
        sequential_pair_anchor_relocalization(
            descriptor,
            landmark_anchor,
            landmark_anchor,
            additional_anchors=(),
            diagnostics=landmark_diag,
            return_candidates=True,
            capture_match_snapshots=False,
            icp_objective=args_cli.route_local_map_icp_objective,
            voxel_size_m=local_map_voxel_size_m,
            max_points=local_map_max_points,
            quality_policy=args_cli.route_local_map_quality_policy,
        )
        landmark_records = landmark_diag.get("covisibility_records", [])
        if landmark_records:
            landmark_outputs = anchor0_landmark_v11_session.score_records(
                landmark_records, step=int(num_steps)
            )
            landmark_record = landmark_records[0]
            landmark_output = landmark_outputs[0] if landmark_outputs else {}
            est_distance = landmark_record.get("estimated_distance_to_anchor_m")
            pose_trusted = bool(landmark_output.get("pose_trusted"))
            with open(anchor0_landmark_log_path, "a") as landmark_handle:
                landmark_handle.write(json.dumps({
                    "event": "return_check",
                    "step": int(num_steps),
                    "estimated_distance_to_landmark_m": est_distance,
                    "pose_trusted": pose_trusted,
                }) + "\\n")
            if (
                pose_trusted
                and est_distance is not None
                and float(est_distance) <= args_cli.anchor0_landmark_trigger_distance_m
            ):
                anchor0_landmark_state["recognized"] = True
                anchor0_landmark_state["recognized_step"] = int(num_steps)
                with open(anchor0_landmark_log_path, "a") as landmark_handle:
                    landmark_handle.write(json.dumps({
                        "event": "landmark_recognized",
                        "step": int(num_steps),
                        "estimated_distance_to_landmark_m": est_distance,
                    }) + "\\n")
    except Exception as exc:
        print(f"[anchor0-landmark] WARNING: return check failed at step {num_steps}: {exc}", flush=True)
"""
