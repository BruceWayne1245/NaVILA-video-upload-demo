"""Reduced, runtime-only terminal features for stronger scene transfer."""

from __future__ import annotations

from typing import Any

from model_features import CausalFeatureState, assert_runtime_only


# Absolute route indices let a tree memorize route length and scene-specific
# anchor layouts.  Terminal authority needs distances, freshness, motion,
# evidence quality and relative support geometry instead.
ABSOLUTE_INDEX_TOKENS = (
    "anchor_index",
    "source_anchor_index",
    "target_anchor_index",
)


class TerminalV2FeatureState:
    def __init__(self) -> None:
        self._base = CausalFeatureState()

    def transform(self, row: dict[str, Any]) -> dict[str, float]:
        features = self._base.transform(row)
        reduced = {
            key: value
            for key, value in features.items()
            if not any(token in key for token in ABSOLUTE_INDEX_TOKENS)
        }
        assert_runtime_only(reduced)
        return reduced
