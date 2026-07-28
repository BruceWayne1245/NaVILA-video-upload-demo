import importlib.util
import sys
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1] / "code"
SCAN_CONTEXT_PATH = (
    ROOT / "policy_v2_live_candidate" / "scripts" / "scan_context.py"
)
spec = importlib.util.spec_from_file_location(
    "scan_context_runtime_candidate",
    SCAN_CONTEXT_PATH,
)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def test_connected_region_returns_size_and_matching_mask_with_wrapped_sectors():
    agree = np.zeros((3, 5), dtype=bool)
    agree[1, 0] = True
    agree[1, 4] = True
    agree[2, 4] = True
    agree[0, 2] = True

    size, mask = module._largest_connected_region_in_mask(agree)

    assert size == 3
    assert mask.dtype == np.bool_
    assert mask.shape == agree.shape
    assert int(mask.sum()) == size
    assert mask[1, 0]
    assert mask[1, 4]
    assert mask[2, 4]


def test_connected_region_stress_keeps_runtime_types_stable():
    rng = np.random.default_rng(20260728)
    for _ in range(500):
        agree = rng.random((20, 60)) > 0.82
        size, mask = module._largest_connected_region_in_mask(agree)
        assert isinstance(size, int)
        assert isinstance(mask, np.ndarray)
        assert int(mask.sum()) == size


def test_connected_region_rejects_non_grid_input():
    try:
        module._largest_connected_region_in_mask(np.asarray(1))
    except ValueError as exc:
        assert "two-dimensional" in str(exc)
    else:
        raise AssertionError("expected a clear ValueError for a scalar mask")
