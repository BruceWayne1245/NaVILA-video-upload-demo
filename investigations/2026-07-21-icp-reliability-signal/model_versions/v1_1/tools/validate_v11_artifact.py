#!/usr/bin/env python3
"""Validate V1.1 artifact locks, schema, leakage exclusions, and inference."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from reliability.v11_validation import validate_development_artifact


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default=str(ROOT / "data" / "processed" / "reliability_v1_1.npz"))
    parser.add_argument("--artifact", default=str(ROOT / "artifacts" / "reliability_v1_1_development.pkl"))
    parser.add_argument("--report", default=str(ROOT / "reports" / "v11_artifact_validation.json"))
    args = parser.parse_args()
    report = validate_development_artifact(args.dataset, args.artifact)
    Path(args.report).write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
