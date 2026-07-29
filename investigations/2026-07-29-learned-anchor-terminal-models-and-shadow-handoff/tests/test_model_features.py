import importlib.util
import json
import sys
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "training" / "model_features.py"
SPEC = importlib.util.spec_from_file_location("model_features", MODULE_PATH)
module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


class FeatureTest(unittest.TestCase):
    def sample(self):
        return {
            "task": "anchor_state",
            "inputs": {
                "movement": {"translation_since_previous_m": 0.2},
                "route_memory": {
                    "distance_to_start_m": 5.0,
                    "estimate_role": "next",
                },
                "support": {
                    "current_anchor_index": 5,
                    "next_anchor_index": 4,
                    "mode": "normal",
                },
                "candidates": [
                    {
                        "anchor_index": 5,
                        "confidence": 0.8,
                        "estimated_distance_to_anchor_m": 0.3,
                        "v11": {"anchor_role": "current", "p_pose_bad": 0.1},
                    },
                    {
                        "anchor_index": 4,
                        "confidence": 0.9,
                        "estimated_distance_to_anchor_m": 0.8,
                        "v11": {"anchor_role": "next", "p_pose_bad": 0.2},
                    },
                ],
            },
            "labels": {"oracle_next_anchor_index": 3},
            "oracle_alignment": {"route_s_m": 4.2},
            "historical_policy": {"observed_next_anchor_index": 4},
        }

    def test_supervision_is_not_extracted(self):
        state = module.CausalFeatureState()
        features = state.transform(self.sample())
        module.assert_runtime_only(features)
        joined = " ".join(features)
        self.assertNotIn("oracle", joined)
        self.assertNotIn("label", joined)
        self.assertNotIn("historical", joined)

    def test_history_is_prior_only(self):
        state = module.CausalFeatureState()
        first = state.transform(self.sample())
        second_row = json.loads(json.dumps(self.sample()))
        second_row["inputs"]["route_memory"]["distance_to_start_m"] = 4.0
        second = state.transform(second_row)
        self.assertNotIn(
            "temporal.route_memory.distance_to_start_m.delta_previous", first
        )
        self.assertEqual(
            second["temporal.route_memory.distance_to_start_m.delta_previous"],
            -1.0,
        )
        self.assertEqual(
            second["temporal.route_memory.distance_to_start_m.w4.mean"],
            5.0,
        )


if __name__ == "__main__":
    unittest.main()
