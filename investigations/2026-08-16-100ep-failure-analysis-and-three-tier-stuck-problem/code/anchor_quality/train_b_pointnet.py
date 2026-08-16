"""Approach B: direct end-to-end point-cloud model. Raw (x,y,z) points ->
learned classifier/regressor, trained straight on anchor_labels.json's
points_xyz + good_fraction. Per user's explicit instruction (2026-08-16): no
data augmentation, no capacity control for this first pass -- if it overfits
the current ~1679 anchors and gets very good numbers on them, that's treated
as progress in itself, not a failure to guard against.

Architecture: simplified PointNet (per-point MLP -> global max-pool ->
regression head). No STN (spatial transformer), no dropout, no weight decay,
no augmentation -- deliberately minimal per instruction above.
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
MAX_POINTS = 512
DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")


class AnchorPointCloudDataset(Dataset):
    def __init__(self, rows):
        self.rows = rows

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, idx):
        row = self.rows[idx]
        pts = np.asarray(row["points_xyz"], dtype=np.float32)
        centroid = pts.mean(axis=0, keepdims=True)
        pts = pts - centroid  # center; NOT scale-normalized (scale is signal: dense vs sparse room)
        n = len(pts)
        if n < MAX_POINTS:
            pad = np.zeros((MAX_POINTS - n, 3), dtype=np.float32)
            mask = np.concatenate([np.ones(n, dtype=np.float32), np.zeros(MAX_POINTS - n, dtype=np.float32)])
            pts = np.concatenate([pts, pad], axis=0)
        else:
            pts = pts[:MAX_POINTS]
            mask = np.ones(MAX_POINTS, dtype=np.float32)
        label = np.float32(row["good_fraction"])
        return pts, mask, label


class SimplePointNet(nn.Module):
    """Per-point MLP (shared weights, i.e. 1x1 conv) -> masked global max-pool
    -> MLP regression head, sigmoid-clamped to [0,1] (good_fraction is a
    fraction). No STN/dropout/batchnorm-affine-freeze/augmentation."""

    def __init__(self):
        super().__init__()
        self.point_mlp = nn.Sequential(
            nn.Linear(3, 64), nn.ReLU(),
            nn.Linear(64, 128), nn.ReLU(),
            nn.Linear(128, 256), nn.ReLU(),
            nn.Linear(256, 512), nn.ReLU(),
        )
        self.head = nn.Sequential(
            nn.Linear(512, 256), nn.ReLU(),
            nn.Linear(256, 128), nn.ReLU(),
            nn.Linear(128, 1),
        )

    def forward(self, pts, mask):
        # pts: (B, N, 3), mask: (B, N)
        feat = self.point_mlp(pts)  # (B, N, 512)
        feat = feat.masked_fill(mask.unsqueeze(-1) == 0, float("-inf"))
        pooled, _ = feat.max(dim=1)  # (B, 512)
        out = self.head(pooled).squeeze(-1)  # (B,)
        return torch.sigmoid(out)


def main():
    with open(LABELS_PATH) as f:
        rows = json.load(f)
    print(f"loaded {len(rows)} rows", flush=True)

    # episode-level split so the held-out numbers mean something (features
    # from anchors of the SAME episode share building geometry); still no
    # augmentation/capacity-control on the model itself per instruction.
    episodes = sorted({r["episode_idx"] for r in rows})
    rng = np.random.RandomState(0)
    rng.shuffle(episodes)
    n_val_eps = max(1, int(0.15 * len(episodes)))
    val_eps = set(episodes[:n_val_eps])
    train_rows = [r for r in rows if r["episode_idx"] not in val_eps]
    val_rows = [r for r in rows if r["episode_idx"] in val_eps]
    print(f"train rows: {len(train_rows)} ({len(episodes) - n_val_eps} episodes), "
          f"val rows: {len(val_rows)} ({n_val_eps} episodes)", flush=True)

    train_ds = AnchorPointCloudDataset(train_rows)
    val_ds = AnchorPointCloudDataset(val_rows)
    train_loader = DataLoader(train_ds, batch_size=32, shuffle=True, num_workers=2)
    val_loader = DataLoader(val_ds, batch_size=64, shuffle=False, num_workers=2)

    model = SimplePointNet().to(DEVICE)
    opt = torch.optim.Adam(model.parameters(), lr=1e-3)  # no weight_decay
    loss_fn = nn.MSELoss()

    n_epochs = 200
    t0 = time.time()
    best_val_mae = float("inf")
    for epoch in range(n_epochs):
        model.train()
        train_losses = []
        for pts, mask, label in train_loader:
            pts, mask, label = pts.to(DEVICE), mask.to(DEVICE), label.to(DEVICE)
            opt.zero_grad()
            pred = model(pts, mask)
            loss = loss_fn(pred, label)
            loss.backward()
            opt.step()
            train_losses.append(loss.item())

        model.eval()
        val_preds, val_labels = [], []
        train_preds, train_labels = [], []
        with torch.no_grad():
            for pts, mask, label in val_loader:
                pts, mask = pts.to(DEVICE), mask.to(DEVICE)
                pred = model(pts, mask).cpu().numpy()
                val_preds.extend(pred.tolist())
                val_labels.extend(label.numpy().tolist())
            for pts, mask, label in DataLoader(train_ds, batch_size=64, shuffle=False):
                pts, mask = pts.to(DEVICE), mask.to(DEVICE)
                pred = model(pts, mask).cpu().numpy()
                train_preds.extend(pred.tolist())
                train_labels.extend(label.numpy().tolist())
        val_mae = float(np.mean(np.abs(np.array(val_preds) - np.array(val_labels)))) if val_preds else float("nan")
        train_mae = float(np.mean(np.abs(np.array(train_preds) - np.array(train_labels))))
        val_labels_arr = np.array(val_labels)
        val_preds_arr = np.array(val_preds)
        if len(val_labels_arr) > 1 and val_labels_arr.std() > 1e-6:
            val_corr = float(np.corrcoef(val_preds_arr, val_labels_arr)[0, 1])
        else:
            val_corr = float("nan")
        # binary good/bad accuracy at 0.5 threshold
        val_acc = float(np.mean((val_preds_arr >= 0.5) == (val_labels_arr >= 0.5))) if val_preds else float("nan")

        if val_mae < best_val_mae:
            best_val_mae = val_mae
            torch.save(model.state_dict(), os.path.join(OUT_DIR, "pointnet_best.pt"))

        if epoch % 5 == 0 or epoch == n_epochs - 1:
            elapsed = time.time() - t0
            print(f"[epoch {epoch:3d}] elapsed {elapsed:.0f}s train_loss={np.mean(train_losses):.4f} "
                  f"train_mae={train_mae:.4f} val_mae={val_mae:.4f} val_corr={val_corr:.3f} val_acc05={val_acc:.3f}",
                  flush=True)

    print(f"DONE. best_val_mae={best_val_mae:.4f}", flush=True)
    with open(os.path.join(OUT_DIR, "pointnet_result.json"), "w") as f:
        json.dump(dict(
            best_val_mae=best_val_mae, n_train=len(train_rows), n_val=len(val_rows),
            train_episodes=len(episodes) - n_val_eps, val_episodes=n_val_eps,
            final_train_mae=train_mae, final_val_mae=val_mae, final_val_corr=val_corr, final_val_acc05=val_acc,
        ), f, indent=2)


if __name__ == "__main__":
    main()
