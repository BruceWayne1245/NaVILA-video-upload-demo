# Figure specification — round-trip VLN thesis

Target document: IEEEtran two-column, A4. Every figure below is for that layout.

## Global requirements (apply to all figures)

**Output**
- Vector PDF. Filenames given per figure. Place in `figures/`.
- No figure title drawn inside the image. The LaTeX caption does that job; an
  in-image title duplicates it and wastes vertical space.

**Sizing** — this is the constraint that most often gets violated.
- Single-column figure: **3.4 in wide**. Full-width (`figure*`): **7.1 in wide**.
- Set the figure size in inches at creation (`figsize=(3.4, h)`) and export at
  that size. Do **not** draw large and downscale in LaTeX — text becomes
  unreadable.
- Font sizes in points, at final size: tick labels 6, axis labels 7, in-panel
  annotations 6.5. Nothing below 6 pt.
- `bbox_inches='tight', pad_inches=0.02`.

**Style**
- Must survive greyscale printing: never rely on colour alone to separate
  series. Pair colour with hatch, marker, or line style.
- No background grid unless it carries information; if used, light grey, below
  the data.
- Despine top and right.
- Colours: use a colourblind-safe pair/set (e.g. Okabe–Ito). Keep the
  baseline/oracle_hint colours consistent between Fig. 2 and any other figure
  that shows those two conditions.

**Data provenance**
- All quantitative figures draw from `final_data2/*.tsv` in the repo
  `BruceWayne1245/NaVILA-video-upload-demo`.
- Two corrections must be applied before computing anything:
  1. In `pure_oracle_hint_action_..._matched50_full_results.tsv`, `episode_id
     602` has a blank result row (corrupted measurement JSON). Set
     `outbound_success = return_success = round_trip_success = True`.
  2. Arrival is `y_arr = (distance_to_start <= 3.0) OR return_success`. The
     plain distance test alone misclassifies one episode (`episode_id 500`,
     logged at 3.008 m but declared successful by the simulator).
- Rows with `exit_code != 0` / blank results are excluded; denominators are the
  per-condition counts given below, not 50.
- **Every figure must be checked against the expected values listed with it.**
  If a computed number disagrees, stop and report rather than plotting.

---

## Figure 2 (revision) — return trajectories, baseline vs Oracle Hint

File: `figures/hint_trajectory_effect.pdf`. Full width (`figure*`), 7.1 in.
A 1×4 panel row.

### Change the four episodes

The current panels use ep 798 / 1154 / 577 / 9. **Episode 9 must be replaced.**
Its return-leg divergence (0.280 m) is *smaller* than its own outbound-leg
divergence (0.303 m), i.e. within run-to-run noise, so it cannot support the
claim the caption makes about it.

