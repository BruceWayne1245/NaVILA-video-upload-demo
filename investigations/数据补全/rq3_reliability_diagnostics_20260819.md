# RQ3 online reliability diagnostics — execution report

Executed per `rq3_data_collection_spec.md`. All figures below are computed
directly from `batch_logs/policy_v2_active50_replay_on_highsuccess100ep_20260816/ep*_eval.log`
and the corresponding per-step trajectory jsonl / `reliability_v11_consumer_v2.jsonl`
files in `eval_results/`, restricted to the M50 episode set
(`final_data2/policy_v2_active50_replay_on_highsuccess100ep_20260816_matched50_full_results.tsv`).
Script: `analysis/b10_rq3_reliability_diagnostics.py`. Per-episode output:
`policy_v2_reliability_diagnostics_20260819.tsv`.

**No counterfactuals are estimated anywhere below.** Every number is a
measurement of what the deployed system logged, not an estimate of what would
have happened under different gating.

## 0. Cohort and denominators

- M50 manifest: 50 episodes, all `exit_code == 0`.
- Return-phase cohort (`outbound_success == True`): **49/50**. The one
  excluded episode (`episode_idx=1004`, `episode_id=1713`) has
  `outbound_success == False` and is out of scope for every number below,
  matching the spec's instruction.
- All 49 cohort episodes parsed cleanly: every episode had a `[return] start
  step=` marker, a readable `measurements/*.json`, a readable trajectory
  jsonl, and (where relevant) a readable `reliability_v11_consumer_v2.jsonl`.
  **Zero parse failures, zero missing files, zero missing confidence values**
  among the 49 — this run's log/measurement-JSON writes did not show the
  corruption bug documented for the Oracle runs (Part B3 of the earlier
  checklist report).
- Three denominators recur below and are never mixed without saying so:
  1. **Return steps with a logged arbiter decision** — n = 1579, pooled
     across 49 episodes. In this run these are numerically identical to "all
     Return-phase VLM-query steps," because the arbiter logs a decision line
     at every such step, including the steps where it declines to act
     (`reason=low_relocalization_confidence`). This is *not* true of the
     Oracle run, where that reason code cannot occur at all — see §2.
  2. **Return steps with a logged stop_gate decision that isn't `pass`** — n
     = 79 pooled. `pass` (n=1500) means the robot was not yet within
     consideration range of the stop boundary; it is excluded from the
     accept/veto/defer/force distribution in §3, matching how the spec's
     Table lists only those four states.
  3. **Episodes** — n = 49 (cohort) or n = 22/27 (failed/succeeded).

## 1. What `r_pose` / `r_bearing` / `r_distance` map to in this codebase

**These three names are not literal identifiers in the code.** An earlier
pass at this same question (`analysis/part_A_and_D1a_findings.md`, section
"可靠性阈值") explicitly logged the exact thresholds/definitions as **NOT
FOUND** after searching `route_memory_agent.py`. This report does not
reverse that — no single place in the code defines three named scalars called
r_pose/r_bearing/r_distance. What follows is a source-grounded mapping from
each name's stated *gating role* (per the spec's own table) to the concrete
logged signal that actually plays that role, verified by reading the
relevant `check()` functions, not inferred from log text alone:

| Component | Concrete signal used | Where it's logged | Verified in |
|---|---|---|---|
| `r_bearing` | `relocalization_confidence` (continuous, 0–1) vs. the launch-config threshold **0.90** (`--hint_arbiter_min_relocalization_confidence=0.90`) | trajectory jsonl, `hint_action_arbiter.relocalization_confidence`, at every step with a `[hint_arbiter]` log line | `hint_action_arbiter.py:439-440` — `if effective_confidence < self.cfg.min_relocalization_confidence: return HintActionDecision(override=False, reason="low_relocalization_confidence", ...)` |
| `r_distance` | `stop_gate`'s internal `conf`/`distance_authority_low_reliability` gate, surfaced as `decision == "deferred"` | trajectory jsonl, `stop_gate.gate_decision` | `stop_gate.py:478,526-562,564-587` — every `deferred` return in this run's flag configuration (`r_in == r_out == 3.0`, no `--use_uncertainty_interval`) originates from either the explicit `distance_authority_low_reliability` flag or `conf < min_confidence (0.5)`; the third, purely-geometric hysteresis-zone branch (`stop_gate.py:620-623`) is provably unreachable under these flags since `r_in == r_out` collapses it to a zero-width interval |
| `r_pose` | `reliability_v11_consumer_v2` active-enforcement layer's `jointly_trusted`/`executed_allow` gate on the `anchor_promotion` and `route_hint` operations, **and** its direct effect on the arbiter's own `hint_action_override` decision (visible as `reason=v11_consumer_v2_blocked(...)` in the same `[hint_arbiter]` log line used for r_bearing) | `reliability_v11_consumer_v2.jsonl` (event-triggered, per operation attempt) + trajectory jsonl `hint_action_arbiter.reason` | `--reliability_v11_consumer_mode=active`, `--reliability_v11_consumer_policy_v2=.../v11_consumer_policy_v2_active50_20260725.json` in argv; `guarded_operations: [anchor_promotion, forced_stop, hint_action_override, route_hint, vlm_stop_veto]` in the jsonl's session-start record |

