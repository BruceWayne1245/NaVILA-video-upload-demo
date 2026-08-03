# Unified 50-episode read-only protocol

## Purpose

Use one physical trajectory per episode to collect evidence for:

1. frozen Anchor Transition V1 promotion-guard shadow evaluation;
2. bounded Hint v3 evidence-recheck evaluation;
3. five Terminal/Anchor0 evidence-policy ablations.

All learned consumers are off.  `control_effect` is `none`; oracle distance is
used only after an episode exits.

## Cohort

- ep670: replication-only and excluded from all fresh pooled metrics;
- 49 fresh episodes;
- eight scenes;
- 49 unique route-geometry hashes;
- disjoint from Anchor/Terminal training, Shadow30, prospective5, and today's
  ep49/ep953 observations;
- every fresh route has baseline start-goal distance strictly greater than
  3.35 m;
- route lengths: 17 short, 21 medium, 11 long.

Fresh-scene allocation:

| Scene | Episodes |
|---|---:|
| `2azQ1b91cZZ` | 10 |
| `QUCTc6BB5sX` | 10 |
| `zsNo4HB9uLZ` | 9 |
| `TbHJrupSAjP` | 9 |
| `EU6Fwq7SyZv` | 4 |
| `X7HyMhZNoso` | 4 |
| `x8F5xyUWy9e` | 2 |
| `Z6MFQCViBuw` | 1 |

The exact order and metadata are frozen in `data/unified50.tsv`.

## Run order and validity

1. Run ep670 as an infrastructure and replication canary.
2. Require model/evaluator hashes, shadow-only Anchor mode, all V1.1 consumers
   off, and complete capture artifacts.
3. If infrastructure is healthy, start fresh49 whether ep670 experimentally
   succeeds or fails.

Ep670's experimental outcome must not gate fresh49.  Episodes that fail to
complete return remain valid system outcomes, although a particular
post-episode scorer may label them unscoreable.  Canary selection must not
condition on likely success/return completion.

## Anchor V1

- mode: shadow;
- confidence threshold: 0.90;
- maximum counterfactual deferrals: 2;
- ep670 excluded from pooled metrics.

Primary metrics:

- harmful-promotion catch precision;
- safe-promotion delay rate;
- eligible-promotion coverage;
- per-scene metrics.

Activation gate:

- precision at least 0.90;
- safe-delay rate at most 0.05;
- no scene with repeated high-confidence safe delays.

## Hint v3

- post-episode read-only;
- maximum two requests per episode/target;
- minimum same-target query gap of ten simulator steps.

Primary metrics:

- beneficial-weight precision;
- non-beneficial weight;
- request rate;
- clearance-unavailable recovery yield.

Activation gate:

- beneficial-weight precision at least 0.90;
- non-beneficial fraction at most 0.10;
- nonzero liveness.

## Terminal

Distance bands:

- arrived: at most 2.65 m;
- boundary: above 2.65 m and at most 3.35 m;
- direct-far: strictly above 3.35 m.

Read-only policies:

1. `terminal_model_only`;
2. `a0_hard_required_with_terminal`;
3. `legacy_a0_sufficient_fallback`;
4. `strong_a0_sufficient_fallback`;
5. `conditional_hierarchical`.

Primary metrics:

- first-accept direct-far count;
- arrived recall;
- boundary accept count;
- Terminal-blind Anchor0 probe coverage;
- missed-arrived runs.

A hard Anchor0 requirement is eligible for further consideration only if it
reduces direct-far accepts while losing no more than 0.10 absolute arrived
recall.  This eligibility rule is not an activation decision.

## Frozen artifact hashes

The exact manifest/config/source hashes are recorded in
`CHANGES_AND_WORKLOG.md` and `ARTIFACT_MANIFEST.sha256`.  Repairing the
runtime import collision must not alter the cohort, model binaries,
thresholds, or decision gates.
