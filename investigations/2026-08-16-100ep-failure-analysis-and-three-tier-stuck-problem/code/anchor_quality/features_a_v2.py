"""features_a v2: adds the REAL cross-anchor alias_score (this anchor's best
ICP overlap against other anchors 2-5 route-positions away, WITHIN THE SAME
episode) -- this is the validated signal from relocalization.py's
compute_anchor_alias_scores docstring (ep187 anchor1 case), which v1's
self-alias-only feature only approximated. Also adds neighbor-spacing
features (distance to the nearest anchor by route index) since sparser
anchors may be intrinsically less prone to cross-anchor confusion.

Motivation (2026-08-16 diagnostic): within-episode variance of good_fraction
(0.081) is larger than between-episode variance (0.054) -- ICC~0.42 -- so
most of the label variation is anchor-specific WITHIN a scene, not just
"this building is hard". A held-out-episode validation split can only use
anchor-level (not scene-level memorized) signal, and a feature that compares
an anchor against its OWN scene's other anchors is exactly the kind of
relative, within-scene signal that should transfer to an unseen building.
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
from relocalization import icp_seed_sweep_2d

OUT_DIR = os.path.dirname(os.path.abspath(__file__))
LABELS_PATH = os.path.join(OUT_DIR, "anchor_labels.json")
FEATURES_A_PATH = os.path.join(OUT_DIR, "features_a.json")
OUT_PATH = os.path.join(OUT_DIR, "features_a_v2.json")
PROGRESS_PATH = os.path.join(OUT_DIR, "features_a_v2_progress.log")

MIN_OFFSET, MAX_OFFSET = 2, 5
ALIAS_YAWS_DEG = list(range(-180, 180, 15))  # matches compute_anchor_alias_scores


def log(msg: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(PROGRESS_PATH, "a") as f:
        f.write(line + "\n")


def main():
    with open(LABELS_PATH) as f:
        labels = json.load(f)
    with open(FEATURES_A_PATH) as f:
        feats_v1 = {(r["episode_idx"], r["anchor_index"]): r for r in json.load(f)}

    by_ep: dict[int, list[dict]] = {}
    for r in labels:
        by_ep.setdefault(r["episode_idx"], []).append(r)

    yaw_inits = [math.radians(d) for d in ALIAS_YAWS_DEG]
    out = []
    t0 = time.time()
    n_ep_done = 0
    for eidx, ep_rows in sorted(by_ep.items()):
        ep_rows = sorted(ep_rows, key=lambda r: r["anchor_index"])
        pts_by_idx = {}
        for r in ep_rows:
            pts = np.asarray(r["points_xyz"], dtype=np.float32)[:, :2]
            if len(pts) >= 12:
                pts_by_idx[r["anchor_index"]] = pts
        xy_by_idx = {r["anchor_index"]: np.asarray(r["world_pose"][:2]) for r in ep_rows}

        cross_alias = {idx: 0.0 for idx in pts_by_idx}
        indices = sorted(pts_by_idx)
        for i, idx_a in enumerate(indices):
            for idx_b in indices[i + 1:]:
                offset = idx_b - idx_a
                if offset < MIN_OFFSET or offset > MAX_OFFSET:
                    continue
                try:
                    scored_results, _bs, _bm = icp_seed_sweep_2d(
                        pts_by_idx[idx_a], pts_by_idx[idx_b], yaw_inits,
                        max_iterations=16, correspondence_threshold_m=0.45,
                        objective="point_to_point",
                    )
                except Exception:
                    continue
                if not scored_results:
                    continue
                _score, result = max(scored_results, key=lambda item: item[0])
                overlap = float(result["overlap_ratio"])
                cross_alias[idx_a] = max(cross_alias[idx_a], overlap)
                cross_alias[idx_b] = max(cross_alias[idx_b], overlap)

        # neighbor spacing: distance (m) to nearest OTHER anchor in this episode by world_pose
        for r in ep_rows:
            idx = r["anchor_index"]
            key = (eidx, idx)
            if key not in feats_v1:
                continue
            base = dict(feats_v1[key])
            base["cross_anchor_alias_score"] = cross_alias.get(idx, -1.0)
            base["cross_anchor_alias_available"] = 1.0 if idx in cross_alias and len(indices) > 1 else 0.0
            other_dists = [
                float(np.linalg.norm(xy_by_idx[idx] - xy_by_idx[j]))
                for j in xy_by_idx if j != idx
            ]
            base["nearest_neighbor_anchor_dist_m"] = min(other_dists) if other_dists else -1.0
            out.append(base)

        n_ep_done += 1
        if n_ep_done % 10 == 0 or n_ep_done == len(by_ep):
            elapsed = time.time() - t0
            log(f"[{n_ep_done}/{len(by_ep)}] episodes, elapsed {elapsed/60:.1f}min, rows so far: {len(out)}")
            with open(OUT_PATH, "w") as f:
                json.dump(out, f)

    with open(OUT_PATH, "w") as f:
        json.dump(out, f)
    log(f"ALL DONE. total rows: {len(out)}")


if __name__ == "__main__":
    main()