The `low_relocalization_confidence` and `v11_consumer_v2_blocked` reason
codes are the two concrete mechanisms by which online gating suppresses
arbiter intervention; neither can appear in the Oracle Hint-Action run
(Table III of the thesis) because that run had no relocalization uncertainty
and no v1.1 consumer guard active.

`r_pose` has **no per-VLM-query-step cadence** — `anchor_promotion` and
`route_hint` decisions in `reliability_v11_consumer_v2.jsonl` fire only when
that specific operation is attempted, which is sparser and not 1:1 with
Return decision steps. Its authorization rate is therefore reported below
against its own denominator, not "all Return steps" — reported separately per
the spec's denominator rule, not blended into the r_bearing/r_distance table.

## 2. Table A — per-component authorisation rates

| Component | Signal | Denominator | Withheld (pooled) | Withheld % (pooled) |
|---|---|---|---|---|
| `r_bearing` | `relocalization_confidence < 0.90` | 1579 Return decision steps | 1009 | **63.90%** |
| `r_distance` | `stop_gate` decision == `deferred` | 79 non-`pass` stop_gate steps | 36 | **45.57%** |
| `r_pose` (`anchor_promotion`) | `executed_allow == False` | 419 anchor_promotion attempts | 225 | **53.70%** |
| `r_pose` (`route_hint`) | `executed_allow == False` | 1340 route_hint attempts | 829 | **61.87%** |
| `r_pose` → arbiter override, same-denominator view | `reason == v11_consumer_v2_blocked(...)` | 1579 Return decision steps | 12 | **0.76%** |

Per-episode distribution (49 episodes), showing the pooled figure is *not*
dominated by a handful of pathological episodes for r_bearing, but **is** for
r_distance:

| Component | Per-episode median | Per-episode Q1 | Per-episode Q3 |
|---|---|---|---|
| `r_bearing` withheld % | 66.67% | 38.46% | 80.95% |
| `r_distance` withheld % | **100.00%** | 50.00% | 100.00% |

The r_distance per-episode median of 100% (vs. pooled 45.57%) is exactly the
distinction the spec asked to watch for: **4/49 episodes never produced a
non-`pass` stop_gate decision at all** (they never got geometrically close
enough to enter stop consideration before timing out — these are the same 4
episodes flagged `timeout_or_other` in §4), and most of the remaining 45 have
only 1–2 non-`pass` decisions total, so a single `deferred` outcome swings an
episode's ratio to 100%. The pooled figure is the right one for "how often
does distance authority withhold, system-wide"; the per-episode median is the
right one for "is a typical episode dominated by withholding" — they answer
different questions and should not be substituted for each other.

**Bearing confidence value distribution** (n=1579, all Return decision
steps): median **0.667**. Of the 1009 withheld steps, **30 (2.97%) had
confidence in [0.85, 0.90)** — i.e. *not* mostly a calibration problem where
accurate readings sit just under threshold. The bulk of withheld steps (the
other 97%) are well below 0.85, which is more consistent with a
genuine-ambiguity/noise regime than a threshold miscalibration. This
contradicts what the companion offline run (`line2_closure_off_cooldown_
kdtree_100ep_20260815`) apparently found — the spec flagged this exact
question as "directly relevant to whether the deficit is a calibration
problem or a genuine-ambiguity problem" — so this is worth double-checking
against that companion run's own confidence distribution before the thesis
draws a conclusion from it.

