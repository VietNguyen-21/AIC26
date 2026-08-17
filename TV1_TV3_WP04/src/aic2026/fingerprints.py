"""Deterministic fingerprints for TV1 preprocessing and TV3 WP04 modules.

Checkpoint hashes are intentionally recomputed from file contents on every call:
replacing a checkpoint at the same path must invalidate only the affected module.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Mapping

from .contracts import CorpusManifestRecord, FrameRecord
from .utils import sha256_file, stable_json_hash

MODULE_DEPENDENCIES: dict[str, tuple[str, ...]] = {
    "media_probe": ("ingest",),
    "frame_index": ("media_probe",),
    "decode_probe": ("frame_index",),
    "audio": ("media_probe",),
    "keyframes": ("frame_index", "decode_probe"),
    "ocr": ("keyframes",),
    "asr": ("audio",),
    "object": ("keyframes",),
    "technical_metadata": ("media_probe",),
    "metadata": ("technical_metadata",),
    "temporal": ("keyframes", "asr"),
    "text_index": ("ocr", "asr", "metadata"),
}


def _file_hash(path_value: str | Path | None) -> str | None:
    if path_value is None:
        return None
    path = Path(path_value)
    return sha256_file(path) if path.is_file() else None


def module_config_payload(module_name: str, settings: Any) -> dict[str, Any]:
    if module_name == "ingest":
        return settings.corpus.model_dump(mode="json")
    if module_name in {"media_probe", "frame_index", "decode_probe", "audio"}:
        payload = settings.media.model_dump(mode="json")
        if module_name == "media_probe":
            return {"ffprobe_timeout_seconds": payload["ffprobe_timeout_seconds"]}
        if module_name == "frame_index":
            return {
                "build_full_frame_index": payload["build_full_frame_index"],
                "frame_index_backend": payload["frame_index_backend"],
                "frame_index_timeout_seconds": payload["frame_index_timeout_seconds"],
                "pts_timestamp_tolerance_ms": payload.get("pts_timestamp_tolerance_ms"),
            }
        if module_name == "decode_probe":
            return {
                "decode_probe_points": payload["decode_probe_points"],
                "allow_ffmpeg_decode_fallback": payload["allow_ffmpeg_decode_fallback"],
            }
        return {
            "create_audio": payload["create_audio"],
            "audio_sample_rate_hz": payload["audio_sample_rate_hz"],
            "audio_duration_tolerance_ms": payload.get("audio_duration_tolerance_ms"),
        }
    if module_name == "keyframes":
        return settings.keyframes.model_dump(mode="json")
    if module_name == "ocr":
        return settings.ocr.model_dump(mode="json")
    if module_name == "asr":
        return settings.asr.model_dump(mode="json")
    if module_name == "object":
        return settings.object.model_dump(mode="json")
    if module_name in {"technical_metadata", "metadata"}:
        return settings.metadata.model_dump(mode="json")
    if module_name == "text_index":
        return settings.text_index.model_dump(mode="json")
    if module_name == "temporal":
        return {"schema": "temporal_registry_1.1.0"}
    return {}


def module_config_hash(module_name: str, settings: Any) -> str:
    return stable_json_hash(module_config_payload(module_name, settings))


def module_model_identity(module_name: str, settings: Any) -> dict[str, Any]:
    if module_name == "keyframes":
        checkpoint = settings.keyframes.autoshoot_checkpoint_path
        return {
            "shot_model": settings.keyframes.shot_model,
            "autoshoot_model_filename": settings.keyframes.autoshoot_model_filename,
            "autoshoot_checkpoint_sha256": _file_hash(checkpoint),
            "autoshoot_threshold": settings.keyframes.autoshoot_threshold,
            "autoshoot_min_loaded_parameter_ratio": settings.keyframes.autoshoot_min_loaded_parameter_ratio,
            "pyscenedetect_threshold": settings.keyframes.pyscenedetect_threshold,
        }

    if module_name == "ocr":
        return {
            "adapter": settings.ocr.adapter,
            "device": settings.ocr.device,
            "deep_solo_parseq_checkpoint_sha256": _file_hash(
                settings.ocr.deep_solo_parseq_checkpoint_path
            ),
            "deep_solo_parseq_command": settings.ocr.deep_solo_parseq_command,
        }
    if module_name == "asr":
        return {
            "adapter": settings.asr.adapter,
            "vad_adapter": settings.asr.vad_adapter,
            "device": settings.asr.device,
            "language": settings.asr.language,
            "chunkformer_checkpoint_sha256": _file_hash(
                settings.asr.chunkformer_checkpoint_path
            ),
            "chunkformer_command": settings.asr.chunkformer_command,
        }
    if module_name == "object":
        return {
            "adapter": settings.object.adapter,
            "device": str(settings.object.device),
            "rfdetr_model_name": settings.object.rfdetr_model_name,
            "rfdetr_checkpoint_sha256": _file_hash(settings.object.rfdetr_checkpoint_path),
        }
    return {}


def build_module_fingerprint(
    module_name: str,
    *,
    source_sha256: str,
    settings: Any,
    pipeline_version: str,
    dependency_fingerprints: Mapping[str, str] | None = None,
    extra: Mapping[str, Any] | None = None,
) -> str:
    return stable_json_hash(
        {
            "module_name": module_name,
            "pipeline_version": pipeline_version,
            "source_sha256": source_sha256,
            "config": module_config_payload(module_name, settings),
            "model": module_model_identity(module_name, settings),
            "dependencies": dict(sorted((dependency_fingerprints or {}).items())),
            "extra": dict(sorted((extra or {}).items())),
        }
    )


def canonical_manifest_payload(
    records: Iterable[CorpusManifestRecord],
) -> list[dict[str, Any]]:
    return sorted(
        (
            {
                "video_id": row.video_id,
                "source_archive": row.source_archive,
                "source_sha256": row.source_sha256,
                "file_size_bytes": row.file_size_bytes,
                "batch_id": row.batch_id,
                "duplicate_of_video_id": row.duplicate_of_video_id,
                "ingest_status": row.ingest_status,
            }
            for row in records
        ),
        key=lambda row: (row["video_id"], row["source_sha256"]),
    )


def source_manifest_hash(records: Iterable[CorpusManifestRecord]) -> str:
    return stable_json_hash(canonical_manifest_payload(records))


def frame_records_hash(frames: Iterable[FrameRecord]) -> str:
    payload = sorted(
        (
            {
                "video_id": row.video_id,
                "frame_id": row.frame_id,
                "timestamp_ms": row.timestamp_ms,
                "pts": row.pts,
                "time_base": row.time_base,
                "decode_index": row.decode_index,
                "keyframe_path": row.keyframe_path,
            }
            for row in frames
        ),
        key=lambda row: (row["video_id"], row["frame_id"]),
    )
    return stable_json_hash(payload)
