# Local storage cleanup for article-only retention (2026-09-02)

## Decision

The local NaVILA evaluation workspace was reduced to an article-only retention set. Future model training from the original sensor-level replay data is explicitly out of scope for this cleanup.

Only per-episode `icp_replay_dataset/` directories were deleted. Episode result directories themselves were retained.

## Deleted data

- Target: `NaVILA-Bench/eval_results/*/icp_replay_dataset/`
- Directories deleted: **1,324**
- Files deleted: **3,106,583**
- Apparent bytes deleted: **2,658,621,407,594 bytes**
- Apparent size deleted: **2,476.034 GiB / 2.418 TiB**
- Remaining replay directories after verification: **0**

Deleted material comprised `steps/*.json`, `rgbd/*.npz`, `anchor_rgbd/*.npz`, `anchors.json`, and one temporary anchors file. This deletion is irreversible locally: rematerializing raw-input features now requires rerunning the corresponding evaluations.

## Retained article evidence

- all **3,328** episode result directories;
- **2,966** MP4 files;
- trajectories, measurements, and route maps;
- **4,845** JSONL files, including reliability, Anchor V3, stop-gate, and terminal-approach logs;
- batch logs, summaries, termination reasons, final distances, and outcomes;
- source code, Git history, checkpoints, normalizers, configurations, and run scripts;
- materialized Anchor V3 train/validation/test datasets;
- compact V1/V1.1/V2 datasets, reports, and paper material.

After cleanup, `NaVILA-Bench/eval_results` occupied approximately **58 GiB**.

## Filesystem result

The 3.6-TiB SSD changed from approximately 204 GiB available at 95% utilization to approximately **2.7 TiB available at 23% utilization**.

## Audit trail

`artifacts/icp_replay_dataset_deletion_manifest.tsv` records apparent bytes, file count, and the episode-relative target for every deleted directory. Absolute local paths were removed before publication.

Local pre-deletion manifest SHA-256:

`12b7f7e341fa058f2c45c74e3a1ab8e34ec4c4ff9e1eb770778e5c040996fbf3`

The published sanitized manifest has its own checksum beside it.

## Verification

1. Confirmed no NaVILA evaluation, VLM server, or Anchor V3 process was running.
2. Generated and checksummed the manifest before deletion.
3. Restricted targets to `eval_results/<episode>/icp_replay_dataset`.
4. Confirmed zero replay directories remained.
5. Confirmed videos, trajectories, measurements, JSONL evidence, materialized datasets, checkpoint, and evaluator source remained.
6. Revalidated the original manifest checksum after deletion.
