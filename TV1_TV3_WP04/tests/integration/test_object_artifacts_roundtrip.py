from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from aic2026.config import Settings
from aic2026.contracts import FrameRecord
from aic2026.objects import (
    BaseObjectAdapter,
    consolidate_object_artifacts,
    load_object_video_result,
    run_object_video,
)
from aic2026.utils import read_jsonl, utcnow_iso


class FixtureDetector(BaseObjectAdapter):
    name = "fixture"
    version = "1"

    def detect(self, image_path):
        return [{"label": "car", "confidence": 0.9, "bbox": (0.1, 0.2, 0.8, 0.9)}]


def test_object_artifacts_round_trip(tmp_path):
    image_path = tmp_path / "frame.jpg"
    assert cv2.imwrite(str(image_path), np.full((64, 96, 3), 127, dtype=np.uint8))
    frame = FrameRecord(
        preprocess_run_id="r1",
        video_id="V1",
        frame_id=7,
        keyframe_seq=0,
        timestamp_ms=700,
        pts=700,
        time_base="1/1000",
        decode_index=7,
        shot_id="s0",
        keyframe_path=str(image_path),
        selection_reason="shot_representative",
        created_at_utc=utcnow_iso(),
    )
    settings = Settings()
    settings.object.enabled = True
    settings.object.adapter = "noop"
    run_root = tmp_path / "run"
    result = run_object_video([frame], run_root, FixtureDetector(), settings.object)
    assert result.failed_frames == 0
    assert result.detections[0].frame_id == 7
    loaded = load_object_video_result(run_root, "V1")
    assert loaded is not None
    assert loaded.detections[0].canonical_label == "car"
    combined = consolidate_object_artifacts(run_root)
    assert len(combined) == 1
    rows = read_jsonl(run_root / "objects" / "objects.jsonl")
    assert rows[0]["source_keyframe_sha256"]
