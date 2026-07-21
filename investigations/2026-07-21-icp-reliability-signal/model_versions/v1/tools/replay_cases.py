#!/usr/bin/env python3
"""Run the required pinned-current and missed-stop counterfactual replays."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from reliability.bundle import ReliabilityBundle
from reliability.dataset import load_json
from reliability.replay import (
    discover_missed_stop_cases,
    replay_current_eviction_false_positives,
    replay_pinned,
    replay_stops,
)
from reliability.training import read_dataset


def _markdown(report: dict) -> str:
    lines = [
        "# Reliability V1 counterfactual replay",
        "",
        f"- Model: `{report['model_version']}`",
        f"- Batch: `{report['batch']}`",
        f"- Pinned cases detected: **{report['pinned_detected_count']}/{len(report['pinned'])}**",
        f"- Healthy current false evictions: **{report['current_eviction_false_positives']['false_positive_segments']}/{report['current_eviction_false_positives']['healthy_current_segments']}**",
        f"- Missed-stop cases found: **{report['stops']['missed_stop_count']}**",
        f"- Counterfactual stop recoveries: **{report['stops']['counterfactual_recovered_count']}**",
        f"- False-stop streak episodes: **{report['stops']['false_stop_streak_count']}**",
        "",
        "## Pinned-current cases",
        "",
        "| Episode | Anchor | Readings | Actual bad rate | High-risk rate | First eviction recommendation |",
        "|---:|---:|---:|---:|---:|---:|",
    ]
    for item in report["pinned"]:
        def fmt(value):
            return "n/a" if value is None else f"{value:.3f}" if isinstance(value, float) else str(value)
        lines.append(
            f"| {item['episode_id']} | {item['pinned_anchor_index']} | {item['readings']} | "
            f"{fmt(item['actual_pose_bad_rate'])} | {fmt(item['high_risk_rate'])} | "
            f"{fmt(item['first_eviction_recommendation_attempt'])} |"
        )
    lines.extend(("", "## Missed-stop cases", "", "| Episode | Final true distance | Recovery attempt | Recovered |", "|---:|---:|---:|:---:|"))
    for item in report["stops"]["episodes"]:
        lines.append(
            f"| {item['episode_id']} | {item['final_true_distance_to_start_m']:.3f} m | "
            f"{item['counterfactual_forced_stop_attempt'] or 'n/a'} | {item['recovered']} |"
        )
    lines.extend(("", "This is an offline counterfactual, not a claim of live navigation success. It does not model a changed robot trajectory after an earlier decision.", ""))
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=str(ROOT / "configs" / "default.json"))
    parser.add_argument("--dataset", default=str(ROOT / "data" / "processed" / "reliability_v1.csv"))
    parser.add_argument("--artifact", default=str(ROOT / "artifacts" / "reliability_v1.pkl"))
    parser.add_argument("--output-json", default=str(ROOT / "reports" / "replay_report.json"))
    parser.add_argument("--output-md", default=str(ROOT / "reports" / "REPLAY_REPORT.md"))
    args = parser.parse_args()
    config = load_json(args.config)
    batch = config["split"]["test_batches"][-1]
    rows = [row for row in read_dataset(args.dataset) if row["batch"] == batch]
    bundle = ReliabilityBundle.load(args.artifact)
    scored = bundle.predict_features_many(rows)
    for row, result in zip(rows, scored):
        row["_reliability"] = result.as_dict()
    temporal = config["temporal_policy"]
    consecutive = int(temporal["high_risk_consecutive"])
    high_risk_threshold = float(temporal["pose_high_risk_threshold"])
    pinned = replay_pinned(rows, bundle, batch, consecutive, high_risk_threshold)
    current_false_positives = replay_current_eviction_false_positives(
        rows, bundle, batch, consecutive, high_risk_threshold
    )
    missed_stop_cases = discover_missed_stop_cases(config["evaluation_root"], batch)
    stops = replay_stops(rows, bundle, batch, missed_stop_cases)
    report = {
        "model_version": bundle.model_version,
        "batch": batch,
        "pinned": pinned,
        "pinned_detected_count": sum(bool(item["detected"]) for item in pinned),
        "current_eviction_false_positives": current_false_positives,
        "stops": stops,
    }
    Path(args.output_json).write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    markdown = _markdown(report)
    Path(args.output_md).write_text(markdown, encoding="utf-8")
    print(markdown)


if __name__ == "__main__":
    main()
