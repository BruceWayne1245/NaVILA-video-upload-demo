from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
VALIDATION = ROOT / "validation"

import sys

sys.path.insert(0, str(VALIDATION))
from validate_episode_capture import validate  # noqa: E402


def make_capture(tmp_path: Path, *, episode: int = 670) -> Path:
    measurement = tmp_path / "measurements/episode.json"
    trajectory = tmp_path / "trajectories/episode.jsonl"
    measurement.parent.mkdir()
    trajectory.parent.mkdir()
    measurement.write_text('{"round_trip": {}}', encoding="utf-8")
    trajectory.write_text('{"step": 1}\n', encoding="utf-8")
    completion = {
        "complete": True,
        "physical_episode_id": episode,
        "measurement": {
            "path": str(measurement.relative_to(tmp_path)),
            "sha256": hashlib.sha256(measurement.read_bytes()).hexdigest(),
        },
        "trajectory": {
            "path": str(trajectory.relative_to(tmp_path)),
            "rows": 1,
        },
    }
    (tmp_path / "capture_completion.json").write_text(
        json.dumps(completion),
        encoding="utf-8",
    )
    return tmp_path


def test_accepts_complete_capture(tmp_path):
    summary = validate(make_capture(tmp_path), 670)
    assert summary["complete"] is True
    assert summary["trajectory_rows"] == 1


@pytest.mark.parametrize("mutation", ["missing", "wrong_episode", "zero_rows"])
def test_rejects_false_clean_exit_captures(tmp_path, mutation):
    root = make_capture(tmp_path)
    completion_path = root / "capture_completion.json"
    completion = json.loads(completion_path.read_text(encoding="utf-8"))
    if mutation == "missing":
        completion_path.unlink()
    elif mutation == "wrong_episode":
        completion["physical_episode_id"] = 49
        completion_path.write_text(json.dumps(completion), encoding="utf-8")
    else:
        completion["trajectory"]["rows"] = 0
        completion_path.write_text(json.dumps(completion), encoding="utf-8")
    with pytest.raises(Exception):
        validate(root, 670)


def test_rejects_path_escape(tmp_path):
    root = make_capture(tmp_path)
    completion_path = root / "capture_completion.json"
    completion = json.loads(completion_path.read_text(encoding="utf-8"))
    completion["measurement"]["path"] = "../outside.json"
    completion_path.write_text(json.dumps(completion), encoding="utf-8")
    with pytest.raises(ValueError, match="escapes"):
        validate(root, 670)
