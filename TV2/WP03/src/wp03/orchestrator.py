"""CPU-testable build orchestration for one visual model."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Protocol, Sequence

import numpy as np

from .artifacts import sha256_file, validate_embedding_array, write_embedding_map_parquet, write_embedding_shard, write_json_atomically
from .contracts import EmbeddingMapRecord, FrameRecord, utc_now_iso8601
from .corpus import resolve_keyframe
from .digests import ContentValidationMode, compute_corpus_digests, compute_shard_input_digest
from .index import build_flat_ip_index


class ImageEncoder(Protocol):
    def encode_images(self, image_paths: tuple[Path, ...]) -> np.ndarray: ...


@dataclass(frozen=True)
class BuildRequest:
    run_id: str
    model_key: str
    model_version: str
    data_root: Path
    artifact_root: Path
    corpus: Sequence[FrameRecord]
    shard_size: int
    compatibility_fingerprint: str = ""
    resume: bool = False
    content_validation: ContentValidationMode = ContentValidationMode.STRICT
    config_digest: str = "default"
    frames_input_digest: str = "inline-corpus"
    code_version: str = ""
    expected_dimension: int | None = None
    rrf_k: int = 60
    dedup_window_ms: int | None = 1_000


@dataclass(frozen=True)
class BuildSummary:
    status: str
    degraded: bool
    run_id: str
    models: Mapping[str, Mapping[str, object]]

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "1.0.0",
            "status": self.status,
            "degraded": self.degraded,
            "wp03_run_id": self.run_id,
            "models": {model: dict(result) for model, result in self.models.items()},
            "finished_at_utc": utc_now_iso8601(),
        }


def _chunks(items: Sequence[FrameRecord], size: int) -> Sequence[Sequence[FrameRecord]]:
    return tuple(items[index : index + size] for index in range(0, len(items), size))


def build_model_artifacts(request: BuildRequest, encoder: ImageEncoder) -> dict[str, object]:
    """Build complete artifacts for one model using an encoder boundary."""

    if request.shard_size <= 0:
        raise ValueError("shard_size must be positive")
    if request.rrf_k <= 0:
        raise ValueError("rrf_k must be positive")
    if request.dedup_window_ms is not None and request.dedup_window_ms < 0:
        raise ValueError("dedup_window_ms must be non-negative or null")
    embeddings_dir = request.artifact_root / "embeddings" / request.model_key
    maps_dir = request.artifact_root / "embedding_maps"
    indexes_dir = request.artifact_root / "indexes"
    manifests_dir = request.artifact_root / "manifests"
    for directory in (embeddings_dir, maps_dir, indexes_dir, manifests_dir):
        directory.mkdir(parents=True, exist_ok=True)

    manifest_path = manifests_dir / f"{request.model_key}.json"
    existing_manifest: dict[str, object] | None = None
    if manifest_path.is_file():
        try:
            existing_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("existing model manifest cannot be read") from exc
        if existing_manifest.get("status") == "complete" and not request.resume:
            raise ValueError("completed run exists; pass resume=True to rebuild or reuse it")

    corpus_digests = compute_corpus_digests(
        request.corpus,
        request.data_root,
        request.content_validation,
        request.frames_input_digest,
        None,
    )
    reusable_manifest = (
        existing_manifest
        if existing_manifest
        and existing_manifest.get("status") == "complete"
        and existing_manifest.get("model_version") == request.model_version
        and existing_manifest.get("compatibility_fingerprint") == request.compatibility_fingerprint
        and existing_manifest.get("config_digest") == request.config_digest
        and existing_manifest.get("content_validation") == request.content_validation.value
        else None
    )
    previous_shards = {
        int(item["shard_id"]): item
        for item in reusable_manifest.get("shards", [])
    } if reusable_manifest else {}

    shard_paths: list[Path] = []
    mapping_records: list[EmbeddingMapRecord] = []
    dimension = int(reusable_manifest["embedding_dim"]) if reusable_manifest else None
    vector_id = 0
    shard_metadata: list[dict[str, object]] = []
    for shard_id, records in enumerate(_chunks(tuple(request.corpus), request.shard_size)):
        shard_input_digest = compute_shard_input_digest(
            records, request.data_root, request.content_validation, request.frames_input_digest, None
        )
        image_paths = tuple(resolve_keyframe(request.data_root, record) for record in records)
        shard_path = embeddings_dir / f"shard-{shard_id:05d}.npy"
        previous = previous_shards.get(shard_id)
        reuse = (
            previous is not None
            and previous.get("shard_input_digest") == shard_input_digest
            and previous.get("dtype") == "float32"
            and shard_path.is_file()
            and sha256_file(shard_path) == previous.get("output_sha256")
        )
        if reuse:
            vectors = np.asarray(np.load(shard_path), dtype=np.float32)
        else:
            vectors = np.asarray(encoder.encode_images(image_paths), dtype=np.float32)
        if vectors.ndim != 2:
            raise ValueError("encoder must return a two-dimensional array")
        if dimension is None:
            dimension = vectors.shape[1]
        if request.expected_dimension is not None and dimension != request.expected_dimension:
            raise ValueError(
                f"encoder dimension {dimension} does not match configured dimension {request.expected_dimension}"
            )
        validate_embedding_array(vectors, expected_rows=len(records), expected_dim=dimension)
        output_sha256 = sha256_file(shard_path) if reuse else write_embedding_shard(shard_path, vectors)
        shard_paths.append(shard_path)
        shard_metadata.append(
            {
                "shard_id": shard_id,
                "record_start": vector_id,
                "record_end": vector_id + len(records) - 1,
                "shard_input_digest": shard_input_digest,
                "output_sha256": output_sha256,
                "shape": list(vectors.shape),
                "dtype": "float32",
            }
        )
        for record in records:
            mapping_records.append(
                EmbeddingMapRecord(
                    schema_version="1.0.0",
                    preprocess_run_id=record.preprocess_run_id,
                    model_name=request.model_key,
                    model_version=request.model_version,
                    vector_id=vector_id,
                    video_id=record.video_id,
                    frame_id=record.frame_id,
                    keyframe_seq=record.keyframe_seq,
                    timestamp_ms=record.timestamp_ms,
                    embedding_dim=dimension,
                    vector_dtype="float32",
                    l2_normalized=True,
                    keyframe_path=record.keyframe_path.replace("\\", "/"),
                    created_at_utc=utc_now_iso8601(),
                )
            )
            vector_id += 1
    if dimension is None:
        raise ValueError("corpus must not be empty")
    mapping_path = maps_dir / f"{request.model_key}.parquet"
    mapping_sha256 = write_embedding_map_parquet(mapping_path, mapping_records)
    index_path = indexes_dir / f"{request.model_key}.faiss"
    index_report = build_flat_ip_index(shard_paths, dimension, index_path)
    manifest: dict[str, object] = {
        "schema_version": "1.0.0",
        "status": "complete",
        "wp03_run_id": request.run_id,
        "model_key": request.model_key,
        "model_version": request.model_version,
        "compatibility_fingerprint": request.compatibility_fingerprint,
        "config_digest": request.config_digest,
        "code_version": request.code_version,
        "content_validation": request.content_validation.value,
        "frames_input_digest": corpus_digests.frames_jsonl_digest,
        "corpus_content_digest": corpus_digests.corpus_content_digest,
        "content_integrity_source": corpus_digests.content_integrity_source,
        "preprocess_run_id": request.corpus[0].preprocess_run_id,
        "vector_count": vector_id,
        "embedding_dim": dimension,
        "mapping_sha256": mapping_sha256,
        "index_sha256": index_report.index_sha256,
        "rrf_k": request.rrf_k,
        "dedup_window_ms": request.dedup_window_ms,
        "shards": shard_metadata,
        "finished_at_utc": utc_now_iso8601(),
    }
    write_json_atomically(manifest_path, manifest)
    return manifest


def build_all_models(
    requests: Sequence[BuildRequest], encoders: Mapping[str, ImageEncoder]
) -> BuildSummary:
    """Build models independently and preserve successful artifacts after a peer fails."""

    if not requests:
        raise ValueError("at least one model build request is required")
    run_ids = {request.run_id for request in requests}
    roots = {request.artifact_root.resolve() for request in requests}
    if len(run_ids) != 1 or len(roots) != 1:
        raise ValueError("all model requests must share one run_id and artifact_root")
    models: dict[str, dict[str, object]] = {}
    for request in requests:
        encoder = encoders.get(request.model_key)
        if encoder is None:
            models[request.model_key] = {"status": "failed", "error": "encoder is not configured"}
            continue
        try:
            models[request.model_key] = build_model_artifacts(request, encoder)
        except (OSError, ValueError, RuntimeError) as exc:
            models[request.model_key] = {"status": "failed", "error": str(exc)}
    completed = sum(result.get("status") == "complete" for result in models.values())
    summary = BuildSummary(
        status="complete" if completed else "failed",
        degraded=completed != len(requests),
        run_id=requests[0].run_id,
        models=models,
    )
    reports_dir = requests[0].artifact_root / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    write_json_atomically(reports_dir / "build-summary.json", summary.to_dict())
    return summary
