# "Confidently-Wrong" LiDAR-ICP Rotational Misregistration in a Symmetric Indoor Return-Navigation Task — Problem Brief for External Research

**Purpose of this document:** this is a self-contained technical brief describing an unsolved failure mode blocking a robot navigation project, written to be handed to another research assistant (with web search) to look for prior art, alternative algorithms, or new angles. It intentionally over-explains context so it can be read without access to the rest of the repository.

**Status as of 2026-07-24.** All quantitative claims below were re-derived this session directly from raw simulation logs (trajectory ground truth + captured point clouds + online diagnostic records), not from memory of older write-ups, so the numbers here supersede earlier informal estimates in this repo's investigation history.

---

## 1. System context

A quadruped robot (Unitree Go2) is evaluated in Isaac Sim (Matterport3D-style indoor scenes) on a **round-trip** task built on top of NaVILA (RSS 2025, an RGB+language VLN model): given a language instruction, the robot navigates from a start pose to a goal (the "outbound" leg, VLM-driven, works well — this part is not in question). It must then **navigate back to the start** using only a non-oracle "route memory" — no privileged position information is available during return, exactly like a real robot would have to do.

**Route memory mechanism ("sequential_pair" backend):**
- During outbound, the controller drops an "anchor" roughly every ~1 m of travel. Each anchor stores: the robot's true world pose (position + quaternion) at that instant *(recorded only for offline ground-truth evaluation and for the diagnostic dataset — not exposed to the online controller)*, and a **raw, undownsampled LiDAR point cloud** (`local_map_points_xyz_body`) captured at that pose.
- During return, at a fixed cadence (every 5 environment steps), the controller takes the robot's current live LiDAR scan and runs **ICP** (iterative closest point, multi-start with a **24-yaw-seed sweep** to avoid local minima) against the point clouds of the two anchors currently tracked as "current" and "next" in the route sequence. This produces, per anchor per attempt: an estimated relative pose (`dx, dy, dtheta` in the anchor's frame), a match-quality label (`match_class`, e.g. `clean_full_pose`, `ambiguous_high_confidence`, `partial_pose_degenerate`), a scalar `confidence` in [0,1], and rich diagnostics (`overlap_ratio`, `inlier_count`, `mean_residual_m`, `icp_basin_count`, `icp_near_tie_basin_count`, `icp_best_to_second_score_ratio`, a `localizability` eigen-analysis of the point-cloud constraint geometry, and — critically — an `icp_top_basins` list of **the top 4 candidate rotation/translation solutions found during the 24-seed sweep**, each with its own score/overlap/residual/dx/dy/dtheta).
- This estimated relative pose feeds: (a) hint generation for the VLM ("turn left/right", "move forward"), (b) a promotion state machine that advances "current" to "next" once enough corroborating evidence accumulates, (c) a `stop_gate` that decides when the robot has arrived back at start (forced-stop / deferred / veto based on estimated distance + independent anchor-route-distance corroboration).
- The project has iteratively hardened this pipeline over ~3 weeks (closure checks, quarantine/anti-cascade budgets, alias-aware promotion, short-baseline disambiguation, a physical stuck/wedge recovery module, etc.). The current best documented ground-truth round-trip success rate is **63%** (12/19 on a 100-episode batch where 19 episodes had outbound success).

**Sensors available:** a forward-facing RGB-D camera and a **rear-facing RGB-D camera** are both physically simulated and their RGB/depth streams are already available at runtime (`descriptor["rgb"]`, `descriptor["rear_rgb"]`, etc.) but are **not currently used by the relocalization pipeline** (only the LiDAR-equivalent point cloud is used for ICP). The simulated LiDAR provides **only XYZ geometry — no intensity/reflectance channel exists anywhere in this pipeline** (confirmed by source search).

---

## 2. The core failure mode: "confidently wrong" ICP

The dominant cause of return-navigation failure (quantified in §3) is **not** noisy/low-quality ICP output that could in principle be filtered by a confidence threshold. It is the opposite: ICP converges to a **wrong rotational solution while reporting every symptom of a good match** — high `confidence` (often ≥0.9, frequently 1.00), `match_class = clean_full_pose`, high `overlap_ratio` (often >0.85), low `mean_residual_m` (~0.1-0.2 m), and a low `icp_basin_count`/`icp_near_tie_basin_count` (i.e. the optimizer itself reports having found a single, unambiguous, well-separated best solution) — yet the true bearing error to the anchor is 30° to 180°.

