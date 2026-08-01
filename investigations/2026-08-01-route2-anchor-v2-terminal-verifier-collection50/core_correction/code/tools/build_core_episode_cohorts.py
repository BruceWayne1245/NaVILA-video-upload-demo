#!/usr/bin/env python3
"""Build frozen Route-2 development and prospective validation cohorts.

Development episodes deliberately favour routes that have reached the outbound
goal before but have produced little or no return success.  They may overlap
the old *development* corpus because their new on-policy captures are intended
for the next training round.  Locked validation episodes are stricter: their
physical episode IDs and exact path geometries have not appeared in the old
training corpus, the current Route-2 50, any completed/failed canonical batch,
or the development cohort selected here.
"""

from __future__ import annotations

import csv
import gzip
import hashlib
import json
import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
DATASET = Path(
    "/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/"
    "isaaclab_exts/omni.isaac.vlnce/assets/vln_ce_isaac_v1.json.gz"
)
BATCH_LOGS = Path(
    "/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/batch_logs"
)
OLD_EPISODES = Path(
    "/home/teambruce/navila-anchor-terminal-training-data-20260729/"
    "data/v1/episodes.jsonl"
)
CURRENT_MANIFEST = ROOT / "manifest/route2_anchorv2_terminal50.tsv"
DEV_MANIFEST = ROOT / "manifest/route2_core_development24.tsv"
VALIDATION_MANIFEST = ROOT / "manifest/route2_core_locked_validation20.tsv"
EVIDENCE = ROOT / "manifest/route2_core_cohort_evidence.tsv"
LOCK = ROOT / "config/route2_core_cohort_lock_v1.json"

DEV_QUOTAS = {
    "2azQ1b91cZZ": 4,
    "EU6Fwq7SyZv": 1,
    "QUCTc6BB5sX": 4,
    "TbHJrupSAjP": 4,
    "X7HyMhZNoso": 3,
    "Z6MFQCViBuw": 2,
    "oLBMNvg9in8": 1,
    "x8F5xyUWy9e": 1,
    "zsNo4HB9uLZ": 4,
}
VALIDATION_QUOTAS = {
    "2azQ1b91cZZ": 7,
    "QUCTc6BB5sX": 5,
    "TbHJrupSAjP": 2,
    "zsNo4HB9uLZ": 6,
}


@dataclass(frozen=True)
class Candidate:
    episode_idx: int
    episode_id: int
    scene: str
    neighbor_idx: int
    neighbor_episode_id: int
    matched_waypoints: int
    mean_distance: float
    baseline_distance_to_start: float
    length_band: str
    geometry_sha256: str
    route_pair_sha256: str


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def scene_key(episode: dict[str, Any]) -> str:
    return str(episode["scene_id"]).split("/")[-2]


def path_xyz(episode: dict[str, Any]) -> list[list[float]]:
    return [[float(value) for value in point] for point in episode["reference_path"]]


def path_xy(episode: dict[str, Any]) -> list[tuple[float, float]]:
    return [(point[0], point[1]) for point in path_xyz(episode)]