Use these four instead. All have **outbound divergence exactly 0.000 m** (the
two runs' outbound trajectories coincide to numerical precision), which makes
the comparison strictly controlled — the Return phase starts from an identical
state and the hint is the only difference.

| Panel | Outcome cell | Episode | Outbound div | Return div (mean / max) |
|---|---|---|---|---|
| 1 | baseline ✓, hint ✓ | **500** | 0.000 | 0.26 / 0.43 |
| 2 | baseline ✗, hint ✓ | **1153** | 0.000 | 3.99 / 6.15 |
| 3 | baseline ✓, hint ✗ | **1154** | 0.000 | 3.36 / 7.28 |
| 4 | baseline ✗, hint ✗ | **1006** | 0.000 | **6.54 / 15.65** |

Keep this left-to-right order. Panel 4 is the most important one in the figure
(both runs fail, yet the paths differ by 6.5 m on average) — it is the evidence
that the hint changes behaviour independently of whether it helps. Do not
reorder it away from the end; the caption refers to "the rightmost panel".

Verify the divergence values against
`trajectory_divergence_{outbound,return}_baseline_vs_oracle_hint_20260818.csv`
before plotting. If any of the four does not show outbound `mean_div_m == 0.0`,
stop and report.

### Fix legibility

The current version is unreadable at print size. Required changes:

- **Remove** the two-line suptitle drawn inside the image.
- **Remove** the in-image legend (the caption states orange = baseline,
  blue = Oracle Hint, star = start/return target).
- **Remove all axis ticks, tick labels, and spines.** Add one horizontal scale
  bar (e.g. 2 m) in the first panel only, with a small text label.
- **Equalise the panels**: same axes box size, aligned on a common top and
  bottom, equal aspect ratio (`ax.set_aspect('equal')`). Currently the four
  panels have different heights and panel 4 floats upward.
- Per-panel title: the outcome cell only, e.g. `both succeed`,
  `hint only`, `baseline only`, `both fail`, at 7 pt bold, with the episode id
  on a second line at 6 pt.
- Crop each map to the union of the two trajectories plus the start marker,
  with a small margin — do not plot the whole floor plan if the paths occupy a
  corner of it.
- Line width ~1.0; draw the start/target star last so it is never occluded.

Total figure height should land near 1.9–2.2 in.

---

## Figure 3 (new) — arrival rate vs success rate

File: `figures/arrival_vs_success.pdf`. **Single column, 3.4 in wide**, about
2.0 in tall. Referenced from Section VI-B, Observation 3.

This carries the paper's headline finding: arrival and success fail
independently, and the gap between them is the termination deficit.

**Content.** Five condition groups along x, two bars each: arrival rate
(AR) and success rate (SR), both conditional on outbound success. Annotate the
gap between the two bars of each group with the termination deficit in points.

| Condition (x label) | AR | SR | Δterm |
|---|---|---|---|
| Language-only | 24.0 | 22.0 | 2.0 |
| + Oracle hint | 39.5 | 37.2 | 2.3 |
| + Hint-Action | 82.2 | 71.1 | 11.1 |
| + Terminal verif. | 90.7 | 86.0 | 4.7 |
| Online | 59.2 | 55.1 | 4.1 |

- y axis 0–100, labelled `Return success / arrival (%)`.
- The first four are the Oracle ladder; the fifth is the online system. Set it
  apart — a gap in x, a vertical rule, or a lighter face — and label the two
  blocks. Do not let a reader read the fifth bar as the next rung of the ladder.
- The AR bar and SR bar of a group must be visually distinguishable in
  greyscale: use a hatch on one, or an open/filled contrast.
- x tick labels will not fit horizontally at 3.4 in — rotate ~30° or use two
  lines. Do not shrink below 6 pt to make them fit.
- Draw the Δterm annotation only where it is legible; if 2.0 and 2.3 are too
  small to annotate cleanly, annotate the three larger ones and leave the rest
  to the table.

**Do not** add error bars. These are exact proportions on small denominators,
and a naive binomial interval would invite comparisons the paired tests in
Table IV are the correct instrument for.

---

## Figure 4 (new) — final distance to start on failed return episodes

File: `figures/failure_distance_distribution.pdf`. **Single column, 3.4 in
wide**, about 2.0 in tall. Referenced from Section VII-B.

Supports two arguments: that residual failures under exact information are
gross trajectory failures rather than borderline arrival misjudgements, and
that the online system's failure morphology resembles Oracle Hint rather than
the full Oracle configuration.

**Content.** For each condition, the distribution of `distance_to_start` over
episodes with `outbound_success == True` and `return_success != True`.

- Horizontal layout (conditions on y) reads better at this width than vertical.
- Use a box plot **with all individual points overlaid** (strip/swarm, small
  markers, slight jitter, alpha ~0.6). The n values are small (6–39) and the
  individual points are the informative part; a box alone over n=6 would be
  misleading.
- Draw a vertical reference line at **3.0 m** (the success radius) and label
  it. Everything to the right of it is an episode that ended outside the
  success region.
- Annotate each row with its `n`.
- x axis in metres, starting at 0. The maximum is 21.03 m; if the long tail
  compresses the bulk, use a log x axis or a broken axis rather than clipping
  points — do not silently drop outliers.

Expected values (verify before plotting):

| Condition | n | median | Q1 | Q3 | min | max |
|---|---|---|---|---|---|---|
| Language-only | 39 | 5.79 | 3.93 | 8.50 | 0.00 | 21.03 |
| Oracle hint | 27 | 5.37 | 3.85 | 6.29 | 1.98 | 13.04 |
| + Hint-Action | 13 | 3.79 | 0.84 | 4.10 | 0.10 | 8.86 |
| + Terminal verif. | 6 | 4.96 | 0.84 | 6.61 | 0.00 | 8.82 |
| Online | 22 | 5.59 | 3.57 | 6.89 | 0.00 | 17.91 |

Note for interpretation (not to be drawn): the `+ Hint-Action` and
`+ Terminal verif.` rows have a cluster of failures *inside* 3.0 m — those are
the termination-deficit episodes, the ones that arrived but did not stop. That
cluster is the visual counterpart of Figure 3's bar gap, so keeping the 3.0 m
line prominent matters.

---

## Figure 5 (deferred — do not build yet)

Reliability-component authorisation over a return episode, for Section VII.
Blocked on parsing the per-step logs of the online run
(`batch_logs/policy_v2_active50_replay_on_highsuccess100ep_20260816/ep*_eval.log`).
Specification will follow once those are available.

---

## Page budget warning

The document is at or near its page limit. Figures 3 and 4 together add roughly
0.55 page. Keep both within the stated single-column footprint; a figure that
overruns its height forces a body-text cut elsewhere.
