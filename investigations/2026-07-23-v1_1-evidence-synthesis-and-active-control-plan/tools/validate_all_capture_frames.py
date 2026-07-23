#!/usr/bin/env python3
"""Parse and validate every prospective capture frame as required by the protocol."""

from __future__ import annotations

import argparse
import json
import re
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path


FRAME_RE = re.compile(r"frame_step(\d+)\.json$")


def validate(path_text: str) -> tuple[str, str | None]:
    path = Path(path_text)
    try:
        with path.open(encoding="utf-8") as handle:
            frame = json.load(handle)
        match = FRAME_RE.search(path.name)
        if match is None or int(frame["step"]) != int(match.group(1)):
            return path_text, "filename_step_mismatch"
        if len(frame.get("robot_world_pose") or []) != 7:
            return path_text, "missing_robot_world_pose"
        if not frame.get("local_map_points_xyz_body"):
            return path_text, "missing_local_map_points"
        return path_text, None
    except Exception as exc:
        return path_text, f"{type(exc).__name__}: {exc}"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--evaluation-root",
        default="/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/eval_results",
    )
    parser.add_argument(
        "--run-tag",
        default="reliability_v11_prospective_capture_shadow_100ep_20260722_accumulated",
    )
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument(
        "--output",
        default=str(Path(__file__).resolve().parent / "all_capture_frame_validation.json"),
    )
    args = parser.parse_args()
    root = Path(args.evaluation_root)
    paths = sorted(
        str(path)
        for run in root.glob(f"*_{args.run_tag}_ep*")
        for path in (run / "icp_replay_dataset" / "steps").glob("frame_step*.json")
    )
    failures = []
    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        for index, (path, error) in enumerate(executor.map(validate, paths, chunksize=8), 1):
            if error is not None:
                failures.append({"path": path, "error": error})
            if index % 2000 == 0 or index == len(paths):
                print(
                    f"validated {index}/{len(paths)} frames; failures={len(failures)}",
                    flush=True,
                )
    report = {
        "run_tag": args.run_tag,
        "frames_discovered": len(paths),
        "frames_valid": len(paths) - len(failures),
        "failures": failures,
        "passed": not failures,
    }
    Path(args.output).write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("frames_discovered", "frames_valid", "passed")}))
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
