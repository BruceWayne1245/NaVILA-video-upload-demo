# 2026-07-09 — Two open failure modes in the `sequential_pair` route-memory relocalizer: promotion-timing lag/overshoot, and undetectable rotational ICP error

**Purpose of this document**: this is written to be handed to an external research assistant (a web-search-capable LLM) to survey prior art and candidate solutions for the two problems below. It is meant to be self-contained — read together with the accompanying `code/` directory (the three files that implement everything described here), you should not need any other context from this project to understand the problem or start searching for relevant literature/techniques.

---

## 1. Project background (read this first if you have no other context)

This is a **Vision-and-Language Navigation, Continuous Environments (VLN-CE)** system built on **NaVILA** (an RSS 2025 vision-language-action navigation model) deployed in **NVIDIA Isaac Sim**, controlling a simulated **Unitree Go2 quadruped** robot with a learned locomotion policy. The task extends normal VLN-CE ("follow this instruction to reach a goal") into a **round-trip** task: the robot must go **Outbound** (start → goal, following a language instruction) then **Return** (goal → start), without any new instruction — it must recall the route it just took.

To make the return trip possible without simply replaying oracle GPS, the system builds a **route memory** during the outbound leg: it drops a sequence of **anchors** at fixed spacing (~1 m) along the path, each anchor storing a local 2D LiDAR point-cloud "local map" (an occupancy-style scan of the robot's surroundings at that point, expressed in the robot's own body frame) plus its cumulative distance-from-start along the route. During the return leg, the robot needs to know **which anchor it is near** and **its precise offset (distance, bearing) to that anchor** at each step, so this can be turned into a navigation hint fed to the VLM (e.g. "the previous location is 2.3 m away, at a bearing of -15°").

**Anchor identity tracking — `sequential_pair` design.** Since the robot always starts the return leg standing exactly on the last outbound anchor, anchor identity does not need to be searched for from scratch: the design only ever tracks a `(current, next)` pair of anchor candidates (`next` is always the anchor immediately closer to start, i.e. `next_index = current_index - 1`, since anchor indices increase monotonically with distance-from-start along the route). Every relocalization attempt (every 5 simulation steps in the batches below) runs ICP matching between the robot's live LiDAR scan and **both** anchors' stored local maps, producing a raw pose estimate (dx, dy, dtheta → converted to distance/bearing) for each. When there is enough accumulating evidence that `next` is a better fit than `current`, the pipeline **promotes**: `next` becomes the new `current`, and a new `next = current_index - 1` is set. Because the candidate set is always exactly two anchors, the design mechanically guarantees "advance at most one anchor per promotion, never skip, never reverse" — but *when* to promote is a separate, tunable decision (see §2 below), and that timing is one of the two problems in this document.

