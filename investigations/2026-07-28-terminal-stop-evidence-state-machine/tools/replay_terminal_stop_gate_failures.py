#!/usr/bin/env python3
"""Counterfactual replay of the new terminal gate on the nine stop episodes.

This reuses recorded VLM STOP query rows and Route-2 model assessments.  It is
not a dynamics replay: once a new decision differs from the historical
controller, later recorded positions are counterfactual.  The useful safety
checks are therefore local:

* no recorded outside-radius STOP is accepted;
* untrusted/stale evidence never gets numeric terminal authority;
* the ep89/ep490 repeated-veto loops become bounded safe failures when no
  independent A0 visual signal is supplied by the old logs.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from collections import Counter
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FORENSICS = Path("/home/teambruce/route2_active50_failure_forensics.py")
EPISODES = (19, 89, 95, 196, 205, 264, 276, 310, 490)


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def latest_attempt(data, step):
    attempts = [
        attempt for attempt in data["attempts"]
        if int(attempt["step"]) <= int(step)
    ]
    return attempts[-1] if attempts else None


def route_row(data, query_step):
    return next(
        (
            row for row in data["trajectory"]
            if (
                int(row.get("last_vlm_step") or -1) == int(query_step)
                and row.get("stop_gate")
            )
        ),
        None,
    )


def progress_and_trust(data, query):
    row = route_row(data, query["query_step"])
    route = (row or {}).get("route_memory") or {}
    kind = str(route.get("estimate_kind") or "raw_icp")
    target = route.get("target_anchor_index")
    source = route.get("estimate_source_anchor_index")
    authority = source if kind == "geometry_reconstructed" else target
    attempt = latest_attempt(data, query["query_step"])
    assessment = (
        attempt["assessments"].get(int(authority))
        if attempt is not None and authority is not None
        else None
    )
    trusted = (
        bool(assessment["jointly_trusted"])
        if assessment is not None
        else None
    )
    distance = route.get("distance_to_start_m")
    if distance is None:
        distance = query.get("authority_d")
    if distance is None:
        return None, trusted
    return SimpleNamespace(
        distance_to_start_m=float(distance),
        relocalization_confidence=float(
            route.get("relocalization_confidence")
            or query.get("confidence")
            or 0.0
        ),
        filter_std_m=route.get("filter_std_m"),
        source=str(route.get("source") or "anchor_relocalization"),
        target_anchor_index=target,
        estimate_kind=kind,
        estimate_role="next",
        estimate_source_anchor_index=source,
        estimate_edge_hop_count=int(
            route.get("estimate_edge_hop_count") or 0
        ),
        evidence_age_updates=route.get("evidence_age_updates"),
    ), trusted


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--forensics", type=Path, default=DEFAULT_FORENSICS)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    stop_gate = load_module(
        "terminal_stop_gate_replay",
        ROOT / "policy_v2_live_candidate" / "scripts" / "stop_gate.py",
    )
    forensics = load_module("route2_forensics_replay", args.forensics)

    episode_reports = []
    all_decisions = Counter()
    unsafe_accepts = []
    authorized_inside_resumes = []
    for episode in EPISODES:
        data = forensics.episode_data(episode)
        gate = stop_gate.ReturnStopGate()
        decisions = []
        for query in data["stop_queries"]:
            row = route_row(data, query["query_step"])
            if row is not None:
                gate.notify_sim_step(row["position"])
            progress, trusted = progress_and_trust(data, query)
            decision = gate.check(
                progress,
                vlm_issued_stop=True,
                evidence_trusted=trusted,
                home_visual_probe=lambda: None,
            )
            record = {
                "query_step": int(query["query_step"]),
                "true_distance_m": float(query["true_distance"]),
                "historical_decision": query["decision"],
                "new_decision": decision.decision,
                "new_state": decision.state,
                "reason": decision.reason,
                "evidence_authority": decision.evidence_authority,
                "route2_trusted": trusted,
            }
            decisions.append(record)
            all_decisions[decision.decision] += 1
            if (
                decision.decision in {"accepted", "forced"}
                and record["true_distance_m"] > gate.r_in
            ):
                unsafe_accepts.append({"episode": episode, **record})
            if (
                decision.reason
                == "fresh_authorized_interval_definitely_outside"
                and record["true_distance_m"] <= gate.r_in
            ):
                authorized_inside_resumes.append(
                    {"episode": episode, **record}
                )
            if decision.decision == "safe_fail":
                break
        episode_reports.append({
            "episode": episode,
            "recorded_stop_queries": len(decisions),
            "historical_counts": dict(Counter(
                decision["historical_decision"] for decision in decisions
            )),
            "new_counts": dict(Counter(
                decision["new_decision"] for decision in decisions
            )),
            "final_new_state": gate.state,
            "decisions": decisions,
        })

    report = {
        "schema": "navila-terminal-stop-gate-counterfactual-v1",
        "scope": list(EPISODES),
        "dynamics_replay": False,
        "home_visual_signal_replayed": False,
        "new_decision_counts": dict(all_decisions),
        "unsafe_outside_accepts": unsafe_accepts,
        "authorized_inside_resumes": authorized_inside_resumes,
        "episodes": episode_reports,
    }
    text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    print(text, end="")
    if unsafe_accepts or authorized_inside_resumes:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
