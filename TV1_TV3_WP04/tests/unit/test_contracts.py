import pytest
from pydantic import ValidationError

from aic2026.contracts import (
    ASRSegment,
    CorpusManifestRecord,
    MediaRecord,
    OriginalFrameIndexRecord,
    SearchCandidate,
    ShotRecord,
)

NOW = "2026-08-06T00:00:00Z"


def test_corpus_ingest_status_defaults_to_accepted():
    row = CorpusManifestRecord(
        video_id="v", original_video_path="v.mp4", source_sha256="0" * 64,
        file_size_bytes=1, created_at_utc=NOW,
    )
    assert row.ingest_status == "accepted"


def test_media_contract_keeps_legacy_and_pts_fields_for_handoff():
    row = MediaRecord(
        preprocess_run_id="r", video_id="v", original_video_path="v.mp4",
        source_sha256="0" * 64, time_base="1/1000", fps_nominal=25,
        fps_average=25, frame_count=10, duration_ms=400, width_px=16,
        height_px=16, has_audio=False, created_at_utc=NOW,
    )
    assert row.fps_nominal == 25
    assert row.frame_index_backend is None


def test_original_frame_keeps_raw_and_normalized_timeline():
    row = OriginalFrameIndexRecord(
        preprocess_run_id="r", video_id="v", frame_id=0, decode_index=0,
        pts=-100, time_base="1/1000", raw_timestamp_ms=-100,
        timeline_origin_ms=-100, timestamp_ms=0, created_at_utc=NOW,
    )
    assert row.raw_timestamp_ms == -100
    assert row.timestamp_ms == 0


def test_shot_rejects_inverted_bounds():
    with pytest.raises(ValidationError):
        ShotRecord(
            preprocess_run_id="r", video_id="v", shot_id="s",
            start_frame_id=2, end_frame_id=1, start_timestamp_ms=0,
            end_timestamp_ms=1, detector_name="x", detector_version="1",
            created_at_utc=NOW,
        )


def test_asr_is_handoff_only_but_preserves_future_contract():
    segment = ASRSegment(
        preprocess_run_id="r", segment_id="a", video_id="v",
        start_ms=0, end_ms=1000, text="xin chào", normalized_text="xin chào",
        model_name="future", model_version="1", created_at_utc=NOW,
    )
    assert segment.language == "vi"


def test_search_candidate_preserves_original_frame_and_temporal_window():
    candidate = SearchCandidate(
        query_id="q", video_id="v", frame_id=12, timestamp_ms=480,
        window_start_ms=400, window_end_ms=600, source="visual", rank=1,
        raw_score=0.9, preprocess_run_id="r", created_at_utc=NOW,
    )
    assert candidate.frame_id == 12
    assert candidate.window_end_ms == 600


def test_contracts_reject_unknown_fields():
    with pytest.raises(ValidationError):
        CorpusManifestRecord.model_validate({
            "video_id":"v","original_video_path":"v.mp4","source_sha256":"0"*64,
            "file_size_bytes":1,"created_at_utc":NOW,"mystery":1,
        })
