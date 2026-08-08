# Anchor V3 online inference adapter (2026-08-08, continued)

Scope check with the user before starting: current/next selection quality
was judged good enough (see `HYSTERESIS_AND_BLIND_RECOVERY_FINDINGS.md`'s
section 3, direct comparison against Anchor V2) to move toward a smoke test.
Confirmed to build only a **self-contained adapter first** -- nothing in
`navila-route2-v11-core-20260801` is touched. Wiring this into
`route_memory_agent.py` is future, separately-reviewed work, not started.

## Key finding that made this straightforward

`round_trip_eval.py`'s existing Anchor V2 pipeline already builds
`anchor_transition_pending["raw_candidates"]` (a list of per-candidate dicts
keyed by `anchor_index`, `match_class`, `inlier_count`, etc.) at each
attempt, in the exact schema `anchor_v3/tensorize.py`'s
`tensorize_candidates` already consumes offline -- because the offline
replay dataset was built by capturing this same live structure in the first
place. **No new feature-extraction code was needed**; the adapter reuses
`tensorize_candidates` unchanged.

## `anchor_v3/online_adapter.py`

`AnchorV3OnlineAdapter`: loads a checkpoint once, then exposes
`observe_attempt(candidates, current_points_xyz, anchor_points_by_index,
decision_ordinal, step) -> AtomicDecision`, called once per completed
relocalization attempt. Internally maintains a rolling
`deque(maxlen=sequence_length)` window of tensorized frames (the causal
Transformer's context) plus its own previously-decided `(current, next)`
state, since there is no oracle to supply ground truth at inference time
(offline `teacher.py` does not apply here -- it requires ground truth and
is offline-label-construction only). Every decision is passed through
`anchor_v3.contract.validate_decision` before being returned, so a contract
violation (e.g. a non-adjacent pair) raises immediately rather than
silently reaching a caller.

## Isolated smoke test (`tools/smoke_test_online_adapter.py`)

Replays all 27 real attempts of episode 386 (test split, never trained on)
through the adapter using the actual historical `candidates` field --
structurally identical to what the live runtime would pass, but read from
the recorded JSONL rather than a live process. Result: all 27 attempts
produced a contract-valid decision; predicted current/next tracked the real
route monotonically (4->3->2->1->0); the previously-documented keep/promote
hysteresis window (steps 2464-2534) now shows mostly correct `keep` with
only isolated `promote` calls, not the sustained streak seen on the
pre-keep-weighted-fix checkpoint -- consistent with the fix's effect shown
elsewhere in this session's evaluation.

## Explicitly not done

No live runtime process was started, no episode was launched, no file in
`navila-route2-v11-core-20260801` was read for writing (only for research,
in the previous doc) or modified. This adapter has never been imported by
anything outside `anchor-v3-20260808`.
