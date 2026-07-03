"""Visualize LiDAR/local-map anchor-match ICP alignments from a round-trip
measurement JSON, to diagnose *why* matches picked the wrong anchor or pose.

The scalar metrics already recorded in ``route_relocalization_diagnostics``
(overlap ratio, median residual, bearing/vector error) say a match was bad but
not what the two point clouds actually looked like. This script samples 10-20
accepted anchor matches spread evenly across a trajectory and renders each one
as a scatter plot: the current local map, the anchor's local map transformed
into the current frame by the ICP alignment, and which anchor points actually
found a close correspondence (inlier, drawn in red) vs. did not.

Requires ``--capture_anchor_match_snapshots`` to have been passed to
round_trip_eval.py for the run being inspected (off by default; see that
flag's help text) -- without it, covisibility records carry only scalar
metrics and this script has nothing to plot.

Run with (no Isaac Sim / conda env required, pure numpy + matplotlib):
    python3 scripts/plot_anchor_match_diagnostics.py \
        --measurement_file eval_results/.../measurements/output_280.json \
        --num_samples 15
"""

from __future__ import annotations

import argparse
import json
import math
import os
from typing import Optional

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


def _iter_covisibility_records(diagnostics: dict):
    """Yield (source_label, record) for every covisibility record reachable
    from a route_relocalization_diagnostics dict, including the nested
    per-backend diagnostics the ``fused`` backend stores its LiDAR side under
    (``fused_lidar_diagnostics``). RGB-D/LoFTR records never carry a
    ``match_snapshot`` (that backend matches sparse features, not point
    clouds), so they are skipped even if present.
    """
    if not isinstance(diagnostics, dict):
        return
    for record in diagnostics.get("covisibility_records", []) or []:
        yield "top_level", record
    nested = diagnostics.get("fused_lidar_diagnostics")
    if isinstance(nested, dict):
        for record in nested.get("covisibility_records", []) or []:
            yield "fused_lidar", record


def _sample_evenly(items: list, num_samples: int) -> list:
    if num_samples <= 0 or len(items) <= num_samples:
        return items
    idx = np.linspace(0, len(items) - 1, num_samples)
    seen = set()
    sampled = []
    for i in idx:
        i = int(round(i))
        if i not in seen:
            seen.add(i)
            sampled.append(items[i])
    return sampled


