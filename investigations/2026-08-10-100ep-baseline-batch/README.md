# 2026-08-10 — Pure NaVILA 100ep Baseline Batch — Session Handoff

**Read this file first if you are picking this up cold** (new conversation, no chat history). It is the restart point. Everything below is accurate as of the pause at **2026-08-10 18:24 BST** — verify current state before acting, don't just trust these numbers if a lot of wall-clock time has passed.

## What this run is

`RUN_TAG=pure_navila_baseline_100ep_20260810`: a 100-episode "pure NaVILA" round-trip baseline (`--round_trip_mode=phase_prompt --instruction_rewriter_provider=cache_only`, **no** `--route_memory`, **no** `--stop_gate`, no oracle/hint/relocalization flags of any kind) on the same canonical 100-episode set used by earlier batches (`canonical_report_next_stopgate_100ep_20260720`, `oracle_anchor_100ep_20260720`, `reliability_fixon_100ep_20260721`, `reliability_v11_*_100ep_20260722/20260724`), so results are directly comparable episode-for-episode. Purpose: a large-sample language-only baseline number to compare the enhanced pipelines against.

Runner (unmodified, original): `/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/scripts/run_pure_baseline_100ep_20260810.sh`. It takes `RUN_TAG`, `PORT_BASE`, and `ONLY_EPISODES` (space-separated episode indices to run; anything else is skipped) as env vars, and always executes its hardcoded 100-`run_episode` list in the same fixed order — `ONLY_EPISODES` is how partial/resumed runs work. Results append to `batch_logs/pure_navila_baseline_100ep_20260810/summary.tsv` regardless of which subset ran.

## Status as of the pause (2026-08-10 18:24 BST)

- **43/100 episodes attempted** (original launch got 6 before crashing at ep408 — see incident below; first resume got 37 more, through ep515).
- **57 remaining**, in the runner's original order:
  ```
  281 268 96 354 347 430 214 338 277 410 137 198 189 491 963 55 337 289 813
  537 932 382 726 546 336 889 20 1004 178 783 162 467 653 88 136 1002 1035
  669 1042 692 652 248 953 1001 696 1039 525 271 447 386 830 122 670 534
  436 290 135
  ```
  (computed programmatically: full 100-ep order from the runner script, minus every `episode_idx` already present as a row in `summary.tsv`, order preserved. Recompute the same way if this list looks stale.)
- **Paused intentionally, not crashed.** The user needed the GPU for something else. Both systemd --user units (batch + watchdog) were stopped cleanly right after ep515 finished. ep281 had just started (VLM server barely up) when the stop happened; it produced no `summary.tsv` row, so it's correctly included in the remaining list above, not double-counted.
- GPU was confirmed idle (0% util) immediately after the stop, then showed real usage shortly after as the user started their own work — that's expected and fine.

## How to resume — DO NOT do this automatically

Only resume after the user **explicitly** confirms they're done with the GPU. If you're a fresh session reading this file without that confirmation in hand, ask first.

1. Confirm the GPU is actually free: `nvidia-smi --query-gpu=utilization.gpu,memory.used --format=csv,noheader` (expect ~0% util, only the idle baseline ~40MiB).
2. Launch the batch. The remaining-episode list is already baked into this script — no need to recompute unless it's gone stale (see below):
   ```
   XDG_RUNTIME_DIR=/run/user/1006 systemd-run --user \
     --unit=navila-pure-baseline-100ep-resume2-20260810 \
     bash -c 'exec bash /home/teambruce/run_pure_navila_baseline_100ep_20260810_resume2.sh > /home/teambruce/run_pure_navila_baseline_100ep_20260810_resume2_master.log 2>&1'
   ```
   (a copy of this script is in `code/run_pure_navila_baseline_100ep_20260810_resume2.sh` in case the local copy on the box is gone).
3. **Verify** the whole process tree's cgroup is under `.../user@1006.service/app.slice/navila-pure-baseline-100ep-resume2-20260810.service`, NOT a `session-*.scope` — this box tears down the whole session scope (killing everything in it, `nohup`/`tmux` included) on SSH disconnect. See `feedback_long_jobs_need_tmux` memory. Never tell the user a job survives disconnect without checking this.
4. **Before re-arming the watchdog**, edit `UNIT=` in `/home/teambruce/navila_gpu_watchdog.sh` from `navila-pure-baseline-100ep-resume-20260810.service` to the new unit name from step 2 (`navila-pure-baseline-100ep-resume2-20260810.service`), or it will immediately think the batch died and alert. Then:
   ```
   XDG_RUNTIME_DIR=/run/user/1006 systemd-run --user \
     --unit=navila-gpu-watchdog-20260810 \
     bash -c 'exec bash /home/teambruce/navila_gpu_watchdog.sh >> /home/teambruce/navila_gpu_watchdog.log 2>&1'
   ```
5. Re-attach live monitoring: `tail -n0 -F /home/teambruce/navila_gpu_watchdog.log` via the Monitor tool so alerts land in the conversation again.

If the remaining-episode list looks stale (summary.tsv has more/fewer rows than 43), recompute it:
```bash
SCRIPT=/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/scripts/run_pure_baseline_100ep_20260810.sh
LOGDIR=/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/batch_logs/pure_navila_baseline_100ep_20260810
full_list=$(grep -oP '^\s*run_episode \K[0-9]+' "$SCRIPT")
completed=$(tail -n +2 "${LOGDIR}/summary.tsv" | cut -f1 | sort -n)
for ep in $full_list; do grep -qx "$ep" <<< "$completed" || echo -n "$ep "; done
```

