#!/usr/bin/env python3
"""Run the group-aware offline audit without retraining Reliability V1."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from reliability.audit import (
    attach_episode_metadata,
    audit_report_markdown,
    evaluate_frozen_bundle,
    load_episode_metadata,
    plot_risk_coverage,
    raw_label_audit,
    sha256_file,
    write_risk_coverage_csv,
)
from reliability.bundle import ReliabilityBundle
from reliability.dataset import load_json
from reliability.training import read_dataset


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=str(ROOT / "configs" / "default.json"))
    parser.add_argument("--dataset", default=str(ROOT / "data" / "processed" / "reliability_v1.csv"))
    parser.add_argument("--artifact", default=str(ROOT / "artifacts" / "reliability_v1.pkl"))
    parser.add_argument("--dataset-manifest", default=str(ROOT / "reports" / "dataset_manifest.json"))
    parser.add_argument("--report-json", default=str(ROOT / "reports" / "offline_audit_report.json"))
    parser.add_argument("--report-md", default=str(ROOT / "reports" / "OFFLINE_AUDIT_REPORT.md"))
    parser.add_argument("--label-audit-csv", default=str(ROOT / "reports" / "label_audit_samples.csv"))
    parser.add_argument("--risk-coverage-csv", default=str(ROOT / "reports" / "risk_coverage.csv"))
    parser.add_argument("--risk-coverage-plot", default=str(ROOT / "reports" / "risk_coverage.png"))
    parser.add_argument("--bootstrap-samples", type=int, default=None)
    args = parser.parse_args()

    config = load_json(args.config)
    audit_config = config["offline_audit"]
    bootstrap_samples = int(args.bootstrap_samples or audit_config["bootstrap_samples"])
    rows = read_dataset(args.dataset)
    metadata = load_episode_metadata(audit_config["episode_dataset"])
    attach_episode_metadata(rows, metadata)
    manifest = load_json(args.dataset_manifest)
    bundle = ReliabilityBundle.load(args.artifact)

    label_audit = raw_label_audit(
        rows,
        manifest,
        int(audit_config["label_sample_size"]),
        int(audit_config["label_sample_seed"]),
        float(config["labels"]["bearing_bad_deg"]),
        float(config["labels"]["distance_bad_m"]),
        args.label_audit_csv,
    )
    evaluation, risk_rows = evaluate_frozen_bundle(
        rows,
        config,
        bundle,
        bootstrap_samples,
        int(audit_config["bootstrap_seed"]),
    )
    write_risk_coverage_csv(risk_rows, args.risk_coverage_csv)
    plot_risk_coverage(risk_rows, args.risk_coverage_plot)
    usable_runs = sum(1 for run in manifest["runs"] if run.get("status") == "ok")
    report = {
        "dataset": str(Path(args.dataset)),
        "dataset_sha256": sha256_file(args.dataset),
        "artifact": str(Path(args.artifact)),
        "artifact_sha256": sha256_file(args.artifact),
        "episode_dataset": audit_config["episode_dataset"],
        "runs_discovered": int(manifest["runs_discovered"]),
        "usable_runs": usable_runs,
        "run_status_counts": manifest["run_status_counts"],
        "label_audit": label_audit,
        "evaluation": evaluation,
        "risk_coverage_csv": str(Path(args.risk_coverage_csv)),
        "risk_coverage_csv_sha256": sha256_file(args.risk_coverage_csv),
        "risk_coverage_plot": str(Path(args.risk_coverage_plot)),
    }
    Path(args.report_json).write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    markdown = audit_report_markdown(report)
    Path(args.report_md).write_text(markdown, encoding="utf-8")
    print(markdown)


if __name__ == "__main__":
    main()
