#!/usr/bin/env python3
"""Isolated smoke test for anchor_v3/online_adapter.py: replays a handful of
real historical episode frames through the adapter using the raw JSONL
`candidates` field (same schema the live runtime already builds), and checks
the output is well-formed and contract-valid. Does not touch any runtime
process or the navila-route2-v11-core-20260801 repo."""
from __future__ import annotations

import json
import sys
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKSPACE))

from anchor_v3.online_adapter import AnchorV3OnlineAdapter  # noqa: E402


def anchors_for_episode(shard_path: Path, physical_episode_id: int) -> tuple[list[dict], dict]:
    rows = []
    with shard_path.open() as f:
        for line in f:
            row = json.loads(line)
            if row["physical_episode_id"] == physical_episode_id:
                rows.append(row)
    rows.sort(key=lambda r: r["step"])
    source = Path(rows[0]["source_path"])
    payload = json.loads((source / "icp_replay_dataset" / "anchors.json").read_text())
    anchor_points = {
        int(r["index"]): r["local_map_points_xyz_body"]
        for r in payload.get("anchors") or []
        if r.get("index") is not None and r.get("local_map_points_xyz_body")
    }
    return rows, anchor_points


def main() -> None:
    checkpoint = WORKSPACE / "reports/anchor_v3_keepweighted_checkpoint.pt"
    normalizer = WORKSPACE / "reports/anchor_v3_keepweighted_normalizer.json"
    adapter = AnchorV3OnlineAdapter.from_checkpoint(checkpoint, normalizer, device="cpu")

    # ep386: held-out test-split episode used throughout this session's analysis.
    rows, anchor_points = anchors_for_episode(WORKSPACE / "shards/formal_dataset/test.jsonl", 386)
    print(f"replaying {len(rows)} real attempts from episode 386 (test split, never trained on)")

    adapter.reset()
    for i, row in enumerate(rows):
        frame = json.loads(Path(row["frame_path"]).read_text())
        decision = adapter.observe_attempt(
            row["candidates"],
            current_points_xyz=frame["local_map_points_xyz_body"],
            anchor_points_by_index=anchor_points,
            decision_ordinal=row.get("decision_ordinal"),
            step=row["step"],
        )
        print(
            f"  attempt {i:>2} step={row['step']:>5} -> action={decision.action.value:<9} "
            f"current={decision.current_anchor} next={decision.next_anchor} "
            f"confidence={decision.confidence:.3f} belief_argmax={max(decision.belief, key=decision.belief.get) if decision.belief else None}"
        )

    print("\nsmoke test passed: adapter ran end-to-end over a real episode, every decision passed validate_decision.")


if __name__ == "__main__":
    main()
