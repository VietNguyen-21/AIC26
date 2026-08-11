from __future__ import annotations

from pathlib import Path

import pytest

from aic2026.contracts import (
    ASRSegment,
    FrameRecord,
    MediaRecord,
    SearchCandidate,
    ShotRecord,
)
from aic2026.temporal import (
    TemporalRegistry,
    TemporalRegistryError,
    build_temporal_registry,
    relink_asr_segments,
)

NOW = "2026-08-04T00:00:00Z"


def frame(frame_id: int, timestamp_ms: int, shot_id: str, seq: int) -> FrameRecord:
    return FrameRecord(
        preprocess_run_id="run-04",
        video_id="V1",
        frame_id=frame_id,
        keyframe_seq=seq,
        timestamp_ms=timestamp_ms,
        pts=timestamp_ms * 90,
        time_base="1/90000",
        decode_index=frame_id,
        shot_id=shot_id,
        keyframe_path=f"keyframes/V1/{seq:06d}.jpg",
        selection_reason="shot_representative",
        created_at_utc=NOW,
    )


def shot(
    shot_id: str,
    start_frame: int,
    end_frame: int,
    start_ms: int,
    end_ms: int,
) -> ShotRecord:
    return ShotRecord(
        preprocess_run_id="run-04",
        video_id="V1",
        shot_id=shot_id,
        start_frame_id=start_frame,
        end_frame_id=end_frame,
        start_timestamp_ms=start_ms,
        end_timestamp_ms=end_ms,
        start_pts=start_ms * 90,
        end_pts=end_ms * 90,
        detector_name="fixture",
        detector_version="1",
        created_at_utc=NOW,
    )


def media(duration_ms: int = 5000) -> MediaRecord:
    return MediaRecord(
        preprocess_run_id="run-04",
        video_id="V1",
        original_video_path="V1.mp4",
        source_sha256="0" * 64,
        time_base="1/90000",
        fps_nominal=30,
        fps_average=30,
        is_variable_frame_rate=False,
        frame_count=151,
        duration_ms=duration_ms,
        width_px=640,
        height_px=360,
        codec="h264",
        has_audio=True,
        created_at_utc=NOW,
    )


def asr(segment_id: str, start_ms: int, end_ms: int) -> ASRSegment:
    return ASRSegment(
        preprocess_run_id="run-04",
        segment_id=segment_id,
        video_id="V1",
        start_ms=start_ms,
        end_ms=end_ms,
        text="xin chao",
        normalized_text="xin chao",
        language="vi",
        model_name="fixture",
        model_version="1",
        created_at_utc=NOW,
    )


def fixture_registry(tmp_path: Path) -> TemporalRegistry:
    frames = [
        frame(0, 0, "s0", 0),
        frame(3, 100, "s0", 1),
        frame(10, 430, "s0", 2),
        frame(45, 1500, "s1", 3),
        frame(120, 4100, "s1", 4),
    ]
    shots = [shot("s0", 0, 29, 0, 999), shot("s1", 30, 150, 1000, 5000)]
    segments = [asr("a0", 350, 1700), asr("a1", 3900, 4500)]
    build_temporal_registry(
        frames,
        tmp_path,
        shots=shots,
        asr_segments=segments,
        media=[media()],
    )
    return TemporalRegistry.from_run_root(tmp_path)


def test_persistent_registry_prev_next_boundaries_and_shot_lookup(tmp_path: Path):
    registry = fixture_registry(tmp_path)
    assert registry.videos() == ["V1"]
    assert registry.previous_keyframe("V1", 0) is None
    assert registry.next_keyframe("V1", 0).frame_id == 3
    assert registry.previous_keyframe("V1", 120).frame_id == 45
    assert registry.next_keyframe("V1", 120) is None
    assert registry.shot_at("V1", 500).shot_id == "s0"
    assert registry.shot_at("V1", 1500).shot_id == "s1"
    assert registry.shot_at("V1", 6000) is None


def test_nearest_before_after_with_sparse_vfr_like_timestamps(tmp_path: Path):
    registry = fixture_registry(tmp_path)
    assert registry.nearest_keyframe("V1", 420, "nearest").frame_id == 10
    assert registry.nearest_keyframe("V1", 420, "before").frame_id == 3
    assert registry.nearest_keyframe("V1", 420, "after").frame_id == 10
    assert registry.nearest_keyframe("V1", 430, "before").frame_id == 10
    assert registry.nearest_keyframe("V1", 430, "after").frame_id == 10


def test_interval_lookup_and_window_clamping_include_asr(tmp_path: Path):
    registry = fixture_registry(tmp_path)
    assert [row.frame_id for row in registry.interval_to_keyframes("V1", 90, 500)] == [3, 10]
    # Sparse interval without an internal keyframe returns the bracketing keyframes.
    assert [row.frame_id for row in registry.interval_to_keyframes("V1", 600, 900)] == [10, 45]
    window = registry.window_by_radius("V1", 100, 500)
    assert window.window_start_ms == 0
    assert window.window_end_ms == 600
    assert window.clamped_to_media is True
    assert window.representative_frame_id == 3
    assert window.asr_segment_ids == ["a0"]


def test_candidate_interval_canonicalization_preserves_provenance(tmp_path: Path):
    registry = fixture_registry(tmp_path)
    candidate = SearchCandidate(
        query_id="q1",
        video_id="V1",
        frame_id=0,
        timestamp_ms=1400,
        window_start_ms=1200,
        window_end_ms=1800,
        source="asr",
        rank=1,
        provenance_sources=["asr"],
        preprocess_run_id="run-04",
        created_at_utc=NOW,
    )
    canonical = registry.canonicalize_candidate(candidate)
    assert canonical.frame_id == 45
    assert canonical.representative_frame_id == 45
    assert canonical.window_start_ms == 1200
    assert canonical.window_end_ms == 1800
    assert canonical.provenance_sources == ["asr", "temporal_registry"]
    assert canonical.provenance["temporal_registry"]["representative_timestamp_ms"] == 1500


def test_missing_video_and_missing_frame_are_explicit_errors(tmp_path: Path):
    registry = fixture_registry(tmp_path)
    with pytest.raises(TemporalRegistryError, match="Unknown"):
        registry.nearest_keyframe("missing", 0)
    with pytest.raises(TemporalRegistryError, match="Unknown keyframe"):
        registry.previous_keyframe("V1", 999)


def test_build_rejects_duplicate_frame_ids(tmp_path: Path):
    frames = [frame(0, 0, "s0", 0), frame(0, 100, "s0", 1)]
    with pytest.raises(TemporalRegistryError, match="Duplicate"):
        build_temporal_registry(frames, tmp_path, shots=[shot("s0", 0, 10, 0, 1000)])


def test_relink_asr_updates_persistent_frame_links(tmp_path: Path):
    frames = [frame(0, 0, "s0", 0), frame(10, 430, "s0", 1)]
    build_temporal_registry(
        frames,
        tmp_path,
        shots=[shot("s0", 0, 20, 0, 1000)],
        media=[media(1000)],
    )
    relink_asr_segments(tmp_path, [asr("late", 300, 600)])
    reloaded = TemporalRegistry.from_run_root(tmp_path)
    assert reloaded.get_frame("V1", 10).linked_asr_segment_ids == ["late"]
    assert reloaded.window_by_radius("V1", 430, 100).asr_segment_ids == ["late"]