**ICP matching stage.** Each anchor-vs-current-scan match is done via 2D point-to-point ICP over point clouds voxel-downsampled to ~512 points (0.10 m voxel), seeded at 24 yaw hypotheses (every 15° from -180° to 180°) to avoid local-minimum convergence, keeping the best-scoring basin. Each match produces rich diagnostics (used throughout this document):
- `match_class`: `clean_full_pose` (converged cleanly), `ambiguous_high_confidence` (multiple yaw seeds converged to similarly-good, meaningfully different poses — i.e. ICP itself detected an orientation ambiguity), or `partial_pose_degenerate` (weak/rank-deficient constraint geometry).
- `icp_near_tie_basin_count`: how many of the 24 yaw-seeded basins scored within a small margin of the winning basin (a direct "is there a competitive second solution" signal).
- `overlap_ratio`, `inlier_count`, `median_residual_m`: standard ICP fit-quality metrics.
- `corridor_degeneracy_ratio`: a pre-ICP geometric-degeneracy score (PCA eigenvalue ratio of the anchor's own point cloud — high value ≈ corridor/hallway-like geometry with a weak constraint direction along the corridor axis).
- The pipeline runs in `quality_policy=diagnostic` mode: **none of these diagnostics currently reject or gate a reading — they are logged for offline analysis only.** Nothing is currently rejected based on them (a stricter `quality_policy=strict` mode exists but is not what generated the data below).

**Promotion logic — `bounded_evidence` + `alias_aware`.** To decide when `next` should be promoted to `current`, the pipeline does not act on a single reading; it requires `next`'s estimate to "look better" in **at least 3 of the last 5 attempts** (a small, bounded, reset-on-promotion voting window — deliberately not an unbounded accumulator, to avoid a previously-documented failure mode where an unbounded odometry-drift accumulator caused permanent stalls). A separate `alias_aware` mechanism additionally requires a stricter vote count for anchors that are known to be geometrically self-similar to nearby anchors (precomputed once via a same-route anchor-vs-anchor ICP cross-check), with a stall-relief fallback after 200 attempts with no promotion.

**Closure-check / fusion.** Once current and next estimates both exist for an attempt, a "closure check" cross-validates them (they should agree, since the known geometric offset between adjacent anchors is available) and — in the currently-live `belief` mode — quality-weighted-blends them, with a `trust_aware_guard` addition that falls back to pure substitution (trust the more-reliable side) instead of blending when disagreement is large and the two sides' `match_class`/`near_tie` diagnostics can discriminate which side is trustworthy. This governs what final `bearing_to_anchor_deg`/`distance_to_anchor_m` is actually delivered as the navigation hint.

**Data used in this document**: a live 11-episode ("hard-11", a fixed hard-episode subset of the Matterport3D scenes used throughout this project) Isaac Sim batch, `hard11_live_trust_aware_guard_20260707_accumulated` (8 of 11 episodes produced usable route-memory data; 3 failed at the outbound stage for unrelated reasons — VLM-server timeouts / a pre-existing "robot physically stops moving" bug — and are excluded). This batch has the `trust_aware_guard` fix already applied and represents the current best-validated configuration (no multi-frame anchor accumulation — that was a separate, later experiment that regressed results and is out of scope for this document). All ground truth below comes from the simulator's privileged pose/arc-length data, used only for offline grading — never fed back into the pipeline itself.

Relevant code (full files included in `code/` alongside this document):
- `code/route_memory_agent.py` — `RouteMemoryAgent` class: anchor sequence, `sequential_target_anchor_pair()`, promotion logic (`_select_sequential_pair_relocalization`, `bounded_evidence`/`alias_aware`), closure-check/fusion (`_sequential_pair_closure_belief_fusion`, `_sequential_pair_closure_belief_trust_aware_reconstruct`).
- `code/relocalization.py` — `sequential_pair_anchor_relocalization()`: the actual ICP matching + all diagnostics described above (`match_class`, `icp_near_tie_basin_count`, `corridor_degeneracy_ratio`, etc.).
- `code/round_trip_eval.py` — episode driver, CLI flags, measurement/trajectory logging.

---

## 2. Problem 1: promotion-timing asymmetry — "current" overshoots 21.3% of the time, "next" reads as "behind" 25.1% of the time

### 2.1 Definitions used for grading

At each relocalization attempt, ground truth "true current anchor index" = the anchor with the largest `distance_from_start_m` that is still ≤ the robot's true arc-length position along the route (privileged simulator data, offline-only). "True next" = true-current-index − 1.

- **Current-selection diff** = (reported current anchor index) − (true current anchor index). 0 = exact; +1/+2+ = **lag** (hasn't advanced far enough yet); negative = **overshoot** (reports being further along than it truly is).
- **Next-selection diff** = (true next index) − (reported next anchor index). 0 = exact; positive = next reads as **ahead** of where it should be (+1/+2/+3+); negative = collapsed into a single **"behind"** bucket (next hasn't advanced as far as expected — includes the common case where next is stuck equal to current).

### 2.2 Pooled results (n=2788 attempts, 8 episodes)

**Current:**

| exact | lag-1 | lag-2+ | overshoot |
|---|---|---|---|
| 55.9% | 13.8% | 9.0% | 21.3% |

**Next** (n=2689, excludes attempts where true-current was already anchor 0, i.e. no meaningful "next"):

| exact | +1 | +2 | +3+ | behind |
|---|---|---|---|---|
| 56.4% | 17.7% | 0.7% | 0.0% | 25.1% |

Never advances 3+ anchors ahead of expectation, confirming the structural "advance ≤1 anchor per promotion" guarantee holds in both directions (overshoot is also capped, see below).

### 2.3 Overshoot: single-step, high-confidence, and NOT a data-quality problem

Of the 593 overshoot attempts: **95.6% are magnitude-1** (567), 4.4% magnitude-2 (26), **zero** magnitude-3+.

**Ruled out: this is not primarily a ground-truth-sampling artifact.** Attempts are graded against ground truth sampled only once per 5 simulation steps (the relocalization interval); one could hypothesize that a magnitude-1 "overshoot" merely reflects genuine promotions that happened correctly, just slightly before the next 5-step sample confirmed the robot had "officially" crossed the anchor boundary. We tested this directly: at the threshold that actually matches the real single-interval travel distance (≈3–7% of one anchor-spacing, derived from the project's own measured robot speed — see §2.5 for the calculation), overshoot rows and exact-match rows look nearly identical:

| threshold (% of one anchor-spacing) | mag-1-overshoot rows within threshold of the boundary | exact-match rows within threshold |
|---|---|---|
| 3% | 7.2% | 6.7% |
| 5% | 10.4% | 8.5% |
| 7% | 13.2% | 9.9% |
| 10% | 18.9% | 12.7% |
| 15% | 29.1% | 16.8% |

The gap only opens up at thresholds (15%+) far larger than one real sampling interval, so attributing overshoot to grading-resolution artifacts is not defensible — the effect is real, not a measurement artifact.

**The promoted anchor's own ICP match is, if anything, *more* confidently clean than a correctly-timed promotion:**

| | `match_class` clean / ambiguous / degenerate | mean `overlap_ratio` | mean `corridor_degeneracy_ratio` |
|---|---|---|---|
| magnitude-1 overshoot (n=567) | 91.7% / 3.9% / 4.4% | **0.957** | 0.693 |
| exact-match baseline (n=1558) | 87.9% / 3.3% / 8.8% | 0.900 | 0.757 |

**Interpretation**: overshoot is not bad/ambiguous ICP data slipping through — the anchor being promoted to genuinely is a very good match. The mechanism is the `bounded_evidence` promotion **vote window** (3-of-5) committing to a promotion once evidence has trended convincingly *before* the ground-truth arc-length threshold says the robot has technically arrived — i.e. **a confirmation-lead/early-commit behavior of the voting design itself**, not a data-quality failure. No `alias_score`/geometric-self-similarity check could be run against this hypothesis: this batch's serialized measurement data only stores an anchor point cloud's `{shape, min, max}` summary, not the raw points, so the identity-alias precompute (computed in-memory during the live episode) could not be reconstructed offline.

### 2.4 Overshoot and "next-behind" are two distinct populations pointing in opposite directions — not one bug

Direct co-occurrence of current-**overshoot** and next-**behind** at the same (episode, attempt): only 7.1%/6.2% overlap — genuinely separate.

**But current-LAG (current hasn't advanced, diff≥1) and next-behind co-occur 92.9%/87.6% of the time — these are mechanically the same phenomenon, not two independent failures.** Since `next_index := current_index − 1` by construction, whenever `current` fails to promote in time, `next`'s reading is automatically read as "behind" too — it is a **downstream symptom of current-lag**, not a separately-caused error mode.

So the real picture is two genuinely distinct directions of failure:
- **Overshoot** (current promotes too early — §2.3, a promotion-vote-timing behavior)
- **Lag** (current promotes too late, dragging next's reading down with it — investigated next)

**Per-episode concentration** (of 593 overshoot / 676 total behind, pooled):

| episode | overshoot n | % of total overshoot | behind n | % of total behind |
|---|---|---|---|---|
| 4 | 119 | 20.1% | 21 | 3.1% |
| 5 | 0 | 0.0% | 286 | **42.3%** |
| 187 | 22 | 3.7% | 90 | 13.3% |
| 368 | 99 | 16.7% | 27 | 4.0% |
| 678 | 136 | **22.9%** | 57 | 8.4% |
| 680 | 113 | 19.1% | 80 | 11.8% |
| 994 | 13 | 2.2% | 75 | 11.1% |
| 1040 | 91 | 15.3% | 40 | 5.9% |

Episode 5 alone drives 42.3% of all lag/"behind" cases and has **zero** overshoot — a previously-documented case (route is uniformly self-similar on every anchor, `alias_aware`'s stricter vote requirement never clears within the episode). Overshoot, by contrast, is spread fairly evenly across the other 7 episodes (15–23% each) — a genuinely different population from episode 5's stall.

### 2.5 Lag/"behind" excluding episode 5's known stall (n=390): mostly NOT explained by poor candidate data

| | n | % |
|---|---|---|
| next-candidate diagnostics genuinely **poor** (`match_class` flagged / `near_tie_basin_count`>0 / `overlap_ratio`<0.5 / `corridor_degeneracy_ratio`>0.90) | 129 | 33.1% |
| next-candidate diagnostics look **fine** by every logged signal, yet still not promoted | 261 | **66.9%** |

Sanity-checked the "fine" bucket is not a near-threshold artifact: median `overlap_ratio` 0.914 (well clear of 0.5), median `corridor_degeneracy_ratio` 0.735 (well clear of 0.90) — genuinely good readings that simply did not accumulate enough promotion votes in time.

Strong per-episode heterogeneity within this 66.9%:

| episode | % of its non-alias-stall "behind" cases that are "fine-but-stuck" |
|---|---|
| 368 | 96.3% |
| 678 | 94.7% |
| 994 | 36.0% (i.e. 64.0% genuinely poor) |
| 4 | 28.6% (i.e. 71.4% genuinely poor) |

**Interpretation**: in some episodes (368, 678) the promotion vote-window/threshold design itself is the bottleneck — good evidence exists but the 3-of-5 window (or `alias_aware`'s stricter variant) simply hasn't accumulated enough qualifying votes. In others (994, 4) the underlying candidate data genuinely is poor, and hesitance is appropriate. **A fixed global vote-window parameter does not fit both regimes.**

**Speed/spacing calculation referenced in §2.3**: from this project's own recorded data (episode 4), the robot travels at ~0.35 m/s during return, and the relocalization interval is 5 simulation steps at the simulator's control rate — giving a per-interval travel distance of roughly 0.03–0.07 m against a ~1.0 m anchor spacing, i.e. 3–7% of one anchor-spacing per sampled interval.

### 2.6 Framing this problem for literature search

Abstracted away from this specific robotics stack, this is: **a sequential/online change-point or state-transition decision problem** — given a stream of noisy, per-step evidence comparing two competing hypotheses (stay at `current` vs. switch to `next`), decide *when* to commit to a state transition, trading off commit-latency (lag) against false-early-commits (overshoot), under a hard constraint that the decision mechanism must never revisit/reconsider more than one step back or forward (a strict Markov-chain-like "advance by exactly one" topology). The current mechanism is a fixed-size sliding-vote-window (3-of-last-5), which is a simple heuristic version of this general class of problem. Candidate related literatures to search:
- Sequential hypothesis testing / **Sequential Probability Ratio Test (SPRT)** and its optimality properties for exactly this kind of two-hypothesis, evidence-accumulation-with-early-stopping problem.
- **CUSUM / change-point detection** literature, particularly online, low-latency variants with bounded false-alarm rate.
- **Topological / landmark-based localization** literature (place-recognition-driven localization, e.g. FAB-MAP, sequence-based place recognition like SeqSLAM) — specifically any treatment of *when* to accept a place-recognition match and advance the robot's belief to a new node, and any adaptive/per-node confidence thresholds (which would map to this project's finding that a fixed vote-window doesn't fit all episodes/anchors uniformly).
- **Hysteresis / debounce design** in state-machine and control-systems literature — the general engineering pattern this vote-window already resembles, and any principled tuning methods (vs. this project's fixed 3-of-5 constant) that adapt window size to evidence quality or expected dwell time.

---

## 3. Problem 2: ICP bearing error >10° is 69% unexplained by any currently-logged diagnostic

### 3.1 Setup

For every **accepted** relocalization event (the actual `bearing_to_anchor_deg`/`distance_to_anchor_m` delivered as the navigation hint, post-fusion), bearing error is computed against ground truth (privileged simulator pose, offline-only). Pooled over 2788 accepted events (8 episodes):

| | distance (m) | bearing (deg) |
|---|---|---|
| median | 0.075 | 5.64 |
| mean | 0.260 | 19.88 |
| p90 | 0.503 | 57.17 |

We focus on the 1087 readings (39.0% of all readings) with bearing error >10°, and ask: **how much of this is explained by the two diagnostic signals the pipeline already computes** (§1's `icp_near_tie_basin_count` and `match_class`), and how much is genuinely unexplained?

### 3.2 A third candidate signal was tested and found NOT to work — reported honestly as a negative result

Before settling on the final categories, `corridor_degeneracy_ratio` (a pre-existing diagnostic, originally designed to flag corridor/hallway geometric degeneracy) was tested as a possible third explanatory signal. Comparing its distribution between the clean population (bearing error ≤5°, n=1329) and the "otherwise unexplained" subset of the >10° bucket (n=750):

| | p50 | p75 | p90 | p95 | max |
|---|---|---|---|---|---|
| clean population (err≤5°) | 0.752 | 0.841 | 0.936 | 0.941 | 0.953 |
| unexplained >10° subset | 0.802 | 0.869 | 0.922 | 0.942 | 0.953 |

At the clean population's own 90th-percentile value (0.936) as a cutoff: 5.9% of the clean population sits above it (as expected by construction) vs. only 6.1% of the unexplained subset — essentially identical rates, no discrimination. **`corridor_degeneracy_ratio` does not separate wrong-but-undiagnosed readings from clean ones once the two existing diagnostics are already accounted for — this is a genuine negative finding, not folded into the taxonomy below.** (This is consistent with an earlier, separately-documented finding in this project that this same signal's fixed skip-threshold never fires in practice at its configured value — but here we tested a data-driven percentile-based threshold from scratch, specifically to rule out "wrong threshold" as the reason, and it still doesn't separate the populations.)

A fourth candidate (`alias_score`, a precomputed anchor-vs-anchor geometric-self-similarity score) could not be tested — like §2.3, this batch's serialized data doesn't retain the raw point clouds needed to recompute it offline.

### 3.3 Final categorization of the >10° bucket (n=1087)

| category | n | % |
|---|---|---|
| A: `icp_near_tie_basin_count`>0 only | 69 | 6.3% |
| B: `match_class` flagged (not `clean_full_pose`) only | 83 | 7.6% |
| C: both A and B | 185 | 17.0% |
| **F: neither signal present — genuinely unexplained** | **750** | **69.0%** |

**69.0% of bearing errors exceeding 10° show absolutely no warning sign in any diagnostic this pipeline currently computes** — not a competing near-tied ICP solution, not a self-reported ambiguous/degenerate match class, and not elevated corridor-degeneracy. Only 31.0% (A+B+C) carry any existing red flag.

### 3.4 Concentration: broadly spread, not a handful of pathological anchors

The 750 unexplained readings touch **76 distinct (episode, anchor) groups** out of ~99 total groups in the batch. The worst 10 groups account for only 35.1% of the unexplained total (top-5 = 19.6%):

| episode / anchor | n | % of unexplained | cumulative |
|---|---|---|---|
| ep1040 / anchor4 | 36 | 4.8% | 4.8% |
| ep187 / anchor8 | 31 | 4.1% | 8.9% |
| ep187 / anchor14 | 28 | 3.7% | 12.7% |
| ep680 / anchor5 | 26 | 3.5% | 16.1% |
| ep1040 / anchor7 | 26 | 3.5% | 19.6% |
| ep187 / anchor13 | 25 | 3.3% | 22.9% |
| ep187 / anchor5 | 23 | 3.1% | 26.0% |
| ep678 / anchor14 | 23 | 3.1% | 29.1% |
| ep680 / anchor14 | 23 | 3.1% | 32.1% |
| ep187 / anchor7 | 22 | 2.9% | 35.1% |

This is a **broadly-distributed** problem across most anchors in the dataset, not a small number of pathologically bad anchors hiding the average — a fix needs to generalize across ordinary-looking anchors, not just target known-bad ones.

### 3.5 Concrete worst-case example: `ep1040`, anchor 4 (the single largest unexplained group, 36 readings)

| attempt | bearing err | dist err | `match_class` | `overlap_ratio` | `corridor_degeneracy_ratio` | `inlier_count` | # near-tied basins | (dx, dy, dθ) |
|---|---|---|---|---|---|---|---|---|
| 249 | 64.8° | 0.421 m | `clean_full_pose` | 0.750 | 0.818 | 384 | 14* | (0.364, 0.232, **123.1°**) |
| 248 | 53.1° | 0.495 m | `clean_full_pose` | 0.755 | 0.818 | 354 | 13* | (0.304, 0.761, **140.6°**) |
| 225 | 49.5° | 0.230 m | `clean_full_pose` | 0.849 | 0.818 | 361 | 16* | (0.388, 0.966, **167.6°**) |
| 237 | 46.9° | 0.368 m | `clean_full_pose` | 0.799 | 0.818 | 409 | 17* | (0.400, 0.337, **127.3°**) |
| 233 | 46.0° | 0.127 m | `clean_full_pose` | 0.906 | 0.818 | 464 | 15* | (0.396, 0.124, **134.8°**) |

*(the "# near-tied basins" column here is the raw multi-basin count found during the 24-seed yaw sweep — all of these register `icp_near_tie_basin_count=0` in the pipeline's own near-tie *margin* test, i.e. one basin clearly outscored all others; the raw basin count is shown only for context, it does not itself indicate ambiguity by this pipeline's own definition.)*

**Every one of these five readings reports the cleanest possible diagnostic signature** — `clean_full_pose`, no near-tie, healthy overlap (0.75–0.91) and inlier counts (350–460), moderate (not extreme) corridor-degeneracy — **yet the estimated translation (dx, dy) is small and reasonable while the estimated rotation (dθ) is confidently wrong by 46–65°, always in the same rough direction (~120–170°) for this one anchor across many attempts.** Position converges correctly; orientation does not, with no diagnostic warning. This is the dominant signature behind the entire 69% unexplained residual, not an isolated anecdote — the same pattern (small dx/dy, large/consistent-per-anchor dθ error, all clean diagnostics) recurs across the other worst groups in §3.4.

### 3.6 Framing this problem for literature search

Abstracted away from this stack: **2D point-cloud registration (ICP) that converges to a translation-correct but rotation-incorrect pose, with no signal in the standard fit-quality metrics (overlap, inlier count, residual) or a multi-seed near-tie/basin check.** This is distinct from the textbook "ICP local minimum" case (which a multi-seed restart, already in use here, normally catches) and distinct from the textbook "degenerate/corridor" case (which a PCA-eigenvalue corridor score, already computed and tested here, does not correlate with). The failure looks like a genuine, single, confident local optimum that is nonetheless wrong specifically in orientation. Point clouds here are 2D, sparse (~250–2800 points per scan after voxel downsampling, an indoor-building floor-plan-like local map), obtained from simulated LiDAR. Candidate related literature to search:
- **Rotational/orientation ambiguity and symmetry detection specifically in point-cloud registration** — literature on detecting when a local scene has (partial or global) rotational or reflective symmetry that ICP's cost function cannot distinguish from the true pose, beyond simple corridor/degeneracy PCA scores (which this project already tried and found insufficient) — e.g. any work using higher-order local shape descriptors, or explicit symmetry-detection as a pre/post-ICP check.
- **SO(2)/SO(3) uncertainty representations for pose estimation** (e.g. Bingham distributions, von Mises on the circle) that might expose ambiguity in the rotational component even when a single point estimate looks confident — as opposed to this pipeline's current multi-seed-basin approach, which apparently isn't sensitive enough to this failure mode.
- **Place recognition / loop-closure verification literature** in SLAM — specifically any technique for verifying that an accepted loop-closure's *orientation* (not just position) is correct, given that mainstream ICP fit metrics are known in that literature to sometimes pass a wrong-orientation match.
- **Learned/geometric-deep-learning point cloud registration methods** (e.g. approaches that predict rotation via a separate/explicit head, or that report calibrated per-axis uncertainty) that might be more diagnostic about rotational confidence specifically, as opposed to a single scalar fit-quality score that conflates translation and rotation confidence.
- Any technique for **combining a small number of repeated/nearby observations to disambiguate rotation** (since dx/dy is usually fine here, could a very cheap secondary cue — e.g. a second, spatially offset partial scan, or short-baseline motion during approach — resolve the rotational ambiguity without needing a much more expensive descriptor-based approach). Weigh this against the finding elsewhere in this project that simply increasing point density on the *same* viewpoint does not help (confirms the ambiguity is about vantage point, not sample count).

---

## 4. What NOT to spend search effort on (already tried / ruled out in this project)

- Raising point density or switching ICP cost function (point-to-point → point-to-line/NDT) on the *same* single viewpoint: empirically confirmed not to shrink the rotational-symmetry "bump" on already-identified symmetric anchors (denser sampling of the same vantage point sees the same symmetric structure).
- `corridor_degeneracy_ratio` as an explanatory or gating signal for either problem: tested directly in this document (§3.2) and does not discriminate.
- A purely disagreement-based cross-check between current/next (closure-check): already known (and reconfirmed) to be structurally blind to the case where both sides are simultaneously, correlately wrong in the same direction — it can only help when one side's own diagnostics independently look bad.
