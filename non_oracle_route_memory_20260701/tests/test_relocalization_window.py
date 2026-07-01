import unittest
from dataclasses import dataclass

import numpy as np

from relocalization import feature_depth_anchor_relocalization


@dataclass
class DummyAnchor:
    index: int
    descriptor: object
    distance_from_start_m: float = 0.0
    route_remaining_to_start_m: float = 0.0


def _current_descriptor():
    return {
        "rgb": np.zeros((8, 8, 3), dtype=np.uint8),
        "depth_obs": np.ones((8, 8), dtype=np.float32),
    }


class RelocalizationWindowTest(unittest.TestCase):
    def test_default_searches_all_descriptor_anchors(self):
        anchors = [DummyAnchor(i, {}) for i in range(12)]
        diagnostics = {}

        feature_depth_anchor_relocalization(
            _current_descriptor(),
            anchors,
            diagnostics=diagnostics,
            matcher_backend="loftr",
            return_candidates=True,
        )

        self.assertEqual(diagnostics.get("candidate_anchors"), 12)

    def test_zero_searches_all_descriptor_anchors(self):
        anchors = [DummyAnchor(i, {}) for i in range(12)]
        diagnostics = {}

        feature_depth_anchor_relocalization(
            _current_descriptor(),
            anchors,
            max_candidates=0,
            diagnostics=diagnostics,
            matcher_backend="loftr",
            return_candidates=True,
        )

        self.assertEqual(diagnostics.get("candidate_anchors"), 12)

    def test_positive_window_limits_descriptor_anchors(self):
        anchors = [DummyAnchor(i, {}) for i in range(12)]
        diagnostics = {}

        feature_depth_anchor_relocalization(
            _current_descriptor(),
            anchors,
            max_candidates=3,
            diagnostics=diagnostics,
            matcher_backend="loftr",
            return_candidates=True,
        )

        self.assertEqual(diagnostics.get("candidate_anchors"), 3)


if __name__ == "__main__":
    unittest.main()
