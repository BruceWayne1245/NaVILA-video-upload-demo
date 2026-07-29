import importlib.util
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TRAINING = ROOT / "training"
sys.path.insert(0, str(TRAINING))
MODULE_PATH = TRAINING / "hint_action_features.py"
SPEC = importlib.util.spec_from_file_location("hint_action_features", MODULE_PATH)
module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


class HintActionFeatureTest(unittest.TestCase):
    def sample(self):
        return {
            "task": "hint_action_decision",
            "inputs": {
                "movement": {"translation_since_previous_m": 0.2},
                "route_memory": {
                    "distance_to_start_m": 5.0,
                    "relocalization_confidence": 0.4,
                },
                "vlm_action_kind": "left",
                "arbiter_proposal": {
                    "desired_kind": "forward",
                    "desired_bearing_deg": 3.0,
                    "desired_distance_m": 0.8,
                },
                "anchor_state_summary": {
                    "support": {
                        "current_anchor_index": 5,
                        "next_anchor_index": 4,
                    },
                    "candidates": [
                        {
                            "anchor_index": 5,
                            "confidence": 0.8,
                            "v11": {
                                "anchor_role": "current",
                                "p_bearing_bad_30": 0.2,
                            },
                        },
                        {
                            "anchor_index": 4,
                            "confidence": 0.6,
                            "v11": {
                                "anchor_role": "next",
                                "p_bearing_bad_30": 0.4,
                            },
                        },
                    ],
                },
            },
            "labels": {
                "decision": "override_hint",
                "oracle_direction_kind": "forward",
            },
            "historical_policy": {
                "override": False,
                "reason": "low_relocalization_confidence",
            },
        }

    def test_features_exclude_oracle_and_old_gate(self):
        state = module.HintActionCausalFeatureState()
        features = state.transform(self.sample())
        joined = " ".join(features).lower()
        self.assertNotIn("oracle", joined)
        self.assertNotIn("historical", joined)
        self.assertNotIn("reason", joined)
        self.assertIn("vlm.action_kind=left", features)

    def test_history_is_causal(self):
        state = module.HintActionCausalFeatureState()
        first = state.transform(self.sample())
        second_row = json.loads(json.dumps(self.sample()))
        second_row["inputs"]["arbiter_proposal"]["desired_bearing_deg"] = 8.0
        second = state.transform(second_row)
        key = "temporal.proposal.desired_bearing_deg.delta_previous"
        self.assertNotIn(key, first)
        self.assertEqual(second[key], 5.0)


if __name__ == "__main__":
    unittest.main()
