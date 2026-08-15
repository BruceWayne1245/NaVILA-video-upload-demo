# V1.1 distance-head as a quarantine false-positive veto

Date: 2026-08-15
Status: **direction agreed, NOT YET IMPLEMENTED** — to be landed together with the
rest of this session's Line-2 changes (cooldown/closure-off/kdtree batch follow-up).
This document exists purely to record the decision and its evidence before
implementation, per this project's established practice.

## Decision

Add an opt-in, default-off veto on top of the existing quarantine mechanism in
`route_memory_agent.py`: before adding a next-candidate anchor to
`_quarantined_anchor_indices`, consult `/home/teambruce/navila-reliability-v1_1`'s
V1.1 "distance" head (`reliability_v1_1_portable_shadow.json`, `hgb_full_temporal`,
`PortableV11Bundle`/`reliability.v11_runtime.V11ShadowJsonlSession`). If V1.1
confidently vouches for the reading (`p_distance_bad_0p5 <= 0.5`, i.e.
`distance_trusted`), do NOT quarantine — even if the existing heuristic
(`_reading_unreliability` bad-fraction-over-history) says to. This is an additive
safety veto, not a replacement of the existing mechanism.

## Why this and not a from-scratch model

This session first tried to improve on the existing 4-scalar
`_reading_unreliability` z-score rule (root cause of ~57% quarantine false-positive
rate diagnosed earlier this session) via: (a) training a model on the same 4
features (LogisticRegression/RandomForest/GradientBoosting, 5-fold CV) — no gain,
AUC 0.71-0.75 vs the existing rule's 0.764; (b) adding `alias_score` — no
discrimination (0.714 vs 0.734 mean between good/bad); (c) the existing
`loftr_rear_yaw_check` vision cross-check — never fired across 37 eligible
high-confidence readings (it targets yaw/rotation ambiguity, not the
translation/position corridor-aliasing failure mode actually observed); (d)
`corridor_degeneracy_ratio`/`localizability` (raw point-cloud geometric
degeneracy) — no discrimination (0.780 vs 0.724 mean). All four dead-ended before
V1.1 was considered.

## What V1.1 is

Route2's foundational reliability model (`/home/teambruce/navila-reliability-v1_1`),
three HGB heads (bearing/distance/pose) on 249 features (full top-4 ICP basins,
current/next pairwise disagreement, scan_context, localizability eigenstructure,
and causal 4/8/16/32-attempt temporal windows), trained on 91,003 real readings
across 56 physical episodes with physical-episode-grouped, chronologically
separated nested CV. Distance head training-time nested-CV AUC: 0.969.
**Its own prospective-validation protocol (`reports/V11_PROSPECTIVE_PROTOCOL.md`)
is still "predeclared; not yet executed"** — the 0.969 number is a rigorous
cross-validation estimate, not a confirmed held-out result.

## Prospective-style test run in this session

Ran V1.1's own existing inference pipeline (`reliability.v11_runtime`,
`PortableV11Bundle`, unmodified) against 194 real candidate readings from 43
quarantine-jump events (jump_size >= 3) in batch
`line2_closure_off_cooldown_kdtree_100ep_20260815` — data V1.1 never saw during
training (07-21/07-23 dataset; this batch is 08-15, later code, different
terrain sample). Ground truth: real robot position (`trajectories/*.jsonl`) vs
real anchor position, independent of ICP's own self-reported confidence.

- Overall AUC on this out-of-sample set: **0.788** (real generalization drop from
  the claimed 0.969 — expected, given prospective validation was never run; still
  better than anything built from scratch this session).
- Sharply asymmetric precision: `p_distance_bad_0p5 <= 0.5` (confidently-good
  bucket) → **100% precision, 0/54 wrong**, at 28% coverage. `p_distance_bad_0p5
  >= 0.5..0.9` (confidently-bad bucket) → only 60-68% precision, no better than
  the existing rule.
