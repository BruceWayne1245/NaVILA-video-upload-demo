import importlib.util
import sys
import unittest
from pathlib import Path


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "tools"
    / "replay_wider_anchor_candidates.py"
)
SPEC = importlib.util.spec_from_file_location("wider_replay", MODULE_PATH)
module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


class WiderReplayTest(unittest.TestCase):
    def row(self):
        return {
            "inputs": {
                "support": {"current_anchor_index": 5},
                "candidates": [
                    {"anchor_index": 5},
                    {"anchor_index": 4},
                    {"anchor_index": 1},
                ],
            }
        }

    def test_neighborhood_is_runtime_derived(self):
        indices = module.replay_indices(
            self.row(), {0, 1, 2, 3, 4, 5, 6}
        )
        self.assertEqual(indices, [6, 5, 4, 3, 1])

    def test_oracle_is_not_implicitly_injected(self):
        row = self.row()
        row["labels"] = {"oracle_next_anchor_index": 2}
        indices = module.replay_indices(row, {0, 1, 2, 3, 4, 5, 6})
        self.assertNotIn(2, indices)

    def test_episode_shards_are_disjoint_and_complete(self):
        keys = ["ep5", "ep1", "ep4", "ep2", "ep3"]
        shards = [module.select_shard(keys, 3, index) for index in range(3)]
        flattened = [key for shard in shards for key in shard]
        self.assertEqual(sorted(flattened), sorted(keys))
        self.assertEqual(len(flattened), len(set(flattened)))


if __name__ == "__main__":
    unittest.main()
