from reliability.v11_validation import FORBIDDEN_FEATURE_TOKENS


def test_forbidden_feature_policy_covers_identity_and_ground_truth():
    assert "scene_id" in FORBIDDEN_FEATURE_TOKENS
    assert "episode_id" in FORBIDDEN_FEATURE_TOKENS
    assert "label_" in FORBIDDEN_FEATURE_TOKENS
    assert "true_" in FORBIDDEN_FEATURE_TOKENS
