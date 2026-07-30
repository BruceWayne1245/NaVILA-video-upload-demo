from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "score_episode", ROOT / "scoring/score_episode.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


CONFIG = {
    "distance_bands_m": {
        "arrived_max": 2.65,
        "direct_far_strictly_greater_than": 3.35,
    }
}


def test_distance_band_boundaries_are_explicit():
    assert MODULE.distance_band(2.65, CONFIG) == "arrived"
    assert MODULE.distance_band(3.35, CONFIG) == "boundary"
    assert MODULE.distance_band(3.351, CONFIG) == "direct_far"


def test_first_accept_uses_chronological_first_row():
    records = [
        {
            "step": 10,
            "direct_distance_to_start_m": 2.5,
            "direct_distance_band": "arrived",
            "policy": False,
        },
        {
            "step": 20,
            "direct_distance_to_start_m": 2.4,
            "direct_distance_band": "arrived",
            "policy": True,
        },
        {
            "step": 30,
            "direct_distance_to_start_m": 4.0,
            "direct_distance_band": "direct_far",
            "policy": True,
        },
    ]
    value = MODULE.first_accept_summary(records, ["policy"])["policy"]
    assert value["first_accept_step"] == 20
    assert value["bands"]["arrived"] == 1
    assert value["bands"]["direct_far"] == 0


def test_ablation_configuration_cannot_control_runtime():
    config = (ROOT / "config/terminal_evidence_ablation_v1.json").read_text()
    assert '"control_effect": "none"' in config
    assert "not_an_activation_policy" in config
