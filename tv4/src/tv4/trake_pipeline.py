"""End-to-end TRAKE orchestration: WP07 event split -> WP10 fusion (whole
query, for video retrieval) -> per-event WP10 fusion (for alignment) -> WP12
temporal alignment -> optional WP09 fine-alignment per event.
"""
from __future__ import annotations

from dataclasses import replace

from .contracts import SearchCandidate, SearchRequest, TrakeHypothesis
from .kis_pipeline import KisServices
from .wp07_router import route_trake
from .wp10_fusion import fuse_kis
from .wp12_trake import align_trake, build_event_pools, pick_video, to_hypothesis


def _fuse_for_request(request: SearchRequest, services: KisServices, query_text: str) -> list[SearchCandidate]:
    branch_results: dict[str, list[SearchCandidate]] = {
        "visual": services.visual.search(request.query_id, query_text, event_index=request.event_index),
    }
    tv3_results = services.tv3.search_all(request, ["ocr", "asr", "object"])
    branch_results.update(tv3_results)
    return fuse_kis(branch_results, top_k=request.limit)


def run_trake_query(
    query_text: str,
    services: KisServices,
    *,
    events: list[str] | None = None,
    query_id: str | None = None,
    strategy: str = "dp",
) -> TrakeHypothesis | None:
    decision = route_trake(query_text, events=events, query_id=query_id)
    request = decision.request

    # Stage 1 (Retrieval): fuse on the whole query text to find the video.
    whole_query_ranked = _fuse_for_request(replace(request, events=()), services, query_text)
    video_id = pick_video(whole_query_ranked)
    if video_id is None:
        return None

    # Stage 2 (Alignment): fuse per event, restricted (post-hoc) to that video.
    per_event_candidates = []
    for idx, event_text in enumerate(request.events):
        event_request = replace(request, query_id=f"{request.query_id}-ev{idx}", event_index=idx, events=())
        ranked = _fuse_for_request(event_request, services, event_text)
        per_event_candidates.append(ranked)

    pools = build_event_pools(video_id, per_event_candidates)
    aligned = align_trake(pools, strategy=strategy)
    if aligned is None:
        return None

    aligned = [replace(c, query_id=request.query_id, preprocess_run_id=services.preprocess_run_id) for c in aligned]
    return to_hypothesis(request.query_id, video_id, aligned, services.preprocess_run_id)
