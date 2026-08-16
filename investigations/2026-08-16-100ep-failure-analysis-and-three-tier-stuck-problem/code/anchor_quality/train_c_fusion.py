"""Approach C: true fusion model. Per-point MLP -> global max-pool (same as
approach B's PointNet branch) CONCATENATED with the engineered meta-features
from features_a_v2.json (including the real cross-anchor alias_score and
neighbor-spacing features that gave approach A its 66.3%->68.3% val_acc05
jump) -> joint MLP head. Trained end-to-end, single loss, single optimizer --
this lets the network learn how to combine raw-geometry representation with
the relative/cross-anchor context in one model, instead of B's blind (no
meta-feature input) and instead of post-hoc-averaging A and B's separate
predictions.

Same no-augmentation/no-capacity-control instruction as approach B; same
episode-level 85/15 split (seed=0) as A and B for a fair comparison.
"""
from __future__ import annotations

import json
import os
import time

import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import Dataset, DataLoader

OUT_DIR = os.path.dirname(os.path.abspath(__file__))
LABELS_PATH = os.path.join(OUT_DIR, "anchor_labels.json")
FEATURES_PATH = os.path.join(OUT_DIR, "features_a_v2.json")
MAX_POINTS = 512
DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")

META_COLS = [
    "n_points", "distance_from_start_m", "pca_lambda_min", "pca_lambda_max",
    "pca_condition_number", "pca_elongation", "bbox_x", "bbox_y", "bbox_z",
    "bbox_aspect", "point_density", "radius_p90", "z_std", "z_range",
    "corridor_degeneracy_ratio", "corridor_degeneracy_available",
    "normal_direction_entropy", "normal_direction_entropy_available",
    "self_alias_score", "self_alias_score_available",
    "cross_anchor_alias_score", "cross_anchor_alias_available",
    "nearest_neighbor_anchor_dist_m",
]


class FusionDataset(Dataset):
    def __init__(self, rows, meta_mean, meta_std):
        self.rows = rows
        self.meta_mean = meta_mean
        self.meta_std = meta_std

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, idx):
        row = self.rows[idx]
        pts = np.asarray(row["points_xyz"], dtype=np.float32)
        centroid = pts.mean(axis=0, keepdims=True)
        pts = pts - centroid
        n = len(pts)
        if n < MAX_POINTS:
            pad = np.zeros((MAX_POINTS - n, 3), dtype=np.float32)
            mask = np.concatenate([np.ones(n, dtype=np.float32), np.zeros(MAX_POINTS - n, dtype=np.float32)])
            pts = np.concatenate([pts, pad], axis=0)
        else:
            pts = pts[:MAX_POINTS]
            mask = np.ones(MAX_POINTS, dtype=np.float32)
        meta = np.array([row[c] for c in META_COLS], dtype=np.float32)
        meta = (meta - self.meta_mean) / self.meta_std
        label = np.float32(row["good_fraction"])
        return pts, mask, meta, label


class FusionPointNet(nn.Module):
    """Per-point MLP -> masked global max-pool -> concat with normalized
    meta-features -> joint MLP head. No STN/dropout/augmentation."""

    def __init__(self, n_meta: int):
        super().__init__()
        self.point_mlp = nn.Sequential(
            nn.Linear(3, 64), nn.ReLU(),
            nn.Linear(64, 128), nn.ReLU(),
            nn.Linear(128, 256), nn.ReLU(),
            nn.Linear(256, 512), nn.ReLU(),
        )
        self.head = nn.Sequential(
            nn.Linear(512 + n_meta, 256), nn.ReLU(),
            nn.Linear(256, 128), nn.ReLU(),
            nn.Linear(128, 1),
        )

    def forward(self, pts, mask, meta):
        feat = self.point_mlp(pts)
        feat = feat.masked_fill(mask.unsqueeze(-1) == 0, float("-inf"))
        pooled, _ = feat.max(dim=1)
        fused = torch.cat([pooled, meta], dim=-1)
        out = self.head(fused).squeeze(-1)
        return torch.sigmoid(out)


