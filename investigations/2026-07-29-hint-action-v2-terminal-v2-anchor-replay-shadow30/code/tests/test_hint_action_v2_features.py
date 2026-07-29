import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "training"))

from hint_action_v2_features import (  # noqa: E402
    HintActionV2FeatureState,
    circular_delta_deg,
    clearance_metadata,
)


def row(step=75, bearing=179.0, target=4):
    return {
        "task": "hint_action_decision",
        "time": {"step": step},
        "inputs": {
            "movement": {
                "steps_since_previous": 75,
                "translation_since_previous_m": 0.4,
                "yaw_change_since_previous_deg": 10.0,
            },
            "route_memory": {},
            "vlm_action_kind": "right",
            "arbiter_proposal": {
                "desired_kind": "left",
                "desired_bearing_deg": bearing,
                "target_anchor_index": target,
            },
            "anchor_state_summary": {},
        },
        "historical_policy": {
            "override": True,
            "reason": "old_gate_allowed",
            "clear_path_available": True,
            "clear_path": False,
            "clear_path_source": "local_map",
            "min_clearance_m": 0.25,
        },
    }


class HintActionV2FeatureTest(unittest.TestCase):
    def test_circular_delta_handles_wraparound(self):
        self.assertAlmostEqual(circular_delta_deg(-179.0, 179.0), 2.0)

    def test_old_gate_is_not_a_model_feature(self):
        features = HintActionV2FeatureState().transform(row())
        self.assertFalse(
            any("override" in key or "reason" in key for key in features)
        )
        self.assertFalse(any("clear_path" in key for key in features))
        self.assertFalse(any("anchor_index" in key for key in features))

    def test_clearance_is_a_separate_runtime_gate(self):
        clearance = clearance_metadata(row())
        self.assertTrue(clearance["available"])
        self.assertFalse(clearance["clear"])
        self.assertEqual(clearance["source"], "local_map")

    def test_long_gap_resets_agreement(self):
        state = HintActionV2FeatureState()
        state.transform(row(step=75))
        features = state.transform(row(step=600, bearing=179.0, target=4))
        self.assertEqual(features["temporal.gap_reset"], 1.0)
        self.assertEqual(
            features["temporal.proposal.same_kind_streak"], 1.0
        )
