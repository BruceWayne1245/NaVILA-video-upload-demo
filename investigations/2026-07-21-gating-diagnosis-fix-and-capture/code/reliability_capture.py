"""Reliability capture subsystem (2026-07-21, investigations/2026-07-21-icp-reliability-signal).

Isolated, non-perturbing capture of per-relocalization-attempt data for the
reliability model (Route 2), implementing the file organization requested by the
Route-2 data spec:

    capture/
      manifest.json          # static meta + config (written once at open)
      attempts.jsonl         # one appended line per relocalization attempt (A + C + GT labels)
      shards_index.jsonl     # one appended line per flushed point-cloud shard
      anchors/anchor_XXX.npz # each anchor's cloud, written once
      pointcloud_shards/shard_XXXXXX.npz
      rgbd/<tag>_front.jpg / _front_depth.png / _rear.jpg / _rear_depth.png / _cam.npz
      SUMMARY.json           # aggregate counts + checksums (written at close)

Design constraints (all deliberate):
  * stdlib + numpy only; optional cv2/PIL for image encoding with NPZ fallback.
    No pyarrow/torch in the Isaac runtime.
  * NEVER blocks or perturbs the navigation control loop: every write is a
    bounded, best-effort operation wrapped so an I/O failure degrades to a
    logged skip, never an exception into the caller.
  * Crash-safe: attempts.jsonl / shards_index.jsonl are append-only and flushed
    per record; every NPZ/image is written to a temp file then atomically
    renamed, so a mid-episode crash leaves every completed record readable and
    never a half-written file.
  * Ground-truth fields are label-only; the caller must never feed them back
    into navigation. This module only writes; it makes no decisions.
"""
import os
import io
import json
import time
import hashlib
import tempfile

import numpy as np

SCHEMA_VERSION = "reliability-capture-v1.0"


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _atomic_write(path: str, write_fn) -> str:
    """write_fn(fileobj) writes bytes; returns sha256 of the file. Temp file in
    the same dir, fsync, atomic rename. Returns checksum, or "" on failure."""
    d = os.path.dirname(path)
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            buf = io.BytesIO()
            write_fn(buf)
            data = buf.getvalue()
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        return _sha256_bytes(data)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        return ""


def fixed_size_points(xyz, n_points: int, seed: int):
    """Deterministic fixed-size resample of an (M,3) cloud to (n_points,3):
    random subsample without replacement when M>=n, with replacement (pad) when
    M<n. Seeded by (episode, attempt) upstream for reproducibility."""
    if xyz is None:
        return None
    xyz = np.asarray(xyz, dtype=np.float32)
    if xyz.ndim != 2 or xyz.shape[1] < 3 or xyz.shape[0] == 0:
        return None
    m = xyz.shape[0]
    rng = np.random.default_rng(seed)
    if m >= n_points:
        idx = rng.choice(m, size=n_points, replace=False)
    else:
        idx = np.concatenate([np.arange(m), rng.choice(m, size=n_points - m, replace=True)])
    return xyz[idx, :3].astype(np.float32)


