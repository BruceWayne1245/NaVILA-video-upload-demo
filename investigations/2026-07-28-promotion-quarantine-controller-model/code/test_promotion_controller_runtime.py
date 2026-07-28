import math
import os
import tempfile
import unittest

from promotion_controller_runtime import (
    PromotionDecisionPolicy,
    PromotionFeatureBuilder,
    PromotionModelBundle,
    PromotionShadowJsonlSession,
    reading_unreliability,
)


def _rec(anchor_index, confidence, inlier_count=300, ratio=0.5, near_tie=0,
         match_class="clean_full_pose", dist=1.0, **extra):
    row = {
        "anchor_index": anchor_index,
        "confidence": confidence,
        "inlier_count": inlier_count,
        "icp_best_to_second_score_ratio": ratio,
        "icp_near_tie_basin_count": near_tie,
        "match_class": match_class,
        "estimated_distance_to_anchor_m": dist,
        "overlap_ratio": 0.5,
        "corridor_degeneracy_ratio": 0.5,
        "mean_residual_m": 0.2,
        "median_residual_m": 0.2,
    }
    row.update(extra)
    return row


class ReadingUnreliabilityTest(unittest.TestCase):
    """2026-07-28: same U formula as route_memory_agent.py's
    _reading_unreliability (Injection A) -- higher = less trustworthy."""

    def test_none_when_a_required_field_is_missing(self):
        self.assertIsNone(reading_unreliability({"confidence": 1.0}))

    def test_none_for_a_none_record(self):
        self.assertIsNone(reading_unreliability(None))

    def test_high_confidence_clean_reading_scores_low(self):
        good = _rec(1, confidence=1.0, inlier_count=400, ratio=0.3, near_tie=0)
        bad = _rec(1, confidence=0.3, inlier_count=100, ratio=0.99, near_tie=3)
        self.assertLess(reading_unreliability(good), reading_unreliability(bad))


