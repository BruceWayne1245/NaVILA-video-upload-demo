#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import random
import sys
from pathlib import Path

import numpy as np
import torch
from torch.utils.data import DataLoader

WORKSPACE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKSPACE))

from anchor_v3.dataset import ReplaySequenceDataset, collate_sequences  # noqa: E402
from anchor_v3.losses import anchor_v3_loss  # noqa: E402
from anchor_v3.model import AnchorV3  # noqa: E402
from anchor_v3.normalization import ScalarNormalizer  # noqa: E402


def batches(dataset: ReplaySequenceDataset, batch_size: int):
    return DataLoader(
        dataset, batch_size=batch_size, shuffle=True, collate_fn=collate_sequences
    )


def evaluate(model, loader, normalizer, device):
    model.eval()
    totals = {"total": 0.0, "action": 0.0, "pair": 0.0, "belief": 0.0, "confidence": 0.0, "consistency": 0.0}
    count = 0
    with torch.no_grad():
        for batch in loader:
            inputs = {key: value.to(device) for key, value in batch["input"].items()}
            target = {key: value.to(device) for key, value in batch["target"].items()}
            output = model(**normalizer.apply(inputs))
            loss = anchor_v3_loss(output, target)
            for key in totals:
                totals[key] += float(loss[key])
            count += 1
    return {key: value / max(count, 1) for key, value in totals.items()}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--train-shard", type=Path, nargs="+", required=True)
    parser.add_argument("--validation-shard", type=Path, nargs="+")
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--normalizer", type=Path, required=True)
    parser.add_argument("--epochs", type=int, default=5)
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--sequence-length", type=int, default=8)
    parser.add_argument("--device", default="cpu")
    args = parser.parse_args()
    random.seed(0)
    np.random.seed(0)
    torch.manual_seed(0)
    device = torch.device(args.device)
    train_dataset = ReplaySequenceDataset(args.train_shard, args.sequence_length)
    if len(train_dataset) == 0:
        raise ValueError("empty train dataset")
    train_loader = batches(train_dataset, args.batch_size)
    first = collate_sequences([train_dataset[0]])
    normalizer = ScalarNormalizer(first["input"]["candidate_scalar"].shape[-1])
    for batch in train_loader:
        normalizer.update(batch["input"])
    normalizer.finalize()
    args.normalizer.parent.mkdir(parents=True, exist_ok=True)
    normalizer.save(args.normalizer)
    model = AnchorV3(
        scalar_dim=first["input"]["candidate_scalar"].shape[-1],
        categorical_dim=first["input"]["candidate_categorical"].shape[-1],
    ).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=3e-4)
    validation_loader = None
    if args.validation_shard:
        validation_loader = batches(
            ReplaySequenceDataset(args.validation_shard, args.sequence_length), args.batch_size
        )
    history = []
    best = float("inf")
    for epoch in range(args.epochs):
        model.train()
        train_total = 0.0
        count = 0
        for batch in train_loader:
            inputs = {key: value.to(device) for key, value in batch["input"].items()}
            target = {key: value.to(device) for key, value in batch["target"].items()}
            optimizer.zero_grad(set_to_none=True)
            output = model(**normalizer.apply(inputs))
            loss = anchor_v3_loss(output, target)
            loss["total"].backward()
            optimizer.step()
            train_total += float(loss["total"].detach())
            count += 1
        metrics = {"train_total": train_total / max(count, 1)}
        if validation_loader is not None:
            metrics["validation"] = evaluate(model, validation_loader, normalizer, device)
            score = metrics["validation"]["total"]
        else:
            score = metrics["train_total"]
        history.append(metrics)
        if math.isfinite(score) and score < best:
            best = score
            args.checkpoint.parent.mkdir(parents=True, exist_ok=True)
            torch.save({
                "schema": "navila-anchor-v3-checkpoint-v0.1",
                "epoch": epoch,
                "model": model.state_dict(),
                "optimizer": optimizer.state_dict(),
                "normalizer": normalizer.state_dict(),
                "history": history,
            }, args.checkpoint)
    print(json.dumps({"epochs": args.epochs, "history": history, "checkpoint": str(args.checkpoint)}, indent=2))


if __name__ == "__main__":
    main()