- Applied as a veto specifically to the 152 already-ground-truth-labeled
  "skipped" (quarantined) readings from the earlier `skipped_vs_landed_survey.py`
  investigation: **rescues 41/87 (47%) of the false-positive quarantines**
  (anchors that were actually fine but got quarantined), **with 0/65 (0%) wrongly
  rescued genuinely-bad anchors**.

## Effect on jump behavior (42 scoreable jump events, jump_size >= 3)

| jump size | before veto | after veto |
|---|---|---|
| 1 | 0 | 12 |
| 2 | 0 | 5 |
| 3 | 7 | 7 |
| 4 | 6 | 7 |
| 5 (budget cap hit) | 29 | 11 |

- Landed-on-bad-anchor rate: 48% (20/42) → 29% (12/42).
- Of the 29 original budget-cap (jump=5) events specifically: landed-bad rate
  52% → 34%; only 11/29 still hit the cap after veto (18 land earlier/shorter).
- 27/42 (64%) events had their landing point change under the veto, and **every
  single one of those 27 changed to a correct landing** (0 cases where the veto
  made a landing worse) — consistent with the 0/65 false-rescue rate above.

## Effect on the 37 return-failure episodes (this batch)

- 20/37 have >=1 jump>=3 event somewhere in the episode; 17/37 never do (this fix
  category is irrelevant to their failure — see the companion 2026-08-15 thread on
  those 17).
- Of the 20, looking at each episode's **terminal** (last) jump event:
  - **5 pushed forward** (terminal landing was bad, veto rescues it): ep962,
    ep367, ep264, ep266, ep960.
  - **10 still land bad after veto** (jump size unchanged, 5->5 or 4->4 — V1.1
    found nothing to rescue because the whole skipped block really is bad per
    ground truth): ep646, ep889, ep324, ep555, ep1062, ep829, ep228, ep291,
    ep428, ep733. Open thread (this session, next): are these anchors genuinely
    all bad, and if so does the fix direction become "avoid needing to skip this
    many anchors at all" vs "get the post-skip landing to actually be correct"?
  - **5 have jump>=3 but the terminal jump wasn't the failure's actual cause**
    (landing was already fine before veto too): ep1038, ep490, ep1004, ep476,
    ep895.

Net: on this batch, the veto is expected to remove the specific stuck point in
**5/37 (13.5%)** of return failures. No case in this session's testing shows the
veto making an outcome worse. Whether those 5 episodes' full return then succeeds
depends on downstream mechanisms not covered by this specific fix.

## Implementation sketch (not yet built)

- New opt-in flag, e.g. `sequential_pair_v11_quarantine_veto` (default off,
  mirrors this project's established pattern for every quarantine-adjacent flag
  this session touched: `sequential_pair_reliability_quarantine`,
  `reliability_quarantine_shared_trend_budget`, etc.).
- Load `PortableV11Bundle` once at agent construction (path configurable via
  CLI flag, default `/home/teambruce/navila-reliability-v1_1/artifacts/
  reliability_v1_1_portable_shadow.json`), pure-Python inference, no sklearn
  dependency at runtime.
- Needs a `CausalV11FeatureBuilder`-equivalent wired into the live per-attempt
  covisibility-record capture path (already computes nearly all 249 raw inputs;
  the temporal windows need real per-anchor attempt history, not the
  from-scratch-per-probe approach this session's offline test used).
- Veto point: wherever `_record_next_anchor_reliability` /
  `_record_next_anchor_trend` are about to call
  `self._quarantined_anchor_indices.add(idx)` — skip the add if the V1.1 veto
  fires for that anchor's most recent reading.

## Caveats carried forward

- V1.1's own prospective validation is still unexecuted; this session's 194-row
  test is suggestive, not a substitute for that on a larger sample.
- The candidate-role pairing used in this session's offline test synthesizes a
  fresh `current` reading per probe rather than reusing the agent's real running
  state — live integration needs the real per-attempt current/next pairing, not
  a from-scratch reconstruction.
