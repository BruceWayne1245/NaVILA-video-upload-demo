import math
import unittest

from route_memory_agent import (
    AnchorRelocalization,
    RelativeStartProgress,
    RouteMemoryAgent,
    compose_pose,
    diagnostic_frame_thresholds_to_fire,
    inverse_delta,
    relative_delta,
)


class DiagnosticFrameThresholdsTest(unittest.TestCase):
    """2026-07-03: --capture_route_memory_diagnostic_frames samples ~4 frames
    per episode by fraction of route remaining, not step count -- this is
    the pure crossing-detection logic round_trip_eval.py's per-step loop
    calls into."""

    def test_no_thresholds_fire_above_the_first_one(self):
        self.assertEqual(diagnostic_frame_thresholds_to_fire(0.9, already_fired=set()), [])

    def test_crossing_below_first_threshold_fires_only_that_one(self):
        self.assertEqual(diagnostic_frame_thresholds_to_fire(0.6, already_fired=set()), [0.75])

    def test_a_big_jump_fires_every_threshold_crossed_at_once(self):
        # e.g. a long blackout between progress checks skipping past several
        # thresholds in one step -- all of them should still fire, not just
        # the nearest one, so no diagnostic stage is silently skipped.
        self.assertEqual(diagnostic_frame_thresholds_to_fire(0.1, already_fired=set()), [0.75, 0.5, 0.25])

    def test_already_fired_thresholds_do_not_refire(self):
        self.assertEqual(diagnostic_frame_thresholds_to_fire(0.1, already_fired={0.75, 0.5}), [0.25])

    def test_all_fired_yields_nothing_further(self):
        self.assertEqual(
            diagnostic_frame_thresholds_to_fire(0.0, already_fired={0.75, 0.5, 0.25, 0.05}), []
        )


