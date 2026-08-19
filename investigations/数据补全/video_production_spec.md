# Supplementary video — production spec

Companion video for the dissertation *Reliability-Aware Sparse Route Memory for
Round-Trip Vision-Language Navigation*. Target: **3–4 minutes**, five segments
plus a closing regression clip.

Work through the phases in order. Phase 2 is a gate: do not start production
until it passes.

---

## What this video has to do

The results tables already establish *how much*. The video exists to show three
things a table cannot:

1. the **form** of baseline return failure — oscillation, drift, walking tens of
   metres from a route it has just traversed;
2. the **moment of arbitration** — the policy proposes one action, the system
   substitutes another;
3. **premature termination presenting as trajectory failure** — a STOP is vetoed,
   execution continues, and the episode goes on to arrive. This is the least
   intuitive finding in the dissertation and the hardest to convey in prose.

Design consequence: **trajectory footage alone is not sufficient.** Two robots
walking around prove roughly what a static figure proves. The internal state —
hint text, gate status, arbitration decision — must be overlaid on the frames.
That overlay is the deliverable's actual content.

## Honesty rules — these are not negotiable

- **Every clip is a real run whose recorded outcome matches its caption.** If a
  re-run produces a different outcome than the table predicts, either use the new
  outcome and change the caption, or discard the clip. Never caption a clip with
  an outcome from a different run of the same episode.
- **Label playback speed** in every segment (`8× speed` in a corner). Return
  phases run to thousands of control steps; speed-up is unavoidable, silent
  speed-up is not.
- **Label the configuration** in every segment. Oracle segments must carry
  `ground-truth pose` on screen, or viewers will read them as the proposed
  system's real performance.
- **The regression clip is mandatory.** A video containing only wins reads as
  cherry-picked and undermines everything before it.

---

## Phase 0 — Inventory what already exists

Before running anything, search the repo and the evaluation machine for existing
recordings:

```
NaVILA-video-upload-demo/            # repo name suggests prior uploads
NaVILA-Bench/batch_logs/*/           # per-episode dirs may hold frames or mp4
```

For each `(episode, configuration)` pair in the Phase 1 matrix, report:
`have full video` / `have frames only` / `have nothing`. Note the camera view
(third-person vs egocentric) and frame rate of anything found.

Most batch runs were launched for metrics, not recording, so expect to find
little. Report the inventory before proceeding — it determines how much of
Phase 1 is needed.

---

## Phase 1 — Runs required

Launch scripts for every configuration already exist:

```
investigations/数据补全/code/run_pure_oracle_hint_highsuccess100ep_20260811.sh
investigations/数据补全/code/run_pure_oracle_hint_action_highsuccess100ep_20260812.sh
investigations/数据补全/code/run_pure_oracle_hint_action_stopgate_highsuccess100ep_20260813.sh
final_data2/policy_v2_active50_replay_on_highsuccess100ep_20260816_code/   # online
```

Reuse their flags exactly — the video must depict the configurations the
dissertation evaluates. Add only recording flags. Restrict each to the single
episode needed rather than the full manifest.

### Run matrix

| Episode | Configuration(s) | Used in | Expected outcome |
|---|---|---|---|
| 1006 | language-only baseline | Seg 1, Seg 5 | return fails, ends 21.03 m from start |
| 1006 | online (proposed) | Seg 5 | return succeeds, ends 1.98 m |
| 1119 | Oracle hint | Seg 2, Seg 3 | return fails |
| 1119 | Oracle hint-action | Seg 3 | return succeeds |
| 33 | Oracle hint-action | Seg 4 | return fails, ends 3.79 m |
| 33 | Oracle hint-action-stop | Seg 4 | return succeeds, ends 1.69 m |
| 1378 | Oracle hint-action | Seg 4 insert | return fails, ends **0.20 m** |
| 428 | online | Seg 5 | return fails; bearing gate withholds on 100% of steps |
| 1439 | online | Seg 5 contrast | return succeeds; gate withholds on 0% of steps |
| 1154 | language-only baseline | Closing | return **succeeds** |
| 1154 | online (proposed) | Closing | return **fails** |

Roughly 11 runs. Each episode runs in its own simulator process under a 7200 s
timeout; typical wall time is far shorter, but budget generously.

### Fallbacks if an episode will not reproduce

- Seg 1 / Seg 5 big win — instead of 1006: **827** (11.31 m → 1.78 m),
  **1119** (10.83 → 0.80), **1517** (6.49 → 1.83)
- Seg 4 veto demonstration — instead of 33: **126** (3.95 m → 2.26 m),
  **922** (4.82 → 2.84)
- Seg 4 insert — instead of 1378: **1368** (hint-action ends 0.10 m, still judged
  a failure)
