from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DRIVER = (ROOT / "launch/run_manifest_batch_driver.sh").read_text(
    encoding="utf-8"
)
RUNNER = (ROOT / "launch/run_unified_shadow50.sh").read_text(
    encoding="utf-8"
)


def test_driver_rejects_false_clean_evaluator_exit():
    assert 'grep -Fq "[fatal_evaluator_exit]"' in DRIVER
    assert "exit_code=97" in DRIVER
    assert "EPISODE_VALIDATOR" in DRIVER
    assert "exit_code=96" in DRIVER


def test_canary_is_fail_fast_and_fresh_batch_still_finishes_audit():
    assert 'run_driver "${CANARY_TAG}" "${CANARY_EPISODE}" 1 1' in RUNNER
    assert 'run_driver "${BATCH_TAG}" "${BATCH_EPISODES}" 0 1' in RUNNER
    assert "NEEDS_INFRA_RETRY" in RUNNER
