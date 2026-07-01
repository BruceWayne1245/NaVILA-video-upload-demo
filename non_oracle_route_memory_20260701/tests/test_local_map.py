import unittest

import numpy as np

from local_map import LocalMapClearPathConfig, local_map_clear_path


class LocalMapTests(unittest.TestCase):
    def test_point_cloud_blocks_hint_corridor(self):
        descriptor = {
            "local_map_points_body": np.asarray(
                [
                    [0.60, 0.02, 0.40],
                    [0.80, 0.80, 0.40],
                ],
                dtype=np.float32,
            )
        }

        result = local_map_clear_path(
            descriptor,
            target_dx_m=1.0,
            target_dy_m=0.0,
            cfg=LocalMapClearPathConfig(robot_radius_m=0.10, clearance_margin_m=0.05),
        )

        self.assertTrue(result.available)
        self.assertFalse(result.clear)
        self.assertEqual(result.reason, "occupied_in_local_map_path")

    def test_ground_height_points_do_not_block(self):
        descriptor = {
            "local_map_points_body": np.asarray(
                [
                    [0.60, 0.02, -0.45],
                    [0.80, 0.80, 0.40],
                ],
                dtype=np.float32,
            )
        }

        result = local_map_clear_path(
            descriptor,
            target_dx_m=1.0,
            target_dy_m=0.0,
            cfg=LocalMapClearPathConfig(robot_radius_m=0.10, clearance_margin_m=0.05),
        )

        self.assertTrue(result.available)
        self.assertTrue(result.clear)


if __name__ == "__main__":
    unittest.main()
