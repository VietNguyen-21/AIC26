from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import yaml
from typer.testing import CliRunner

from aic2026 import cli
from aic2026.config import Settings
from aic2026.evidence_catalog import CatalogBuildResult

runner = CliRunner()


def _config(tmp_path: Path) -> tuple[Path, Settings]:
    settings = Settings()
    settings.paths.runs_root = tmp_path / "runs"
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(settings.model_dump(mode="json"), sort_keys=False), encoding="utf-8")
    return path, settings


def test_doctor_inspect_download_and_export(tmp_path: Path, monkeypatch):
    config, _ = _config(tmp_path)
    monkeypatch.setattr(cli, "pyav_available", lambda: True)
    monkeypatch.setattr(cli.shutil, "which", lambda name: f"/usr/bin/{name}")
    result = runner.invoke(cli.app, ["doctor", "--config", str(config)])
    assert result.exit_code == 0
    assert json.loads(result.stdout)["production_ready"] is True

    manifest = tmp_path / "manifest.xlsx"
    manifest.write_bytes(b"fixture")
    monkeypatch.setattr(cli, "manifest_entries", lambda path: [{"filename": "Videos_A.mp4", "url": "u"}])
    inspected = runner.invoke(cli.app, ["inspect-batch-manifest", "--manifest", str(manifest)])
    assert inspected.exit_code == 0 and "Videos_A.mp4" in inspected.stdout

    downloaded_path = tmp_path / "videos" / "Videos_A.mp4"
    monkeypatch.setattr(cli, "download_entries", lambda entries, output, include_prefix: [downloaded_path])
    downloaded = runner.invoke(
        cli.app,
        ["download-batch-videos", "--manifest", str(manifest), "--output", str(tmp_path / "videos")],
    )
    assert downloaded.exit_code == 0
    downloaded_payload = json.loads(downloaded.stdout)
    assert downloaded_payload == [str(downloaded_path)]

    schema_dir = tmp_path / "schemas"
    exported = runner.invoke(cli.app, ["export-schemas", "--output", str(schema_dir)])
    assert exported.exit_code == 0
    assert (schema_dir / "Settings.schema.json").is_file()


def test_preprocess_success_and_failure(tmp_path: Path, monkeypatch):
    config, settings = _config(tmp_path)
    monkeypatch.setattr(cli, "_settings", lambda path: (settings, {"fixture": True}))

    def fake_result(errors):
        return SimpleNamespace(
            run=SimpleNamespace(model_dump=lambda mode: {"preprocess_run_id": "r"}),
            executed_modules=["ingest"],
            skipped_modules=[],
            errors=errors,
            registry_summary={"completed": 1},
        )

    monkeypatch.setattr(cli, "run_preprocessing", lambda **kwargs: fake_result([]))
    success = runner.invoke(
        cli.app,
        ["preprocess", "--input", str(tmp_path), "--run-id", "r", "--config", str(config)],
    )
    assert success.exit_code == 0 and '"executed_modules"' in success.stdout

    monkeypatch.setattr(cli, "run_preprocessing", lambda **kwargs: fake_result(["broken"]))
    failure = runner.invoke(
        cli.app,
        ["preprocess", "--input", str(tmp_path), "--run-id", "r", "--config", str(config)],
    )
    assert failure.exit_code == 2


def test_catalog_text_status_reload_commands(tmp_path: Path, monkeypatch):
    config, settings = _config(tmp_path)
    run_root = settings.paths.runs_root / "r"
    monkeypatch.setattr(cli, "_settings", lambda path: (settings, {}))
    build_result = CatalogBuildResult(
        database_path=run_root / "evidence_catalog" / "evidence.sqlite3",
        manifest_path=run_root / "evidence_catalog" / "manifest.json",
        reused=False,
        counts={"ocr": 1, "asr": 2, "object": 3, "metadata": 4},
    )
    monkeypatch.setattr(cli, "build_evidence_catalog", lambda *args, **kwargs: build_result)
    monkeypatch.setattr(cli, "validate_evidence_catalog", lambda *args, **kwargs: {"valid": True, "counts": build_result.counts})

    built = runner.invoke(cli.app, ["build-evidence-catalog", "--run-id", "r", "--config", str(config)])
    assert built.exit_code == 0 and '"ocr": 1' in built.stdout
    status = runner.invoke(cli.app, ["evidence-catalog-status", "--run-id", "r", "--config", str(config)])
    assert status.exit_code == 0 and '"valid": true' in status.stdout

    manifest = SimpleNamespace(model_dump=lambda mode: {"document_count": 10})
    text_result = SimpleNamespace(
        manifest=manifest,
        reused=False,
        requested_adapter="local_bm25",
        selected_adapter="local_bm25",
        degraded_reason=None,
    )
    monkeypatch.setattr(cli, "build_text_index", lambda *args, **kwargs: text_result)
    monkeypatch.setattr(cli, "validate_text_index_artifacts", lambda *args, **kwargs: {"valid": True})
    invalidated = []
    monkeypatch.setattr(cli, "invalidate_text_index_cache", lambda root: invalidated.append(root))

    built_text = runner.invoke(cli.app, ["build-text-index", "--run-id", "r", "--config", str(config)])
    assert built_text.exit_code == 0 and "local_bm25" in built_text.stdout
    text_status = runner.invoke(cli.app, ["text-index-status", "--run-id", "r", "--config", str(config)])
    assert text_status.exit_code == 0
    reloaded = runner.invoke(cli.app, ["reload-text-index", "--run-id", "r", "--config", str(config)])
    assert reloaded.exit_code == 0 and invalidated == [run_root]


