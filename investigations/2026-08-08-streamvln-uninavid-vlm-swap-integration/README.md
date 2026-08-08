# 2026-08-08 — Cross-backbone hint_action reproduction: StreamVLN + Uni-NaVid swapped in as NaVILA's VLM

**Goal:** the project's "hint_action_arbiter intervenes on only 4.3% of return-phase
decisions, yet lifts round-trip return success from ~50% to ~97%" finding
(`stop_gate_r3_hint_arbiter_hard11_20260630` + `oracle_shadow_loftr_v4_30_return_anchor_fix_20260701`,
combined 17/18 = 94.4%, vs. the earlier `stop_gate_r3_oracle_hard_20260630` +
two 2026-06-29 hard-11 batches combined 14/28 = 50%) had only ever been shown on
NaVILA itself. This session set up two other VLN backbones — **StreamVLN**
(ICRA 2026, Qwen2-7B video-LLM) and **Uni-NaVid** (RSS 2025, LLaMA-VID-based) —
as drop-in replacements for NaVILA's VLM inside the *same, unmodified* Isaac
Sim / `round_trip_eval.py` harness, to test whether the intervention mechanism
generalizes across backbones.

**Status at end of session:** environments and adapters built and validated
end-to-end against real Isaac Sim episodes. A queued 30-episode StreamVLN
batch (hint_action first, then oracle-hint-only) was launched but has not
finished as of this writing — see "Pending" below.

## Phase 0 — locating the source numbers and freezing the protocol

The 4.3%/50%→97% claim traces to two comparisons in this repo's own root
README, confirmed by reading the raw `measurement_*.json` files directly
(not just the narrative prose):

- **Oracle-hint baseline (no `hint_action_arbiter`), pooled 14/28 = 50%:**
  three hard-11 batches (`4,5,134,187,367,368,408,678,680,994,1040`), all
  `--route_hint_source=oracle --oracle_align_return_yaw_to_anchor_segment`
  (+ stop_gate in the later two): 5/10 (2026-06-29 direct-oracle), 5/10
  (2026-06-29 stop-gate arbiter), 4/8 (2026-06-30 stop-gate r3 fix).
- **Oracle-hint + `hint_action_arbiter`, pooled 17/18 = 94.4%:** hard-11
  (`stop_gate_r3_hint_arbiter_hard11_20260630`, 7/7) + a separate 30-episode
  set (`oracle_shadow_loftr_v4_30_return_anchor_fix_20260701`, 10/11).
  The 30-episode batch logged 348 return-phase decisions across its 7
  outbound-success episodes: 180 already hint-consistent, 153 blocked by the
  local-occupancy clear-path check, **15 actually overridden — 15/348 = 4.31%
  ≈ 4.3%.**

**Protocol correction found late in the session:** all of the above batches
used `--round_trip_mode=phase_prompt`, not the harness's default
`static_long_instruction`. Confirmed directly from
`artifacts/stop_gate_r3_hint_arbiter_hard11_20260630/ep5/measurement_8.json`
(`"mode": "phase_prompt"`). Early StreamVLN runs this session used the
default mode before this was caught; those results are noted as
non-comparable below and were superseded by phase_prompt reruns.

The exact 30-episode list used for the 94.4%/4.3% batch (from
`code/run_oracle_shadow_loftr_v4_30_batch_20260701.sh`):
`106, 367, 613, 133, 198, 186, 4, 336, 408, 107, 368, 614, 993, 134, 199,
187, 5, 337, 409, 678, 679, 680, 994, 995, 1038, 1039, 1040, 465, 466, 467`.

## Phase 1 — isolated environments, no changes to NaVILA's own envs/processes

Two new conda envs built from scratch on `/mnt/SSD4T/teambruce/conda_envs/`
(`streamvln`: python3.9/torch2.1.2+cu121; `uninavid`: python3.10/torch2.0.1+cu117),
fully separate from the project's existing `navila-vlm`/`vlnce-isaac` envs —
confirmed untouched throughout (checked via direct `import torch` version
probes before/after, and by observing the project's own live NaVILA batches
continue running correctly in parallel on multiple occasions during this
session).

Dependency issues hit and fixed, all scoped to the new envs only:
- `clip` (git dep) needed `pkg_resources`, missing from a fresh isolated
  build env's auto-fetched `setuptools`; pinned `setuptools==69.5.1` in-env.
- `av==14.4.0` needed a `Cython` build dependency, then hit a FFmpeg-version
  bracket: system FFmpeg 4.4.2 is too old (missing `ch_layout`), conda-forge's
  default FFmpeg 8.0 is too new (`AVFMT_ALLOW_FLUSH` removed); pinned
  conda-forge `ffmpeg=7` inside the `streamvln` env prefix only.