## The 2026-08-10 ep408 kernel-panic incident (why all this infrastructure exists)

The **original** launch of this batch (not this resume) started at 14:06:37 and crashed at ep408 (~14:25 BST). This was a **real kernel panic**, confirmed via a firmware EFI pstore crash dump (`/var/lib/systemd/pstore/*/dmesg-efi_pstore-*`, 32 fragments all timestamped 14:25) — not just an app hang. `journalctl` for that boot goes completely silent from 14:25:32 until the next boot at 16:22:05 (~1h57m fully unresponsive; the routine 15:17 cron.hourly job never ran). The box has no working IPMI/BMC watchdog (`ipmiutil_wdt.service` fails every boot — no real BMC on this consumer board), so nothing self-recovered; it needed a manual power cycle. This is the same class of incident as the 2026-07-31 "GPU/Vulkan driver lockup" (see `feedback`/`project` memory if available) — a recurring, low-frequency (~once per 10-14 days of heavy GPU use) hardware/driver hazard, not something specific to this run's script.

**Two things initially suspected as crash precursors turned out to be false positives** (worth knowing before trusting any future "the logs show X before it happened" claim):
- `nvidia-drm` kernel error "Flip event timeout on head 0" — appears ~2x in the first 3 seconds of essentially every boot (checked back to July), including boots that ran fine for hours. GDM/display-startup noise, not a hang precursor.
- USD/Hydra "corrupted data in primvar" warnings and "GLFW initialization failed" — appear identically in the normal Isaac-Sim-Kit startup/teardown of every single episode, successful or not (verified against 5 successfully-completed episodes). Zero discriminating power; these fired one false alert (on ep144) before being removed from the watchdog script.

No genuine NVIDIA Xid fault code was ever logged before or during the incident — there was no clean escalating warning trail available; the hang looks fairly abrupt in the retained logs.

## Fix already applied to the machine (persists across reboots)

`/etc/sysctl.d/99-navila-watchdog.conf`:
```
kernel.panic = 60
kernel.hardlockup_panic = 1
kernel.softlockup_panic = 1
```
Confirmed active 2026-08-10 ~18:0x. This does not add any new daemon or detection heuristic — `kernel.panic` only changes what happens *after* an already-confirmed panic (auto-reboot after 60s instead of halting forever), and the two `*_panic` flags make the pre-existing, already-enabled NMI/soft-lockup detectors (`kernel.nmi_watchdog=1`, `kernel.watchdog=1`, thresh=10s) panic instead of only warning. Heavy GPU/CPU userspace load does not trip soft/hard lockup detection (it specifically requires a CPU stuck *in kernel space* not yielding to the scheduler), so this should be safe to leave on permanently, including during future batches. If this fires, you'd see an unexpected entry in `journalctl --list-boots` and a fresh pstore dump — worth checking if a future incident happens, to confirm the fix actually worked as intended (not yet observed in the wild, since no panic has recurred since it was applied).

A stronger option (real Intel PCH `iTCO_wdt` hardware watchdog + a userspace petting daemon) was researched but deliberately **not** enabled — it would add genuine false-positive risk (the petting daemon could get starved under heavy legitimate load and trigger an unwanted reboot mid-batch) for only marginal extra coverage over the sysctl-only fix above. Revisit only if the sysctl fix demonstrably fails to catch a future incident.

## Key files

On `hrl-4090-server`, not all mirrored into this repo (copies of the important ones are under `code/` in this folder):
- `/home/teambruce/run_pure_navila_baseline_100ep_20260810_resume2.sh` — ready-to-launch resume script with the current 57-episode remaining list baked in (copy: `code/run_pure_navila_baseline_100ep_20260810_resume2.sh`)
- `/home/teambruce/navila_gpu_watchdog.sh` — precursor watchdog, calibration notes inline in the header comment (copy: `code/navila_gpu_watchdog.sh`) — **remember to update its `UNIT=` line before relaunching, per step 4 above**
- `/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/batch_logs/pure_navila_baseline_100ep_20260810/summary.tsv` — full per-episode results so far (snapshot as of the pause: `code/summary_snapshot_20260810_1824.tsv`); per-episode `epNNN_eval.log` / `epNNN_vlm.log` files live in the same directory but were not copied here (too large / too many)
- `/mnt/SSD4T/teambruce/projects/navila-isaac/NaVILA-Bench/scripts/run_pure_baseline_100ep_20260810.sh` — the underlying per-episode runner (unmodified original, not copied here — read it in place)

## For a fresh Claude session picking this up

1. Read this file first — it's the whole story, don't re-derive it from scratch.
2. Check current state: `systemctl --user status navila-pure-baseline-100ep-resume2-20260810.service navila-gpu-watchdog-20260810.service` (unit name may differ if resume2 was never actually launched yet — check what's actually running with `systemctl --user list-units | grep navila`).
3. Compare `summary.tsv`'s row count to the 43/57 split above to see if anything changed since this doc was written.
4. If the user says the GPU is free and to continue — follow "How to resume" above, in order.
5. Don't re-litigate the ep408 root cause from scratch — it's fully covered above; the sysctl fix is already live.
