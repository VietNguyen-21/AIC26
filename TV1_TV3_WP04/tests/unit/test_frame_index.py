from __future__ import annotations

import pytest

from aic2026.contracts import OriginalFrameIndexRecord
from aic2026.frame_index import FrameIndexError, OriginalFrameIndex


def record(frame_id: int, timestamp_ms: int) -> OriginalFrameIndexRecord:
    return OriginalFrameIndexRecord(
        preprocess_run_id="run-1",
        video_id="video-1",
        frame_id=frame_id,
        decode_index=frame_id,
        pts=timestamp_ms,
        dts=timestamp_ms,
        time_base="1/1000",
        timestamp_ms=timestamp_ms,
        is_technical_keyframe=frame_id == 0,
        created_at_utc="2026-08-04T00:00:00Z",
    )


def test_resolve_timestamp_modes_and_round_trip():
    index = OriginalFrameIndex([record(0, 0), record(1, 40), record(2, 80)])
    assert index.resolve_timestamp(59, mode="nearest").record.frame_id == 1
    assert index.resolve_timestamp(60, mode="nearest").record.frame_id == 1
    assert index.resolve_timestamp(61, mode="nearest").record.frame_id == 2
    assert index.resolve_timestamp(60, mode="before").record.frame_id == 1
    assert index.resolve_timestamp(60, mode="after").record.frame_id == 2
    assert index.get(2).timestamp_ms == 80


def test_iter_window_deduplicates_frames():
    index = OriginalFrameIndex([record(0, 0), record(1, 40), record(2, 80)])
    output = index.iter_window(0, 80, step_ms=10)
    assert [item.record.frame_id for item in output] == [0, 1, 2]


def test_index_rejects_non_monotonic_and_duplicate_frame_id():
    with pytest.raises(FrameIndexError, match="not monotonic"):
        OriginalFrameIndex([record(0, 40), record(1, 0)])
    with pytest.raises(FrameIndexError, match="expected 1"):
        OriginalFrameIndex([record(0, 0), record(2, 40)])


def test_get_rejects_frame_outside_original_range():
    index = OriginalFrameIndex([record(0, 0)])
    with pytest.raises(FrameIndexError, match="outside"):
        index.get(1)