- Closing regression — instead of 1154: **428**, **128**, **1137**

### Recording settings

- Third-person chase camera as primary view; it shows the robot and the corridor
  structure together. Egocentric RGB as a small picture-in-picture where the
  VLM's actual input matters (Seg 2).
- Record the **full return phase**, plus the last ~10 s of outbound so the phase
  transition is visible.
- Fixed frame rate, and **log the control step index per frame** — Phase 3
  depends on being able to join frames to log lines. If the recorder cannot emit
  this, record a frame counter burned into a corner and reconcile against the
  step count afterwards.

---

## Phase 2 — Verification gate

For every completed run, extract the measurement file and check:

- `return_success` matches the expected outcome in the matrix;
- `distance_to_start` is within ~0.5 m of the expected value;
- `outbound_success` is true (all segments depict return-phase behaviour).

Produce a table of expected vs actual for all 11 runs.

**Do not begin Phase 4 until every clip's caption matches its own run.** Runs are
not deterministic; the table values come from earlier batches. If an episode
reproduces a different outcome, take a fallback from the list above rather than
forcing the original. If a fallback is used, say so in the report — the segment
captions and the episode numbers in this spec will need updating.

---

## Phase 3 — Overlay data

Parse the per-step eval log of each recorded run into a per-frame overlay table.
Existing parsers to start from:

```
investigations/数据补全/analysis/b4_stop_step_arbiter.py
investigations/数据补全/analysis/b6_b7_b8_b9.py
```

Both already match `[hint_arbiter] step=N override=X reason=Y`. Extend rather
than rewrite.

Fields to extract per step:

| Field | Display | Notes |
|---|---|---|
| hint text | `[Hint: anchor A7 · 2.3 m · left 35°]` | grey `— hint withheld (r_bearing 0.41 < 0.90)` when the gate withholds |
| VLM action | `VLM: turn right` | parsed from the policy output |
| arbitration | `→ EXECUTED` or `→ OVERRIDDEN (forward)` | flash red for ~0.4 s on override |
| running count | `overrides: 7` | cumulative, Seg 3 only |
| terminal state | `STOP proposed → VETOED` | Seg 4; hold on screen ~2 s |
| true distance | `d = 4.1 m` + a 3.0 m radius indicator | ground truth, label it as such |

Emit one CSV per clip: `frame_index, step, hint, vlm_action, arbitration,
terminal_state, distance_to_start`. Overlays are then rendered with ffmpeg
`drawtext` from this CSV rather than composited live in the simulator — this
guarantees the on-screen numbers and the dissertation's numbers come from the
same logs.

---

## Phase 4 — Composition

Each segment opens with a ~3 s black title card stating what it demonstrates and
which configuration is shown. Side-by-side split screen for all comparisons; the
same episode on both sides, synchronised by control step, not by wall time.

| # | Content | Episode(s) | ~Length |
|---|---|---|---|
| 1 | Baseline return failure: walks 21 m from a route it just traversed | 1006 baseline | 40 s |
| 2 | Perfect information is not enough: hint is correct throughout, policy contradicts it. Freeze on one conflict frame | 1119 Oracle hint | 50 s |
| 3 | Constraining the action: Oracle hint \| Oracle hint-action, same episode. Overrides flash; counter accumulates | 1119 both | 50 s |
| 4 | **Premature termination prevents arrival**: hint-action \| hint-action-stop. Left stops at 3.8 m and the episode ends; right's STOP is vetoed, execution continues, arrives. Insert: ep 1378 ending 0.20 m from start and still judged a failure | 33 both, 1378 insert | 60 s |
| 5 | Online system and its cost: baseline \| online on 1006. Then ep 428, gate withholding on every step, hint bar grey throughout, arbiter never fires — the deficit made visible. Contrast with ep 1439, gate never withholds | 1006, 428, 1439 | 60 s |
| — | Closing regression: baseline succeeds, proposed system fails. Caption: 4 of 49 episodes regressed | 1154 both | 20 s |

Segment 4 is the most valuable in the video; if length must be cut, take it from
segments 1 and 2, not from 4.

Closing card: the main results table (language-only 22.0% → Oracle ladder 37.2 /
71.1 / 86.0% → online 55.1%), with `Oracle rows use ground-truth pose` stated on
the card.

---

## Deliverables

1. `video/segments/` — rendered clips, one per segment
2. `video/final.mp4` — assembled cut, H.264, 1080p
3. `video/overlay_data/*.csv` — per-clip overlay tables
4. `video/VERIFICATION.md` — the Phase 2 expected-vs-actual table, any fallback
   substitutions made, and the final caption text for each segment

Report the Phase 0 inventory and the Phase 2 verification table before
assembling anything.
