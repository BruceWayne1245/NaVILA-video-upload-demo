#!/usr/bin/env python3
"""Require both Route1 A/B arms to have one terminal summary row per cohort episode."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path


def manifest_ids(path: Path) -> set[int]:
    with path.open(newline="", encoding="utf-8") as handle:
        return {int(row["episode_idx"]) for row in csv.DictReader(handle, delimiter="\t")}


def terminal_ids(path: Path) -> tuple[set[int], int]:
    if not path.is_file():
        return set(), 0
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    ids = {
        int(row["episode_idx"])
        for row in rows
        if row.get("episode_idx", "").strip() and row.get("end_time", "").strip()
    }
    return ids, len(rows)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--summary", type=Path, action="append", required=True)
    args = parser.parse_args()

    expected = manifest_ids(args.manifest)
    if len(expected) != 50:
        raise SystemExit(f"manifest must contain 50 unique episodes, got {len(expected)}")

    failures: list[str] = []
    for summary in args.summary:
        actual, rows = terminal_ids(summary)
        missing = sorted(expected - actual)
        unexpected = sorted(actual - expected)
        print(
            f"{summary}: terminal_unique={len(actual & expected)}/50 "
            f"rows={rows} missing={missing} unexpected={unexpected}"
        )
        if missing or unexpected:
            failures.append(str(summary))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