- `torch-scatter` and `flash-attn` both needed `--no-build-isolation` to see
  the already-installed torch; `flash-attn` additionally needed the system's
  default `nvcc` (apt-packaged, CUDA 11.5) overridden via `CUDA_HOME`/`PATH`
  to the already-installed `/usr/local/cuda-12.8` toolkit, scoped to that one
  build command only (no system-wide change).
- Uni-NaVid's `numpy` needed pinning to `1.23.5` (matches NaVid-VLN-CE's own
  requirements.txt) — its `deepspeed==0.9.5` imports `numpy.BUFSIZE`, removed
  in modern numpy; opencv-python-headless's own numpy>=2 preference had to be
  overridden back down after installing it.

Checkpoints downloaded: `mengwei0427/StreamVLN_Video_qwen_1_5_r2r_rxr_envdrop_scalevln_v1_3`
(15GB), `Jzzhang/Uni-NaVid/uninavid-7b-full-224-video-fps-1-grid-2` (15GB) +
EVA-ViT-G vision encoder (2GB). Both models' own official single-inference
smoke scripts (StreamVLN: ported from `streamvln/http_realworld_server.py`'s
model-loading path; Uni-NaVid: `offline_eval_uninavid.py` with its own bundled
`test_cases/vln_1` sample) ran cleanly on real images before any Isaac Sim
integration was attempted.

## Phase 2 — wire-compatible adapter servers, validated against real episodes

`scripts/vlm_server.py`'s protocol (raw TCP socket, 8-byte big-endian length
prefix + JSON; request `{"images": [8 base64 jpg], "query": <instruction>}`,
response a JSON-encoded plain-text string) was reverse-engineered from
`vlm_server.py` + `round_trip_eval.py`'s `sample_images_and_send_to_vlm` /
`parse_vlm_command` / `get_vel_command` (in the installed
`omni.isaac.vlnce.utils.eval_utils`, not this repo). Two new standalone
servers (`code/streamvln_server.py`, `code/uninavid_server.py`) replicate
this protocol exactly and never import or modify anything under
`NaVILA-Bench/`. A small shared
translation module (`code/nav_action_translate.py`) maps each model's native
action tokens (StreamVLN: `{0:STOP,1:forward,2:left,3:right}` int ids from
`actions2idx`; Uni-NaVid: `{"forward","left","right","stop"}` words) onto the
exact fixed phrases `get_vel_command` recognizes by substring match — and
*only* those four phrases, defaulting to `"stop"` (never a free-text guess)
on any unrecognized token, specifically to avoid `get_vel_command`'s silent
"unrecognized text defaults to move-forward" fallback turning a translation
bug into unsupervised forward motion.

**End-to-end validation, episode 88, no hints at all**
(`--round_trip_mode` defaulted to `static_long_instruction` on this first
pass — see the protocol-correction note above, not reused for later
comparisons):
- StreamVLN: `outbound_success=true` (2.14m nav error), `return_success=false`
  (4.21m, outside 3.0m radius) — 1001/1001 return-phase steps 100%
  parseable throughout.
