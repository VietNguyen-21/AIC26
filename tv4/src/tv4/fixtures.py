"""Canned, contract-accurate responses for TV4_FIXTURE_MODE.

Every field/shape here matches exactly what the live endpoints in `api.py`
return -- TV5 can build against these on day one and swap to the live API
later with zero UI code changes, only an env var flip.
"""
from __future__ import annotations

KIS_RESPONSE = {
    "query_id": "kis-fixture-001",
    "candidates": [
        {
            "query_id": "kis-fixture-001", "video_id": "L21_V001", "frame_id": 10690,
            "timestamp_ms": 356333, "source": "fusion", "rank": 1, "schema_version": "1.0.0",
            "event_index": None, "representative_frame_id": None,
            "window_start_ms": None, "window_end_ms": None,
            "raw_score": None, "score": 0.0405,
            "model_scores": {"bge_vl": 0.109, "metaclip2": 0.199, "perception": 0.224},
            "model_ranks": {"bge_vl": 45, "metaclip2": 17, "perception": 44},
            "matched_filters": [], "evidence_refs": ["keyframe:keyframes/L21_V001/83.jpg"],
            "provenance_sources": ["visual"], "provenance": {}, "confidence": None,
            "preprocess_run_id": "run_v1_batch1", "created_at_utc": "2026-08-14T05:36:45Z",
        },
        {
            "query_id": "kis-fixture-001", "video_id": "L21_V002", "frame_id": 23940,
            "timestamp_ms": 798000, "source": "fusion", "rank": 2, "schema_version": "1.0.0",
            "event_index": None, "representative_frame_id": None,
            "window_start_ms": None, "window_end_ms": None,
            "raw_score": None, "score": 0.0371,
            "model_scores": {"bge_vl": 0.116, "metaclip2": 0.187, "perception": 0.213},
            "model_ranks": {"bge_vl": 12, "metaclip2": 37, "perception": 55},
            "matched_filters": [], "evidence_refs": ["keyframe:keyframes/L21_V002/214.jpg"],
            "provenance_sources": ["visual"], "provenance": {}, "confidence": None,
            "preprocess_run_id": "run_v1_batch1", "created_at_utc": "2026-08-14T05:36:45Z",
        },
    ],
}

VQA_RESPONSE = {
    "query_id": "qa-fixture-001",
    "results": [
        {
            "rank": 1, "video_id": "L05_V005", "frame_id": 888, "timestamp_ms": 29600,
            "confidence": None, "answer": "màu xanh", "verified": True, "manual_review": False,
            "evidence": {
                "query_id": "qa-fixture-001", "video_id": "L05_V005", "frame_id": 888,
                "timestamp_ms": 29600, "keyframe_path": "keyframes/L05_V005/0888.jpg",
                "ocr_texts": [], "asr_texts": ["...cô ấy đang cầm ly màu xanh..."],
                "object_labels": ["person", "cup"], "neighbor_frame_ids": [880, 896],
                "provenance": {"candidate_source": ["visual", "asr"]},
            },
        },
    ],
}

TRAKE_RESPONSE = {
    "query_id": "trake-fixture-001",
    "result": {
        "video_id": "L10_V010",
        "frame_ids": [101, 156, 203, 251],
        "event_scores": [0.9, 0.7, 0.85, 0.6],
        "aggregate_score": 3.05,
        "preprocess_run_id": "run_v1_batch1",
    },
}
