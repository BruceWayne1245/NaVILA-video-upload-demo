# Paper Handoff — Reliability-Aware Sparse Route Memory (MSc Thesis)

**Last updated:** 2026-08-13
**Purpose:** State transfer document. Upload at the start of a new conversation so work can
continue without re-deriving prior decisions.

---

## 0. How to use this document

Read sections 1–3 first (structure, decisions, data). Section 4 lists open problems that must
be fixed. Section 5 lists pending experiments with pre-written placeholders. Section 6 records
working preferences.

If numbers in this document conflict with `final_data/` in the repo
(`BruceWayne1245/NaVILA-video-upload-demo`), **the repo wins** — it is updated more often than
this file.

---

## 1. Paper structure (current, agreed)

```
I.    Introduction                          — written, needs updates (see §4.1)
II.   Related Work                          — written, minor fixes pending
III.  Problem Formulation                   — written (task + metrics)
IV.   Reliability-Aware Sparse Route Memory — written (method: memory + 3 interfaces)
V.    Experimental Setup and Comparison Configurations — written, cohort definitions MISSING
VI.   Diagnostic Analysis                   — VI-A written; VI-B needs rewrite (see §4.2)
VII.  Results                               — DOES NOT EXIST YET
VIII. Discussion                            — DOES NOT EXIST YET
IX.   Conclusions                           — exists but numbered VII in the current file
Appendices A/B/C                            — all DRAFT NOTE placeholders
```

A major restructuring was already performed: method content was split out of Problem
Formulation into its own Section IV, and the experimental setup moved to Section V. The
current PDF still shows Conclusions as Section VII because Results and Discussion have not
been created yet.

### Section IV interfaces (method)

Three functionally separated interfaces, each authorised by its own reliability component:

| Interface | Symbol | Addresses | Reliability gate |
|---|---|---|---|
| Structured route hint | `h_t` | D1 | `r^bearing_t` |
| Hint-Action arbiter | Eq. (12) | D2 | `r^bearing_t` + occupancy check |
| Terminal verification | `v^stop_t` | D3 | `r^distance_t` |

Route-state update `b_t = f(b_{t-1}, z_t, r_t)` gated by `r^pose_t`.

---

## 2. Key decisions already made (do not re-litigate)

**RQ framing = "Plan 2".** RQ2/RQ3 are framed around *which interfaces an external reference
should act through, and how large the online reliability deficit is* — NOT around "how to
validate and accumulate geometric evidence". Reason: the non-Oracle system plateaus at
~60–70% while the Oracle ceiling is far higher, so a reliability-centric RQ would read as an
unmet goal. Under Plan 2 the same gap is a *measured finding*.

**D1/D2/D3 promoted to the Introduction.** The three failure dimensions (directional
observability / recovery from deviation / stability of arrival judgement) are introduced in
Section I-C and reused throughout. This was conditional on adding more controlled pairs to
support the reduction (see §5.3).

**`hard-11` renamed.** Now the *diagnostic subset* `\mathcal{D}_{\mathrm{diag}}`, stated to
belong to the development cohort and used for mechanism diagnosis, not generalisation.
Figure/table captions still say "hard-11" and must be updated.

**Division of labour between datasets.** `D_diag` carries *qualitative mechanism* evidence
(per-episode trajectories, failure morphology). The high-success 100-episode sample carries
*all quantitative claims*. This split must be stated explicitly in the text so readers know
which numbers are authoritative.

**Related Work gained a runtime-intervention strand** (Section II-A): predictive safety
filters [Wabersich & Zeilinger 2021], residual policy learning [Johannink et al. 2019],
pre-execution feasibility verification [Lin et al. 2023, Text2Motion]. All three verified via
web search. The strand exists so the Research Gap can argue that action-level arbitration is
mature in robot control but unstudied in VLN.

---

## 3. Confirmed data (use these numbers)

### 3.1 Main result — high-success 100ep sample

Same manifest, flags differ only.

| Configuration | Outbound | SR_ret\|out |
|---|---|---|
| Oracle Hint | 86/100 | 32/86 = **37.2%** |
| Oracle Hint-Action | 86/100 | 52/86 = **60.5%** |

Paired analysis on the 76 episodes with outbound success in *both* runs:
- Hint 26/76 = 34.2% → Hint-Action 43/76 = 56.6%
- 23 fail→success, 6 success→fail
- **exact McNemar two-sided p = 0.002**

### 3.2 Arbiter decision breakdown (3094 return-phase decisions, 87 episodes)