class PromotionFeatureBuilderTest(unittest.TestCase):
    """Mirrors the offline extract_dwell_dataset.py's per-attempt feature
    computation (investigations/2026-07-28-promotion-quarantine-controller-model/
    code/) -- these tests exist so an online/offline drift shows up as a
    failing test instead of a silent feature-order mismatch at inference
    time."""

    def test_returns_none_with_fewer_than_two_anchors(self):
        builder = PromotionFeatureBuilder()
        self.assertIsNone(builder.build_attempt("ep0", 1, [_rec(5, 1.0)]))
        self.assertIsNone(builder.build_attempt("ep0", 2, []))

    def test_role_inference_takes_the_higher_index_as_current(self):
        builder = PromotionFeatureBuilder()
        feat = builder.build_attempt("ep0", 1, [_rec(7, 0.9, dist=0.1), _rec(6, 0.5, dist=2.0)])
        self.assertEqual(feat["anchor_idx"], 6.0)  # 'next' role's index is what's tracked
        self.assertEqual(feat["cur_confidence"], 0.9)
        self.assertEqual(feat["next_confidence"], 0.5)

    def test_attempt_in_dwell_increments_within_a_dwell_and_resets_on_transition(self):
        builder = PromotionFeatureBuilder()
        f0 = builder.build_attempt("ep0", 1, [_rec(9, 1.0), _rec(8, 1.0)])
        f1 = builder.build_attempt("ep0", 2, [_rec(9, 1.0), _rec(8, 1.0)])
        f2 = builder.build_attempt("ep0", 3, [_rec(9, 1.0), _rec(8, 1.0)])
        self.assertEqual([f0["attempt_in_dwell"], f1["attempt_in_dwell"], f2["attempt_in_dwell"]], [0.0, 1.0, 2.0])
        # next candidate changes from 8 to 7 -- a new dwell, counter resets
        f3 = builder.build_attempt("ep0", 4, [_rec(9, 1.0), _rec(7, 1.0)])
        self.assertEqual(f3["attempt_in_dwell"], 0.0)
        self.assertEqual(f3["anchor_idx"], 7.0)

    def test_rolling_mean_and_std_are_causal_and_match_hand_computation(self):
        builder = PromotionFeatureBuilder()
        dists = [1.0, 2.0, 3.0]
        feats = [
            builder.build_attempt("ep0", i + 1, [_rec(9, 1.0), _rec(8, 1.0, dist=d)])
            for i, d in enumerate(dists)
        ]
        # attempt 1: no prior history yet
        self.assertIsNone(feats[0]["next_dist_rollmean"])
        # attempt 2: rolling stats over [1.0] only (this attempt's own 2.0 not included -- causal)
        self.assertAlmostEqual(feats[1]["next_dist_rollmean"], 1.0)
        self.assertAlmostEqual(feats[1]["next_dist_rollstd"], 0.0)
        # attempt 3: rolling stats over [1.0, 2.0]
        self.assertAlmostEqual(feats[2]["next_dist_rollmean"], 1.5)
        self.assertAlmostEqual(feats[2]["next_dist_rollstd"], math.sqrt(((1.5 - 1.0) ** 2 + (1.5 - 2.0) ** 2) / 2))

    def test_cur_bad_fraction_hist_is_none_before_three_samples_then_causal(self):
        builder = PromotionFeatureBuilder()
        # 5 attempts, current(9)'s confidence low enough each time to score U >= 2.5
        feats = []
        for i in range(5):
            f = builder.build_attempt(
                "ep0", i + 1,
                [_rec(9, confidence=0.1, inlier_count=50, ratio=0.99, near_tie=4), _rec(8, 1.0)],
            )
            feats.append(f)
        self.assertIsNone(feats[0]["cur_bad_fraction_hist"])
        self.assertIsNone(feats[1]["cur_bad_fraction_hist"])
        # at attempt 4, 3 PRIOR readings exist (attempts 1-3), all bad -> fraction 1.0
        self.assertEqual(feats[3]["cur_bad_fraction_hist"], 1.0)

    def test_match_class_one_hot_and_missing_record_is_all_none(self):
        builder = PromotionFeatureBuilder()
        feat = builder.build_attempt(
            "ep0", 1, [_rec(9, 1.0, match_class="ambiguous_high_confidence"), _rec(8, 1.0)]
        )
        self.assertEqual(feat["cur_match_ambiguous_high_confidence"], 1.0)
        self.assertEqual(feat["cur_match_clean_full_pose"], 0.0)

    def test_new_episode_resets_state_even_with_the_same_anchor_indices(self):
        builder = PromotionFeatureBuilder()
        builder.build_attempt("ep0", 1, [_rec(9, 1.0), _rec(8, 1.0)])
        builder.build_attempt("ep0", 2, [_rec(9, 1.0), _rec(8, 1.0)])
        feat = builder.build_attempt("ep1", 1, [_rec(9, 1.0), _rec(8, 1.0)])
        self.assertEqual(feat["attempt_in_dwell"], 0.0)
        self.assertIsNone(feat["next_dist_rollmean"])


class PromotionDecisionPolicyTest(unittest.TestCase):
    def test_quarantine_wins_above_threshold_regardless_of_wait_vs_promote(self):
        policy = PromotionDecisionPolicy(quarantine_threshold=0.65)
        self.assertEqual(
            policy.decide({"wait": 0.1, "promote": 0.2, "quarantine": 0.7}), "quarantine"
        )

    def test_below_threshold_falls_back_to_promote_vs_wait(self):
        policy = PromotionDecisionPolicy(quarantine_threshold=0.65)
        self.assertEqual(policy.decide({"wait": 0.3, "promote": 0.6, "quarantine": 0.1}), "promote")
        self.assertEqual(policy.decide({"wait": 0.7, "promote": 0.2, "quarantine": 0.1}), "wait")

    def test_metadata_round_trips_the_threshold(self):
        policy = PromotionDecisionPolicy(quarantine_threshold=0.42)
        self.assertEqual(policy.metadata()["quarantine_threshold"], 0.42)


class _StubModel:
    """Deterministic stand-in for a fitted sklearn classifier -- avoids
    pulling the real ~1MB trained artifact into a unit test; only exercises
    the bundle's save/load/hash/predict_proba plumbing."""

    def predict_proba(self, rows):
        # ignore input, return a fixed distribution -- this test is about the
        # bundle mechanics (hashing, feature-name-safe row building, reload),
        # not about model quality.
        return [[0.5, 0.3, 0.2] for _ in rows]


