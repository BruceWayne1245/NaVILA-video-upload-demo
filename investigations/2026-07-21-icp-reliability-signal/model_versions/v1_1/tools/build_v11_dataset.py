#!/usr/bin/env python3
"""Build the V1.1 full-basin and causal-temporal NPZ dataset."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from reliability.dataset import load_json
from reliability.v11_dataset import build_v11_dataset


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=str(ROOT / "configs" / "default.json"))
    parser.add_argument("--v1-dataset", default=str(ROOT / "data" / "processed" / "reliability_v1.csv"))
    parser.add_argument("--v1-manifest", default=str(ROOT / "reports" / "dataset_manifest.json"))
    parser.add_argument("--output", default=str(ROOT / "data" / "processed" / "reliability_v1_1.npz"))
    parser.add_argument("--manifest", default=str(ROOT / "reports" / "v11_dataset_manifest.json"))
    args = parser.parse_args()
    config = load_json(args.config)
    manifest = build_v11_dataset(
        args.v1_dataset,
        args.v1_manifest,
        config["offline_audit"]["episode_dataset"],
        args.output,
    )
    Path(args.manifest).write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({
        key: manifest[key] for key in (
            "dataset", "sha256", "size_bytes", "rows", "numeric_features",
            "episodes", "scenes", "label_positive_rates",
        )
    }, indent=2))


if __name__ == "__main__":
    main()