def main():
    with open(LABELS_PATH) as f:
        label_rows = {(r["episode_idx"], r["anchor_index"]): r for r in json.load(f)}
    with open(FEATURES_PATH) as f:
        feat_rows = json.load(f)

    rows = []
    for r in feat_rows:
        key = (r["episode_idx"], r["anchor_index"])
        if key not in label_rows:
            continue
        merged = dict(r)
        merged["points_xyz"] = label_rows[key]["points_xyz"]
        rows.append(merged)
    print(f"merged {len(rows)} rows (points + meta features)", flush=True)

    episodes = sorted({r["episode_idx"] for r in rows})
    rng = np.random.RandomState(0)  # SAME seed/split as approach A/B for a fair comparison
    rng.shuffle(episodes)
    n_val_eps = max(1, int(0.15 * len(episodes)))
    val_eps = set(episodes[:n_val_eps])
    train_rows = [r for r in rows if r["episode_idx"] not in val_eps]
    val_rows = [r for r in rows if r["episode_idx"] in val_eps]
    print(f"train rows: {len(train_rows)} ({len(episodes) - n_val_eps} episodes), "
          f"val rows: {len(val_rows)} ({n_val_eps} episodes)", flush=True)

    meta_train = np.array([[r[c] for c in META_COLS] for r in train_rows], dtype=np.float32)
    meta_mean = meta_train.mean(axis=0)
    meta_std = meta_train.std(axis=0)
    meta_std[meta_std < 1e-6] = 1.0

    train_ds = FusionDataset(train_rows, meta_mean, meta_std)
    val_ds = FusionDataset(val_rows, meta_mean, meta_std)
    train_loader = DataLoader(train_ds, batch_size=32, shuffle=True, num_workers=2)
    val_loader = DataLoader(val_ds, batch_size=64, shuffle=False, num_workers=2)
    train_eval_loader = DataLoader(train_ds, batch_size=64, shuffle=False)

    model = FusionPointNet(n_meta=len(META_COLS)).to(DEVICE)
    opt = torch.optim.Adam(model.parameters(), lr=1e-3)
    loss_fn = nn.MSELoss()

    n_epochs = 200
    t0 = time.time()
    best_val_mae = float("inf")
    best_epoch_stats = None
    for epoch in range(n_epochs):
        model.train()
        train_losses = []
        for pts, mask, meta, label in train_loader:
            pts, mask, meta, label = pts.to(DEVICE), mask.to(DEVICE), meta.to(DEVICE), label.to(DEVICE)
            opt.zero_grad()
            pred = model(pts, mask, meta)
            loss = loss_fn(pred, label)
            loss.backward()
            opt.step()
            train_losses.append(loss.item())

        model.eval()
        val_preds, val_labels = [], []
        train_preds, train_labels = [], []
        with torch.no_grad():
            for pts, mask, meta, label in val_loader:
                pts, mask, meta = pts.to(DEVICE), mask.to(DEVICE), meta.to(DEVICE)
                pred = model(pts, mask, meta).cpu().numpy()
                val_preds.extend(pred.tolist())
                val_labels.extend(label.numpy().tolist())
            for pts, mask, meta, label in train_eval_loader:
                pts, mask, meta = pts.to(DEVICE), mask.to(DEVICE), meta.to(DEVICE)
                pred = model(pts, mask, meta).cpu().numpy()
                train_preds.extend(pred.tolist())
                train_labels.extend(label.numpy().tolist())

        val_preds_arr, val_labels_arr = np.array(val_preds), np.array(val_labels)
        train_preds_arr, train_labels_arr = np.array(train_preds), np.array(train_labels)
        val_mae = float(np.mean(np.abs(val_preds_arr - val_labels_arr)))
        train_mae = float(np.mean(np.abs(train_preds_arr - train_labels_arr)))
        val_corr = float(np.corrcoef(val_preds_arr, val_labels_arr)[0, 1]) if val_labels_arr.std() > 1e-6 else float("nan")
        val_acc = float(np.mean((val_preds_arr >= 0.5) == (val_labels_arr >= 0.5)))

        if val_mae < best_val_mae:
            best_val_mae = val_mae
            best_epoch_stats = dict(epoch=epoch, val_mae=val_mae, val_corr=val_corr, val_acc05=val_acc, train_mae=train_mae)
            torch.save(model.state_dict(), os.path.join(OUT_DIR, "fusion_best.pt"))

        if epoch % 5 == 0 or epoch == n_epochs - 1:
            elapsed = time.time() - t0
            print(f"[epoch {epoch:3d}] elapsed {elapsed:.0f}s train_loss={np.mean(train_losses):.4f} "
                  f"train_mae={train_mae:.4f} val_mae={val_mae:.4f} val_corr={val_corr:.3f} val_acc05={val_acc:.3f}",
                  flush=True)

    print(f"DONE. best_val_mae={best_val_mae:.4f} at {best_epoch_stats}", flush=True)
    with open(os.path.join(OUT_DIR, "fusion_result.json"), "w") as f:
        json.dump(dict(
            n_train=len(train_rows), n_val=len(val_rows), best=best_epoch_stats,
            final_train_mae=train_mae, final_val_mae=val_mae, final_val_corr=val_corr, final_val_acc05=val_acc,
        ), f, indent=2)


if __name__ == "__main__":
    main()
