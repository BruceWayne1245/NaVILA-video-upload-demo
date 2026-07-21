#!/usr/bin/env python3
"""Compare and freeze a development-only Reliability V1.1 candidate."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from reliability.dataset import load_json
from reliability.v11_training import (
    fit_final_development_bundle,
    load_v11_npz,
    nested_compare,
    save_bundle,
    training_report_markdown,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=str(ROOT / "configs" / "default.json"))
    parser.add_argument("--dataset", default=str(ROOT / "data" / "processed" / "reliability_v1_1.npz"))
    parser.add_argument("--artifact", default=str(ROOT / "artifacts" / "reliability_v1_1_development.pkl"))
    parser.add_argument("--report-json", default=str(ROOT / "reports" / "v11_nested_report.json"))
    parser.add_argument("--report-md", default=str(ROOT / "reports" / "V11_NESTED_REPORT.md"))
    parser.add_argument("--artifact-manifest", default=str(ROOT / "reports" / "v11_artifact_manifest.json"))
    parser.add_argument("--outer-splits", type=int, default=4)
    parser.add_argument("--inner-splits", type=int, default=3)
    parser.add_argument("--bootstrap-samples", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=20260721)
    args = parser.parse_args()

    config = load_json(args.config)
    data = load_v11_npz(args.dataset)
    nested = nested_compare(
        data, args.outer_splits, args.inner_splits, args.bootstrap_samples,
        args.seed, config["trusted_bad_rate_targets"],
    )
    bundle, final_report = fit_final_development_bundle(
        data, nested, args.outer_splits, args.bootstrap_samples,
        args.seed, config["trusted_bad_rate_targets"],
    )
    artifact_manifest = save_bundle(bundle, args.artifact)
    report = {
        "dataset": args.dataset,
        "nested": nested,
        "final_development": final_report,
        "artifact": artifact_manifest,
    }
    Path(args.report_json).write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    Path(args.artifact_manifest).write_text(
        json.dumps(artifact_manifest, indent=2, sort_keys=True), encoding="utf-8"
    )
    markdown = training_report_markdown(report)
    Path(args.report_md).write_text(markdown, encoding="utf-8")
    print(markdown)


if __name__ == "__main__":
    main()