- Uni-NaVid: `outbound_success=false` on all 4 attempts tried (episodes 88,
  4, 368×2 prompt modes) — always 100% parseable (never an adapter/format
  failure), but never reached the goal within the outbound step budget.
  Plausible domain-transfer effect (Habitat/VLN-CE-trained model seeing
  Isaac Sim's renderer/embodiment for the first time) rather than an
  integration bug; not resolved this session, flagged as an open question.

**Bugs found and fixed during validation (all in the new adapter code, not
in NaVILA or in `round_trip_eval.py`):**
1. `VLNEvaluator.step()`'s first argument is a fixed per-env index (checked
   against `model.reset(1)`'s length-1 internal state list), not an
   incrementing step counter — passing an incrementing counter caused
   `IndexError: list index out of range` on the second query of any episode.
2. Python's default block-buffered stdout when redirected to a file hid the
   servers' own "listening"/"ready"/per-request log lines for several
   minutes at a time, at one point making a genuinely-ready server look
   hung. Fixed by always launching adapter servers with `PYTHONUNBUFFERED=1`
   / `python -u`.
3. StreamVLN's streaming architecture keeps growing internal KV-cache/memory
   state across `evaluator.step()` calls by design; reusing one server
   process across multiple separate episode-test attempts (done for
   debugging convenience, not matching the "fresh process per episode"
   convention the adapter's own docstring already assumed) caused
   unbounded GPU memory growth, eventually hitting `CUDA out of memory` on a
   third reused attempt. The 30-episode batch driver (below) always starts a
   fresh server process per episode specifically to avoid this.

## Phase 3 — hint_action_arbiter requires zero adapter changes

`hint_action_arbiter.py::HintActionArbiter.check()` only ever consumes the
already-parsed VLM text output plus a harness-computed oracle hint direction
(`progress.bearing_to_anchor_deg`/`distance_to_anchor_m`, or a
`bearing_to_start_deg`/`distance_to_start_m` fallback) — it has no
NaVILA-specific dependency, so the arbiter worked immediately once the right
CLI flags (`--route_memory --route_hint_source=oracle
--oracle_align_return_yaw_to_anchor_segment --stop_gate
--stop_gate_r_in=3.0 --stop_gate_r_out=3.0 --topdown_route_map
--hint_action_arbiter`) were pointed at the StreamVLN adapter's port. Note:
`--route_hint_source=oracle` alone, without `--route_memory`, produces no
hint direction at all in the currently-installed `round_trip_eval.py`
(`_hint_direction` sees `progress=None`) — this is a config requirement, not
a bug, and easy to miss.

First StreamVLN + hint_action_arbiter test (episode 88, `static_long_instruction`
still, pre-correction): `round_trip_success` flipped from the no-hint
baseline's failure to **true** (2.69m final distance, SPL 0.899). But the
arbiter's own per-step log shows **zero actual overrides** in this run (7
checks: 6 blocked by `occupied_in_local_map_path`, 1
`vlm_action_consistent`) — so this single episode's flip is attributable to
the passive oracle-hint *text* injected via `--route_memory`, not to the
active `hint_action_arbiter` override mechanism, and should not be cited as
evidence for the 4.3%-intervention story specifically. A larger sample with
`phase_prompt` (see Pending) is needed before any intervention-rate number
can be computed for StreamVLN.

## Pending

A fail-closed, disconnect-resilient (`systemd-run --user`, linger enabled)
queued batch was launched at the end of this session:
`streamvln-30ep-chain-20260808.service` waits for no active `navila-*`
systemd unit and ≥20GB free GPU memory, then runs, in order:
1. `streamvln_hint_action_30ep_20260808` — the same 30-episode list as
   `oracle_shadow_loftr_v4_30_return_anchor_fix_20260701`, same
   `route_memory`/oracle-hint/`phase_prompt` config, plus
   `--hint_action_arbiter` (the batch directly comparable to the 4.3%/94.4%
   number).
2. `streamvln_oracle_hint_30ep_20260808` — the same 30 episodes, same
   config, *without* `--hint_action_arbiter` (comparable to the 50%
   baseline).

Neither had produced a `summary.tsv` as of this write-up. Uni-NaVid's
outbound-failure pattern (4/4 attempts) is also unresolved — worth checking
whether a different episode subset, or Uni-NaVid's own instruction-length
assumptions, explain it before spending more GPU time on it.

## Validity caveat for the paper

StreamVLN/Uni-NaVid were trained and published against Habitat/VLN-CE, never
fine-tuned for this project's Isaac Sim renderer or Go2 quadruped embodiment
(unlike NaVILA, which was purpose-adapted for exactly this setup). Absolute
success numbers produced here characterize "this backbone transplanted into
an unfamiliar harness," not the backbone's native benchmark capability —
Uni-NaVid's 4/4 outbound failures here despite a published R2R SR=51.8%/
SPL=47.7% is a concrete illustration of that gap. The paper's cross-backbone
claim should be framed narrowly (does the intervention mechanism help,
relative to each backbone's own no-hint baseline, once plugged into the same
harness) rather than as a claim about StreamVLN/Uni-NaVid's general VLN
capability, and should cite each model's own native benchmark numbers as
context.

## Code

- `code/nav_action_translate.py` — action-token → NaVILA-phrase translation,
  shared by both adapter servers (offline self-test included).
- `code/streamvln_server.py` — StreamVLN adapter server.
- `code/uninavid_server.py` — Uni-NaVid adapter server.
- `code/run_streamvln_oracle_hint_30ep_20260808.sh` — 30-episode batch
  driver (parameterized by `RUN_TAG`/`PORT_BASE`/`EXTRA_ISAAC_ARGS`; used for
  both the hint_action and oracle_hint-only stages).
- `code/wait_for_idle_then_run_streamvln_30ep_chain_20260808.sh` — fail-closed
  queue + two-stage chain launcher.

No credentials, checkpoints, or captured trajectory/measurement data are
included in this folder.
