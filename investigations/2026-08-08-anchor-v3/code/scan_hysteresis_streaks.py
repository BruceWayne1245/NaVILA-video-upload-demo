#!/usr/bin/env python3
"""Scans all held-out episodes (test + validation) for consecutive same-direction
KEEP<->PROMOTE misprediction streaks, and checks whether the streak coincides
with the true oracle_current_anchor being unchanged (the "hysteresis" pattern
found by hand in episodes 4 and 386)."""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import torch

WORKSPACE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKSPACE))

from anchor_v3.dataset import ReplaySequenceDataset, collate_sequences  # noqa: E402
from anchor_v3.model import ACTION_ORDER, AnchorV3  # noqa: E402
from anchor_v3.normalization import ScalarNormalizer  # noqa: E402

KEEP_IDX = ACTION_ORDER.index("keep")
PROMOTE_IDX = ACTION_ORDER.index("promote")
MIN_STREAK = 3


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", type=Path, default=WORKSPACE / "reports/anchor_v3_baseline_checkpoint.pt")
    parser.add_argument("--normalizer", type=Path, default=WORKSPACE / "reports/anchor_v3_baseline_normalizer.json")
    args = parser.parse_args()

    device = torch.device("cpu")
    shards = [WORKSPACE / "shards/formal_dataset/test.jsonl", WORKSPACE / "shards/formal_dataset/validation.jsonl"]
    dataset = ReplaySequenceDataset(shards, sequence_length=8)
    normalizer = ScalarNormalizer.load(args.normalizer)
    sample = collate_sequences([dataset[0]])
    model = AnchorV3(
        scalar_dim=sample["input"]["candidate_scalar"].shape[-1],
        categorical_dim=sample["input"]["candidate_categorical"].shape[-1],
    ).to(device)
    checkpoint = torch.load(args.checkpoint, map_location=device, weights_only=False)
    model.load_state_dict(checkpoint["model"])
    model.eval()

    # gather per-episode, chronologically ordered (step, true_action, pred_action, oracle_current_anchor)
    per_episode = defaultdict(list)
    with torch.no_grad():
        for index in range(len(dataset)):
            raw = dataset[index]
            batch = collate_sequences([raw])
            inputs = {key: value.to(device) for key, value in batch["input"].items()}
            target = {key: value.to(device) for key, value in batch["target"].items()}
            output = model(**normalizer.apply(inputs))
            action_pred = output["action_logits"].argmax(dim=-1)[0]
            action_true = target["action"][0]
            time_mask = target["time_mask"].bool()[0]
            for t, row in enumerate(dataset.sequences[index]):
                if not bool(time_mask[t]):
                    continue
                ep = row["physical_episode_id"]
                per_episode[ep].append((
                    row["step"],
                    ACTION_ORDER[int(action_true[t])],
                    ACTION_ORDER[int(action_pred[t])],
                    int(row["physical_route_oracle"]["oracle_current_anchor"]),
                ))

    total_episodes = len(per_episode)
    episodes_with_streak = 0
    all_streaks = []
    for ep, entries in per_episode.items():
        entries.sort(key=lambda e: e[0])
        i = 0
        n = len(entries)
        while i < n:
            step, true_a, pred_a, anchor = entries[i]
            is_confusion = {true_a, pred_a} == {"keep", "promote"} and true_a != pred_a
            if not is_confusion:
                i += 1
                continue
            direction = (true_a, pred_a)
            j = i
            while j < n and {entries[j][1], entries[j][2]} == {"keep", "promote"} and entries[j][1] != entries[j][2] and (entries[j][1], entries[j][2]) == direction:
                j += 1
            streak_len = j - i
            if streak_len >= MIN_STREAK:
                anchors_in_streak = {entries[k][3] for k in range(i, j)}
                all_streaks.append({
                    "episode": ep,
                    "length": streak_len,
                    "direction": f"{direction[0]}->{direction[1]}",
                    "start_step": entries[i][0],
                    "end_step": entries[j - 1][0],
                    "anchor_stable": len(anchors_in_streak) == 1,
                    "anchors_seen": sorted(anchors_in_streak),
                })
            i = j

    episodes_with_streak = len({s["episode"] for s in all_streaks})
    stable_streaks = [s for s in all_streaks if s["anchor_stable"]]

    print(f"episodes scanned (test+validation): {total_episodes}")
    print(f"episodes with >= {MIN_STREAK}-long same-direction keep<->promote streak: {episodes_with_streak}")
    print(f"total streaks found: {len(all_streaks)}")
    print(f"streaks where true oracle_current_anchor never changed (hysteresis-type): {len(stable_streaks)}/{len(all_streaks)}")
    print()
    for s in sorted(all_streaks, key=lambda s: -s["length"]):
        print(f"  ep={s['episode']:>5} len={s['length']:>2} {s['direction']:<14} steps {s['start_step']}-{s['end_step']} anchor_stable={s['anchor_stable']} anchors={s['anchors_seen']}")


if __name__ == "__main__":
    main()
