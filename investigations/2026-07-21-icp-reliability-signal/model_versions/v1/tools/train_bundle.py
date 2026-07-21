#!/usr/bin/env python3
"""Train and calibrate the three-head model bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from reliability.dataset import load_json
from reliability.portable import export_portable
from reliability.training import read_dataset, report_markdown, train_bundle


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=str(ROOT / "configs" / "default.json"))
    parser.add_argument("--dataset", default=str(ROOT / "data" / "processed" / "reliability_v1.csv"))
    parser.add_argument("--artifact", default=str(ROOT / "artifacts" / "reliability_v1.pkl"))
    parser.add_argument("--portable-artifact", default=str(ROOT / "artifacts" / "reliability_v1_portable.json"))
    parser.add_argument("--report-json", default=str(ROOT / "reports" / "training_report.json"))
    parser.add_argument("--report-md", default=str(ROOT / "reports" / "TRAINING_REPORT.md"))
    parser.add_argument("--artifact-manifest", default=str(ROOT / "reports" / "artifact_manifest.json"))
    args = parser.parse_args()
    config = load_json(args.config)
    rows = read_dataset(args.dataset)
    bundle, report = train_bundle(rows, config, args.dataset)
    bundle.save(args.artifact)
    export_portable(bundle, args.portable_artifact)
    artifact_path = Path(args.artifact)
    portable_path = Path(args.portable_artifact)
    artifact_manifest = {
        "artifact": str(artifact_path),
        "sha256": hashlib.sha256(artifact_path.read_bytes()).hexdigest(),
        "size_bytes": artifact_path.stat().st_size,
        "model_version": bundle.model_version,
        "schema_version": bundle.schema_version,
        "python_version": platform.python_version(),
        "sklearn_version": report["sklearn_version"],
        "enforcement_approved": False,
        "portable_artifact": str(portable_path),
        "portable_sha256": hashlib.sha256(portable_path.read_bytes()).hexdigest(),
        "portable_size_bytes": portable_path.stat().st_size,
    }
    Path(args.artifact_manifest).write_text(
        json.dumps(artifact_manifest, indent=2, sort_keys=True), encoding="utf-8"
    )
    Path(args.report_json).write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    Path(args.report_md).write_text(report_markdown(report), encoding="utf-8")
    print(report_markdown(report))
    print(f"artifact: {args.artifact}")


if __name__ == "__main__":
    main()