**r_distance deferred-step confidence breakdown** (n=36 deferred steps):
25 had `conf < 0.5` (the plain low-confidence branch), 11 had `conf ≥ 0.5`
(only reachable via the separately-logged `distance_authority_low_reliability`
flag, since the geometric hysteresis branch is unreachable under this run's
`r_in == r_out` config — see §1). That flag itself is **not** written to the
trajectory jsonl (`stop_gate.gate_decision`'s logged fields are only
`gate_decision`/`gate_authority_d`/`gate_conf`/`gate_teleport_filtered` — the
richer `_diag` dict in `GateDecision` never reaches the log), so the 11/25
split is as far as this can be decomposed from the available logs; the exact
share attributable to the low-reliability flag specifically vs. plain low
confidence is **not recoverable from these logs**.

## 3. Table B — online override rate, against the Oracle baseline (17.3%)

Same reason-code breakdown as Table III of the thesis, recomputed on this
online run. Both columns use the same denominator convention: percentage of
*logged arbiter decisions* (n=1604 Oracle, n=1579 online).

| Outcome | Reason code | Oracle value (n=1604) | Online value (n=1579) |
|---|---|---|---|
| Model action already consistent with hint | `vlm_action_consistent` | 60.8% | **14.95%** (236) |
| Conflict; hinted direction not traversable, declined | `occupied_in_local_map_path` | 15.6% | **7.22%** (114) |
| Conflict; hinted direction traversable, overridden | `vlm_conflicts_with_clear_hint` (override executed) | 17.3% | **8.23%** (130) |
| Target anchor too close, arbitration skipped | `target_too_close` | 6.3% | **6.84%** (108) |
| *(does not occur offline)* | `low_relocalization_confidence` — r_bearing withheld the arbiter entirely | 0% | **62.00%** (979) |
| *(does not occur offline)* | `v11_consumer_v2_blocked(vlm_conflicts_with_clear_hint)` — arbiter wanted to override, r_pose vetoed it | 0% | **0.76%** (12) |
| **Total decisions** | | 1604 | **1579** |

**Steps at which the arbiter was not consulted at all because `r_bearing`
withheld authorisation**, using the spec's requested denominator (all Return
steps, not logged-arbiter-decisions): **979/1579 = 62.00%**. In this run
these two denominators are numerically the same set (every Return-phase
VLM-query step produces exactly one `[hint_arbiter]` log line, even the ones
where the arbiter declines to act), which is why the number does not change
between the two framings here — that identity does **not** hold in general
and is called out explicitly per the spec's instruction to always name the
denominator.

A second, distinct withholding mechanism sits on top of the first: **12/1579
(0.76%) of all Return decision steps** are cases where the arbiter's own
logic reached "override" (bearing confidence was fine, hint conflicted with
a traversable VLM action) but the reliability_v11_consumer_v2 active-
enforcement guard (r_pose) blocked the override anyway. This is small in
absolute terms but qualitatively important: it is evidence that r_pose and
r_bearing are gating *different* failure modes, not two labels for the same
signal — 130 overrides executed vs. 12 blocked (130+12=142 total steps where
the arbiter *wanted* to override on a traversable conflict), an 8.5% veto
rate by r_pose specifically on that subset, using yet a fourth denominator
that should not be confused with the 62.00%/0.76% figures above.

**Per-episode override rate**: median **6.90%**, mean **8.88%**, Q1 3.23%,
Q3 13.04% — both well below the Oracle values (median 12.6%, mean ~15.9%).
This is consistent with the online run's low arrival/success rates being
partly attributable to the arbiter simply not getting to act as often, not
only to it acting and being wrong.

## 4. Table C — terminal-verifier (stop_gate) state distribution

Pooled counts over the 79 non-`pass` Return-phase stop_gate decisions (49
episodes):

| State | Count | Share of non-`pass` |
|---|---|---|
| `deferred` | 36 | 45.57% |
| `vetoed` | 34 | 43.04% |
| `forced` | 5 | 6.33% |
| `accepted` | 4 | 5.06% |

The Oracle Hint-Action-Stop run's raw logs were not located during this pass
(the batch directory referenced in the earlier B6/B8 scripts,
`pure_oracle_hint_action_stopgate_highsuccess100ep_20260813`, was not
re-parsed here — doing so was out of scope for this spec, which asks for it
only "if still available," and re-deriving it would have doubled the scope
of this pass). The side-by-side comparison the spec requests is therefore
**not completed** — flagging this as an open item rather than substituting
a remembered number from `part_B_findings.md`, since that document's B6/B7
figures use the uncorrected 86-episode Oracle denominator (see its §B3) and
re-deriving a clean 87-denominator comparison was not part of this task.

