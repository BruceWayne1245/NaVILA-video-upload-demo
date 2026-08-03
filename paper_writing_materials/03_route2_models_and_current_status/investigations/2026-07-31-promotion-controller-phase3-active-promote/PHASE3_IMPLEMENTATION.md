# Phase 3 implementation: promote/wait live enforcement, quarantine still shadow

Continues `FINDINGS.md` Section 4. This is `2026-07-28-promotion-quarantine-controller-model/INTEGRATION_PLAN.md`'s
Phase 3, previously unimplemented (`PromotionModelBundle.load()` only accepted
`mode="shadow"` and raised on anything else, by design, until this session).

## 1. Design decision

`_select_sequential_pair_relocalization` (in `route_memory_agent.py`) is not a
single promote/wait switch -- it's a chain: `quality_ok` (next must not be
catastrophically worse than current, unless current is itself persistently
unreliable) AND (`close_enough` OR `trend_ok`) -> `candidate_promote` ->
`closure_reject_reason` veto (current/next cross-check disagreement) ->
`bounded_evidence` vote aggregation (3-of-5 window, not a single-attempt
decision) -> `short_baseline`-unresolved withhold. Each gate exists to guard
against a specific, documented historical failure (cited inline in the
source).

Three integration options were considered for how the model's promote/wait
call should interact with this chain:

