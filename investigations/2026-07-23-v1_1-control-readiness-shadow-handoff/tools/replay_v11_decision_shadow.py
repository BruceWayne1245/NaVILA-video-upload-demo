#!/usr/bin/env python3
"""Replay the frozen counterfactual decision policy over online shadow logs."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from reliability.v11_runtime import V11DecisionShadowPolicy


def _events(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("shadow_logs", nargs="+")
    parser.add_argument(
        "--policy",
        default=str(ROOT / "configs" / "v11_decision_shadow_v1.json"),
    )
    parser.add_argument("--output-jsonl")
    parser.add_argument("--summary")
    args = parser.parse_args()

    policy = V11DecisionShadowPolicy.load(args.policy)
    decisions: list[dict[str, Any]] = []
    per_episode: list[dict[str, Any]] = []
    aggregate_actions: Counter[str] = Counter()
    aggregate_disagreements: Counter[str] = Counter()

    for source_text in args.shadow_logs:
        source = Path(source_text)
        events = _events(source)
        starts = [
            event
            for event in events
            if event.get("event") == "v11_shadow_session_start"
        ]
        if len(starts) != 1:
            raise ValueError(f"{source}: expected exactly one session start")
        episode_key = str(starts[0]["episode_key"])
        scores = {
            int(event["attempt"]): event.get("outputs", [])
            for event in events
            if event.get("event") == "v11_shadow_score"
        }
        snapshots = [
            event
            for event in events
            if event.get("event") == "v11_shadow_controller_snapshot"
        ]
        logged_decisions = [
            event
            for event in events
            if event.get("event") == "v11_shadow_decision"
        ]
        episode_actions: Counter[str] = Counter()
        episode_disagreements: Counter[str] = Counter()
        if logged_decisions:
            if len(logged_decisions) != len(snapshots):
                raise ValueError(
                    f"{source}: logged decision/snapshot count mismatch"
                )
            if any(
                (decision.get("policy") or {}).get("policy_sha256")
                != policy.policy_sha256
                for decision in logged_decisions
            ):
                raise ValueError(f"{source}: logged decision policy hash mismatch")
            episode_decisions = [
                {**decision, "source_log": str(source)}
                for decision in logged_decisions
            ]
        else:
            episode_decisions = []
            for snapshot in snapshots:
                attempt = int(snapshot["attempt"])
                decision = policy.evaluate(
                    scores.get(attempt, []),
                    accepted_event=snapshot.get("existing_controller_event"),
                    target_anchor_index=snapshot.get(
                        "existing_target_anchor_index"
                    ),
                )
                episode_decisions.append({
                    "event": "v11_shadow_decision_replay",
                    "source_log": str(source),
                    "episode_key": episode_key,
                    "step": int(snapshot["step"]),
                    "attempt": attempt,
                    **decision,
                })
        for record in episode_decisions:
            decisions.append(record)
            action = str(record["counterfactual"]["action"])
            episode_actions[action] += 1
            aggregate_actions[action] += 1
            for key, value in record["disagreement"].items():
                if value is True:
                    episode_disagreements[key] += 1
                    aggregate_disagreements[key] += 1
        per_episode.append({
            "episode_key": episode_key,
            "source_log": str(source),
            "score_calls": len(scores),
            "controller_snapshots": len(snapshots),
            "decisions": len(episode_decisions),
            "actions": dict(sorted(episode_actions.items())),
            "disagreements": dict(sorted(episode_disagreements.items())),
        })

    report = {
        "passed": bool(
            decisions
            and all(
                decision["mode"] == "shadow"
                and decision["activation_approved"] is False
                and decision["enforcement_enabled"] is False
                and decision["controller_effect"] is False
                and decision["counterfactual"]["identity_override_authorized"]
                is False
                for decision in decisions
            )
        ),
        "policy": policy.metadata(),
        "logs": len(args.shadow_logs),
        "episodes": len(per_episode),
        "decisions": len(decisions),
        "actions": dict(sorted(aggregate_actions.items())),
        "disagreements": dict(sorted(aggregate_disagreements.items())),
        "per_episode": per_episode,
    }
    if args.output_jsonl:
        Path(args.output_jsonl).write_text(
            "".join(
                json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"
                for record in decisions
            ),
            encoding="utf-8",
        )
    rendered = json.dumps(report, indent=2, sort_keys=True)
    if args.summary:
        Path(args.summary).write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
