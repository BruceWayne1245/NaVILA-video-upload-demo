# Multiframe merge fix for the anchor0-landmark descriptor, extracted from
# navila-route2-v11-core-20260801/runtime_candidate/scripts/round_trip_eval.py
# (that file is not tracked whole in this repo -- see
# round_trip_eval_diff_snippets.py for the same convention, which this file
# continues). Implements the fix described in FINDINGS.md's "2026-08-10/11:
# multiframe merge fix implemented" section: the landmark descriptor was a
# single, un-merged frame (overlap_ratio capped at 0.45-0.75 across 683
# return-phase attempts, 0/683 pose_trusted); this reuses the same
# backward+forward frame-merge primitive already built and vetted for real
# waypoint anchors (RouteMemoryAgent._merge_point_frames /
# _begin_pending_anchor / _finalize_pending_anchor), WITHOUT calling that
# real-anchor state machine directly -- see the inline comments below for
# why (shared single-occupancy _pending_anchor slot, and its finalize path
# inserts into route_agent.anchors, which the landmark must never do).
#
# Not yet smoke-tested live as of this commit -- next step is a 1-episode
# rerun (e.g. ep386) with --route_memory_multiframe_anchor_symmetric_enabled
# added to the launch command.

# ---------------------------------------------------------------------------
# anchor0_landmark_state dict additions (~line 3378, next to the existing
# fields)
# ---------------------------------------------------------------------------
"""
    anchor0_landmark_state = {
        "placed": False,
        "placed_step": None,
        "descriptor": None,
        "recognized": False,
        "recognized_step": None,
        "last_outbound_check_step": None,
        "last_return_check_step": None,
        # 2026-08-11: symmetric multiframe merge for the landmark descriptor
        # (see investigations/2026-08-10-anchor0-landmark/FINDINGS.md's
        # overlap-ratio root cause). Own pending-window bookkeeping, kept
        # entirely separate from route_agent._pending_anchor -- that slot is
        # single-occupancy and shared with real outbound anchor placement,
        # and its own finalize path inserts into route_agent.anchors, which
        # the landmark must never do.
        "awaiting_merge": False,
        "pending_trigger_distance_m": None,
        "pending_trigger_pose": None,
        "pending_fallback_descriptor": None,
        "pending_backward_frames": None,
        "pending_updates": 0,
    }
"""

# ---------------------------------------------------------------------------
# Finalize-check: runs every outbound step (right after
# route_agent.update_outbound_motion, unconditionally -- NOT gated by the
# interval-gated ICP trigger check below it) -- ~line 5521
# ---------------------------------------------------------------------------
"""
                if (
                    anchor0_landmark_v11_session is not None
                    and anchor0_landmark_state["awaiting_merge"]
                ):
                    try:
                        anchor0_landmark_state["pending_updates"] += 1
                        forward_m = (
                            float(route_agent._outbound_distance_m)
                            - anchor0_landmark_state["pending_trigger_distance_m"]
                        )
                        if (
                            forward_m >= route_agent.multiframe_anchor_forward_distance_m
                            or anchor0_landmark_state["pending_updates"]
                            >= route_agent.multiframe_anchor_forward_stall_updates
                        ):
                            trigger_distance_m = anchor0_landmark_state["pending_trigger_distance_m"]
                            trigger_pose = anchor0_landmark_state["pending_trigger_pose"]
                            hi = trigger_distance_m + route_agent.multiframe_anchor_forward_distance_m
                            # Backward frames were snapshotted at trigger time
                            # (see below) -- route_agent's own buffer prunes
                            # its backward margin relative to the *current*
                            # advancing distance whenever no real anchor is
                            # concurrently pending in route_agent._pending_anchor
                            # (see its update_outbound_motion docstring
                            # comment), which would otherwise silently evict
                            # this landmark's pre-trigger frames before this
                            # forward window finishes accumulating. Only the
                            # forward half is safe to re-read fresh here.
                            forward_frames = [
                                (pose, desc)
                                for (dist, pose, desc) in route_agent._outbound_symmetric_frame_buffer
                                if trigger_distance_m < dist <= hi
                            ]
                            frames = (
                                anchor0_landmark_state["pending_backward_frames"] + forward_frames
                            )
                            merged = route_agent._merge_point_frames(frames, trigger_pose)
                            descriptor = (
                                merged if merged is not None
                                else anchor0_landmark_state["pending_fallback_descriptor"]
                            )
                            anchor0_landmark_state["awaiting_merge"] = False
                            anchor0_landmark_state["placed"] = True
                            anchor0_landmark_state["placed_step"] = int(num_steps)
                            anchor0_landmark_state["descriptor"] = descriptor
                            with open(anchor0_landmark_log_path, "a") as landmark_handle:
                                landmark_handle.write(json.dumps({
                                    "event": "landmark_placed",
                                    "step": int(num_steps),
                                    "trigger_distance_m": trigger_distance_m,
                                    "multiframe": True,
                                    "multiframe_frame_count": len(frames),
                                    "multiframe_merge_succeeded": merged is not None,
                                }) + "\\n")
                            print(
                                f"[anchor0-landmark] placed (multiframe) at step {num_steps}, "
                                f"{len(frames)} frames merged (fallback={merged is None})",
                                flush=True,
                            )
                    except Exception as exc:
                        anchor0_landmark_state["awaiting_merge"] = False
                        anchor0_landmark_state["placed"] = True
                        anchor0_landmark_state["placed_step"] = int(num_steps)
                        anchor0_landmark_state["descriptor"] = (
                            anchor0_landmark_state["pending_fallback_descriptor"]
                        )
                        print(
                            f"[anchor0-landmark] WARNING: multiframe merge failed at step {num_steps}, "
                            f"falling back to single frame: {exc}",
                            flush=True,
                        )
"""