def test_certify_benchmark_and_handoff_commands(tmp_path: Path, monkeypatch):
    config, settings = _config(tmp_path)
    settings.paths.runs_root = tmp_path / "runs"
    monkeypatch.setattr(cli, "_settings", lambda path: (settings, {}))

    cert_report = {"acceptance": {"competition_ready": False}, "profile": "development"}
    monkeypatch.setattr(cli, "certify_models", lambda *args, **kwargs: cert_report)
    cert = runner.invoke(cli.app, ["certify-tv3-models", "--config", str(config), "--output", str(tmp_path / "cert.json")])
    assert cert.exit_code == 0
    cert_load = runner.invoke(cli.app, ["certify-tv3-models", "--config", str(config), "--load-models"])
    assert cert_load.exit_code == 5

    queries = tmp_path / "queries.txt"
    queries.write_text("# comment\ncar\nspeech\n", encoding="utf-8")
    benchmark_report = {"quality_metrics": "PENDING_GROUND_TRUTH", "total_requests": 4}
    monkeypatch.setattr(cli, "benchmark_concurrent_queries", lambda *args, **kwargs: benchmark_report)
    written = []
    monkeypatch.setattr(cli, "write_benchmark_report", lambda path, report: written.append((path, report)))
    benchmark = runner.invoke(
        cli.app,
        ["benchmark-tv3", "--run-id", "r", "--queries", str(queries), "--config", str(config), "--output", str(tmp_path / "bench.json")],
    )
    assert benchmark.exit_code == 0 and written[0][1] == benchmark_report

    run_root = settings.paths.runs_root / "r"
    for relative in [
        "ocr/ocr.jsonl", "asr/asr.jsonl",
        "objects/objects.jsonl", "metadata/metadata.jsonl",
    ]:
        path = run_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}\n", encoding="utf-8")

    handoff_path = run_root / "handoff_tv1_tv3.json"
    handoff_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "preprocess_run_id": "r",
                "status": "completed",
                "candidate_policy": {
                    "ocr": "exact_source_frame_submittable",
                    "asr": "requires_temporal_resolution_before_submit",
                    "metadata": "video_soft_boost_only_not_submittable",
                    "object": "exact_source_frame_soft_constraint_submittable",
                },
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        cli, "validate_evidence_catalog", lambda *args, **kwargs: {"valid": True}
    )
    monkeypatch.setattr(
        cli, "validate_text_index_artifacts", lambda *args, **kwargs: {"valid": True}
    )

    handoff = runner.invoke(
        cli.app, ["verify-tv3-handoff", "--run-id", "r", "--config", str(config)]
    )
    assert handoff.exit_code == 0
    assert '"handoff_contract_valid": true' in handoff.stdout
    assert '"evidence_catalog_valid": true' in handoff.stdout
    assert '"text_index_valid": true' in handoff.stdout
    assert '"compatible": true' in handoff.stdout

    not_stable = runner.invoke(
        cli.app,
        [
            "verify-tv3-handoff", "--run-id", "r", "--config", str(config),
            "--require-stable",
        ],
    )
    assert not_stable.exit_code == 6
    assert '"stable_ok": false' in not_stable.stdout

    registry_path = run_root / "registry" / "run_registry.sqlite3"
    with cli.RunRegistry(registry_path) as registry:
        registry.register_run(
            "r",
            status="stable",
            source_manifest_sha256="a" * 64,
            config_sha256="b" * 64,
            details={"stable": {"artifact_state_sha256": "c" * 64}},
        )
    stable_payload = json.loads(handoff_path.read_text(encoding="utf-8"))
    stable_payload["status"] = "stable"
    stable_payload["artifact_state_sha256"] = "c" * 64
    handoff_path.write_text(json.dumps(stable_payload), encoding="utf-8")

    stable_handoff = runner.invoke(
        cli.app,
        [
            "verify-tv3-handoff", "--run-id", "r", "--config", str(config),
            "--require-stable",
        ],
    )
    assert stable_handoff.exit_code == 0
    assert '"run_status": "stable"' in stable_handoff.stdout
    assert '"handoff_status": "stable"' in stable_handoff.stdout
    assert '"stable_artifact_state_match": true' in stable_handoff.stdout
    assert '"stable_ok": true' in stable_handoff.stdout
    assert '"compatible": true' in stable_handoff.stdout

    monkeypatch.setattr(
        cli, "validate_evidence_catalog", lambda *args, **kwargs: {"valid": False}
    )
    bad_catalog = runner.invoke(
        cli.app,
        [
            "verify-tv3-handoff", "--run-id", "r", "--config", str(config),
            "--require-stable",
        ],
    )
    assert bad_catalog.exit_code == 6
    assert '"evidence_catalog_valid": false' in bad_catalog.stdout
    assert '"compatible": false' in bad_catalog.stdout

    monkeypatch.setattr(
        cli, "validate_evidence_catalog", lambda *args, **kwargs: {"valid": True}
    )
    handoff_path.unlink()
    incompatible = runner.invoke(
        cli.app,
        [
            "verify-tv3-handoff", "--run-id", "r", "--config", str(config),
            "--require-stable",
        ],
    )
    assert incompatible.exit_code == 6
    assert '"compatible": false' in incompatible.stdout


