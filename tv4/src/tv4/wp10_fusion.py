"""WP10 — Multimodal Fusion (RRF) and the KIS orchestration workflow.

Combines independent branch results (visual from TV2/WP03, ocr/asr/object/
metadata from TV3) into one ranked, deduplicated, video-diverse top-100 list
of `SearchCandidate`, tolerant of any single branch being empty/unavailable
(object is always a *soft* signal, never a hard filter, per the plan).
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import replace

from .contracts import SearchCandidate

DEFAULT_RRF_K = 60
DEFAULT_DEDUP_WINDOW_MS = 1_000

# Branches TV4 treats as soft/boost-only signals rather than hard filters —
# a candidate is never *dropped* purely for missing an object hint. They
# still contribute to RRF like every other branch, but at a reduced weight
# (see DEFAULT_SOFT_BRANCH_WEIGHT below) so an object/metadata match alone
# can't out-rank a genuine visual/OCR/ASR hit; it can only nudge candidates
# that other branches already found.
SOFT_BRANCHES = {"object", "metadata"}
DEFAULT_SOFT_BRANCH_WEIGHT = 0.5


def reciprocal_rank_fusion(
    branch_results: dict[str, list[SearchCandidate]],
    *,
    rrf_k: int = DEFAULT_RRF_K,
    dedup_window_ms: int = DEFAULT_DEDUP_WINDOW_MS,
    top_k: int = 100,
    soft_branch_weight: float = DEFAULT_SOFT_BRANCH_WEIGHT,
) -> list[SearchCandidate]:
    """Standard RRF: score(c) = sum_over_branches weight(branch) / (rrf_k + rank).

    Candidates are keyed by (video_id, frame bucket) where the bucket rounds
    timestamp_ms to `dedup_window_ms` so near-duplicate keyframes from
    different branches merge into one submission-ready row instead of
    crowding the top-100 with near-identical frames of the same event.

    `soft_branch_weight` scales the RRF contribution of SOFT_BRANCHES
    (object/metadata) relative to hard branches (visual/ocr/asr), so those
    signals boost/break ties among otherwise-found candidates without being
    able to rank a candidate that *only* an object/metadata hit ever saw.
    """
    if rrf_k <= 0:
        raise ValueError("rrf_k must be positive")
    if dedup_window_ms <= 0:
        raise ValueError("dedup_window_ms must be positive")
    if soft_branch_weight < 0:
        raise ValueError("soft_branch_weight must be non-negative")

    buckets: dict[tuple[str, int], dict] = {}
    for branch, candidates in branch_results.items():
        weight = soft_branch_weight if branch in SOFT_BRANCHES else 1.0
        for c in candidates:
            bucket_key = (c.video_id, c.timestamp_ms // dedup_window_ms)
            contribution = weight / (rrf_k + c.rank)
            entry = buckets.get(bucket_key)
            if entry is None:
                entry = {"candidate": c, "score": 0.0, "sources": [], "model_scores": {}}
                buckets[bucket_key] = entry
            entry["score"] += contribution
            entry["sources"].append(branch)
            if c.score is not None:
                entry["model_scores"][branch] = c.score
            # Prefer the highest-confidence representative frame for the bucket.
            if c.rank < entry["candidate"].rank:
                entry["candidate"] = c

    fused: list[SearchCandidate] = []
    for entry in buckets.values():
        base = entry["candidate"]
        fused.append(
            replace(
                base,
                source="fusion",
                score=entry["score"],
                provenance_sources=tuple(sorted(set(entry["sources"]))),
                model_scores={**base.model_scores, **entry["model_scores"]},
            )
        )

    fused.sort(key=lambda c: c.score or 0.0, reverse=True)
    return _diversify_top_k(fused, top_k=top_k)


def _diversify_top_k(ranked: list[SearchCandidate], *, top_k: int, per_video_cap: int = 5) -> list[SearchCandidate]:
    """Cap how many frames per single video can occupy the top slots.

    Prevents one very-well-matched video from filling the whole top-100 and
    starving the "top-20 diversity" gate the plan calls for (G1/G3). This cap
    is enforced strictly -- a query genuinely matching only one video still
    returns at most `per_video_cap` frames rather than padding out to
    `top_k` with more near-duplicates of the same video.
    """
    per_video_count: dict[str, int] = defaultdict(int)
    kept: list[SearchCandidate] = []
    for c in ranked:
        if per_video_count[c.video_id] < per_video_cap:
            kept.append(c)
            per_video_count[c.video_id] += 1
        if len(kept) >= top_k:
            break
    return [replace(c, rank=i + 1) for i, c in enumerate(kept[:top_k])]


def fuse_kis(
    branch_results: dict[str, list[SearchCandidate]],
    *,
    rrf_k: int = DEFAULT_RRF_K,
    dedup_window_ms: int = DEFAULT_DEDUP_WINDOW_MS,
    top_k: int = 100,
    soft_branch_weight: float = DEFAULT_SOFT_BRANCH_WEIGHT,
) -> list[SearchCandidate]:
    """KIS/WP10 entry point. Object/metadata contribute score only, at reduced
    weight, never a hard gate."""
    return reciprocal_rank_fusion(
        branch_results, rrf_k=rrf_k, dedup_window_ms=dedup_window_ms, top_k=top_k,
        soft_branch_weight=soft_branch_weight,
    )
