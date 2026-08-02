# Route 2 2026-08-02 live-run status and handoff

更新时间：2026-08-02

## Smoke and controller fixes

Anchor V2 full-active ep368 smoke completed successfully after two controller boundary fixes:

- route-index direction is now inferred locally; both ascending and descending candidate pairs are supported;
- a same-anchor pair is a safe hold and can never self-promote or raise a fatal evaluator error;
- controller tests: 8/8 passed;
- smoke result: outbound/return/round-trip all `true`;
- V1.1 core validator: `pass`;
- 348 active directives, 17 promotions, 22 bounded recoveries, 9 same-anchor holds, no fatal evaluator marker;
- capture contains 3,762 trajectory rows.

The initial smoke exit-95 was a launcher omission (the validator path was not passed to the batch driver), not a capture failure. The capture was validated manually and the launcher now passes `validate_v11_core_episode.py`.

## Serial execution

The clean predecessor run is:

`promotion_quarantine_veto_30ep_20260801_resume11`

It resumes the original 30-episode plan from episode 11 (ep368), using the original configuration. Earlier automatically-created rows in the old run tag after the first interruption are invalid placeholders and must not be used as results.

The large successor is fixed as:

`anchor_v2_full_active_batch49_20260802`

It uses the locked `route2_anchorv2_terminal50.tsv` order excluding smoke ep368, for 49 episodes. Anchor V2 is `full_active`; TRB, Hint and Terminal are unchanged.

Launcher:

`/home/teambruce/navila-route2-v11-core-20260801/launch/run_anchor_v2_full_active_batch49_after_resume11.sh`

## Resource and liveness protections

- one serial flock shared by the full-active successor;
- no successor start while the predecessor wrapper, any evaluator, or any VLM server is present;
- predecessor processes exceeding 3,600 seconds are terminated as a full process tree;
- after the predecessor wrapper actually exits, a 60-second stability window is required before residue cleanup;
- only known predecessor evaluator run-tag processes and its dedicated VLM ports are cleaned;
- unknown processes are never killed automatically; the successor waits instead;
- GPU free memory must be at least 20 GiB before launch;
- each successor episode uses a 3,600-second timeout and 300-second kill-after;
- the batch driver kills evaluator/VLM process groups, waits for port closure, validates capture integrity, and continues after an individual failure.

At handoff time, resume11 was running independently of the conversation process and the batch49 watcher was waiting for the predecessor wrapper to finish. No TRB, Hint or Terminal change was active.

