import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TRAINING = ROOT / "training"
sys.path.insert(0, str(TRAINING))
MODULE_PATH = TRAINING / "terminal_v2_features.py"
SPEC = importlib.util.spec_from_file_location("terminal_v2_features", MODULE_PATH)
module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


class TerminalV2FeatureTest(unittest.TestCase):
    def sample(self):
        return {
            "task": "terminal_decision",
            "inputs": {
                "movement": {"translation_since_previous_m": 0.1},
                "route_memory": {
                    "distance_to_start_m": 4.2,
                    "target_anchor_index": 8,
                    "evidence_age_updates": 2,
                },
                "vlm_requested_stop": False,
                "a0_visual": {"available": True, "confirmed": False},
                "anchor_state_summary": {
                    "support": {
                        "current_anchor_index": 9,
                        "next_anchor_index": 8,
                    },
                    "candidates": [
                        {
                            "anchor_index": 9,
                            "confidence": 0.7,
                            "estimated_distance_to_anchor_m": 0.5,
                            "v11": {"anchor_role": "current"},
                        },
                        {
                            "anchor_index": 8,
                            "confidence": 0.8,
                            "estimated_distance_to_anchor_m": 1.0,
                            "v11": {"anchor_role": "next"},
                        },
                    ],
                },
            },
        }

    def test_absolute_indices_are_removed(self):
        features = module.TerminalV2FeatureState().transform(self.sample())
        self.assertFalse(
            any("anchor_index" in key for key in features),
            list(features)[:20],
        )
        self.assertIn("route_memory.distance_to_start_m", features)
        self.assertIn("state.support_gap", features)


if __name__ == "__main__":
    unittest.main()