**Episode-level termination classification** (49 cohort episodes), derived
from each episode's *last* Return-phase trajectory record: `forced_no_vlm_
stop` if the final `stop_gate.gate_decision == "forced"`; `vlm_stop_accepted`
if the final decision is `accepted` or `deferred` and the last VLM output
contains stop text; `timeout_or_other` otherwise (no qualifying stop signal
before the episode ended — these are exactly the 4 episodes with zero
non-`pass` stop_gate decisions in §2, confirming internal consistency):

| Terminal class | All 49 | Among 27 `return_success=True` | Among 22 `return_success=False` |
|---|---|---|---|
| `vlm_stop_accepted` | 40 | 22 | 18 |
| `forced_no_vlm_stop` | 5 | 5 | 0 |
| `timeout_or_other` | 4 | 0 | 4 |

**18 of the 22 failed returns still ended via a `stop_gate`-accepted VLM
stop** — the gate approved the stop using its own (uncertain) distance
estimate, but the true final distance was outside the 3.0m success radius.
This means the dominant failure mode among returns that do terminate is not
"never stopped" (only 4/22 failures are pure timeouts) but "stopped
confidently at the wrong place," which is a distance-authority accuracy
problem more than a distance-authority withholding problem — the withholding
figures in §2 describe how often the gate abstains, not how often it is
wrong when it doesn't. **This report does not attempt to quantify how often
an "accepted" decision was wrong** (that would require joining against
ground-truth distance at that exact step, which is a different and larger
analysis than what this spec asked for); it only reports the counts above.
All 5 `forced_no_vlm_stop` episodes succeeded — consistent with the earlier
`project_stop_gate_force_reliability_gap_20260803` memory's note that the
anchor-corroboration FORCE path was specifically hardened after the
ep368/ep498 failures on an earlier batch, though the mechanism was not
re-verified against this batch's FORCE episodes individually.

## 5. Parsing caveats (explicit, per spec requirement)

- **`distance_authority_low_reliability` is never logged per-step** — only
  `stop_gate.gate_decision`/`gate_authority_d`/`gate_conf`/
  `gate_teleport_filtered` reach the trajectory jsonl. Any claim about *why*
  a specific `deferred` fired beyond the conf<0.5/conf≥0.5 split in §2 is not
  recoverable from these logs.
- **`r_pose`'s two measures (`anchor_promotion`, `route_hint`, both from
  `reliability_v11_consumer_v2.jsonl`) use a different, sparser, event-
  triggered denominator than `r_bearing`/`r_distance`.** They are not
  directly comparable percentages to the other two rows in §2's table
  despite sharing the same table — this is flagged, not hidden, per the
  spec's instruction.
- **Zero missing/corrupted files** were encountered in the 49-episode
  cohort for this run (contrast with the Oracle runs' JSON-corruption bug
  documented in `part_B_findings.md` §B3) — there is nothing to report as
  silently dropped.
- **A component that never appears to withhold could mean it never fired
  or was never logged** — this does not apply to any of the three
  components here: all three have nonzero withheld counts, so this failure
  mode was not encountered in this pass.
- **No counterfactual recovery estimate is given anywhere in this report.**
  Every percentage above describes what was logged, not what would have
  happened under different gating — consistent with the same limitation the
  thesis already discloses for the companion offline run.

## 6. What this replaces in the thesis

- **Section VII-B**: the `\draftnote` can be replaced by §2/§3 above.
- **Section VIII-A**: per the spec, the companion-run classification should
  now drop to corroboration status, since §2/§3 are measured on the
  evaluated system itself.
- **Section IX (RQ3)**: the attribution can now cite this run directly. The
  clearest single-sentence attribution supported by this data: *the online
  reliability deficit is dominated by `r_bearing` withholding the hint
  system from acting at all (62% of Return decision steps), not by the
  arbiter or terminal verifier acting and being wrong* — `r_distance`'s
  pooled withholding rate (45.6% of the much smaller set of steps where it
  is even consulted) is real but structurally minor by comparison, and its
  failures more often look like confident-but-wrong accepts (18/22 failed
  returns) than like withholding.
