"""End-to-end Textual-KIS orchestration: router (WP07) -> retrievers -> fusion (WP10)
-> optional WP09 exact-frame refinement -> submission-ready top-100.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

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
    preprocess_run_id: str = "unknown"


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
    for i, c in enumerate(out[:refine_top_n]):
        result = services.refine.refine(
            {
                "candidate": {"video_id": c.video_id, "frame_id": c.frame_id, "timestamp_ms": c.timestamp_ms,
                              "upstream_score": c.score, "confidence": c.confidence},
                "video_path": _video_path_for(c.video_id, services.tv1),
                "task": "KIS",
                "refinement_text": query_text,
                "policy": "representative",
                "context": {
                    "preprocess_run_id": services.preprocess_run_id,
                    "media_record_ref": c.video_id,
                    "mapping_ref": c.video_id,
                    "decoder_version": "pyav-tv4-adapter-1",
                    "model_version": "n/a",
                    "config_version": "default",
                },
                "decode_budget": {"max_decoded_frames": 64, "max_window_ms": 4000, "max_decode_time_ms": 8000, "max_dense_regions": 3},
            }
        )
        if not result or not result.get("hypotheses"):
            continue
        best = result["hypotheses"][0]
        out[i] = replace(c, frame_id=best.get("frame_id", c.frame_id), timestamp_ms=best.get("timestamp_ms", c.timestamp_ms))
    return out


def _video_path_for(video_id: str, tv1: TV1Client) -> str:
    """Resolve the real media path (and real extension) for a video.

    `run_parallel.py` (TV1_TV3_WP04) accepts .mp4/.mkv/.avi/.mov/.webm, so
    hard-coding `.mp4` here silently breaks refine for any other format.
    Falls back to the old `.mp4` guess only if TV1's media record is
    unavailable, so refine degrades instead of hard-failing on lookup issues.
    """
    media = tv1.media_record(video_id)
    if media and media.get("original_video_path"):
        return media["original_video_path"]
    return f"data/raw/{video_id}.mp4"
