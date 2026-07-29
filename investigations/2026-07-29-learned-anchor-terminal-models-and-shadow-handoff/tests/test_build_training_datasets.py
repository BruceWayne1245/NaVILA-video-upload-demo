import importlib.util
import sys
import unittest
from pathlib import Path


MODULE_PATH = (
    Path(__file__).resolve().parents[1] / "tools" / "build_training_datasets.py"
)
SPEC = importlib.util.spec_from_file_location("builder", MODULE_PATH)
builder = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = builder
SPEC.loader.exec_module(builder)


def anchor(index, x, y, route_s):
    return {
        "index": index,
        "world_pose": [x, y],
        "distance_from_start_m": route_s,
    }


def row(step, x, y):
    return {"step": step, "position": [x, y], "yaw_deg": 0.0}


class RouteLabelTest(unittest.TestCase):
    def test_route_distance_is_not_euclidean_a0_radius(self):
        anchors = [
            anchor(0, 0.0, 0.0, 0.0),
            anchor(1, 1.0, 0.0, 1.0),
            anchor(2, 0.2, 0.1, 2.0),
            anchor(3, 1.2, 0.1, 3.0),
        ]
        rows = [row(1, 1.2, 0.1), row(2, 0.2, 0.1)]
        alignment = builder.align_route_viterbi(rows, anchors)
        labels = builder.oracle_labels(rows[-1], alignment[2], anchors)
        self.assertGreater(labels["oracle_route_distance_to_a0_m"], 1.0)

    def test_terminal_boundaries_match_stop_interval(self):
        self.assertEqual(builder.terminal_action_label("arrived", True), "accept")
        self.assertEqual(builder.terminal_action_label("boundary", True), "verify")
        self.assertEqual(builder.terminal_action_label("far", True), "reject")
        self.assertEqual(
            builder.terminal_action_label("arrived", False),
            "arrived_without_stop",
        )

    def test_scene_splits_are_disjoint_and_stable(self):
        scenes = ["scene-a", "scene-b", "scene-c", "scene-d"]
        first = builder.stable_scene_splits(scenes)
        second = builder.stable_scene_splits(reversed(scenes))
        self.assertEqual(first, second)
        self.assertEqual(set(first), set(scenes))
        self.assertEqual(set(first.values()), {"train", "validation", "test"})

    def test_viterbi_alignment_tracks_progress_on_straight_route(self):
        anchors = [
            anchor(0, 0.0, 0.0, 0.0),
            anchor(1, 1.0, 0.0, 1.0),
            anchor(2, 2.0, 0.0, 2.0),
            anchor(3, 3.0, 0.0, 3.0),
        ]
        rows = [
            row(1, 2.9, 0.0),
            row(2, 2.1, 0.0),
            row(3, 1.1, 0.0),
            row(4, 0.2, 0.0),
        ]
        alignment = builder.align_route_viterbi(rows, anchors)
        route_s = [alignment[index]["route_s_m"] for index in range(1, 5)]
        self.assertGreater(route_s[0], route_s[-1])
        self.assertTrue(all(a >= b for a, b in zip(route_s, route_s[1:])))


if __name__ == "__main__":
    unittest.main()
