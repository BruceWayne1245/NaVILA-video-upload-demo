# Prospective learned-controller replay shadow

This queue runs only after the existing promotion-shadow 30-episode service
finishes and the GPU has remained free for a 60-second settle window.

The five episodes (`319`, `498`, `295`, `430`, and `1008`) do not occur in the
training corpus. They were selected from the existing evaluator cohort because
historical runs have reached outbound STOP often enough to exercise return
logic.

The latest frozen 2026-07-28 evaluator records causal candidate, route-memory,
movement, terminal, and V1.1 evidence. After each episode is complete,
`score_episode.py` reconstructs the exact chronological feature stream and
writes:

- `learned_controller_replay_shadow_v1.jsonl`
- `learned_controller_replay_shadow_v1_summary.json`

The learned models are never imported by the evaluator. Predictions are
post-episode counterfactuals with `control_effect="none"`. In particular, the
terminal validation threshold has no stopping authority.
