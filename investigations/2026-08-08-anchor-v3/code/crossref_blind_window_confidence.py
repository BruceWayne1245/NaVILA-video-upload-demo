#!/usr/bin/env python3
"""For each of the 67 real historical blind-exhaustion safe_fail episodes, finds
the TERMINAL_BLIND step window in the trajectory log, checks how many Anchor V3
replay frames fall inside it, and runs the (best) checkpoint to see what belief/
confidence the model would have reported during that window versus the rest of
the same episode. Read-only; no runtime process touched."""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

import torch

WORKSPACE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKSPACE))

from anchor_v3.dataset import ReplaySequenceDataset, collate_sequences  # noqa: E402
from anchor_v3.model import AnchorV3  # noqa: E402
from anchor_v3.normalization import ScalarNormalizer  # noqa: E402

SCAN_RESULT = WORKSPACE / "reports/blind_exhaustion_safe_fail_scan.json"
CHECKPOINT = WORKSPACE / "reports/anchor_v3_keepweighted_checkpoint.pt"
NORMALIZER = WORKSPACE / "reports/anchor_v3_keepweighted_normalizer.json"


def blind_window(path: Path) -> tuple[int, int] | None:
    traj_dir = path / "trajectories"
    traj_files = sorted(traj_dir.glob("*.jsonl")) if traj_dir.exists() else []
    if not traj_files:
        return None
    steps = []
    with traj_files[-1].open() as f:
        for line in f:
            row = json.loads(line)
            gate = row.get("stop_gate")
            if gate and gate.get("gate_state") == "terminal_blind":
                steps.append(int(row["step"]))
    if not steps:
        return None
    return min(steps), max(steps)


def main() -> None:
    scan = json.loads(SCAN_RESULT.read_text())
    blind_episodes = scan["blind_exhaustion_episodes"]

    device = torch.device("cpu")
    shards = {
        "train": WORKSPACE / "shards/formal_dataset/train.jsonl",
        "validation": WORKSPACE / "shards/formal_dataset/validation.jsonl",
        "test": WORKSPACE / "shards/formal_dataset/test.jsonl",
    }
    dataset = ReplaySequenceDataset(list(shards.values()), sequence_length=8)
    normalizer = ScalarNormalizer.load(NORMALIZER)
    sample = collate_sequences([dataset[0]])
    model = AnchorV3(
        scalar_dim=sample["input"]["candidate_scalar"].shape[-1],
        categorical_dim=sample["input"]["candidate_categorical"].shape[-1],
    ).to(device)
    checkpoint = torch.load(CHECKPOINT, map_location=device, weights_only=False)
    model.load_state_dict(checkpoint["model"])
    model.eval()

    # per-episode: list of (step, confidence_pred, confidence_target, belief_max_prob)
    per_ep_preds = defaultdict(list)
    with torch.no_grad():
        for index in range(len(dataset)):
            raw = dataset[index]
            batch = collate_sequences([raw])
            inputs = {key: value.to(device) for key, value in batch["input"].items()}
            target = {key: value.to(device) for key, value in batch["target"].items()}
            output = model(**normalizer.apply(inputs))
            time_mask = target["time_mask"].bool()[0]
            confidence_pred = output["confidence"][0]
            confidence_target = target["confidence"][0]
            belief_probs = torch.softmax(output["belief_logits"], dim=-1)[0]
            belief_max = belief_probs.max(dim=-1).values
            for t, row in enumerate(dataset.sequences[index]):
                if not bool(time_mask[t]):
                    continue
                ep = row["physical_episode_id"]
                per_ep_preds[ep].append((
                    row["step"],
                    float(confidence_pred[t]),
                    float(confidence_target[t]),
                    float(belief_max[t]),
                ))

    seen_ids = set()
    results = []
    for rec in blind_episodes:
        pid = rec["physical_episode_id"]
        if pid in seen_ids:
            continue
        seen_ids.add(pid)
        results.append(rec)

    # episode_directory in the scan is just a basename; recover full path from the catalog
    catalog = json.loads((WORKSPACE / "manifests/historical_compatibility_catalog.json").read_text())
    dir_to_path = {e["episode_directory"]: e["path"] for e in catalog["episodes"]}

    print(f"{'ep':>6} {'split':<10} {'blind_window':<16} {'v3_frames_total':>15} {'v3_frames_in_window':>19} {'conf_in_window':>14} {'conf_outside':>13} {'belief_in_window':>16}")
    covered_count = 0
    summary_rows = []
    for rec in results:
        pid = rec["physical_episode_id"]
        path = Path(dir_to_path.get(rec["episode_directory"], ""))
        window = blind_window(path) if path.exists() else None
        preds = sorted(per_ep_preds.get(pid, []))
        total_frames = len(preds)
        if window is None or total_frames == 0:
            print(f"{pid:>6} {rec['anchor_v3_split'] or '?':<10} {'N/A':<16} {total_frames:>15} {0:>19} {'-':>14} {'-':>13} {'-':>16}")
            continue
        lo, hi = window
        in_window = [p for p in preds if lo <= p[0] <= hi]
        outside = [p for p in preds if not (lo <= p[0] <= hi)]
        if in_window:
            covered_count += 1
        conf_in = sum(p[1] for p in in_window) / len(in_window) if in_window else None
        conf_out = sum(p[1] for p in outside) / len(outside) if outside else None
        belief_in = sum(p[3] for p in in_window) / len(in_window) if in_window else None
        print(f"{pid:>6} {rec['anchor_v3_split'] or '?':<10} {str(window):<16} {total_frames:>15} {len(in_window):>19} "
              f"{(f'{conf_in:.3f}' if conf_in is not None else '-'):>14} "
              f"{(f'{conf_out:.3f}' if conf_out is not None else '-'):>13} "
              f"{(f'{belief_in:.3f}' if belief_in is not None else '-'):>16}")
        summary_rows.append({
            "physical_episode_id": pid, "split": rec["anchor_v3_split"], "blind_window": window,
            "v3_frames_total": total_frames, "v3_frames_in_window": len(in_window),
            "confidence_in_window_mean": conf_in, "confidence_outside_mean": conf_out,
            "belief_max_prob_in_window_mean": belief_in,
        })

    print(f"\n{covered_count}/{len(results)} unique blind-exhaustion episodes have >=1 Anchor V3 frame inside the real TERMINAL_BLIND window")
    out = WORKSPACE / "reports/blind_window_confidence_crossref.json"
    out.write_text(json.dumps(summary_rows, indent=2))
    print(f"full results written to {out}")


if __name__ == "__main__":
    main()
