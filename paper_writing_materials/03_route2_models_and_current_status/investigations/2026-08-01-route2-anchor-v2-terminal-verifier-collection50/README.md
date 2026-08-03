# Route 2 — 2026-08-01 Anchor V2 and Terminal verifier collection50

> **Superseding 2026-08-01 correction:** later audit proved that this
> collection launched with `reliability_v11_consumer_mode=off`. It is not a
> valid evaluation of the intended V1.1-core Route 2 architecture. The old
> collection was canceled after 24 clean completions; head-specific downstream
> models were retrained through a raw-quality feature firewall, and a new
> development24 + locked-validation20 chain was launched with the V1.1 Core
> consumer active. Start with `CORE_CORRECTION_2026-08-01.md`,
> `COHORTS_24_PLUS_20.md` and `LIVE_CORE_RUN_STATUS.md`. The material below is
> preserved as the earlier time-stamped record, not current architecture
> authority.

## Scope and authority

This investigation records the Route 2 work performed on 2026-08-01 after
the frozen Unified Shadow50 retry4 completed: final result accounting,
isolated Anchor-guard candidate analysis, a rejected Terminal feature-masking
experiment, a causal-evidence availability audit, and launch of a new
50-episode development collection for Anchor V2 shadow behavior and Terminal
candidate-time verifier evidence.

The latest GitHub state was freshly cloned before this record was created.
Five concurrent Route 1 commits landed while it was being drafted; they were
fetched and reviewed before this investigation was committed. The
authoritative parent commit is
`384f19893475f3c1a8240f6c53d1784ec11e4916` (2026-08-01 15:56:58 BST).
The top-level GitHub `README.md` and newer investigations remain authoritative;
old local README/code copies are not project authority.

## Executive status

- **Frozen Unified50:** finished with 48 result summaries; ep855 remained an
  infrastructure-missing episode. Twenty-eight fresh episodes were scoreable
  for the joint Hint/Terminal analysis. Fresh49 remains locked evaluation-only
  and ep670 remains replication-only.
- **Hint v3:** still the strongest of the three Route 2 learned components.
  It made 10 bounded recheck requests with weighted beneficial/non-beneficial
  evidence `8.5 / 1.0`, or `89.47%` beneficial. This is close to, but below,
  the preregistered 90% activation gate and is too small a request population
  for activation.
- **Anchor V1:** did not replicate its encouraging Shadow30 precision. On the
  126 scoreable fresh promotion-truth votes it made two deferrals: one harmful
  catch and one safe delay (`50%` precision, `1/11` harmful-catch recall).
- **Anchor V2 candidate:** keep the frozen model and 0.90 threshold, but treat
  only `rollback` as over-advance risk and include high-confidence
  non-adjacent rollback candidates. Offline shadow replay gives two harmful
  catches, zero safe delays (`100%` precision, `2/11` recall). It is now being
  collected live in strict shadow mode; it has no controller authority.
- **Terminal:** the direct scalar estimator and simple reliability masking are
  not safe enough. A separate candidate-time verifier is the next design, but
  historical logs lack the causal A0 and deployable-motion evidence required
  to fit it responsibly.
- **New collection50:** running as a detached user systemd service. It logs an
  independent A0 RGB-D probe at every return VLM query and Anchor V2
  counterfactuals on one physical trajectory. The declared control effect is
  `none`.

## Decisions made today

1. Do not activate Anchor V1, Anchor V2, Hint v3, or a Terminal policy.
2. Do not tune any candidate on the locked Unified50 fresh cohort.
3. Reject the Terminal reliability-masking negative control.
4. Keep the frozen Terminal V2 estimator as a proposal generator. Collect
   genuinely new evidence for a second-stage verifier rather than replacing
   it with another model over the same correlated scalar features.
5. Treat Anchor0 as corroboration, not a universal necessary or sufficient
   arrival condition.
6. Collect A0 at every return query and reconstruct deployable query-to-query
   motion from action-integrated route-memory state. Never reuse legacy
   `inputs.movement`, which was derived from simulator ground-truth poses.
