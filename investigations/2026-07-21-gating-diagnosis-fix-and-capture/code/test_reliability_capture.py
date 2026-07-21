"""Standalone smoke test for reliability_capture (no Isaac needed)."""
import os, json, glob, shutil, tempfile
import numpy as np
from reliability_capture import CaptureWriter, fixed_size_points

def main():
    d = tempfile.mkdtemp(prefix="relcap_test_")
    print("test dir:", d)
    w = CaptureWriter(d, meta={"batch": "smoke", "git_commit": "deadbeef",
                               "episode_id": 5, "scene_id": "x8F5xyUWy9e"},
                      config={"shard_size": 16, "baseline_full_rate": 0.1})

    # anchors
    for ai in range(4):
        xyz = np.random.randn(300 + ai * 10, 3).astype(np.float32)
        w.add_anchor_cloud(ai, xyz, extra={"distance_from_start_m": ai * 1.0})
        w.add_rgbd(f"anchor_{ai:03d}", front_rgb=np.random.randint(0, 255, (32, 32, 3)),
                   front_depth=np.random.rand(32, 32) * 5.0,
                   camera={"intrinsics": np.eye(3), "world_pose": np.zeros(6)})

    # attempts
    n_full = 0
    for att in range(40):
        events = {}
        if att == 7: events = {"promotion_event": True}
        if att == 12: events = {"near_tie": True, "stop_request": True}
        sample_full, reason, prob = w.should_sample_full(5, att, events)
        if sample_full: n_full += 1
        xyz = np.random.randn(250, 3).astype(np.float32)
        w.add_current_cloud(5, att, xyz, save_full=sample_full,
                            sampling_reason=reason, sampling_probability=prob,
                            extra={"anchor_index": 11})
        w.record_attempt({
            "attempt_index": att, "anchor_index": 11, "role": "current",
            "overlap_ratio": 0.6, "inlier_count": 200, "confidence": 0.8,
            "icp_near_tie_basin_count": 1 if att == 12 else 0,
            "reliability_bearing_bad_probability": 0.3,
            # GT labels (offline only)
            "gt_bearing_error_deg": 45.0, "gt_bearing_bad": True,
            "sequence_id": 0, "attempt_index_prev": att - 1, "anchor_generation": 0,
            "promotion_event": att == 7, "sampling_reason": reason,
        })
        if sample_full:
            w.add_rgbd(f"att{att:06d}", front_rgb=np.random.randint(0, 255, (32, 32, 3)),
                       rear_rgb=np.random.randint(0, 255, (32, 32, 3)),
                       front_depth=np.random.rand(32, 32) * 5.0)

    # --- crash-safety check: read append logs BEFORE close() ---
    pre_close_attempts = sum(1 for _ in open(os.path.join(d, "attempts.jsonl")))
    pre_close_shards = len(glob.glob(os.path.join(d, "pointcloud_shards", "*.npz")))
    print(f"pre-close: attempts.jsonl lines={pre_close_attempts}, flushed shards={pre_close_shards} (readable mid-run ✓)")

    summary = w.close()

    # --- assertions ---
    ok = True
    def check(name, cond):
        nonlocal ok
        print(("  ✅ " if cond else "  ❌ ") + name); ok = ok and cond

    manifest = json.load(open(os.path.join(d, "manifest.json")))
    check("manifest schema+meta present", manifest["schema_version"].startswith("reliability-capture")
          and manifest["meta"]["episode_id"] == 5)
    check("attempts.jsonl has 40 lines", sum(1 for _ in open(os.path.join(d, "attempts.jsonl"))) == 40)
    check(f"summary n_attempts=40 (got {summary['n_attempts']})", summary["n_attempts"] == 40)
    check(f"summary n_full_clouds matches sampled ({summary['n_full_clouds']}=={n_full})", summary["n_full_clouds"] == n_full)
    check("event attempts always sampled full (7,12)", (w.should_sample_full(5,7,{'promotion_event':True})[0]
          and w.should_sample_full(5,12,{'near_tie':True})[0]))
    check("sampling deterministic", w.should_sample_full(5, 3, {}) == w.should_sample_full(5, 3, {}))
    check("4 anchor NPZ written", len(glob.glob(os.path.join(d, "anchors", "*.npz"))) == 4)
    check("shards_index.jsonl non-empty", os.path.getsize(os.path.join(d, "shards_index.jsonl")) > 0)

    # verify a shard round-trips + checksum recorded
    idx_rows = [json.loads(l) for l in open(os.path.join(d, "shards_index.jsonl"))]
    shard_rows = [r for r in idx_rows if r["kind"] == "pointcloud_shard"]
    check("shard rows recorded with checksum", len(shard_rows) > 0 and all(r["checksum"] for r in shard_rows))
    z = np.load(os.path.join(d, shard_rows[0]["path"]))
    check("shard NPZ loads + has fixed-size clouds", any(k.endswith("_xyz_1024") for k in z.files))

    # anchor cloud round-trip + fixed sizes
    za = np.load(os.path.join(d, "anchors", "anchor_000.npz"))
    check("anchor NPZ has xyz + xyz_1024 + xyz_2048", set(["xyz","xyz_1024","xyz_2048"]).issubset(set(za.files))
          and za["xyz_1024"].shape == (1024, 3))

    # fixed_size_points edge cases
    check("fixed_size upsamples when M<n", fixed_size_points(np.random.randn(10,3), 1024, 1).shape == (1024,3))
    check("fixed_size handles empty", fixed_size_points(np.zeros((0,3)), 1024, 1) is None)

    # rgbd written (NPZ fallback if no cv2/PIL)
    rgbd_files = glob.glob(os.path.join(d, "rgbd", "*"))
    check("rgbd files written", len(rgbd_files) > 0)

    print("\n" + ("ALL PASS ✅" if ok else "FAILURES ❌"))
    print("rgbd sample files:", [os.path.basename(f) for f in rgbd_files[:4]])
    shutil.rmtree(d)
    return 0 if ok else 1

if __name__ == "__main__":
    raise SystemExit(main())
