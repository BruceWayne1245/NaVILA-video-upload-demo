#!/usr/bin/env python3
"""Audit batch integrity, capture linkage, and navigation outcomes."""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any


FRAME_RE = re.compile(r"frame_step(\d+)\.json$")


def distance(first: list[float], second: list[float]) -> float:
    return math.hypot(float(first[0]) - float(second[0]), float(first[1]) - float(second[1]))


def optional_bool(value: str) -> bool | None:
    if value == "True":
        return True
    if value == "False":
        return False
    return None


def trajectory_path(run_dir: Path, measurement_path: Path, round_trip: dict[str, Any]) -> Path:
    recorded = round_trip.get("trajectory_file")
    if recorded:
        candidate = Path(str(recorded))
        if not candidate.is_absolute():
            candidate = run_dir / candidate
        if candidate.exists():
            return candidate
    return run_dir / "trajectories" / f"output_{measurement_path.stem}.jsonl"


def read_trajectory(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def main() -> None:
    parser = argparse.ArgumentParser()
    here = Path(__file__).resolve().parent
    parser.add_argument(
        "--batch-dir",
        default="/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/batch_logs/"
        "reliability_v11_prospective_capture_shadow_100ep_20260722_accumulated",
    )
    parser.add_argument(
        "--evaluation-root",
        default="/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/eval_results",
    )
    parser.add_argument("--output", default=str(here / "batch_audit.json"))
    parser.add_argument("--episode-csv", default=str(here / "navigation_episode_audit.csv"))
    args = parser.parse_args()

    batch_dir = Path(args.batch_dir)
    evaluation_root = Path(args.evaluation_root)
    with (batch_dir / "summary.tsv").open(newline="", encoding="utf-8") as handle:
        summary = list(csv.DictReader(handle, delimiter="\t"))

    episode_rows = []
    capture_runs = []
    diagnostics_total = diagnostics_required_complete = diagnostics_mappable = 0
    sampled_frames = sampled_frame_failures = 0
    return_steps_total = capture_frames_total = 0
    terminal_reset_rows_removed = 0
    actual_argv_checks = Counter()

    for summary_row in summary:
        episode = int(summary_row["episode_idx"])
        result_suffix = summary_row["result_suffix"]
        matches = sorted(evaluation_root.glob(f"*_{result_suffix}"))
        run_dir = matches[-1] if matches else None
        measurement_path = (
            Path(summary_row["measurement_file"]) if summary_row["measurement_file"] else None
        )
        measurement = None
        trajectory = []
        return_rows = []
        final_distance = None
        minimum_return_distance = None
        final_stop_decision = "no_return"
        stuck_recovery_fired = False
        records = []
        anchor_count = 0

        eval_log = Path(summary_row["eval_log"])
        log_text = eval_log.read_text(encoding="utf-8", errors="replace") if eval_log.exists() else ""
        argv_line = next(
            (line for line in log_text.splitlines() if "Passing the following args" in line), ""
        )
        actual_argv_checks["logs_checked"] += 1
        actual_argv_checks[
            "has_capture"
            if "--capture_icp_replay_dataset" in argv_line
            else "missing_capture"
        ] += 1
        actual_argv_checks[
            "has_shared_trend_budget"
            if "--reliability_quarantine_shared_trend_budget" in argv_line
            else "missing_shared_trend_budget"
        ] += 1
        actual_argv_checks[
            "has_stuck_recovery" if "--stuck_recovery" in argv_line else "missing_stuck_recovery"
        ] += 1
        model_runtime_tokens = (
            "--reliability_v11_artifact",
            "--reliability_v11_model",
            "--reliability_v11_enforce",
        )
        actual_argv_checks[
            "model_runtime_absent"
            if not any(token in argv_line for token in model_runtime_tokens)
            else "model_runtime_present"
        ] += 1

        if measurement_path and measurement_path.exists():
            measurement = json.loads(measurement_path.read_text(encoding="utf-8"))
            round_trip = measurement.get("round_trip") or {}
            run_dir = measurement_path.parent.parent
            path = trajectory_path(run_dir, measurement_path, round_trip)
            if path.exists():
                trajectory = read_trajectory(path)
                return_rows = [row for row in trajectory if row.get("phase") == "return"]
            diagnostics = round_trip.get("route_relocalization_diagnostics") or {}
            records = diagnostics.get("covisibility_records") or []
            diagnostics_total += len(records)
            interval = int((round_trip.get("route_memory") or {}).get(
                "relocalization_interval_updates", 0
            ))
            anchors = {
                int(anchor["index"]): anchor
                for anchor in (round_trip.get("route_memory") or {}).get("anchors") or []
            }
            anchor_count = len(anchors)
            for record in records:
                required = (
                    "attempt",
                    "anchor_index",
                    "estimated_bearing_to_anchor_deg",
                    "estimated_distance_to_anchor_m",
                )
                complete = all(record.get(name) is not None for name in required)
                diagnostics_required_complete += int(complete)
                if not complete or interval < 1:
                    continue
                attempt = int(record["attempt"])
                anchor_index = int(record["anchor_index"])
                index = 0 if attempt == 1 else (attempt - 1) * interval - 1
                pose = ((anchors.get(anchor_index) or {}).get("metadata") or {}).get("world_pose")
                if 0 <= index < len(return_rows) and isinstance(pose, list) and len(pose) >= 2:
                    diagnostics_mappable += 1

            if trajectory and return_rows:
                start = trajectory[0]["position"]
                cleaned = list(return_rows)
                while len(cleaned) >= 2:
                    jump = distance(cleaned[-1]["position"], cleaned[-2]["position"])
                    if jump > 1.0 and float(cleaned[-1].get("speed_mps") or 0.0) < 0.05:
                        cleaned.pop()
                        terminal_reset_rows_removed += 1
                    else:
                        break
                final_distance = distance(cleaned[-1]["position"], start)
                minimum_return_distance = min(distance(row["position"], start) for row in cleaned)
                final_gate = cleaned[-1].get("stop_gate") or {}
                final_stop_decision = str(final_gate.get("gate_decision") or "no_gate_decision")
                stuck_recovery_fired = any(
                    bool((row.get("stuck_recovery") or {}).get("recovery_override"))
                    for row in cleaned
                )

            if run_dir and return_rows:
                capture_root = run_dir / "icp_replay_dataset"
                steps_dir = capture_root / "steps"
                frame_files = sorted(steps_dir.glob("frame_step*.json")) if steps_dir.exists() else []
                frame_steps = []
                zero_byte = 0
                for frame in frame_files:
                    match = FRAME_RE.search(frame.name)
                    if match:
                        frame_steps.append(int(match.group(1)))
                    zero_byte += int(frame.stat().st_size == 0)
                expected_steps = [int(row["step"]) for row in return_rows]
                return_steps_total += len(expected_steps)
                capture_frames_total += len(frame_steps)
                anchors_file = capture_root / "anchors.json"
                anchor_report = {
                    "exists": anchors_file.exists(),
                    "anchors": 0,
                    "anchor_zero_cloud_missing": None,
                    "nonzero_anchor_cloud_missing": None,
                }
                if anchors_file.exists():
                    captured_anchors = (
                        json.loads(anchors_file.read_text(encoding="utf-8")).get("anchors") or []
                    )
                    anchor_report = {
                        "exists": True,
                        "anchors": len(captured_anchors),
                        "anchor_zero_cloud_missing": bool(
                            captured_anchors
                            and captured_anchors[0].get("local_map_points_xyz_body") is None
                        ),
                        "nonzero_anchor_cloud_missing": sum(
                            1
                            for anchor in captured_anchors
                            if int(anchor.get("index", -1)) != 0
                            and not anchor.get("local_map_points_xyz_body")
                        ),
                    }
                sample_failures = 0
                if frame_files:
                    selected = sorted({0, len(frame_files) // 2, len(frame_files) - 1})
                    for index in selected:
                        sampled_frames += 1
                        try:
                            frame = json.loads(frame_files[index].read_text(encoding="utf-8"))
                            passed = (
                                int(frame["step"]) == frame_steps[index]
                                and len(frame.get("robot_world_pose") or []) == 7
                                and bool(frame.get("local_map_points_xyz_body"))
                            )
                        except Exception:
                            passed = False
                        if not passed:
                            sample_failures += 1
                            sampled_frame_failures += 1
                capture_runs.append({
                    "episode_idx": episode,
                    "return_steps": len(expected_steps),
                    "capture_frames": len(frame_steps),
                    "missing_steps": sorted(set(expected_steps) - set(frame_steps)),
                    "extra_steps": sorted(set(frame_steps) - set(expected_steps)),
                    "duplicate_frame_steps": len(frame_steps) - len(set(frame_steps)),
                    "zero_byte_frames": zero_byte,
                    "sampled_frame_failures": sample_failures,
                    "anchors": anchor_report,
                })

        strict_success = final_distance is not None and final_distance < 3.0
        ever_within = minimum_return_distance is not None and minimum_return_distance < 3.0
        episode_rows.append({
            "episode_idx": episode,
            "scene": summary_row["scene"],
            "exit_code": int(summary_row["exit_code"]),
            "result_dir_exists": run_dir is not None and run_dir.exists(),
            "measurement_exists": measurement is not None,
            "trajectory_rows": len(trajectory),
            "return_rows": len(return_rows),
            "diagnostic_records": len(records),
            "anchor_count": anchor_count,
            "reported_outbound_success": optional_bool(summary_row["outbound_success"]),
            "reported_return_success": optional_bool(summary_row["return_success"]),
            "reported_round_trip_success": optional_bool(summary_row["round_trip_success"]),
            "strict_final_distance_m": final_distance,
            "minimum_return_distance_m": minimum_return_distance,
            "strict_return_success": strict_success,
            "ever_within_3m": ever_within,
            "entered_then_left_3m": bool(ever_within and not strict_success),
            "final_stop_gate_decision": final_stop_decision,
            "stuck_recovery_fired": stuck_recovery_fired,
        })

    capture_failures = [
        run for run in capture_runs
        if run["missing_steps"]
        or run["extra_steps"]
        or run["duplicate_frame_steps"]
        or run["zero_byte_frames"]
        or run["sampled_frame_failures"]
        or not run["anchors"]["exists"]
        or run["anchors"]["nonzero_anchor_cloud_missing"]
    ]
    outbound_true = [
        row for row in episode_rows if row["reported_outbound_success"] is True
    ]
    outbound_evaluable = [row for row in outbound_true if row["return_rows"] > 0]
    strict_outbound_successes = [
        row for row in outbound_evaluable if row["strict_return_success"]
    ]
    recovery_rows = [row for row in episode_rows if row["stuck_recovery_fired"]]
    recovery_successes = [row for row in recovery_rows if row["strict_return_success"]]

    report = {
        "summary": {
            "rows": len(summary),
            "unique_episode_idx": len({int(row["episode_idx"]) for row in summary}),
            "exit_codes": dict(Counter(row["exit_code"] for row in summary)),
            "reported_outbound_success_true": sum(
                optional_bool(row["outbound_success"]) is True for row in summary
            ),
            "reported_return_success_true": sum(
                optional_bool(row["return_success"]) is True for row in summary
            ),
            "reported_round_trip_success_true": sum(
                optional_bool(row["round_trip_success"]) is True for row in summary
            ),
        },
        "actual_argv": dict(actual_argv_checks),
        "capture": {
            "runs_with_return": len(capture_runs),
            "return_steps_total": return_steps_total,
            "capture_frames_total": capture_frames_total,
            "exact_linkage_runs": len(capture_runs) - len(capture_failures),
            "failed_runs": capture_failures,
            "sampled_frames_parsed": sampled_frames,
            "sampled_frame_failures": sampled_frame_failures,
            "anchor_zero_cloud_missing_runs": sum(
                run["anchors"]["anchor_zero_cloud_missing"] is True for run in capture_runs
            ),
            "nonzero_anchor_cloud_missing_total": sum(
                int(run["anchors"]["nonzero_anchor_cloud_missing"] or 0)
                for run in capture_runs
            ),
        },
        "diagnostics": {
            "raw_records": diagnostics_total,
            "required_fields_complete": diagnostics_required_complete,
            "attempt_step_and_anchor_pose_mappable": diagnostics_mappable,
            "required_drop_count": diagnostics_total - diagnostics_mappable,
        },
        "navigation": {
            "strict_definition": "final trajectory XY distance to step-0 start < 3.0 m",
            "terminal_reset_rows_removed": terminal_reset_rows_removed,
            "all_episodes_with_return": sum(row["return_rows"] > 0 for row in episode_rows),
            "strict_return_success_all_100": sum(
                row["strict_return_success"] for row in episode_rows
            ),
            "strict_return_success_given_any_return": sum(
                row["strict_return_success"] for row in episode_rows
            ) / max(sum(row["return_rows"] > 0 for row in episode_rows), 1),
            "outbound_success_episodes": len(outbound_true),
            "outbound_success_with_evaluable_return": len(outbound_evaluable),
            "strict_round_trip_successes": len(strict_outbound_successes),
            "strict_round_trip_rate_all_100": len(strict_outbound_successes) / len(summary),
            "strict_return_rate_given_outbound_and_evaluable": (
                len(strict_outbound_successes) / max(len(outbound_evaluable), 1)
            ),
            "strict_return_rate_given_outbound_operational": (
                len(strict_outbound_successes) / max(len(outbound_true), 1)
            ),
            "entered_then_left_3m_episodes": [
                row["episode_idx"] for row in episode_rows if row["entered_then_left_3m"]
            ],
            "near_miss_3_to_3p2m_episodes": [
                row["episode_idx"]
                for row in episode_rows
                if row["strict_final_distance_m"] is not None
                and 3.0 <= row["strict_final_distance_m"] < 3.2
            ],
            "final_stop_gate_decisions_given_outbound": dict(
                Counter(row["final_stop_gate_decision"] for row in outbound_evaluable)
            ),
            "strict_success_by_final_stop_gate_decision": {
                decision: sum(
                    row["strict_return_success"]
                    for row in outbound_evaluable
                    if row["final_stop_gate_decision"] == decision
                )
                for decision in sorted({
                    row["final_stop_gate_decision"] for row in outbound_evaluable
                })
            },
            "stuck_recovery_fired_episodes": [row["episode_idx"] for row in recovery_rows],
            "stuck_recovery_fired_count": len(recovery_rows),
            "stuck_recovery_strict_successes": [
                row["episode_idx"] for row in recovery_successes
            ],
        },
        "episodes": episode_rows,
    }
    Path(args.output).write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    with Path(args.episode_csv).open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(episode_rows[0]))
        writer.writeheader()
        writer.writerows(episode_rows)
    concise = {
        "summary": report["summary"],
        "actual_argv": report["actual_argv"],
        "capture": {key: value for key, value in report["capture"].items() if key != "failed_runs"},
        "capture_failed_runs": len(capture_failures),
        "diagnostics": report["diagnostics"],
        "navigation": report["navigation"],
    }
    print(json.dumps(concise, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