def test_release_commands(tmp_path: Path):
    clean = tmp_path / "clean"
    clean.mkdir()
    (clean / "README.md").write_text("clean\n", encoding="utf-8")
    audit = runner.invoke(cli.app, ["release-audit", "--root", str(clean)])
    assert audit.exit_code == 0
    output = tmp_path / "release.zip"
    package = runner.invoke(cli.app, ["release-package", "--root", str(clean), "--output", str(output)])
    assert package.exit_code == 0 and output.is_file() and "sha256" in package.stdout
    (clean / "bad.mp4").write_bytes(b"x")
    dirty = runner.invoke(cli.app, ["release-audit", "--root", str(clean)])
    assert dirty.exit_code == 4


def test_metadata_registry_validation_keyframe_and_serve_commands(tmp_path: Path, monkeypatch):
    config, settings = _config(tmp_path)
    settings.paths.runs_root = tmp_path / "runs"
    run_root = settings.paths.runs_root / "r"
    monkeypatch.setattr(cli, "_settings", lambda path: (settings, {}))

    media_path = run_root / "media" / "media.jsonl"
    media_path.parent.mkdir(parents=True, exist_ok=True)
    media_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "preprocess_run_id": "r",
                "video_id": "V1",
                "original_video_path": "video.mp4",
                "source_sha256": "a" * 64,
                "duration_ms": 1000,
                "width_px": 320,
                "height_px": 180,
                "has_audio": False,
                "created_at_utc": "2026-01-01T00:00:00Z",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    import_result = SimpleNamespace(
        report=SimpleNamespace(status="completed", model_dump=lambda mode: {"status": "completed"}),
        records=[{"x": 1}],
        artifact_paths=[run_root / "metadata" / "organizer.jsonl"],
    )
    monkeypatch.setattr(cli, "import_organizer_youtube_metadata", lambda *args, **kwargs: import_result)
    monkeypatch.setattr(cli, "consolidate_metadata_artifacts", lambda root: [{"x": 1}, {"x": 2}])
    monkeypatch.setattr(cli, "invalidate_text_index_cache", lambda root: None)
    imported = runner.invoke(cli.app, ["import-organizer-metadata", "--run-id", "r", "--config", str(config)])
    assert imported.exit_code == 0 and '"combined_records": 2' in imported.stdout

    registry_path = run_root / "registry" / "run_registry.sqlite3"
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.touch()

    class FakeRegistry:
        def __init__(self, path): self.path = path
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def get_run(self, run_id): return {"run_id": run_id, "status": "completed"}
        def summarize_run(self, run_id): return {"completed": 2}
        def list_status(self, run_id): return [{"module": "ocr", "status": "completed"}]
        def assert_run_mutable(self, run_id): return None

    monkeypatch.setattr(cli, "RunRegistry", FakeRegistry)
    registry = runner.invoke(cli.app, ["registry-status", "--run-id", "r", "--config", str(config)])
    assert registry.exit_code == 0 and '"module": "ocr"' in registry.stdout

    validation_report = SimpleNamespace(
        g0_pass=True,
        model_dump=lambda mode: {"g0_pass": True, "stable_eligible": False},
    )
    monkeypatch.setattr(cli, "validate_run", lambda run_id, settings: (validation_report, run_root / "validation.json"))
    validated = runner.invoke(cli.app, ["validate-run", "--run-id", "r", "--config", str(config)])
    assert validated.exit_code == 0 and '"g0_pass": true' in validated.stdout

    monkeypatch.setattr(cli, "benchmark_keyframe_strategies", lambda media, root, settings: {"video_id": media.video_id, "strategies": 3})
    keyframes = runner.invoke(
        cli.app,
        ["benchmark-keyframes", "--run-id", "r", "--video-id", "V1", "--config", str(config)],
    )
    assert keyframes.exit_code == 0 and '"strategies": 3' in keyframes.stdout

    calls = []
    fake_uvicorn = SimpleNamespace(run=lambda app, host, port: calls.append((app, host, port)))
    monkeypatch.setitem(__import__("sys").modules, "uvicorn", fake_uvicorn)
    monkeypatch.setattr(cli, "create_app", lambda run_id, config: "fixture-app")
    served = runner.invoke(
        cli.app,
        ["serve", "--run-id", "r", "--config", str(config), "--host", "0.0.0.0", "--port", "9999"],
    )
    assert served.exit_code == 0 and calls == [("fixture-app", "0.0.0.0", 9999)]