**Direct evidence that this is a genuine geometric-ambiguity problem, not a data-quality problem:** at the robot's *true* (ground-truth) pose at these failure points, its live point cloud overlaps the anchor's stored point cloud at 87-88% with a median point-to-point residual of only ~1 cm — i.e. the sensor data is rich and the correct alignment fits it well — and yet ICP's optimizer converges to a *different* rotation ~120-180° away that also scores as a clean, confident match. The environments where this happens are **multi-door turn-around junctions** — not simple long straight corridors (the local point cloud's PCA axis ratio at these failure points is only ~1.3-1.6, i.e. not a degenerate single-axis corridor; the symmetry is subtler, likely from a roughly-symmetric arrangement of doorways/walls around a turnaround point).

**Three observed surface presentations of the same root mechanism** (from qualitative case review of ~13 episodes in one 100-episode batch, before this session's systematic re-analysis):
1. **Whole-chain rotation lock:** the robot's *own* heading estimate gets rotated by the wrong amount, which then poisons the estimated bearing to *every* anchor in the route uniformly (since all downstream anchor comparisons implicitly assume the current-frame point cloud's orientation is correctly understood).
2. **False-stop via promotion cascade:** a confidently-wrong match to one anchor causes the "promote current→next" state machine to advance rapidly through several anchors in a row (each one *also* confidently-wrong, because the corridor's turnaround geometry fools the match against several nearby anchors near-simultaneously), which drives the estimated "distance remaining to start" down artificially fast, and — because the `stop_gate`'s two nominally-independent corroboration signals (estimated ICP distance, and the promoted anchor's own known route-distance) are **not actually independent** (both derive from the same corrupted anchor-identity belief) — triggers a forced stop while the robot is still meters from home.
3. **Reversed-bearing hint:** the "next" anchor's estimated bearing locks onto the *opposite* direction from the true one, so the hint generator tells the VLM to go the wrong way.

---

## 3. Quantitative evidence (this session, fresh full-series ground-truth analysis)

Previous write-ups in this project characterized this phenomenon qualitatively from single "crash frame" snapshots per episode. This session instead ran a systematic, reproducible analysis over **every return-phase timestep of every failed episode across two complete 100-episode batches** (batch A: `reliability_fixon_100ep_20260721`, the current-best-63% baseline controller with no learned model involved; batch B: `reliability_v11_prospective_capture_shadow_100ep_20260722`, same controller plus two additional default-off fixes, run in pure shadow so navigation behavior is identical to batch A's controller family).

**Methodology:**
- Ground truth for "did the episode actually return successfully" was computed from the robot's true recorded world trajectory (final return-phase position vs. the true start position, success radius 3.0 m), **not** from the run's self-reported `distance_to_start` field, which has a known corruption bug (a fraction of episodes have this field zeroed out, and a fraction have their final trajectory record polluted by the *next* episode's reset-teleport frame — both were detected and corrected for: the corruption is an inter-step position jump >0.5 m against a normal per-step motion of ~0.01-0.05 m, trivially separable).
- For each return-phase attempt, the *raw* (pre-safety-layer) ICP diagnostic record was used — specifically **not** the "reported" confidence value that downstream trust/quarantine mechanisms may have already capped after detecting a problem, since that would make an already-caught failure look artificially "unconfident" in hindsight. The raw per-attempt diagnostic (`covisibility_records` in the online log) preserves ICP's original, unadjusted output.
- Ground-truth bearing/distance error per attempt was computed from the robot's true recorded pose and the anchor's true recorded world pose (both available; the anchor's true pose is recorded once, right after the outbound leg, and never changes).
- A reading was labeled **"confident"** if raw `confidence ≥ 0.9` or `match_class == clean_full_pose`, and **"pose-bad"** if true bearing error > 30° or true distance error > 0.5 m (thresholds taken from this project's existing model-training convention). **"Confidently wrong" = confident AND pose-bad.**
- An episode/anchor-window was flagged as **confidently-wrong-driven** if it contained a run of ≥5 consecutive confidently-wrong readings covering ≥30% of all confident readings in that anchor's assignment window (this excludes one-off noise blips; the 30% cutoff was calibrated by checking it correctly separates a known "good ICP, bad VLM navigation" episode from the rest — see below).

**Headline numbers:**
- 62 episodes had outbound success across the two batches (19 in batch A, 43 in batch B).
- Of these, **30 failed to return** by ground truth (7 in batch A, 23 in batch B); 31 succeeded; 1 had no usable return data (excluded).
- **29 of these 30 failures (96.7%) are "confidently-wrong"-driven** by the definition above. The single exception is a case where the anchor's raw confident readings were correct 94% of the time (only 6% pose-bad) — a genuine "ICP was fine, the VLM walked the wrong way" failure, unrelated to this phenomenon.
- This is markedly higher than an earlier informal estimate of ~70% in this repo's history, which was based on eyeballing one crash-frame per episode rather than checking every step against ground truth; several episodes previously filed under other causes ("physical wedge," "step budget exceeded," "a stale-estimate bug") were found, on full-series inspection, to *also* contain a genuine sustained confidently-wrong run, sometimes coexisting with the other cause in the same episode.
- Of the 29, **5 occur while the robot's speed is <0.05 m/s** (i.e. concurrently with what looks like a physical stuck/wedge condition) — flagged as a possible confound, but the confidently-wrong signature itself is still strong and independently verifiable in those cases (fractions 0.57-1.00, not marginal).

**A previously-unreported sub-classification (this session, per the requester's hypothesis):** within an anchor's assignment window during return, is the wrongness present **from the very first confident reading** the moment the tracker locks onto that anchor, or does it **start correct and flip to confidently-wrong partway through** the same window (same anchor, same approach, no anchor-identity change)?

- **Type A — "wrong from the start" (24/29, 83%):** the first confident reading obtained for that anchor is already pose-bad, and stays pose-bad essentially the whole window. Interpretation: this specific anchor's local geometry is, from the direction/manner the robot is approaching it, intrinsically unsolvable by ICP — arriving there at all dooms the reading.
- **Type B — "flips mid-window" (5/29, 17%):** the anchor is tracked *correctly* (low error, high confidence, `clean_full_pose`) for a sustained period — one worked example ran cleanly for 100 consecutive steps, bearing error <5°, before a single step-to-step transition where bearing error jumped from ~4° to ~79° with *distance error staying small* (~0.09 m, i.e. a nearly pure rotation-only flip, not a translation error) and then stayed wrong. Interpretation: for these anchors, the correct solution **is** reachable by ICP under some conditions — something changes (robot's precise position/heading, or which local sub-region of the point cloud is currently visible) that tips the optimizer from the correct basin into the wrong one. This is mechanistically more interesting than Type A because it demonstrates the ambiguity is not always maximal/intrinsic to the anchor — there is a boundary condition worth characterizing.

Per-episode table (episode id, batch, true final distance-to-start in m, type, implicated anchor index, count of confidently-wrong readings / count of confident readings in that window, mean robot speed m/s during that window, low-speed confound flag):

```
ep     batch    dist   type  anchor  n_cw/n_conf   frac  speed   stuck?
5      A        9.47   A     10      2087/2337     0.89  0.020   Y
134    A        7.15   A     1       15/15         1.00  0.176   N
187    A        8.26   A     4       1329/1329     1.00  0.005   Y
367    A        3.08   A     6       303/311       0.97  0.270   N
491    A        6.70   A     8       2380/2380     1.00  0.032   Y
669    A        4.60   A     1       27/27         1.00  0.138   N
678    A       11.30   A     7       1046/1296     0.81  0.195   N
18     B        8.02   A     3       915/915       1.00  0.122   N
19     B        5.65   B     7       179/235       0.76  0.271   N
87     B        3.95   A     6       1848/2597     0.71  0.051   N
93     B        8.72   A     1       30/30         1.00  0.418   N
95     B        4.81   A     1       32/32         1.00  0.408   N
205    B        3.12   A     2       187/187       1.00  0.378   N
264    B        5.85   A     1       45/45         1.00  0.412   N
276    B        9.41   A     5       775/775       1.00  0.082   N
344    B        9.22   A     9       38/38         1.00  0.038   Y
427    B        3.11   A     1       27/27         1.00  0.176   N
428    B        3.11   A     1       27/27         1.00  0.176   N
490    B        6.15   A     6       10/10         1.00  0.305   N
581    B        7.43   A     1       10/10         1.00  0.397   N
688    B        6.12   B     5       1016/1850     0.55  0.205   N
698    B        7.46   A     12      840/840       1.00  0.342   N
764    B        6.74   A     2       147/147       1.00  0.382   N
784    B        4.28   A     1       30/30         1.00  0.447   N
785    B        7.52   B     8       1967/3462     0.57  0.031   Y
814    B        4.27   B     5       100/260       0.38  0.282   N
961    B        3.92   A     4       15/15         1.00  0.415   N
979    B        5.79   B     10      645/850       0.76  0.294   N
1062   B        3.50   A     1       15/15         1.00  0.412   N
(646   B        9.44   —(not confidently-wrong)—    0.06 (excluded, see text above))
```

---

## 4. What has already been tried and ruled out (please don't re-suggest these without a new angle)

- **Better scalar ICP diagnostics as a trust/reliability classifier.** A hand-built combination of 4 signals (`inlier_count`, `best_to_second_score_ratio`, a localizability condition number, `mean_residual`) reaches AUC ≈ 0.80; a full HistGradientBoosting model over ~15 scalar features reaches only AUC ≈ 0.84. The residual ~16% of readings are "confidently wrong": *identical* to good readings on every available scalar diagnostic. No amount of additional scalar feature engineering or model capacity moves this ceiling (verified: it is a property of the feature space, not the classifier).
- **Multi-view spread** (comparing the match across a small set of nearby viewpoints — a genuinely wrong anchor identity should, in principle, be inconsistent across viewpoints): tested, AUC only 0.737, and — worse — it *inverts* on exactly the symmetric-corridor cases that matter most, because the wrong lock is *consistent* across viewpoints there (the whole local region shares the same false symmetry).
- **Motion-integrated multi-frame submaps** (accumulating several consecutive LiDAR frames into a denser local submap before matching, to add more geometric constraint): tested, found to *hurt* matching quality and was excluded from the production controller.
- **Multi-anchor static consistency checks** (does the current/next pair's relative geometry agree with what's expected from their both being real anchors along the same known route): exists as a feature (`closure_check` with a `bearing`/`dtheta` reconciliation signal) but is fundamentally a comparison between two *live ICP estimates*, both of which can be simultaneously and consistently wrong under the same symmetry — it does not have access to any information orthogonal to the symmetry itself.
- **Dead-reckoning / accumulated odometry position integration**, to give the controller an independent (non-ICP) position estimate: explicitly rejected project-wide because integrated drift over a multi-hundred-step episode becomes unreliable and was found to introduce new failure modes rather than fix this one.
- **This session, newly tested and also rejected:** a naive **heading prior** derived from **outbound anchor metadata** — specifically, "the anchor's recorded heading at the moment it was dropped during outbound, plus a fixed +180° (robot is now walking the route in reverse)" as a hypothesis for what the robot's current heading should roughly be, used to re-rank ICP's own top-4 logged candidate rotations. Result: this performs *worse than random* at picking the correct candidate among the alternatives (20.2% success vs. a 27.3% random-pick baseline, n=823 attempts where a correct candidate existed among the alternatives at all). The naive "outbound heading + 180°" assumption does not hold in practice — plausibly because the VLM's return-leg navigation does not simply time-reverse the outbound path's exact heading profile.
- **No LiDAR intensity/reflectance channel exists in this simulation** to exploit as an additional geometry-independent-but-still-LiDAR signal (confirmed by source search — the sensor pipeline only ever produces XYZ points).

**A load-bearing new finding from this session, important for evaluating *any* proposed fix:** among attempts where ICP's selected ("top") candidate was wrong, only **4.8%** (823/17,229) had the *true correct answer present at all* among the 4 candidates ICP itself logs (out of its internal 24-yaw-seed multi-start sweep — only the top-4-scoring seeds' results are persisted; the other ~20 evaluated-and-discarded seeds per attempt are not logged anywhere). This means: **any fix that works by re-scoring/re-ranking the already-generated top-4 candidates (whether by a heading prior, a vision check, or anything else) has a hard ceiling around 5%,** unless paired with widening the candidate search itself (e.g. persisting/considering more of the 24 seeds, or a different global-registration search strategy that doesn't rely on a fixed small seed count). **It is currently unknown whether the true correct rotation is reachable among the full 24 seeds** (untested — would require an offline replay against the captured raw point clouds with full seed logging) or whether it is absent even there, which would point to the ICP seeding/local-minimum-avoidance strategy itself as an additional contributing bottleneck, separate from the "the geometry is truly symmetric so nothing could tell the two apart" explanation.

---

## 5. The leading hypothesis and its status

**Hypothesis:** the failure is close to information-theoretically irreducible using LiDAR point-cloud geometry alone, because in these specific junction geometries the point clouds produced by the correct pose and by one or more wrong poses are genuinely (near-)indistinguishable given the sensor's information content (pure XYZ, no reflectance) — supported by (a) the ground-truth-pose overlap/residual test in §2 showing the "wrong" solution is not a poor match by any geometric metric, and (b) several *structurally different* algorithmic approaches (§4) all independently hitting the same wall, which is more consistent with an information limit than with any single algorithm's weakness.

**Proposed fix direction (not yet quantitatively validated):** exploit the front/rear RGB cameras already physically present in the simulation (currently unused for relocalization). Qualitative review of RGB frames at several confirmed failure points shows what looks like "overwhelming" visual distinguishability between headings that are geometrically near-identical to LiDAR (different rooms visible through different doorways, a mirror, plants, different wall materials/colors) — i.e. the camera very plausibly carries the exact orthogonal information the LiDAR lacks. The concrete plan under consideration: retain more than 4 of ICP's yaw-sweep candidates (see the 4.8%-ceiling finding above — this needs to happen regardless of whether vision or something else is used to pick among them), then use RGB feature matching (the project already has a LoFTR integration used elsewhere) between the robot's current-frame RGB and the RGB stored at anchor-creation time to pick the visually-consistent candidate, triggered only at the two points where a wrong decision is irreversible (promoting current→next, and forced-stop) to bound compute cost. **This has only been checked qualitatively on a handful of frames; a quantitative offline PoC (does LoFTR-based re-selection actually recover the correct rotation, measured in degrees of bearing-error reduction, on the known failure episodes) was planned but has not yet been executed.**

---

## 6. Open questions — what this research request is for

We are looking for **prior art, alternative algorithms, or angles we have not considered**, particularly:

1. **Is there established literature on "rotational aliasing" / perceptual-aliasing-induced relocalization failure specifically in geometrically symmetric indoor environments** (e.g. symmetric corridor intersections, turn-around alcoves, repeated door/room layouts)? Related keywords that might help a search: kidnapped-robot problem, perceptual aliasing in SLAM, loop-closure ambiguity, place recognition under symmetry, rotational ICP local minima.
2. **Global / multi-hypothesis point cloud registration methods** that might handle multi-modal (multiple plausible-looking rotation basins) ambiguity better than a fixed small multi-start local ICP — e.g. branch-and-bound registration (Go-ICP), certifiably-optimal registration (TEASER++), learned point cloud descriptors (FCGF, Predator, GeoTransformer), or semantic/structural-landmark-assisted registration. Would any of these plausibly do better than plain multi-seed ICP on a *genuinely* symmetric local region, or is the ceiling the same regardless of algorithm (which would further support the "information-theoretic, not algorithmic" framing)?
3. **Cheap ways to widen ICP's candidate search** beyond a fixed 24-seed sweep with only the top 4 logged — adaptive/coarse-to-fine seeding, seeding informed by the previous attempt's belief, etc. — specifically to test whether the true answer is reachable at all before investing in a vision-based re-ranker.
4. **Visual place recognition / cross-view relocalization techniques** that could combine with (or substitute for) LiDAR in symmetric regions — e.g. NetVLAD-style global descriptors, visual loop-closure detection, visual-LiDAR fusion approaches specifically targeting symmetric/repetitive environments, one-shot RGB feature matching (we already use LoFTR elsewhere but haven't applied it to this specific problem) — and any known failure modes of *those* techniques we should anticipate (e.g. textureless walls, lighting changes, motion blur) before committing.
5. **Bounded / short-horizon dead-reckoning fusion**: is there established guidance on when odometry integrated over a *short, bounded* window (e.g. only across the single hop between two adjacent anchors, reset at every anchor rather than accumulated over a whole episode) is trustworthy enough to help disambiguate rotation, versus when even short-horizon odometry is too noisy to be useful? (Our own naive version of a *static* outbound-heading-based prior failed, per §4 — but we have not tried a *dynamic*, previous-anchor-anchored short-horizon version.)
6. **Runtime integrity monitoring / fault detection for robot relocalization** — literature on detecting "the localization estimate is wrong" from time-series self-consistency alone (sudden bearing/identity jumps, physically-implausible velocity of belief change) without any new sensing modality, as a cheap stopgap that prevents a wrong-but-confident reading from triggering an irreversible action (promotion, forced-stop) even if it can't fix the underlying wrong estimate.

---

## 7. Constraints any proposed solution needs to respect

- **No oracle/ground-truth information may be used online** — the robot has no access to its true position during return; everything above must work from the robot's own sensors (front/rear RGB-D, LiDAR/point-cloud) plus what was recorded into each anchor during outbound.
- **Compute budget:** the existing controller runs one relocalization attempt every 5 environment steps for the *entire* return phase, which can be 1,000-3,500+ steps long; any new heavy technique (like RGB feature matching) needs to be cheap enough to run at most at the two irreversible decision points per anchor (promotion, forced stop), not every attempt.
- **No accumulated long-horizon odometry** (already tried and rejected — see §4) — but bounded/short-horizon variants are an open question (see §6.5).
- Any fix should be evaluable **offline against already-captured data** where possible before being wired into the live simulator loop (the project has a capture pipeline that records full return-phase point clouds, and can be extended to capture RGB-D per anchor and per return step at low marginal cost).
