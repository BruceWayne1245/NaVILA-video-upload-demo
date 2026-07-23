# Verification record

Date: 2026-07-23

No Isaac process or GPU workload was launched while constructing or checking
this framework. All checks below were CPU-only.

## Completed checks

- Full V1.1 project test suite: 27 passed.
- Python compilation:
  - `reliability/v11_runtime.py`
  - `candidate/scripts/reliability_v11_portable_runtime.py`
  - `tools/validate_v11_shadow_jsonl.py`
  - `tools/replay_v11_decision_shadow.py`
  - `tools/score_v11_control_readiness.py`
  - candidate `round_trip_eval.py`
- Frozen runner preflight: passed all runtime, portable artifact, policy,
  gate, validator, and scorer hashes.
- Synthetic decision-event validation: passed.
- Old 5ep-canary replay: 698/698 counterfactual decisions reconstructed
  without changing the recorded controller events.
- Independent old-canary rescore:
  - ep539: 472 candidate rows, passed;
  - ep579: 530 candidate rows, passed;
  - ep688: 242 candidate rows, passed;
  - ep448 and ep691: no score rows, correctly classified non-evaluable.

## Locks checked

- policy mode remains `shadow`;
- `enforcement_approved=false`;
- `identity_override_authorized=false`;
- every decision records `controller_effect=false`;
- posthoc truth is declared unused for features, scoring, and decisions.

## Not yet tested

The final merged Route-1 entry point and its 100ep runner do not exist in this
snapshot, so their final hashes and the first live decision event must be
checked by Claude after integration and before the batch launch. Real
enforcement is intentionally absent from this version; it is permitted only
after the frozen 100ep readiness contract passes.