def geometry_sha(episode: dict[str, Any]) -> str:
    normalized = [[round(value, 3) for value in point] for point in path_xyz(episode)]
    encoded = json.dumps(normalized, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def route_length(episode: dict[str, Any]) -> float:
    path = path_xyz(episode)
    return sum(math.dist(left, right) for left, right in zip(path, path[1:]))


def length_band(length: float) -> str:
    if length < 5.0:
        return "short"
    if length < 10.0:
        return "medium"
    return "long"


def ordered_match(
    candidate: list[tuple[float, float]],
    target: list[tuple[float, float]],
    tolerance: float = 2.0,
) -> tuple[int, float]:
    target_index = 0
    distances: list[float] = []
    for point in candidate:
        available = [
            (math.dist(point, other), index)
            for index, other in enumerate(target[target_index:], target_index)
        ]
        if not available:
            break
        distance, index = min(available)
        if distance <= tolerance:
            distances.append(distance)
            target_index = index + 1
    return (
        (len(distances), sum(distances) / len(distances))
        if distances
        else (0, float("inf"))
    )


def reverse_neighbor(
    episodes: list[dict[str, Any]], source_index: int
) -> tuple[int, int, float] | None:
    source = episodes[source_index]
    source_path = path_xy(source)
    targets = [list(reversed(source_path))]
    if len(source_path) > 2:
        targets.append(list(reversed(source_path[:-1])))
    best: tuple[tuple[Any, ...], int, int, float] | None = None
    for index, episode in enumerate(episodes):
        if index == source_index or scene_key(episode) != scene_key(source):
            continue
        candidate_path = path_xy(episode)
        if len(candidate_path) < 2:
            continue
        for target in targets:
            matched, mean_distance = ordered_match(candidate_path, target)
            required = max(2, min(len(candidate_path), len(target)) - 1)
            coverage = matched / max(1, min(len(candidate_path), len(target)))
            if matched < required or coverage < 0.8:
                continue
            key = (
                -matched,
                abs(len(candidate_path) - len(target)),
                -(matched / len(candidate_path)),
                mean_distance,
                index,
            )
            if best is None or key < best[0]:
                best = (key, index, matched, mean_distance)
    return None if best is None else (best[1], best[2], best[3])


def candidates(episodes: list[dict[str, Any]]) -> list[Candidate]:
    result = []
    for index, episode in enumerate(episodes):
        neighbor = reverse_neighbor(episodes, index)
        if neighbor is None:
            continue
        neighbor_index, matched, mean_distance = neighbor
        route_hashes = sorted((geometry_sha(episode), geometry_sha(episodes[neighbor_index])))
        pair_sha = hashlib.sha256("|".join(route_hashes).encode()).hexdigest()
        distance = route_length(episode)
        result.append(
            Candidate(
                episode_idx=index,
                episode_id=int(episode["episode_id"]),
                scene=scene_key(episode),
                neighbor_idx=neighbor_index,
                neighbor_episode_id=int(episodes[neighbor_index]["episode_id"]),
                matched_waypoints=matched,
                mean_distance=mean_distance,
                baseline_distance_to_start=distance,
                length_band=length_band(distance),
                geometry_sha256=geometry_sha(episode),
                route_pair_sha256=pair_sha,
            )
        )
    return result


def manifest_ids(path: Path) -> set[int]:
    with path.open(newline="", encoding="utf-8") as handle:
        return {int(row["episode_idx"]) for row in csv.DictReader(handle, delimiter="\t")}


def old_training_ids() -> set[int]:
    with OLD_EPISODES.open(encoding="utf-8") as handle:
        return {
            int(json.loads(line)["physical_episode_id"])
            for line in handle
            if line.strip()
        }


def history() -> tuple[set[int], dict[int, list[int]]]:
    attempted: set[int] = set()
    completed: dict[int, list[int]] = defaultdict(lambda: [0, 0, 0])
    for path in sorted(BATCH_LOGS.glob("*/summary.tsv")):
        try:
            with path.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle, delimiter="\t"))
        except (OSError, UnicodeError):
            continue
        for row in rows:
            try:
                episode_idx = int(row.get("episode_idx", ""))
            except ValueError:
                continue
            attempted.add(episode_idx)
            if row.get("exit_code") != "0" or row.get("outbound_success") not in {
                "True", "False", "true", "false"
            }:
                continue
            values = completed[episode_idx]
            values[0] += int(row["outbound_success"].lower() == "true")
            values[1] += 1
            values[2] += int(str(row.get("return_success", "")).lower() == "true")
    return attempted, completed


def select_development(
    pool: list[Candidate], current_ids: set[int], completed: dict[int, list[int]]
) -> list[Candidate]:
    selected = []
    used_geometry: set[str] = set()
    current_geometry = {item.geometry_sha256 for item in pool if item.episode_idx in current_ids}
    for scene, quota in DEV_QUOTAS.items():
        eligible = [
            item
            for item in pool
            if item.scene == scene
            and item.episode_idx not in current_ids
            and item.geometry_sha256 not in current_geometry
            and completed[item.episode_idx][0] >= 1
        ]
        eligible.sort(
            key=lambda item: (
                completed[item.episode_idx][2],
                -completed[item.episode_idx][0],
                -(completed[item.episode_idx][0] / completed[item.episode_idx][1]),
                -item.baseline_distance_to_start,
                item.episode_idx,
            )
        )
        for item in eligible:
            if item.geometry_sha256 in used_geometry:
                continue
            selected.append(item)
            used_geometry.add(item.geometry_sha256)
            if sum(candidate.scene == scene for candidate in selected) == quota:
                break
        if sum(candidate.scene == scene for candidate in selected) != quota:
            raise RuntimeError(f"insufficient development candidates for {scene}")
    return selected


def stable_rank(item: Candidate, band: str) -> str:
    return hashlib.sha256(
        f"route2-core-locked-v1|{item.scene}|{band}|{item.episode_idx}".encode()
    ).hexdigest()


def select_validation(
    pool: list[Candidate],
    excluded_ids: set[int],
    excluded_geometry: set[str],
    excluded_route_pairs: set[str],
) -> list[Candidate]:
    selected = []
    used_geometry = set(excluded_geometry)
    used_route_pairs = set(excluded_route_pairs)
    band_order = ("short", "medium", "long", "medium", "long", "medium", "long")
    for scene, quota in VALIDATION_QUOTAS.items():
        scene_pool = [
            item
            for item in pool
            if item.scene == scene
            and item.episode_idx not in excluded_ids
            and item.geometry_sha256 not in used_geometry
            and item.route_pair_sha256 not in used_route_pairs
        ]
        for desired_band in band_order[:quota]:
            eligible = [
                item
                for item in scene_pool
                if item.geometry_sha256 not in used_geometry
                and item.route_pair_sha256 not in used_route_pairs
                and item.length_band == desired_band
            ]
            if not eligible:
                eligible = [
                    item for item in scene_pool
                    if item.geometry_sha256 not in used_geometry
                    and item.route_pair_sha256 not in used_route_pairs
                ]
            if not eligible:
                raise RuntimeError(f"insufficient locked validation candidates for {scene}")
            item = min(eligible, key=lambda value: stable_rank(value, desired_band))
            selected.append(item)
            used_geometry.add(item.geometry_sha256)
            used_route_pairs.add(item.route_pair_sha256)
    return selected


