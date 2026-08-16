"""Approach A: hand-crafted geometric features from each anchor's own point
cloud (self-contained -- no correspondence to another anchor needed), extending
relocalization.py's corridor_degeneracy_ratio / compute_anchor_alias_scores
ideas. Computes one feature row per (episode_idx, anchor_index) label row in
anchor_labels.json.
"""
from __future__ import annotations

import json
import math
import os
import sys
import time

SCRIPTS_DIR = "/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/scripts"
sys.path.insert(0, SCRIPTS_DIR)
import numpy as np
from relocalization import corridor_degeneracy_ratio, icp_seed_sweep_2d

OUT_DIR = os.path.dirname(os.path.abspath(__file__))
LABELS_PATH = os.path.join(OUT_DIR, "anchor_labels.json")
OUT_PATH = os.path.join(OUT_DIR, "features_a.json")
PROGRESS_PATH = os.path.join(OUT_DIR, "features_a_progress.log")

# self-alias seeds: does this cloud match ITSELF well at a non-zero rotation?
# (skip angles very close to 0/360 -- that's the trivial identity match)
SELF_ALIAS_YAWS_DEG = [30, 60, 90, 120, 150, 180, 210, 240, 270, 300, 330]


def log(msg: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(PROGRESS_PATH, "a") as f:
        f.write(line + "\n")


def normal_direction_entropy(xy: np.ndarray, k: int = 8, n_bins: int = 18) -> float | None:
    """Entropy (bits) of the local-surface-normal-angle histogram, sign-folded
    to [0, pi) since a normal and its negation describe the same surface.
    Low entropy = every point's normal points the same way (flat wall /
    corridor -- degenerate for ICP translation along that wall). High entropy
    = normals spread across many directions (corners, clutter, doorways --
    well-constrained). Generalizes corridor_degeneracy_ratio's 2-eigenvalue
    summary into a finer-grained multi-direction histogram (catches e.g. an
    L-shaped corner with exactly two dominant directions, which the 2x2
    scatter-matrix ratio can't distinguish from omnidirectional clutter)."""
    n = len(xy)
    if n < k + 1:
        return None
    diff = xy[:, None, :] - xy[None, :, :]
    dist2 = np.einsum("ijk,ijk->ij", diff, diff)
    np.fill_diagonal(dist2, np.inf)
    neighbor_idx = np.argpartition(dist2, k, axis=1)[:, :k]
    angles = []
    for i in range(n):
        patch = xy[neighbor_idx[i]]
        patch = patch - patch.mean(axis=0)
        cov = (patch.T @ patch) / max(1, len(patch) - 1)
        eigvals, eigvecs = np.linalg.eigh(cov)
        normal = eigvecs[:, 0]
        if np.linalg.norm(normal) < 1e-9:
            continue
        ang = math.atan2(normal[1], normal[0]) % math.pi  # fold +/-n
        angles.append(ang)
    if len(angles) < 8:
        return None
    hist, _ = np.histogram(angles, bins=n_bins, range=(0, math.pi))
    p = hist / hist.sum()
    p = p[p > 0]
    return float(-(p * np.log2(p)).sum())


def self_alias_score(xy: np.ndarray) -> float | None:
    """Best ICP overlap_ratio this cloud achieves matching against ITSELF at
    a non-zero rotation. High score = the cloud has repeating/periodic
    structure that a non-identity transform can still explain well --
    directly analogous to compute_anchor_alias_scores' cross-anchor version
    but self-referential, so it needs only this one anchor's point cloud
    (no access to neighboring anchors required)."""
    if len(xy) < 12:
        return None
    yaw_inits = [math.radians(d) for d in SELF_ALIAS_YAWS_DEG]
    try:
        scored_results, _basin_summary, _basin_metrics = icp_seed_sweep_2d(
            xy, xy, yaw_inits, max_iterations=12, correspondence_threshold_m=0.45,
            objective="point_to_point",
        )
    except Exception:
        return None
    if not scored_results:
        return None
    _score, result = max(scored_results, key=lambda item: item[0])
    return float(result["overlap_ratio"])


def extract_features(row: dict) -> dict | None:
    pts = np.asarray(row["points_xyz"], dtype=np.float64)
    if pts.ndim != 2 or pts.shape[0] < 12:
        return None
    xy = pts[:, :2]
    z = pts[:, 2] if pts.shape[1] > 2 else np.zeros(len(pts))
    n = len(pts)

    centroid = xy.mean(axis=0)
    xy_c = xy - centroid
    cov = (xy_c.T @ xy_c) / max(1, n - 1)
    eigvals = np.linalg.eigvalsh(cov)
    lam_min, lam_max = float(eigvals[0]), float(eigvals[1])
    condition_number = lam_max / (lam_min + 1e-9)
    elongation = 1.0 - lam_min / (lam_max + 1e-9)

    bbox_x = float(xy[:, 0].max() - xy[:, 0].min())
    bbox_y = float(xy[:, 1].max() - xy[:, 1].min())
    bbox_z = float(z.max() - z.min())
    bbox_area = max(bbox_x * bbox_y, 1e-6)
    density = n / bbox_area

    try:
        hull_radius = float(np.percentile(np.linalg.norm(xy_c, axis=1), 90))
    except Exception:
        hull_radius = float(np.linalg.norm(xy_c, axis=1).max()) if n else 0.0

    cdr = corridor_degeneracy_ratio(pts, k=8)
    nde = normal_direction_entropy(xy, k=8, n_bins=18)
    sas = self_alias_score(xy)

    return dict(
        episode_idx=row["episode_idx"],
        anchor_index=row["anchor_index"],
        n_points=n,
        distance_from_start_m=row["distance_from_start_m"],
        pca_lambda_min=lam_min,
        pca_lambda_max=lam_max,
        pca_condition_number=condition_number,
        pca_elongation=elongation,
        bbox_x=bbox_x,
        bbox_y=bbox_y,
        bbox_z=bbox_z,
        bbox_aspect=bbox_x / (bbox_y + 1e-6),
        point_density=density,
        radius_p90=hull_radius,
        z_std=float(z.std()),
        z_range=bbox_z,
        corridor_degeneracy_ratio=cdr if cdr is not None else -1.0,
        corridor_degeneracy_available=1.0 if cdr is not None else 0.0,
        normal_direction_entropy=nde if nde is not None else -1.0,
        normal_direction_entropy_available=1.0 if nde is not None else 0.0,
        self_alias_score=sas if sas is not None else -1.0,
        self_alias_score_available=1.0 if sas is not None else 0.0,
        good_fraction=row["good_fraction"],
        n_observations=row["n_observations"],
    )


def main():
    with open(LABELS_PATH) as f:
        labels = json.load(f)
    log(f"loaded {len(labels)} label rows, extracting geometric features...")
    out = []
    t0 = time.time()
    for i, row in enumerate(labels):
        try:
            feat = extract_features(row)
        except Exception as exc:
            log(f"  ep{row.get('episode_idx')}/a{row.get('anchor_index')} FAILED: {type(exc).__name__}: {exc}")
            feat = None
        if feat is not None:
            out.append(feat)
        if (i + 1) % 100 == 0 or i == len(labels) - 1:
            elapsed = time.time() - t0
            log(f"[{i+1}/{len(labels)}] elapsed {elapsed/60:.1f}min, ok rows: {len(out)}")
            with open(OUT_PATH, "w") as f:
                json.dump(out, f)
    with open(OUT_PATH, "w") as f:
        json.dump(out, f)
    log(f"ALL DONE. total feature rows: {len(out)}")


if __name__ == "__main__":
    main()
