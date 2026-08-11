"""Dependency-aware orchestration for reproducible raw-video preprocessing runs."""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Generic, Iterable, TypeVar

from . import __version__
from .config import Settings
from .contracts import (
    AudioRecord,
    CorpusManifestRecord,
    FrameRecord,
    MediaRecord,
    ModuleArtifactManifest,
    PreprocessingRun,
)
from .fingerprints import (
    build_module_fingerprint,
    module_config_hash,
    module_model_identity,
    source_manifest_hash,
    frame_records_hash,
)
from .frame_index import load_original_frame_index
from .evidence_catalog import build_evidence_catalog
from .ingest import ingest
from .keyframes import extract_keyframes
from .media import (
    decode_probe,
    ensure_original_frame_index,
    extract_audio,
    infer_variable_frame_rate,
    probe_media,
    write_media_records,
)
from .metadata import (
    consolidate_metadata_artifacts,
    import_organizer_youtube_metadata,
    metadata_source_fingerprint,
    write_technical_metadata,
)
from .objects import (
    ObjectAdapterResolution,
    cleanup_object_video,
    consolidate_object_artifacts,
    load_object_video_result,
    make_object_adapter,
    run_object_video,
)
from .ocr import (
    OCRAdapterResolution,
    cleanup_ocr_video,
    consolidate_ocr_artifacts,
    load_ocr_video_result,
    make_ocr_adapter,
    run_ocr_video,
)
from .asr import (
    ASRAdapterResolution,
    VADAdapterResolution,
    cleanup_asr_video,
    clear_consolidated_asr_artifacts,
    consolidate_asr_artifacts,
    load_asr_video_result,
    make_asr_adapter,
    make_vad_adapter,
    run_asr_video,
)
from .registry import RunRegistry, save_artifact_manifest
from .temporal import build_temporal_registry
from .text_index import build_text_index
from .utils import (
    artifact_checksums,
    read_json,
    read_jsonl,
    remove_tree,
    sha256_file,
    stable_json_hash,
    utcnow_iso,
    write_json,
    write_jsonl,
)

T = TypeVar("T")


TV4_CANDIDATE_POLICY = {
    "ocr": "exact_source_frame_submittable",
    "asr": "requires_temporal_resolution_before_submit",
    "metadata": "video_soft_boost_only_not_submittable",
    "object": "exact_source_frame_soft_constraint_submittable",
}


@dataclass
class ModuleResult(Generic[T]):
    value: T | None
    fingerprint: str
    executed: bool
    reason: str
    error: str | None = None


@dataclass
class PreprocessResult:
    run: PreprocessingRun
    registry_summary: dict[str, Any]
    errors: list[dict[str, str]]
    executed_modules: int
    skipped_modules: int


