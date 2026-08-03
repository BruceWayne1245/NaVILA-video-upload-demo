# Next steps

## Immediate blocker repair

1. Move the Anchor runtime modules into a uniquely named package such as
   `anchor_transition_runtime`, or load them through an explicit file-backed
   module boundary.  Do not rely on adding a second `reliability` directory to
   `sys.path`, and do not reload/replace the already-imported V1.1 package.
2. Update only the isolated evaluator import/wiring.  Preserve the exact
   Anchor model, feature construction, confidence threshold, maximum
   deferrals, and shadow-only behavior.
3. Add a regression test that imports the V1.1 `reliability` package first and
   then loads the Anchor shadow runtime successfully.
4. Make the episode driver propagate evaluator failure instead of reporting a
   misleading zero exit code.  Retain the outer `capture_completion.json`
   integrity check.
5. Run the existing 41 tests plus the new namespace/exit-propagation tests,
   compile all touched Python files, and repeat the full static/dynamic
   preflight.

## Resume the frozen experiment

6. Use new retry result tags; never overwrite either failed attempt.
7. Rerun ep670.  Confirm that a trajectory and complete capture files exist,
   Anchor is shadow-only, and every active V1.1 consumer remains off.
8. Treat ep670 only as replication evidence.  Its pass/fail must not enter
   fresh metrics and must not decide whether fresh49 runs once infrastructure
   is healthy.
9. Launch the unchanged fresh49 manifest.
10. Preserve incomplete-return episodes as system outcomes.  Score only the
    model analyses whose required artifacts exist; separately report
    scoreability and infrastructure health.

## Decision after data collection

11. **Anchor:** if fresh precision is at least 0.90, safe-delay rate is at most
    0.05, no scene repeats safe delays, and ep670 appears isolated, keep V1
    unchanged and prepare a separately authorized guarded-active collection.
    If ep670 repeats or the same pattern appears elsewhere, investigate the
    shared failure before activation.
12. **Hint:** activate nothing unless beneficial precision reaches at least
    0.90, non-beneficial fraction stays at or below 0.10, and the policy
    remains live.  It should initially remain evidence-request-only.
13. **Terminal:** compare the five registered policies without retuning on
    the batch.  Do not introduce a universal Anchor0 requirement.  Prefer the
    conditional hierarchy if it reduces direct-far acceptance without
    excessive arrived-recall loss.
14. If no registered Terminal policy is safe, collect richer route-blind
    evidence rather than forcing a threshold: Anchor0 confidence/distance,
    camera/viewpoint change, motion, freshness, provenance, route
    contradiction, repeated VLM intent, and Terminal probability.

## Repository discipline

15. Before continuing, pull and read the latest GitHub README and all newer
    investigations.  Resolve the runtime candidate from those documents and
    verify hashes; do not trust local historical README or code copies.
16. Keep future daily evidence under a new dated investigation directory and
    record failed launches separately from experimental results.
