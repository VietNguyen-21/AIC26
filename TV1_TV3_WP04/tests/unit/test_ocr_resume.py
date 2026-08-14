from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from aic2026.config import Settings
from aic2026.contracts import FrameRecord
from aic2026.ocr import (
    BaseOCRAdapter,
    consolidate_ocr_artifacts,
    ocr_search,
    run_ocr_video,
)
from aic2026.utils import utcnow_iso


class CountingOCRAdapter(BaseOCRAdapter):
    name = "counting_ocr"
    version = "1"

    def __init__(self):
        self.calls: list[list[str]] = []

    def recognize_batch(self, image_paths):
        self.calls.append(list(image_paths))
        output = []
        for index, _ in enumerate(image_paths):
            output.append(
                [
                    {
                        "text": "Cộng hòa Việt Nam" if index == 0 else "AIC 2026",
                        "bbox": (0.1, 0.2, 0.8, 0.7),
                        "confidence": 0.12 if index == 0 else 0.98,
                    }
                ]
            )
        return output


def make_frames(tmp_path: Path) -> list[FrameRecord]:
    frames = []
    for index in range(2):
        path = tmp_path / f"frame-{index}.jpg"
        image = np.full((80, 180, 3), 255, dtype=np.uint8)
        cv2.putText(image, f"AIC {index}", (10, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 0), 2)
        assert cv2.imwrite(str(path), image)
        frames.append(
            FrameRecord(
                preprocess_run_id="ocr-run",
                video_id="V1",
                frame_id=index,
                keyframe_seq=index,
                timestamp_ms=index * 1000,
                pts=index * 90000,
                time_base="1/90000",
                decode_index=index,
                shot_id="s0",
                keyframe_path=str(path),
                selection_reason="max_gap",
                created_at_utc=utcnow_iso(),
            )
        )
    return frames


def test_ocr_per_frame_resume_crop_and_retrieval(tmp_path):
    frames = make_frames(tmp_path)
    settings = Settings()
    settings.ocr.enabled = True
    settings.ocr.adapter = "noop"
    settings.ocr.batch_size = 2
    settings.ocr.confidence_threshold = 0.25
    settings.ocr.keep_raw_below_threshold = True
    adapter = CountingOCRAdapter()
    run_root = tmp_path / "run"

    first = run_ocr_video(frames, run_root, adapter, settings.ocr)
    assert first.processed_frames == 2
    assert first.resumed_frames == 0
    assert len(first.detections) == 2
    assert first.detections[0].below_threshold is True
    assert first.detections[0].normalized_text == "cộng hòa việt nam"
    assert first.detections[0].normalized_text_no_diacritics == "cong hoa viet nam"
    assert first.detections[0].crop_evidence_path
    assert (run_root / first.detections[0].crop_evidence_path).is_file()
    assert len(adapter.calls) == 1

    second = run_ocr_video(frames, run_root, adapter, settings.ocr)
    assert second.processed_frames == 0
    assert second.resumed_frames == 2
    assert len(adapter.calls) == 1

    consolidate_ocr_artifacts(run_root)
    results = ocr_search("q1", "cong hoa viet nam", "ocr-run", run_root, 10)
    # Low-confidence records are retained as raw evidence but not indexed by default.
    assert results == []
    results = ocr_search("q2", "AIC 2026", "ocr-run", run_root, 10)
    assert results
    assert results[0].source == "ocr"
    assert results[0].provenance["crop_evidence_path"]

    # Corrupt one crop: only that frame should be processed again.
    crop = run_root / first.detections[1].crop_evidence_path
    crop.write_bytes(b"corrupt")
    third = run_ocr_video(frames, run_root, adapter, settings.ocr)
    assert third.processed_frames == 1
    assert third.resumed_frames == 1
    assert len(adapter.calls) == 2
