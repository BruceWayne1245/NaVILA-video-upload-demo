# Route 2 Hint / Terminal v3 offline decision

Date: 2026-07-30

All work in this directory is isolated and offline. No active controller,
stable model, movement behavior, or stop behavior was changed.

## Hint

Keep the frozen Hint v2 binary estimator and add only a bounded evidence
recheck policy:

- missing clearance and score at or above the frozen advisory threshold:
  request a clearance refresh;
- clear clearance and score at or above the frozen execution threshold, but
  execution streak incomplete: request a stability rescore;
- occupied clearance: always hard-block;
- at most two rechecks per episode/target, with at least ten simulator steps
  between requests;
- no movement-action authority and no stop authority.

Results:

| Evaluation | Recheck rows | Beneficial weight | Non-beneficial weight | Beneficial fraction |
|---|---:|---:|---:|---:|
| Untouched test scene | 23 | 12.25 | 1.75 | 0.8750 |
| Shadow30 scoreable rows | 8 | 6.50 | 1.00 | 0.8667 |

Decision: retain as a shadow-only candidate. It addresses missed
opportunities without weakening the frozen movement execution gate.

## Terminal direct-far veto

The enhanced supervision adds 1,715 previously zero-weight direct-far query
rows while keeping model inputs, row order, episode split, and trajectory
provenance unchanged.

The dedicated far-veto estimator has development OOF AP 0.9333 and ROC AUC
0.8530, but no threshold satisfies the safety constraint without making the
policy inert:

- zero-direct-far development setting: arrived recall 0.0000;
- untouched test: direct-far confirms fall from 24 to 4, but arrived recall
  falls from 0.2692 to 0.0511.

Decision: reject for activation. Current scalar/runtime features are not
sufficient to robustly separate correct terminal tails from visually similar
far tails.

## Terminal A0 visual fallback

The historical independent A0-visual plus repeated-VLM fallback accepted
eight shadow episodes:

- five arrived;
- one boundary;
- two direct-far: ep640 at 4.319 m and ep783 at 3.618 m.

Ep189 was not a case where the old terminal path failed to publish: the
historical gate accepted at step 3391, at 2.645 m.

An observation-only diagnostic requiring two consecutive VLM-stop queries
whose A0 visual confidence is each at least 0.60 changes the shadow counts to
four arrived, one boundary, and zero direct-far. It also loses ep189. This is
not held-out validation: only three pre-shadow episodes (14 probe rows)
contain A0 visual evidence, so the same shadow batch cannot be used both to
inspect the failure and validate the correction.

Decision: do not activate. Log A0 probe evidence on every terminal-blind query
and validate the diagnostic rule on a fresh batch.

## Frozen artifacts

- Hint recheck policy SHA-256:
  `21035c66e2748e3bc54f34ee849c6020ab113bf86906a8ce4460d51d41ef26f5`
- Terminal direct-far veto research artifact SHA-256:
  `9b6c94999ee804f72793af1b6e94f8ce3d1a5b97819a867bb5b63ecbc140fe03`
- Terminal visual-gate diagnostic policy SHA-256:
  `b84050114ace1df2f25c157bca1dadf55cd4101afebc71fe9bac79b533610439`
- Terminal safety dataset SHA-256:
  `cb210b78592321e29c1c5a57bda1ec610eac69f48e59e9f166d63260bbcf7b1d`

Verification: nine focused tests pass; all Python sources compile.
