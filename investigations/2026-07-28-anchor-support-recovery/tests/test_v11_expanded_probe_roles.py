from reliability.v11_runtime import CausalV11FeatureBuilder


def _record(anchor, role):
    return {
        "attempt": 1,
        "anchor_index": anchor,
        "anchor_role": role,
        "confidence": 0.9,
        "outcome": "pose_candidate",
    }


def test_explicit_roles_survive_nonadjacent_expanded_probe_order():
    builder = CausalV11FeatureBuilder([])
    prepared = builder.build_attempt(
        "ep",
        1,
        [
            _record(12, "current"),
            _record(6, "next"),
            _record(8, "other"),
            _record(7, "other"),
        ],
    )
    roles = {candidate.anchor_index: candidate.anchor_role for candidate in prepared}
    assert roles == {12: "current", 6: "next", 8: "other", 7: "other"}
