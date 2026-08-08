from __future__ import annotations

from typing import Mapping

import torch
from torch.nn import functional as F


def anchor_v3_loss(
    output: Mapping[str, torch.Tensor],
    target: Mapping[str, torch.Tensor],
    *,
    action_weight: float = 1.0,
    pair_weight: float = 1.0,
    belief_weight: float = 0.5,
    confidence_weight: float = 0.25,
) -> dict[str, torch.Tensor]:
    """Masked multi-task loss for one atomic decision publication."""
    valid = target["time_mask"].bool()
    if not valid.any():
        zero = torch.zeros((), device=output["action_logits"].device, dtype=output["action_logits"].dtype)
        return {name: zero for name in ["total", "action", "pair", "belief", "confidence"]}

    action = F.cross_entropy(
        output["action_logits"][valid], target["action"][valid].long()
    )
    pair_valid = valid & target.get("pair_mask", valid).bool()
    pair_logits = output["pair_logits"]
    candidates = pair_logits.shape[-1]
    flat_pair = pair_logits.reshape(*pair_logits.shape[:2], candidates * candidates)
    pair_target = (
        target["current_position"].long() * candidates
        + target["next_position"].long()
    )
    pair = (
        F.cross_entropy(flat_pair[pair_valid], pair_target[pair_valid])
        if pair_valid.any()
        else torch.zeros((), device=pair_logits.device, dtype=pair_logits.dtype)
    )

    belief_target = target["belief"].to(output["belief_logits"].dtype)
    belief_target = belief_target / belief_target.sum(dim=-1, keepdim=True).clamp_min(1e-8)
    belief_valid = valid & target.get("belief_mask", valid).bool()
    valid_belief = belief_target[belief_valid]
    log_belief = F.log_softmax(output["belief_logits"][belief_valid], dim=-1)
    belief_terms = torch.where(
        valid_belief > 0.0, valid_belief * log_belief, torch.zeros_like(log_belief)
    )
    belief = (
        -belief_terms.sum(dim=-1).mean()
        if belief_valid.any()
        else torch.zeros((), device=output["belief_logits"].device, dtype=output["belief_logits"].dtype)
    )
    confidence = F.binary_cross_entropy(
        output["confidence"][valid],
        target["confidence"].to(output["confidence"].dtype)[valid],
    )
    total = (
        action_weight * action
        + pair_weight * pair
        + belief_weight * belief
        + confidence_weight * confidence
    )
    return {
        "total": total,
        "action": action,
        "pair": pair,
        "belief": belief,
        "confidence": confidence,
    }
