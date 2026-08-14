from pathlib import Path

from aic2026.config import load_settings
from aic2026.preprocessing import run_preprocessing
from aic2026.validation import ValidationPolicy, validate_run


def test_real_video_pipeline_resume_and_g0(real_smoke_run):
    settings = real_smoke_run["settings"]
    run_root = real_smoke_run["run_root"]
    assert (run_root / "frame_indexes").is_dir()
    assert (run_root / "frames.jsonl").is_file()
    assert (run_root / "temporal" / "manifest.json").is_file()
    report, _ = validate_run(
        "real-smoke", settings,
        policy=ValidationPolicy(require_pyav_for_stable=False, require_autoshot_for_stable=False),
    )
    assert report.g0_pass is True
    assert report.stable_eligible is True


def test_second_real_video_run_skips_all_completed_modules(real_smoke_run):
    config_path = Path(__file__).parents[2] / "configs" / "external_video_smoke.yaml"
    settings, raw = load_settings(config_path)

    # The session fixture intentionally uses FFprobe to verify the degraded
    # fallback path. The second run must use the exact same configuration,
    # otherwise the fingerprint changes when PyAV is installed.
    settings.media.frame_index_backend = "ffprobe"
    raw["media"]["frame_index_backend"] = "ffprobe"

    settings.paths.runs_root = real_smoke_run["runs"]

    result = run_preprocessing(
        source=real_smoke_run["root"] / "videos",
        run_id="real-smoke",
        settings=settings,
        raw_config=raw,
        repository_root=Path(__file__).parents[2],
    )

    assert result.errors == []
    assert result.executed_modules == 0
    assert result.skipped_modules >= 6
