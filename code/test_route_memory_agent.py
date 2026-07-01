import math
import unittest

from route_memory_agent import (
    AnchorRelocalization,
    RelativeStartProgress,
    RouteMemoryAgent,
    compose_pose,
    inverse_delta,
    relative_delta,
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

    def test_finalize_outbound_saves_final_descriptor(self):
        agent = RouteMemoryAgent(enabled=True, anchor_spacing_m=1.0)
        agent.update_outbound_motion([0.5, 0.0, 0.0])
        agent.finalize_outbound(
            descriptor={"kind": "final_rgbd"},
            metadata={"world_pose": [1.0, 2.0, 0.0]},
        )

        final_anchor = agent.summary()["anchors"][-1]
        self.assertEqual(final_anchor["metadata"]["event"], "outbound_final")
        self.assertEqual(final_anchor["metadata"]["world_pose"], [1.0, 2.0, 0.0])
        self.assertEqual(final_anchor["descriptor"], {"kind": "final_rgbd"})

    def test_first_return_update_forces_relocalization_before_interval(self):
        calls = []

        def relocalizer(descriptor, anchors):
            calls.append(descriptor)
            return AnchorRelocalization(
                anchor_index=1,
                anchor_dx_m=0.0,
                anchor_dy_m=0.0,
                anchor_dtheta_rad=0.0,
                confidence=1.0,
                backend="forced_first",
            )

        agent = RouteMemoryAgent(
            enabled=True,
            anchor_spacing_m=1.0,
            relocalization_interval_updates=25,
            relocalizer=relocalizer,
        )
        agent.update_outbound_motion([1.0, 0.0, 0.0], descriptor={"kind": "anchor"})
        agent.finalize_outbound()
        agent.update_return_motion([0.0, 0.0, 0.0], local_descriptor={"kind": "return_start"})

        self.assertEqual(calls, [{"kind": "return_start"}])
        self.assertEqual(agent.summary()["latest_relocalization"]["backend"], "forced_first")

    def test_return_start_prior_rejects_first_alias_observation(self):
        agent = RouteMemoryAgent(enabled=True, anchor_spacing_m=1.0)
        for _ in range(10):
            agent.update_outbound_motion([1.0, 0.0, 0.0])
        agent.finalize_outbound()

        rejected = agent.update_relocalization(relocalization=AnchorRelocalization(
            anchor_index=4,
            anchor_dx_m=0.0,
            anchor_dy_m=0.0,
            anchor_dtheta_rad=0.0,
            confidence=1.0,
            backend="aliased_first_frame",
            inlier_count=30,
        ))

        self.assertIsNone(rejected)
        summary = agent.summary()
        self.assertIsNone(summary["latest_relocalization"])
        self.assertEqual(summary["sequence_observation"]["source"], "return_start_prior")
        self.assertEqual(summary["relocalization_events"][-1]["reject_reason"], "sequence_candidate_score_too_low")

    def test_vio_bridge_defaults_enabled(self):
        agent = RouteMemoryAgent(enabled=True)
        self.assertTrue(agent.vio_bridge_enabled)

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
        self.assertIn("odometry next-anchor vector", instruction)
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
        self.assertLessEqual(agent.progress().target_anchor_index, 2)
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
        self.assertLessEqual(progress.target_anchor_index, 1)
        self.assertEqual(progress.relocalization_backend, "external_full_pose")
        self.assertEqual(progress.source, "arc_length_particle_filter")
        self.assertLess(progress.distance_to_start_m, 2.0)

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
            anchor_index=5,
            anchor_dx_m=-1.0,
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
        self.assertLessEqual(progress.target_anchor_index, 5)

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
