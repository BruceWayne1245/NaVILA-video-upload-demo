# Should Terminal arrival be hard-bound to trusted Anchor 0 observation?

Date: 2026-07-30

## Decision

No universal hard binding should be added.

Anchor 0 observation is useful positive evidence in a route-blind state, but
it is neither a reliable necessary condition nor a reliable sufficient
condition for arrival. Hard rules should constrain evidence eligibility and
contradictions, not equate one place-recognition output with the arrival
label.

## What the current gate actually does

The authoritative evaluator has two positive paths:

1. repeated fresh, Route2-trusted `next/raw` route evidence whose complete
   distance interval is inside the arrival radius;
2. when route evidence is unavailable, repeated VLM STOP plus repeated A0
   visual confirmation.

The first path does not require the observed anchor to be A0. The A0 binding
already exists only as the blind fallback.

## Why A0 should not be a universal necessary condition

- The success region is a radius around the start, not the exact original
  camera pose. A robot can be correctly arrived while A0 is outside the
  matcher viewpoint envelope.
- Occlusion, yaw, lighting, depth sparsity, descriptor capture failure and
  missingness can make A0 unavailable at the true start.
- A hard requirement turns sensor missingness into a permanent false
  negative. It would force safe-fail or endless verification even when fresh
  trusted route geometry is already consistently near.
- In shadow30, raising visual confidence enough to remove the observed far
  accepts also removes ep189, which was truly inside the arrived band.

## Why A0 should not be a sufficient condition

- A0 matching is place recognition, not ground-truth metric localization.
  Repeated observations can repeat the same perceptual alias.
- Ep640 was accepted at 4.319 m and ep783 at 3.618 m by repeated A0 visual plus
  VLM STOP.
- Repetition does not create independence when the camera view and matcher
  failure mode remain the same.
- Conjoining Terminal v2 with A0 is also not automatically independent:
  Terminal v2 already consumes A0/VLM/route-derived features. Correlated
  errors can pass both sides of the conjunction.

## Recommended conditional hierarchy

1. **Hard evidence-eligibility rules**
   - only fresh evidence;
   - explicit current/next role;
   - raw distance has positive terminal authority;
   - reconstructed distance never creates arrival;
   - stale, multi-hop, OOD or unavailable evidence has zero positive
     authority.
2. **Hard bounded contradiction**
   - a fresh trusted interval definitely outside the arrival radius vetoes
     that proposal;
   - the veto expires with evidence freshness and cannot become an infinite
     STOP denial.
3. **Direct near route path**
   - repeated fresh trusted raw-near evidence may confirm arrival without A0;
   - A0 can corroborate but is not mandatory.
4. **Route-blind fallback**
   - enter stationary, bounded verification;
   - collect multiple A0 probe records, raw confidence/distance, motion,
     repeated VLM intent and Terminal probability;
   - A0 contributes evidence but does not by itself publish STOP;
   - unresolved evidence ends in explicit safe-fail, not claimed success.

This keeps the genuinely useful hard constraints—freshness, provenance,
role, contradiction and boundedness—without making one fallible sensor a
semantic oracle.

## Fresh29 ablation

The next read-only batch compares:

- frozen Terminal v2 without an A0 requirement;
- Terminal v2 with strong repeated A0 as a hard necessary condition;
- legacy repeated A0 as a sufficient blind fallback;
- stronger repeated A0 as a sufficient blind fallback;
- the conditional hierarchy above.

Ground-truth direct distance is used only after each saved episode completes.
No counterfactual policy has movement or STOP authority.
