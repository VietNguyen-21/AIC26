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

    # Build requests for whole query (idx 0) and all ordered events (idx 1..N)
    batch_specs: list[tuple[str, str, int | None, SearchRequest]] = []
    whole_req = replace(request, events=())
    batch_specs.append((request.query_id, query_text, None, whole_req))

    for idx, event_text in enumerate(request.events):
        event_req = replace(request, query_id=f"{request.query_id}-ev{idx}", event_index=idx, events=())
        batch_specs.append((event_req.query_id, event_text, idx, event_req))

    # Single batched visual search across whole sequence and all events
    visual_queries = [(qid, qtxt, ev_idx) for qid, qtxt, ev_idx, _ in batch_specs]
    if hasattr(services.visual, "search_batch"):
        visual_results = services.visual.search_batch(visual_queries)
    else:
        visual_results = [
            services.visual.search(qid, qtxt, event_index=ev_idx)
            for qid, qtxt, ev_idx in visual_queries
        ]

    # Perform TV3 search and fusion per branch
    ranked_results: list[list[SearchCandidate]] = []
    for (_, _, _, req), visual_candidates in zip(batch_specs, visual_results):
        branch_results: dict[str, list[SearchCandidate]] = {
            "visual": visual_candidates,
        }
        tv3_results = services.tv3.search_all(req, ["ocr", "asr", "object"])
        branch_results.update(tv3_results)
        ranked = fuse_kis(branch_results, top_k=req.limit)
        ranked_results.append(ranked)

    whole_query_ranked = ranked_results[0]
    per_event_candidates = ranked_results[1:]

    # Stage 1 (Retrieval): Pick video from whole query ranked fusion
    video_id = pick_video(whole_query_ranked)
    if video_id is None:
        return None

    # Stage 2 (Alignment): Build event pools and align with dynamic programming
    pools = build_event_pools(video_id, per_event_candidates)
    aligned = align_trake(pools, strategy=strategy)
    if aligned is None:
        return None

    aligned = [replace(c, query_id=request.query_id, preprocess_run_id=services.preprocess_run_id) for c in aligned]
    return to_hypothesis(request.query_id, video_id, aligned, services.preprocess_run_id)
