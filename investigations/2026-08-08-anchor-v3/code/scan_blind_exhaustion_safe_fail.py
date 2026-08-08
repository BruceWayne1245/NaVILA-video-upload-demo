#!/usr/bin/env python3
"""Finds real historical episodes that ended in stop_gate SAFE_FAIL, classifies
why (blind-budget exhaustion specifically vs other reasons), and cross-references
against the Anchor V3 replay dataset's train/validation/test episode coverage.
Read-only: does not touch any runtime process."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

WORKSPACE = Path("/home/teambruce/anchor-v3-20260808")
CATALOG = WORKSPACE / "manifests/historical_compatibility_catalog.json"


def episode_ids_in_shard(path: Path) -> set[int]:
    ids = set()
    with path.open() as f:
        for line in f:
            ids.add(int(json.loads(line)["physical_episode_id"]))
    return ids


def main() -> None:
    catalog = json.loads(CATALOG.read_text())
    episodes = catalog["episodes"]

    safe_fail = [e for e in episodes if e["outcome"].get("return_terminal_safe_fail") is True]
    print(f"total episode directories in catalog: {len(episodes)}")
    print(f"directories with outcome.return_terminal_safe_fail == True: {len(safe_fail)}")

    train_ids = episode_ids_in_shard(WORKSPACE / "shards/formal_dataset/train.jsonl")
    val_ids = episode_ids_in_shard(WORKSPACE / "shards/formal_dataset/validation.jsonl")
    test_ids = episode_ids_in_shard(WORKSPACE / "shards/formal_dataset/test.jsonl")
    all_anchor_v3_ids = train_ids | val_ids | test_ids

    reason_counts = Counter()
    max_blind_counts = Counter()
    covered = []
    uncovered = []

    for ep in safe_fail:
        traj_dir = Path(ep["path"]) / "trajectories"
        traj_files = sorted(traj_dir.glob("*.jsonl")) if traj_dir.exists() else []
        if not traj_files:
            reason_counts["no_trajectory_file"] += 1
            continue
        traj_file = traj_files[-1]
        try:
            with traj_file.open() as f:
                lines = f.readlines()
        except OSError:
            reason_counts["trajectory_unreadable"] += 1
            continue
        if not lines:
            reason_counts["empty_trajectory"] += 1
            continue

        # scan the tail for the terminal stop_gate record and the max blind_query_count seen
        max_blind = 0
        terminal_gate = None
        for line in reversed(lines[-500:]):
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            gate = row.get("stop_gate")
            if not gate:
                continue
            max_blind = max(max_blind, int(gate.get("gate_blind_query_count", 0) or 0))
            if terminal_gate is None and gate.get("gate_decision") == "safe_fail":
                terminal_gate = gate

        pid = int(ep["physical_episode_id"])
        reason = terminal_gate["gate_reason"] if terminal_gate else "no_safe_fail_gate_record_found_in_tail"
        reason_counts[reason] += 1
        max_blind_counts[max_blind] += 1

        record = {
            "physical_episode_id": pid,
            "episode_directory": ep["episode_directory"],
            "gate_reason": reason,
            "max_blind_query_count_seen": max_blind,
            "in_anchor_v3_dataset": pid in all_anchor_v3_ids,
            "anchor_v3_split": (
                "train" if pid in train_ids else
                "validation" if pid in val_ids else
                "test" if pid in test_ids else None
            ),
        }
        if pid in all_anchor_v3_ids:
            covered.append(record)
        else:
            uncovered.append(record)

    print(f"\nreason breakdown (terminal gate_reason at safe_fail):")
    for reason, count in reason_counts.most_common():
        print(f"  {reason}: {count}")

    print(f"\nmax gate_blind_query_count distribution among safe_fail episodes:")
    for count, n in sorted(max_blind_counts.items()):
        print(f"  blind_count={count}: {n} episodes")

    blind_exhaustion = [r for r in covered + uncovered if r["gate_reason"] == "blind_probe_budget_exhausted_without_terminal_evidence"]
    print(f"\nblind-budget-exhaustion safe_fail episodes: {len(blind_exhaustion)} total")
    print(f"  covered by Anchor V3 dataset: {sum(1 for r in blind_exhaustion if r['in_anchor_v3_dataset'])}")
    print(f"  NOT covered (unique physical_episode_ids, dedup):")
    ids_seen = set()
    for r in blind_exhaustion:
        if r["in_anchor_v3_dataset"] and r["physical_episode_id"] not in ids_seen:
            ids_seen.add(r["physical_episode_id"])
            print(f"    ep={r['physical_episode_id']:>5} split={r['anchor_v3_split']:<10} dir={r['episode_directory']}")

    out = WORKSPACE / "reports/blind_exhaustion_safe_fail_scan.json"
    out.write_text(json.dumps({
        "total_catalog_directories": len(episodes),
        "total_safe_fail_directories": len(safe_fail),
        "reason_breakdown": dict(reason_counts),
        "max_blind_query_count_distribution": {str(k): v for k, v in max_blind_counts.items()},
        "blind_exhaustion_episodes": blind_exhaustion,
    }, indent=2))
    print(f"\nfull results written to {out}")


if __name__ == "__main__":
    main()