def _plot_one_match(record: dict, source_label: str, out_path: str) -> None:
    snapshot = record["match_snapshot"]
    anchor_points = np.asarray(snapshot["anchor_points_body"], dtype=np.float32)
    current_points = np.asarray(snapshot["current_points_body"], dtype=np.float32)
    theta = float(snapshot["theta_rad"])
    translation = np.asarray(snapshot["translation"], dtype=np.float32)
    inlier_mask = np.asarray(snapshot["anchor_inlier_mask"], dtype=bool)

    c, s = math.cos(theta), math.sin(theta)
    rotation = np.asarray([[c, -s], [s, c]], dtype=np.float32)
    anchor_in_current_frame = anchor_points[:, :2] @ rotation.T + translation

    fig, ax = plt.subplots(figsize=(6.5, 6.5))
    ax.scatter(
        current_points[:, 0], current_points[:, 1],
        s=10, c="#1f77b4", alpha=0.7, label=f"current local map (n={len(current_points)})",
    )
    if np.any(~inlier_mask):
        ax.scatter(
            anchor_in_current_frame[~inlier_mask, 0], anchor_in_current_frame[~inlier_mask, 1],
            s=14, c="#888888", alpha=0.6, marker="x",
            label=f"anchor, unmatched (n={int((~inlier_mask).sum())})",
        )
    if np.any(inlier_mask):
        ax.scatter(
            anchor_in_current_frame[inlier_mask, 0], anchor_in_current_frame[inlier_mask, 1],
            s=16, c="#d62728", label=f"anchor, matched/inlier (n={int(inlier_mask.sum())})",
        )
    ax.scatter([0], [0], s=90, c="#2ca02c", marker="^", zorder=5, label="robot (current frame origin)")

    anchor_index = record.get("anchor_index")
    backend = record.get("matcher_backend", "?")
    overlap = record.get("overlap_ratio")
    residual = record.get("median_residual_m")
    confidence = record.get("confidence")
    dtheta_deg = record.get("estimated_anchor_dtheta_deg")
    bearing_deg = record.get("estimated_bearing_to_anchor_deg")
    dist_m = record.get("estimated_distance_to_anchor_m")
    degeneracy = record.get("corridor_degeneracy_ratio")

    title_lines = [
        f"anchor {anchor_index}  |  backend={backend}  |  source={source_label}  |  attempt={record.get('attempt')}",
        f"overlap={overlap:.2f}  median_residual={residual:.3f} m  confidence={confidence:.2f}"
        if overlap is not None and residual is not None and confidence is not None else "",
        f"dtheta={dtheta_deg:.1f} deg  bearing_to_anchor={bearing_deg:.1f} deg  distance_to_anchor={dist_m:.2f} m"
        if dtheta_deg is not None and bearing_deg is not None and dist_m is not None else "",
        f"corridor_degeneracy_ratio={degeneracy:.3f} (near 0 = degenerate corridor)" if degeneracy is not None else "",
    ]
    ax.set_title("\n".join(line for line in title_lines if line), fontsize=9)
    ax.set_xlabel("x (m, body frame)")
    ax.set_ylabel("y (m, body frame)")
    ax.set_aspect("equal", adjustable="datalim")
    ax.legend(fontsize=7, loc="best")
    ax.grid(True, alpha=0.25)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def plot_anchor_match_diagnostics(measurement_file: str, output_dir: Optional[str], num_samples: int) -> list:
    with open(measurement_file, "r", encoding="utf-8") as f:
        measurement = json.load(f)

    # round_trip_eval.py nests everything round-trip-specific (including
    # route_relocalization_diagnostics) under a "round_trip" key alongside the
    # standard single-episode VLN metrics (success/spl/distance_to_goal/...);
    # fall back to top level for measurement files that aren't nested this way.
    round_trip = measurement.get("round_trip")
    container = round_trip if isinstance(round_trip, dict) else measurement
    diagnostics = container.get("route_relocalization_diagnostics") or {}
    all_records = [
        (source_label, record)
        for source_label, record in _iter_covisibility_records(diagnostics)
        if isinstance(record, dict) and "match_snapshot" in record
    ]
    if not all_records:
        raise SystemExit(
            "No covisibility records with a 'match_snapshot' were found. "
            "Re-run round_trip_eval.py with --capture_anchor_match_snapshots for this episode."
        )

    sampled = _sample_evenly(all_records, num_samples)

    if output_dir is None:
        output_dir = os.path.join(os.path.dirname(measurement_file), "anchor_match_plots")
    os.makedirs(output_dir, exist_ok=True)

    base = os.path.splitext(os.path.basename(measurement_file))[0]
    saved_paths = []
    for i, (source_label, record) in enumerate(sampled):
        attempt = record.get("attempt", "na")
        anchor_index = record.get("anchor_index", "na")
        out_path = os.path.join(
            output_dir, f"{base}_sample{i:02d}_attempt{attempt}_anchor{anchor_index}.png"
        )
        _plot_one_match(record, source_label, out_path)
        saved_paths.append(out_path)

    print(f"Loaded {len(all_records)} anchor-match records with point-cloud snapshots.")
    print(f"Saved {len(saved_paths)} plots to {output_dir}:")
    for path in saved_paths:
        print(f"  {path}")
    return saved_paths


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--measurement_file", required=True, help="Path to a round_trip_eval measurements/*.json file.")
    parser.add_argument(
        "--output_dir", default=None,
        help="Directory to save plots to (default: 'anchor_match_plots/' next to the measurement file).",
    )
    parser.add_argument("--num_samples", type=int, default=15, help="Number of anchor matches to sample and plot (10-20 typical).")
    args = parser.parse_args()
    plot_anchor_match_diagnostics(args.measurement_file, args.output_dir, args.num_samples)


if __name__ == "__main__":
    main()
