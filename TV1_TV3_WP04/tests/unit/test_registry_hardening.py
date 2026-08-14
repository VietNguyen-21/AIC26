from pathlib import Path

import pytest

from aic2026.registry import RegistryError, RunRegistry
from aic2026.utils import sha256_file, write_json
from aic2026.validation import compute_artifact_state_sha256


def _setup_validated_registry(tmp_path: Path):
    run_root = tmp_path / "runs" / "r"
    artifact = run_root / "artifact.txt"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("ok", encoding="utf-8")
    manifest = run_root / "registry" / "artifacts" / "v" / "m.json"
    write_json(manifest, {
        "preprocess_run_id":"r","video_id":"v","module_name":"m","module_version":"1",
        "status":"completed","fingerprint":"fp","config_sha256":"c","source_sha256":"s",
        "artifact_paths":["artifact.txt"],"artifact_checksums":{"artifact.txt":sha256_file(artifact)},
    })
    report = run_root / "reports" / "validation.json"
    state = compute_artifact_state_sha256(run_root)
    write_json(report, {"g0_pass":True,"stable_eligible":True,"artifact_state_sha256":state})
    report_sha = sha256_file(report)
    registry_path = run_root / "registry" / "run_registry.sqlite3"
    with RunRegistry(registry_path) as registry:
        registry.register_run("r", status="completed", source_manifest_sha256="s", config_sha256="c")
        registry.mark_validated(
            "r", validation_report_path=report, validation_report_sha256=report_sha,
            artifact_state_sha256=state, severity_counts={"P0":0,"P1":0,"P2":0},
        )
    return run_root, artifact, report, report_sha, state


def test_registry_rejects_stale_artifacts_even_if_caller_bypasses_cli(tmp_path: Path):
    run_root, artifact, report, report_sha, state = _setup_validated_registry(tmp_path)
    artifact.write_text("changed", encoding="utf-8")
    with RunRegistry(run_root / "registry" / "run_registry.sqlite3") as registry:
        with pytest.raises(RegistryError, match="Artifacts changed after validation"):
            registry.mark_stable(
                "r", validation_report_path=report, validation_report_sha256=report_sha,
                artifact_state_sha256=state,
            )


def test_registry_can_seal_unchanged_validated_run(tmp_path: Path):
    run_root, _, report, report_sha, state = _setup_validated_registry(tmp_path)
    with RunRegistry(run_root / "registry" / "run_registry.sqlite3") as registry:
        registry.mark_stable(
            "r", validation_report_path=report, validation_report_sha256=report_sha,
            artifact_state_sha256=state,
        )
        assert registry.get_run("r")["status"] == "stable"
        with pytest.raises(RegistryError):
            registry.assert_run_mutable("r")
