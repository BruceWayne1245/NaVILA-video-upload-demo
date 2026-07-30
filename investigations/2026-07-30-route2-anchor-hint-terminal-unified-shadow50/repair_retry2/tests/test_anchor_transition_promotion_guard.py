from __future__ import annotations

import pathlib
import sys

import pytest


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from anchor_transition_runtime import (  # noqa: E402
    AnchorTransitionPromotionGuard,
)


MODEL_SHA = "4d37f9" * 10 + "4d37"


def make_guard(**overrides):
    values = {
        "confidence_threshold": 0.9,
        "max_deferrals_per_candidate": 2,
        "expected_model_sha256": MODEL_SHA,
    }
    values.update(overrides)
    return AnchorTransitionPromotionGuard(**values)


def observe(guard, attempt, action="rollback", confidence=0.95):
    guard.observe(
        attempt=attempt,
        action=action,
        confidence=confidence,
        model_sha256=MODEL_SHA,
    )


def evaluate(guard, attempt, baseline=True, current=5, next_index=4, kill=False):
    return guard.evaluate(
        current_anchor_index=current,
        next_anchor_index=next_index,
        proposal_attempt=attempt,
        baseline_vote=baseline,
        kill_switch_engaged=kill,
    )


def test_high_confidence_over_advance_signal_defers_only_next_attempt():
    guard = make_guard()
    observe(guard, 7)
    decision = evaluate(guard, 8)
    assert decision.executed_vote is False
    assert decision.controller_effect == "defer_promotion"
    assert decision.signal_attempt == 7


def test_guard_fails_open_after_bounded_deferrals():
    guard = make_guard()
    observe(guard, 7)
    assert evaluate(guard, 8).executed_vote is False
    observe(guard, 8)
    assert evaluate(guard, 9).executed_vote is False
    observe(guard, 9)
    decision = evaluate(guard, 10)
    assert decision.executed_vote is True
    assert decision.reason == "fail_open_deferral_cap"


@pytest.mark.parametrize(
    ("action", "confidence"),
    [
        ("hold", 0.99),
        ("advance_one", 0.99),
        ("rebase", 0.99),
        ("rollback", 0.89),
        ("skip_or_rebase", 0.89),
    ],
)
def test_non_risk_or_low_confidence_signal_allows_baseline(
    action, confidence
):
    guard = make_guard()
    observe(guard, 3, action=action, confidence=confidence)
    assert evaluate(guard, 4).executed_vote is True


def test_stale_same_attempt_non_adjacent_and_kill_switch_fail_open():
    guard = make_guard()
    observe(guard, 4)
    assert evaluate(guard, 4).executed_vote is True
    assert evaluate(guard, 6).executed_vote is True
    assert evaluate(guard, 5, current=5, next_index=3).executed_vote is True
    assert evaluate(guard, 5, kill=True).executed_vote is True


def test_never_turns_a_false_baseline_vote_true():
    guard = make_guard()
    observe(guard, 1, action="hold", confidence=0.99)
    decision = evaluate(guard, 2, baseline=False)
    assert decision.executed_vote is False
    assert decision.reason == "baseline_not_promoting"


def test_rejects_noncausal_timing_and_wrong_model_hash():
    guard = make_guard()
    with pytest.raises(ValueError, match="hash mismatch"):
        guard.observe(
            attempt=1,
            action="rollback",
            confidence=0.95,
            model_sha256="wrong",
        )
    with pytest.raises(ValueError, match="non-causal"):
        guard.observe(
            attempt=1,
            action="rollback",
            confidence=0.95,
            model_sha256=MODEL_SHA,
            feature_timing="same_attempt_post_selection",
        )
