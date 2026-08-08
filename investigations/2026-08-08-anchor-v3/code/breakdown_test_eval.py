#!/usr/bin/env python3
"""Per-teacher_stream / per-action-class breakdown of a checkpoint's test-split
performance, plus a majority-class baseline for context. Read-only analysis;
does not modify any runtime process."""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import torch

WORKSPACE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKSPACE))

from anchor_v3.dataset import ReplaySequenceDataset, collate_sequences  # noqa: E402
from anchor_v3.model import ACTION_ORDER, AnchorV3  # noqa: E402
from anchor_v3.normalization import ScalarNormalizer  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--test-shard", type=Path, nargs="+", required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--normalizer", type=Path, required=True)
    parser.add_argument("--sequence-length", type=int, default=8)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    device = torch.device(args.device)
    dataset = ReplaySequenceDataset(args.test_shard, args.sequence_length)
    normalizer = ScalarNormalizer.load(args.normalizer)
    sample = collate_sequences([dataset[0]])
    model = AnchorV3(
        scalar_dim=sample["input"]["candidate_scalar"].shape[-1],
        categorical_dim=sample["input"]["candidate_categorical"].shape[-1],
    ).to(device)
    checkpoint = torch.load(args.checkpoint, map_location=device, weights_only=False)
    model.load_state_dict(checkpoint["model"])
    model.eval()

    stream_action = defaultdict(lambda: {"correct": 0, "total": 0})
    stream_pair = defaultdict(lambda: {"correct": 0, "total": 0})
    stream_belief = defaultdict(lambda: {"correct": 0, "total": 0})
    action_class_recall = defaultdict(lambda: {"correct": 0, "total": 0})
    confusion = Counter()
    true_action_counts = Counter()
    predicted_action_counts = Counter()

    with torch.no_grad():
        for index in range(len(dataset)):
            raw = dataset[index]
            batch = collate_sequences([raw])
            inputs = {key: value.to(device) for key, value in batch["input"].items()}
            target = {key: value.to(device) for key, value in batch["target"].items()}
            output = model(**normalizer.apply(inputs))
            candidates = output["pair_logits"].shape[-1]

            action_pred = output["action_logits"].argmax(dim=-1)[0]
            action_true = target["action"][0]
            time_mask = target["time_mask"].bool()[0]

            flat_pair = output["pair_logits"].reshape(*output["pair_logits"].shape[:2], candidates * candidates)
            pair_pred_flat = flat_pair.argmax(dim=-1)[0]
            pred_current = pair_pred_flat // candidates
            pred_next = pair_pred_flat % candidates
            pair_valid = (time_mask & target["pair_mask"].bool()[0])
            pair_hit = (
                (pred_current == target["current_position"][0])
                & (pred_next == target["next_position"][0])
            )

            belief_pred = output["belief_logits"].argmax(dim=-1)[0]
            belief_true = target["belief"][0].argmax(dim=-1)
            belief_valid = time_mask & target["belief_mask"].bool()[0]
            belief_hit = belief_pred == belief_true

            for t, frame in enumerate(raw):
                if not bool(time_mask[t]):
                    continue
                stream = frame["target"]["teacher_stream"]
                true_cls = ACTION_ORDER[int(action_true[t])]
                pred_cls = ACTION_ORDER[int(action_pred[t])]
                hit = pred_cls == true_cls

                stream_action[stream]["total"] += 1
                stream_action[stream]["correct"] += int(hit)
                action_class_recall[true_cls]["total"] += 1
                action_class_recall[true_cls]["correct"] += int(hit)
                confusion[(true_cls, pred_cls)] += 1
                true_action_counts[true_cls] += 1
                predicted_action_counts[pred_cls] += 1

                if bool(pair_valid[t]):
                    stream_pair[stream]["total"] += 1
                    stream_pair[stream]["correct"] += int(pair_hit[t])
                if bool(belief_valid[t]):
                    stream_belief[stream]["total"] += 1
                    stream_belief[stream]["correct"] += int(belief_hit[t])

    def rate(d):
        return {k: v["correct"] / max(v["total"], 1) for k, v in d.items()}

    def with_counts(d):
        return {k: {"accuracy": v["correct"] / max(v["total"], 1), "n": v["total"]} for k, v in d.items()}

    majority_class = true_action_counts.most_common(1)[0]
    majority_baseline_accuracy = majority_class[1] / sum(true_action_counts.values())

    result = {
        "checkpoint": str(args.checkpoint),
        "checkpoint_epoch": checkpoint.get("epoch"),
        "action_accuracy_by_teacher_stream": with_counts(stream_action),
        "pair_exact_match_by_teacher_stream": with_counts(stream_pair),
        "belief_top1_by_teacher_stream": with_counts(stream_belief),
        "action_recall_by_true_class": with_counts(action_class_recall),
        "true_action_class_distribution": dict(true_action_counts),
        "predicted_action_class_distribution": dict(predicted_action_counts),
        "majority_class_baseline": {
            "class": majority_class[0],
            "accuracy_if_always_predicted": majority_baseline_accuracy,
        },
        "confusion_matrix_true_pred_counts": {f"{t}->{p}": c for (t, p), c in confusion.items()},
    }

    text = json.dumps(result, indent=2)
    print(text)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
