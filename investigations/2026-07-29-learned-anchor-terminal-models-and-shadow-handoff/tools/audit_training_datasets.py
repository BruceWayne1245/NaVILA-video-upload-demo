#!/usr/bin/env python3
"""Independent structural and leakage audit for generated datasets."""

from __future__ import annotations

import argparse
import collections
import gzip
import hashlib
import json
from pathlib import Path
from typing import Any, Iterator


DEFAULT_DATA = Path(__file__).resolve().parents[1] / "data" / "v1"


def rows(path: Path) -> Iterator[dict[str, Any]]:
    opener = gzip.open if path.suffix == ".gz" else path.open
    with opener(path, "rt", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"{path}:{line_number}: {exc}") from exc


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def audit(data_dir: Path) -> dict[str, Any]:
    split_info = json.loads((data_dir / "splits.json").read_text(encoding="utf-8"))
    scene_to_split = split_info["scene_to_split"]
    split_scenes = {
        split: set(scenes)
        for split, scenes in split_info["split_to_scenes"].items()
    }
    names = list(split_scenes)
    overlap = {
        f"{a}_{b}": sorted(split_scenes[a] & split_scenes[b])
        for index, a in enumerate(names)
        for b in names[index + 1 :]
    }
    if any(overlap.values()):
        raise RuntimeError(f"scene leakage detected: {overlap}")

    reports = {}
    for filename, task in (
        ("anchor_state.jsonl.gz", "anchor_state"),
        ("terminal_decision.jsonl.gz", "terminal_decision"),
    ):
        count = 0
        episodes = set()
        scenes = set()
        splits = collections.Counter()
        classes = collections.Counter()
        zero_weight = 0
        for row in rows(data_dir / filename):
            count += 1
            if row.get("task") != task:
                raise RuntimeError(f"{filename}: wrong task at row {count}")
            episode = row["episode"]
            scene = episode["scene_id"]
            split = episode["split"]
            if scene_to_split.get(scene) != split:
                raise RuntimeError(
                    f"{filename}: split mismatch scene={scene} row_split={split}"
                )
            if "position" in row.get("inputs", {}):
                raise RuntimeError(f"{filename}: absolute position leaked into inputs")
            if any(key.startswith("oracle_") for key in row.get("inputs", {})):
                raise RuntimeError(f"{filename}: oracle field leaked into inputs")
            episodes.add(episode["episode_key"])
            scenes.add(scene)
            splits[split] += 1
            label_name = (
                row["labels"]["transition_action"]
                if task == "anchor_state"
                else row["labels"]["terminal_class"]
            )
            classes[str(label_name)] += 1
            zero_weight += float(row["labels"]["sample_weight"]) == 0.0
        reports[task] = {
            "rows": count,
            "episodes": len(episodes),
            "scenes": len(scenes),
            "split_rows": dict(sorted(splits.items())),
            "classes": dict(sorted(classes.items())),
            "zero_weight_rows": zero_weight,
        }

    expected_manifest = {}
    for line in (data_dir / "DATA_MANIFEST.sha256").read_text(
        encoding="utf-8"
    ).splitlines():
        digest, name = line.split("  ", 1)
        expected_manifest[name] = digest
    actual_manifest = {
        path.name: sha256_file(path)
        for path in data_dir.iterdir()
        if path.is_file() and path.name != "DATA_MANIFEST.sha256"
    }
    if expected_manifest != actual_manifest:
        raise RuntimeError("DATA_MANIFEST.sha256 does not match generated files")

    return {
        "scene_overlap": overlap,
        "datasets": reports,
        "manifest_files": len(actual_manifest),
        "status": "pass",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA))
    args = parser.parse_args()
    print(json.dumps(audit(Path(args.data_dir).resolve()), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
