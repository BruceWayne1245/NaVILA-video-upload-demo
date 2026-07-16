"""2026-07-16: offline validation of --sequential_pair_short_baseline_require_resolution
against the same hard-anchor icp_replay_dataset captures used to originally
diagnose short-baseline disambiguation's 0.1% fire rate / 0% recall
(investigations/2026-07-13-icp-bearing-error-cross-batch-deep-dive/FINDINGS.md).

For each episode, replays with short_baseline_disambiguation=True and
require_resolution=False (baseline) vs True (fixed), and reports:
  - fire rate: fraction of accepted events with anchor_heading_reliable=False
  - recall: of true bearing_error>45deg events, fraction flagged unreliable
  - precision: of flagged-unreliable events, fraction that are true bearing_error>45deg

Uses the now-fixed offline_replay.py harness (2026-07-16, real per-step motion
via update_return_motion) -- the OLD harness would have shown 0% fire rate
regardless of this flag, since travel_dist_m was always frozen at 0.0.
"""
import json
import math
import sys

from offline_replay import replay_episode, wrap_angle


EPISODES = [4, 5, 187, 367, 368, 408, 994, 1040]
BATCH = "icp_replay_capture_hard11_20260706_accumulated"


def bearing_error(true_bearing, reported_bearing):
    if true_bearing is None or reported_bearing is None:
        return None
    return abs(wrap_angle(math.radians(true_bearing - reported_bearing)))


def analyze(results):
    accepted = [r for r in results if r["accepted"] and r["true_bearing_deg"] is not None]
    n = len(accepted)
    if n == 0:
        return None
    errs = []
    flagged = []
    for r in accepted:
        err_rad = bearing_error(r["true_bearing_deg"], r["reported_bearing_deg"])
        err_deg = math.degrees(err_rad) if err_rad is not None else None
        errs.append(err_deg)
        flagged.append(r["anchor_heading_reliable"] is False)

    fire_rate = sum(flagged) / n
    catastrophic = [e is not None and e > 45.0 for e in errs]
    n_cat = sum(catastrophic)
    n_flagged = sum(flagged)
    tp = sum(1 for f, c in zip(flagged, catastrophic) if f and c)
    recall = tp / n_cat if n_cat else None
    precision = tp / n_flagged if n_flagged else None
    return dict(n=n, fire_rate=fire_rate, n_catastrophic=n_cat, n_flagged=n_flagged,
                recall=recall, precision=precision)


def main():
    summary = {}
    for ep in EPISODES:
        print(f"\n{'='*70}\nEPISODE {ep}\n{'='*70}", flush=True)
        ep_result = {}
        for require_resolution in [False, True]:
            label = "require_resolution=" + str(require_resolution)
            print(f"  running {label} ...", flush=True)
            results = replay_episode(
                BATCH, ep, promotion_mode="bounded_evidence",
                short_baseline_disambiguation=True,
                short_baseline_require_resolution=require_resolution,
                short_baseline_stall_attempts=60,
            )
            if results is None:
                print(f"    ep{ep}: capture not found/corrupted, skipping")
                ep_result[require_resolution] = None
                continue
            stats = analyze(results)
            ep_result[require_resolution] = stats
            if stats:
                print(f"    n={stats['n']} fire_rate={stats['fire_rate']*100:.2f}% "
                      f"n_catastrophic(>45deg)={stats['n_catastrophic']} "
                      f"recall={stats['recall']*100:.1f}%" if stats['recall'] is not None else
                      f"    n={stats['n']} fire_rate={stats['fire_rate']*100:.2f}% n_catastrophic=0",
                      flush=True)
                if stats['precision'] is not None:
                    print(f"    precision={stats['precision']*100:.1f}%", flush=True)
        summary[ep] = ep_result
        with open("/tmp/short_baseline_require_resolution_validation_20260716.json", "w") as f:
            json.dump(summary, f, indent=2)

    print("\n\n" + "="*70)
    print("POOLED SUMMARY")
    print("="*70)
    for require_resolution in [False, True]:
        total_n = total_cat = total_flagged = total_tp = 0
        for ep, ep_result in summary.items():
            stats = ep_result.get(require_resolution)
            if not stats:
                continue
            total_n += stats["n"]
            total_cat += stats["n_catastrophic"]
            total_flagged += stats["n_flagged"]
            if stats["recall"] is not None:
                total_tp += round(stats["recall"] * stats["n_catastrophic"])
        fire_rate = total_flagged / total_n if total_n else 0
        recall = total_tp / total_cat if total_cat else None
        precision = total_tp / total_flagged if total_flagged else None
        print(f"require_resolution={require_resolution}: n={total_n} fire_rate={fire_rate*100:.2f}% "
              f"n_catastrophic={total_cat} recall={f'{recall*100:.1f}%' if recall is not None else 'n/a'} "
              f"precision={f'{precision*100:.1f}%' if precision is not None else 'n/a'}")


if __name__ == "__main__":
    main()
