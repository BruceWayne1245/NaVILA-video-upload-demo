import json
import math
import unittest

import numpy as np

from route_memory_agent import (
    AnchorRelocalization,
    RelativeStartProgress,
    RouteAnchor,
    RouteMemoryAgent,
    compose_pose,
    diagnostic_frame_thresholds_to_fire,
    inverse_delta,
    relative_delta,
    wrap_angle,
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

    @unittest.skip("legacy arc-length particle-filter path removed from non-oracle sequential_pair")
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

    @unittest.skip("legacy arc-length particle-filter path removed from non-oracle sequential_pair")
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

    @unittest.skip("legacy arc-length particle-filter path removed from non-oracle sequential_pair")
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

    def test_full_pose_anchor_target_vector_mirrors_anchor_translation(self):
        # 2026-07-14: target_dx/dy no longer chains anchor_dtheta_rad through
        # the anchor's recorded pose_from_start to point straight at the
        # (possibly distant) start -- that vector ignored corridor shape and
        # inherited raw ICP rotational error. It now mirrors anchor_dx/dy
        # (plain ICP translation to the nearby tracked anchor), matching
        # direct_oracle_route_anchor_progress's own convention.
        agent = RouteMemoryAgent(enabled=True, anchor_spacing_m=0.1)
        agent.update_outbound_motion([2.0, 0.0, math.pi / 2])
        agent.finalize_outbound()
        agent.update_return_motion([0.0, 0.0, math.pi / 2])

        agent.update_relocalization(relocalization=AnchorRelocalization(
            anchor_index=1,
            anchor_dx_m=0.3,
            anchor_dy_m=-0.1,
            anchor_dtheta_rad=-math.pi / 2,
            confidence=0.9,
            backend="external_full_pose",
            anchor_heading_reliable=True,
        ))

        progress = agent.progress()
        self.assertTrue(progress.anchor_heading_reliable)
        self.assertAlmostEqual(progress.target_dx_m, 0.3, places=6)
        self.assertAlmostEqual(progress.target_dy_m, -0.1, places=6)

    @unittest.skip("legacy arc-length projection superseded by sequential_pair promotion")
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

    @unittest.skip("legacy pass-anchor projection superseded by sequential_pair promotion")
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

    @unittest.skip("legacy pass-anchor projection superseded by sequential_pair promotion")
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

    @unittest.skip("return-stage odometry propagation removed from non-oracle route memory")
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

    @unittest.skip("legacy arc-length particle-filter path removed from non-oracle sequential_pair")
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

    @unittest.skip("dead-reckoning consistency gate removed from non-oracle route memory")
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

    @unittest.skip("legacy global-candidate fusion superseded by sequential_pair current/next selection")
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

    @unittest.skip("legacy odometer-based large-forward-jump gate removed")
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

    @unittest.skip("legacy odometer-based large-forward-jump gate removed")
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

    @unittest.skip("legacy odometer-based large-forward-jump gate removed")
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

    @unittest.skip("legacy VIO bridge removed from non-oracle sequential_pair selection")
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


class SequentialTargetAnchorPairTest(unittest.TestCase):
    """RouteMemoryAgent.sequential_target_anchor_pair(): the (current, next)
    accessor the sequential_pair relocalization backend reads every attempt
    (2026-07-04). These test the accessor's own bootstrap/lookup logic
    directly -- whether _sequence_match_observation correctly accepts a
    candidate and sets _target_anchor_index is pre-existing, already-tested
    machinery (see test_direct_oracle_override_bypasses_particle_filter_hint
    above), not re-verified here except for one end-to-end sanity check."""

    def _agent_with_anchors(self, count: int) -> RouteMemoryAgent:
        # RouteMemoryAgent always seeds an index-0 "start" anchor at distance
        # 0 the moment finalize_outbound() runs, on top of whichever anchors
        # anchor_spacing_m-triggered motion creates -- so `count` motion
        # calls of 1m each yields count+1 total anchors (indices 0..count).
        agent = RouteMemoryAgent(enabled=True, anchor_spacing_m=1.0)
        for _ in range(count):
            agent.update_outbound_motion([1.0, 0.0, 0.0])
        agent.finalize_outbound()
        return agent

    def test_bootstrap_before_any_relocalization_returns_last_two_anchors(self):
        agent = self._agent_with_anchors(3)
        current, nxt = agent.sequential_target_anchor_pair()
        self.assertEqual(current.index, agent.anchors[-1].index)
        self.assertEqual(nxt.index, agent.anchors[-2].index)

    def test_no_anchors_returns_none_none(self):
        """A disabled agent never seeds the index-0 start anchor (unlike an
        enabled one, which always has at least that one) -- must not crash
        on a genuinely empty anchors list."""
        agent = RouteMemoryAgent(enabled=False)
        self.assertEqual(agent.sequential_target_anchor_pair(), (None, None))

    def test_tracks_target_anchor_index_once_set(self):
        agent = self._agent_with_anchors(3)
        agent._target_anchor_index = agent.anchors[1].index
        current, nxt = agent.sequential_target_anchor_pair()
        self.assertEqual(current.index, agent.anchors[1].index)
        self.assertEqual(nxt.index, agent.anchors[0].index)

    def test_next_is_none_at_the_first_anchor(self):
        agent = self._agent_with_anchors(3)
        agent._target_anchor_index = agent.anchors[0].index
        current, nxt = agent.sequential_target_anchor_pair()
        self.assertEqual(current.index, agent.anchors[0].index)
        self.assertIsNone(nxt)

    def test_accepted_relocalization_against_next_anchor_advances_the_pair(self):
        """End-to-end sanity check: a single accepted match against the
        'next' anchor (not the bootstrap 'current' one) should be enough for
        _target_anchor_index to move to it, with no separate advance step --
        monotonic progression falls out of _sequence_match_observation's
        existing scoring plus the caller only ever offering these two
        anchors as candidates (see relocalization.sequential_pair_anchor_
        relocalization's docstring)."""
        agent = self._agent_with_anchors(2)  # anchors: index 0 @ 0m (start), 1 @ 1m, 2 @ 2m
        current, nxt = agent.sequential_target_anchor_pair()
        self.assertEqual((current.index, nxt.index), (2, 1))

        accepted = agent.update_relocalization(relocalization=AnchorRelocalization(
            anchor_index=1,
            anchor_dx_m=1.5,
            anchor_dy_m=0.5,
            anchor_dtheta_rad=0.0,
            confidence=0.9,
            backend="sequential_pair",
            inlier_count=1,
        ))

        self.assertIsNotNone(accepted, "a plausible match against the next anchor should be accepted")
        current, nxt = agent.sequential_target_anchor_pair()
        self.assertEqual(current.index, 1, "accepting a match against the 'next' anchor should advance the pair")
        self.assertEqual(nxt.index, 0)


class SequentialPairGeometrySourceTest(unittest.TestCase):
    """sequential_pair_geometry_source (2026-07-04): _reproject_delta_to_anchor
    can pull the anchor-to-anchor reference geometry from either the existing
    non-privileged edge_from_previous chain ("accumulated", default) or ground-
    truth metadata["world_pose"] ("oracle") -- an explicit ablation switch to
    isolate anchor-geometry error from ICP/odometry error, not a behavior
    change on its own."""

    def _agent_with_world_pose_anchors(self, geometry_source: str) -> RouteMemoryAgent:
        agent = RouteMemoryAgent(enabled=True, anchor_spacing_m=1.0, sequential_pair_geometry_source=geometry_source)
        for _ in range(3):
            agent.update_outbound_motion([1.0, 0.0, 0.0])
        agent.finalize_outbound()
        # Ground-truth world_pose along +x, matching the accumulated poses
        # exactly (no injected drift) so both sources should agree here.
        for anchor in agent.anchors:
            anchor.metadata["world_pose"] = [float(anchor.index), 0.0, 0.3, 1.0, 0.0, 0.0, 0.0]
        return agent

    def test_default_geometry_source_is_accumulated(self):
        agent = RouteMemoryAgent(enabled=True)
        self.assertEqual(agent.sequential_pair_geometry_source, "accumulated")

    def test_oracle_and_accumulated_agree_with_no_injected_drift(self):
        oracle_agent = self._agent_with_world_pose_anchors("oracle")
        accumulated_agent = self._agent_with_world_pose_anchors("accumulated")
        oracle_edge = oracle_agent._anchor_edge_between(2, 1)
        accumulated_edge = accumulated_agent._anchor_edge_between(2, 1)
        for actual, expected in zip(oracle_edge, accumulated_edge):
            self.assertAlmostEqual(actual, expected, places=6)

    def test_oracle_source_ignores_corrupted_accumulated_pose(self):
        """Injecting drift into the accumulated edge_from_previous chain must not
        change the oracle-sourced edge, since it is computed purely from
        metadata["world_pose"] -- this is the whole point of the ablation."""
        agent = self._agent_with_world_pose_anchors("oracle")
        agent.anchors[1].edge_from_previous = [999.0, -123.0, 2.5]
        edge = agent._anchor_edge_between(2, 1)
        self.assertAlmostEqual(edge[0], -1.0, places=6)
        self.assertAlmostEqual(edge[1], 0.0, places=6)

    def test_oracle_source_returns_none_without_world_pose_metadata(self):
        agent = RouteMemoryAgent(enabled=True, anchor_spacing_m=1.0, sequential_pair_geometry_source="oracle")
        for _ in range(2):
            agent.update_outbound_motion([1.0, 0.0, 0.0])
        agent.finalize_outbound()
        self.assertIsNone(agent._anchor_edge_between(1, 0))


class SequentialPairClosureCheckTest(unittest.TestCase):
    """sequential_pair closure check (user-proposed 2026-07-04, verified against
    real overshoot data before implementation): the independent ICP fits
    against the current and next anchor, each attempt, should agree with each
    other up to the true current-to-next anchor displacement. Off by default;
    see RouteMemoryAgent.__init__'s docstring for exactly what it catches
    (3 of 4 known single-bad-ICP-read overshoot triggers) and does not catch
    (both anchors' fits simultaneously, correlatedly wrong)."""

    def _agent_with_pair(self) -> RouteMemoryAgent:
        agent = RouteMemoryAgent(
            enabled=True, anchor_spacing_m=1.0, sequential_pair_closure_check_enabled=True,
        )
        for _ in range(2):
            agent.update_outbound_motion([1.0, 0.0, 0.0])
        agent.finalize_outbound()
        return agent  # anchors: 0 @ 0m, 1 @ 1m, 2 @ 2m (return-start)

    def test_disabled_by_default_returns_estimates_unchanged(self):
        agent = RouteMemoryAgent(enabled=True)
        good = AnchorRelocalization(anchor_index=2, anchor_dx_m=-0.05, anchor_dy_m=0.0, anchor_dtheta_rad=0.0,
                                     confidence=0.9, backend="sequential_pair", inlier_count=400)
        bad = AnchorRelocalization(anchor_index=1, anchor_dx_m=-0.05, anchor_dy_m=0.0, anchor_dtheta_rad=0.0,
                                    confidence=0.35, backend="sequential_pair", inlier_count=150)
        estimates, reason = agent._sequential_pair_closure_precheck([good, bad])
        self.assertIsNone(reason)
        self.assertIs(estimates[0], good)
        self.assertIs(estimates[1], bad)

    def test_agreeing_estimates_pass_through_unchanged(self):
        agent = self._agent_with_pair()
        current = AnchorRelocalization(anchor_index=2, anchor_dx_m=-0.05, anchor_dy_m=0.0, anchor_dtheta_rad=0.0,
                                        confidence=0.9, backend="sequential_pair", inlier_count=400)
        # anchor 1 is ~1m behind anchor 2 -- a clean, agreeing next-anchor reading.
        nxt = AnchorRelocalization(anchor_index=1, anchor_dx_m=-1.05, anchor_dy_m=0.0, anchor_dtheta_rad=0.0,
                                    confidence=0.85, backend="sequential_pair", inlier_count=380)
        estimates, reason = agent._sequential_pair_closure_precheck([current, nxt])
        self.assertIsNone(reason)
        self.assertNotIn("closure_reconstructed", estimates[0].backend)
        self.assertNotIn("closure_reconstructed", estimates[1].backend)

    def test_one_sided_disagreement_reconstructs_the_weaker_side(self):
        """Mirrors the real ep4/ep5/ep678 overshoot signature: a low-quality
        'next' reading falsely implies the robot has nearly arrived, while the
        high-quality 'current' reading is clean -- the weaker reading should be
        replaced with a value reprojected from the stronger one, not accepted
        or silently discarded."""
        agent = self._agent_with_pair()
        current = AnchorRelocalization(anchor_index=2, anchor_dx_m=-0.05, anchor_dy_m=0.0, anchor_dtheta_rad=0.0,
                                        confidence=0.90, backend="sequential_pair", inlier_count=400)
        bad_next = AnchorRelocalization(anchor_index=1, anchor_dx_m=-0.05, anchor_dy_m=0.0, anchor_dtheta_rad=0.0,
                                         confidence=0.35, backend="sequential_pair", inlier_count=150)
        estimates, reason = agent._sequential_pair_closure_precheck([current, bad_next])
        self.assertIsNone(reason)
        by_index = {e.anchor_index: e for e in estimates}
        self.assertNotIn("closure_reconstructed", by_index[2].backend)
        reconstructed = by_index[1]
        self.assertIn("closure_reconstructed", reconstructed.backend)
        self.assertAlmostEqual(reconstructed.anchor_dx_m, -1.05, places=6)
        self.assertAlmostEqual(reconstructed.anchor_dy_m, 0.0, places=6)

    def test_comparable_quality_disagreement_is_rejected(self):
        """When neither side clearly dominates, this must not guess which one
        to trust -- mirrors this project's existing 'genuinely ambiguous, no
        candidate' policy for other backends (fused/scan_context margin
        checks) rather than accepting either blindly."""
        agent = self._agent_with_pair()
        a = AnchorRelocalization(anchor_index=2, anchor_dx_m=-0.05, anchor_dy_m=0.0, anchor_dtheta_rad=0.0,
                                  confidence=0.95, backend="sequential_pair", inlier_count=400)
        b = AnchorRelocalization(anchor_index=1, anchor_dx_m=-0.05, anchor_dy_m=0.0, anchor_dtheta_rad=0.0,
                                  confidence=0.90, backend="sequential_pair", inlier_count=350)
        estimates, reason = agent._sequential_pair_closure_precheck([a, b])
        self.assertEqual(reason, "sequential_pair_closure_mismatch")

    def test_reconstruction_prevents_a_false_arrival_from_being_accepted(self):
        """End-to-end: without the closure check, a confident-looking but wrong
        'next' reading implying near-zero distance would be accepted outright
        (the real overshoot mechanism, verified this session against actual
        batch data). With it enabled, the reading is corrected before scoring,
        so the accepted estimate reflects the true ~1m remaining distance."""
        agent = self._agent_with_pair()
        current = AnchorRelocalization(anchor_index=2, anchor_dx_m=-0.05, anchor_dy_m=0.0, anchor_dtheta_rad=0.0,
                                        confidence=0.90, backend="sequential_pair", inlier_count=400)
        bad_next = AnchorRelocalization(anchor_index=1, anchor_dx_m=-0.05, anchor_dy_m=0.0, anchor_dtheta_rad=0.0,
                                         confidence=0.35, backend="sequential_pair", inlier_count=150)
        accepted = agent.update_relocalization(relocalization=[current, bad_next])
        self.assertIsNotNone(accepted)
        self.assertEqual(accepted.anchor_index, 2, "current anchor's own clean reading should win the score")
        # The corrected (reconstructed) next-anchor reading, not the raw false-
        # arrival one, should be what's now recorded as the sequence position.
        self.assertGreater(agent._sequence_current_s_m, 0.9)


class SequentialPairQuarantineTest(unittest.TestCase):
    """Bad-anchor quarantine (user-proposed 2026-07-04): an anchor whose ICP fit
    bounces beyond tolerance across consecutive attempts while still "next"
    (unpromoted) is permanently skipped. Verified against real data before
    implementation: catches anchors unstable before promotion (ep368 anchor 2,
    ep187 anchor 1); confirmed blind to an anchor whose fit only degrades at
    the instant of promotion (ep368 anchor 3) -- an accepted, out-of-scope gap
    per the user, not something these tests claim to cover."""

    def _agent(self, count: int = 4, **kwargs) -> RouteMemoryAgent:
        agent = RouteMemoryAgent(
            enabled=True, anchor_spacing_m=1.0, sequential_pair_quarantine_enabled=True,
            quarantine_min_samples=3, quarantine_heading_spread_rad=math.radians(20.0), **kwargs,
        )
        for _ in range(count):
            agent.update_outbound_motion([1.0, 0.0, 0.0])
        agent.finalize_outbound()
        agent._target_anchor_index = agent.anchors[-1].index
        return agent

    def _bouncing_readings(self, anchor_index: int, thetas_deg: list[float]) -> list[list[AnchorRelocalization]]:
        return [
            [AnchorRelocalization(
                anchor_index=anchor_index, anchor_dx_m=-1.0, anchor_dy_m=0.0,
                anchor_dtheta_rad=math.radians(theta), confidence=0.5,
                backend="sequential_pair", inlier_count=150,
            )]
            for theta in thetas_deg
        ]

    def test_disabled_by_default_next_is_never_flagged(self):
        agent = RouteMemoryAgent(enabled=True, anchor_spacing_m=1.0)
        for _ in range(4):
            agent.update_outbound_motion([1.0, 0.0, 0.0])
        agent.finalize_outbound()
        agent._target_anchor_index = agent.anchors[-1].index
        for readings in self._bouncing_readings(agent.anchors[-2].index, [0, 40, -35, 30]):
            agent._record_next_anchor_stability(readings)
        self.assertEqual(agent._quarantined_anchor_indices, set())

    def test_stable_next_anchor_is_never_flagged(self):
        agent = self._agent()
        next_index = agent.anchors[-2].index
        for readings in self._bouncing_readings(next_index, [0, 2, -1, 1, 0]):
            agent._record_next_anchor_stability(readings)
        self.assertNotIn(next_index, agent._quarantined_anchor_indices)

    def test_bouncing_next_anchor_gets_quarantined(self):
        agent = self._agent()
        next_index = agent.anchors[-2].index
        for readings in self._bouncing_readings(next_index, [0, 40, -35, 30]):
            agent._record_next_anchor_stability(readings)
        self.assertIn(next_index, agent._quarantined_anchor_indices)

    def test_quarantined_next_anchor_is_skipped_by_pair_accessor(self):
        agent = self._agent()
        current_index = agent._target_anchor_index
        next_index = current_index - 1
        for readings in self._bouncing_readings(next_index, [0, 40, -35, 30]):
            agent._record_next_anchor_stability(readings)
        current, nxt = agent.sequential_target_anchor_pair()
        self.assertEqual(current.index, current_index)
        self.assertEqual(nxt.index, next_index - 1)

    def test_quarantine_skips_multiple_consecutive_bad_anchors(self):
        agent = self._agent()
        current_index = agent._target_anchor_index
        for readings in self._bouncing_readings(current_index - 1, [0, 40, -35, 30]):
            agent._record_next_anchor_stability(readings)
        for readings in self._bouncing_readings(current_index - 2, [0, 50, -45, 60]):
            agent._record_next_anchor_stability(readings)
        current, nxt = agent.sequential_target_anchor_pair()
        self.assertEqual(current.index, current_index)
        self.assertEqual(nxt.index, current_index - 3)

    def test_current_anchor_readings_are_never_flagged(self):
        """_record_next_anchor_stability must not track the anchor already
        promoted to _target_anchor_index -- degradation after promotion is a
        separate, explicitly out-of-scope problem (see class docstring)."""
        agent = self._agent()
        current_index = agent._target_anchor_index
        for readings in self._bouncing_readings(current_index, [0, 40, -35, 30]):
            agent._record_next_anchor_stability(readings)
        self.assertNotIn(current_index, agent._quarantined_anchor_indices)


class SequentialPairBeliefClosureTest(unittest.TestCase):
    """Belief-curve closure mode (user-proposed 2026-07-05): replaces
    "threshold" mode's magic 1.5x quality ratio and fixed disagreement caps
    with a continuous, quality-weighted fusion that never rejects an attempt
    outright. Verified against real A/B batch data (2026-07-05): "threshold"
    mode's outright rejects starve _distance_since_sequence_observation_m's
    reset and can cascade into a permanent stall (5 of 7 regressed episodes in
    one batch showed a long unbroken no_sequence_candidates tail right after
    a run of sequential_pair_closure_mismatch rejects)."""

    def _agent_with_pair(self, **kwargs) -> RouteMemoryAgent:
        agent = RouteMemoryAgent(
            enabled=True, anchor_spacing_m=1.0, sequential_pair_closure_check_enabled=True, **kwargs,
        )
        for _ in range(2):
            agent.update_outbound_motion([1.0, 0.0, 0.0])
        agent.finalize_outbound()
        return agent  # anchors: 0 @ 0m, 1 @ 1m, 2 @ 2m (return-start)

    def test_default_mode_is_threshold(self):
        agent = RouteMemoryAgent(enabled=True)
        self.assertEqual(agent.sequential_pair_closure_mode, "threshold")

    def test_comparable_quality_disagreement_is_fused_not_rejected(self):
        """Same scenario as SequentialPairClosureCheckTest's
        test_comparable_quality_disagreement_is_rejected -- "threshold" mode
        rejects this outright; "belief" mode must never reject, only fuse."""
        agent = self._agent_with_pair(sequential_pair_closure_mode="belief")
        a = AnchorRelocalization(anchor_index=2, anchor_dx_m=-0.05, anchor_dy_m=0.0, anchor_dtheta_rad=0.0,
                                  confidence=0.95, backend="sequential_pair", inlier_count=400)
        b = AnchorRelocalization(anchor_index=1, anchor_dx_m=-0.05, anchor_dy_m=0.0, anchor_dtheta_rad=0.0,
                                  confidence=0.90, backend="sequential_pair", inlier_count=350)
        estimates, reason = agent._sequential_pair_closure_precheck([a, b])
        self.assertIsNone(reason)
        for estimate in estimates:
            self.assertIn("belief_fused", estimate.backend)

    def test_disagreement_discounts_confidence_but_never_to_zero(self):
        agent = self._agent_with_pair(sequential_pair_closure_mode="belief")
        a = AnchorRelocalization(anchor_index=2, anchor_dx_m=-0.05, anchor_dy_m=0.0, anchor_dtheta_rad=0.0,
                                  confidence=0.95, backend="sequential_pair", inlier_count=400)
        b = AnchorRelocalization(anchor_index=1, anchor_dx_m=-0.05, anchor_dy_m=0.0, anchor_dtheta_rad=0.0,
                                  confidence=0.90, backend="sequential_pair", inlier_count=350)
        estimates, reason = agent._sequential_pair_closure_precheck([a, b])
        self.assertIsNone(reason)
        fused_confidence = estimates[0].confidence
        self.assertLess(fused_confidence, min(a.confidence, b.confidence))
        self.assertGreater(fused_confidence, 0.0)

    def test_fusion_weights_toward_the_higher_quality_side(self):
        """Mirrors the real ep4/ep5/ep678 overshoot signature (a low-quality
        'next' reading falsely implying near-arrival while 'current' is
        clean) but checks the continuous weighting instead of a hard
        reconstruct: the fused estimate should land close to the high-quality
        side's own reading, weighted by quality * sqrt(inlier_count)."""
        agent = self._agent_with_pair(sequential_pair_closure_mode="belief")
        a = AnchorRelocalization(anchor_index=2, anchor_dx_m=-0.05, anchor_dy_m=0.0, anchor_dtheta_rad=0.0,
                                  confidence=0.90, backend="sequential_pair", inlier_count=400)
        bad_next = AnchorRelocalization(anchor_index=1, anchor_dx_m=-0.05, anchor_dy_m=0.0, anchor_dtheta_rad=0.0,
                                         confidence=0.35, backend="sequential_pair", inlier_count=150)
        estimates, reason = agent._sequential_pair_closure_precheck([a, bad_next])
        self.assertIsNone(reason)
        by_index = {e.anchor_index: e for e in estimates}
        quality_a = 0.90 * math.sqrt(400)
        quality_b = 0.35 * math.sqrt(150)
        weight_a = quality_a / (quality_a + quality_b)
        # Reprojecting bad_next's raw (-0.05, 0, 0) from anchor 1 into anchor 2's
        # frame (1m apart) yields dx=0.95 -- the fused anchor-2-frame dx should
        # sit at weight_a*(-0.05) + (1-weight_a)*0.95.
        expected_dx = weight_a * (-0.05) + (1.0 - weight_a) * 0.95
        self.assertAlmostEqual(by_index[2].anchor_dx_m, expected_dx, places=4)
        # The high-quality side dominates heavily (~0.81 weight) so the fused
        # result should sit much closer to a's own reading than to a naive average.
        self.assertLess(abs(by_index[2].anchor_dx_m - a.anchor_dx_m), abs(by_index[2].anchor_dx_m - 0.95))

    def test_never_rejects_regardless_of_disagreement_magnitude(self):
        agent = self._agent_with_pair(sequential_pair_closure_mode="belief")
        for dy in (0.5, 2.0, 5.0, 10.0):
            a = AnchorRelocalization(anchor_index=2, anchor_dx_m=-0.05, anchor_dy_m=0.0, anchor_dtheta_rad=0.0,
                                      confidence=0.8, backend="sequential_pair", inlier_count=300)
            b = AnchorRelocalization(anchor_index=1, anchor_dx_m=-1.05, anchor_dy_m=dy, anchor_dtheta_rad=0.0,
                                      confidence=0.8, backend="sequential_pair", inlier_count=300)
            _estimates, reason = agent._sequential_pair_closure_precheck([a, b])
            self.assertIsNone(reason, f"belief mode rejected outright at dy={dy}")

    def test_belief_mode_avoids_a_stall_that_threshold_mode_would_hit(self):
        """End-to-end: the same comparable-quality disagreement that
        "threshold" mode's test_comparable_quality_disagreement_is_rejected
        turns into an outright reject (no accepted estimate this attempt, no
        _distance_since_sequence_observation_m reset) still yields an accepted
        estimate under "belief" mode."""
        agent = self._agent_with_pair(sequential_pair_closure_mode="belief")
        a = AnchorRelocalization(anchor_index=2, anchor_dx_m=-0.05, anchor_dy_m=0.0, anchor_dtheta_rad=0.0,
                                  confidence=0.95, backend="sequential_pair", inlier_count=400)
        b = AnchorRelocalization(anchor_index=1, anchor_dx_m=-0.05, anchor_dy_m=0.0, anchor_dtheta_rad=0.0,
                                  confidence=0.90, backend="sequential_pair", inlier_count=350)
        accepted = agent.update_relocalization(relocalization=[a, b])
        self.assertIsNotNone(accepted)


class SequentialPairBeliefTrustAwareGuardTest(unittest.TestCase):
    """Trust-aware guard (2026-07-07, ICP bearing-error investigation
    follow-on): belief mode's circular_weighted_mean blend is numerically
    unstable when current/next disagree by a large (near-antipodal) amount --
    confirmed on real data (ep187 anchor14) that blending in a bimodal/
    unstable partner reading can swing the fused bearing by 100+ degrees even
    while the partner holds a minority fusion weight, corrupting an anchor
    whose own raw ICP was accurate (~4 deg mean error) the whole time. When
    the disagreement is large and exactly one side's own match_class/
    near_tie_basin_count says it is trustworthy, this guard reconstructs the
    other side from it via the known anchor-to-anchor edge geometry instead
    of blending."""

    def _agent_with_pair(self, **kwargs) -> RouteMemoryAgent:
        agent = RouteMemoryAgent(
            enabled=True, anchor_spacing_m=1.0, sequential_pair_closure_check_enabled=True,
            sequential_pair_closure_mode="belief", **kwargs,
        )
        for _ in range(2):
            agent.update_outbound_motion([1.0, 0.0, 0.0])
        agent.finalize_outbound()
        return agent  # anchors: 0 @ 0m, 1 @ 1m, 2 @ 2m (return-start)

    def test_default_guard_is_off(self):
        agent = RouteMemoryAgent(enabled=True, sequential_pair_closure_check_enabled=True,
                                  sequential_pair_closure_mode="belief")
        self.assertFalse(agent.sequential_pair_closure_belief_trust_aware_guard)

    def test_large_heading_disagreement_reconstructs_untrustworthy_side(self):
        """Mirrors the real ep187 anchor13/14 signature: current (anchor 2)
        is clean and accurate; next (anchor 1) disagrees by ~150 deg and is
        flagged degenerate. The guard should keep anchor 2's own reading
        byte-for-byte unchanged and reconstruct anchor 1 purely from anchor
        2's reading + the known 1m edge -- never averaging the two."""
        agent = self._agent_with_pair(sequential_pair_closure_belief_trust_aware_guard=True)
        current = AnchorRelocalization(
            anchor_index=2, anchor_dx_m=-0.05, anchor_dy_m=0.0, anchor_dtheta_rad=0.0,
            confidence=1.0, backend="sequential_pair", inlier_count=450,
            match_class="clean_full_pose", near_tie_basin_count=0,
        )
        bad_next = AnchorRelocalization(
            anchor_index=1, anchor_dx_m=-0.05, anchor_dy_m=0.0, anchor_dtheta_rad=math.radians(150.0),
            confidence=0.55, backend="sequential_pair", inlier_count=300,
            match_class="partial_pose_degenerate", near_tie_basin_count=0,
        )
        estimates, reason = agent._sequential_pair_closure_precheck([current, bad_next])
        self.assertIsNone(reason)
        by_index = {e.anchor_index: e for e in estimates}
        # The trustworthy side (anchor 2) is kept byte-for-byte unchanged --
        # not even its backend tag is touched.
        self.assertEqual(by_index[2].anchor_dx_m, current.anchor_dx_m)
        self.assertEqual(by_index[2].anchor_dy_m, current.anchor_dy_m)
        self.assertEqual(by_index[2].anchor_dtheta_rad, current.anchor_dtheta_rad)
        self.assertEqual(by_index[2].backend, "sequential_pair")
        self.assertIn("belief_trust_aware_reconstructed", by_index[1].backend)
        # Reconstructed anchor-1 reading should agree with anchor 2's own
        # reading reprojected through the known edge, not some blend of the
        # two disagreeing thetas.
        self.assertAlmostEqual(by_index[1].anchor_dtheta_rad, current.anchor_dtheta_rad, places=4)

    def test_large_disagreement_both_trustworthy_falls_back_to_blend(self):
        agent = self._agent_with_pair(sequential_pair_closure_belief_trust_aware_guard=True)
        a = AnchorRelocalization(anchor_index=2, anchor_dx_m=-0.05, anchor_dy_m=0.0, anchor_dtheta_rad=0.0,
                                  confidence=0.95, backend="sequential_pair", inlier_count=400,
                                  match_class="clean_full_pose", near_tie_basin_count=0)
        b = AnchorRelocalization(anchor_index=1, anchor_dx_m=-0.05, anchor_dy_m=0.0,
                                  anchor_dtheta_rad=math.radians(150.0),
                                  confidence=0.90, backend="sequential_pair", inlier_count=350,
                                  match_class="clean_full_pose", near_tie_basin_count=0)
        estimates, reason = agent._sequential_pair_closure_precheck([a, b])
        self.assertIsNone(reason)
        for estimate in estimates:
            self.assertIn("belief_fused", estimate.backend)

    def test_large_disagreement_neither_trustworthy_falls_back_to_blend(self):
        agent = self._agent_with_pair(sequential_pair_closure_belief_trust_aware_guard=True)
        a = AnchorRelocalization(anchor_index=2, anchor_dx_m=-0.05, anchor_dy_m=0.0, anchor_dtheta_rad=0.0,
                                  confidence=0.6, backend="sequential_pair", inlier_count=300,
                                  match_class="ambiguous_high_confidence", near_tie_basin_count=1)
        b = AnchorRelocalization(anchor_index=1, anchor_dx_m=-0.05, anchor_dy_m=0.0,
                                  anchor_dtheta_rad=math.radians(150.0),
                                  confidence=0.55, backend="sequential_pair", inlier_count=280,
                                  match_class="partial_pose_degenerate", near_tie_basin_count=0)
        estimates, reason = agent._sequential_pair_closure_precheck([a, b])
        self.assertIsNone(reason)
        for estimate in estimates:
            self.assertIn("belief_fused", estimate.backend)

    def test_small_disagreement_ignores_match_class_uses_normal_blend(self):
        """The guard only applies once disagreement crosses the "large"
        threshold -- a noise-level disagreement should behave exactly like
        plain belief mode even if match_class would otherwise flag one side,
        since averaging is still meaningful at this scale."""
        agent = self._agent_with_pair(sequential_pair_closure_belief_trust_aware_guard=True)
        a = AnchorRelocalization(anchor_index=2, anchor_dx_m=-0.05, anchor_dy_m=0.0, anchor_dtheta_rad=0.0,
                                  confidence=0.95, backend="sequential_pair", inlier_count=400,
                                  match_class="clean_full_pose", near_tie_basin_count=0)
        b = AnchorRelocalization(anchor_index=1, anchor_dx_m=-0.15, anchor_dy_m=0.0, anchor_dtheta_rad=0.0,
                                  confidence=0.5, backend="sequential_pair", inlier_count=200,
                                  match_class="partial_pose_degenerate", near_tie_basin_count=0)
        estimates, reason = agent._sequential_pair_closure_precheck([a, b])
        self.assertIsNone(reason)
        for estimate in estimates:
            self.assertIn("belief_fused", estimate.backend)

    def test_guard_off_behaves_like_plain_belief_mode_even_for_large_disagreement(self):
        agent = self._agent_with_pair()  # guard defaults off
        current = AnchorRelocalization(anchor_index=2, anchor_dx_m=-0.05, anchor_dy_m=0.0, anchor_dtheta_rad=0.0,
                                        confidence=1.0, backend="sequential_pair", inlier_count=450,
                                        match_class="clean_full_pose", near_tie_basin_count=0)
        bad_next = AnchorRelocalization(anchor_index=1, anchor_dx_m=-0.05, anchor_dy_m=0.0,
                                         anchor_dtheta_rad=math.radians(150.0),
                                         confidence=0.55, backend="sequential_pair", inlier_count=300,
                                         match_class="partial_pose_degenerate", near_tie_basin_count=0)
        estimates, reason = agent._sequential_pair_closure_precheck([current, bad_next])
        self.assertIsNone(reason)
        for estimate in estimates:
            self.assertIn("belief_fused", estimate.backend)


class SequentialPairQuarantineTrendTest(unittest.TestCase):
    """Trend-aware quarantine (user-proposed 2026-07-05): replaces the
    "window" mode's small (3-6 sample) fixed-window spread check with a
    dwell-time-long majority-bad-fit + no-improvement-trend criterion.
    Verified against real A/B batch data (2026-07-05): of 8 anchors "window"
    mode quarantined across the episodes checked, only anchors tied to one
    already-confirmed permanent-lock episode had independent baseline/off
    evidence of real difficulty -- the rest were anchors an independent run
    showed were perfectly fine (100% accept, <0.15m error), i.e. mostly false
    positives from a single unlucky reading inside a small window."""

    def _agent(self, **kwargs) -> RouteMemoryAgent:
        agent = RouteMemoryAgent(
            enabled=True, anchor_spacing_m=1.0, sequential_pair_quarantine_enabled=True,
            sequential_pair_quarantine_mode="trend", quarantine_trend_min_history=6, **kwargs,
        )
        for _ in range(2):
            agent.update_outbound_motion([1.0, 0.0, 0.0])
        agent.finalize_outbound()
        agent._target_anchor_index = agent.anchors[-1].index  # anchor 2 ("current")
        return agent  # "next" is anchor 1, 1m away

    def _current_reading(self) -> AnchorRelocalization:
        return AnchorRelocalization(anchor_index=2, anchor_dx_m=-0.05, anchor_dy_m=0.0, anchor_dtheta_rad=0.0,
                                     confidence=0.9, backend="sequential_pair", inlier_count=400)

    def _next_reading(self, dx: float, dy: float) -> AnchorRelocalization:
        return AnchorRelocalization(anchor_index=1, anchor_dx_m=dx, anchor_dy_m=dy, anchor_dtheta_rad=0.0,
                                     confidence=0.6, backend="sequential_pair", inlier_count=200)

    def test_default_mode_is_window(self):
        agent = RouteMemoryAgent(enabled=True, sequential_pair_quarantine_enabled=True)
        self.assertEqual(agent.sequential_pair_quarantine_mode, "window")

    def test_single_bad_reading_among_good_ones_does_not_quarantine(self):
        """The one case "window" mode structurally cannot distinguish from
        genuine instability -- a single unlucky read inside a min-3-sample
        window. Trend mode's whole-dwell-time majority requirement should
        absorb it."""
        agent = self._agent()
        current = self._current_reading()
        # Consistent readings agree with current's -0.05 via the known 1m
        # anchor-to-anchor edge (dx roughly -1.05); one reading is a wild
        # outlier (dx=0.5, dy=1.6).
        sequence = [(-1.05, 0.0), (-0.95, 0.0), (-1.10, 0.0), (0.5, 1.6), (-0.85, 0.0), (-0.75, 0.0), (-0.65, 0.0)]
        for dx, dy in sequence:
            agent._record_next_anchor_stability([current, self._next_reading(dx, dy)])
        self.assertNotIn(1, agent._quarantined_anchor_indices)

    def test_persistently_disagreeing_anchor_gets_quarantined(self):
        agent = self._agent()
        current = self._current_reading()
        for _ in range(6):
            agent._record_next_anchor_stability([current, self._next_reading(-1.05, 4.0)])
        self.assertIn(1, agent._quarantined_anchor_indices)

    def test_improving_anchor_is_not_quarantined_despite_majority_bad_early(self):
        """Even when more than half the whole-dwell history disagrees, an
        anchor that clearly improves as the robot's own ICP-measured distance
        to it shrinks must not be quarantined -- the one invariant this
        project can rely on is that the robot only ever draws closer to
        "next", so a genuinely fine anchor has no reason to still look bad
        once it's close."""
        agent = self._agent()
        current = self._current_reading()
        sequence = [(-1.05, 4.0)] * 4 + [(-1.05, 0.0)] * 3
        for dx, dy in sequence:
            agent._record_next_anchor_stability([current, self._next_reading(dx, dy)])
        self.assertNotIn(1, agent._quarantined_anchor_indices)

    def test_current_anchor_readings_are_never_flagged(self):
        agent = self._agent()
        current = self._current_reading()
        for _ in range(6):
            agent._record_next_anchor_stability([current, self._next_reading(-1.05, 4.0)])
        self.assertNotIn(2, agent._quarantined_anchor_indices)


class SequentialPairNextIndexQuarantineSkipTest(unittest.TestCase):
    """Regression test for a real bug found 2026-07-06 while debugging why
    bounded_evidence + alias-aware promotion could freeze permanently on some
    episodes (ep5 of the hard-11 set): _select_sequential_pair_relocalization
    used to independently recompute next_idx = current_idx - 1, ignoring
    quarantine's skip-ahead logic that sequential_target_anchor_pair() (the
    thing that actually offers a candidate to the live ICP call) already
    applies. Whenever quarantine skipped past more than the immediate
    neighbor, the live call correctly matched against the real next
    candidate, but _select_sequential_pair_relocalization went looking for a
    different (skipped-over, never-computed) anchor's estimate -- always
    None -- so promotion could never be recorded again for the rest of the
    episode. This bug predates bounded_evidence entirely (quarantine shipped
    2026-07-04); it went unnoticed because "immediate" mode promotes within a
    few attempts, rarely giving quarantine's trend tracker enough dwell time
    to fire mid-promotion in the first place."""

    def _agent(self, **kwargs) -> RouteMemoryAgent:
        return RouteMemoryAgent(
            enabled=True, anchor_spacing_m=1.0,
            sequential_pair_promotion_mode="bounded_evidence",
            sequential_pair_promotion_window=5, sequential_pair_promotion_min_votes=3,
            sequential_pair_quarantine_enabled=True,
            **kwargs,
        )

    def test_next_idx_matches_the_anchor_quarantine_actually_offers(self):
        agent = self._agent()
        agent.anchors = [
            RouteAnchor(index=3, pose_from_start=[0, 0, 0], distance_from_start_m=3.0),
            RouteAnchor(index=2, pose_from_start=[0, 0, 0], distance_from_start_m=2.0),
            RouteAnchor(index=1, pose_from_start=[0, 0, 0], distance_from_start_m=1.0),
            RouteAnchor(index=0, pose_from_start=[0, 0, 0], distance_from_start_m=0.0),
        ]
        agent._target_anchor_index = 3
        agent._return_started = True
        # anchor 2 (the immediate neighbor) is quarantined -- sequential_target_anchor_pair()
        # must skip straight to anchor 1.
        agent._quarantined_anchor_indices.add(2)
        current, next_anchor = agent.sequential_target_anchor_pair()
        self.assertEqual(current.index, 3)
        self.assertEqual(next_anchor.index, 1)

    def test_promotion_still_commits_when_quarantine_skips_the_immediate_neighbor(self):
        """End-to-end: with anchor2 quarantined, an estimate keyed to anchor1
        (the real, quarantine-skipped candidate) must still be found and
        voted on by _select_sequential_pair_relocalization -- before the fix,
        it looked for anchor2's estimate (never offered, always missing) and
        could never promote again for the rest of the episode."""
        agent = self._agent()
        agent.anchors = [
            RouteAnchor(index=3, pose_from_start=[0, 0, 0], distance_from_start_m=3.0),
            RouteAnchor(index=2, pose_from_start=[0, 0, 0], distance_from_start_m=2.0),
            RouteAnchor(index=1, pose_from_start=[0, 0, 0], distance_from_start_m=1.0),
            RouteAnchor(index=0, pose_from_start=[0, 0, 0], distance_from_start_m=0.0),
        ]
        agent._target_anchor_index = 3
        agent._return_started = True
        agent._quarantined_anchor_indices.add(2)
        current = AnchorRelocalization(anchor_index=3, anchor_dx_m=-1.5, anchor_dy_m=0.0,
                                        confidence=0.5, backend="sequential_pair", inlier_count=100)
        close_next = AnchorRelocalization(anchor_index=1, anchor_dx_m=-0.05, anchor_dy_m=0.0,
                                           confidence=0.95, backend="sequential_pair", inlier_count=450)
        for _ in range(3):
            agent.update_relocalization(relocalization=[current, close_next])
        self.assertEqual(agent._target_anchor_index, 1,
                          "must promote directly to the quarantine-skipped candidate (anchor1), "
                          "not stay stuck looking for anchor2's estimate")


class SequentialPairNextQualityQuarantineTest(unittest.TestCase):
    """Quality-based "next"-role quarantine (2026-07-15, opt-in, off by
    default) -- see investigations/2026-07-15-50ep-batch-current-next-
    simultaneous-failure/FINDINGS.md. Unlike the "window"/"trend" quarantine
    modes above (both judge "next" only relative to the simultaneously-read
    "current" anchor), this uses each attempt's own
    best_to_second_score_ratio (single-attempt ICP ambiguity, independent of
    any other anchor) -- targeting the case this session found the existing
    modes structurally cannot: current and next both degraded together."""

    def _agent(self, **kwargs) -> RouteMemoryAgent:
        agent = RouteMemoryAgent(
            enabled=True, anchor_spacing_m=1.0,
            quarantine_next_quality_enabled=True,
            quarantine_next_quality_threshold=0.75,
            quarantine_next_quality_min_samples=5,
            **kwargs,
        )
        agent.anchors = [
            RouteAnchor(index=2, pose_from_start=[0, 0, 0], distance_from_start_m=2.0),
            RouteAnchor(index=1, pose_from_start=[0, 0, 0], distance_from_start_m=1.0),
            RouteAnchor(index=0, pose_from_start=[0, 0, 0], distance_from_start_m=0.0),
        ]
        agent._target_anchor_index = 2  # "next" is anchor 1
        agent._return_started = True
        return agent

    def _next_reading(self, ratio: float) -> AnchorRelocalization:
        return AnchorRelocalization(anchor_index=1, anchor_dx_m=-0.5, anchor_dy_m=0.0,
                                     confidence=0.9, backend="sequential_pair", inlier_count=300,
                                     best_to_second_score_ratio=ratio)

    def test_default_off_never_quarantines(self):
        agent = self._agent()
        agent.quarantine_next_quality_enabled = False
        for _ in range(10):
            agent._record_next_anchor_quality([self._next_reading(0.95)])
        self.assertNotIn(1, agent._quarantined_anchor_indices)

    def test_persistently_ambiguous_next_gets_quarantined(self):
        agent = self._agent()
        for _ in range(5):
            agent._record_next_anchor_quality([self._next_reading(0.9)])
        self.assertIn(1, agent._quarantined_anchor_indices)

    def test_clearly_unambiguous_next_is_not_quarantined(self):
        agent = self._agent()
        for _ in range(10):
            agent._record_next_anchor_quality([self._next_reading(0.3)])
        self.assertNotIn(1, agent._quarantined_anchor_indices)

    def test_below_min_samples_does_not_quarantine_yet(self):
        agent = self._agent()
        for _ in range(4):
            agent._record_next_anchor_quality([self._next_reading(0.99)])
        self.assertNotIn(1, agent._quarantined_anchor_indices)

    def test_current_anchor_readings_are_never_flagged(self):
        agent = self._agent()
        for _ in range(10):
            reading = AnchorRelocalization(anchor_index=2, anchor_dx_m=-0.05, anchor_dy_m=0.0,
                                            confidence=0.9, backend="sequential_pair", inlier_count=300,
                                            best_to_second_score_ratio=0.99)
            agent._record_next_anchor_quality([reading])
        self.assertNotIn(2, agent._quarantined_anchor_indices)

    def test_missing_ratio_is_never_treated_as_a_bad_vote(self):
        """A candidate whose backend/estimate never populates
        best_to_second_score_ratio (e.g. only one ICP basin found -- no
        second hypothesis to compare against) must not be quarantined from
        missing data alone."""
        agent = self._agent()
        reading = AnchorRelocalization(anchor_index=1, anchor_dx_m=-0.5, anchor_dy_m=0.0,
                                        confidence=0.9, backend="sequential_pair", inlier_count=300,
                                        best_to_second_score_ratio=None)
        for _ in range(10):
            agent._record_next_anchor_quality([reading])
        self.assertNotIn(1, agent._quarantined_anchor_indices)

    def test_skip_ahead_engages_even_when_original_quarantine_flag_is_off(self):
        """_next_candidate_index must skip a quality-quarantined anchor even
        if --sequential_pair_quarantine itself was never enabled -- the two
        mechanisms populate the same _quarantined_anchor_indices set but are
        independently switched."""
        agent = self._agent()
        self.assertFalse(agent.sequential_pair_quarantine_enabled)
        agent._quarantined_anchor_indices.add(1)
        self.assertEqual(agent._next_candidate_index(2), 0)


class SequentialPairCurrentConfidenceAmbiguityGateTest(unittest.TestCase):
    """Current-role confidence-ambiguity gate (2026-07-16, opt-in, off by
    default) -- see investigations/2026-07-16-.../CODE_CHANGE_current_
    confidence_gate.md. Deliberately NOT a quarantine: no persistent
    per-anchor state, nothing banned, nothing to cascade. Reuses the same
    best_to_second_score_ratio signal as quarantine_next_quality_enabled, but
    only ever caps the *reported* relocalization_confidence for the single
    current-role estimate of the attempt it's computed on -- letting the
    already-existing hint_action_arbiter/stop_gate confidence gates defer to
    the VLM instead of acting on a possibly-wrong hint. The very next attempt
    is judged completely fresh."""

    def _agent(self, **kwargs) -> RouteMemoryAgent:
        agent = RouteMemoryAgent(
            enabled=True, anchor_spacing_m=1.0,
            current_confidence_ambiguity_gate_enabled=True,
            current_confidence_ambiguity_gate_threshold=0.75,
            current_confidence_ambiguity_gate_floor=0.5,
            **kwargs,
        )
        agent.anchors = [
            RouteAnchor(index=1, pose_from_start=[0, 0, 0], distance_from_start_m=1.0,
                        route_remaining_to_start_m=1.0),
            RouteAnchor(index=0, pose_from_start=[0, 0, 0], distance_from_start_m=0.0,
                        route_remaining_to_start_m=0.0),
        ]
        agent._target_anchor_index = 1
        agent._return_started = True
        return agent

    def _current_reading(self, ratio) -> AnchorRelocalization:
        return AnchorRelocalization(anchor_index=1, anchor_dx_m=-0.5, anchor_dy_m=0.0,
                                     confidence=0.98, backend="sequential_pair", inlier_count=300,
                                     best_to_second_score_ratio=ratio)

    def test_default_off_preserves_original_confidence(self):
        agent = self._agent()
        agent.current_confidence_ambiguity_gate_enabled = False
        reading = self._current_reading(0.95)
        self.assertEqual(agent._current_reported_confidence(reading), 0.98)

    def test_ambiguous_reading_is_capped_at_floor(self):
        agent = self._agent()
        reading = self._current_reading(0.9)
        self.assertEqual(agent._current_reported_confidence(reading), 0.5)

    def test_unambiguous_reading_is_unaffected(self):
        agent = self._agent()
        reading = self._current_reading(0.3)
        self.assertEqual(agent._current_reported_confidence(reading), 0.98)

    def test_ratio_exactly_at_threshold_is_gated(self):
        agent = self._agent()
        reading = self._current_reading(0.75)
        self.assertEqual(agent._current_reported_confidence(reading), 0.5)

    def test_missing_ratio_is_never_treated_as_ambiguous(self):
        agent = self._agent()
        reading = self._current_reading(None)
        self.assertEqual(agent._current_reported_confidence(reading), 0.98)

    def test_floor_never_raises_an_already_lower_confidence(self):
        """If the raw estimate confidence is already below the floor, the
        gate must not raise it back up -- min(), not a hard overwrite."""
        agent = self._agent()
        reading = AnchorRelocalization(anchor_index=1, anchor_dx_m=-0.5, anchor_dy_m=0.0,
                                        confidence=0.2, backend="sequential_pair", inlier_count=300,
                                        best_to_second_score_ratio=0.9)
        self.assertEqual(agent._current_reported_confidence(reading), 0.2)

    def test_gate_does_not_mutate_the_underlying_estimate(self):
        """The raw estimate.confidence used elsewhere (promotion voting,
        closure-check quality comparisons, quarantine) must stay untouched --
        only the value reported downstream is affected."""
        agent = self._agent()
        reading = self._current_reading(0.9)
        agent._current_reported_confidence(reading)
        self.assertEqual(reading.confidence, 0.98)

    def test_stateless_across_attempts(self):
        """Unlike quarantine_next_quality, nothing here should be remembered
        between calls -- an ambiguous attempt followed by a clean one must
        report full confidence again immediately, with no history/cooldown."""
        agent = self._agent()
        self.assertEqual(agent._current_reported_confidence(self._current_reading(0.9)), 0.5)
        self.assertEqual(agent._current_reported_confidence(self._current_reading(0.1)), 0.98)
        self.assertEqual(agent._current_reported_confidence(self._current_reading(0.9)), 0.5)

    def test_end_to_end_progress_reports_gated_confidence_and_wider_std(self):
        agent = self._agent()
        clean = agent._anchor_progress_from_estimate(self._current_reading(0.1))
        ambiguous = agent._anchor_progress_from_estimate(self._current_reading(0.9))
        self.assertAlmostEqual(clean.relocalization_confidence, 0.98)
        self.assertAlmostEqual(ambiguous.relocalization_confidence, 0.5)
        self.assertGreater(ambiguous.filter_std_m, clean.filter_std_m,
                            "an ambiguous reading's reported uncertainty must widen, not just its confidence")

    def test_default_off_end_to_end_is_byte_for_byte_unchanged(self):
        agent = self._agent()
        agent.current_confidence_ambiguity_gate_enabled = False
        progress = agent._anchor_progress_from_estimate(self._current_reading(0.99))
        self.assertAlmostEqual(progress.relocalization_confidence, 0.98)


class SequentialPairPromotionModeTest(unittest.TestCase):
    """Bounded-evidence promotion gate (user-proposed 2026-07-06). Forensic
    replay of real hard-11 data (investigations/2026-07-06-anchor-selection-
    and-icp-aliasing) found the original "immediate" design -- promote the
    instant one attempt's next-anchor reading is close_enough or its distance
    trend looks improving -- lets a chain of single-step promotions race
    through many anchors within a short attempt window whenever local
    structure repeats along the route: every one of those promotions is a
    high-overlap, low-residual, many-inlier ICP fit (i.e. "confidently
    wrong", not low-confidence noise), so quality_ok alone never blocks it.
    "bounded_evidence" mode requires that same per-attempt test to keep
    passing across sequential_pair_promotion_min_votes of the last
    sequential_pair_promotion_window attempts against one candidate anchor
    before the promotion commits."""

    def _agent_with_pair(self, **kwargs) -> RouteMemoryAgent:
        agent = RouteMemoryAgent(enabled=True, anchor_spacing_m=1.0, **kwargs)
        for _ in range(2):
            agent.update_outbound_motion([1.0, 0.0, 0.0])
        agent.finalize_outbound()
        return agent  # anchors: 0 @ 0m, 1 @ 1m, 2 @ 2m (return-start); current starts at 2

    def _current_reading(self) -> AnchorRelocalization:
        # Deliberately mediocre so quality_ok (next_quality >= 0.85 * current_quality)
        # is trivially satisfied by the close, high-quality "next" reading below --
        # isolates the promotion-gate behavior from the quality_ok comparison.
        return AnchorRelocalization(anchor_index=2, anchor_dx_m=-1.5, anchor_dy_m=0.0, anchor_dtheta_rad=0.0,
                                     confidence=0.5, backend="sequential_pair", inlier_count=100)

    def _close_next_reading(self) -> AnchorRelocalization:
        # distance_to_anchor_m = 0.05 <= promotion_close_radius_m (0.75) -> close_enough=True every time.
        return AnchorRelocalization(anchor_index=1, anchor_dx_m=-0.05, anchor_dy_m=0.0, anchor_dtheta_rad=0.0,
                                     confidence=0.95, backend="sequential_pair", inlier_count=450)

    def test_default_mode_is_immediate(self):
        agent = RouteMemoryAgent(enabled=True)
        self.assertEqual(agent.sequential_pair_promotion_mode, "immediate")

    def test_immediate_mode_promotes_on_the_first_qualifying_attempt(self):
        agent = self._agent_with_pair(sequential_pair_promotion_mode="immediate")
        agent.update_relocalization(relocalization=[self._current_reading(), self._close_next_reading()])
        self.assertEqual(agent._target_anchor_index, 1)

    def test_bounded_evidence_withholds_promotion_until_min_votes_reached(self):
        agent = self._agent_with_pair(
            sequential_pair_promotion_mode="bounded_evidence",
            sequential_pair_promotion_window=5,
            sequential_pair_promotion_min_votes=3,
        )
        for _ in range(2):
            agent.update_relocalization(relocalization=[self._current_reading(), self._close_next_reading()])
            self.assertEqual(agent._target_anchor_index, 2, "must not promote before 3 qualifying votes")
        agent.update_relocalization(relocalization=[self._current_reading(), self._close_next_reading()])
        self.assertEqual(agent._target_anchor_index, 1, "must promote on the 3rd qualifying vote")

    def test_bounded_evidence_counts_non_consecutive_votes_within_the_window(self):
        """K-of-W, not "K in a row": one non-qualifying attempt in between
        (next reported far away this one attempt) must not reset progress
        toward the 3-vote threshold, only bounded_evidence's fixed window
        should matter."""
        agent = self._agent_with_pair(
            sequential_pair_promotion_mode="bounded_evidence",
            sequential_pair_promotion_window=5,
            sequential_pair_promotion_min_votes=3,
        )
        far_next = AnchorRelocalization(anchor_index=1, anchor_dx_m=-3.0, anchor_dy_m=0.0, anchor_dtheta_rad=0.0,
                                         confidence=0.95, backend="sequential_pair", inlier_count=450)
        votes = [True, False, True, True]  # 3 qualifying votes by the 4th attempt
        for qualifies in votes[:-1]:
            reading = self._close_next_reading() if qualifies else far_next
            agent.update_relocalization(relocalization=[self._current_reading(), reading])
            self.assertEqual(agent._target_anchor_index, 2)
        agent.update_relocalization(relocalization=[self._current_reading(), self._close_next_reading()])
        self.assertEqual(agent._target_anchor_index, 1)

    def test_promotion_clears_vote_history_so_the_next_anchor_starts_fresh(self):
        """The vote window must not carry over past a promotion (unlike the
        deleted unbounded odometry gates) -- once anchor 1 is promoted, anchor
        0 (the new "next") needs its own sequential_pair_promotion_min_votes
        qualifying attempts, even though anchor 1 already accumulated some."""
        agent = self._agent_with_pair(
            sequential_pair_promotion_mode="bounded_evidence",
            sequential_pair_promotion_window=5,
            sequential_pair_promotion_min_votes=3,
        )
        close_to_1 = self._close_next_reading()
        for _ in range(3):
            agent.update_relocalization(relocalization=[self._current_reading(), close_to_1])
        self.assertEqual(agent._target_anchor_index, 1)
        current_at_1 = AnchorRelocalization(anchor_index=1, anchor_dx_m=-1.5, anchor_dy_m=0.0, anchor_dtheta_rad=0.0,
                                             confidence=0.5, backend="sequential_pair", inlier_count=100)
        close_to_0 = AnchorRelocalization(anchor_index=0, anchor_dx_m=-0.05, anchor_dy_m=0.0, anchor_dtheta_rad=0.0,
                                           confidence=0.95, backend="sequential_pair", inlier_count=450)
        agent.update_relocalization(relocalization=[current_at_1, close_to_0])
        self.assertEqual(agent._target_anchor_index, 1, "one qualifying attempt against anchor 0 must not promote")

    def test_bounded_evidence_slows_a_racing_chain_the_way_immediate_mode_does_not(self):
        """Narrative regression mirroring the real ep187 signature: with
        "immediate" mode, a candidate anchor that reads close_enough on every
        single attempt promotes once per attempt, racing straight through
        both anchors in 2 update_relocalization calls. "bounded_evidence"
        (min_votes=3) must take at least 3 attempts per anchor, i.e. at least
        6 calls to reach anchor 0."""
        immediate_agent = self._agent_with_pair(sequential_pair_promotion_mode="immediate")
        for _ in range(2):
            immediate_agent.update_relocalization(
                relocalization=[
                    AnchorRelocalization(anchor_index=immediate_agent._target_anchor_index, anchor_dx_m=-1.5,
                                         anchor_dy_m=0.0, confidence=0.5, backend="sequential_pair", inlier_count=100),
                    AnchorRelocalization(anchor_index=immediate_agent._target_anchor_index - 1, anchor_dx_m=-0.05,
                                         anchor_dy_m=0.0, confidence=0.95, backend="sequential_pair", inlier_count=450),
                ]
            )
        self.assertEqual(immediate_agent._target_anchor_index, 0, "immediate mode races through both anchors in 2 calls")

        bounded_agent = self._agent_with_pair(
            sequential_pair_promotion_mode="bounded_evidence",
            sequential_pair_promotion_window=5,
            sequential_pair_promotion_min_votes=3,
        )
        for _ in range(5):
            bounded_agent.update_relocalization(
                relocalization=[
                    AnchorRelocalization(anchor_index=bounded_agent._target_anchor_index, anchor_dx_m=-1.5,
                                         anchor_dy_m=0.0, confidence=0.5, backend="sequential_pair", inlier_count=100),
                    AnchorRelocalization(anchor_index=bounded_agent._target_anchor_index - 1, anchor_dx_m=-0.05,
                                         anchor_dy_m=0.0, confidence=0.95, backend="sequential_pair", inlier_count=450),
                ]
            )
        self.assertEqual(bounded_agent._target_anchor_index, 1,
                          "5 attempts is only enough for one 3-vote promotion (anchor 2 -> 1), not two")


class SequentialPairPromotionAliasAwareTest(unittest.TestCase):
    """Anchor-distinctiveness-aware promotion requirement (user-proposed
    2026-07-06, see relocalization.compute_anchor_alias_scores' and
    RouteMemoryAgent._promotion_requirement_for_anchor's docstrings, and
    investigations/2026-07-06-anchor-selection-and-icp-aliasing). Off by
    default; only changes bounded_evidence's window/min_votes for a
    candidate anchor whose precomputed alias_score is at or above threshold."""

    def _agent(self, **kwargs) -> RouteMemoryAgent:
        return RouteMemoryAgent(
            enabled=True, anchor_spacing_m=1.0,
            sequential_pair_promotion_mode="bounded_evidence",
            sequential_pair_promotion_window=5,
            sequential_pair_promotion_min_votes=3,
            sequential_pair_promotion_alias_threshold=0.6,
            sequential_pair_promotion_alias_window=8,
            sequential_pair_promotion_alias_min_votes=5,
            **kwargs,
        )

    def test_alias_aware_off_by_default(self):
        agent = RouteMemoryAgent(enabled=True)
        self.assertFalse(agent.sequential_pair_promotion_alias_aware)

    def test_flat_requirement_when_alias_aware_is_off(self):
        agent = self._agent(sequential_pair_promotion_alias_aware=False)
        agent.anchors = [RouteAnchor(index=3, pose_from_start=[0, 0, 0], distance_from_start_m=3.0,
                                      alias_score=0.99)]
        window, min_votes = agent._promotion_requirement_for_anchor(3)
        self.assertEqual((window, min_votes), (5, 3))

    def test_flat_requirement_when_alias_score_is_none(self):
        """Alias-aware mode is on but compute_anchor_alias_scores() was never
        called this episode -- must fall back to the flat requirement, not
        crash or treat an unknown anchor as suspicious."""
        agent = self._agent(sequential_pair_promotion_alias_aware=True)
        agent.anchors = [RouteAnchor(index=3, pose_from_start=[0, 0, 0], distance_from_start_m=3.0)]
        window, min_votes = agent._promotion_requirement_for_anchor(3)
        self.assertEqual((window, min_votes), (5, 3))

    def test_stall_relief_falls_back_to_flat_after_stall_attempts(self):
        """Stall relief (found necessary against real data): ep5 of the
        hard-11 set had every single anchor flagged (a uniformly self-similar
        route, not just a couple of hot spots) -- with plain alias-aware, it
        promoted once then froze for the remaining 357 of 381 attempts,
        actively worse than plain bounded_evidence. After
        sequential_pair_promotion_alias_stall_attempts votes without ever
        promoting, this anchor must fall back to the flat requirement."""
        agent = self._agent(sequential_pair_promotion_alias_aware=True,
                             sequential_pair_promotion_alias_stall_attempts=5)
        agent.anchors = [RouteAnchor(index=3, pose_from_start=[0, 0, 0], distance_from_start_m=3.0,
                                      alias_score=0.9)]
        for _ in range(4):
            agent._record_promotion_vote(3, False)
            window, min_votes = agent._promotion_requirement_for_anchor(3)
            self.assertEqual((window, min_votes), (8, 5), "must stay strict before the stall threshold")
        agent._record_promotion_vote(3, False)  # 5th vote -- stall counter now at 5
        window, min_votes = agent._promotion_requirement_for_anchor(3)
        self.assertEqual((window, min_votes), (5, 3), "must relax to flat once stalled")

    def test_stall_counter_resets_on_promotion(self):
        """The stall counter must not carry over past a promotion, mirroring
        how _promotion_vote_history itself is pruned -- the anchor that
        becomes "next" after a promotion is a different anchor and must get
        its own fresh stall budget."""
        agent = self._agent(sequential_pair_promotion_alias_aware=True,
                             sequential_pair_promotion_alias_stall_attempts=5)
        agent.anchors = [
            RouteAnchor(index=2, pose_from_start=[0, 0, 0], distance_from_start_m=2.0),
            RouteAnchor(index=1, pose_from_start=[0, 0, 0], distance_from_start_m=1.0, alias_score=0.9),
            RouteAnchor(index=0, pose_from_start=[0, 0, 0], distance_from_start_m=0.0, alias_score=0.9),
        ]
        agent._target_anchor_index = 2
        agent._return_started = True
        current = AnchorRelocalization(anchor_index=2, anchor_dx_m=-1.5, anchor_dy_m=0.0,
                                        confidence=0.5, backend="sequential_pair", inlier_count=100)
        close_next = AnchorRelocalization(anchor_index=1, anchor_dx_m=-0.05, anchor_dy_m=0.0,
                                           confidence=0.95, backend="sequential_pair", inlier_count=450)
        for _ in range(5):
            agent.update_relocalization(relocalization=[current, close_next])
        self.assertEqual(agent._target_anchor_index, 1)
        self.assertNotIn(1, agent._promotion_alias_stall_counter)
        # anchor0 is a brand new candidate -- must not inherit anchor1's exhausted stall budget.
        window, min_votes = agent._promotion_requirement_for_anchor(0)
        self.assertEqual((window, min_votes), (8, 5))

    def test_flat_requirement_when_alias_score_below_threshold(self):
        agent = self._agent(sequential_pair_promotion_alias_aware=True)
        agent.anchors = [RouteAnchor(index=3, pose_from_start=[0, 0, 0], distance_from_start_m=3.0,
                                      alias_score=0.59)]
        window, min_votes = agent._promotion_requirement_for_anchor(3)
        self.assertEqual((window, min_votes), (5, 3))

    def test_stricter_requirement_when_alias_score_at_or_above_threshold(self):
        agent = self._agent(sequential_pair_promotion_alias_aware=True)
        agent.anchors = [RouteAnchor(index=3, pose_from_start=[0, 0, 0], distance_from_start_m=3.0,
                                      alias_score=0.60)]
        window, min_votes = agent._promotion_requirement_for_anchor(3)
        self.assertEqual((window, min_votes), (8, 5))

    def test_alias_aware_promotion_takes_longer_for_a_flagged_anchor(self):
        """End-to-end: an alias-prone candidate that reads close_enough every
        single attempt must survive 5 attempts (not just 3) before promoting
        once alias-aware mode is on."""
        agent = self._agent(sequential_pair_promotion_alias_aware=True)
        agent.anchors = [
            RouteAnchor(index=2, pose_from_start=[0, 0, 0], distance_from_start_m=2.0),
            RouteAnchor(index=1, pose_from_start=[0, 0, 0], distance_from_start_m=1.0, alias_score=0.9),
            RouteAnchor(index=0, pose_from_start=[0, 0, 0], distance_from_start_m=0.0),
        ]
        agent._target_anchor_index = 2
        agent._return_started = True
        current = AnchorRelocalization(anchor_index=2, anchor_dx_m=-1.5, anchor_dy_m=0.0,
                                        confidence=0.5, backend="sequential_pair", inlier_count=100)
        close_next = AnchorRelocalization(anchor_index=1, anchor_dx_m=-0.05, anchor_dy_m=0.0,
                                           confidence=0.95, backend="sequential_pair", inlier_count=450)
        for _ in range(4):
            agent.update_relocalization(relocalization=[current, close_next])
            self.assertEqual(agent._target_anchor_index, 2, "must not promote before 5 qualifying votes")
        agent.update_relocalization(relocalization=[current, close_next])
        self.assertEqual(agent._target_anchor_index, 1, "must promote on the 5th qualifying vote")


class ComputeAnchorAliasScoresIntegrationTest(unittest.TestCase):
    """RouteMemoryAgent.compute_anchor_alias_scores: thin wiring around
    relocalization.compute_anchor_alias_scores (unit-tested on its own,
    directly against real hand-built shapes, in test_geometry_pipeline.py) --
    this only checks the RouteAnchor.alias_score field actually gets set
    from the real function's output."""

    @staticmethod
    def _rectangle_points() -> np.ndarray:
        top = np.stack([np.linspace(-2.0, 2.0, 40), np.full(40, 1.0)], axis=1)
        bottom = np.stack([np.linspace(-2.0, 2.0, 40), np.full(40, -1.0)], axis=1)
        return np.concatenate([top, bottom], axis=0).astype(np.float32)

    def test_alias_score_is_stored_on_each_anchor(self):
        agent = RouteMemoryAgent(enabled=True)
        rect = self._rectangle_points()
        agent.anchors = [
            RouteAnchor(index=0, pose_from_start=[0, 0, 0], distance_from_start_m=0.0,
                        descriptor={"local_map_points_body": rect}),
            RouteAnchor(index=1, pose_from_start=[0, 0, 0], distance_from_start_m=1.0,
                        descriptor={"local_map_points_body": rect}),
            RouteAnchor(index=2, pose_from_start=[0, 0, 0], distance_from_start_m=2.0,
                        descriptor={"local_map_points_body": rect}),
        ]
        for anchor in agent.anchors:
            self.assertIsNone(anchor.alias_score)
        agent.compute_anchor_alias_scores(min_neighbor_offset=2, max_neighbor_offset=5)
        # anchor0 and anchor2 (offset 2, identical shape) are within the
        # window and not the excluded immediate neighbor -- both flagged high.
        self.assertGreater(agent.anchors[0].alias_score, 0.6)
        self.assertGreater(agent.anchors[2].alias_score, 0.6)

    def test_no_anchors_is_a_no_op(self):
        agent = RouteMemoryAgent(enabled=True)
        agent.compute_anchor_alias_scores()  # must not raise

    def test_alias_score_is_serialized_in_summary(self):
        """2026-07-10: previously alias_score was computed and stored on each
        RouteAnchor but silently dropped by `_anchor_summary` before ever
        reaching the measurement JSON, so no offline analysis could check it
        against other diagnostics after the fact -- see
        investigations/2026-07-09-.../DATA.md §G and
        investigations/2026-07-10-.../FINDINGS.md's methodology notes."""
        agent = RouteMemoryAgent(enabled=True)
        rect = self._rectangle_points()
        agent.anchors = [
            RouteAnchor(index=0, pose_from_start=[0, 0, 0], distance_from_start_m=0.0,
                        descriptor={"local_map_points_body": rect}),
            RouteAnchor(index=1, pose_from_start=[0, 0, 0], distance_from_start_m=1.0,
                        descriptor={"local_map_points_body": rect}),
            RouteAnchor(index=2, pose_from_start=[0, 0, 0], distance_from_start_m=2.0,
                        descriptor={"local_map_points_body": rect}),
        ]
        self.assertIsNone(agent.summary()["anchors"][0]["alias_score"])
        agent.compute_anchor_alias_scores(min_neighbor_offset=2, max_neighbor_offset=5)
        summary_anchors = agent.summary()["anchors"]
        for anchor, summary_anchor in zip(agent.anchors, summary_anchors):
            self.assertEqual(summary_anchor["alias_score"], anchor.alias_score)
        self.assertGreater(summary_anchors[0]["alias_score"], 0.6)
        json.dumps(summary_anchors)


class MultiframeAnchorWindowTest(unittest.TestCase):
    """2026-07-08: anchors default to a single instantaneous LiDAR frame
    (window=1, unchanged). window>1 merges the last N outbound frames --
    each reprojected from its own capture-time pose into the anchor's own
    final frame -- into one richer submap, aimed at genuine rotational
    self-similarity a single viewpoint cannot disambiguate at any point
    density (see investigations/2026-07-08 self-alias findings)."""

    def test_default_window_is_one_and_behaves_exactly_like_before(self):
        agent = RouteMemoryAgent(enabled=True, anchor_spacing_m=1.0)
        self.assertEqual(agent.multiframe_anchor_window, 1)
        agent.update_outbound_motion([0.5, 0.0, 0.0], descriptor={"local_map_points_body": np.array([[9.0, 9.0]])})
        agent.update_outbound_motion([0.5, 0.0, 0.0], descriptor={"local_map_points_body": np.array([[1.0, 0.0]])})
        # index 0 is the always-present "start" anchor created in __init__.
        self.assertEqual(len(agent.anchors), 2)
        np.testing.assert_allclose(agent.anchors[-1].descriptor["local_map_points_body"], [[1.0, 0.0]])

    def test_window_merges_translation_only_frames_into_anchor_frame(self):
        agent = RouteMemoryAgent(enabled=True, anchor_spacing_m=1.0, multiframe_anchor_window=2)
        # step1: pose becomes (0.5,0,0); its own point [1.0, 0.0] is 1m ahead
        # of the robot at that moment, i.e. world (1.5, 0.0).
        agent.update_outbound_motion([0.5, 0.0, 0.0], descriptor={"local_map_points_body": np.array([[1.0, 0.0]])})
        # step2: pose becomes (1.0,0,0) -- crosses anchor_spacing_m, anchor
        # created here. Its own point [1.0, 0.0] is world (2.0, 0.0).
        agent.update_outbound_motion([0.5, 0.0, 0.0], descriptor={"local_map_points_body": np.array([[1.0, 0.0]])})
        self.assertEqual(len(agent.anchors), 2)
        merged = agent.anchors[-1].descriptor["local_map_points_body"]
        self.assertEqual(len(merged), 2)
        # anchor's own frame is pose (1.0,0,0): world (1.5,0) -> anchor-frame (0.5,0);
        # world (2.0,0) -> anchor-frame (1.0,0).
        np.testing.assert_allclose(sorted(merged[:, 0].tolist()), [0.5, 1.0], atol=1e-5)
        np.testing.assert_allclose(merged[:, 1], [0.0, 0.0], atol=1e-5)

    def test_window_correctly_reprojects_across_a_rotation(self):
        agent = RouteMemoryAgent(enabled=True, anchor_spacing_m=1.0, multiframe_anchor_window=2)
        # step1: pure 90-degree turn in place, no translation yet (distance still 0).
        agent.update_outbound_motion(
            [0.0, 0.0, math.pi / 2], descriptor={"local_map_points_body": np.array([[1.0, 0.0]])})
        # step2: move 1.0m forward in the NEW heading -- crosses anchor_spacing_m.
        agent.update_outbound_motion(
            [1.0, 0.0, 0.0], descriptor={"local_map_points_body": np.array([[1.0, 0.0]])})
        self.assertEqual(len(agent.anchors), 2)
        merged = agent.anchors[-1].descriptor["local_map_points_body"]
        self.assertEqual(len(merged), 2)
        # anchor's own pose is (0, 1.0, pi/2) (compose_pose([0,0,0],[0,0,pi/2]) then
        # moving 1.0 "forward" in body frame = world +y). step1's point [1.0,0.0] in
        # step1's frame (pose (0,0,pi/2)) is world (0, 1.0) -- coincides exactly with
        # the anchor's own origin, so it must land at local (0,0) in the anchor frame.
        # step2's own frame IS the anchor's frame (identical pose), so its point
        # [1.0,0.0] must reproject to itself unchanged.
        merged_sorted = merged[np.argsort(merged[:, 0])]
        np.testing.assert_allclose(merged_sorted[0], [0.0, 0.0], atol=1e-5)
        np.testing.assert_allclose(merged_sorted[1], [1.0, 0.0], atol=1e-5)

    def test_frames_without_a_recognized_point_key_are_skipped_not_crashed(self):
        agent = RouteMemoryAgent(enabled=True, anchor_spacing_m=1.0, multiframe_anchor_window=3)
        agent.update_outbound_motion([0.4, 0.0, 0.0], descriptor={"rgb": np.zeros((2, 2, 3))})
        agent.update_outbound_motion([0.3, 0.0, 0.0], descriptor={"local_map_points_body": np.array([[1.0, 0.0]])})
        agent.update_outbound_motion([0.3, 0.0, 0.0], descriptor={"local_map_points_body": np.array([[2.0, 0.0]])})
        self.assertEqual(len(agent.anchors), 2)
        merged = agent.anchors[-1].descriptor["local_map_points_body"]
        self.assertEqual(len(merged), 2)  # only the two usable frames contribute


class SequentialPairPromotionUsePreClosureEstimatesTest(unittest.TestCase):
    """2026-07-10 (next-behind gate-vs-fusion investigation): the promotion
    vote gates (close_enough/trend_ok/quality_ok) normally see next/current's
    estimate AFTER _sequential_pair_closure_precheck has run -- in belief mode
    with trust_aware_guard, a large disagreement can rewrite next's own dx/dy
    (and inherit a discounted confidence) before promotion ever gets to look
    at it, even though next's own raw ICP reading was fine on its own. This
    flag (off by default) makes the gates look at each side's raw,
    pre-closure-check estimate instead -- the reported hint (once promoted)
    still goes through the unchanged closure-check/fusion pipeline."""

    def _agent_with_pair(self, **kwargs) -> RouteMemoryAgent:
        agent = RouteMemoryAgent(
            enabled=True, anchor_spacing_m=1.0, sequential_pair_closure_check_enabled=True,
            sequential_pair_closure_mode="belief", sequential_pair_closure_belief_trust_aware_guard=True,
            sequential_pair_promotion_mode="immediate", **kwargs,
        )
        for _ in range(2):
            agent.update_outbound_motion([1.0, 0.0, 0.0])
        agent.finalize_outbound()
        return agent  # anchors: 0 @ 0m, 1 @ 1m, 2 @ 2m (return-start); current starts at 2

    def _scenario(self):
        # current (anchor 2): far (distance 1.5m), but clean/trustworthy.
        current = AnchorRelocalization(
            anchor_index=2, anchor_dx_m=-1.5, anchor_dy_m=0.0, anchor_dtheta_rad=0.0,
            confidence=0.5, backend="sequential_pair", inlier_count=100,
            match_class="clean_full_pose", near_tie_basin_count=0,
        )
        # next (anchor 1): close (distance 0.05m) and high quality on its own
        # raw reading, but flagged untrustworthy (ambiguous) -- the large
        # current/next disagreement this creates makes the trust-aware guard
        # reconstruct next from current's own reading, pushing next's
        # post-fusion distance out to ~2.5m (>> promotion_close_radius_m).
        next_reading = AnchorRelocalization(
            anchor_index=1, anchor_dx_m=-0.05, anchor_dy_m=0.0, anchor_dtheta_rad=0.0,
            confidence=0.95, backend="sequential_pair", inlier_count=450,
            match_class="ambiguous_high_confidence", near_tie_basin_count=1,
        )
        return current, next_reading

    def test_default_flag_is_off(self):
        agent = RouteMemoryAgent(enabled=True)
        self.assertFalse(agent.sequential_pair_promotion_use_pre_closure_estimates)

    def test_flag_off_promotion_gated_on_post_fusion_estimate(self):
        agent = self._agent_with_pair(sequential_pair_promotion_use_pre_closure_estimates=False)
        current, next_reading = self._scenario()
        agent.update_relocalization(relocalization=[current, next_reading])
        self.assertEqual(
            agent._target_anchor_index, 2,
            "post-fusion next reading (~2.5m away) must not clear close_enough on attempt 1",
        )

    def test_flag_on_promotion_gated_on_raw_pre_fusion_estimate(self):
        agent = self._agent_with_pair(sequential_pair_promotion_use_pre_closure_estimates=True)
        current, next_reading = self._scenario()
        agent.update_relocalization(relocalization=[current, next_reading])
        self.assertEqual(
            agent._target_anchor_index, 1,
            "raw next reading (0.05m away, high quality) should promote immediately",
        )

    def test_flag_on_reported_hint_still_goes_through_closure_fusion(self):
        """The promotion decision uses raw estimates, but once next is
        selected, the reported anchor_dx_m/anchor_dy_m must still be the
        closure-check's reconstructed value, not the raw one -- this flag
        only changes what feeds the vote gate, never the reported hint."""
        agent = self._agent_with_pair(sequential_pair_promotion_use_pre_closure_estimates=True)
        current, next_reading = self._scenario()
        accepted = agent.update_relocalization(relocalization=[current, next_reading])
        self.assertIsNotNone(accepted)
        self.assertEqual(agent._target_anchor_index, 1)
        self.assertIn("belief_trust_aware_reconstructed", accepted.backend)
        self.assertNotAlmostEqual(accepted.anchor_dx_m, next_reading.anchor_dx_m, places=4)


class SequentialPairShortBaselineDisambiguationTest(unittest.TestCase):
    """2026-07-12, problem-2 step 5: cross-checks an ambiguous ICP reading of
    a candidate anchor against a second reading of the *same* candidate taken
    once the robot has genuinely moved (default 0.3m) -- exploiting real
    parallax between two different vantage points.

    NOT the same mechanism as the already-tried-and-regressed 2026-07-08
    `multiframe_anchor_window` (merges several OUTBOUND frames captured at
    the *same* physical location into one denser anchor descriptor -- more
    points from the same viewpoint, confirmed not to help a genuinely
    symmetric structure). This instead compares two independent RETURN-phase
    observations from two different positions."""

    def _agent(self, **kwargs) -> RouteMemoryAgent:
        agent = RouteMemoryAgent(
            enabled=True, anchor_spacing_m=1.0, sequential_pair_promotion_mode="immediate",
            **kwargs,
        )
        for _ in range(2):
            agent.update_outbound_motion([1.0, 0.0, 0.0])
        agent.finalize_outbound()
        return agent  # anchors: 0 @ 0m, 1 @ 1m, 2 @ 2m (return-start); current starts at 2

    def _ambiguous_next_reading(self, dx: float, dy: float, dtheta: float) -> AnchorRelocalization:
        return AnchorRelocalization(
            anchor_index=1, anchor_dx_m=dx, anchor_dy_m=dy, anchor_dtheta_rad=dtheta,
            confidence=0.95, backend="sequential_pair", inlier_count=450,
            match_class="ambiguous_high_confidence", near_tie_basin_count=1,
        )

    def _clean_current_reading(self) -> AnchorRelocalization:
        return AnchorRelocalization(
            anchor_index=2, anchor_dx_m=0.0, anchor_dy_m=0.0, anchor_dtheta_rad=0.0,
            confidence=0.5, backend="sequential_pair", inlier_count=100,
            match_class="clean_full_pose", near_tie_basin_count=0,
        )

    def test_default_flag_is_off(self):
        agent = RouteMemoryAgent(enabled=True)
        self.assertFalse(agent.sequential_pair_short_baseline_disambiguation)

    def test_disabled_by_default_does_not_touch_heading_reliable(self):
        agent = self._agent()  # flag left at its default (off)
        current = self._clean_current_reading()
        reading = self._ambiguous_next_reading(0.3, 0.2, math.radians(25))
        accepted = agent.update_relocalization(relocalization=[current, reading])
        self.assertTrue(accepted.anchor_heading_reliable)
        self.assertEqual(agent._yaw_disambiguation_pending, {})

    def test_two_consistent_readings_from_different_positions_confirm_reliable(self):
        agent = self._agent(sequential_pair_short_baseline_disambiguation=True)
        p1 = agent.current_absolute_pose_from_start()
        # anchor's true (synthetic) absolute pose, implied by reading 1 --
        # distance 0.92m (> promotion_close_radius_m=0.75) so attempt 1 must
        # NOT promote yet (pending state needs to survive to attempt 2).
        dx1, dy1, dtheta1 = 0.9, 0.2, math.radians(25)
        anchor_abs_pose = compose_pose(p1, [dx1, dy1, dtheta1])
        current = self._clean_current_reading()
        reading1 = self._ambiguous_next_reading(dx1, dy1, dtheta1)
        agent.update_relocalization(relocalization=[current, reading1])
        self.assertIn(1, agent._yaw_disambiguation_pending, "first ambiguous reading should be stored, waiting")

        agent.update_return_motion([0.4, 0.0, 0.0])  # >= default min_travel_m=0.3
        p2 = agent.current_absolute_pose_from_start()

        # second reading of the SAME real anchor pose, computed exactly (no noise)
        dx2, dy2, dtheta2 = relative_delta(p2, anchor_abs_pose)
        reading2 = self._ambiguous_next_reading(dx2, dy2, dtheta2)
        accepted = agent.update_relocalization(relocalization=[current, reading2])

        self.assertNotIn(1, agent._yaw_disambiguation_pending, "resolved pair must be consumed")
        self.assertEqual(accepted.anchor_index, 1, "close reading should have promoted next")
        self.assertTrue(accepted.anchor_heading_reliable, "two consistent readings must not downgrade reliability")

    def test_two_disagreeing_readings_flag_heading_unreliable(self):
        agent = self._agent(sequential_pair_short_baseline_disambiguation=True)
        p1 = agent.current_absolute_pose_from_start()
        # same distance-0.92m setup as the consistent-readings test, so
        # attempt 1 doesn't promote and the pending state survives.
        dx1, dy1, dtheta1 = 0.9, 0.2, math.radians(25)
        anchor_abs_pose = compose_pose(p1, [dx1, dy1, dtheta1])
        current = self._clean_current_reading()
        reading1 = self._ambiguous_next_reading(dx1, dy1, dtheta1)
        agent.update_relocalization(relocalization=[current, reading1])

        agent.update_return_motion([0.4, 0.0, 0.0])
        p2 = agent.current_absolute_pose_from_start()

        # second reading implies a genuinely DIFFERENT absolute anchor pose --
        # same position (dx/dy consistent, so close_enough still forces
        # promotion), rotation off by 90 deg -- the "confidently wrong
        # rotation" signature this mechanism targets.
        wrong_abs_pose = [
            anchor_abs_pose[0], anchor_abs_pose[1],
            wrap_angle(anchor_abs_pose[2] + math.radians(90.0)),
        ]
        dx2, dy2, dtheta2 = relative_delta(p2, wrong_abs_pose)
        reading2 = self._ambiguous_next_reading(dx2, dy2, dtheta2)
        accepted = agent.update_relocalization(relocalization=[current, reading2])

        self.assertEqual(accepted.anchor_index, 1, "close reading should have promoted next")
        self.assertFalse(accepted.anchor_heading_reliable, "disagreeing readings must flag heading unreliable")

    def test_triggers_even_when_match_class_reports_clean_full_pose(self):
        """This is NOT gated on match_class -- an offline smoke test against
        real ep1040 capture data (this project's own flagship
        confidently-wrong-rotation example) found 86.5% of its worst bearing
        errors carry match_class=clean_full_pose, which is the whole reason
        they were unexplained by existing diagnostics in the first place.
        Gating this check behind match_class ambiguity would have missed
        almost all of the cases it exists to catch."""
        agent = self._agent(sequential_pair_short_baseline_disambiguation=True)
        p1 = agent.current_absolute_pose_from_start()
        dx1, dy1, dtheta1 = 0.9, 0.2, math.radians(25)
        anchor_abs_pose = compose_pose(p1, [dx1, dy1, dtheta1])
        current = self._clean_current_reading()
        clean_reading1 = AnchorRelocalization(
            anchor_index=1, anchor_dx_m=dx1, anchor_dy_m=dy1, anchor_dtheta_rad=dtheta1,
            confidence=0.95, backend="sequential_pair", inlier_count=450,
            match_class="clean_full_pose", near_tie_basin_count=0,
        )
        agent.update_relocalization(relocalization=[current, clean_reading1])
        self.assertIn(1, agent._yaw_disambiguation_pending, "clean-tagged reading must still be tracked")

        agent.update_return_motion([0.4, 0.0, 0.0])
        p2 = agent.current_absolute_pose_from_start()
        wrong_abs_pose = [
            anchor_abs_pose[0], anchor_abs_pose[1],
            wrap_angle(anchor_abs_pose[2] + math.radians(90.0)),
        ]
        dx2, dy2, dtheta2 = relative_delta(p2, wrong_abs_pose)
        clean_reading2 = AnchorRelocalization(
            anchor_index=1, anchor_dx_m=dx2, anchor_dy_m=dy2, anchor_dtheta_rad=dtheta2,
            confidence=0.95, backend="sequential_pair", inlier_count=450,
            match_class="clean_full_pose", near_tie_basin_count=0,
        )
        accepted = agent.update_relocalization(relocalization=[current, clean_reading2])

        self.assertEqual(accepted.anchor_index, 1)
        self.assertFalse(
            accepted.anchor_heading_reliable,
            "must flag unreliable even though both raw readings self-report clean_full_pose",
        )

    def test_not_enough_travel_keeps_waiting_without_overwriting_first_reading(self):
        agent = self._agent(sequential_pair_short_baseline_disambiguation=True)
        current = self._clean_current_reading()
        reading1 = self._ambiguous_next_reading(1.5, 0.3, math.radians(25))
        agent.update_relocalization(relocalization=[current, reading1])
        stored_first = dict(agent._yaw_disambiguation_pending[1])

        agent.update_return_motion([0.1, 0.0, 0.0])  # below default min_travel_m=0.3
        reading_too_soon = self._ambiguous_next_reading(1.4, 0.3, math.radians(99))
        agent.update_relocalization(relocalization=[current, reading_too_soon])

        self.assertIn(1, agent._yaw_disambiguation_pending, "still waiting for enough travel")
        self.assertEqual(
            agent._yaw_disambiguation_pending[1]["anchor_abs_pose"], stored_first["anchor_abs_pose"],
            "first reading must not be overwritten before enough baseline accumulates",
        )

    def test_pending_history_cleared_on_promotion_when_require_resolution_off(self):
        """Pruned like _promotion_distance_history/etc -- must not carry stale
        state for an already-passed anchor into the next candidate's dwell.

        This documents the DEFAULT (sequential_pair_short_baseline_require_
        resolution=False) behavior specifically: promotion can still wipe an
        unresolved pending entry, since that's exactly the 2026-07-15/16
        finding this project's own under-triggering investigation traced the
        0.1% fire rate to. See SequentialPairShortBaselineRequireResolutionTest
        below for the require_resolution=True behavior, which changes this."""
        agent = self._agent(sequential_pair_short_baseline_disambiguation=True)
        current = self._clean_current_reading()
        reading1 = self._ambiguous_next_reading(1.5, 0.3, math.radians(25))
        agent.update_relocalization(relocalization=[current, reading1])
        self.assertIn(1, agent._yaw_disambiguation_pending)

        # a close, unambiguous reading promotes next (anchor 1) outright
        close_reading = AnchorRelocalization(
            anchor_index=1, anchor_dx_m=0.1, anchor_dy_m=0.0, anchor_dtheta_rad=0.0,
            confidence=0.95, backend="sequential_pair", inlier_count=450,
            match_class="clean_full_pose", near_tie_basin_count=0,
        )
        accepted = agent.update_relocalization(relocalization=[current, close_reading])
        self.assertEqual(accepted.anchor_index, 1)
        self.assertNotIn(1, agent._yaw_disambiguation_pending, "promoted anchor's pending state must be pruned")


class SequentialPairShortBaselineRequireResolutionTest(unittest.TestCase):
    """2026-07-16: fixes short-baseline disambiguation's measured 0.1% fire
    rate / 0% recall (investigations/2026-07-13-.../FINDINGS.md), root-caused
    to promotion routinely committing -- via the rare single-attempt bypass
    (4.4% of promotions) AND, dominantly, via bounded_evidence's own normal
    multi-vote path (19.8% of all promotions lacked the required 0.3m of
    travel) -- before a pending disambiguation entry ever gets a chance to
    resolve, which then gets deleted unconditionally on promotion regardless.

    Deliberately NOT a quarantine: no permanent block, bounded by
    sequential_pair_short_baseline_stall_attempts (a release valve), and once
    resolved -- agreeing or disagreeing -- promotion proceeds exactly as
    before (abstain, don't ban)."""

    def _agent(self, **kwargs) -> RouteMemoryAgent:
        agent = RouteMemoryAgent(
            enabled=True, anchor_spacing_m=1.0, sequential_pair_promotion_mode="immediate",
            **kwargs,
        )
        for _ in range(2):
            agent.update_outbound_motion([1.0, 0.0, 0.0])
        agent.finalize_outbound()
        return agent  # anchors: 0 @ 0m, 1 @ 1m, 2 @ 2m (return-start); current starts at 2

    def _clean_current_reading(self) -> AnchorRelocalization:
        return AnchorRelocalization(
            anchor_index=2, anchor_dx_m=0.0, anchor_dy_m=0.0, anchor_dtheta_rad=0.0,
            confidence=0.5, backend="sequential_pair", inlier_count=100,
            match_class="clean_full_pose", near_tie_basin_count=0,
        )

    def _close_next_reading(self, dx: float, dy: float, dtheta: float) -> AnchorRelocalization:
        # distance <= promotion_close_radius_m (0.75) -> close_enough=True,
        # high enough confidence/inlier_count that quality_ok is trivially met
        # against the mediocre current reading above.
        return AnchorRelocalization(
            anchor_index=1, anchor_dx_m=dx, anchor_dy_m=dy, anchor_dtheta_rad=dtheta,
            confidence=0.95, backend="sequential_pair", inlier_count=450,
            match_class="ambiguous_high_confidence", near_tie_basin_count=1,
        )

    def test_default_require_resolution_flag_is_off(self):
        agent = RouteMemoryAgent(enabled=True)
        self.assertFalse(agent.sequential_pair_short_baseline_require_resolution)

    def test_require_resolution_is_a_noop_without_disambiguation_enabled(self):
        agent = self._agent(
            sequential_pair_short_baseline_disambiguation=False,
            sequential_pair_short_baseline_require_resolution=True,
        )
        current = self._clean_current_reading()
        close_reading = self._close_next_reading(0.5, 0.0, math.radians(25))
        accepted = agent.update_relocalization(relocalization=[current, close_reading])
        self.assertEqual(
            accepted.anchor_index, 1,
            "must promote immediately -- disambiguation itself is off, so nothing can ever be pending",
        )

    def test_unresolved_pending_withholds_promotion(self):
        agent = self._agent(
            sequential_pair_short_baseline_disambiguation=True,
            sequential_pair_short_baseline_require_resolution=True,
        )
        current = self._clean_current_reading()
        close_reading = self._close_next_reading(0.5, 0.0, math.radians(25))
        accepted = agent.update_relocalization(relocalization=[current, close_reading])
        self.assertIn(1, agent._yaw_disambiguation_pending, "first reading creates a pending entry")
        self.assertEqual(
            accepted.anchor_index, 2,
            "promotion must be withheld while disambiguation is still unresolved, even though this "
            "reading is close enough that it would have promoted immediately otherwise",
        )
        self.assertEqual(agent._target_anchor_index, 2)

    def test_resolution_completes_agreeing_then_promotes_and_prunes_state(self):
        agent = self._agent(
            sequential_pair_short_baseline_disambiguation=True,
            sequential_pair_short_baseline_require_resolution=True,
        )
        current = self._clean_current_reading()
        p1 = agent.current_absolute_pose_from_start()
        dx1, dy1, dtheta1 = 0.5, 0.0, math.radians(25)
        anchor_abs_pose = compose_pose(p1, [dx1, dy1, dtheta1])
        reading1 = self._close_next_reading(dx1, dy1, dtheta1)
        agent.update_relocalization(relocalization=[current, reading1])
        self.assertEqual(agent._target_anchor_index, 2, "withheld on attempt 1")

        agent.update_return_motion([0.4, 0.0, 0.0])  # >= default min_travel_m=0.3
        p2 = agent.current_absolute_pose_from_start()
        dx2, dy2, dtheta2 = relative_delta(p2, anchor_abs_pose)
        reading2 = self._close_next_reading(dx2, dy2, dtheta2)
        accepted = agent.update_relocalization(relocalization=[current, reading2])

        self.assertEqual(accepted.anchor_index, 1, "resolved (agreeing) -> promotes normally")
        self.assertTrue(accepted.anchor_heading_reliable)
        self.assertNotIn(1, agent._yaw_disambiguation_pending)
        self.assertNotIn(1, agent._short_baseline_stall_counter)

    def test_resolution_completes_disagreeing_still_promotes_with_reliable_false(self):
        """Abstain, don't ban: a confirmed disagreement does not block
        promotion -- consistent with this project's established convention
        (e.g. current_confidence_ambiguity_gate_enabled) that detecting a
        problem downgrades trust, it doesn't blacklist the candidate."""
        agent = self._agent(
            sequential_pair_short_baseline_disambiguation=True,
            sequential_pair_short_baseline_require_resolution=True,
        )
        current = self._clean_current_reading()
        p1 = agent.current_absolute_pose_from_start()
        dx1, dy1, dtheta1 = 0.5, 0.0, math.radians(25)
        anchor_abs_pose = compose_pose(p1, [dx1, dy1, dtheta1])
        reading1 = self._close_next_reading(dx1, dy1, dtheta1)
        agent.update_relocalization(relocalization=[current, reading1])

        agent.update_return_motion([0.4, 0.0, 0.0])
        p2 = agent.current_absolute_pose_from_start()
        wrong_abs_pose = [
            anchor_abs_pose[0], anchor_abs_pose[1],
            wrap_angle(anchor_abs_pose[2] + math.radians(90.0)),
        ]
        dx2, dy2, dtheta2 = relative_delta(p2, wrong_abs_pose)
        reading2 = self._close_next_reading(dx2, dy2, dtheta2)
        accepted = agent.update_relocalization(relocalization=[current, reading2])

        self.assertEqual(accepted.anchor_index, 1, "resolved (disagreeing) -> still promotes")
        self.assertFalse(accepted.anchor_heading_reliable)
        self.assertNotIn(1, agent._yaw_disambiguation_pending)
        self.assertNotIn(1, agent._short_baseline_stall_counter)

    def test_stall_release_valve_forces_promotion_after_max_attempts(self):
        agent = self._agent(
            sequential_pair_short_baseline_disambiguation=True,
            sequential_pair_short_baseline_require_resolution=True,
            sequential_pair_short_baseline_stall_attempts=2,
        )
        current = self._clean_current_reading()
        close_reading = self._close_next_reading(0.5, 0.0, math.radians(25))
        # No update_return_motion between attempts -- travel stays 0, so the
        # pending entry never resolves either way on its own.
        accepted1 = agent.update_relocalization(relocalization=[current, close_reading])
        self.assertEqual(accepted1.anchor_index, 2, "attempt 1: withheld (stall counter -> 1)")
        accepted2 = agent.update_relocalization(relocalization=[current, close_reading])
        self.assertEqual(accepted2.anchor_index, 2, "attempt 2: still withheld (stall counter -> 2, <= limit)")
        accepted3 = agent.update_relocalization(relocalization=[current, close_reading])
        self.assertEqual(
            accepted3.anchor_index, 1,
            "attempt 3: stall counter -> 3, exceeds stall_attempts=2 -> release valve promotes anyway",
        )
        self.assertTrue(
            accepted3.anchor_heading_reliable,
            "never resolved either way (no travel accumulated) -- left at its default True, not downgraded",
        )

    def test_pending_and_stall_counter_pruned_on_promotion_via_release_valve(self):
        agent = self._agent(
            sequential_pair_short_baseline_disambiguation=True,
            sequential_pair_short_baseline_require_resolution=True,
            sequential_pair_short_baseline_stall_attempts=2,
        )
        current = self._clean_current_reading()
        close_reading = self._close_next_reading(0.5, 0.0, math.radians(25))
        for _ in range(3):
            accepted = agent.update_relocalization(relocalization=[current, close_reading])
        self.assertEqual(accepted.anchor_index, 1, "promoted via the release valve on the 3rd attempt")
        self.assertNotIn(1, agent._yaw_disambiguation_pending)
        self.assertNotIn(1, agent._short_baseline_stall_counter)

    def test_does_not_add_delay_once_resolved_before_vote_quota_in_bounded_evidence(self):
        """The withhold check must only engage while a pending entry is
        genuinely unresolved -- it must not add a blanket extra delay to
        bounded_evidence's own normal multi-vote path once disambiguation has
        already resolved. Runs the identical scenario with the flag on vs off
        and confirms promotion happens on the same attempt in both cases."""
        def run(require_resolution: bool):
            agent = RouteMemoryAgent(
                enabled=True, anchor_spacing_m=1.0,
                sequential_pair_promotion_mode="bounded_evidence",
                sequential_pair_promotion_window=5, sequential_pair_promotion_min_votes=2,
                sequential_pair_short_baseline_disambiguation=True,
                sequential_pair_short_baseline_require_resolution=require_resolution,
            )
            for _ in range(2):
                agent.update_outbound_motion([1.0, 0.0, 0.0])
            agent.finalize_outbound()
            current = self._clean_current_reading()  # present every attempt -> vote path, not the bypass
            p1 = agent.current_absolute_pose_from_start()
            dx1, dy1, dtheta1 = 0.5, 0.0, math.radians(25)
            anchor_abs_pose = compose_pose(p1, [dx1, dy1, dtheta1])
            reading1 = self._close_next_reading(dx1, dy1, dtheta1)
            a1 = agent.update_relocalization(relocalization=[current, reading1])  # vote 1 (fresh pending -> withheld either way)
            agent.update_return_motion([0.4, 0.0, 0.0])  # resolve exactly as the 2-vote quota is met
            p2 = agent.current_absolute_pose_from_start()
            dx2, dy2, dtheta2 = relative_delta(p2, anchor_abs_pose)
            reading2 = self._close_next_reading(dx2, dy2, dtheta2)
            a2 = agent.update_relocalization(relocalization=[current, reading2])  # vote 2, resolves here too
            return a1.anchor_index, a2.anchor_index

        with_flag = run(True)
        without_flag = run(False)
        self.assertEqual(with_flag, without_flag, "identical promotion timing whether the flag is on or off")
        self.assertEqual(with_flag[-1], 1, "promotes on the 2nd qualifying vote in both cases, the moment "
                                            "disambiguation resolves -- no extra delay added")


if __name__ == "__main__":
    unittest.main()
