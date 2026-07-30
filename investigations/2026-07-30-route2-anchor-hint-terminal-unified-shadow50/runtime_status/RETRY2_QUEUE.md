# Retry2 queue status

Snapshot: 2026-07-30 12:02 BST.

- Route 1 active unit:
  `navila-promotion-shadow-unseen30v2-20260730.service`
- Route 1 description:
  `NaVILA promotion-shadow unseen30 v2 (corrected candidates) 20260730`
- Route 2 waiting unit:
  `navila-unified-shadow50-after-route1-v2-20260730.service`
- Route 2 state: waiting; no Route 2 VLM or Isaac process started.
- Route 2 next action after Route 1 completion: wait for at least 12,000 MiB
  free GPU memory, run frozen preflight, then start ep670 retry2 canary.
- Fresh49 starts only after ep670 produces a complete valid capture with
  Anchor shadow-only and all learned consumers off.

The waiting wrapper also checks matching Route 1 master scripts and evaluator
processes, so a renamed/transient systemd unit or an episode-to-episode GPU
gap cannot release Route 2 early.
