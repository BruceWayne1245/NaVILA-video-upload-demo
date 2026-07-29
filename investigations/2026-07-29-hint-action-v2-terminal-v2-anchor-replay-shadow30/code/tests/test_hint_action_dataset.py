import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))
MODULE_PATH = TOOLS / "build_hint_action_dataset.py"
SPEC = importlib.util.spec_from_file_location("hint_builder", MODULE_PATH)
builder = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = builder
SPEC.loader.exec_module(builder)


class HintActionLabelTest(unittest.TestCase):
    def test_counterfactual_labels_do_not_copy_gate(self):
        self.assertEqual(
            builder.label_for_choices("left", "forward", "forward"),
            "override_hint",
        )
        self.assertEqual(
            builder.label_for_choices("left", "forward", "left"),
            "keep_vlm",
        )
        self.assertEqual(
            builder.label_for_choices("left", "forward", "right"),
            "abstain",
        )

    def test_body_frame_bearing_convention(self):
        left = builder.body_frame_bearing_deg(
            [0.0, 0.0], 0.0, [0.0, 1.0]
        )
        right_after_quarter_turn = builder.body_frame_bearing_deg(
            [0.0, 0.0], 1.5707963267948966, [1.0, 0.0]
        )
        self.assertAlmostEqual(left, 90.0)
        self.assertAlmostEqual(right_after_quarter_turn, -90.0)

    def test_stop_is_outside_direction_model(self):
        self.assertEqual(builder.action_kind("The next action is stop."), "stop")

    def test_conflict_logic_matches_arbiter(self):
        self.assertTrue(builder.conflicts("left", "forward", 0.0))
        self.assertFalse(builder.conflicts("forward", "left", 25.0))
        self.assertTrue(builder.conflicts("forward", "left", 35.0))


if __name__ == "__main__":
    unittest.main()
