from __future__ import annotations

import json
from pathlib import Path

from aic2026.contracts import FrameRecord, MediaRecord, ShotRecord
from aic2026.temporal import TemporalRegistry, build_temporal_registry

NOW = "2026-08-04T00:00:00Z"


def test_temporal_artifacts_reload_and_keep_original_timeline(tmp_path: Path):
    frames = [
        FrameRecord(
            preprocess_run_id="r",
            video_id="V",
            frame_id=2,
            keyframe_seq=0,
            timestamp_ms=67,
            pts=1024,
            time_base="1/15360",
            decode_index=2,
            shot_id="s",
            keyframe_path="0.jpg",
            selection_reason="shot_representative",
            created_at_utc=NOW,
        ),
        FrameRecord(
            preprocess_run_id="r",
            video_id="V",
            frame_id=31,
            keyframe_seq=1,
            timestamp_ms=1140,
            pts=17510,
            time_base="1/15360",
            decode_index=31,
            shot_id="s",
            keyframe_path="1.jpg",
            selection_reason="max_gap",
            created_at_utc=NOW,
        ),
    ]
    shots = [
        ShotRecord(
            preprocess_run_id="r",
            video_id="V",
            shot_id="s",
            start_frame_id=0,
            end_frame_id=60,
            start_timestamp_ms=0,
            end_timestamp_ms=2000,
            start_pts=0,
            end_pts=30720,
            detector_name="fixture",
            detector_version="1",
            created_at_utc=NOW,
        )
    ]
    media = [
        MediaRecord(
            preprocess_run_id="r",
            video_id="V",
            original_video_path="V.mp4",
            source_sha256="1" * 64,
            time_base="1/15360",
            fps_nominal=30,
            fps_average=27.2,
            is_variable_frame_rate=True,
            frame_count=61,
            duration_ms=2000,
            width_px=320,
            height_px=240,
            codec="h264",
            has_audio=False,
            created_at_utc=NOW,
        )
    ]
    build_temporal_registry(frames, tmp_path, shots=shots, media=media)
    registry = TemporalRegistry.from_run_root(tmp_path)
    assert registry.nearest_keyframe("V", 1000).frame_id == 31
    assert registry.get_frame("V", 31).pts == 17510
    manifest = json.loads((tmp_path / "temporal" / "manifest.json").read_text())
    assert manifest["temporal_frame_count"] == 2
    assert manifest["video_count"] == 1
    assert (tmp_path / "temporal" / "temporal_frames.jsonl").exists()
    assert (tmp_path / "temporal" / "asr_links.jsonl").exists()
