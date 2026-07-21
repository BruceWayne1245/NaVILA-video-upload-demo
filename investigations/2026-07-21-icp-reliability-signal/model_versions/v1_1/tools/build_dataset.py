#!/usr/bin/env python3
"""Build the versioned three-label reliability dataset."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from reliability.dataset import build_dataset, load_json


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=str(ROOT / "configs" / "default.json"))
    parser.add_argument("--output", default=str(ROOT / "data" / "processed" / "reliability_v1.csv"))
    parser.add_argument("--manifest", default=str(ROOT / "reports" / "dataset_manifest.json"))
    args = parser.parse_args()
    config = load_json(args.config)
    manifest = build_dataset(config, args.output)
    manifest_path = Path(args.manifest)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({key: manifest[key] for key in ("dataset", "sha256", "rows", "rows_by_batch", "run_status_counts")}, indent=2))


if __name__ == "__main__":
    main()