def test_cli_failure_branches(tmp_path: Path, monkeypatch):
    config, settings = _config(tmp_path)
    settings.paths.runs_root = tmp_path / "runs"
    monkeypatch.setattr(cli, "_settings", lambda path: (settings, {}))

    missing_registry = runner.invoke(cli.app, ["registry-status", "--run-id", "missing", "--config", str(config)])
    assert missing_registry.exit_code != 0
    assert "Registry not found" in missing_registry.output

    report = SimpleNamespace(g0_pass=False, model_dump=lambda mode: {"g0_pass": False})
    monkeypatch.setattr(cli, "validate_run", lambda run_id, settings: (report, tmp_path / "validation.json"))
    invalid = runner.invoke(cli.app, ["validate-run", "--run-id", "r", "--config", str(config)])
    assert invalid.exit_code == 3

    media_path = settings.paths.runs_root / "r" / "media" / "media.jsonl"
    media_path.parent.mkdir(parents=True, exist_ok=True)
    media_path.write_text("", encoding="utf-8")
    unknown = runner.invoke(
        cli.app,
        ["benchmark-keyframes", "--run-id", "r", "--video-id", "unknown", "--config", str(config)],
    )
    assert unknown.exit_code != 0 and "Unknown video_id" in unknown.output


def test_mutability_checks_and_failed_metadata_import(tmp_path: Path, monkeypatch):
    config, settings = _config(tmp_path)
    settings.paths.runs_root = tmp_path / "runs"
    run_root = settings.paths.runs_root / "r"
    registry_path = run_root / "registry" / "run_registry.sqlite3"
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.touch()
    media_path = run_root / "media" / "media.jsonl"
    media_path.parent.mkdir(parents=True, exist_ok=True)
    media_path.write_text("", encoding="utf-8")
    monkeypatch.setattr(cli, "_settings", lambda path: (settings, {}))
    mutable_checks = []

    class FakeRegistry:
        def __init__(self, path): pass
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def assert_run_mutable(self, run_id): mutable_checks.append(run_id)

    monkeypatch.setattr(cli, "RunRegistry", FakeRegistry)
    failed_import = SimpleNamespace(
        report=SimpleNamespace(status="failed", model_dump=lambda mode: {"status": "failed"}),
        records=[], artifact_paths=[],
    )
    monkeypatch.setattr(cli, "import_organizer_youtube_metadata", lambda *args, **kwargs: failed_import)
    monkeypatch.setattr(cli, "consolidate_metadata_artifacts", lambda root: [])
    monkeypatch.setattr(cli, "invalidate_text_index_cache", lambda root: None)
    imported = runner.invoke(cli.app, ["import-organizer-metadata", "--run-id", "r", "--config", str(config)])
    assert imported.exit_code == 2

    monkeypatch.setattr(
        cli,
        "build_evidence_catalog",
        lambda *args, **kwargs: CatalogBuildResult(
            run_root / "evidence.sqlite3", run_root / "manifest.json", False, {}
        ),
    )
    assert runner.invoke(cli.app, ["build-evidence-catalog", "--run-id", "r", "--config", str(config)]).exit_code == 0

    text_result = SimpleNamespace(
        manifest=SimpleNamespace(model_dump=lambda mode: {}), reused=False,
        requested_adapter="local_bm25", selected_adapter="local_bm25", degraded_reason=None,
    )
    monkeypatch.setattr(cli, "build_text_index", lambda *args, **kwargs: text_result)
    assert runner.invoke(cli.app, ["build-text-index", "--run-id", "r", "--config", str(config)]).exit_code == 0
    assert mutable_checks == ["r", "r", "r"]
