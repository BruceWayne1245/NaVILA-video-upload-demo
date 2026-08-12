# Home Directory Cleanup / Archive (2026-08-12)

`/home/teambruce` on `hrl-4090-server` had accumulated ~2 months (2026-06-05 through
2026-08-12) of one-off batch launcher scripts, logs, and per-batch staging/queue
directories directly at the top level — 336 top-level entries including hidden files.
This folder is a **lookup reference for later**: if a script, log, or staging directory
that used to live directly in `~` can't be found, or a `wait_for_X_then_run_Y.sh`/
`monitor_*.sh` script that references a sibling path by relative reference breaks,
check the manifest below before assuming something was lost.

**Nothing was deleted except one pure bytecode cache directory.** Everything else was
*moved*, not removed — full old-path → new-path mapping is in
[`cleanup_manifest_20260812.tsv`](cleanup_manifest_20260812.tsv) (248 rows).

## New layout

Home dir went from 336 top-level entries (28 after cleanup) to:

```
~/navila_archive/
  scripts/{2026-07,2026-08}/    97 launcher scripts (run_*.sh / chain_*.sh / wait_for_*.sh / monitor_*.sh)
  logs/{2026-06,2026-07,2026-08,unknown}/   80 log files (*.log, *_master.log, *.nohup.log, *_stdout.log)
  misc/                          17 one-off files (BRUCE_macros.py, watchdog scripts, manifest tsvs, a few stale .lock files)
  staging_dirs/                  52 one-batch project/staging directories (navila-*, streamvln-*-queue-*, github-*, replay_results_*, etc.)
```

Bucketing rule for `scripts/` and `logs/`: the first `2026(06|07|08)\d\d` date pattern
found in the filename determines the `YYYY-MM` subfolder; files with no such date landed
in `logs/unknown/` (2 files: `smoketest_short_baseline.log`, `smoketest_short_baseline2.log`).

## What was deliberately left untouched

- All dotfiles/dot-directories at `~` (`.claude`, `.ssh`, `.cache`, `.vscode`, `.gitconfig`,
  etc.) — not part of this cleanup, never inspected beyond confirming they exist.
- Standard tool/env/data directories: `configs`, `Desktop`, `Documents`, `Downloads`,
  `eval_results`, `isaacgym`, `IsaacLab`, `isaacsim`, `miniconda3`,
  `miniconda3_bernardo`, `mujoco`, `point6`, `rsl_rl`, `scratch_inv`, `snap`, `src`,
  `unitree_rl_gym`, `unitree_rl_gym_main`, `unitree_rl_lab`, `unitree_sdk2_python`,
  `users`.
- `~/navila-reliability-v1_1` — **left in place, not archived.** It has 15 untracked
  files (last touched 2026-07-23) that are genuine unpushed V1.1 work: `reliability/v11_portable.py`,
  `reliability/v11_runtime.py`, 7 `tools/*.py` scripts, and an `experiments/` tree with
  real result artifacts (npz/csv/json) from the 07-22/23/24 decision-shadow work. These
  match the "confirmed still missing from GitHub" list identified back on 2026-07-24.
  **Open TODO:** push these 9-10 files to GitHub next time this line of work is picked
  up — they still are not represented anywhere in this repo as of this commit.

## The one directory that WAS archived after review

`~/NaVILA-video-upload-demo-work` had 4 modified files (`code/relocalization.py`,
`round_trip_eval.py`, `route_memory_agent.py`, `tests/test_geometry_pipeline.py`) adding
z-preserving / 3D LiDAR local-map support (`descriptor_local_map_points_xyz`,
`voxel_downsample_xyz`). Investigated before moving: base commit was 2026-07-01, files
last touched 2026-07-05, and the clone was 344 commits behind `origin/main` at cleanup
time — assessed as an abandoned/superseded exploration (all later relocalization work —
multiframe anchor, the ICP KD-tree proposal — went a different direction and never
referenced this branch). User confirmed archiving it after seeing this summary. Now at
`~/navila_archive/staging_dirs/NaVILA-video-upload-demo-work/`.

## One deletion

`~/__pycache__` (top-level, 64K) — pure Python bytecode cache, regenerates automatically,
zero information content.

## Side discovery — unrelated git repo at `~`

`/home/teambruce` itself is a git working tree for an unrelated project ("BRUCE" — a
physical robot's walking/RL codebase; branch `master`, commits like "Organised baseline
model parameters for walking", tracking things like `rsl_rl` and `snap/code/...`).
Confirmed via `git ls-files` / `git check-ignore` that none of the archived NaVILA files
were tracked by or ignored in that repo, so this cleanup had zero interaction with it.
That repo itself was not touched or investigated further — noted here only so a future
session isn't confused by unrelated `git status` output when running `git status` at `~`.

## Known risk not fixed

Some `wait_for_X_then_run_Y.sh` scripts reference sibling scripts/paths by relative
reference in their own body. They were archived as historical record, not for re-execution
— if one is ever copied out and re-run, check its internal paths first rather than assuming
it still works unmodified from the archive location.

## Full manifest

See [`cleanup_manifest_20260812.tsv`](cleanup_manifest_20260812.tsv) — every one of the 248
affected paths (`original_path`, `new_path`, `category`), where `category` is one of
`script`, `log`, `misc`, `staging_dir`, `deleted`, `held`.
