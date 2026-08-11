from __future__ import annotations

from aic2026.asr import deduplicate_asr_segments, normalize_vad_intervals
from aic2026.contracts import ASRSegment
from aic2026.utils import utcnow_iso


def make_segment(segment_id: str, start_ms: int, end_ms: int, text: str, avg_logprob: float):
    return ASRSegment(
        preprocess_run_id="r1",
        segment_id=segment_id,
        video_id="V1",
        start_ms=start_ms,
        end_ms=end_ms,
        text=text,
        normalized_text=text.lower(),
        normalized_text_no_diacritics=text.lower(),
        language="vi",
        avg_logprob=avg_logprob,
        model_name="fixture",
        model_version="1",
        created_at_utc=utcnow_iso(),
    )


def test_vad_intervals_merge_clamp_and_split_with_overlap():
    rows = normalize_vad_intervals(
        [
            {"start_ms": -50, "end_ms": 1800},
            {"start_ms": 1950, "end_ms": 5600},
            {"start_ms": 9000, "end_ms": 12000},
        ],
        duration_ms=10000,
        max_segment_ms=3000,
        overlap_ms=500,
        merge_gap_ms=200,
    )
    assert rows == [
        {"start_ms": 0, "end_ms": 3000, "confidence": None},
        {"start_ms": 2500, "end_ms": 5500, "confidence": None},
        {"start_ms": 5000, "end_ms": 5600, "confidence": None},
        {"start_ms": 9000, "end_ms": 10000, "confidence": None},
    ]


def test_overlap_dedup_keeps_better_segment_and_reassigns_stable_ids():
    rows = deduplicate_asr_segments(
        [
            make_segment("a", 1000, 2000, "xin chào", -0.8),
            make_segment("b", 1200, 2100, "xin chào", -0.2),
            make_segment("c", 2300, 2800, "việt nam", -0.4),
        ]
    )
    assert len(rows) == 2
    assert rows[0].start_ms == 1200
    assert rows[0].segment_id == "asr:V1:000000"
    assert rows[1].segment_id == "asr:V1:000001"