7. Use repeated-scenario, return-data episodes for this development batch;
   keep Fresh49 and ep670 out of it.

## New collection50 design

The ordered cohort is archived in `data/route2_anchorv2_terminal50.tsv`; the
selection evidence is in `data/selection_evidence.tsv`.

- 50/50 physical episodes have a return-data record.
- 49/50 have at least two historical outbound successes and an aggregate
  outbound success rate of at least 50%.
- The deliberate exception is ep134 (`9/33` historical outbound): it is a key
  Terminal far hard negative and completed round trip in the immediately
  preceding active-promote run.
- Priority Terminal cases are ep87, ep88, ep134, ep310 and ep678.
- The locked Unified50 Fresh49 and replication-only ep670 are excluded.
- Ep368 is the fail-fast canary (`40/40` historical outbound success).
- Port allocation uses `54000 + episode_idx`, with a maximum of 55062. This
  fixes the predecessor launcher's TCP-port overflow failure.

The runtime change is deliberately narrow:

- Anchor V2 runs with `--anchor_transition_guard_mode=shadow`, frozen model
  SHA-256
  `4d37f9bcb341f093d4cdc87e92c041db7d582a912acdb629963039cf7b27dc55`,
  confidence threshold 0.90 and maximum two counterfactual deferrals.
- `--terminal_a0_probe_all_return_queries_shadow` calls the existing
  independent LoFTR/RGB-D A0 probe once per return VLM query. A per-query cache
  lets the unchanged stop gate read the same result when it would already have
  requested the callback. The eager call itself changes no movement, STOP,
  anchor index or controller state.
- All Reliability V1.1 active consumers remain off.
- Hint remains post-episode/read-only.

Static manifest/hash/geometry/port preflight passed. The relevant test set
passed `51/51` in the sklearn-1.7.2 Isaac environment.

## Canary and live status

Ep368 completed round trip successfully:

- `exit_code=0`, complete capture and 3,737 trajectory records;
- 30 return VLM commands and exactly 30 A0 probes;
- 29/30 probes produced an A0 match and 17 confirmed home;
- 318 Anchor predictions and 313 promotion counterfactual decisions;
- `controller_effects=0`.

The first detached service then exited after the valid canary because the
post-episode scorer wrapper declared `tag`, `episode`, and a `result_dir` that
expanded `tag` on the same Bash `local` statement under `set -u`. This was an
orchestration failure after capture, not a VLM/Isaac/model failure. The local
declarations were split, the existing canary was revalidated and reused, and
the remaining 49 episodes were started under a new detached resume service.

At the 2026-08-01 16:00:57 BST snapshot:

- 6/50 episodes were complete and ep4 was running;
- all six completed captures had `exit_code=0`;
- completed IDs: ep368, ep87, ep88, ep134, ep310, ep678;
- reported outcomes: 5/6 outbound, 2/6 return, 2/6 round trip;
- A0 coverage was 252/252 return queries, with 251 available matches;
- accumulated Anchor predictions were 3,198 and all completed episodes had
  `controller_effects=0`;
- no new fatal error, timeout, OOM, port failure or capture-integrity failure
  was present after resume.

See `LIVE_RUN_STATUS.md` for exact service/log paths and resume rules.

## Predecessor active-promote 30ep incident

The Route 1 Phase-3 batch `promotion_active_promote_30ep_20260731` finished at
11:39:41 BST, but its launcher used `PORT_BASE=65000`. Eleven later episodes
therefore requested invalid ports above 65535 (starting with ep647); ep354 had
a separate transient VLM startup failure and ep5 timed out. Nineteen of 30
episodes retained valid outcome and/or trajectory data. The summary contains
17 `exit_code=0` captures, one timeout and 12 VLM-start failures; three
exit-zero captures have blank final outcome summaries but intact JSONL and
trajectory data. Among the 17 completed captures, eight reported outbound
success and four reported round trip success. On the 13 episodes comparable
to baseline, active promotion produced two failure-to-success gains (ep134 and
ep205) and no regressions.