| Reason | Count | Share |
|---|---|---|
| VLM action already consistent with hint | 1699 | 54.9% |
| Conflict, but hinted path occupied → declined | 727 | 23.5% |
| Conflict, hinted path clear → **overridden** | 503 | **16.3%** |
| Target too close, skipped | 165 | 5.3% |

Derived:
- **VLM conflicts with the supplied correct direction in 39.8% of steps**
- Of those conflicts, 40.9% overridden
- VLM output retained on 83.7% of decisions
- Per-episode override rate: median 13.3%, 70/87 episodes have ≥1 override

### 3.3 Correction to the "4.3%" figure — MUST be fixed in the text

The historical 4.3% (15/348) was measured with the arbiter **bundled** with
`--oracle_align_return_yaw_to_anchor_segment` and `--stop_gate`. Yaw-oracle had already
removed most heading noise, so the arbiter's workload was systematically understated.

| Measurement | Decisions | Overrides | Rate |
|---|---|---|---|
| Historical (bundled) | 348 | 15 | 4.3% |
| **Isolated arbiter (this sample)** | 3094 | 503 | **16.26%** |
| Isolated arbiter (canonical-100 cross-check) | 2480 | 433 | 17.46% |

Two different manifests agree within 1.2 points → 16–17% is a property of the isolated
arbiter, not of the sample. **Delete "4.3% of decisions" from Introduction contribution 3.**

### 3.4 Selection-effect check (resolves a long-standing concern)

Override rate, successful vs failed return episodes:

| | n | median | mean |
|---|---|---|---|
| Return success | 52 | 13.3% | 15.4% |
| Return failure | 34 | **8.6%** | 20.0% |

Failed episodes have a *lower* median override rate, which rules out "less intervention
therefore success" as an explanation.

### 3.5 Arrival vs termination separation — first D3 evidence

| | Ends < 3.0 m | Judged success | Reached-but-not-stopped |
|---|---|---|---|
| Oracle Hint | 34/86 (39.5%) | 32 | 2 |
| Oracle Hint-Action | **61/86 (70.9%)** | 52 | **9** |

Of the 6 success→fail episodes, **four ended up closer**: id 422 (2.745→1.103 m), 500
(3.008→0.734), 1378 (0.784→**0.205**), 1523 (1.955→2.495). Only 1379 (1.969→4.043) and 143
(1.200→6.214) genuinely degraded.

**Interpretation:** the arbiter compensates D2 (arriving) but leaves D3 untouched, and by
making arrival more frequent it *exposes* D3 more often. Headroom for the stop gate:
60.5% → 70.9%, i.e. 10.4 points.

### 3.6 D_diag material (demoted to qualitative use)

Fig. 2 grids, Table I pairing, four failure episodes at 13.722 / 8.095 / 7.554 / 11.440 m.
The 50.0% and 94.4% figures may remain as a side note but must no longer carry the argument.

### 3.7 Baseline — NOT usable as-is

canonical-100 language-only: 34/100 outbound, 7 round-trip = 20.6% (17.9% with historical
merge). **Different manifest from all Oracle runs — only 30/100 episode overlap.** Cannot be
compared. See §5.1.

On the 30 shared ids: baseline 7/28 = 25.0%, hint 9/27 = 33.3%, hint-action 14/23 = 60.9%
(directionally consistent, samples too small to cite).

---

## 4. Open problems in the current draft

### 4.1 Introduction

- **Contribution 3 still cites 50.0% → 94.4% and "4.3% of decisions".** Must be replaced with
  37.2% → 60.5%, paired 34.2% → 56.6%, McNemar p = 0.002, and the 39.8% conflict rate.
- **Contribution 6 is an empty numbered item** — will render as a blank entry.
- **New contribution to add:** the arrival/termination separation (§3.5). Draft text:
  > An empirical separation of the arrival and termination failure modes. Action-level
  > arbitration raises the proportion of episodes terminating within the 3.0 m success radius
  > from 39.5% to 70.9%, yet the success rate reaches only 60.5%: the residual 10.4 points
  > consist of episodes that reach the start region but fail to terminate there. Improving the
  > agent's ability to arrive therefore exposes, rather than resolves, the instability of its
  > arrival judgement.
- Report Structure (I-E) has five `??` references.

### 4.2 Section VI-B (Oracle analysis) — needs rewrite

- Observation 1 must lead with 37.2% (86 episodes), with `D_diag` trajectories demoted to
  failure-morphology illustration.
- Observation 2 title "The Size of the Deficit—4.3% of Decisions" is now wrong. Suggested
  replacement: **"The Size of the Deficit: How Often the Policy Contradicts Correct
  Information"**, built on the 39.8% conflict rate and the reason-code table.
