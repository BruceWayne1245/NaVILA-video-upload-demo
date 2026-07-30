from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime_candidate/scripts"))

from stop_gate import ReturnStopGate  # noqa: E402


def progress(distance: float):
    return SimpleNamespace(
        distance_to_start_m=distance,
        relocalization_confidence=1.0,
        source="anchor_relocalization",
        evidence_age_updates=0,
        estimate_kind="raw_icp",
        estimate_role="next",
    )


def test_verify_to_blind_transition_records_probe_without_accepting():
    gate = ReturnStopGate(
        r_in=3.0,
        r_out=3.0,
        verify_queries=2,
        blind_max_queries=8,
    )
    # Establish a trusted definitely-far envelope.
    gate.check(progress(6.0), False, evidence_trusted=True)
    calls = []

    first = gate.check(
        progress(6.0),
        True,
        evidence_trusted=False,
        home_visual_probe=lambda: calls.append("first") or True,
    )
    second = gate.check(
        progress(6.0),
        True,
        evidence_trusted=False,
        home_visual_probe=lambda: calls.append("second") or True,
    )

    assert first.decision == "resume"
    assert second.state == "terminal_blind"
    assert second.decision == "resume"
    assert second.visual_home_confirmed is True
    assert calls == ["second"]
    assert gate.state == "terminal_blind"
