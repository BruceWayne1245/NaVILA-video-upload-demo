"""Self-contained online inference adapter for Anchor V3.

Consumes the SAME per-attempt candidate schema the live runtime already
builds for Anchor V2 (`round_trip_eval.py`'s `new_records` / `raw_candidates`
-- see `anchor_transition_pending["raw_candidates"]`), so no new feature
extraction is needed: this reuses `tensorize_candidates` unchanged from the
offline package.

This module does not import, modify, or depend on anything in the runtime
repo (`navila-route2-v11-core-20260801`). It is a standalone adapter that a
future, separately-reviewed integration step would call from
`route_memory_agent.py` -- that wiring has not been written yet and is not
authorized by this module. There is no shadow/active flag here because there
is nothing to flag on: nothing calls this from a live process yet.

Maintains a rolling `sequence_length`-frame window per episode (the causal
Transformer's context), unlike the offline `ReplaySequenceDataset` which
operates on fixed pre-chunked sequences from a whole recorded episode. There
is no oracle at inference time, so `AtomicDecision`/`validate_decision` from
`anchor_v3.contract` are used for the output instead of `teacher.py`, which
requires ground truth and only applies to offline label construction.
"""
from __future__ import annotations

from collections import deque
from pathlib import Path
from typing import Any, Mapping, Optional

import numpy as np
import torch

from anchor_v3.contract import Action, AtomicDecision, validate_decision
from anchor_v3.dataset import collate_sequences
from anchor_v3.model import ACTION_ORDER, AnchorV3
from anchor_v3.normalization import ScalarNormalizer
from anchor_v3.tensorize import tensorize_candidates


class AnchorV3OnlineAdapter:
    """Call ``observe_attempt`` once per completed relocalization attempt."""

    def __init__(
        self,
        model: AnchorV3,
        normalizer: ScalarNormalizer,
        *,
        sequence_length: int = 8,
        device: str | torch.device = "cpu",
    ) -> None:
        self.model = model.to(device)
        self.model.eval()
        self.normalizer = normalizer
        self.sequence_length = int(sequence_length)
        self.device = torch.device(device)
        self._history: deque[dict[str, Any]] = deque(maxlen=self.sequence_length)
        self._state_current: Optional[int] = None
        self._state_next: Optional[int] = None
        self._previous_ordinal: Optional[int] = None
        self._previous_step: Optional[int] = None

    @classmethod
    def from_checkpoint(
        cls,
        checkpoint_path: Path,
        normalizer_path: Path,
        *,
        sequence_length: int = 8,
        device: str | torch.device = "cpu",
    ) -> "AnchorV3OnlineAdapter":
        normalizer = ScalarNormalizer.load(Path(normalizer_path))
        checkpoint = torch.load(Path(checkpoint_path), map_location=device, weights_only=False)
        state_dict = checkpoint["model"]
        scalar_dim = state_dict["token_projection.0.weight"].shape[1]
        # token_input = point_dim*2 + scalar_dim*2 + categorical_dim; point_dim=64 fixed default.
        # Recover scalar_dim/categorical_dim directly from the normalizer instead (robust to
        # architecture defaults changing): normalizer was fit on candidate_scalar's own width.
        scalar_dim = len(normalizer.mean)
        categorical_dim = state_dict["token_projection.0.weight"].shape[1] - 64 * 2 - scalar_dim * 2
        model = AnchorV3(scalar_dim=scalar_dim, categorical_dim=categorical_dim)
        model.load_state_dict(state_dict)
        return cls(model, normalizer, sequence_length=sequence_length, device=device)

    def reset(self) -> None:
        """Call at the start of a new episode."""
        self._history.clear()
        self._state_current = None
        self._state_next = None
        self._previous_ordinal = None
        self._previous_step = None

    def observe_attempt(
        self,
        candidates: list[dict[str, Any]],
        *,
        current_points_xyz: Any,
        anchor_points_by_index: Mapping[int, Any],
        decision_ordinal: Optional[int] = None,
        step: Optional[int] = None,
    ) -> AtomicDecision:
        """Tensorize one completed relocalization attempt, run the model over
        the rolling window ending at this attempt, and return an atomic
        decision for just this attempt (the causal window's last timestep).

        ``candidates`` must be the same per-candidate record schema the live
        runtime already builds for Anchor V2 (list of dicts keyed by
        ``anchor_index``, ``match_class``, ``inlier_count``, etc. -- see
        ``anchor_v3/tensorize.py``'s ``SCALAR_FEATURES``/``MATCH_CLASSES``).
        """
        if not candidates:
            raise ValueError("at least one candidate is required")

        decision_gap = (
            int(decision_ordinal) - self._previous_ordinal
            if decision_ordinal is not None and self._previous_ordinal is not None
            else None
        )
        environment_step_gap = (
            int(step) - self._previous_step
            if step is not None and self._previous_step is not None
            else None
        )
        prior_belief = {self._state_current: 1.0} if self._state_current is not None else {}

        tensors = tensorize_candidates(
            candidates,
            current_points_xyz=current_points_xyz,
            anchor_points_by_index=anchor_points_by_index,
            state_current=self._state_current,
            state_next=self._state_next,
            prior_belief=prior_belief,
            decision_gap=decision_gap,
            environment_step_gap=environment_step_gap,
        )
        candidate_indices = tensors["candidate_indices"].tolist()

        placeholder_target = {
            "action": 0,
            "current_position": 0,
            "next_position": 0,
            "pair_mask": False,
            "belief": np.zeros(len(candidates), dtype=np.float32),
            "belief_mask": False,
            "confidence": 0.0,
        }
        self._history.append({"input": tensors, "target": placeholder_target})

        batch = collate_sequences([list(self._history)])
        inputs = {key: value.to(self.device) for key, value in batch["input"].items()}
        with torch.no_grad():
            output = self.model(**self.normalizer.apply(inputs))

        t = len(self._history) - 1
        action = Action(ACTION_ORDER[int(output["action_logits"][0, t].argmax())])
        confidence = float(output["confidence"][0, t])

        n = len(candidate_indices)
        belief_probs = torch.softmax(output["belief_logits"][0, t, :n], dim=-1)
        belief = {int(candidate_indices[i]): float(belief_probs[i]) for i in range(n)}

        candidates_dim = output["pair_logits"].shape[-1]
        pair_flat = output["pair_logits"][0, t].reshape(-1)
        pred_current_pos, pred_next_pos = divmod(int(pair_flat.argmax()), candidates_dim)

        current_anchor: Optional[int]
        next_anchor: Optional[int]
        if action is Action.ABSTAIN or pred_current_pos >= n or pred_next_pos >= n:
            action = Action.ABSTAIN if pred_current_pos >= n or pred_next_pos >= n else action
            current_anchor, next_anchor = None, None
        else:
            current_anchor = int(candidate_indices[pred_current_pos])
            next_anchor = int(candidate_indices[pred_next_pos])

        decision = AtomicDecision(action, current_anchor, next_anchor, confidence, belief)
        validate_decision(decision, set(int(i) for i in candidate_indices))

        self._state_current, self._state_next = current_anchor, next_anchor
        self._previous_ordinal = decision_ordinal
        self._previous_step = step
        return decision