- Add a paragraph documenting the 4.3% → 16.26% correction (§3.3). This *strengthens* the
  paper — it demonstrates experimental rigour.
- Add a new subsection on arrival vs termination (§3.5) — this is the only D3 evidence in the
  paper.
- Add the selection-effect check (§3.4).
- One `??` in Observation 1 pointing to the terminal-verification evaluation.

### 4.3 Section V — cohort definitions are MISSING

Three episode sets are used and none is defined:

1. `D_diag` (ex-hard-11): 11 hand-picked difficult episodes. **Selection criteria unknown —
   only Bruce knows whether baseline failure outcomes were used to select them.** If they
   were, a selection-bias caveat is mandatory.
2. canonical-100: standard manifest, 26–43% outbound success across six historical batches.
3. high-success-100: top 100 of 264 episode ids ranked by historical outbound success rate,
   weighted historical outbound success 884/932 ≈ 94.85%. Overlaps canonical-100 by 30.

Defence for using high-success-100 (this argument is sound and should be written out):
selection was performed on *outbound* outcomes only and is independent of return-phase
performance, so `SR_ret|out` remains interpretable; `SR_rt` is inflated by construction and
should be reported for completeness only.

Also required in Section V: pairing tolerance statistics (distance from `P_ret` endpoint to
`s_0`, mean/max, and the exclusion bound — anything above ~1.5 m should be dropped given the
3.0 m success criterion).

Threats to validity: 28/100 episodes in high-success-100 were selected on n=1 historical
evidence.

### 4.4 Section IV-C2 — DRAFT NOTE still open

Need the implementation values: the conflict criterion of condition 2 (angular threshold or
action-set incompatibility), the occupancy check radius/criterion of condition 3, and the
construction of `a^β_t`. The 23.5% "declined due to occupancy" figure can now be cited as
evidence that condition 3 does real work.

### 4.5 Section II — leftovers

- Orphan heading `D. System Overview` at the end of Section II with no content — delete.
- Section II opening paragraph and the II-C closing summary list both omit *runtime action
  intervention*, which was added to II-A. Add it to both.

### 4.6 Figures and tables

- Fig. 2 caption still says "hard-11 batch" → change to `D_diag`.
- Table I and Table II appear in reverse order relative to the text.
- Trajectory grids will be regenerated from the high-success-100 runs later; do not invest in
  the current ones.

### 4.7 Undefined metric

SPL is used in VI-A (Episode 705, SPL 0.892) but never defined. Add to Section III-B.

### 4.8 Hint template confound (unresolved)

All hints use one template:

```
[System Hint: route anchor A10 is 0.58 m away, ahead; estimated remaining route via anchor
is 10.66 m; next-anchor vector dx=0.58 m, dy=0.02 m.]
```

Weaknesses a reviewer can attack: redundant/heterogeneous encoding (dx/dy alongside natural
language); "ahead" is a quantised direction word while the arbiter uses continuous `β_t`, so
the two interfaces receive different precision; "A10" is meaningless to the model; the
`[System Hint: ...]` format is out of NaVILA's training distribution.

Existing defences: failure magnitudes (8–13 m) are inconsistent with mere wording problems;
and 187/367/994 recovered with the hint text unchanged, by action-level arbitration alone.
Trajectory shape also changes visibly once hints are supplied, showing the hints are read.

**Required:** put the template in Section IV-C1 (currently absent from the paper entirely),
and add a paragraph in VI-B acknowledging the single-template limitation. **Optional but
valuable:** run 2–3 hint template variants on `D_diag` to show insensitivity.

---

## 5. Pending experiments (with pre-writable placeholders)

### 5.1 Baseline on high-success-100 — MUST DO, highest priority

Without it the main table has no first row and RQ1 is unanswerable.

**Expected range:** 25–35% (from the 30-episode overlap: 25.0%).

**If it lands near 35%**, i.e. close to Oracle Hint's 37.2%, that is a *strong* finding:
external information by itself buys almost nothing, and essentially all the gain comes from
the action-level constraint. Have wording ready for this outcome.

**Placeholder:** main table row 1 = `[X]%`. All baseline comparisons in VI-B should currently
say "see Section VII" without stating a delta.

### 5.2 Non-Oracle full architecture on high-success-100 — MUST DO

