"""Sequential visual search over completed WP03 artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Protocol, Sequence

import numpy as np
import pyarrow.parquet as pq
import faiss

from .artifacts import sha256_file
from .contracts import ContractError, SearchRequest, SearchResponse
from .fusion import RankedHit, diversify_visual_candidates, fuse_rrf
from .index import search_flat_ip_index


class SearchEncoder(Protocol):
    def encode_text(self, texts: tuple[str, ...]) -> np.ndarray: ...

    def compatibility_fingerprint(self) -> str: ...


class ImageSearchEncoder(SearchEncoder, Protocol):
    def encode_images(self, image_paths: Sequence[Path]) -> np.ndarray: ...


def search_visual(
    *,
    request: SearchRequest | None = None,
    artifact_root: Path,
    encoders: dict[str, SearchEncoder],
    candidate_k_per_model: int,
    hard_candidate_cap: int | None,
    query_id: str | None = None,
    query_text: str | None = None,
    event_index: int | None = None,
    requested_top_k: int | None = None,
    rrf_k: int = 60,
    dedup_window_ms: int | None = 1_000,
) -> SearchResponse:
    """Search usable model indexes one at a time and RRF their ranked hits."""

    if request is None:
        if query_id is None or query_text is None or requested_top_k is None:
            raise ContractError("request or legacy query fields are required")
        request = SearchRequest(
            query_id=query_id,
            task="KIS",
            query_text=query_text,
            question=None,
            events=(),
            filters={},
            limit=requested_top_k,
            language=None,
            session_id=None,
            event_index=event_index,
        )
    normalized_query = request.visual_query_text()
    return _search_embeddings(
        request=request,
        artifact_root=artifact_root,
        encoders=encoders,
        candidate_k_per_model=candidate_k_per_model,
        hard_candidate_cap=hard_candidate_cap,
        rrf_k=rrf_k,
        dedup_window_ms=dedup_window_ms,
        encode_query=lambda encoder: encoder.encode_text((normalized_query,)),
    )


def search_image(
    *,
    request: SearchRequest,
    image_paths: Sequence[Path],
    artifact_root: Path,
    encoders: dict[str, ImageSearchEncoder],
    candidate_k_per_model: int,
    hard_candidate_cap: int | None,
    rrf_k: int = 60,
    dedup_window_ms: int | None = 1_000,
) -> SearchResponse:
    """Retrieve frames from one or more reference images in each model's own space."""

    if not image_paths:
        raise ContractError("image_paths must not be empty")
    return _search_embeddings(
        request=request,
        artifact_root=artifact_root,
        encoders=encoders,
        candidate_k_per_model=candidate_k_per_model,
        hard_candidate_cap=hard_candidate_cap,
        rrf_k=rrf_k,
        dedup_window_ms=dedup_window_ms,
        encode_query=lambda encoder: encoder.encode_images(tuple(image_paths)),
    )


