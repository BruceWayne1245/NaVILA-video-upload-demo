#!/usr/bin/env python3
"""Replay a wider anchor neighborhood with the authoritative ICP primitive.

The script is resumable at episode granularity and writes one JSONL shard per
episode.  It never edits a capture or the active evaluator.  Each selected
anchor-state row is replayed against:

* observed current - 2;
* observed current - 1;
* observed current;
* observed current + 1;
* every historically logged candidate for that row.

The oracle anchor is used only for evaluation after candidate construction; it
is never injected into the replay neighborhood.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterator

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ANCHOR_DATA = ROOT / "data" / "v1" / "anchor_state.jsonl.gz"
DEFAULT_EPISODES = ROOT / "data" / "v1" / "episodes.jsonl"
DEFAULT_OUTPUT = ROOT / "data" / "v2" / "wider_candidate_shards"
DEFAULT_RUNTIME = Path(
    "/home/teambruce/navila-reliability-v1_1-anchor-support-recovery-20260728/"
    "policy_v2_live_candidate/scripts"
)
SCHEMA = "navila-wider-anchor-replay-v2"


def compact_json(value: Any) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_json(value: Any) -> str:
    return hashlib.sha256(compact_json(value).encode("utf-8")).hexdigest()


def read_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def read_jsonl_gz(path: Path) -> Iterator[dict[str, Any]]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def load_episode_index(path: Path) -> dict[str, dict[str, Any]]:
    return {row["episode_key"]: row for row in read_jsonl(path)}


def selected_rows(
    path: Path,
    episode_keys: set[str],
    stride: int,
    max_rows: int,
) -> dict[str, list[dict[str, Any]]]:
    result = {key: [] for key in episode_keys}
    ordinals = {key: 0 for key in episode_keys}
    for row in read_jsonl_gz(path):
        key = row["episode"]["episode_key"]
        if key not in result:
            continue
        ordinal = ordinals[key]
        ordinals[key] += 1
        if ordinal % max(1, int(stride)) != 0:
            continue
        if float(row["labels"].get("sample_weight") or 0.0) <= 0.0:
            continue
        if max_rows and len(result[key]) >= max_rows:
            continue
        result[key].append(row)
    return result


def observed_current_index(row: dict[str, Any]) -> int | None:
    support = row["inputs"].get("support") or {}
    value = support.get("current_anchor_index")
    if value is not None:
        return int(value)
    candidates = row["inputs"].get("candidates") or []
    current = next(
        (
            candidate.get("anchor_index")
            for candidate in candidates
            if (candidate.get("v11") or {}).get("anchor_role") == "current"
        ),
        None,
    )
    if current is not None:
        return int(current)
    indices = [
        int(candidate["anchor_index"])
        for candidate in candidates
        if candidate.get("anchor_index") is not None
    ]
    return max(indices) if indices else None


def replay_indices(
    row: dict[str, Any],
    available: set[int],
) -> list[int]:
    current = observed_current_index(row)
    result = set()
    if current is not None:
        result.update((current - 2, current - 1, current, current + 1))
    result.update(
        int(candidate["anchor_index"])
        for candidate in row["inputs"].get("candidates") or []
        if candidate.get("anchor_index") is not None
    )
    return sorted(result & available, reverse=True)


def select_shard(
    keys: list[str],
    num_shards: int,
    shard_index: int,
) -> list[str]:
    if num_shards < 1:
        raise ValueError("num_shards must be >= 1")
    if shard_index < 0 or shard_index >= num_shards:
        raise ValueError("shard_index must satisfy 0 <= index < num_shards")
    return [
        key
        for ordinal, key in enumerate(sorted(keys))
        if ordinal % num_shards == shard_index
    ]


def load_anchors(path: Path) -> tuple[dict[int, Any], str]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    anchors = raw.get("anchors") or []
    total = max(
        (float(anchor.get("distance_from_start_m") or 0.0) for anchor in anchors),
        default=0.0,
    )
    result = {}
    for anchor in anchors:
        index = int(anchor["index"])
        points = anchor.get("local_map_points_xyz_body")
        if not points:
            continue
        distance = float(anchor["distance_from_start_m"])
        result[index] = SimpleNamespace(
            index=index,
            pose_from_start=[0.0, 0.0, 0.0],
            distance_from_start_m=distance,
            route_remaining_to_start_m=max(0.0, total - distance),
            descriptor={
                "local_map_points_body": np.asarray(
                    points, dtype=np.float32
                )
            },
        )
    return result, sha256_file(path)


def load_frame(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    points = value.get("local_map_points_xyz_body")
    if not points:
        raise RuntimeError("frame_local_map_missing")
    return {
        "step": int(value["step"]),
        "robot_world_pose": value.get("robot_world_pose"),
        "descriptor": {
            "local_map_points_body": np.asarray(points, dtype=np.float32)
        },
    }


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): json_safe(child) for key, child in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(child) for child in value]
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def replay_episode(
    episode: dict[str, Any],
    rows: list[dict[str, Any]],
    output_dir: Path,
    reloc: Any,
    runtime_hash: str,
    overwrite: bool,
) -> dict[str, Any]:
    key = episode["episode_key"]
    shard = output_dir / f"{key}.jsonl"
    marker = output_dir / f"{key}.complete.json"
    request_sha = sha256_json(
        {
            "schema": SCHEMA,
            "episode_key": key,
            "authoritative_relocalization_sha256": runtime_hash,
            "selected_rows": [
                {
                    "attempt_index": row["time"].get("attempt_index"),
                    "step": row["time"]["step"],
                }
                for row in rows
            ],
        }
    )
    if marker.exists() and shard.exists() and not overwrite:
        previous = json.loads(marker.read_text(encoding="utf-8"))
        if previous.get("request_sha256") == request_sha:
            return previous

    capture_dir = Path(episode["source"]["anchors"]).parent
    anchors, anchors_sha = load_anchors(
        Path(episode["source"]["anchors"])
    )
    available = set(anchors)
    output_dir.mkdir(parents=True, exist_ok=True)
    temporary = shard.with_suffix(".jsonl.tmp")
    counts = {
        "requested_rows": len(rows),
        "replayed_rows": 0,
        "missing_frames": 0,
        "candidate_records": 0,
        "oracle_candidate_present": 0,
        "historical_oracle_candidate_present": 0,
    }
    elapsed_start = time.monotonic()
    with temporary.open("w", encoding="utf-8") as handle:
        for row in rows:
            step = int(row["time"]["step"])
            frame_path = (
                capture_dir / "steps" / f"frame_step{step:06d}.json"
            )
            if not frame_path.exists():
                counts["missing_frames"] += 1
                continue
            try:
                frame = load_frame(frame_path)
            except (OSError, json.JSONDecodeError, RuntimeError):
                counts["missing_frames"] += 1
                continue
            indices = replay_indices(row, available)
            if not indices:
                continue
            ordered = [anchors[index] for index in indices]
            diagnostics: dict[str, Any] = {}
            reloc.sequential_pair_anchor_relocalization(
                frame["descriptor"],
                ordered[0] if ordered else None,
                ordered[1] if len(ordered) > 1 else None,
                additional_anchors=tuple(ordered[2:]),
                diagnostics=diagnostics,
                return_candidates=True,
                icp_objective="point_to_point",
                voxel_size_m=0.10,
                max_points=512,
                quality_policy="diagnostic",
                loftr_rear_yaw_check=False,
            )
            records = diagnostics.get("covisibility_records") or []
            oracle_index = int(row["labels"]["oracle_next_anchor_index"])
            historical_indices = {
                int(candidate["anchor_index"])
                for candidate in row["inputs"].get("candidates") or []
                if candidate.get("anchor_index") is not None
            }
            counts["replayed_rows"] += 1
            counts["candidate_records"] += len(records)
            counts["oracle_candidate_present"] += int(
                oracle_index in {int(record["anchor_index"]) for record in records}
            )
            counts["historical_oracle_candidate_present"] += int(
                oracle_index in historical_indices
            )
            output = {
                "schema": SCHEMA,
                "episode": row["episode"],
                "time": row["time"],
                "inputs": {
                    "movement": row["inputs"].get("movement"),
                    "route_memory": row["inputs"].get("route_memory"),
                    "support": row["inputs"].get("support"),
                    "wider_candidate_indices": indices,
                    "wider_candidates": records,
                },
                "labels": row["labels"],
                "historical_policy": row.get("historical_policy"),
                "provenance": {
                    "capture_directory": str(capture_dir),
                    "anchors_sha256": anchors_sha,
                    "frame_path": str(frame_path),
                    "authoritative_relocalization_sha256": runtime_hash,
                },
            }
            handle.write(compact_json(json_safe(output)))
            handle.write("\n")
    os.replace(temporary, shard)
    replayed = counts["replayed_rows"]
    summary = {
        "schema": SCHEMA,
        "episode_key": key,
        "request_sha256": request_sha,
        "shard": str(shard),
        "shard_sha256": sha256_file(shard),
        "elapsed_seconds": time.monotonic() - elapsed_start,
        **counts,
        "wider_oracle_candidate_coverage": (
            counts["oracle_candidate_present"] / replayed if replayed else 0.0
        ),
        "historical_oracle_candidate_coverage": (
            counts["historical_oracle_candidate_present"] / replayed
            if replayed
            else 0.0
        ),
    }
    marker.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--anchor-data", default=str(DEFAULT_ANCHOR_DATA))
    parser.add_argument("--episodes", default=str(DEFAULT_EPISODES))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--runtime-dir", default=str(DEFAULT_RUNTIME))
    parser.add_argument("--episode-key", action="append", default=[])
    parser.add_argument("--split", choices=("train", "validation", "test"))
    parser.add_argument("--max-episodes", type=int, default=0)
    parser.add_argument("--num-shards", type=int, default=1)
    parser.add_argument("--shard-index", type=int, default=0)
    parser.add_argument("--stride", type=int, default=1)
    parser.add_argument("--max-rows-per-episode", type=int, default=0)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    episode_index = load_episode_index(Path(args.episodes))
    if args.episode_key:
        keys = [
            key for key in args.episode_key if key in episode_index
        ]
    else:
        keys = [
            key
            for key, episode in episode_index.items()
            if args.split is None or episode["split"] == args.split
        ]
    keys = select_shard(keys, args.num_shards, args.shard_index)
    if args.max_episodes:
        keys = keys[: args.max_episodes]
    if not keys:
        raise RuntimeError("no episodes selected")

    runtime_dir = Path(args.runtime_dir).resolve()
    sys.path.insert(0, str(runtime_dir))
    import relocalization as reloc

    runtime_path = runtime_dir / "relocalization.py"
    runtime_hash = sha256_file(runtime_path)
    rows = selected_rows(
        Path(args.anchor_data),
        set(keys),
        args.stride,
        args.max_rows_per_episode,
    )
    summaries = []
    for ordinal, key in enumerate(keys, start=1):
        print(
            f"[wider-replay] {ordinal}/{len(keys)} {key} "
            f"rows={len(rows.get(key) or [])}",
            flush=True,
        )
        summaries.append(
            replay_episode(
                episode_index[key],
                rows.get(key) or [],
                Path(args.output_dir),
                reloc,
                runtime_hash,
                args.overwrite,
            )
        )
        print(json.dumps(summaries[-1], sort_keys=True), flush=True)
    print(
        json.dumps(
            {
                "schema": SCHEMA,
                "episodes": len(summaries),
                "replayed_rows": sum(
                    item["replayed_rows"] for item in summaries
                ),
                "candidate_records": sum(
                    item["candidate_records"] for item in summaries
                ),
                "elapsed_seconds": sum(
                    item["elapsed_seconds"] for item in summaries
                ),
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