def _git_commit(repository_root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repository_root,
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def _cache_path(run_root: Path, video_id: str, name: str) -> Path:
    return run_root / "registry" / "cache" / video_id / f"{name}.json"


def _read_model(path: Path, model_type):
    if not path.exists():
        return None
    return model_type.model_validate(read_json(path))


def _write_model(path: Path, value: Any) -> None:
    write_json(path, value.model_dump(mode="json"))


def _artifact_details(
    run_root: Path,
    paths: Iterable[str | Path],
    *,
    manifest_path: Path,
    record_count: int | None,
    reason: str,
) -> dict[str, Any]:
    checksums = artifact_checksums(paths, run_root)
    return {
        "artifact_paths": sorted(checksums),
        "artifact_checksums": checksums,
        "artifact_manifest_path": manifest_path.relative_to(run_root).as_posix(),
        "record_count": record_count,
        "decision_reason": reason,
    }


def _module_manifest(
    *,
    run_id: str,
    video_id: str,
    module_name: str,
    fingerprint: str,
    source_sha256: str,
    settings: Settings,
    paths: Iterable[str | Path],
    run_root: Path,
    record_count: int | None,
    started_at: str,
) -> tuple[ModuleArtifactManifest, Path, dict[str, Any]]:
    checksums = artifact_checksums(paths, run_root)
    model_identity = module_model_identity(module_name, settings)
    manifest = ModuleArtifactManifest(
        preprocess_run_id=run_id,
        video_id=video_id,
        module_name=module_name,
        module_version=__version__,
        status="completed",
        fingerprint=fingerprint,
        config_sha256=module_config_hash(module_name, settings),
        source_sha256=source_sha256,
        model_name=str(
            model_identity.get("baseline_model")
            or model_identity.get("adapter")
            or model_identity.get("shot_model")
        )
        if model_identity
        else None,
        model_version=stable_json_hash(model_identity) if model_identity else None,
        artifact_paths=sorted(checksums),
        artifact_checksums=checksums,
        record_count=record_count,
        started_at_utc=started_at,
        finished_at_utc=utcnow_iso(),
    )
    manifest_path = save_artifact_manifest(run_root, manifest)
    details = _artifact_details(
        run_root,
        paths,
        manifest_path=manifest_path,
        record_count=record_count,
        reason="executed",
    )
    return manifest, manifest_path, details


def _execute_module(
    *,
    registry: RunRegistry,
    run_root: Path,
    run_id: str,
    video_id: str,
    module_name: str,
    fingerprint: str,
    source_sha256: str,
    settings: Settings,
    retry_failed: bool,
    recompute: bool,
    loader: Callable[[], T | None],
    runner: Callable[[], T],
    artifacts: Callable[[T], Iterable[str | Path]],
    record_count: Callable[[T], int | None] = lambda value: None,
    cleanup: Callable[[], None] | None = None,
) -> ModuleResult[T]:
    decision = registry.decide(
        run_id,
        video_id,
        module_name,
        fingerprint,
        run_root=run_root,
        retry_failed=retry_failed,
        recompute=recompute,
    )
    if not decision.should_run:
        try:
            value = loader()
        except Exception:
            value = None
        return ModuleResult(value, fingerprint, False, decision.reason)

    with registry.module_lock(
        run_root,
        video_id,
        module_name,
        stale_after_seconds=settings.runtime.lock_timeout_seconds,
    ):
        # Another process could have completed the module while this process was
        # waiting for the lock, so make the decision again inside the lock.
        decision = registry.decide(
            run_id,
            video_id,
            module_name,
            fingerprint,
            run_root=run_root,
            retry_failed=retry_failed,
            recompute=recompute,
        )
        if not decision.should_run:
            try:
                value = loader()
            except Exception:
                value = None
            return ModuleResult(value, fingerprint, False, decision.reason)
        if cleanup is not None:
            cleanup()
        started_at = utcnow_iso()
        registry.begin_module(
            run_id,
            video_id,
            module_name,
            fingerprint,
            details={"decision_reason": decision.reason},
        )
        try:
            value = runner()
            paths = list(artifacts(value))
            _, _, details = _module_manifest(
                run_id=run_id,
                video_id=video_id,
                module_name=module_name,
                fingerprint=fingerprint,
                source_sha256=source_sha256,
                settings=settings,
                paths=paths,
                run_root=run_root,
                record_count=record_count(value),
                started_at=started_at,
            )
            registry.complete_module(
                run_id, video_id, module_name, fingerprint, details=details
            )
            return ModuleResult(value, fingerprint, True, decision.reason)
        except Exception as exc:
            registry.fail_module(
                run_id,
                video_id,
                module_name,
                fingerprint,
                exc,
                details={"decision_reason": decision.reason},
            )
            return ModuleResult(
                None,
                fingerprint,
                True,
                decision.reason,
                error=f"{type(exc).__name__}: {exc}",
            )


def _module_recompute(module_name: str, recompute_modules: set[str]) -> bool:
    return "all" in recompute_modules or module_name in recompute_modules


def _load_manifest_records(path: Path) -> list[CorpusManifestRecord]:
    return [CorpusManifestRecord.model_validate(row) for row in read_jsonl(path)]


def _prepare_corpus_manifest(
    source: Path, run_root: Path, settings: Settings
) -> list[CorpusManifestRecord]:
    """Ingest a directory/archive using TV1 archive limits and collision-safe IDs."""
    manifest_path = run_root / "corpus_manifest.jsonl"
    state_path = run_root / "registry" / "source_input.json"
    kwargs = {
        "batch_id": settings.corpus.batch_id,
        "video_id_rule": settings.corpus.video_id_rule,
        "max_archive_members": settings.corpus.max_archive_members,
        "max_archive_uncompressed_bytes": settings.corpus.max_archive_uncompressed_bytes,
        "max_archive_compression_ratio": settings.corpus.max_archive_compression_ratio,
    }
    if source.is_file() and source.suffix.lower() == ".zip":
        archive_sha = sha256_file(source)
        if state_path.exists() and manifest_path.exists():
            state = read_json(state_path)
            extracted = run_root / "extracted"
            if state.get("archive_sha256") == archive_sha and extracted.exists():
                return _load_manifest_records(manifest_path)
        remove_tree(run_root / "extracted")
        rows = ingest(source, run_root, workspace=run_root / "extracted", **kwargs)
        write_json(
            state_path,
            {
                "source": str(source.resolve()),
                "archive_sha256": archive_sha,
                "created_at_utc": utcnow_iso(),
            },
        )
        return rows
    return ingest(source, run_root, **kwargs)


def _mark_ingest_records(
    registry: RunRegistry,
    run_root: Path,
    run_id: str,
    records: list[CorpusManifestRecord],
    settings: Settings,
) -> dict[str, str]:
    output: dict[str, str] = {}
    for record in records:
        fingerprint = build_module_fingerprint(
            "ingest",
            source_sha256=record.source_sha256,
            settings=settings,
            pipeline_version=__version__,
            extra={
                "video_id": record.video_id,
                "ingest_status": record.ingest_status,
                "file_size_bytes": record.file_size_bytes,
            },
        )
        output[record.video_id] = fingerprint
        cache_path = _cache_path(run_root, record.video_id, "ingest")
        decision = registry.decide(
            run_id,
            record.video_id,
            "ingest",
            fingerprint,
            run_root=run_root,
            retry_failed=True,
            recompute=False,
        )
        if not decision.should_run:
            continue
        with registry.module_lock(
            run_root,
            record.video_id,
            "ingest",
            stale_after_seconds=settings.runtime.lock_timeout_seconds,
        ):
            decision = registry.decide(
                run_id,
                record.video_id,
                "ingest",
                fingerprint,
                run_root=run_root,
                retry_failed=True,
                recompute=False,
            )
            if not decision.should_run:
                continue
            registry.begin_module(
                run_id, record.video_id, "ingest", fingerprint,
                details={"decision_reason": decision.reason},
            )
            try:
                _write_model(cache_path, record)
                checksums = artifact_checksums([cache_path], run_root)
                manifest = ModuleArtifactManifest(
                    preprocess_run_id=run_id,
                    video_id=record.video_id,
                    module_name="ingest",
                    module_version=__version__,
                    status="completed",
                    fingerprint=fingerprint,
                    config_sha256=module_config_hash("ingest", settings),
                    source_sha256=record.source_sha256,
                    artifact_paths=sorted(checksums),
                    artifact_checksums=checksums,
                    record_count=1,
                    started_at_utc=record.created_at_utc,
                    finished_at_utc=utcnow_iso(),
                )
                manifest_path = save_artifact_manifest(run_root, manifest)
                details = _artifact_details(
                    run_root,
                    [cache_path],
                    manifest_path=manifest_path,
                    record_count=1,
                    reason=decision.reason,
                )
                registry.complete_module(
                    run_id, record.video_id, "ingest", fingerprint, details=details
                )
            except Exception as exc:
                registry.fail_module(
                    run_id, record.video_id, "ingest", fingerprint, exc
                )
                raise
    return output


def _cleanup_frame_index(run_root: Path, video_id: str) -> None:
    for path in (run_root / "frame_indexes").glob(f"{video_id}.*"):
        path.unlink(missing_ok=True)
    _cache_path(run_root, video_id, "media").unlink(missing_ok=True)


def _cleanup_keyframes(run_root: Path, video_id: str) -> None:
    remove_tree(run_root / "keyframes" / video_id)
    remove_tree(run_root / "thumbnails" / video_id)
    for root in (run_root / "mappings", run_root / "shots"):
        for path in root.glob(f"{video_id}.*"):
            path.unlink(missing_ok=True)
    report = run_root / "reports" / "keyframes" / f"{video_id}.json"
    report.unlink(missing_ok=True)


def _load_frames(run_root: Path, video_id: str) -> list[FrameRecord] | None:
    path = run_root / "mappings" / f"{video_id}.jsonl"
    if not path.exists():
        return None
    return [FrameRecord.model_validate(row) for row in read_jsonl(path)]


def run_preprocessing(
    *,
    source: str | Path,
    run_id: str,
    settings: Settings,
    raw_config: dict[str, Any],
    repository_root: str | Path = ".",
    retry_failed: bool = True,
    recompute_modules: Iterable[str] = (),
) -> PreprocessResult:
    """Execute the dependency-aware preprocessing DAG for one immutable run identifier."""
    source = Path(source)
    runs_root = Path(settings.paths.runs_root)
    run_root = runs_root / run_id
    run_root.mkdir(parents=True, exist_ok=True)
    # Explicit recompute requests override otherwise valid registry resume decisions.
    recompute_set = {item.strip() for item in recompute_modules if item.strip()}
    started_at = utcnow_iso()
    errors: list[dict[str, str]] = []
    executed_modules = 0
    skipped_modules = 0

    with RunRegistry(run_root / "registry" / "run_registry.sqlite3") as registry:
        registry.assert_run_mutable(run_id)
        manifest = _prepare_corpus_manifest(source, run_root, settings)
        manifest_sha = source_manifest_hash(manifest)
        config_sha = stable_json_hash(raw_config)
        existing_run = registry.get_run(run_id)
        effective_started = existing_run["started_at"] if existing_run else started_at
        registry.register_run(
            run_id,
            status="running",
            source_manifest_sha256=manifest_sha,
            config_sha256=config_sha,
            details={"source": str(source.resolve())},
            started_at=effective_started,
        )
        ingest_fingerprints = _mark_ingest_records(
            registry, run_root, run_id, manifest, settings
        )
        accepted = [row for row in manifest if row.ingest_status == "accepted"]

        media_by_video: dict[str, MediaRecord] = {}
        audio_by_video: dict[str, AudioRecord] = {}
        frames_by_video: dict[str, list[FrameRecord]] = {}
        decode_reports: dict[str, list[dict[str, Any]]] = {}
        ocr_resolution: OCRAdapterResolution | None = None
        ocr_initialization_error: str | None = None
        if settings.ocr.enabled:
            try:
                ocr_resolution = make_ocr_adapter(settings.ocr)
            except Exception as exc:
                ocr_initialization_error = f"{type(exc).__name__}: {exc}"

        asr_resolution: ASRAdapterResolution | None = None
        vad_resolution: VADAdapterResolution | None = None
        asr_initialization_error: str | None = None
        if settings.asr.enabled:
            try:
                asr_resolution = make_asr_adapter(settings.asr)
                vad_resolution = make_vad_adapter(settings.asr)
            except Exception as exc:
                asr_initialization_error = f"{type(exc).__name__}: {exc}"

        object_resolution: ObjectAdapterResolution | None = None
        object_initialization_error: str | None = None
        if settings.object.enabled:
            try:
                object_resolution = make_object_adapter(settings.object)
            except Exception as exc:
                object_initialization_error = f"{type(exc).__name__}: {exc}"

        # Each module fingerprint includes its upstream dependencies to prevent stale reuse.
        fingerprints: dict[str, dict[str, str]] = {
            row.video_id: {"ingest": ingest_fingerprints[row.video_id]}
            for row in accepted
        }

        for record in accepted:
            video_id = record.video_id
            source_sha = record.source_sha256
            module_fps = fingerprints[video_id]

            media_probe_cache = _cache_path(run_root, video_id, "media_probe")
            media_cache = _cache_path(run_root, video_id, "media")
            media_fp = build_module_fingerprint(
                "media_probe",
                source_sha256=source_sha,
                settings=settings,
                pipeline_version=__version__,
                dependency_fingerprints={"ingest": module_fps["ingest"]},
            )
            module_fps["media_probe"] = media_fp
            media_result = _execute_module(
                registry=registry,
                run_root=run_root,
                run_id=run_id,
                video_id=video_id,
                module_name="media_probe",
                fingerprint=media_fp,
                source_sha256=source_sha,
                settings=settings,
                retry_failed=retry_failed,
                recompute=_module_recompute("media_probe", recompute_set),
                loader=lambda path=media_probe_cache: _read_model(path, MediaRecord),
                runner=lambda row=record: probe_media(
                    row, run_id, settings.media.ffprobe_timeout_seconds
                ),
                artifacts=lambda value, path=media_probe_cache: (
                    _write_model(path, value) or [path]
                ),
                record_count=lambda value: 1,
                cleanup=lambda path=media_probe_cache: path.unlink(missing_ok=True),
            )
            executed_modules += int(media_result.executed)
            skipped_modules += int(not media_result.executed)
            if media_result.error or media_result.value is None:
                errors.append(
                    {
                        "video_id": video_id,
                        "module": "media_probe",
                        "error": media_result.error or media_result.reason,
                    }
                )
                continue
            media_item = media_result.value

            frame_fp = build_module_fingerprint(
                "frame_index",
                source_sha256=source_sha,
                settings=settings,
                pipeline_version=__version__,
                dependency_fingerprints={"media_probe": media_fp},
            )
            module_fps["frame_index"] = frame_fp

            def build_frame_index(item: MediaRecord = media_item) -> MediaRecord:
                item.original_frame_index_path = None
                item.frame_index_backend = None
                path = ensure_original_frame_index(
                    item,
                    run_root,
                    backend=settings.media.frame_index_backend,
                    timeout=settings.media.frame_index_timeout_seconds,
                )
                records = load_original_frame_index(path)
                item.frame_count = len(records)
                item.is_variable_frame_rate = infer_variable_frame_rate(records)
                item.duration_ms = max(item.duration_ms, records[-1].timestamp_ms)
                _write_model(media_cache, item)
                return item

            frame_result = _execute_module(
                registry=registry,
                run_root=run_root,
                run_id=run_id,
                video_id=video_id,
                module_name="frame_index",
                fingerprint=frame_fp,
                source_sha256=source_sha,
                settings=settings,
                retry_failed=retry_failed,
                recompute=_module_recompute("frame_index", recompute_set),
                loader=lambda path=media_cache: _read_model(path, MediaRecord),
                runner=build_frame_index,
                artifacts=lambda value: [
                    value.original_frame_index_path,
                    run_root / "frame_indexes" / f"{video_id}.manifest.json",
                    run_root / "frame_indexes" / f"{video_id}.parquet",
                    media_cache,
                ],
                record_count=lambda value: value.frame_count,
                cleanup=lambda: _cleanup_frame_index(run_root, video_id),
            )
            executed_modules += int(frame_result.executed)
            skipped_modules += int(not frame_result.executed)
            if frame_result.error or frame_result.value is None:
                errors.append(
                    {
                        "video_id": video_id,
                        "module": "frame_index",
                        "error": frame_result.error or frame_result.reason,
                    }
                )
                continue
            media_item = frame_result.value
            media_by_video[video_id] = media_item

            decode_path = run_root / "reports" / "decode_probe" / f"{video_id}.json"
            decode_fp = build_module_fingerprint(
                "decode_probe",
                source_sha256=source_sha,
                settings=settings,
                pipeline_version=__version__,
                dependency_fingerprints={"frame_index": frame_fp},
            )
            module_fps["decode_probe"] = decode_fp

            def run_decode(item: MediaRecord = media_item) -> list[dict[str, Any]]:
                report = decode_probe(
                    item,
                    settings.media.decode_probe_points,
                    frame_index_path=item.original_frame_index_path,
                    backend="auto",
                    allow_ffmpeg_fallback=settings.media.allow_ffmpeg_decode_fallback,
                )
                write_json(decode_path, report)
                return report

            decode_result = _execute_module(
                registry=registry,
                run_root=run_root,
                run_id=run_id,
                video_id=video_id,
                module_name="decode_probe",
                fingerprint=decode_fp,
                source_sha256=source_sha,
                settings=settings,
                retry_failed=retry_failed,
                recompute=_module_recompute("decode_probe", recompute_set),
                loader=lambda path=decode_path: read_json(path) if path.exists() else None,
                runner=run_decode,
                artifacts=lambda value: [decode_path],
                record_count=len,
                cleanup=lambda path=decode_path: path.unlink(missing_ok=True),
            )
            executed_modules += int(decode_result.executed)
            skipped_modules += int(not decode_result.executed)
            if decode_result.error:
                errors.append(
                    {"video_id": video_id, "module": "decode_probe", "error": decode_result.error}
                )
            elif decode_result.value is not None:
                decode_reports[video_id] = decode_result.value

            if settings.media.create_audio:
                audio_cache = _cache_path(run_root, video_id, "audio")
                audio_fp = build_module_fingerprint(
                    "audio",
                    source_sha256=source_sha,
                    settings=settings,
                    pipeline_version=__version__,
                    dependency_fingerprints={"media_probe": media_fp},
                )
                module_fps["audio"] = audio_fp

                def run_audio(item: MediaRecord = media_item) -> AudioRecord:
                    result = extract_audio(
                        item, run_root / "audio", settings.media.audio_sample_rate_hz
                    )
                    if result.status == "failed":
                        raise RuntimeError(f"Audio extraction failed for {item.video_id}")
                    _write_model(audio_cache, result)
                    return result

                audio_result = _execute_module(
                    registry=registry,
                    run_root=run_root,
                    run_id=run_id,
                    video_id=video_id,
                    module_name="audio",
                    fingerprint=audio_fp,
                    source_sha256=source_sha,
                    settings=settings,
                    retry_failed=retry_failed,
                    recompute=_module_recompute("audio", recompute_set),
                    loader=lambda path=audio_cache: _read_model(path, AudioRecord),
                    runner=run_audio,
                    artifacts=lambda value: [
                        audio_cache,
                        value.audio_path if value.audio_path else audio_cache,
                    ],
                    record_count=lambda value: 1,
                    cleanup=lambda: (
                        (run_root / "audio" / f"{video_id}.wav").unlink(missing_ok=True),
                        audio_cache.unlink(missing_ok=True),
                    ),
                )
                executed_modules += int(audio_result.executed)
                skipped_modules += int(not audio_result.executed)
                if audio_result.error:
                    errors.append(
                        {"video_id": video_id, "module": "audio", "error": audio_result.error}
                    )
                elif audio_result.value is not None:
                    audio_by_video[video_id] = audio_result.value
            else:
                disabled_fp = build_module_fingerprint(
                    "audio",
                    source_sha256=source_sha,
                    settings=settings,
                    pipeline_version=__version__,
                    dependency_fingerprints={"media_probe": media_fp},
                )
                module_fps["audio"] = disabled_fp
                registry.skip_module(
                    run_id, video_id, "audio", disabled_fp, "disabled_by_config"
                )

            asr_fp = build_module_fingerprint(
                "asr",
                source_sha256=source_sha,
                settings=settings,
                pipeline_version=__version__,
                dependency_fingerprints={"audio": module_fps.get("audio", "missing")},
                extra={
                    "selected_adapter": (
                        asr_resolution.selected_adapter if asr_resolution else None
                    ),
                    "adapter_version": (
                        asr_resolution.adapter.version if asr_resolution else None
                    ),
                    "selected_vad_adapter": (
                        vad_resolution.selected_adapter if vad_resolution else None
                    ),
                    "vad_adapter_version": (
                        vad_resolution.adapter.version if vad_resolution else None
                    ),
                    "audio_sha256": (
                        audio_by_video.get(video_id).audio_sha256
                        if audio_by_video.get(video_id) is not None
                        else None
                    ),
                },
            )
            module_fps["asr"] = asr_fp
            if not settings.asr.enabled:
                registry.skip_module(
                    run_id, video_id, "asr", asr_fp, "disabled_by_config"
                )
            elif audio_by_video.get(video_id) is None:
                registry.skip_module(
                    run_id, video_id, "asr", asr_fp, "dependency_audio_unavailable"
                )
            elif asr_resolution is None or vad_resolution is None:
                error_text = asr_initialization_error or "ASR/VAD adapter unavailable"
                registry.begin_module(
                    run_id,
                    video_id,
                    "asr",
                    asr_fp,
                    details={"decision_reason": "adapter_initialization_failed"},
                )
                registry.fail_module(
                    run_id,
                    video_id,
                    "asr",
                    asr_fp,
                    RuntimeError(error_text),
                    details={"decision_reason": "adapter_initialization_failed"},
                )
                errors.append(
                    {"video_id": video_id, "module": "asr", "error": error_text}
                )
            else:
                force_asr = _module_recompute("asr", recompute_set)
                asr_result = _execute_module(
                    registry=registry,
                    run_root=run_root,
                    run_id=run_id,
                    video_id=video_id,
                    module_name="asr",
                    fingerprint=asr_fp,
                    source_sha256=source_sha,
                    settings=settings,
                    retry_failed=retry_failed,
                    recompute=force_asr,
                    loader=lambda video_id=video_id: load_asr_video_result(
                        run_root, video_id
                    ),
                    runner=lambda item=media_item, audio=audio_by_video[video_id], ar=asr_resolution, vr=vad_resolution: run_asr_video(
                        item,
                        audio,
                        run_root,
                        ar.adapter,
                        vr.adapter,
                        settings.asr,
                        asr_resolution=ar,
                        vad_resolution=vr,
                    ),
                    artifacts=lambda value: value.artifact_paths,
                    record_count=lambda value: len(value.segments),
                    cleanup=lambda video_id=video_id, force_asr=force_asr: cleanup_asr_video(
                        run_root,
                        video_id,
                        preserve_segment_cache=not force_asr,
                    ),
                )
                executed_modules += int(asr_result.executed)
                skipped_modules += int(not asr_result.executed)
                if asr_result.error:
                    errors.append(
                        {
                            "video_id": video_id,
                            "module": "asr",
                            "error": asr_result.error,
                        }
                    )

            keyframe_fp = build_module_fingerprint(
                "keyframes",
                source_sha256=source_sha,
                settings=settings,
                pipeline_version=__version__,
                dependency_fingerprints={
                    "frame_index": frame_fp,
                    "decode_probe": decode_fp,
                },
            )
            module_fps["keyframes"] = keyframe_fp
            mapping_path = run_root / "mappings" / f"{video_id}.jsonl"

            keyframe_result = _execute_module(
                registry=registry,
                run_root=run_root,
                run_id=run_id,
                video_id=video_id,
                module_name="keyframes",
                fingerprint=keyframe_fp,
                source_sha256=source_sha,
                settings=settings,
                retry_failed=retry_failed,
                recompute=_module_recompute("keyframes", recompute_set),
                loader=lambda video_id=video_id: _load_frames(run_root, video_id),
                runner=lambda item=media_item: extract_keyframes(item, run_root, settings),
                artifacts=lambda value: [
                    mapping_path,
                    run_root / "mappings" / f"{video_id}.parquet",
                    run_root / "shots" / f"{video_id}.jsonl",
                    run_root / "shots" / f"{video_id}.parquet",
                    run_root / "reports" / "keyframes" / f"{video_id}.json",
                    run_root / "keyframes" / video_id,
                    run_root / "thumbnails" / video_id,
                ],
                record_count=len,
                cleanup=lambda: _cleanup_keyframes(run_root, video_id),
            )
            executed_modules += int(keyframe_result.executed)
            skipped_modules += int(not keyframe_result.executed)
            if keyframe_result.error or keyframe_result.value is None:
                errors.append(
                    {
                        "video_id": video_id,
                        "module": "keyframes",
                        "error": keyframe_result.error or keyframe_result.reason,
                    }
                )
            else:
                frames_by_video[video_id] = keyframe_result.value

                ocr_fp = build_module_fingerprint(
                    "ocr",
                    source_sha256=source_sha,
                    settings=settings,
                    pipeline_version=__version__,
                    dependency_fingerprints={"keyframes": keyframe_fp},
                    extra={
                        "frame_records_hash": frame_records_hash(keyframe_result.value),
                        "selected_adapter": (
                            ocr_resolution.selected_adapter if ocr_resolution else None
                        ),
                        "adapter_version": (
                            ocr_resolution.adapter.version if ocr_resolution else None
                        ),
                    },
                )
                module_fps["ocr"] = ocr_fp
                if not settings.ocr.enabled:
                    registry.skip_module(
                        run_id, video_id, "ocr", ocr_fp, "disabled_by_config"
                    )
                elif ocr_resolution is None:
                    error_text = ocr_initialization_error or "OCR adapter unavailable"
                    registry.begin_module(
                        run_id,
                        video_id,
                        "ocr",
                        ocr_fp,
                        details={"decision_reason": "adapter_initialization_failed"},
                    )
                    registry.fail_module(
                        run_id,
                        video_id,
                        "ocr",
                        ocr_fp,
                        RuntimeError(error_text),
                        details={"decision_reason": "adapter_initialization_failed"},
                    )
                    errors.append(
                        {"video_id": video_id, "module": "ocr", "error": error_text}
                    )
                else:
                    force_ocr = _module_recompute("ocr", recompute_set)
                    ocr_result = _execute_module(
                        registry=registry,
                        run_root=run_root,
                        run_id=run_id,
                        video_id=video_id,
                        module_name="ocr",
                        fingerprint=ocr_fp,
                        source_sha256=source_sha,
                        settings=settings,
                        retry_failed=retry_failed,
                        recompute=force_ocr,
                        loader=lambda video_id=video_id: load_ocr_video_result(
                            run_root, video_id
                        ),
                        runner=lambda frames=keyframe_result.value, resolution=ocr_resolution: run_ocr_video(
                            frames,
                            run_root,
                            resolution.adapter,
                            settings.ocr,
                            resolution=resolution,
                        ),
                        artifacts=lambda value: value.artifact_paths,
                        record_count=lambda value: len(value.detections),
                        cleanup=lambda video_id=video_id, force_ocr=force_ocr: cleanup_ocr_video(
                            run_root,
                            video_id,
                            preserve_frame_cache=not force_ocr,
                        ),
                    )
                    executed_modules += int(ocr_result.executed)
                    skipped_modules += int(not ocr_result.executed)
                    if ocr_result.error:
                        errors.append(
                            {
                                "video_id": video_id,
                                "module": "ocr",
                                "error": ocr_result.error,
                            }
                        )

                object_fp = build_module_fingerprint(
                    "object",
                    source_sha256=source_sha,
                    settings=settings,
                    pipeline_version=__version__,
                    dependency_fingerprints={"keyframes": keyframe_fp},
                    extra={
                        "frame_records_hash": frame_records_hash(keyframe_result.value),
                        "selected_adapter": (
                            object_resolution.selected_adapter if object_resolution else None
                        ),
                        "adapter_version": (
                            object_resolution.adapter.version if object_resolution else None
                        ),
                    },
                )
                module_fps["object"] = object_fp
                if not settings.object.enabled:
                    registry.skip_module(
                        run_id, video_id, "object", object_fp, "disabled_by_config"
                    )
                elif object_resolution is None:
                    error_text = object_initialization_error or "Object adapter unavailable"
                    registry.begin_module(
                        run_id,
                        video_id,
                        "object",
                        object_fp,
                        details={"decision_reason": "adapter_initialization_failed"},
                    )
                    registry.fail_module(
                        run_id,
                        video_id,
                        "object",
                        object_fp,
                        RuntimeError(error_text),
                        details={"decision_reason": "adapter_initialization_failed"},
                    )
                    errors.append(
                        {"video_id": video_id, "module": "object", "error": error_text}
                    )
                else:
                    force_object = _module_recompute("object", recompute_set)
                    object_result = _execute_module(
                        registry=registry,
                        run_root=run_root,
                        run_id=run_id,
                        video_id=video_id,
                        module_name="object",
                        fingerprint=object_fp,
                        source_sha256=source_sha,
                        settings=settings,
                        retry_failed=retry_failed,
                        recompute=force_object,
                        loader=lambda video_id=video_id: load_object_video_result(
                            run_root, video_id
                        ),
                        runner=lambda frames=keyframe_result.value, resolution=object_resolution: run_object_video(
                            frames,
                            run_root,
                            resolution.adapter,
                            settings.object,
                            resolution=resolution,
                        ),
                        artifacts=lambda value: value.artifact_paths,
                        record_count=lambda value: len(value.detections),
                        cleanup=lambda video_id=video_id, force_object=force_object: cleanup_object_video(
                            run_root,
                            video_id,
                            preserve_frame_cache=not force_object,
                        ),
                    )
                    executed_modules += int(object_result.executed)
                    skipped_modules += int(not object_result.executed)
                    if object_result.error:
                        errors.append(
                            {
                                "video_id": video_id,
                                "module": "object",
                                "error": object_result.error,
                            }
                        )

        if settings.ocr.enabled and ocr_resolution is not None:
            consolidate_ocr_artifacts(run_root)
        if settings.object.enabled and object_resolution is not None:
            consolidate_object_artifacts(run_root)
        if settings.asr.enabled and asr_resolution is not None and vad_resolution is not None:
            consolidate_asr_artifacts(
                run_root,
                [row.video_id for row in accepted],
            )
        else:
            clear_consolidated_asr_artifacts(run_root)

        media_rows = [media_by_video[key] for key in sorted(media_by_video)]
        audio_rows = [audio_by_video[key] for key in sorted(audio_by_video)]
        all_frames = [
            frame
            for video_id in sorted(frames_by_video)
            for frame in frames_by_video[video_id]
        ]
        write_media_records(run_root, media_rows, audio_rows)
        write_json(run_root / "reports" / "decode_probe.json", decode_reports)
        write_jsonl(
            run_root / "frames.jsonl",
            [row.model_dump(mode="json") for row in all_frames],
        )

        # Temporal registry is a compact global artifact. It is rebuilt only if
        # at least one per-video temporal fingerprint changed or became invalid.
        temporal_candidates: list[tuple[CorpusManifestRecord, str]] = []
        for record in accepted:
            if record.video_id not in frames_by_video:
                dependency_fp = fingerprints[record.video_id].get("keyframes", "missing")
                asr_dependency_fp = fingerprints[record.video_id].get("asr", "missing")
                blocked_fp = build_module_fingerprint(
                    "temporal",
                    source_sha256=record.source_sha256,
                    settings=settings,
                    pipeline_version=__version__,
                    dependency_fingerprints={
                        "keyframes": dependency_fp,
                        "asr": asr_dependency_fp,
                    },
                )
                registry.skip_module(
                    run_id,
                    record.video_id,
                    "temporal",
                    blocked_fp,
                    "dependency_keyframes_unavailable",
                )
                continue
            keyframe_fp = fingerprints[record.video_id]["keyframes"]
            asr_dependency_fp = fingerprints[record.video_id].get("asr", "missing")
            temporal_fp = build_module_fingerprint(
                "temporal",
                source_sha256=record.source_sha256,
                settings=settings,
                pipeline_version=__version__,
                dependency_fingerprints={
                    "keyframes": keyframe_fp,
                    "asr": asr_dependency_fp,
                },
            )
            fingerprints[record.video_id]["temporal"] = temporal_fp
            decision = registry.decide(
                run_id,
                record.video_id,
                "temporal",
                temporal_fp,
                run_root=run_root,
                retry_failed=retry_failed,
                recompute=_module_recompute("temporal", recompute_set),
            )
            if decision.should_run:
                temporal_candidates.append((record, temporal_fp))
            else:
                skipped_modules += 1

        if temporal_candidates:
            with registry.module_lock(run_root, "__corpus__", "temporal"):
                for record, fp in temporal_candidates:
                    registry.begin_module(run_id, record.video_id, "temporal", fp)
                try:
                    temporal_rows = build_temporal_registry(
                        all_frames, run_root, media=media_rows
                    )
                    temporal_paths = [
                        run_root / "temporal" / "temporal_frames.jsonl",
                        run_root / "temporal" / "temporal_frames.parquet",
                        run_root / "temporal" / "shots.jsonl",
                        run_root / "temporal" / "shots.parquet",
                        run_root / "temporal" / "asr_links.jsonl",
                        run_root / "temporal" / "asr_links.parquet",
                        run_root / "temporal" / "manifest.json",
                    ]
                    for record in accepted:
                        if record.video_id not in frames_by_video:
                            continue
                        fp = fingerprints[record.video_id]["temporal"]
                        _, _, details = _module_manifest(
                            run_id=run_id,
                            video_id=record.video_id,
                            module_name="temporal",
                            fingerprint=fp,
                            source_sha256=record.source_sha256,
                            settings=settings,
                            paths=temporal_paths,
                            run_root=run_root,
                            record_count=sum(
                                row.video_id == record.video_id for row in temporal_rows
                            ),
                            started_at=utcnow_iso(),
                        )
                        registry.complete_module(
                            run_id, record.video_id, "temporal", fp, details=details
                        )
                        executed_modules += 1
                except Exception as exc:
                    for record, fp in temporal_candidates:
                        registry.fail_module(
                            run_id, record.video_id, "temporal", fp, exc
                        )
                        errors.append(
                            {
                                "video_id": record.video_id,
                                "module": "temporal",
                                "error": f"{type(exc).__name__}: {exc}",
                            }
                        )

        if settings.metadata.technical_enabled and media_rows:
            metadata_candidates: list[tuple[CorpusManifestRecord, str]] = []
            for record in accepted:
                if record.video_id not in media_by_video:
                    continue
                fp = build_module_fingerprint(
                    "technical_metadata",
                    source_sha256=record.source_sha256,
                    settings=settings,
                    pipeline_version=__version__,
                    dependency_fingerprints={
                        "media_probe": fingerprints[record.video_id]["media_probe"]
                    },
                    extra={"corpus_manifest_sha256": manifest_sha},
                )
                fingerprints[record.video_id]["technical_metadata"] = fp
                decision = registry.decide(
                    run_id,
                    record.video_id,
                    "technical_metadata",
                    fp,
                    run_root=run_root,
                    retry_failed=retry_failed,
                    recompute=_module_recompute("technical_metadata", recompute_set),
                )
                if decision.should_run:
                    metadata_candidates.append((record, fp))
                else:
                    skipped_modules += 1
            if metadata_candidates:
                with registry.module_lock(
                    run_root, "__corpus__", "technical_metadata"
                ):
                    for record, fp in metadata_candidates:
                        registry.begin_module(
                            run_id, record.video_id, "technical_metadata", fp
                        )
                    try:
                        write_technical_metadata(media_rows, run_root)
                        consolidate_metadata_artifacts(run_root)
                        metadata_path = run_root / "metadata" / "technical.jsonl"
                        for record in accepted:
                            if record.video_id not in media_by_video:
                                continue
                            fp = fingerprints[record.video_id]["technical_metadata"]
                            _, _, details = _module_manifest(
                                run_id=run_id,
                                video_id=record.video_id,
                                module_name="technical_metadata",
                                fingerprint=fp,
                                source_sha256=record.source_sha256,
                                settings=settings,
                                paths=[metadata_path],
                                run_root=run_root,
                                record_count=1,
                                started_at=utcnow_iso(),
                            )
                            registry.complete_module(
                                run_id,
                                record.video_id,
                                "technical_metadata",
                                fp,
                                details=details,
                            )
                            executed_modules += 1
                    except Exception as exc:
                        for record, fp in metadata_candidates:
                            registry.fail_module(
                                run_id, record.video_id, "technical_metadata", fp, exc
                            )
                            errors.append(
                                {
                                    "video_id": record.video_id,
                                    "module": "technical_metadata",
                                    "error": f"{type(exc).__name__}: {exc}",
                                }
                            )

        if settings.metadata.organizer_youtube_enabled and media_rows:
            organizer_root_fingerprint = metadata_source_fingerprint(
                settings.metadata.organizer_metadata_root,
                settings.metadata.organizer_metadata_globs,
            )
            metadata_candidates: list[tuple[CorpusManifestRecord, str]] = []
            for record in accepted:
                if record.video_id not in media_by_video:
                    continue
                fp = build_module_fingerprint(
                    "metadata",
                    source_sha256=record.source_sha256,
                    settings=settings,
                    pipeline_version=__version__,
                    dependency_fingerprints={
                        "technical_metadata": fingerprints[record.video_id].get(
                            "technical_metadata", "disabled"
                        )
                    },
                    extra={
                        "organizer_source_fingerprint": organizer_root_fingerprint,
                        "corpus_manifest_sha256": manifest_sha,
                    },
                )
                fingerprints[record.video_id]["metadata"] = fp
                decision = registry.decide(
                    run_id,
                    record.video_id,
                    "metadata",
                    fp,
                    run_root=run_root,
                    retry_failed=retry_failed,
                    recompute=_module_recompute("metadata", recompute_set),
                )
                if decision.should_run:
                    metadata_candidates.append((record, fp))
                else:
                    skipped_modules += 1
            if metadata_candidates:
                with registry.module_lock(
                    run_root,
                    "__corpus__",
                    "metadata",
                    stale_after_seconds=settings.runtime.lock_timeout_seconds,
                ):
                    for record, fp in metadata_candidates:
                        registry.begin_module(run_id, record.video_id, "metadata", fp)
                    try:
                        import_result = import_organizer_youtube_metadata(
                            run_id,
                            run_root,
                            media_rows,
                            settings.metadata,
                        )
                        combined = consolidate_metadata_artifacts(run_root)
                        metadata_paths = list(import_result.artifact_paths) + [
                            run_root / "metadata" / "metadata.jsonl",
                            run_root / "metadata" / "metadata.parquet",
                            run_root / "reports" / "metadata_summary.json",
                        ]
                        for record in accepted:
                            if record.video_id not in media_by_video:
                                continue
                            fp = fingerprints[record.video_id]["metadata"]
                            _, _, details = _module_manifest(
                                run_id=run_id,
                                video_id=record.video_id,
                                module_name="metadata",
                                fingerprint=fp,
                                source_sha256=record.source_sha256,
                                settings=settings,
                                paths=metadata_paths,
                                run_root=run_root,
                                record_count=sum(
                                    item.video_id == record.video_id
                                    and str(item.source) == "organizer_youtube"
                                    for item in combined
                                ),
                                started_at=utcnow_iso(),
                            )
                            registry.complete_module(
                                run_id, record.video_id, "metadata", fp, details=details
                            )
                            executed_modules += 1
                    except Exception as exc:
                        for record, fp in metadata_candidates:
                            registry.fail_module(run_id, record.video_id, "metadata", fp, exc)
                            errors.append(
                                {
                                    "video_id": record.video_id,
                                    "module": "metadata",
                                    "error": f"{type(exc).__name__}: {exc}",
                                }
                            )
        elif media_rows:
            consolidate_metadata_artifacts(run_root)

        if settings.evidence_catalog.enabled and settings.evidence_catalog.auto_build:
            try:
                catalog_result = build_evidence_catalog(
                    run_root,
                    database_name=settings.evidence_catalog.database_name,
                    force=bool(
                        recompute_set.intersection(
                            {"ocr", "asr", "object", "metadata", "technical_metadata", "evidence_catalog"}
                        )
                    ),
                )
                executed_modules += int(not catalog_result.reused)
                skipped_modules += int(catalog_result.reused)
                write_json(
                    run_root / "reports" / "evidence_catalog.json",
                    {
                        "status": "ready",
                        "reused": catalog_result.reused,
                        "counts": catalog_result.counts,
                        "database_path": str(catalog_result.database_path.relative_to(run_root)),
                        "created_at_utc": utcnow_iso(),
                    },
                )
            except Exception as exc:
                write_json(
                    run_root / "reports" / "evidence_catalog.json",
                    {
                        "status": "failed",
                        "error": f"{type(exc).__name__}: {exc}",
                        "fail_open": bool(settings.evidence_catalog.fail_open),
                        "created_at_utc": utcnow_iso(),
                    },
                )
                if not settings.evidence_catalog.fail_open:
                    errors.append(
                        {
                            "video_id": "__corpus__",
                            "module": "evidence_catalog",
                            "error": f"{type(exc).__name__}: {exc}",
                        }
                    )

        if settings.text_index.enabled:
            try:
                text_index_result = build_text_index(
                    run_id,
                    run_root,
                    settings,
                    force=_module_recompute("text_index", recompute_set),
                )
                executed_modules += int(not text_index_result.reused)
                skipped_modules += int(text_index_result.reused)
            except Exception as exc:
                write_json(
                    run_root / "reports" / "text_index.json",
                    {
                        "status": "failed",
                        "error": f"{type(exc).__name__}: {exc}",
                        "fail_open": bool(settings.text_index.fail_open),
                        "created_at_utc": utcnow_iso(),
                    },
                )
                if not settings.text_index.fail_open:
                    errors.append(
                        {
                            "video_id": "__corpus__",
                            "module": "text_index",
                            "error": f"{type(exc).__name__}: {exc}",
                        }
                    )

        status = "partial" if errors else "completed"
        finished_at = utcnow_iso()
        registry_summary = registry.summarize_run(run_id)
        registry.register_run(
            run_id,
            status=status,
            source_manifest_sha256=manifest_sha,
            config_sha256=config_sha,
            details={
                "source": str(source.resolve()),
                "errors": errors,
                "registry_summary": registry_summary,
            },
            started_at=effective_started,
            finished_at=finished_at,
        )
        run = PreprocessingRun(
            pipeline_version=__version__,
            preprocess_run_id=run_id,
            source_manifest_sha256=manifest_sha,
            config_sha256=config_sha,
            code_commit=_git_commit(Path(repository_root)),
            status=status,
            video_count=len(media_rows),
            keyframe_count=len(all_frames),
            started_at_utc=effective_started,
            finished_at_utc=finished_at,
            artifact_root=str(run_root),
            validation_report_path=str(run_root / "reports" / "validation.json"),
        )
        write_json(run_root / "manifest.json", run.model_dump(mode="json"))
        write_json(run_root / "config.snapshot.json", raw_config)
        write_json(
            run_root / "reports" / "validation.json",
            {
                "status": "not_run",
                "round": 6,
                "g0_pass": False,
                "note": "Run `aic validate-run --run-id <id>` before marking this run validated or stable.",
                "videos": len(media_rows),
                "keyframes": len(all_frames),
                "errors": errors,
            },
        )
        write_json(run_root / "reports" / "registry_summary.json", registry_summary)
        write_json(
            run_root / "handoff_tv1_tv3.json",
            {
                "schema_version": "1.0.0",
                "preprocess_run_id": run_id,
                "status": status,
                "source_manifest_sha256": manifest_sha,
                "config_sha256": config_sha,
                "video_count": len(media_rows),
                "keyframe_count": len(all_frames),
                "modalities": {
                    "ocr": bool(settings.ocr.enabled),
                    "asr": bool(settings.asr.enabled),
                    "object": bool(settings.object.enabled),
                    "metadata": bool(settings.metadata.technical_enabled or settings.metadata.organizer_youtube_enabled),
                    "text_index": bool(settings.text_index.enabled),
                },
                "candidate_policy": dict(TV4_CANDIDATE_POLICY),
                "created_at_utc": finished_at,
            },
        )
        return PreprocessResult(
            run=run,
            registry_summary=registry_summary,
            errors=errors,
            executed_modules=executed_modules,
            skipped_modules=skipped_modules,
        )