def _search_embeddings(
    *,
    request: SearchRequest,
    artifact_root: Path,
    encoders: dict[str, SearchEncoder],
    candidate_k_per_model: int,
    hard_candidate_cap: int | None,
    rrf_k: int,
    dedup_window_ms: int | None,
    encode_query: Callable[[SearchEncoder], np.ndarray],
) -> SearchResponse:
    requested_top_k = request.limit
    if requested_top_k <= 0 or candidate_k_per_model <= 0 or rrf_k <= 0:
        raise ContractError("requested_top_k, candidate_k_per_model and rrf_k must be positive")
    if dedup_window_ms is not None and dedup_window_ms < 0:
        raise ContractError("dedup_window_ms must be non-negative or null")
    requested_models = tuple(encoders)
    model_hits: dict[str, list[RankedHit]] = {}
    used_models: list[str] = []
    run_id: str | None = None
    preprocess_run_id: str | None = None
    for model_key, encoder in encoders.items():
        manifest_path = artifact_root / "manifests" / f"{model_key}.json"
        index_path = artifact_root / "indexes" / f"{model_key}.faiss"
        mapping_path = artifact_root / "embedding_maps" / f"{model_key}.parquet"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("status") != "complete":
            continue
        if sha256_file(index_path) != manifest.get("index_sha256"):
            raise ContractError(f"{model_key} index digest mismatch")
        if sha256_file(mapping_path) != manifest.get("mapping_sha256"):
            raise ContractError(f"{model_key} mapping digest mismatch")
        mapping = pq.read_table(mapping_path).to_pylist()
        index = faiss.read_index(str(index_path))
        if index.ntotal != len(mapping) or index.ntotal != manifest.get("vector_count"):
            raise ContractError(f"{model_key} index/map vector count mismatch")
        try:
            required_compatibility = str(manifest.get("compatibility_fingerprint", ""))
            fingerprint = getattr(encoder, "compatibility_fingerprint", None)
            if required_compatibility and (not callable(fingerprint) or fingerprint() != required_compatibility):
                continue
            query_vectors = np.asarray(encode_query(encoder), dtype=np.float32)
            if query_vectors.ndim != 2 or query_vectors.shape[0] == 0:
                raise ContractError("query encoder must return a non-empty matrix")
            query_vector = query_vectors.mean(axis=0)
            limit = min(len(mapping), max(requested_top_k, candidate_k_per_model))
            if hard_candidate_cap is not None:
                limit = min(limit, hard_candidate_cap)
            scores, ids = search_flat_ip_index(index_path, query_vector, limit)
        except (OSError, ValueError, ContractError):
            continue
        run_id = str(manifest["wp03_run_id"])
        preprocess_run_id = str(manifest["preprocess_run_id"])
        hits: list[RankedHit] = []
        for rank, (score, vector_id) in enumerate(zip(scores.tolist(), ids.tolist()), start=1):
            row = mapping[vector_id]
            hits.append(
                RankedHit(
                    vector_id=vector_id,
                    video_id=str(row["video_id"]),
                    frame_id=int(row["frame_id"]),
                    timestamp_ms=int(row["timestamp_ms"]),
                    keyframe_path=str(row["keyframe_path"]),
                    rank=rank,
                    similarity=float(score),
                )
            )
        model_hits[model_key] = hits
        used_models.append(model_key)
    if not used_models or run_id is None or preprocess_run_id is None:
        raise ContractError("no usable visual model")
    result = fuse_rrf(
        model_hits,
        query_id=request.query_id,
        event_index=request.event_index,
        preprocess_run_id=preprocess_run_id,
        limit=max(requested_top_k, candidate_k_per_model),
        rrf_k=rrf_k,
    )
    candidates = (
        result.candidates[:requested_top_k]
        if dedup_window_ms is None
        else diversify_visual_candidates(result.candidates, limit=requested_top_k, dedup_window_ms=dedup_window_ms)
    )
    return SearchResponse.create(
        query_id=request.query_id,
        wp03_run_id=run_id,
        preprocess_run_id=preprocess_run_id,
        requested_top_k=requested_top_k,
        candidate_k_per_model=candidate_k_per_model,
        hard_candidate_cap=hard_candidate_cap,
        models_requested=requested_models,
        models_used=tuple(used_models),
        candidates=candidates,
    )