# ---------------------------------------------------------------------------
# Outbound ICP-trigger block: the existing "and not anchor0_landmark_state
# ['placed']" guard gains "and not anchor0_landmark_state['awaiting_merge']"
# (so the interval-gated ICP check stops re-firing once a merge window is
# pending), and the trigger branch splits on whether symmetric multiframe is
# enabled -- ~line 5592
# ---------------------------------------------------------------------------
"""
                if (
                    anchor0_landmark_v11_session is not None
                    and not anchor0_landmark_state["placed"]
                    and not anchor0_landmark_state["awaiting_merge"]
                    and phase == "outbound"
                    and (
                        anchor0_landmark_state["last_outbound_check_step"] is None
                        or int(num_steps) - anchor0_landmark_state["last_outbound_check_step"]
                        >= args_cli.anchor0_landmark_interval_env_steps
                    )
                ):
                    ...  # unchanged ICP-vs-real-anchor0 check, same as before
                                if (
                                    pose_trusted
                                    and est_distance is not None
                                    and float(est_distance) <= args_cli.anchor0_landmark_trigger_distance_m
                                ):
                                    if route_agent.multiframe_anchor_symmetric_enabled:
                                        # Don't finalize on a single frame --
                                        # defer and accumulate a
                                        # backward+forward window the same
                                        # way _begin_pending_anchor/
                                        # _finalize_pending_anchor do for
                                        # real anchors (see FINDINGS.md:
                                        # single-frame overlap_ratio topped
                                        # out at 0.45-0.75, well under the
                                        # ~0.84+ trusted matches elsewhere
                                        # need). Own bookkeeping, not
                                        # route_agent._pending_anchor -- see
                                        # anchor0_landmark_state's comment.
                                        trigger_distance_m = float(route_agent._outbound_distance_m)
                                        lo = (
                                            trigger_distance_m
                                            - route_agent.multiframe_anchor_backward_distance_m
                                        )
                                        anchor0_landmark_state["awaiting_merge"] = True
                                        anchor0_landmark_state["pending_trigger_distance_m"] = (
                                            trigger_distance_m
                                        )
                                        anchor0_landmark_state["pending_trigger_pose"] = [
                                            float(x) for x in route_agent._outbound_pose_from_start
                                        ]
                                        anchor0_landmark_state["pending_fallback_descriptor"] = route_descriptor
                                        # Snapshot now, before route_agent's own
                                        # rolling prune (keyed off its own
                                        # _pending_anchor, which this landmark
                                        # never sets) can evict these.
                                        anchor0_landmark_state["pending_backward_frames"] = [
                                            (pose, desc)
                                            for (dist, pose, desc) in route_agent._outbound_symmetric_frame_buffer
                                            if lo <= dist <= trigger_distance_m
                                        ]
                                        anchor0_landmark_state["pending_updates"] = 0
                                        with open(anchor0_landmark_log_path, "a") as landmark_handle:
                                            landmark_handle.write(json.dumps({
                                                "event": "landmark_trigger_pending_merge",
                                                "step": int(num_steps),
                                                "estimated_distance_to_anchor0_m": est_distance,
                                            }) + "\\n")
                                        print(
                                            f"[anchor0-landmark] trigger fired at step {num_steps}, "
                                            f"estimated_distance={est_distance:.3f}m -- accumulating "
                                            f"multiframe window before placing",
                                            flush=True,
                                        )
                                    else:
                                        # Unchanged fallback path when
                                        # --route_memory_multiframe_anchor_symmetric_enabled
                                        # is off: single-frame placement, exactly
                                        # as before 2026-08-11 (keeps old runs
                                        # reproducible).
                                        anchor0_landmark_state["placed"] = True
                                        anchor0_landmark_state["placed_step"] = int(num_steps)
                                        anchor0_landmark_state["descriptor"] = route_descriptor
                                        with open(anchor0_landmark_log_path, "a") as landmark_handle:
                                            landmark_handle.write(json.dumps({
                                                "event": "landmark_placed",
                                                "step": int(num_steps),
                                                "estimated_distance_to_anchor0_m": est_distance,
                                                "multiframe": False,
                                            }) + "\\n")
                                        print(
                                            f"[anchor0-landmark] placed at step {num_steps}, "
                                            f"estimated_distance={est_distance:.3f}m",
                                            flush=True,
                                        )
"""
