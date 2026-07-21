#!/usr/bin/env python3
"""Diagnose V1 calibration transfer and subgroup/domain shift."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from reliability.audit import attach_episode_metadata, load_episode_metadata
from reliability.bundle import ReliabilityBundle
from reliability.dataset import load_json
from reliability.diagnostics import (
    build_shift_diagnostic,
    diagnostic_markdown,
    plot_calibration,
    write_subgroup_csv,
)
from reliability.training import read_dataset


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=str(ROOT / "configs" / "default.json"))
    parser.add_argument("--dataset", default=str(ROOT / "data" / "processed" / "reliability_v1.csv"))
    parser.add_argument("--artifact", default=str(ROOT / "artifacts" / "reliability_v1.pkl"))
    parser.add_argument("--report-json", default=str(ROOT / "reports" / "v1_shift_diagnostic.json"))
    parser.add_argument("--report-md", default=str(ROOT / "reports" / "V1_SHIFT_DIAGNOSTIC.md"))
    parser.add_argument("--subgroups-csv", default=str(ROOT / "reports" / "v1_test_subgroups.csv"))
    parser.add_argument("--calibration-plot", default=str(ROOT / "reports" / "v1_calibration_shift.png"))
    args = parser.parse_args()

    config = load_json(args.config)
    rows = read_dataset(args.dataset)
    metadata = load_episode_metadata(config["offline_audit"]["episode_dataset"])
    attach_episode_metadata(rows, metadata)
    bundle = ReliabilityBundle.load(args.artifact)
    report = build_shift_diagnostic(rows, config, bundle)

    write_subgroup_csv(report, args.subgroups_csv)
    plot_calibration(report, args.calibration_plot)
    Path(args.report_json).write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    markdown = diagnostic_markdown(report)
    Path(args.report_md).write_text(markdown, encoding="utf-8")
    print(markdown)


if __name__ == "__main__":
    main()
