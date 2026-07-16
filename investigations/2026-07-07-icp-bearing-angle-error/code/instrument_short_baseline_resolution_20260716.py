"""2026-07-16: instruments _check_short_baseline_yaw_disambiguation directly
(monkeypatch) to count None/True/False outcomes per call -- a more sensitive,
faster-to-observe signal than the final "flagged unreliable" fire rate, since
resolving as True (agree) vs never resolving at all are conflated by that
metric alone. Confirms whether require_resolution=True actually increases how
often the pending check gets a chance to resolve at all, before looking at
the rarer disagreement sub-case."""
import sys

SCRIPTS_DIR = "/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/scripts"
sys.path.insert(0, SCRIPTS_DIR)

import route_memory_agent  # noqa: E402
from offline_replay import replay_episode  # noqa: E402

_counts = {"none": 0, "true": 0, "false": 0}
_orig = route_memory_agent.RouteMemoryAgent._check_short_baseline_yaw_disambiguation


def _wrapped(self, anchor_index, raw_estimate):
    result = _orig(self, anchor_index, raw_estimate)
    if result is None:
        _counts["none"] += 1
    elif result is True:
        _counts["true"] += 1
    else:
        _counts["false"] += 1
    return result


route_memory_agent.RouteMemoryAgent._check_short_baseline_yaw_disambiguation = _wrapped


def run(ep, require_resolution, max_attempts=None):
    _counts["none"] = _counts["true"] = _counts["false"] = 0
    results = replay_episode(
        "icp_replay_capture_hard11_20260706_accumulated", ep, promotion_mode="bounded_evidence",
        short_baseline_disambiguation=True,
        short_baseline_require_resolution=require_resolution,
        short_baseline_stall_attempts=60,
        max_attempts=max_attempts,
    )
    total_calls = sum(_counts.values())
    resolved = _counts["true"] + _counts["false"]
    return dict(
        n_events=len(results) if results else 0,
        calls=total_calls, none=_counts["none"], resolved_true=_counts["true"],
        resolved_false=_counts["false"], resolution_rate=resolved / total_calls if total_calls else 0,
    )


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--episodes", type=int, nargs="+", default=[367])
    parser.add_argument("--max_attempts", type=int, default=None)
    args = parser.parse_args()

    for ep in args.episodes:
        print(f"\n=== ep{ep} ===", flush=True)
        for rr in [False, True]:
            stats = run(ep, rr, max_attempts=args.max_attempts)
            print(f"  require_resolution={rr}: {stats}", flush=True)
