import types
import unittest
from unittest import mock

import numpy as np

import relocalization


class VisualPairTests(unittest.TestCase):
    def test_visual_pair_never_searches_outside_supplied_pair(self):
        calls = []

        def fake_feature(current, anchors, **kwargs):
            calls.append([a.index for a in anchors])
            return [types.SimpleNamespace(
                anchor_index=anchors[0].index,
                confidence=0.9,
                inlier_count=20,
            )]

        descriptor = {
            "rear_rgb": np.zeros((8, 8, 3), dtype=np.uint8),
            "rear_depth_obs": np.ones((8, 8), dtype=np.float32),
        }
        current = types.SimpleNamespace(index=9, descriptor=descriptor)
        next_anchor = types.SimpleNamespace(index=8, descriptor=descriptor)
        with mock.patch.object(relocalization, "feature_depth_anchor_relocalization", fake_feature):
            result = relocalization.visual_sequential_pair_relocalization(
                {"rgb": descriptor["rear_rgb"], "depth_obs": descriptor["rear_depth_obs"]},
                current,
                next_anchor,
            )
        self.assertEqual(calls, [[9], [8]])
        self.assertEqual([item.anchor_index for item in result], [9, 8])


    def test_visual_pair_requires_rear_rgbd(self):
        called = False

        def fake_feature(*args, **kwargs):
            nonlocal called
            called = True
            return []

        anchor = types.SimpleNamespace(index=1, descriptor={"rear_rgb": np.zeros((2, 2, 3))})
        with mock.patch.object(relocalization, "feature_depth_anchor_relocalization", fake_feature):
            result = relocalization.visual_sequential_pair_relocalization({}, anchor, None)
        self.assertEqual(result, [])
        self.assertFalse(called)


if __name__ == "__main__":
    unittest.main()
