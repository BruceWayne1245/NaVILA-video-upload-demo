# Paper data — return-success results from 2026-07-22 onward

## Scope and aggregation rule

This note records the batches identified in `investigations/` with a reported
return/round-trip success rate above 50% from 2026-07-22 onward.  For each
batch, the numerator and denominator are retained exactly as reported.  The
aggregate is the pooled ratio `sum(successes) / sum(denominators)`, not the
arithmetic mean of the percentages.

The project's preferred post-2026-07-22 return metric is conditional on
outbound success.  Historical reports are not fully homogeneous: two Route 2
entries use an explicitly documented geometric/actual-return definition, and
some entries use strict round-trip terminology.  Therefore the pooled number
is a descriptive cross-batch summary, **not** a controlled benchmark or a
causal comparison between methods.

## Included batch records

| Date | Batch / report | Successes | Denominator | Reported rate | Reported metric |
|---|---|---:|---:|---:|---|
| 2026-07-22 | fix-ON A+B+C best-result report | 12 | 19 | 63.2% | ground-truth return success among outbound-success episodes |
| 2026-07-22 | V1.1 shadow batch | 12 | 20 | 60.0% | return success |
| 2026-07-26 | Route 2 Active V2 (analysis freeze) | 18 | 30 | 60.0% | strict round trip among outbound-success episodes |
| 2026-08-03 | Route 2 Anchor V2 full-active | 10 | 15 | 66.7% | actual/geometric return success; strict evaluator result was 7/15 |
| 2026-08-05 | `line2_stopgate_redesign_30ep_20260804` | 7 | 10 | 70.0% | return success among outbound-success episodes, after recovery of one infra-misclassified success |

## Pooled descriptive result

\[
\frac{12 + 12 + 18 + 10 + 7}{19 + 20 + 30 + 15 + 10}
= \frac{59}{94}
= 62.8\%.
\]

Thus, the pooled descriptive return-success rate for the included records is
**59/94 = 62.8%**.

## Source records

- `investigations/2026-07-22-best-result-63pct/README.md`
- `investigations/2026-07-22/FINDINGS.md`
- `investigations/2026-07-26-v2-integrated-anchor-state/README.md`
- `investigations/2026-08-03-route2-anchor-v2-active-66.7-return-success/README.md`
- `investigations/2026-08-05-line2-stopgate-30ep-70pct-milestone/FINDINGS.md`

## Exclusions

The table intentionally excludes batches at or below 50% (for example,
`promotion_shadow_30ep_20260728`, 15/30 = 50%) and partial/in-progress
reports.  It also does not merge the 2026-08-03 strict evaluator result (7/15)
with that batch's actual/geometric result (10/15); the latter is the result
selected above and must not be double-counted.
