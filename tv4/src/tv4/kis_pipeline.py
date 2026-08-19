"""End-to-end Textual-KIS orchestration: router (WP07) -> retrievers -> fusion (WP10)
-> optional WP09 exact-frame refinement -> submission-ready top-100.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Mapping

from .clients.tv1_client import TV1Client
from .clients.tv2_refine_client import TV2RefineClient
from .clients.tv2_visual_client import TV2VisualClient
from .clients.tv3_client import TV3Client
from .contracts import SearchCandidate
from .wp07_router import route_kis
from .wp10_fusion import fuse_kis


@dataclass
class KisServices:
    tv1: TV1Client
    tv3: TV3Client
    visual: TV2VisualClient
    refine: TV2RefineClient | None = None
    feedback: Any | None = None
    preprocess_run_id: str = "unknown"
    original_media_root: Path | None = None
    media_registry: Mapping[str, object] | None = None
    allowed_media_extensions: frozenset[str] = frozenset()
    derivative_asset_root: Path | None = None
    allowed_image_extensions: frozenset[str] = frozenset()


def run_kis_query(query_text: str, services: KisServices, *, query_id: str | None = None, top_k: int = 100) -> list[SearchCandidate]:
    decision = route_kis(query_text, query_id=query_id, limit=top_k)

    branch_results: dict[str, list[SearchCandidate]] = {}
    if "visual" in decision.branches:
        branch_results["visual"] = services.visual.search(decision.request.query_id, query_text)
    tv3_routes = [b for b in decision.branches if b in {"ocr", "asr", "object", "metadata"}]
    if tv3_routes:
        # search_all keys results by the TV3 route name ("ocr"/"asr"/...),
        # which already matches the branch name used above.
        branch_results.update(services.tv3.search_all(decision.request, tv3_routes))

    ranked = fuse_kis(branch_results, top_k=top_k)
    ranked = [replace(c, query_id=decision.request.query_id, preprocess_run_id=services.preprocess_run_id) for c in ranked]

    if services.refine is not None:
        ranked = _refine_top(ranked, query_text, services)
    return ranked


def _refine_top(ranked: list[SearchCandidate], query_text: str, services: KisServices, refine_top_n: int = 5) -> list[SearchCandidate]:
    """Ask WP09 to tighten the frame for the top few candidates only.

    Refinement is comparatively expensive (it decodes the original video),
    so it is only spent on the handful of candidates most likely to become
    the actual submission, matching the plan's "shared exact-frame service
    improves the real frame for KIS/VQA/TRAKE" description.
    """
    out = list(ranked)
    if services.original_media_root is None:
        return out
    from .media_identity import resolve_original_media_path
    for i, c in enumerate(out[:refine_top_n]):
        try:
            media_path = resolve_original_media_path(services.original_media_root, c.video_id, services.media_registry, services.preprocess_run_id, services.allowed_media_extensions)
        except ValueError:
            continue
        result = services.refine.refine(
            {
                "candidate": {"video_id": c.video_id, "frame_id": c.frame_id, "timestamp_ms": c.timestamp_ms,
                              "upstream_score": c.score, "confidence": c.confidence},
                "video_path": str(media_path),
                "task": "KIS",
                "refinement_text": query_text,
                "policy": "representative",
                "context": {
                    "preprocess_run_id": services.preprocess_run_id,
                    "media_record_ref": c.video_id,
                    "mapping_ref": f"tv1-frames/{c.video_id}",
                    "decoder_version": "pyav-tv4-adapter-1",
                    "model_version": "n/a",
                    "config_version": "default",
                },
                "decode_budget": {"max_decoded_frames": 64, "max_window_ms": 4000, "max_decode_time_ms": 8000, "max_dense_regions": 3},
            }
        )
        if not result or not result.get("hypotheses"):
            continue
        best = canonical_refined_candidate(result["hypotheses"][0])
        if best is not None:
            out[i] = replace(c, frame_id=best[0], timestamp_ms=best[1])
    return out


def canonical_refined_candidate(payload: object) -> tuple[int, int] | None:
    """Allow a replacement only when WP09 explicitly proved original identity."""
    if not isinstance(payload, dict):
        return None
    if payload.get("mapping_guaranteed") is not True or payload.get("submission_selectable") is not True:
        return None
    if payload.get("provenance_mode") != "live" or payload.get("identity_source") != "certified_run_consecutive_original_decode":
        return None
    if payload.get("media_identity_verified") is not True or payload.get("producer_compatibility_verified") is not True:
        return None
    if not isinstance(payload.get("certification_id"), str) or not isinstance(payload.get("certification_report_sha256"), str):
        return None
    frame_id, timestamp_ms = payload.get("frame_id"), payload.get("timestamp_ms")
    if isinstance(frame_id, bool) or not isinstance(frame_id, int) or frame_id < 0:
        return None
    if isinstance(timestamp_ms, bool) or not isinstance(timestamp_ms, int) or timestamp_ms < 0:
        return None
    return frame_id, timestamp_ms
