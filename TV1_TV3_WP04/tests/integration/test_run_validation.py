import shutil
from pathlib import Path

from aic2026.config import load_settings
from aic2026.registry import RunRegistry
from aic2026.utils import read_json, write_json
from aic2026.validation import ValidationPolicy, validate_run


def _copy_smoke(real_smoke_run, tmp_path: Path):
    target_runs = tmp_path / "runs"
    target_runs.mkdir()
    shutil.copytree(real_smoke_run["run_root"], target_runs / "copy")
    # Rename run IDs in registry/manifest is unnecessary for validation if we keep ID real-smoke;
    # put it at the same directory name to preserve registry keys.
    shutil.rmtree(target_runs / "copy")
    shutil.copytree(real_smoke_run["run_root"], target_runs / "real-smoke")
    settings, _ = load_settings(Path(__file__).parents[2] / "configs" / "external_video_smoke.yaml")
    settings.paths.runs_root = target_runs
    return target_runs / "real-smoke", settings


def test_pts_arithmetic_corruption_is_p0(real_smoke_run, tmp_path: Path):
    run_root, settings = _copy_smoke(real_smoke_run, tmp_path)
    index = next((run_root / "frame_indexes").glob("*.jsonl"))
    lines = index.read_text(encoding="utf-8").splitlines()
    import json

    row = json.loads(lines[1])
    row["raw_timestamp_ms"] += 500
    lines[1] = json.dumps(row)
    index.write_text("\n".join(lines) + "\n", encoding="utf-8")
    report, _ = validate_run("real-smoke", settings)
    assert report.g0_pass is False
    assert any(
        issue.code in {"PTS_TIMEBASE_MISMATCH", "MODULE_ARTIFACT_MISSING_OR_CORRUPT"}
        for issue in report.issues
    )


def test_stable_audit_is_written_outside_stable_root(real_smoke_run, tmp_path: Path):
    run_root, settings = _copy_smoke(real_smoke_run, tmp_path)
    policy = ValidationPolicy(require_pyav_for_stable=False, require_autoshot_for_stable=False)
    report, report_path = validate_run("real-smoke", settings, policy=policy)
    assert report.stable_eligible
    from aic2026.utils import sha256_file

    with RunRegistry(run_root / "registry" / "run_registry.sqlite3") as registry:
        registry.mark_stable(
            "real-smoke",
            validation_report_path=report_path,
            validation_report_sha256=sha256_file(report_path),
            artifact_state_sha256=report.artifact_state_sha256 or "",
        )
    before = {
        p.relative_to(run_root).as_posix(): p.stat().st_mtime_ns
        for p in run_root.rglob("*")
        if p.is_file()
    }
    _, audit_path = validate_run("real-smoke", settings, policy=policy)
    after = {
        p.relative_to(run_root).as_posix(): p.stat().st_mtime_ns
        for p in run_root.rglob("*")
        if p.is_file()
    }
    assert before == after
    assert "_audits" in audit_path.parts