def write_manifest(path: Path, rows: Iterable[Candidate], role: str) -> None:
    fields = (
        "episode_idx", "episode_id", "scene", "neighbor_idx",
        "neighbor_episode_id", "matched_waypoints", "mean_distance",
        "baseline_distance_to_start", "length_band", "cohort_role",
        "geometry_sha256",
    )
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for item in rows:
            writer.writerow(
                {
                    **{field: getattr(item, field) for field in fields if hasattr(item, field)},
                    "mean_distance": f"{item.mean_distance:.6f}",
                    "baseline_distance_to_start": f"{item.baseline_distance_to_start:.6f}",
                    "cohort_role": role,
                }
            )


def main() -> int:
    with gzip.open(DATASET, "rt", encoding="utf-8") as handle:
        episodes = json.load(handle)["episodes"]
    pool = candidates(episodes)
    current_ids = manifest_ids(CURRENT_MANIFEST)
    training_ids = old_training_ids()
    attempted_ids, completed = history()
    development = select_development(pool, current_ids, completed)
    development_ids = {item.episode_idx for item in development}
    strict_excluded_ids = training_ids | current_ids | attempted_ids | development_ids
    strict_excluded_geometry = {
        item.geometry_sha256 for item in pool if item.episode_idx in strict_excluded_ids
    }
    strict_excluded_route_pairs = {
        item.route_pair_sha256
        for item in pool
        if item.episode_idx in current_ids | development_ids
    }
    validation = select_validation(
        pool,
        strict_excluded_ids,
        strict_excluded_geometry,
        strict_excluded_route_pairs,
    )

    assert len(development) == 24 and len(validation) == 20
    assert not (development_ids & {item.episode_idx for item in validation})
    assert not ({item.episode_idx for item in validation} & strict_excluded_ids)
    assert not ({item.geometry_sha256 for item in validation} & strict_excluded_geometry)
    assert not ({item.route_pair_sha256 for item in validation} & strict_excluded_route_pairs)
    write_manifest(DEV_MANIFEST, development, "training_development")
    write_manifest(VALIDATION_MANIFEST, validation, "locked_validation")

    with EVIDENCE.open("w", newline="", encoding="utf-8") as handle:
        fields = (
            "cohort_role", "episode_idx", "scene", "length_band",
            "historical_outbound_successes", "historical_completed_trials",
            "historical_return_successes", "old_training_overlap",
            "current50_overlap", "historical_attempt_overlap",
            "route_pair_sha256", "selection_reason",
        )
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for role, rows in (("training_development", development), ("locked_validation", validation)):
            for item in rows:
                values = completed[item.episode_idx]
                writer.writerow(
                    {
                        "cohort_role": role,
                        "episode_idx": item.episode_idx,
                        "scene": item.scene,
                        "length_band": item.length_band,
                        "historical_outbound_successes": values[0],
                        "historical_completed_trials": values[1],
                        "historical_return_successes": values[2],
                        "old_training_overlap": item.episode_idx in training_ids,
                        "current50_overlap": item.episode_idx in current_ids,
                        "historical_attempt_overlap": item.episode_idx in attempted_ids,
                        "route_pair_sha256": item.route_pair_sha256,
                        "selection_reason": (
                            "known_outbound_reachable_low_return_yield"
                            if role == "training_development"
                            else "sealed_fresh_physical_id_and_geometry"
                        ),
                    }
                )

    lock = {
        "schema": "navila-route2-core-cohort-lock-v1",
        "state": "sealed_before_execution",
        "execution_authorized": False,
        "queue_authorized": False,
        "current_50_control_effect": "none",
        "selection_tool": str(Path(__file__).resolve()),
        "selection_tool_sha256": sha256(Path(__file__).resolve()),
        "dataset": str(DATASET),
        "dataset_sha256": sha256(DATASET),
        "development": {
            "manifest": str(DEV_MANIFEST),
            "manifest_sha256": sha256(DEV_MANIFEST),
            "episodes": len(development),
            "scene_counts": dict(sorted(Counter(item.scene for item in development).items())),
            "may_enter_future_training": True,
        },
        "locked_validation": {
            "manifest": str(VALIDATION_MANIFEST),
            "manifest_sha256": sha256(VALIDATION_MANIFEST),
            "episodes": len(validation),
            "scene_counts": dict(sorted(Counter(item.scene for item in validation).items())),
            "old_training_id_overlap": 0,
            "current_50_id_overlap": 0,
            "canonical_history_attempt_id_overlap": 0,
            "development_id_overlap": 0,
            "excluded_geometry_overlap": 0,
            "current_or_development_route_pair_overlap": 0,
            "may_enter_future_training": False,
            "may_tune_thresholds": False,
        },
        "evidence": str(EVIDENCE),
        "evidence_sha256": sha256(EVIDENCE),
    }
    LOCK.write_text(json.dumps(lock, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(lock, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
