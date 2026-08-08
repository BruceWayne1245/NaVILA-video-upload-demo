#!/usr/bin/env python3
"""Scene-disjoint offline evaluation of an Anchor V3 checkpoint on a held-out shard.

Computes the same multi-task loss decomposition used during training plus
label-grounded accuracy metrics (action, pair, belief, confidence). Does not
touch any NaVILA runtime process, evaluator episode, or queue.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import torch

WORKSPACE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKSPACE))

from anchor_v3.dataset import ReplaySequenceDataset, collate_sequences  # noqa: E402
from anchor_v3.losses import anchor_v3_loss  # noqa: E402
from anchor_v3.model import AnchorV3  # noqa: E402
from anchor_v3.normalization import ScalarNormalizer  # noqa: E402


def evaluate(model, dataset, normalizer, device) -> dict:
    loss_totals = {"total": 0.0, "action": 0.0, "pair": 0.0, "belief": 0.0, "confidence": 0.0}
    sequence_count = 0

    action_correct = action_total = 0
    pair_correct = pair_adjacent = pair_total = 0
    belief_correct = belief_total = 0
    confidence_sq_error = 0.0
    confidence_correct = confidence_total = 0

    model.eval()
    with torch.no_grad():
        for index in range(len(dataset)):
            batch = collate_sequences([dataset[index]])
            inputs = {key: value.to(device) for key, value in batch["input"].items()}
            target = {key: value.to(device) for key, value in batch["target"].items()}
            output = model(**normalizer.apply(inputs))
            loss = anchor_v3_loss(output, target)
            for key in loss_totals:
                loss_totals[key] += float(loss[key])
            sequence_count += 1

            time_mask = target["time_mask"].bool()
            candidates = output["pair_logits"].shape[-1]

            action_pred = output["action_logits"].argmax(dim=-1)
            action_hit = (action_pred == target["action"]) & time_mask
            action_correct += int(action_hit.sum())
            action_total += int(time_mask.sum())

            pair_valid = time_mask & target["pair_mask"].bool()
            if pair_valid.any():
                flat_pair = output["pair_logits"].reshape(*output["pair_logits"].shape[:2], candidates * candidates)
                pair_pred_flat = flat_pair.argmax(dim=-1)
                pred_current = pair_pred_flat // candidates
                pred_next = pair_pred_flat % candidates
                pair_hit = (
                    (pred_current == target["current_position"])
                    & (pred_next == target["next_position"])
                    & pair_valid
                )
                pair_correct += int(pair_hit.sum())
                indices = inputs["candidate_indices"]
                gathered_current = torch.gather(indices, 2, pred_current.clamp_min(0).unsqueeze(-1)).squeeze(-1)
                gathered_next = torch.gather(indices, 2, pred_next.clamp_min(0).unsqueeze(-1)).squeeze(-1)
                adjacent = (gathered_current - gathered_next).abs() <= 1
                pair_adjacent += int((adjacent & pair_valid).sum())
                pair_total += int(pair_valid.sum())

            belief_valid = time_mask & target["belief_mask"].bool()
            if belief_valid.any():
                belief_pred = output["belief_logits"].argmax(dim=-1)
                belief_target_index = target["belief"].argmax(dim=-1)
                belief_hit = (belief_pred == belief_target_index) & belief_valid
                belief_correct += int(belief_hit.sum())
                belief_total += int(belief_valid.sum())

            confidence_pred = output["confidence"][time_mask]
            confidence_target = target["confidence"][time_mask]
            confidence_sq_error += float(((confidence_pred - confidence_target) ** 2).sum())
            confidence_correct += int(((confidence_pred >= 0.5) == (confidence_target >= 0.5)).sum())
            confidence_total += int(time_mask.sum())

    result = {
        "sequences": sequence_count,
        "loss": {key: value / max(sequence_count, 1) for key, value in loss_totals.items()},
        "action_accuracy": action_correct / max(action_total, 1),
        "action_frames": action_total,
        "pair_exact_match_accuracy": pair_correct / max(pair_total, 1),
        "pair_adjacency_compliance": pair_adjacent / max(pair_total, 1),
        "pair_frames": pair_total,
        "belief_top1_accuracy": belief_correct / max(belief_total, 1),
        "belief_frames": belief_total,
        "confidence_brier_score": confidence_sq_error / max(confidence_total, 1),
        "confidence_threshold_accuracy": confidence_correct / max(confidence_total, 1),
        "confidence_frames": confidence_total,
    }
    return result


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
    if len(dataset) == 0:
        raise ValueError("empty test dataset")

    normalizer = ScalarNormalizer.load(args.normalizer)
    sample = collate_sequences([dataset[0]])
    model = AnchorV3(
        scalar_dim=sample["input"]["candidate_scalar"].shape[-1],
        categorical_dim=sample["input"]["candidate_categorical"].shape[-1],
    ).to(device)
    checkpoint = torch.load(args.checkpoint, map_location=device, weights_only=False)
    model.load_state_dict(checkpoint["model"])

    result = evaluate(model, dataset, normalizer, device)
    result["checkpoint"] = str(args.checkpoint)
    result["checkpoint_epoch"] = checkpoint.get("epoch")
    result["test_shard"] = [str(p) for p in args.test_shard]

    text = json.dumps(result, indent=2)
    print(text)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
