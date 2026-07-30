from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def test_anchor_runtime_import_survives_preloaded_foreign_reliability_package():
    code = r"""
import sys
import types

foreign = types.ModuleType("reliability")
foreign.__path__ = ["/definitely/not/the/anchor/runtime"]
sys.modules["reliability"] = foreign
sys.path.insert(0, sys.argv[1])

from anchor_transition_runtime import (
    AnchorTransitionPromotionGuard,
    OnlineAnchorTransitionV1,
)

assert AnchorTransitionPromotionGuard.__module__.startswith(
    "anchor_transition_runtime."
)
assert OnlineAnchorTransitionV1.__module__.startswith(
    "anchor_transition_runtime."
)
"""
    env = dict(os.environ)
    result = subprocess.run(
        [sys.executable, "-c", code, str(ROOT)],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, result.stderr
