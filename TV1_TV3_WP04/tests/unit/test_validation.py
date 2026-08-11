from __future__ import annotations

import json
import shutil
from pathlib import Path

from aic2026.config import load_settings
from aic2026.validation import ValidationPolicy, validate_run


def _copy_run(real_smoke_run, tmp_path: Path):
    runs = tmp_path / "runs"
    runs.mkdir()
    shutil.copytree(real_smoke_run["run_root"], runs / "real-smoke")
    settings, _ = load_settings(Path(__file__).parents[2] / "configs" / "external_video_smoke.yaml")
    settings.paths.runs_root = runs
    return runs / "real-smoke", settings


def test_valid_foundation_run_passes_g0_but_fallback_blocks_production_stable(real_smoke_run, tmp_path):
    _, settings = _copy_run(real_smoke_run, tmp_path)
    report, path = validate_run("real-smoke", settings)
    assert report.g0_pass is True
    assert report.stable_eligible is False
    assert report.severity_counts["P0"] == 0
    assert any(issue.code == "DEGRADED_FRAME_INDEX_BACKEND" for issue in report.issues)
    assert any(issue.code == "DEGRADED_SHOT_DETECTOR" for issue in report.issues)
    assert path.is_file()


def test_mapping_corruption_is_p0(real_smoke_run, tmp_path):
    run_root, settings = _copy_run(real_smoke_run, tmp_path)
    mapping = next((run_root / "mappings").glob("*.jsonl"))
    rows = [json.loads(line) for line in mapping.read_text(encoding="utf-8").splitlines() if line]
    rows[0]["pts"] = int(rows[0].get("pts") or 0) + 999999
    mapping.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    report, _ = validate_run("real-smoke", settings)
    assert report.g0_pass is False
    assert report.severity_counts["P0"] >= 1
    codes = {issue.code for issue in report.issues}
    assert "MODULE_ARTIFACT_MISSING_OR_CORRUPT" in codes or "KEYFRAME_ORIGINAL_MAPPING_MISMATCH" in codes


def test_policy_can_allow_degraded_smoke_for_test_sealing(real_smoke_run, tmp_path):
    _, settings = _copy_run(real_smoke_run, tmp_path)
    report, _ = validate_run(
        "real-smoke",
        settings,
        policy=ValidationPolicy(
            require_pyav_for_stable=False,
            require_autoshot_for_stable=False,
        ),
    )
    assert report.g0_pass is True
    assert report.stable_eligible is True


def test_validation_detects_pts_timebase_invariant(real_smoke_run, tmp_path):
    run_root, settings = _copy_run(real_smoke_run, tmp_path)
    index = next((run_root / "frame_indexes").glob("*.jsonl"))
    rows = [json.loads(line) for line in index.read_text(encoding="utf-8").splitlines() if line]
    rows[1]["raw_timestamp_ms"] = int(rows[1]["raw_timestamp_ms"]) + 333
    index.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    report, _ = validate_run("real-smoke", settings)
    assert report.g0_pass is False
    assert any(issue.code in {"PTS_TIMEBASE_MISMATCH", "MODULE_ARTIFACT_MISSING_OR_CORRUPT"} for issue in report.issues)