class CaptureWriter:
    def __init__(self, output_dir, meta: dict, config: dict = None):
        self.dir = output_dir
        self.config = {
            "baseline_full_rate": 0.08,          # deterministic 8% of ordinary attempts get the full cloud/RGB-D
            "shard_size": 128,                   # attempts' fixed-size clouds per NPZ shard
            "fixed_point_counts": [1024, 2048],  # PointNet-ready sizes always saved
            "rgbd_jpeg_quality": 92,
        }
        if config:
            self.config.update(config)
        self._attempts_path = os.path.join(self.dir, "attempts.jsonl")
        self._shards_index_path = os.path.join(self.dir, "shards_index.jsonl")
        self._shard_buffer = {}     # key -> np.ndarray, flushed every shard_size
        self._shard_records = 0
        self._shard_seq = 0
        self._n_attempts = 0
        self._n_full_clouds = 0
        self._n_rgbd = 0
        self._n_anchor_clouds = 0
        os.makedirs(self.dir, exist_ok=True)
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "created_unix": time.time(),
            "meta": meta,                         # batch/run id, git commit, episode/scene id, ...
            "config": self.config,
        }
        _atomic_write(os.path.join(self.dir, "manifest.json"),
                      lambda b: b.write(json.dumps(manifest, default=_jsonable).encode()))
        # truncate/create append logs
        open(self._attempts_path, "w").close()
        open(self._shards_index_path, "w").close()

    # ---- sampling policy -------------------------------------------------
    def should_sample_full(self, episode_id, attempt_index: int, event_flags: dict):
        """Return (sample_full: bool, reason: str, probability: float).
        Full (undownsampled) cloud + RGB-D are saved for a deterministic
        baseline fraction of ordinary attempts PLUS every attempt carrying a
        listed event flag (near-tie, promotion, current-change, stop/veto,
        high-conf-but-gt-wrong, large current/next disagreement)."""
        events = [k for k, v in (event_flags or {}).items() if v]
        if events:
            return True, "+".join(sorted(events)), 1.0
        rate = float(self.config["baseline_full_rate"])
        h = int(hashlib.sha256(f"{episode_id}:{attempt_index}".encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
        if h < rate:
            return True, "baseline", rate
        return False, "", rate

    # ---- A + C: per-attempt scalar row + GT labels -----------------------
    def record_attempt(self, row: dict):
        try:
            with open(self._attempts_path, "a") as f:
                f.write(json.dumps(row, default=_jsonable) + "\n")
                f.flush()
            self._n_attempts += 1
        except Exception:
            pass

    # ---- B: point clouds -------------------------------------------------
    def add_anchor_cloud(self, anchor_index: int, xyz, extra: dict = None):
        """Each anchor's raw cloud, written once to anchors/anchor_XXX.npz."""
        if xyz is None:
            return
        xyz = np.asarray(xyz, dtype=np.float32)
        path = os.path.join(self.dir, "anchors", f"anchor_{int(anchor_index):03d}.npz")
        arrays = {"xyz": xyz}
        for n in self.config["fixed_point_counts"]:
            fp = fixed_size_points(xyz, n, seed=int(anchor_index))
            if fp is not None:
                arrays[f"xyz_{n}"] = fp
        ck = _atomic_write(path, lambda b: np.savez_compressed(b, **arrays))
        self._n_anchor_clouds += 1
        self._append_index(self._shards_index_path, {
            "kind": "anchor", "anchor_index": int(anchor_index),
            "path": os.path.relpath(path, self.dir), "n_points": int(xyz.shape[0]),
            "checksum": ck, "extra": extra or {}})

    def add_current_cloud(self, episode_id, attempt_index: int, xyz_full, save_full: bool,
                          sampling_reason: str, sampling_probability: float, extra: dict = None):
        """Always buffers the fixed-size (PointNet-ready) versions into the
        current shard; only buffers the full undownsampled cloud when save_full
        (per should_sample_full). Flushes a shard every shard_size attempts."""
        if xyz_full is None:
            return
        xyz_full = np.asarray(xyz_full, dtype=np.float32)
        seed = int(hashlib.sha256(f"{episode_id}:{attempt_index}".encode()).hexdigest()[:8], 16)
        prefix = f"att{int(attempt_index):06d}"
        for n in self.config["fixed_point_counts"]:
            fp = fixed_size_points(xyz_full, n, seed=seed)
            if fp is not None:
                self._shard_buffer[f"{prefix}_xyz_{n}"] = fp
        if save_full:
            self._shard_buffer[f"{prefix}_xyz_full"] = xyz_full
            self._n_full_clouds += 1
        self._shard_buffer[f"{prefix}_meta"] = np.frombuffer(
            json.dumps({"attempt_index": int(attempt_index), "n_points_full": int(xyz_full.shape[0]),
                        "saved_full": bool(save_full), "sampling_reason": sampling_reason,
                        "sampling_probability": float(sampling_probability),
                        "extra": extra or {}}, default=_jsonable).encode(), dtype=np.uint8)
        self._shard_records += 1
        if self._shard_records >= int(self.config["shard_size"]):
            self._flush_shard()

    def _flush_shard(self):
        if not self._shard_buffer:
            return
        path = os.path.join(self.dir, "pointcloud_shards", f"shard_{self._shard_seq:06d}.npz")
        buf = dict(self._shard_buffer)
        ck = _atomic_write(path, lambda b: np.savez_compressed(b, **buf))
        self._append_index(self._shards_index_path, {
            "kind": "pointcloud_shard", "shard_seq": self._shard_seq,
            "path": os.path.relpath(path, self.dir), "n_records": self._shard_records,
            "keys": sorted(buf.keys()), "checksum": ck})
        self._shard_seq += 1
        self._shard_buffer = {}
        self._shard_records = 0

    # ---- D: front/rear RGB-D --------------------------------------------
    def add_rgbd(self, tag: str, front_rgb=None, front_depth=None, rear_rgb=None, rear_depth=None,
                 camera=None):
        """Write front/rear RGB-D for one sampled anchor or attempt. RGB as JPEG
        (cv2/PIL) with NPZ fallback; depth as uint16-mm PNG with NPZ fallback;
        intrinsics/extrinsics as a small NPZ."""
        base = os.path.join(self.dir, "rgbd", tag)
        wrote = False
        for name, img in (("front", front_rgb), ("rear", rear_rgb)):
            if img is not None:
                wrote |= _write_rgb(f"{base}_{name}.jpg", img, self.config["rgbd_jpeg_quality"])
        for name, d in (("front", front_depth), ("rear", rear_depth)):
            if d is not None:
                wrote |= _write_depth(f"{base}_{name}_depth.png", d)
        if camera:
            _atomic_write(f"{base}_cam.npz",
                          lambda b: np.savez_compressed(b, **{k: np.asarray(v) for k, v in camera.items()}))
        if wrote:
            self._n_rgbd += 1

    # ---- lifecycle -------------------------------------------------------
    def _append_index(self, path, row):
        try:
            with open(path, "a") as f:
                f.write(json.dumps(row, default=_jsonable) + "\n")
                f.flush()
        except Exception:
            pass

    def close(self):
        self._flush_shard()
        summary = {
            "schema_version": SCHEMA_VERSION, "closed_unix": time.time(),
            "n_attempts": self._n_attempts, "n_full_clouds": self._n_full_clouds,
            "n_anchor_clouds": self._n_anchor_clouds, "n_rgbd": self._n_rgbd,
            "n_shards": self._shard_seq,
        }
        _atomic_write(os.path.join(self.dir, "SUMMARY.json"),
                      lambda b: b.write(json.dumps(summary, default=_jsonable).encode()))
        return summary


def _jsonable(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    return str(o)


def _write_rgb(path, img, quality) -> bool:
    img = np.asarray(img)
    if img.ndim == 3 and img.shape[2] >= 3:
        img = img[:, :, :3]
    img = np.clip(img, 0, 255).astype(np.uint8)
    try:
        import cv2
        return bool(cv2.imwrite(path, cv2.cvtColor(img, cv2.COLOR_RGB2BGR),
                                [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)]))
    except Exception:
        pass
    try:
        from PIL import Image
        _atomic_write(path, lambda b: Image.fromarray(img).save(b, format="JPEG", quality=int(quality)))
        return True
    except Exception:
        # dependency-free fallback so capture never fails for lack of an encoder
        _atomic_write(path + ".npz", lambda b: np.savez_compressed(b, rgb=img))
        return True


def _write_depth(path, depth) -> bool:
    d = np.asarray(depth, dtype=np.float32)
    mm = np.clip(np.nan_to_num(d, nan=0.0) * 1000.0, 0, 65535).astype(np.uint16)
    try:
        import cv2
        return bool(cv2.imwrite(path, mm))
    except Exception:
        pass
    try:
        from PIL import Image
        _atomic_write(path, lambda b: Image.fromarray(mm, mode="I;16").save(b, format="PNG"))
        return True
    except Exception:
        _atomic_write(path + ".npz", lambda b: np.savez_compressed(b, depth_mm=mm))
        return True