class RouteMemoryAgentTest(unittest.TestCase):
    def test_compose_and_relative_delta_round_trip(self):
        start = [1.0, 2.0, math.pi / 2]
        delta = [1.0, 0.2, -math.pi / 4]
        end = compose_pose(start, delta)
        recovered = relative_delta(start, end)
        for actual, expected in zip(recovered, delta):
            self.assertAlmostEqual(actual, expected, places=6)

    def test_inverse_delta_returns_to_previous_pose(self):
        outbound = [0.75, 0.0, math.radians(15.0)]
        arrival = compose_pose([0.0, 0.0, 0.0], outbound)
        recovered = compose_pose(arrival, inverse_delta(outbound))
        for actual, expected in zip(recovered, [0.0, 0.0, 0.0]):
            self.assertAlmostEqual(actual, expected, places=6)

    def test_outbound_integrates_start_to_return_start_pose(self):
        agent = RouteMemoryAgent(enabled=True)
        agent.update_outbound_motion([1.0, 0.0, 0.0])
        agent.update_outbound_motion([0.0, 1.0, math.pi / 2])
        agent.finalize_outbound()

        summary = agent.summary()
        self.assertEqual(summary["localizer"], "action_integrated_relative_start")
        self.assertEqual(summary["outbound_pose_from_start"], summary["return_start_pose_from_start"])
        self.assertAlmostEqual(summary["return_start_pose_from_start"][0], 1.0)
        self.assertAlmostEqual(summary["return_start_pose_from_start"][1], 1.0)
        self.assertAlmostEqual(summary["return_start_pose_from_start"][2], math.pi / 2)

    def test_progress_reports_start_relative_to_current_return_pose(self):
        agent = RouteMemoryAgent(enabled=True)
        agent.update_outbound_motion([2.0, 0.0, 0.0])
        agent.finalize_outbound()
        progress = agent.progress()
        self.assertAlmostEqual(progress.target_dx_m, -2.0)
        self.assertAlmostEqual(progress.target_dy_m, 0.0)
        self.assertAlmostEqual(progress.distance_to_start_m, 2.0)

        agent.update_return_motion([-0.5, 0.0, 0.0])
        progress = agent.progress()
        self.assertAlmostEqual(progress.target_dx_m, -1.5)
        self.assertAlmostEqual(progress.distance_to_start_m, 1.5)

    def test_hint_uses_start_distance_not_anchor_chain(self):
        agent = RouteMemoryAgent(enabled=True)
        agent.update_outbound_motion([2.0, 0.0, 0.0])
        agent.finalize_outbound()
        instruction, event = agent.inject_hint("Return to start.", step=10)

        self.assertIsNotNone(event)
        self.assertIn("original start", instruction)
        self.assertIn("2.00 m away", instruction)
        self.assertIn("Return to start.", instruction)
        self.assertNotIn("anchor", instruction.lower())

    def test_hint_can_use_external_progress_override(self):
        agent = RouteMemoryAgent(enabled=True)
        agent.update_outbound_motion([2.0, 0.0, 0.0])
        agent.finalize_outbound()
        progress = RelativeStartProgress(
            target_dx_m=0.25,
            target_dy_m=-0.25,
            distance_to_start_m=0.35,
            bearing_to_start_deg=-45.0,
            current_pose_from_start=[0.0, 0.0, 0.0],
            return_pose_from_return_start=[],
            return_start_pose_from_start=[],
        )

        instruction, event = agent.inject_hint(
            "Return to start.",
            step=10,
            progress_override=progress,
        )

        self.assertIsNotNone(event)
        self.assertIn("0.35 m away", instruction)
        self.assertIn("45 deg to your right", instruction)

    def test_direct_oracle_override_bypasses_particle_filter_hint(self):
        agent = RouteMemoryAgent(enabled=True, anchor_spacing_m=1.0)
        agent.update_outbound_motion([1.0, 0.0, 0.0])
        agent.update_outbound_motion([1.0, 0.0, 0.0])
        agent.finalize_outbound()
        agent.update_relocalization(relocalization=AnchorRelocalization(
            anchor_index=1,
            anchor_dx_m=1.5,
            anchor_dy_m=0.5,
            anchor_dtheta_rad=0.0,
            confidence=0.9,
            backend="oracle_anchor",
            inlier_count=1,
        ))
        self.assertEqual(agent.progress().source, "arc_length_particle_filter")

        oracle_progress = RelativeStartProgress(
            target_dx_m=1.2,
            target_dy_m=-0.4,
            distance_to_start_m=math.hypot(1.2, -0.4),
            bearing_to_start_deg=math.degrees(math.atan2(-0.4, 1.2)),
            current_pose_from_start=[-1.2, 0.4, 0.0],
            return_pose_from_return_start=[],
            return_start_pose_from_start=[],
            source="direct_oracle_start",
            relocalization_confidence=1.0,
            relocalization_backend="oracle_direct",
            filter_std_m=None,
        )

        instruction, event = agent.inject_hint(
            "Return to start.",
            step=20,
            progress_override=oracle_progress,
        )

        self.assertIsNotNone(event)
        self.assertIn("original start", instruction)
        self.assertIn("1.26 m away", instruction)
        self.assertNotIn("route anchor", instruction)
        self.assertNotIn("filter lost", instruction)
        self.assertEqual(event["progress"]["source"], "direct_oracle_start")
        self.assertIsNone(event["progress"]["target_anchor_index"])
        self.assertIsNone(event["progress"]["filter_std_m"])

    def test_direct_oracle_route_anchor_hint_names_next_anchor_vector(self):
        agent = RouteMemoryAgent(enabled=True, anchor_spacing_m=1.0)
        agent.update_outbound_motion([1.0, 0.0, 0.0])
        agent.update_outbound_motion([1.0, 0.0, 0.0])
        agent.finalize_outbound()
        progress = RelativeStartProgress(
            target_dx_m=0.8,
            target_dy_m=0.2,
            distance_to_start_m=1.8,
            bearing_to_start_deg=14.0,
            current_pose_from_start=[1.8, 0.0, 0.0],
            return_pose_from_return_start=[],
            return_start_pose_from_start=[],
            source="direct_oracle_route_anchor",
            target_anchor_index=1,
            anchor_dx_m=0.8,
            anchor_dy_m=0.2,
            distance_to_anchor_m=math.hypot(0.8, 0.2),
            bearing_to_anchor_deg=math.degrees(math.atan2(0.2, 0.8)),
            anchor_route_remaining_m=1.0,
            anchor_heading_reliable=True,
            relocalization_confidence=1.0,
            relocalization_backend="oracle_direct_route_anchor",
            filter_std_m=None,
        )

        instruction, event = agent.inject_hint(
            "Return to start.",
            step=20,
            progress_override=progress,
        )

        self.assertIsNotNone(event)
        self.assertIn("route anchor A1", instruction)
        self.assertIn("next-anchor vector", instruction)
        self.assertNotIn("start vector dx=", instruction)
        self.assertEqual(event["progress"]["source"], "direct_oracle_route_anchor")

    def test_outbound_saves_route_anchors_with_remaining_distance(self):
        agent = RouteMemoryAgent(enabled=True, anchor_spacing_m=1.0)
        agent.update_outbound_motion([0.5, 0.0, 0.0])
        agent.update_outbound_motion([0.6, 0.0, 0.0], descriptor={"kind": "height_map"})
        agent.update_outbound_motion([1.0, 0.0, 0.0])
        agent.finalize_outbound()

        summary = agent.summary()
        self.assertGreaterEqual(len(summary["anchors"]), 3)
        self.assertEqual(summary["anchors"][0]["metadata"]["event"], "start")
        self.assertEqual(summary["anchors"][1]["descriptor"], {"kind": "height_map"})
        self.assertAlmostEqual(summary["anchors"][0]["route_remaining_to_start_m"], 0.0)
        self.assertAlmostEqual(summary["anchors"][-1]["route_remaining_to_start_m"], 2.1)

    def test_full_pose_anchor_relocalization_overrides_integrated_start_hint(self):
        agent = RouteMemoryAgent(enabled=True, anchor_spacing_m=1.0)
        agent.update_outbound_motion([1.0, 0.0, 0.0])
        agent.update_outbound_motion([1.0, 0.0, 0.0])
        agent.finalize_outbound()

        estimate = AnchorRelocalization(
            anchor_index=1,
            anchor_dx_m=1.8,
            anchor_dy_m=0.6,
            anchor_dtheta_rad=0.0,
            confidence=0.82,
            backend="external_full_pose",
            inlier_count=42,
        )
        agent.update_relocalization(relocalization=estimate)

        progress = agent.progress()
        self.assertEqual(progress.source, "arc_length_particle_filter")
        self.assertEqual(progress.target_anchor_index, 0)
        self.assertAlmostEqual(progress.distance_to_start_m, 0.0)
        self.assertAlmostEqual(progress.anchor_route_remaining_m, 0.0)
        self.assertAlmostEqual(progress.target_dx_m, 0.8)
        self.assertAlmostEqual(progress.target_dy_m, 0.6)

        instruction, event = agent.inject_hint("Return to start.", step=20)
        self.assertIsNotNone(event)
        self.assertIn("route anchor A0", instruction)
        self.assertIn("estimated remaining route via anchor", instruction)
        self.assertEqual(event["progress"]["relocalization_backend"], "external_full_pose")

    def test_translation_only_anchor_does_not_rotate_start_vector_with_fake_heading(self):
        agent = RouteMemoryAgent(enabled=True, anchor_spacing_m=0.1)
        agent.update_outbound_motion([2.0, 0.0, math.pi / 2])
        agent.finalize_outbound()
        agent.update_return_motion([0.0, 0.0, math.pi / 2])

        agent.update_relocalization(relocalization=AnchorRelocalization(
            anchor_index=1,
            anchor_dx_m=0.0,
            anchor_dy_m=0.0,
            anchor_dtheta_rad=0.0,
            confidence=0.9,
            backend="feature_depth_loftr_3d3d",
            anchor_heading_reliable=False,
        ))

        progress = agent.progress()
        self.assertEqual(progress.source, "arc_length_particle_filter")
        self.assertFalse(progress.anchor_heading_reliable)
        self.assertEqual(progress.current_pose_from_start, [2.0, 0.0, math.pi])
        self.assertAlmostEqual(progress.target_dx_m, 2.0, places=6)
        self.assertAlmostEqual(progress.target_dy_m, 0.0, places=6)
        self.assertLessEqual(progress.anchor_route_remaining_m, 2.0)

        instruction, event = agent.inject_hint("Return to start.", step=20)
        self.assertIsNotNone(event)
        self.assertIn("odometry start vector", instruction)
        self.assertFalse(event["progress"]["anchor_heading_reliable"])

    def test_full_pose_anchor_uses_reliable_heading_to_chain_start_vector(self):
        agent = RouteMemoryAgent(enabled=True, anchor_spacing_m=0.1)
        agent.update_outbound_motion([2.0, 0.0, math.pi / 2])
        agent.finalize_outbound()
        agent.update_return_motion([0.0, 0.0, math.pi / 2])

        agent.update_relocalization(relocalization=AnchorRelocalization(
            anchor_index=1,
            anchor_dx_m=0.0,
            anchor_dy_m=0.0,
            anchor_dtheta_rad=-math.pi / 2,
            confidence=0.9,
            backend="external_full_pose",
            anchor_heading_reliable=True,
        ))

        progress = agent.progress()
        self.assertTrue(progress.anchor_heading_reliable)
        self.assertAlmostEqual(progress.target_dx_m, 2.0, places=6)
        self.assertAlmostEqual(progress.target_dy_m, 0.0, places=6)

    def test_anchor_target_is_monotonic_toward_start(self):
        agent = RouteMemoryAgent(enabled=True, anchor_spacing_m=1.0)
        for _ in range(4):
            agent.update_outbound_motion([1.0, 0.0, 0.0])
        agent.finalize_outbound()

        accepted = agent.update_relocalization(relocalization=AnchorRelocalization(
            anchor_index=3,
            anchor_dx_m=0.4,
            anchor_dy_m=0.0,
            anchor_dtheta_rad=0.0,
            confidence=0.9,
            backend="external_full_pose",
        ))
        self.assertIsNotNone(accepted)

        rejected = agent.update_relocalization(relocalization=AnchorRelocalization(
            anchor_index=4,
            anchor_dx_m=0.2,
            anchor_dy_m=0.0,
            anchor_dtheta_rad=0.0,
            confidence=0.9,
            backend="external_full_pose",
        ))
        self.assertIsNone(rejected)
        self.assertEqual(agent.progress().target_anchor_index, 2)
        self.assertEqual(
            agent.relocalization_events[-1]["reject_reason"],
            "no_sequence_candidates",
        )

    def test_passed_anchor_advances_to_next_route_target(self):
        agent = RouteMemoryAgent(enabled=True, anchor_spacing_m=1.0)
        for _ in range(4):
            agent.update_outbound_motion([1.0, 0.0, 0.0])
        agent.finalize_outbound()

        agent.update_relocalization(relocalization=AnchorRelocalization(
            anchor_index=3,
            anchor_dx_m=0.2,
            anchor_dy_m=0.0,
            anchor_dtheta_rad=0.0,
            confidence=0.9,
            backend="external_full_pose",
        ))
        agent.update_return_motion([1.0, 0.0, 0.0])

        progress = agent.progress()
        self.assertEqual(progress.target_anchor_index, 1)
        self.assertEqual(progress.relocalization_backend, "external_full_pose")
        self.assertEqual(progress.source, "arc_length_particle_filter")
        self.assertAlmostEqual(progress.distance_to_start_m, 1.8)

    def test_passed_anchor_can_advance_without_entering_tight_radius(self):
        agent = RouteMemoryAgent(enabled=True, anchor_spacing_m=1.0)
        for _ in range(4):
            agent.update_outbound_motion([1.0, 0.0, 0.0])
        agent.finalize_outbound()

        agent.update_relocalization(relocalization=AnchorRelocalization(
            anchor_index=3,
            anchor_dx_m=1.5,
            anchor_dy_m=0.0,
            anchor_dtheta_rad=0.0,
            confidence=0.9,
            backend="external_full_pose",
        ))
        agent.update_return_motion([-0.7, 0.0, 0.0])

        progress = agent.progress()
        self.assertEqual(progress.target_anchor_index, 0)
        self.assertEqual(progress.relocalization_backend, "external_full_pose")

    def test_low_confidence_relocalization_is_ignored(self):
        agent = RouteMemoryAgent(enabled=True, min_relocalization_confidence=0.5)
        agent.update_outbound_motion([1.0, 0.0, 0.0])
        agent.finalize_outbound()
        agent.update_relocalization(relocalization={
            "anchor_index": 1,
            "anchor_dx_m": 1.0,
            "anchor_dy_m": 0.0,
            "confidence": 0.1,
        })

        progress = agent.progress()
        self.assertEqual(progress.source, "action_integrated_relative_start")

    def test_relocalization_is_propagated_by_return_odometry(self):
        agent = RouteMemoryAgent(enabled=True, anchor_spacing_m=1.0)
        agent.update_outbound_motion([1.0, 0.0, 0.0])
        agent.finalize_outbound()
        agent.update_relocalization(relocalization=AnchorRelocalization(
            anchor_index=1,
            anchor_dx_m=2.0,
            anchor_dy_m=0.0,
            confidence=0.9,
            backend="feature_depth_sift_3d3d",
            anchor_heading_reliable=False,
        ))

        agent.update_return_motion([0.5, 0.0, 0.0])
        progress = agent.progress()
        self.assertEqual(progress.source, "arc_length_particle_filter")
        latest = agent.summary()["latest_relocalization"]
        self.assertAlmostEqual(latest["anchor_dx_m"], 1.5)

    def test_arc_length_filter_keeps_remaining_distance_monotonic_past_anchor(self):
        agent = RouteMemoryAgent(enabled=True, anchor_spacing_m=1.0)
        for _ in range(6):
            agent.update_outbound_motion([1.0, 0.0, 0.0])
        agent.finalize_outbound()

        agent.update_relocalization(relocalization=AnchorRelocalization(
            anchor_index=4,
            anchor_dx_m=1.0,
            anchor_dy_m=0.0,
            anchor_dtheta_rad=0.0,
            confidence=0.9,
            backend="external_full_pose",
        ))
        previous_distance = agent.progress().distance_to_start_m

        for _ in range(4):
            agent.update_return_motion([0.5, 0.0, 0.0])
            current_distance = agent.progress().distance_to_start_m
            self.assertLessEqual(current_distance, previous_distance + 0.25)
            previous_distance = current_distance

        progress = agent.progress()
        self.assertEqual(progress.source, "arc_length_particle_filter")
        self.assertLessEqual(progress.target_anchor_index, 4)

    def test_inconsistent_relocalization_is_rejected(self):
        agent = RouteMemoryAgent(
            enabled=True,
            anchor_spacing_m=1.0,
            max_relocalization_consistency_error_m=1.0,
        )
        agent.update_outbound_motion([2.0, 0.0, 0.0])
        agent.finalize_outbound()
        result = agent.update_relocalization(relocalization=AnchorRelocalization(
            anchor_index=1,
            anchor_dx_m=20.0,
            anchor_dy_m=0.0,
            confidence=0.9,
            backend="external_full_pose",
        ))

        self.assertIsNone(result)
        progress = agent.progress()
        self.assertEqual(progress.source, "action_integrated_relative_start")
        summary = agent.summary()
        self.assertFalse(summary["relocalization_events"][-1]["accepted"])
        self.assertEqual(
            summary["relocalization_events"][-1]["reject_reason"],
            "no_sequence_candidates",
        )

    def test_fusion_blends_agreeing_candidates_from_same_query(self):
        """Direction 2: candidates from the same relocalization query that agree
        (same anchor, close heading/position) should be averaged, not reduced to
        the single top-scored one."""
        agent = RouteMemoryAgent(enabled=True, anchor_spacing_m=1.0)
        agent.update_outbound_motion([1.0, 0.0, 0.0])
        agent.update_outbound_motion([1.0, 0.0, 0.0])
        agent.finalize_outbound()

        candidate_a = AnchorRelocalization(
            anchor_index=1, anchor_dx_m=1.0, anchor_dy_m=0.0, anchor_dtheta_rad=0.0,
            confidence=0.95, backend="local_map_icp", inlier_count=40,
        )
        candidate_b = AnchorRelocalization(
            anchor_index=1, anchor_dx_m=1.02, anchor_dy_m=0.03, anchor_dtheta_rad=math.radians(20.0),
            confidence=0.9, backend="local_map_icp", inlier_count=38,
        )
        result = agent.update_relocalization(relocalization=[candidate_a, candidate_b])

        self.assertIsNotNone(result)
        self.assertIn("+fused2", result.backend)
        fused_dtheta_deg = math.degrees(result.anchor_dtheta_rad)
        # Strictly between the two raw candidates -- proves averaging happened
        # instead of winner-take-all (which would land exactly on 0.0 or 20.0).
        self.assertGreater(fused_dtheta_deg, 0.0)
        self.assertLess(fused_dtheta_deg, 20.0)

    def test_fusion_excludes_disagreeing_candidate(self):
        """Direction 2 must not average in a candidate that disagrees sharply with
        the top pick (e.g. a competing +1-anchor-bias hypothesis) -- that would
        just reintroduce the P1 ambiguity problem in reverse."""
        agent = RouteMemoryAgent(enabled=True, anchor_spacing_m=1.0)
        agent.update_outbound_motion([1.0, 0.0, 0.0])
        agent.update_outbound_motion([1.0, 0.0, 0.0])
        agent.finalize_outbound()

        candidate_a = AnchorRelocalization(
            anchor_index=1, anchor_dx_m=1.0, anchor_dy_m=0.0, anchor_dtheta_rad=0.0,
            confidence=0.95, backend="local_map_icp", inlier_count=40,
        )
        candidate_b = AnchorRelocalization(
            anchor_index=1, anchor_dx_m=1.0, anchor_dy_m=0.0, anchor_dtheta_rad=math.radians(60.0),
            confidence=0.9, backend="local_map_icp", inlier_count=38,
        )
        result = agent.update_relocalization(relocalization=[candidate_a, candidate_b])

        self.assertIsNotNone(result)
        self.assertNotIn("+fused", result.backend)
        # Whichever of the two wins the SeqSLAM continuity race, the result must be
        # exactly one of the two raw candidates -- not an in-between blend, which
        # would mean a disagreeing candidate got averaged in.
        matches_a = math.isclose(result.anchor_dtheta_rad, 0.0, abs_tol=1e-6)
        matches_b = math.isclose(result.anchor_dtheta_rad, math.radians(60.0), abs_tol=1e-6)
        self.assertTrue(matches_a or matches_b, f"unexpected blended dtheta: {result.anchor_dtheta_rad}")

    def test_temporal_smoothing_blends_across_successive_estimates(self):
        """Direction 1: a second accepted estimate should be blended with the
        previous filtered belief, not overwrite it outright.

        Calls _temporally_smooth_relocalization directly (rather than through
        update_relocalization/_sequence_match_observation) so this test is
        isolated from the independent SeqSLAM motion-consistency gate, which
        has its own dedicated coverage elsewhere in this file."""
        agent = RouteMemoryAgent(enabled=True, anchor_spacing_m=1.0)
        agent.update_outbound_motion([1.0, 0.0, 0.0])
        agent.update_outbound_motion([1.0, 0.0, 0.0])
        agent.finalize_outbound()

        first = AnchorRelocalization(
            anchor_index=1, anchor_dx_m=1.0, anchor_dy_m=0.0, anchor_dtheta_rad=0.0,
            confidence=0.9, backend="local_map_icp", inlier_count=40,
        )
        first_smoothed = agent._temporally_smooth_relocalization(first)
        self.assertNotIn("+ema", first_smoothed.backend)  # nothing to blend with yet
        agent._latest_relocalization = first_smoothed

        second = AnchorRelocalization(
            anchor_index=1, anchor_dx_m=1.0, anchor_dy_m=0.0, anchor_dtheta_rad=math.radians(20.0),
            confidence=0.9, backend="local_map_icp", inlier_count=40,
        )
        second_smoothed = agent._temporally_smooth_relocalization(second)

        self.assertIn("+ema", second_smoothed.backend)
        second_dtheta_deg = math.degrees(second_smoothed.anchor_dtheta_rad)
        # Strictly between the previous belief (0 deg) and the fresh estimate
        # (20 deg) -- proves blending happened instead of an outright overwrite.
        self.assertGreater(second_dtheta_deg, 0.0)
        self.assertLess(second_dtheta_deg, 20.0)

    def test_temporal_smoothing_trusts_fresh_estimate_on_sharp_disagreement(self):
        """Direction 1 must not average toward a stale belief when the fresh
        estimate disagrees sharply -- that would just re-introduce lag/latency."""
        agent = RouteMemoryAgent(enabled=True, anchor_spacing_m=1.0)
        agent.update_outbound_motion([1.0, 0.0, 0.0])
        agent.update_outbound_motion([1.0, 0.0, 0.0])
        agent.finalize_outbound()

        first = AnchorRelocalization(
            anchor_index=1, anchor_dx_m=1.0, anchor_dy_m=0.0, anchor_dtheta_rad=0.0,
            confidence=0.9, backend="local_map_icp", inlier_count=40,
        )
        agent._latest_relocalization = agent._temporally_smooth_relocalization(first)

        second = AnchorRelocalization(
            anchor_index=1, anchor_dx_m=1.0, anchor_dy_m=0.0, anchor_dtheta_rad=math.radians(90.0),
            confidence=0.9, backend="local_map_icp", inlier_count=40,
        )
        second_smoothed = agent._temporally_smooth_relocalization(second)

        self.assertNotIn("+ema", second_smoothed.backend)
        self.assertAlmostEqual(second_smoothed.anchor_dtheta_rad, math.radians(90.0), places=6)

    def _make_agent_with_first_observation(self, n_anchors=7, anchor_spacing_m=1.0):
        """Shared setup: n_anchors anchors 1m apart, then one normal accepted
        observation (so self._sequence_observation.source is no longer
        'return_start_prior' -- the large-jump gate below is exempt for the
        prior, by design, so tests of that gate need a real prior observation
        first)."""
        agent = RouteMemoryAgent(enabled=True, anchor_spacing_m=anchor_spacing_m)
        # Widen the motion-continuity sigma so a multi-anchor jump isn't already
        # killed by the (independent, pre-existing) continuity-score gate --
        # isolates the large-forward-jump confirmation gate under test below.
        agent.sequence_motion_sigma_m = 3.0
        for _ in range(n_anchors - 1):
            agent.update_outbound_motion([1.0, 0.0, 0.0])
        agent.finalize_outbound()
        first = AnchorRelocalization(
            anchor_index=n_anchors - 2, anchor_dx_m=1.0, anchor_dy_m=0.0, anchor_dtheta_rad=0.0,
            confidence=0.9, backend="local_map_icp", inlier_count=40,
        )
        result = agent.update_relocalization(relocalization=first)
        self.assertIsNotNone(result)
        self.assertNotEqual(agent._sequence_observation.source, "return_start_prior")
        return agent

    def test_large_forward_jump_is_held_pending_not_trusted_outright(self):
        """2026-07-02 ep680 fix (1/2): a single observation implying the route is
        already finished (s~=0) when tracking was around s~=4 must not be
        trusted immediately -- this is exactly the failure that locked ep680's
        shadow path onto anchor 0 for the rest of the episode."""
        agent = self._make_agent_with_first_observation()
        jump = AnchorRelocalization(
            anchor_index=0, anchor_dx_m=0.0, anchor_dy_m=0.0, anchor_dtheta_rad=0.0,
            confidence=0.9, backend="local_map_icp", inlier_count=40,
        )
        first_attempt = agent.update_relocalization(relocalization=jump)
        self.assertIsNone(first_attempt)
        self.assertIsNotNone(agent._pending_jump_observed_s_m)
        # target_anchor_index must still reflect the earlier, trusted observation.
        self.assertNotEqual(agent._target_anchor_index, 0)

    def test_large_forward_jump_is_accepted_after_second_corroborating_observation(self):
        """A second, independent observation landing near the same implausible s
        confirms it wasn't noise -- now it should be trusted."""
        agent = self._make_agent_with_first_observation()
        jump = AnchorRelocalization(
            anchor_index=0, anchor_dx_m=0.0, anchor_dy_m=0.0, anchor_dtheta_rad=0.0,
            confidence=0.9, backend="local_map_icp", inlier_count=40,
        )
        agent.update_relocalization(relocalization=jump)  # first: held pending
        second_attempt = agent.update_relocalization(relocalization=jump)  # corroborates

        self.assertIsNotNone(second_attempt)
        self.assertEqual(agent._target_anchor_index, 0)
        self.assertIsNone(agent._pending_jump_observed_s_m)

    def test_pending_jump_is_superseded_by_a_normal_confirmed_observation(self):
        """If a normal (non-jump) observation gets accepted while a jump
        candidate is still pending, the stale pending guess must not linger to
        falsely confirm some unrelated later jump."""
        agent = self._make_agent_with_first_observation()
        jump = AnchorRelocalization(
            anchor_index=0, anchor_dx_m=0.0, anchor_dy_m=0.0, anchor_dtheta_rad=0.0,
            confidence=0.9, backend="local_map_icp", inlier_count=40,
        )
        agent.update_relocalization(relocalization=jump)
        self.assertIsNotNone(agent._pending_jump_observed_s_m)

        normal = AnchorRelocalization(
            anchor_index=5, anchor_dx_m=1.0, anchor_dy_m=0.0, anchor_dtheta_rad=0.0,
            confidence=0.9, backend="local_map_icp", inlier_count=40,
        )
        result = agent.update_relocalization(relocalization=normal)
        self.assertIsNotNone(result)
        self.assertIsNone(agent._pending_jump_observed_s_m)

    def test_vio_bridge_relaxes_after_prolonged_blackout(self):
        """2026-07-02 ep680 fix (2/2): once std has been elevated for a while
        with no accepted observation, the VIO bridge must eventually let a
        re-acquisition candidate through instead of suppressing forever.

        Both candidates below are motion-consistent with the current
        dead-reckoning expectation at the moment they're submitted (so neither
        trips the large-forward-jump gate under test elsewhere) -- this isolates
        the VIO std-threshold relaxation specifically.
        """
        agent = self._make_agent_with_first_observation()
        agent._arc_length_filter.std = lambda: 3.0  # fixed uncertainty for a deterministic test

        consistent_candidate = AnchorRelocalization(
            anchor_index=5, anchor_dx_m=1.0, anchor_dy_m=0.0, anchor_dtheta_rad=0.0,
            confidence=0.9, backend="local_map_icp", inlier_count=40,
        )
        # Immediately after the prior observation: base threshold (2.5) < std (3.0) -> suppressed.
        blocked = agent.update_relocalization(relocalization=consistent_candidate)
        self.assertIsNone(blocked)
        self.assertEqual(agent.relocalization_events[-1]["reject_reason"], "vio_bridge_suppressed")

        # Rack up blackout distance with no accepted observation (dead reckoning
        # alone drives the expected position down to the s=0 floor).
        for _ in range(6):
            agent.update_return_motion([-1.0, 0.0, 0.0])
        # effective_threshold = 2.5 + 0.3 * (distance_since - 3.0) > 3.0 once distance_since > ~4.67 m.
        self.assertGreater(agent._distance_since_sequence_observation_m, 4.67)

        late_candidate = AnchorRelocalization(
            anchor_index=0, anchor_dx_m=0.0, anchor_dy_m=0.0, anchor_dtheta_rad=0.0,
            confidence=0.9, backend="local_map_icp", inlier_count=40,
        )
        recovered = agent.update_relocalization(relocalization=late_candidate)
        self.assertIsNotNone(recovered)

    def test_compose_edges_between_matches_manual_composition(self):
        """Relative-edge pose graph (2026-07-02): composing the local
        edge_from_previous chain between two anchors must equal manually
        composing the individual outbound motions between them."""
        agent = RouteMemoryAgent(enabled=True, anchor_spacing_m=1.0)
        agent.update_outbound_motion([1.0, 0.0, 0.0])
        agent.update_outbound_motion([0.0, 1.0, math.radians(30.0)])
        agent.update_outbound_motion([1.0, 0.0, math.radians(-10.0)])
        agent.finalize_outbound()

        composed = agent._compose_edges_between(0, 3)
        manual = [0.0, 0.0, 0.0]
        for anchor in agent.anchors[1:]:
            manual = compose_pose(manual, anchor.edge_from_previous)
        for actual, expected in zip(composed, manual):
            self.assertAlmostEqual(actual, expected, places=9)

    def test_compose_edges_between_is_its_own_inverse(self):
        agent = RouteMemoryAgent(enabled=True, anchor_spacing_m=1.0)
        for _ in range(4):
            agent.update_outbound_motion([1.0, 0.1, math.radians(5.0)])
        agent.finalize_outbound()

        forward = agent._compose_edges_between(1, 4)
        backward = agent._compose_edges_between(4, 1)
        round_trip = compose_pose(forward, backward)
        for actual, expected in zip(round_trip, [0.0, 0.0, 0.0]):
            self.assertAlmostEqual(actual, expected, places=9)

    def test_estimate_arc_observation_ignores_unrelated_anchor_drift(self):
        """The route-position estimate for a match against anchor K must depend
        only on K's own scalar distance_from_start_m and the local ICP offset --
        not on any OTHER anchor's pose_from_start. Corrupting a distant anchor's
        stored pose (simulating accumulated outbound dead-reckoning drift) must
        not change the observed_s computed from a match against a different,
        uncorrupted anchor."""
        agent = RouteMemoryAgent(enabled=True, anchor_spacing_m=1.0)
        for _ in range(6):
            agent.update_outbound_motion([1.0, 0.0, 0.0])
        agent.finalize_outbound()

        estimate = AnchorRelocalization(
            anchor_index=3, anchor_dx_m=0.5, anchor_dy_m=0.0, anchor_dtheta_rad=0.0,
            confidence=0.9, backend="local_map_icp", inlier_count=40,
        )
        baseline = agent._estimate_arc_observation(estimate)

        # Corrupt a distant, unrelated anchor's pose (simulating outbound drift).
        agent.anchors[5].pose_from_start = [999.0, -123.0, 2.5]

        corrupted = agent._estimate_arc_observation(estimate)
        self.assertAlmostEqual(baseline.observed_s_m, corrupted.observed_s_m, places=9)

    def test_fallback_control_is_absent(self):
        agent = RouteMemoryAgent(enabled=True)
        agent.update_outbound_motion([1.0, 0.0, 0.0])
        agent.finalize_outbound()
        agent.update_return_motion([-1.0, 0.0, 0.0], local_descriptor={"kind": "height_scan"})

        summary = agent.summary()
        self.assertEqual(summary["fallback_events"], [])
        self.assertFalse(agent.correction_decision(10).triggered)
        self.assertFalse(agent.fallback_decision(10, is_parseable=False).triggered)


if __name__ == "__main__":
    unittest.main()
