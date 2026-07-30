#!/usr/bin/env python3
"""Validate that an evaluator exit produced one complete usable capture."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def safe_child(root: Path, relative: str) -> Path:
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"capture path escapes result root: {relative}") from exc
    return candidate


def validate(result_root: Path, expected_episode: int) -> dict:
    root = result_root.resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"result directory missing: {root}")
    completion_path = root / "capture_completion.json"
    completion = json.loads(completion_path.read_text(encoding="utf-8"))
    if completion.get("complete") is not True:
        raise ValueError("capture is not marked complete")
    if int(completion.get("physical_episode_id", -1)) != expected_episode:
        raise ValueError("capture physical_episode_id mismatch")

    measurement = completion.get("measurement") or {}
    trajectory = completion.get("trajectory") or {}
    measurement_path = safe_child(root, str(measurement.get("path", "")))
    trajectory_path = safe_child(root, str(trajectory.get("path", "")))
    if not measurement_path.is_file():
        raise FileNotFoundError(f"measurement missing: {measurement_path}")
    if not trajectory_path.is_file():
        raise FileNotFoundError(f"trajectory missing: {trajectory_path}")
    if int(trajectory.get("rows", 0)) <= 0:
        raise ValueError("trajectory has no rows")
    expected_measurement_sha = str(measurement.get("sha256", ""))
    if not expected_measurement_sha:
        raise ValueError("measurement SHA256 missing")
    actual_measurement_sha = sha256(measurement_path)
    if actual_measurement_sha != expected_measurement_sha:
        raise ValueError("measurement SHA256 mismatch")
    json.loads(measurement_path.read_text(encoding="utf-8"))
    return {
        "complete": True,
        "physical_episode_id": expected_episode,
        "measurement": str(measurement_path),
        "trajectory": str(trajectory_path),
        "trajectory_rows": int(trajectory["rows"]),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("result_root", type=Path)
    parser.add_argument("expected_episode", type=int)
    args = parser.parse_args()
    try:
        summary = validate(args.result_root, args.expected_episode)
    except Exception as exc:  # validation failures are a stable CLI contract
        print(
            f"[capture_integrity_fail] type={type(exc).__name__} error={exc}",
            file=sys.stderr,
        )
        return 1
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
