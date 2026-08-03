# Changes and worklog

## Offline analysis and model work

1. Re-audited all 12 scoreable Shadow30 episodes for Anchor, Hint, and
   Terminal missed opportunities.
2. Added 1,715 direct-far Terminal query rows to research supervision and
   corrected the far-veto estimator's calibration class-order handling.
3. Rejected the resulting Terminal far-veto model after held-out recall
   collapse.
4. Defined Hint v3 as a bounded evidence-recheck policy over the frozen Hint
   v2 model.
5. Evaluated a stronger Anchor0 visual diagnostic (`confidence >= 0.60`,
   streak 2) without changing live behavior.
6. Wrote the Anchor0/Terminal hard-binding analysis and selected a conditional
   evidence hierarchy for fresh ablation.

## Runtime/scoring changes in isolated candidates

- `stop_gate.py`: records an Anchor0 probe when the state transitions from
  `verify` to `terminal_blind`.  This is observability only; no decision,
  movement, or STOP behavior changes.
- `score_episode.py`: implements strict post-episode scoring for five
  Terminal/A0 policies and explicitly skips episodes missing the replay
  anchor dataset.
- `anchor_transition_online.py` and
  `anchor_transition_promotion_guard.py`: exact frozen Anchor V1 shadow
  implementation used for the attempted unified batch.
- `run_manifest_batch_driver.sh`: manifest-aware batch wrapper.
- `run_unified_shadow50.sh`: frozen preflight, ep670 canary, capture-integrity
  gate, and fresh49 launch orchestration.

The relevant source snapshots are archived under `code/`; focused tests are
under `tests/`.

## Test results

- Hint/Terminal v3 safety candidate: 9 focused tests passed; Python sources
  compiled.
- Shadow29 Terminal-evidence candidate: 25 focused tests passed.
- Unified Shadow50 candidate: 41 focused tests passed.

These tests covered local policy behavior, evaluator wiring contracts,
Anchor parity, promotion-guard behavior, scorer behavior, Terminal-blind
probe logging, and StopGate behavior.  They did not catch the runtime package
namespace collision described below.

## Shadow29 run chronology

### Attempt 0

The isolated evaluator root was incorrectly reused as the V1.1 artifact root.
Preflight failed before simulator execution.  No trajectory was produced.

### Retry1 — ep953

The simulator ran, but the episode began inside the outbound success radius
and ended after one command.  It produced one trajectory and no
`icp_replay_dataset/anchors.json`; strict scoring returned
`SkipEpisode:anchors_missing`.

### Retry2 — ep49

The simulator produced 1,807 trajectory records and the measurement contained
15 route-memory anchors.  The episode did not complete outbound/return, so it
did not produce the replay anchor dataset.  Strict scoring again returned
`SkipEpisode:anchors_missing`, and the remaining 28 episodes were stopped by
the then-overly-strict canary gate.

## Unified Shadow50 run chronology

### Attempt 0

The VLM checkpoint failed to load before Isaac or any episode trajectory
started.  The attempt was retained as infrastructure audit only.  No model or
threshold changed.

### Retry1

- Static and dynamic preflight passed: ep670 plus 49 fresh routes, eight
  scenes, all learned consumers off.
- The VLM server became ready.
- The evaluator failed before creating a trajectory because
  `reliability.anchor_transition_online` could not be imported in the
  evaluator process.
- The driver printed episode exit code 0 even though the evaluator had failed.
- The outer gate then required `capture_completion.json`, did not find it,
  exited nonzero, and prevented fresh49 from starting.
- Service end: 2026-07-30 11:33:28 BST, failed.

Root cause: the evaluator first imports the established V1.1 `reliability`
package.  Adding the unified root to `sys.path` cannot extend or replace that
already-loaded package with a second directory containing
`reliability/anchor_transition_online.py`.  This is a Python package
namespace collision, not an Anchor model failure.

## Frozen hashes

| Artifact | SHA-256 |
|---|---|
| Authoritative GitHub baseline | `a1d50470ccc9c522d95ed76646ce10f6d3c04684` |
| Anchor V1 model | `4d37f9bcb341f093d4cdc87e92c041db7d582a912acdb629963039cf7b27dc55` |
| Hint v2 model | `567e24aef5036e3310a36a8333ab8cc40ee467a293506973fa544fb1baa49603` |
| Hint v3 bounded policy | `21035c66e2748e3bc54f34ee849c6020ab113bf86906a8ce4460d51d41ef26f5` |
| Terminal robust v2 | `f033696bf632134c48edf3ce1734850833c98a93bfdadc7173780ef5ebef6bbb` |
| Rejected Terminal far-veto v3 | `9b6c94999ee804f72793af1b6e94f8ce3d1a5b97819a867bb5b63ecbc140fe03` |
| Unified50 manifest | `4019465c954882b2190fe7ae01d9368c767e402cd75100053418b01a3cafbbfa` |
| Unified protocol | `a88d6ed95531590fcb7d51449d481484a6830ddad29b5b3dd517b01d7024d8c2` |
| Terminal ablation config | `1fde99e000ee9ae0ee50705ee54ad45cca2f3f3baf54ce74c5ab45c0a4adc81e` |
| Evaluator candidate | `fd44c2a485366205beccd37b1f471f68d81dd1b5a860a7b9ab7f634b74a866fe` |
| Route-memory candidate | `e86488f7308f393a839913b369c16a420e4675b762d51e6cf4fa49417aec35c1` |
| StopGate candidate | `37a372ab121f1d7766698ffc89db0e3fce7b7ede1d1680263a22ec7699f5f16b` |

## Deliberately not changed

- no live/stable model was replaced;
- no Anchor, movement, route-state, Hint-execution, or STOP authority was
  enabled;
- no frozen manifest member, model hash, threshold, or preregistered gate was
  changed after observing the launch failures;
- no failed run was counted as an experimental episode.