def search_visual_batch(
    requests: Sequence[SearchRequest],
    *,
    artifact_root: Path,
    encoders: dict[str, SearchEncoder],
    candidate_k_per_model: int,
    hard_candidate_cap: int | None,
    rrf_k: int = 60,
    dedup_window_ms: int | None = 1_000,
) -> list[SearchResponse]:
    """Batch search multiple text queries across usable model indexes in one pass."""
    if not requests:
        return []
    for req in requests:
        if req.limit <= 0 or candidate_k_per_model <= 0 or rrf_k <= 0:
            raise ContractError("requested_top_k, candidate_k_per_model and rrf_k must be positive")
        if dedup_window_ms is not None and dedup_window_ms < 0:
            raise ContractError("dedup_window_ms must be non-negative or null")

    requested_models = tuple(encoders)
    num_queries = len(requests)
    per_request_hits: list[dict[str, list[RankedHit]]] = [{} for _ in range(num_queries)]
    used_models: list[str] = []
    run_id: str | None = None
    preprocess_run_id: str | None = None

    normalized_queries = tuple(req.visual_query_text() for req in requests)

    for model_key, encoder in encoders.items():
        manifest_path = artifact_root / "manifests" / f"{model_key}.json"
        index_path = artifact_root / "indexes" / f"{model_key}.faiss"
        mapping_path = artifact_root / "embedding_maps" / f"{model_key}.parquet"
        if not manifest_path.exists() or not index_path.exists() or not mapping_path.exists():
            continue
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("status") != "complete":
            continue
        if sha256_file(index_path) != manifest.get("index_sha256"):
            raise ContractError(f"{model_key} index digest mismatch")
        if sha256_file(mapping_path) != manifest.get("mapping_sha256"):
            raise ContractError(f"{model_key} mapping digest mismatch")
        mapping = pq.read_table(mapping_path).to_pylist()
        index = faiss.read_index(str(index_path))
        if index.ntotal != len(mapping) or index.ntotal != manifest.get("vector_count"):
            raise ContractError(f"{model_key} index/map vector count mismatch")
        try:
            required_compatibility = str(manifest.get("compatibility_fingerprint", ""))
            fingerprint = getattr(encoder, "compatibility_fingerprint", None)
            if required_compatibility and (not callable(fingerprint) or fingerprint() != required_compatibility):
                continue
            query_vectors = np.asarray(encoder.encode_text(normalized_queries), dtype=np.float32)
            if query_vectors.ndim != 2 or query_vectors.shape[0] != num_queries:
                raise ContractError("query encoder must return a matrix matching number of queries")

            for q_idx, req in enumerate(requests):
                q_vec = query_vectors[q_idx : q_idx + 1]
                norm = float(np.linalg.norm(q_vec))
                if not np.isfinite(q_vec).all() or norm == 0:
                    continue
                q_vec = q_vec / norm
                limit = min(len(mapping), max(req.limit, candidate_k_per_model))
                if hard_candidate_cap is not None:
                    limit = min(limit, hard_candidate_cap)
                count = min(limit, index.ntotal)
                scores, ids = index.search(q_vec, count)
                score_row, id_row = scores[0], ids[0]
                order = np.lexsort((id_row, -score_row))
                scores_sorted = score_row[order]
                ids_sorted = id_row[order]

                hits: list[RankedHit] = []
                for rank, (score, vector_id) in enumerate(zip(scores_sorted.tolist(), ids_sorted.tolist()), start=1):
                    row = mapping[vector_id]
                    hits.append(
                        RankedHit(
                            vector_id=vector_id,
                            video_id=str(row["video_id"]),
                            frame_id=int(row["frame_id"]),
                            timestamp_ms=int(row["timestamp_ms"]),
                            keyframe_path=str(row["keyframe_path"]),
                            rank=rank,
                            similarity=float(score),
                        )
                    )
                per_request_hits[q_idx][model_key] = hits
        except (OSError, ValueError, ContractError):
            continue
        run_id = str(manifest["wp03_run_id"])
        preprocess_run_id = str(manifest["preprocess_run_id"])
        used_models.append(model_key)

    if not used_models or run_id is None or preprocess_run_id is None:
        raise ContractError("no usable visual model")

    responses: list[SearchResponse] = []
    for q_idx, req in enumerate(requests):
        hits_for_q = per_request_hits[q_idx]
        result = fuse_rrf(
            hits_for_q,
            query_id=req.query_id,
            event_index=req.event_index,
            preprocess_run_id=preprocess_run_id,
            limit=max(req.limit, candidate_k_per_model),
            rrf_k=rrf_k,
        )
        candidates = (
            result.candidates[:req.limit]
            if dedup_window_ms is None
            else diversify_visual_candidates(result.candidates, limit=req.limit, dedup_window_ms=dedup_window_ms)
        )
        responses.append(
            SearchResponse.create(
                query_id=req.query_id,
                wp03_run_id=run_id,
                preprocess_run_id=preprocess_run_id,
                requested_top_k=req.limit,
                candidate_k_per_model=candidate_k_per_model,
                hard_candidate_cap=hard_candidate_cap,
                models_requested=requested_models,
                models_used=tuple(used_models),
                candidates=candidates,
            )
        )
    return responses
