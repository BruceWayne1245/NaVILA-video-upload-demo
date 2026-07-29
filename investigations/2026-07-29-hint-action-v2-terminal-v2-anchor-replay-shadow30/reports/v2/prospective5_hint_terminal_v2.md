# Prospective 5-episode hint/terminal-v2 replay

This is read-only offline scoring. All five runs have
`control_effect=none`; no evaluator input or output was modified. Episode 319
was parsed with two known repairs in memory, leaving its source JSON
untouched. Episode 430 failed outbound and is not scoreable.

## Dedicated hint-action model

The positive class is a true-far movement conflict where the route hint is
correct and the VLM movement is wrong. Counts below are label-quality
weighted.

| Episode | Old precision | Old recall | Model precision | Model recall |
|---:|---:|---:|---:|---:|
| 319 | 0.9167 | 0.3793 | 0.9615 | 0.8621 |
| 498 | 1.0000 | 0.1538 | 1.0000 | 0.1538 |
| 295 | 0.8889 | 0.6667 | 1.0000 | 0.8333 |
| 1008 | 0.0000 | 0.0000 | 0.6667 | 0.5000 |
| pooled | 0.9130 | 0.3000 | 0.9000 | 0.6429 |

The dedicated model more than doubles prospective intervention recall at
nearly unchanged pooled precision. It also recovers four interventions that
the old gate misses entirely in ep1008, but makes two false interventions in
that episode. This is strong evidence for a separate controller and equally
strong evidence against activating v1.

## Robust terminal v2

The frozen sequence rule is `p(arrived) >= 0.713282` for four consecutive
queries.

- ep319: zero false-far confirmations, but zero arrived recall;
- ep498 and ep295: zero false-far confirmations;
- ep1008: 26 confirmed arrived rows, arrived recall 0.7027, zero false-far
  and zero boundary confirmations;
- pooled scoreable cohort: 26/41.5 weighted arrived rows confirmed and no
  false-far confirmation.

The prospective result is safe but not sufficient for promotion: the
untouched historical test scene still has five true-far false-arrived
confirmations.

Machine-readable source:
`prospective5_hint_terminal_v2.json`.
