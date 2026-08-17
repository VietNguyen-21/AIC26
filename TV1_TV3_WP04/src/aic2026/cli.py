"""CLI for the TV1 preprocessing + TV3 WP04 evidence release."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Optional

import typer

from . import __version__
from .api import create_app
from .batch_manifest import download_entries, manifest_entries
from .benchmarking import benchmark_concurrent_queries, write_benchmark_report
from .config import Settings, load_settings
from .contracts import (
    ASRSegment,
    ASRSegmentManifest,
    ASRVideoMetrics,
    AudioRecord,
    CorpusManifestRecord,
    FrameRecord,
    MediaRecord,
    MetadataImportReport,
    MetadataRecord,
    ModuleArtifactManifest,
    ObjectDetection,
    ObjectFrameManifest,
    ObjectVideoMetrics,
    OCRDetection,
    OCRFrameManifest,
    OCRVideoMetrics,
    OriginalFrameIndexRecord,
    PreprocessingRun,
    RunValidationReport,
    SearchCandidate,
    ShotRecord,
    TemporalASRLinkRecord,
    TemporalFrameRecord,
    TemporalWindowRecord,
    TextIndexManifest,
    VADSegmentRecord,
)
from .frame_index import pyav_available
from .evidence_catalog import build_evidence_catalog, validate_evidence_catalog
from .keyframes import benchmark_keyframe_strategies
from .metadata import consolidate_metadata_artifacts, import_organizer_youtube_metadata
from .model_certification import certify_models
from .text_index import build_text_index, invalidate_text_index_cache, validate_text_index_artifacts
from .preprocessing import TV4_CANDIDATE_POLICY, run_preprocessing
from .registry import RunRegistry
from .release import audit_release, package_release
from .utils import read_json, read_jsonl, sha256_file, write_json
from .validation import compute_artifact_state_sha256, validate_run

app = typer.Typer(no_args_is_help=True, help="AIC2026 TV1 preprocessing + TV3 WP04 evidence pipeline")


def _settings(path: Path) -> tuple[Settings, dict]:
    return load_settings(path)


@app.command()
def doctor(config: Path = typer.Option(Path("configs/default.yaml"), "--config")):
    settings, _ = _settings(config)
    checks = {
        "package_version": __version__,
        "ffmpeg": shutil.which("ffmpeg"),
        "ffprobe": shutil.which("ffprobe"),
        "pyav": pyav_available(),
        "frame_index_backend": settings.media.frame_index_backend,
        "ffmpeg_fallback": settings.media.allow_ffmpeg_decode_fallback,
        "autoshoot_repo": (
            str(settings.keyframes.autoshoot_repo_root)
            if settings.keyframes.autoshoot_repo_root
            else None
        ),
        "autoshoot_checkpoint": (
            str(settings.keyframes.autoshoot_checkpoint_path)
            if settings.keyframes.autoshoot_checkpoint_path
            else None
        ),
        "ocr_adapter": settings.ocr.adapter,
        "asr_adapter": settings.asr.adapter,
        "vad_adapter": settings.asr.vad_adapter,
        "object_adapter": settings.object.adapter,
        "text_index_adapter": settings.text_index.adapter,
    }
    checks["production_ready"] = bool(
        checks["ffmpeg"]
        and checks["ffprobe"]
        and checks["pyav"]
        and settings.media.frame_index_backend == "pyav"
    )
    typer.echo(json.dumps(checks, ensure_ascii=False, indent=2))


@app.command("inspect-batch-manifest")
def inspect_batch_manifest(manifest: Path = typer.Option(..., "--manifest")):
    typer.echo(json.dumps(manifest_entries(manifest), ensure_ascii=False, indent=2))


@app.command("download-batch-videos")
def download_batch_videos(
    manifest: Path = typer.Option(..., "--manifest"),
    output: Path = typer.Option(Path("external_data/videos"), "--output"),
    prefix: str = typer.Option("Videos_", "--prefix"),
):
    paths = download_entries(manifest_entries(manifest), output, include_prefix=prefix)
    typer.echo(json.dumps([str(path) for path in paths], ensure_ascii=False, indent=2))


@app.command()
def preprocess(
    input: Path = typer.Option(..., "--input"),
    run_id: str = typer.Option(..., "--run-id"),
    config: Path = typer.Option(Path("configs/default.yaml"), "--config"),
    retry_failed: bool = typer.Option(True, "--retry-failed/--no-retry-failed"),
    recompute: list[str] = typer.Option([], "--recompute"),
):
    settings, raw = _settings(config)
    result = run_preprocessing(
        source=input,
        run_id=run_id,
        settings=settings,
        raw_config=raw,
        repository_root=Path.cwd(),
        retry_failed=retry_failed,
        recompute_modules=recompute,
    )
    typer.echo(
        json.dumps(
            {
                "run": result.run.model_dump(mode="json"),
                "executed_modules": result.executed_modules,
                "skipped_modules": result.skipped_modules,
                "errors": result.errors,
                "registry_summary": result.registry_summary,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    if result.errors:
        raise typer.Exit(code=2)


@app.command("import-organizer-metadata")
def import_organizer_metadata_command(
    run_id: str = typer.Option(..., "--run-id"),
    config: Path = typer.Option(Path("configs/default.yaml"), "--config"),
):
    settings, _ = _settings(config)
    run_root = Path(settings.paths.runs_root) / run_id
    registry_path = run_root / "registry" / "run_registry.sqlite3"
    if registry_path.is_file():
        with RunRegistry(registry_path) as registry:
            registry.assert_run_mutable(run_id)
    media = [MediaRecord.model_validate(row) for row in read_jsonl(run_root / "media" / "media.jsonl")]
    result = import_organizer_youtube_metadata(run_id, run_root, media, settings.metadata)
    combined = consolidate_metadata_artifacts(run_root)
    invalidate_text_index_cache(run_root)
    typer.echo(json.dumps({
        "report": result.report.model_dump(mode="json"),
        "records": len(result.records),
        "combined_records": len(combined),
        "artifact_paths": [str(path) for path in result.artifact_paths],
    }, ensure_ascii=False, indent=2))
    if result.report.status == "failed":
        raise typer.Exit(code=2)


@app.command("build-evidence-catalog")
def build_evidence_catalog_command(
    run_id: str = typer.Option(..., "--run-id"),
    config: Path = typer.Option(Path("configs/default.yaml"), "--config"),
    force: bool = typer.Option(False, "--force"),
):
    settings, _ = _settings(config)
    run_root = Path(settings.paths.runs_root) / run_id
    registry_path = run_root / "registry" / "run_registry.sqlite3"
    if registry_path.is_file():
        with RunRegistry(registry_path) as registry:
            registry.assert_run_mutable(run_id)
    result = build_evidence_catalog(
        run_root,
        database_name=settings.evidence_catalog.database_name,
        force=force,
    )
    typer.echo(
        json.dumps(
            {
                "reused": result.reused,
                "counts": result.counts,
                "database_path": str(result.database_path),
                "manifest_path": str(result.manifest_path),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


@app.command("evidence-catalog-status")
def evidence_catalog_status_command(
    run_id: str = typer.Option(..., "--run-id"),
    config: Path = typer.Option(Path("configs/default.yaml"), "--config"),
):
    settings, _ = _settings(config)
    run_root = Path(settings.paths.runs_root) / run_id
    typer.echo(json.dumps(validate_evidence_catalog(run_root), ensure_ascii=False, indent=2))


@app.command("build-text-index")
def build_text_index_command(
    run_id: str = typer.Option(..., "--run-id"),
    config: Path = typer.Option(Path("configs/default.yaml"), "--config"),
    force: bool = typer.Option(False, "--force"),
):
    settings, _ = _settings(config)
    run_root = Path(settings.paths.runs_root) / run_id
    registry_path = run_root / "registry" / "run_registry.sqlite3"
    if registry_path.is_file():
        with RunRegistry(registry_path) as registry:
            registry.assert_run_mutable(run_id)
    result = build_text_index(run_id, run_root, settings, force=force)
    typer.echo(json.dumps({
        "manifest": result.manifest.model_dump(mode="json"),
        "reused": result.reused,
        "requested_adapter": result.requested_adapter,
        "selected_adapter": result.selected_adapter,
        "degraded_reason": result.degraded_reason,
    }, ensure_ascii=False, indent=2))


@app.command("text-index-status")
def text_index_status_command(
    run_id: str = typer.Option(..., "--run-id"),
    config: Path = typer.Option(Path("configs/default.yaml"), "--config"),
):
    settings, _ = _settings(config)
    run_root = Path(settings.paths.runs_root) / run_id
    payload = validate_text_index_artifacts(run_root, settings, verify_source_checksums=True)
    typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))


@app.command("reload-text-index")
def reload_text_index_command(
    run_id: str = typer.Option(..., "--run-id"),
    config: Path = typer.Option(Path("configs/default.yaml"), "--config"),
):
    settings, _ = _settings(config)
    run_root = Path(settings.paths.runs_root) / run_id
    invalidate_text_index_cache(run_root)
    payload = validate_text_index_artifacts(run_root, settings, verify_source_checksums=True)
    typer.echo(json.dumps({"reloaded": True, **payload}, ensure_ascii=False, indent=2))


@app.command("certify-tv3-models")
def certify_tv3_models_command(
    config: Path = typer.Option(Path("configs/local/competition.yaml"), "--config"),
    output: Path = typer.Option(
        Path("reports/verification/TV3_MODEL_CERTIFICATION.json"), "--output"
    ),
    load_models: bool = typer.Option(False, "--load-models/--inspect-only"),
):
    settings, _ = _settings(config)
    report = certify_models(settings, load_models=load_models, output_path=output)
    typer.echo(json.dumps(report, ensure_ascii=False, indent=2))
    if load_models and not report["acceptance"]["competition_ready"]:
        raise typer.Exit(code=5)


@app.command("benchmark-tv3")
def benchmark_tv3_command(
    run_id: str = typer.Option(..., "--run-id"),
    queries: Path = typer.Option(..., "--queries"),
    config: Path = typer.Option(Path("configs/default.yaml"), "--config"),
    output: Path = typer.Option(
        Path("reports/verification/TV3_ENGINEERING_BENCHMARK.json"), "--output"
    ),
    workers: int = typer.Option(4, "--workers", min=1, max=128),
    repetitions: int = typer.Option(3, "--repetitions", min=1, max=1000),
    top_k: int = typer.Option(20, "--top-k", min=1, max=100),
):
    settings, _ = _settings(config)
    run_root = Path(settings.paths.runs_root) / run_id
    query_rows = [
        line.strip()
        for line in queries.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    report = benchmark_concurrent_queries(
        run_id,
        run_root,
        settings,
        query_rows,
        workers=workers,
        repetitions=repetitions,
        top_k=top_k,
    )
    write_benchmark_report(output, report)
    typer.echo(json.dumps({"output": str(output), **report}, ensure_ascii=False, indent=2))


@app.command("verify-tv3-handoff")
def verify_tv3_handoff_command(
    run_id: str = typer.Option(..., "--run-id"),
    config: Path = typer.Option(Path("configs/default.yaml"), "--config"),
    require_stable: bool = typer.Option(
        False,
        "--require-stable",
        help=(
            "Require a sealed stable run and stable handoff manifest. "
            "Use this for the final production handoff to TV4."
        ),
    ),
):
    settings, _ = _settings(config)
    run_root = Path(settings.paths.runs_root) / run_id

    catalog = validate_evidence_catalog(run_root, verify_sources=True)
    text = validate_text_index_artifacts(
        run_root, settings, verify_source_checksums=True
    )

    handoff_path = run_root / "handoff_tv1_tv3.json"
    required = {
        "handoff": handoff_path.is_file(),
        "ocr": (run_root / "ocr" / "ocr.jsonl").is_file(),
        "asr": (run_root / "asr" / "asr.jsonl").is_file(),
        "objects": (run_root / "objects" / "objects.jsonl").is_file(),
        "metadata": (run_root / "metadata" / "metadata.jsonl").is_file(),
    }

    handoff = read_json(handoff_path) if handoff_path.is_file() else {}
    handoff_run_id_match = handoff.get("preprocess_run_id") == run_id
    candidate_policy = handoff.get("candidate_policy")
    handoff_policy_valid = candidate_policy == TV4_CANDIDATE_POLICY
    handoff_contract_valid = bool(
        required["handoff"] and handoff_run_id_match and handoff_policy_valid
    )

    catalog_valid = bool(catalog.get("valid"))
    text_index_valid = bool(text.get("valid"))

    registry_path = run_root / "registry" / "run_registry.sqlite3"
    run_status: str | None = None
    registry_artifact_state_sha256 = ""
    if registry_path.is_file():
        with RunRegistry(registry_path) as registry:
            run_record = registry.get_run(run_id)
        if run_record is not None:
            run_status = str(run_record.get("status") or "")
            stable_details = run_record.get("details", {}).get("stable", {})
            if isinstance(stable_details, dict):
                registry_artifact_state_sha256 = str(
                    stable_details.get("artifact_state_sha256") or ""
                )

    handoff_status = str(handoff.get("status") or "") if handoff else None
    handoff_artifact_state_sha256 = (
        str(handoff.get("artifact_state_sha256") or "") if handoff else ""
    )
    handoff_artifact_state_valid = (
        len(handoff_artifact_state_sha256) == 64
        and all(char in "0123456789abcdef" for char in handoff_artifact_state_sha256.lower())
    )
    stable_artifact_state_match = (
        handoff_artifact_state_valid
        and registry_artifact_state_sha256 == handoff_artifact_state_sha256
    )
    stable_ok = (
        not require_stable
        or (
            run_status == "stable"
            and handoff_status == "stable"
            and stable_artifact_state_match
        )
    )

    compatible = (
        all(required.values())
        and handoff_contract_valid
        and catalog_valid
        and text_index_valid
        and stable_ok
    )

    payload = {
        "run_id": run_id,
        "required_artifacts": required,
        "handoff_contract_valid": handoff_contract_valid,
        "handoff_run_id_match": handoff_run_id_match,
        "handoff_policy_valid": handoff_policy_valid,
        "evidence_catalog": catalog,
        "evidence_catalog_valid": catalog_valid,
        "text_index": text,
        "text_index_valid": text_index_valid,
        "run_status": run_status,
        "handoff_status": handoff_status,
        "handoff_artifact_state_valid": handoff_artifact_state_valid,
        "stable_artifact_state_match": stable_artifact_state_match,
        "stable_required": require_stable,
        "stable_ok": stable_ok,
        "compatible": compatible,
    }
    typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
    if not compatible:
        raise typer.Exit(code=6)


@app.command("registry-status")
def registry_status(
    run_id: str = typer.Option(..., "--run-id"),
    config: Path = typer.Option(Path("configs/default.yaml"), "--config"),
):
    settings, _ = _settings(config)
    path = Path(settings.paths.runs_root) / run_id / "registry" / "run_registry.sqlite3"
    if not path.is_file():
        raise typer.BadParameter(f"Registry not found: {path}")
    with RunRegistry(path) as registry:
        payload = {
            "run": registry.get_run(run_id),
            "summary": registry.summarize_run(run_id),
            "modules": registry.list_status(run_id),
        }
    typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))


@app.command("validate-run")
def validate_run_command(
    run_id: str = typer.Option(..., "--run-id"),
    config: Path = typer.Option(Path("configs/default.yaml"), "--config"),
):
    settings, _ = _settings(config)
    report, path = validate_run(run_id, settings)
    typer.echo(
        json.dumps(
            {
                "report_path": str(path),
                **report.model_dump(mode="json"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    if not report.g0_pass:
        raise typer.Exit(code=3)


@app.command("mark-stable")
def mark_stable_command(
    run_id: str = typer.Option(..., "--run-id"),
    config: Path = typer.Option(Path("configs/default.yaml"), "--config"),
):
    settings, _ = _settings(config)
    run_root = Path(settings.paths.runs_root) / run_id
    registry_path = run_root / "registry" / "run_registry.sqlite3"
    with RunRegistry(registry_path) as registry:
        current = registry.get_run(run_id)
        if current and current["status"] == "stable":
            typer.echo(json.dumps({"run_id": run_id, "status": "already_stable"}, indent=2))
            return
    # Fresh validation is mandatory; stale reports are never accepted.
    report, report_path = validate_run(run_id, settings)
    if not report.stable_eligible:
        typer.echo(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2))
        raise typer.BadParameter(
            "Run is not production-stable eligible; resolve P0 and production blockers"
        )
    current_state = compute_artifact_state_sha256(run_root)
    if current_state != report.artifact_state_sha256:
        raise typer.BadParameter("Artifacts changed after validation")
    report_file_sha = sha256_file(report_path)

    # Update human-readable manifests before sealing the registry.  These files
    # are excluded from the module artifact-state hash and are never changed
    # again after the stable transition.
    manifest_path = run_root / "manifest.json"
    manifest = PreprocessingRun.model_validate(read_json(manifest_path))
    manifest.status = "stable"
    manifest.validation_report_path = str(report_path)
    write_json(manifest_path, manifest.model_dump(mode="json"))
    handoff_path = run_root / "handoff_tv1_tv3.json"
    if not handoff_path.is_file():
        handoff_path = run_root / "handoff_tv1.json"
    if handoff_path.is_file():
        handoff = read_json(handoff_path)
        handoff["status"] = "stable"
        handoff["validation_report_path"] = str(report_path)
        handoff["artifact_state_sha256"] = current_state
        write_json(handoff_path, handoff)

    with RunRegistry(registry_path) as registry:
        registry.mark_stable(
            run_id,
            validation_report_path=report_path,
            validation_report_sha256=report_file_sha,
            artifact_state_sha256=current_state,
        )
    typer.echo(
        json.dumps(
            {
                "run_id": run_id,
                "status": "stable",
                "validation_report": str(report_path),
                "artifact_state_sha256": current_state,
            },
            indent=2,
        )
    )


@app.command("benchmark-keyframes")
def benchmark_keyframes_command(
    run_id: str = typer.Option(..., "--run-id"),
    video_id: str = typer.Option(..., "--video-id"),
    config: Path = typer.Option(Path("configs/default.yaml"), "--config"),
):
    settings, _ = _settings(config)
    run_root = Path(settings.paths.runs_root) / run_id
    media_rows = [
        MediaRecord.model_validate(row)
        for row in read_jsonl(run_root / "media" / "media.jsonl")
    ]
    media = next((row for row in media_rows if row.video_id == video_id), None)
    if media is None:
        raise typer.BadParameter(f"Unknown video_id: {video_id}")
    report = benchmark_keyframe_strategies(media, run_root, settings)
    typer.echo(json.dumps(report, ensure_ascii=False, indent=2))


@app.command()
def serve(
    run_id: str = typer.Option(..., "--run-id"),
    config: Path = typer.Option(Path("configs/default.yaml"), "--config"),
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(8000, "--port"),
):
    import uvicorn

    uvicorn.run(create_app(run_id, config), host=host, port=port)


SCHEMA_MODELS = [
    PreprocessingRun,
    CorpusManifestRecord,
    MediaRecord,
    AudioRecord,
    OriginalFrameIndexRecord,
    ShotRecord,
    FrameRecord,
    OCRDetection,
    OCRFrameManifest,
    OCRVideoMetrics,
    VADSegmentRecord,
    ASRSegment,
    ASRSegmentManifest,
    ASRVideoMetrics,
    ObjectDetection,
    ObjectFrameManifest,
    ObjectVideoMetrics,
    MetadataRecord,
    MetadataImportReport,
    TextIndexManifest,
    TemporalFrameRecord,
    TemporalASRLinkRecord,
    TemporalWindowRecord,
    SearchCandidate,
    ModuleArtifactManifest,
    RunValidationReport,
]


@app.command("export-schemas")
def export_schemas(
    output: Path = typer.Option(Path("configs/schemas"), "--output")
):
    output.mkdir(parents=True, exist_ok=True)
    for model in SCHEMA_MODELS:
        write_json(output / f"{model.__name__}.schema.json", model.model_json_schema())
    write_json(output / "Settings.schema.json", Settings.model_json_schema())
    typer.echo(json.dumps({"output": str(output), "schemas": len(SCHEMA_MODELS) + 1}))


@app.command("release-audit")
def release_audit(root: Path = typer.Option(Path("."), "--root")):
    issues = audit_release(root)
    typer.echo(json.dumps(issues, ensure_ascii=False, indent=2))
    if issues:
        raise typer.Exit(code=4)


@app.command("release-package")
def release_package(
    root: Path = typer.Option(Path("."), "--root"),
    output: Path = typer.Option(..., "--output"),
):
    path = package_release(root, output)
    typer.echo(json.dumps({"output": str(path), "sha256": sha256_file(path)}, indent=2))


if __name__ == "__main__":
    app()