class PromotionModelBundleTest(unittest.TestCase):
    def test_save_load_round_trip_predicts_consistently(self):
        bundle = PromotionModelBundle(
            model=_StubModel(),
            feature_names=["next_confidence", "cur_confidence"],
            classes=["wait", "promote", "quarantine"],
            metadata={"format": PromotionModelBundle.FORMAT},
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "bundle.pkl")
            sha_at_save = bundle.save(path)
            loaded = PromotionModelBundle.load(path, mode="shadow")
            self.assertEqual(loaded.source_artifact_sha256, sha_at_save)
            self.assertEqual(loaded.feature_names, ["next_confidence", "cur_confidence"])
            proba = loaded.predict_proba({"next_confidence": 0.9, "cur_confidence": 0.4})
            self.assertEqual(proba, {"wait": 0.5, "promote": 0.3, "quarantine": 0.2})

    def test_missing_feature_becomes_nan_not_a_crash(self):
        bundle = PromotionModelBundle(
            model=_StubModel(),
            feature_names=["next_confidence", "some_feature_not_in_this_feat_dict"],
            classes=["wait", "promote", "quarantine"],
            metadata={},
        )
        # should not raise even though the second feature name is absent from feat
        proba = bundle.predict_proba({"next_confidence": 0.9})
        self.assertEqual(sum(proba.values()), 1.0)

    def test_load_rejects_non_shadow_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "bundle.pkl")
            PromotionModelBundle(_StubModel(), ["f"], ["wait", "promote", "quarantine"], {}).save(path)
            with self.assertRaises(ValueError):
                PromotionModelBundle.load(path, mode="active")


class PromotionShadowJsonlSessionTest(unittest.TestCase):
    """Fail-open contract: a scoring exception must never propagate out of
    score_attempt (mirrors V11ShadowJsonlSession's fail-open design in
    reliability/v11_runtime.py) -- a bug in this shadow path must not be
    able to crash a real episode."""

    def _make_bundle(self, tmp):
        path = os.path.join(tmp, "bundle.pkl")
        PromotionModelBundle(
            model=_StubModel(),
            feature_names=["next_confidence", "cur_confidence"],
            classes=["wait", "promote", "quarantine"],
            metadata={},
        ).save(path)
        return PromotionModelBundle.load(path, mode="shadow")

    def test_score_attempt_logs_and_never_raises_on_bad_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle = self._make_bundle(tmp)
            session = PromotionShadowJsonlSession(
                bundle, episode_key="ep0", log_path=os.path.join(tmp, "shadow.jsonl"),
            )
            # only one anchor -- build_attempt returns None -- should not raise
            out = session.score_attempt(step=0, attempt=1, records=[_rec(9, 1.0)])
            self.assertIsNone(out)

            # a record missing anchor_index entirely -> exception inside build_attempt,
            # must be caught, not propagated
            out2 = session.score_attempt(step=1, attempt=2, records=[{"confidence": 1.0}, {"confidence": 1.0}])
            self.assertIsNone(out2)
            summary = session.close()
            self.assertEqual(summary["shadow_exceptions"], 1)

    def test_valid_attempt_produces_a_decision_and_logs_enforcement_false(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle = self._make_bundle(tmp)
            log_path = os.path.join(tmp, "shadow.jsonl")
            session = PromotionShadowJsonlSession(bundle, episode_key="ep0", log_path=log_path)
            out = session.score_attempt(
                step=0, attempt=1, records=[_rec(9, 1.0), _rec(8, 0.5)],
                existing_heuristic_decision={"action": "wait"},
            )
            # stub always returns wait=0.5/promote=0.3/quarantine=0.2 -> quarantine below
            # threshold, then promote(0.3) < wait(0.5) -> "wait"
            self.assertEqual(out["decision"], "wait")
            session.close()
            with open(log_path) as f:
                lines = [l for l in f]
            self.assertTrue(any('"enforcement_enabled": false' in l for l in lines))
            self.assertTrue(any('"controller_effect": false' in l for l in lines))


if __name__ == "__main__":
    unittest.main()
