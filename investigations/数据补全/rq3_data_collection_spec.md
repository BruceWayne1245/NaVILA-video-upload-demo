# Data collection — online reliability diagnostics (RQ3 quantitative gap)

Fills the one remaining `\draftnote` in the thesis body, at the end of
Section VII-B. Everything here is log parsing; no experiment needs rerunning.

## Why this is being collected

RQ3 asks how large the online reliability deficit is **and which component of
the reliability estimate accounts for most of it**. The first half is answered
(26.2 points on paired episodes). The second half is currently supported only
by a failure-mode classification from a *companion* online run
(`line2_closure_off_cooldown_kdtree_100ep_20260815`), which Section VIII-A has
to disclose as: not the evaluated system, not an independent annotation, and
confirming only that the diagnosed condition occurs rather than that removing
it would recover the episode.

The goal here is to replace that borrowed evidence with the evaluated system's
own measurements, so the component-level attribution rests on the same run that
produced the 55.1% headline number.

## Source

```
batch_logs/policy_v2_active50_replay_on_highsuccess100ep_20260816/ep*_eval.log
```

Restrict to the **M50 episode set** and to the **Return phase only**. Episode
ids are those in
`final_data2/policy_v2_active50_replay_on_highsuccess100ep_20260816_matched50_full_results.tsv`.
Exclude rows with `exit_code != 0`. The Return-phase denominator should be the
49 episodes with `outbound_success == True`; report separately if any of those
49 has no parsable log.

## Existing parsers to start from

`investigations/数据补全/analysis/` already contains working parsers against
the same log format. Reuse rather than rewrite:

- `b4_stop_step_arbiter.py` — parses `[hint_arbiter] step=N override=X
  reason=Y`, pairs STOP proposals with the executed `Vel Command`, and counts
  reason codes. This is the closest starting point.
- `b6_b7_b8_b9.py` — same `arbiter_re` pattern, per-episode aggregation.

Both hardcode `RUN_DIR` at the top; point it at the policy_v2 batch. Note these
were written against an **Oracle** run, where reliability gating is inactive —
the online logs will contain gating lines the Oracle logs do not, so the regexes
will need extending rather than just re-pointing.

## Quantities needed

### A. Per-component authorisation rates

For each Return-phase decision step, whether each reliability component passed
its threshold. Report over all Return steps in the cohort:

| Component | What it gates | Report |
|---|---|---|
| `r_pose` | route-state updates | % of steps withheld |
| `r_bearing` | route hint (D1) and arbiter (D2) | % of steps withheld |
| `r_distance` | terminal verification (D3) | % of steps withheld |

Report both the pooled percentage and the per-episode distribution (median and
IQR), since a few pathological episodes may dominate the pooled figure — that
distinction matters for the write-up.

The bearing authorisation threshold is 0.90 (from the launch config). If the
logs record the continuous confidence value rather than only the binary
decision, **also report the distribution of the value itself**, in particular
what fraction of withheld steps fall in `[0.85, 0.90)`. The companion-run
analysis found a large group of episodes whose readings were accurate but whose
confidence sat marginally below threshold; whether that reproduces here is
directly relevant to whether the deficit is a calibration problem or a
genuine-ambiguity problem, and those two have different remedies.

### B. Online override rate, against the Oracle baseline of 17.3%

Same reason-code breakdown already reported for the Oracle Hint-Action run
(Table III of the thesis), recomputed on the online run:

| Outcome | Oracle value | Online value |
|---|---|---|
| Model action already consistent with hint | 60.8% | ? |
| Conflict; hinted direction not traversable, declined | 15.6% | ? |
| Conflict; hinted direction traversable, overridden | 17.3% | ? |
| Target anchor too close, arbitration skipped | 6.3% | ? |
| **Total decisions** | 1604 | ? |

Also needed: **steps at which the arbiter was not consulted at all because
`r_bearing` withheld authorisation.** In the Oracle run this category is empty
by construction, so it does not appear in Table III, but online it is the
mechanism by which gating suppresses intervention. Report it as a separate row
with its own denominator (all Return steps), and state clearly which
denominator each percentage uses — Table III's percentages are over *logged
arbiter decisions*, and mixing the two denominators would make the online and
Oracle columns non-comparable.

Per-episode override rate distribution (median, mean, IQR) as well, to compare
against the Oracle values of median 12.6% / mean ~15.9%.

### C. Terminal-verifier state distribution

Counts and shares of `accept` / `veto` / `defer` / `force`, over the online run.
If the Oracle Hint-Action-Stop run's logs are still available, compute the same
breakdown there for side-by-side comparison — the thesis argues that distance
evidence remains serviceable online (termination deficit 4.7 → 4.1 points), and
a similar state distribution would corroborate that, while a divergent one would
qualify it.

Also report how many episodes ended by `force` versus by an accepted VLM STOP,
and among failed returns, the terminal state at the final step.

## Output format

A single TSV plus a short markdown summary, in the style of
`thesis_data_collection_report.md`:

- `policy_v2_reliability_diagnostics_<date>.tsv` — one row per episode, columns
  for each quantity above, so per-episode distributions can be recomputed.
- A markdown summary giving the pooled figures, the denominators used, and any
  parsing caveats.

## Reporting requirements

- **State the denominator for every percentage.** Return steps, logged arbiter
  decisions, and episodes are three different denominators and the write-up
  needs to name which one each figure uses.
- **Report parse failures explicitly.** If a log is truncated, or a component's
  gating decision is not recorded at every step, say how many steps are affected
  rather than silently dropping them. A component that appears never to withhold
  authorisation could equally mean it never fired or that it was not logged —
  those must be distinguishable in the output.
- **Do not infer counterfactuals.** The point is to measure which component
  withheld authorisation and how often, not to estimate how many episodes would
  have succeeded had it not. Any change to gating alters the subsequent
  trajectory, so the logs cannot support recovery estimates — the thesis makes
  this limitation explicit for the companion run and the same applies here.
- If a quantity turns out not to be recoverable from the logs, report that
  rather than substituting a proxy; a missing number is easy to write around, a
  silently substituted one is not.

## What happens to the thesis afterwards

- Section VII-B: the `\draftnote` is replaced by these figures.
- Section VIII-A: the companion-run classification drops from primary evidence
  to corroboration, and its three qualifications shrink accordingly.
- Section IX, RQ3: the attribution can be stated directly rather than attributed
  to a supporting analysis on a different configuration.