**Expected:** 60–70% (Bruce's own estimate).

**Caution:** Oracle Hint-Action (no stop gate) is already 60.5%, whereas the non-Oracle full
system *includes* the stop gate. If non-Oracle lands at 60–70%, the online-estimation loss and
the stop-gate gain are confounded and cannot be separately attributed.

**Recommended addition:** a non-Oracle run *without* stop gate, which pairs strictly with
Oracle Hint-Action and isolates the pure cost of degraded information quality. This is more
valuable than the full-architecture run for RQ3.

**Placeholders:** Introduction contribution 5 = `[X]% vs [Y]%`; main table last row; RQ3
answer paragraph can be drafted structurally with numbers left blank.

### 5.3 More one-way vs round-trip controlled pairs — MUST DO

Currently n=1 (Ep0/705). Since D1/D2/D3 are now promoted to the Introduction, the whole
reduction rests on this single pair.

**Protocol:** pick 2–3 more reverse-paired episodes, run each (a) as an independent one-way
task and (b) as the Return phase with initial pose error zeroed. Draw episodes from outside
the locked cohort.

**Placeholder:** expand Table II to multiple rows; for now soften VI-A's wording to "based on
a single controlled pair; additional pairs are reported in Table [X]".

### 5.4 Oracle Hint-Action + Stop Gate on high-success-100 — OPTIONAL

**Expected:** 65–71%, based on the 9 reached-but-not-stopped episodes in §3.5.

If skipped, redirect the VI-B forward reference to the non-Oracle full-architecture results
(which include the stop gate).

### 5.5 Non-Oracle module decomposition — OPTIONAL

Mirrors the Oracle chain (hint / +arbiter / +stop gate) under online estimation. Completes the
2×2 diagnostic matrix:

| | Oracle info | Online ICP info |
|---|---|---|
| Hint only | 37.2% ✅ | `[5.5]` |
| Hint + Arbiter | 60.5% ✅ | `[5.5]` |
| Hint + Arbiter + StopGate | `[5.4]` | `[5.2]` |

Do not create explicit placeholders in the text for optional items; mention them in Future
Work instead so skipping leaves no hole.

### 5.6 Reliability-decomposition ablation — recommended if time allows

Replace `r^pose/r^bearing/r^distance` with a single confidence value gating all three
interfaces. **This is the only direct evidence for the "Reliability-Aware" in the title**, and
RQ3's second half ("to what extent does the decomposition limit propagation of erroneous
evidence") cannot otherwise be answered.

### 5.7 Logging fields required for all future runs

Per time step: predicted anchor index; ground-truth nearest anchor index; ICP-estimated
bearing/distance; **ground-truth bearing/distance (also under non-Oracle — this is the only
way to compute error distributions)**; `r^pose/r^bearing/r^distance` raw values and verdicts;
arbiter trigger flag with `a^VLM_t` and `a^β_t`; stop-gate verdict and distances at trigger;
ground-truth pose; distance to start (enables minimum-distance-during-Return).

### 5.8 Before launching: freeze

Freeze and record in Appendix A-B *before* any locked-cohort run: episode list, `δ_a`,
`R_lidar`, downsampling resolution, ICP parameters, all reliability thresholds, arbiter
angular threshold and occupancy radius, `r_in`, step budget. If parameters change mid-way, the
"method frozen before evaluation" claim in Section V collapses.

Consider reusing a single set of Outbound executions across all configurations (route memory
only affects Return). This halves compute *and* removes the run-to-run Outbound stochasticity
already observed (Ep 1040/678), making configurations strictly paired. Worth stating in
Section V as a methodological strength.

---

## 6. Working preferences

- Chinese for discussion and technical back-and-forth; English for deliverables (LaTeX).
- IEEEtran two-column format; British spelling.
- Content strictly grounded in provided materials; no unverified citations under any
  circumstances.
- Direct acknowledgement and correction of errors; concise deliverables.
- Preferred workflow: Chinese draft first with a change rationale, then English LaTeX after
  confirmation.

---

## 7. Suggested next actions

1. Rewrite VI-B Observation 2 + the 4.3% correction paragraph + the new arrival/termination
   subsection (all data in hand; fixes a number already published in the Introduction).
2. Rewrite Introduction contribution 3; add the new D2/D3 separation contribution; delete the
   empty item 6.
3. Write the Section V cohort definitions (tightest methodological gap).
4. Rewrite VI-B Observation 1 around 37.2%.
5. Create the Section VII skeleton and main table with placeholder rows.

---

## 8. Repository

`github.com/BruceWayne1245/NaVILA-video-upload-demo` (public)

- `final_data/` — authoritative results (three TSVs + READMEs + arbiter decisions TSV)
- `artifacts/stop_gate_r3_oracle_hard_20260630_route_maps/` — the two Fig. 2 grids
- `artifacts/hard11_no_hint_vs_stop_gate_maps_20260630/` — per-episode no-hint vs hint
  comparisons (11 episodes); useful for the "hints are actually read" defence
- `investigations/数据补全/` — selection methodology for high-success-100
