import json
import tempfile
import types
import unittest

import numpy as np

from visual_ground_truth_monitor import VisualGroundTruthMonitor


class FakeTensor:
    def __init__(self, value):
        self.value = np.asarray(value, dtype=np.float32)

    def __getitem__(self, item):
        return FakeTensor(self.value[item])

    def detach(self):
        return self

    def cpu(self):
        return self

    def numpy(self):
        return self.value.copy()


class GroundTruthMonitorTests(unittest.TestCase):
    def test_records_truth_without_returning_it_to_controller(self):
        robot = types.SimpleNamespace(
            data=types.SimpleNamespace(root_state_w=FakeTensor([[0, 0, 0, 1, 0, 0, 0]]))
        )
        env = types.SimpleNamespace(
            unwrapped=types.SimpleNamespace(scene={"robot": robot})
        )
        descriptor = {
            "rear_rgb": np.zeros((2, 2, 3), dtype=np.uint8),
            "rear_depth_obs": np.ones((2, 2), dtype=np.float32),
        }
        anchor = types.SimpleNamespace(
            index=0,
            descriptor=descriptor,
            distance_from_start_m=0.0,
            route_remaining_to_start_m=0.0,
            metadata={"world_pose": [1, 0, 0, 1, 0, 0, 0]},
        )
        agent = types.SimpleNamespace(
            anchors=[anchor],
            _target_anchor_index=0,
            sequential_target_anchor_pair=lambda: (anchor, None),
        )
        progress = types.SimpleNamespace(
            target_anchor_index=0,
            bearing_to_anchor_deg=10.0,
            distance_to_anchor_m=1.25,
            distance_to_start_m=1.25,
            confidence=0.8,
        )
        with tempfile.TemporaryDirectory() as directory:
            monitor = VisualGroundTruthMonitor(directory, 4, "scene")
            result = monitor.record_step(
                step=1, phase="return", env=env, route_agent=agent,
                progress=progress, command=[0, 0, 0], output="stop",
            )
            monitor.close(agent)
            self.assertIsNone(result)
            with open(monitor.path, encoding="utf-8") as handle:
                rows = [json.loads(line) for line in handle]
            step = next(row for row in rows if row["event"] == "step")
            self.assertEqual(step["pair_ground_truth"][0]["bearing_deg"], 0.0)
            self.assertEqual(step["online_error_against_truth"]["bearing_error_deg"], 10.0)
            self.assertTrue(step["online_error_against_truth"]["distance_abs_error_m"] > 0)


if __name__ == "__main__":
    unittest.main()