1. **Model fully replaces the chain.** Highest ceiling (could fix the
   mechanism-gap failures the heuristic itself can't see), but discards every
   gate's accumulated protection against its own specific historical bug.
   Highest risk.
2. **Model as an additional AND-gate** (heuristic must already agree to
   promote; model can only veto, never force). Safest, but can never fix a
   case where the heuristic itself never proposes a promotion -- defeats part
   of the original motivation for building this model (the 0728
   `promotion_quarantine_controller` FINDINGS.md's own framing: "fixes
   mechanism A/B/C gaps").
3. **Model replaces only the vote-aggregation step** (`bounded_evidence`'s
   3-of-5 window). `quality_ok`/`close_enough`/`trend_ok` are not reapplied
   as a second gate on the model (the model's own richer features -- rolling
   distance/confidence/ratio history, `cur_bad_fraction_hist` -- already
   subsume what those simple threshold checks approximate; `quality_ok`
   specifically has a known false-negative mode Injection B was added to work
   around, so keeping it as a hard gate would reintroduce that exact bug
   class for model-driven promotions too). `closure_reject_reason`'s veto and
   the short-baseline withhold still apply on top of the model's call --
   those guard "is this reading resolvable at all", a different question
   from "should we promote", independent of decision mechanism.

**Option 3 was chosen** (explicit user decision, 2026-07-31). Quarantine
stays entirely on the existing `_record_next_anchor_trend` heuristic
regardless -- the model's `quarantine` class, when active, only ever
suppresses this attempt's promote (mapped to `wait`), it never writes to
`_quarantined_anchor_indices`.

## 2. Code changes

Three files, all Route 1-owned (verified zero file overlap with Route 2's
`unified_shadow50_retry4`, which runs its own separate checkout at
`runtime_candidate/scripts/round_trip_eval.py` -- confirmed while this was
being written, since that job happened to be running concurrently on the same
GPU).

- **`route_memory_agent.py`** -- new `sequential_pair_promotion_model_active_promote: bool = False`
  constructor param + `self._active_promotion_model_decision: Optional[bool] = None`
  transient per-attempt field. In `_select_sequential_pair_relocalization`,
  `_record_promotion_vote(...)` still runs unmodified for bookkeeping (vote
  history, alias-aware stall counter stay populated), but its result is
  overridden by `_active_promotion_model_decision` (ANDed with
  `not closure_reject_veto`) when the flag is on and a decision was set this
  attempt. See `code/route_memory_agent_active_promote.patch`.
- **`round_trip_eval.py`** -- new `--sequential_pair_promotion_model_active_promote`
  CLI flag (requires `--sequential_pair_promotion_model_shadow` also set,
  validated at startup). Inside the existing `_sequential_pair_relocalizer_with_v11_shadow`
  closure, a **separate** `PromotionFeatureBuilder` instance (not shared with
  `promotion_shadow_session`'s own builder -- sharing would double-append to
  rolling history and quietly corrupt every rolling-mean/std feature) scores
  the model synchronously on the same `covisibility_records`, before
  `update_relocalization()`'s continuation reads it. Fail-open: any exception
  sets the decision to `None` (falls back to the heuristic vote) and prints a
  diagnostic line, mirroring `PromotionShadowJsonlSession.score_attempt`'s own
  fail-open contract. See `code/round_trip_eval_active_promote.patch`.
- **`promotion_controller_runtime.py`** -- `PromotionShadowJsonlSession` gained
  an `active_promote: bool = False` param. When true, its JSONL log now
  honestly writes `enforcement_enabled`/`controller_effect: True` and
  `mode: "shadow+active_promote"` instead of the previous hardcoded-always-False
  fields, which would otherwise silently mislead anyone reading the log after
  Phase 3 shipped. Default `False` reproduces the exact old log fields. See
  `code/promotion_controller_runtime_active_promote.patch` (a real, mechanically
  verified diff against the 0728 baseline already in this repo) and the full
  updated file at `code/promotion_controller_runtime.py`.

Deployed to `NaVILA-Bench/scripts/promotion_controller_runtime.py` (what
`round_trip_eval.py` actually imports at runtime) -- initially edited only a
separate local mirror checkout by mistake while reading it as a reference,
caught via `diff` before running anything, then copied over. Worth restating
this project's standing rule: always confirm which copy of a file is actually
on `sys.path` / gets imported before trusting an edit took effect, per
`2026-07-24`'s publish-workflow notes on multiple local checkouts.

## 3. Verification performed

**Static (no GPU needed), all passed**: `py_compile` on all three files.
Synthetic smoke test: `RouteMemoryAgent` instantiates with the new param
either way, `_active_promotion_model_decision` settable/readable; the full
`PromotionFeatureBuilder` -> `predict_proba` -> `PromotionDecisionPolicy.decide()`
pipeline runs end to end on synthetic covisibility records; a
`PromotionShadowJsonlSession(active_promote=True)` writes honest
`enforcement_enabled=True`/`controller_effect=True`/`mode=shadow+active_promote`;
`active_promote=False` reproduces the previous log byte-for-byte.

**Not yet done**: `_select_sequential_pair_relocalization`'s actual
consumption of `_active_promotion_model_decision` against a real live Isaac
Sim episode (real ICP estimates, real anchor sequence). This can't be unit
tested in pure Python, and the GPU was occupied the entire session by Route 2's
`unified_shadow50_retry4` (peaked near 20.9/24.5GB used). This is the first
time this code path will ever execute for real -- see the smoke test below.

## 4. Overnight smoke test + data batch

Per explicit user direction: rather than wait for a dedicated GPU window,
queue a 30-episode batch directly behind the currently-running
`unified_shadow50_retry4` so it starts automatically once that job finishes
and the GPU clears -- if the new code has a bug, it fails loud across up to
30 episodes overnight instead of silently; if not, real validation data comes
back by morning either way.

- **Queue watcher**: `code/wait_for_unified50_then_run_active_promote_30ep_20260731.sh`,
  running as `systemd --user` unit `navila-active-promote-30ep-queue-20260731`
  (cgroup verified under `user@1006.service`, `Linger=yes` confirmed on this
  host -- survives a disconnected session; see the operational note below for
  why that specifically needed re-checking today). Detects
  `unified_shadow50_retry4` as still-active via `pgrep` on its own master
  scripts (that job does **not** run under a systemd unit itself -- its whole
  process tree currently sits in a login-session cgroup, launched directly in
  an interactive shell rather than via `systemd-run`) plus an eval-process
  pattern fallback, mirrors the existing (and already-proven) `wait_for_route1_then_run_unified50.sh`
  pattern in the opposite direction. Waits for GPU free >= 22000MiB (same
  threshold that script uses) before launching.
- **Launcher**: `code/run_promotion_active_promote_30ep_20260731.sh`
  (`RUN_TAG=promotion_active_promote_30ep_20260731`, `PORT_BASE=65000`, reuses
  the existing generic `run_promotion_shadow_reliable30v3_driver_20260731.sh`
  unmodified -- that driver already contains a same-day fix
  (`sweep_kill_stragglers`) for a process-tree-cleanup issue found earlier
  today (an episode that timed out took 2 hours to be fully killed because
  Isaac Kit had detached descendants into their own session, missed by a
  plain process-group kill) -- confirmed this fix is present and actually
  invoked (3 call sites: timeout path, normal-completion path, error path)
  before reusing it). Config identical to `promotion_shadow_reliable30v3_20260731`
  except: `--sequential_pair_promotion_model_active_promote` added,
  `--sequential_pair_promotion_model_quarantine_threshold` raised 0.65->0.85
  per `FINDINGS.md` Section 3.
- **Same 30 episode_idx values as `reliable30v3`**, deliberately, so this run
  can be compared directly against that batch's shadow-only baseline on
  identical episodes/scenes/neighbors -- isolating the promote mechanism
  change as the only variable.

Results will land in
`NaVILA-Bench/batch_logs/promotion_active_promote_30ep_20260731/summary.tsv`.
**Outcome not yet known as of this writing** -- check that, the eval logs for
any `[promotion-active] scoring exception` lines, and
`journalctl --user -u navila-active-promote-30ep-queue-20260731.service` next
session. If `round_trip_success` improves meaningfully over `reliable30v3`'s
baseline on the same 30 episodes with no new infra-failure pattern, that's
the promote/wait Phase 3 rollout working as intended.

## 5. Operational context: Route 2 health + a session-scope correction

Not this investigation's primary subject, but recorded here since it directly
determines whether the smoke test above actually gets to run tonight.

`unified_shadow50_retry4` itself had a rough day, largely as a downstream
symptom of the GPU/Vulkan driver lockup covered in
`2026-07-31-route2-runtime-failure-forensics`: all 49 fresh episodes failed
(900s startup-watchdog timeout, `episode_failures=49/49`) between 2026-07-30
20:54 and 2026-07-31 09:06, coincident with that lockup. After the reboot
(~10:46) it correctly queued behind this session's `reliable30v3` batch via
the existing Route1->Route2 queue script, waited until 19:10, then retried
its `ep670` canary -- which passed cleanly (`exit_code=0`) for the first time
that day at 19:44. As of this writing it has re-started the 49-episode batch
and the first several episodes (`ep94`, `ep185`, `ep1037`, `ep479`) have all
completed with `exit_code=0` -- a clear contrast with the prior all-failure
run, consistent with that run having been a lockup symptom rather than a
Route 2 code defect.

Separately: `unified_shadow50_retry4`'s process tree runs in a login-session
cgroup (`session-N.scope`) rather than under `systemd-run`, which was flagged
mid-session as a disconnect risk matching this project's established
"long jobs must escape session scope" rule. Checked `/etc/systemd/logind.conf`
on this host: `KillUserProcesses=no` (the effective default, not overridden)
-- meaning a closing/disconnected login session does **not** cause `logind`
to kill processes still running in its scope; they're orphaned to PID 1
instead. Live-confirmed: the specific SSH session that originally launched
this job showed `State=closing` while the job's processes (already
reparented to PID 1) continued running and progressing unaffected. The
original "would not survive a disconnect" concern raised earlier the same
session does not hold on this specific host's configuration -- worth
re-verifying on any other host before assuming the same, since
`KillUserProcesses=no` is a per-host `logind.conf` setting, not a NaVILA
project convention.

---
No credential, private token, model binary, or simulator log bundle is stored
in this investigation.