That batch is useful as an operational smoke record but cannot support a clean
30-episode efficacy conclusion. The new Route 2 collection uses a validated
safe port range.

## Relationship to the concurrent Route 1 changes

The same-day Route 1 investigation
`investigations/2026-08-01-anchor0-fix-and-quarantine-veto/FINDINGS.md`
identified ep498's quarantine cascade and an unmatchable synthetic A0 in the
main Route 1 runtime. It added a first-real-descriptor A0 backfill and a
model-backed quarantine veto implemented as an AND-gate: the model cannot
initiate quarantine, but may veto a heuristic quarantine when it has no
independent support.

The current Route 2 snapshot already contains its separate, opt-in
`--route_memory_capture_start_anchor_descriptor` implementation from
2026-07-27 and launched with that flag; this is why eager A0 was available on
251/252 queries in the live snapshot. The newer Route 1 implementation
backfills A0 through the first outbound descriptor instead. These mechanisms
must be reconciled after collection, not hot-patched into the immutable
running Route 2 snapshot.

Route 1's new 30-episode anchor0-fix + quarantine-veto batch is queued under
`navila-quarantine-veto-30ep-queue-20260801.service`. It waits for the detached
Route 2 service to finish before launching, so it does not compete for the GPU
or alter this collection's code, process tree, ports or artifacts.

## Directory map

- `CORE_CORRECTION_2026-08-01.md` — root-cause finding, corrected consumer
  graph, cleaning/retraining results and current model status.
- `COHORTS_24_PLUS_20.md` — development/validation isolation, hashes and
  execution contract.
- `STOP_AND_QUEUE_AUDIT.md` — canceled collection accounting, resource cleanup
  checks and final queue order.
- `LIVE_CORE_RUN_STATUS.md` — time-stamped snapshot of the corrected chain.
- `core_correction/` — exact small docs/config/reports/manifests/source and
  launch provenance for the correction; no model binaries or raw captures.
- `FINDINGS.md` — detailed three-model results and candidate analyses.
- `LIVE_RUN_STATUS.md` — detached-service proof, exact paths, live snapshot,
  and continuation rules.
- `data/route2_anchorv2_terminal50.tsv` — frozen ordered development cohort.
- `data/selection_evidence.tsv` — historical outbound and return-data evidence
  used for cohort selection.
- `data/cancelled_collection50_canary_summary.tsv` and
  `data/cancelled_collection50_batch49_summary.tsv` — final append-only old-run
  accounting at cancellation (24 clean completions plus ep581 incomplete).
- `data/cancelled_collection50_provenance.txt` — immutable old-run identity and
  artifact hashes.
- `code/anchor_v2_candidate.patch` — exact semantic delta from the frozen
  Anchor V1 promotion guard.
- `code/terminal_a0_all_return_queries_shadow.patch` — exact evaluator delta
  for eager observation-only A0 collection.
- `ARTIFACT_MANIFEST.sha256` — integrity hashes for the files archived here.

## Next steps

1. Do not resume the canceled V1.1-off collection50 as Core evidence.
2. Let the frozen Core development24 and locked-validation20 run in order.
3. Separate infrastructure validity, return-data yield and model scoreability.
4. Aggregate Anchor V2 harmful-catch precision/recall and safe-delay rate,
   including adjacent versus non-adjacent rollback cases.
5. Build Terminal candidate windows with per-query A0, action-integrated
   motion/viewpoint displacement, authority transitions and contradictions.
6. Do not fit a verifier until there are at least 30 non-arrived candidate
   events across five scenes and at least two matched arrived controls per
   non-arrived event, with A0 and deployable motion represented in every class.
7. Use scene-grouped development and preserve a completely untouched scene
   before a new prospective shadow run.
8. Require separate authorization before giving any learned component control
   authority.

No access credential, model binary, raw simulator log bundle or video
is stored in this investigation.
