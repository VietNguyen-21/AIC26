from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from aic2026.config import Settings
from aic2026.contracts import FrameRecord
from aic2026.objects import BaseObjectAdapter, consolidate_object_artifacts, object_search, run_object_video
from aic2026.utils import utcnow_iso


class CountingObjectAdapter(BaseObjectAdapter):
    name = "fixture_detector"
    version = "1"

    def __init__(self):
        self.calls: list[list[str]] = []

    def detect_batch(self, image_paths):
        self.calls.append(list(image_paths))
        outputs = []
        for index, _ in enumerate(image_paths):
            if index == 0:
                outputs.append(
                    [
                        {"label": "person", "class_id": 0, "confidence": 0.95, "bbox": (0.05, 0.2, 0.25, 0.8)},
                        {"label": "person", "class_id": 0, "confidence": 0.90, "bbox": (0.30, 0.2, 0.48, 0.8)},
                        {"label": "car", "class_id": 2, "confidence": 0.88, "bbox": (0.70, 0.55, 0.95, 0.90)},
                    ]
                )
            else:
                outputs.append(
                    [
                        {"label": "cell phone", "class_id": 67, "confidence": 0.15, "bbox": (0.45, 0.40, 0.55, 0.60)},
                    ]
                )
        return outputs


def make_frames(tmp_path: Path) -> list[FrameRecord]:
    frames: list[FrameRecord] = []
    for index in range(2):
        path = tmp_path / f"frame-{index}.jpg"
        image = np.full((100, 200, 3), 255, dtype=np.uint8)
        assert cv2.imwrite(str(path), image)
        frames.append(
            FrameRecord(
                preprocess_run_id="object-run",
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


def test_object_resume_count_spatial_relation_and_low_confidence(tmp_path):
    frames = make_frames(tmp_path)
    settings = Settings()
    settings.object.enabled = True
    settings.object.adapter = "noop"
    settings.object.batch_size = 2
    settings.object.confidence_threshold = 0.25
    settings.object.keep_raw_below_threshold = True
    adapter = CountingObjectAdapter()
    run_root = tmp_path / "run"

    first = run_object_video(frames, run_root, adapter, settings.object)
    assert first.processed_frames == 2
    assert first.resumed_frames == 0
    assert len(first.detections) == 4
    people = [item for item in first.detections if item.canonical_label == "person"]
    assert len(people) == 2
    assert all(item.count_in_frame == 2 for item in people)
    assert people[0].spatial_region in {"left", "bottom_left"}
    phone = next(item for item in first.detections if item.canonical_label == "cell phone")
    assert phone.below_threshold is True
    assert phone.count_in_frame == 0
    assert phone.raw_count_in_frame == 1
    assert len(adapter.calls) == 1

    second = run_object_video(frames, run_root, adapter, settings.object)
    assert second.processed_frames == 0
    assert second.resumed_frames == 2
    assert len(adapter.calls) == 1

    consolidate_object_artifacts(run_root)
    count_results = object_search("q1", "hai người", "object-run", run_root, 10)
    assert count_results
    assert count_results[0].frame_id == 0
    assert count_results[0].provenance["evidence"]["count_ok"] is True
    assert count_results[0].provenance["submittable"] is True
    assert count_results[0].provenance["localization_required"] is False
    assert count_results[0].provenance["frame_resolution"] == "source_keyframe"
    assert count_results[0].confidence == 0.95

    relation_results = object_search("q2", "person left of car", "object-run", run_root, 10)
    assert relation_results
    assert relation_results[0].provenance["evidence"]["relation_ok"] is True

    # Low-confidence phone is kept for audit but excluded from retrieval.
    assert object_search("q3", "điện thoại", "object-run", run_root, 10) == []


class ConfidenceOrderAdapter(BaseObjectAdapter):
    name = "confidence_order_fixture"
    version = "1"

    def detect_batch(self, image_paths):
        return [
            [
                {"label": "weak", "confidence": 0.10, "bbox": (0.0, 0.0, 0.1, 0.1)},
                {"label": "medium", "confidence": 0.20, "bbox": (0.1, 0.1, 0.2, 0.2)},
                {"label": "strong", "confidence": 0.95, "bbox": (0.2, 0.2, 0.3, 0.3)},
            ]
            for _ in image_paths
        ]


class MixedConfidenceCountAdapter(BaseObjectAdapter):
    name = "mixed_count_fixture"
    version = "1"

    def detect_batch(self, image_paths):
        return [
            [
                {"label": "person", "confidence": 0.95, "bbox": (0.0, 0.0, 0.2, 0.8)},
                {"label": "person", "confidence": 0.10, "bbox": (0.3, 0.0, 0.5, 0.8)},
                {"label": "person", "confidence": 0.05, "bbox": (0.6, 0.0, 0.8, 0.8)},
            ]
            for _ in image_paths
        ]


def test_object_limit_keeps_highest_confidence_detections(tmp_path):
    frame = make_frames(tmp_path)[0]
    settings = Settings()
    settings.object.enabled = True
    settings.object.confidence_threshold = 0.0
    settings.object.max_detections_per_frame = 2
    result = run_object_video([frame], tmp_path / "run-order", ConfidenceOrderAdapter(), settings.object)
    assert {item.canonical_label for item in result.detections} == {"strong", "medium"}
    assert sorted((item.confidence for item in result.detections), reverse=True) == [0.95, 0.20]


def test_object_count_excludes_below_threshold_detections(tmp_path):
    frame = make_frames(tmp_path)[0]
    settings = Settings()
    settings.object.enabled = True
    settings.object.confidence_threshold = 0.25
    settings.object.keep_raw_below_threshold = True
    result = run_object_video([frame], tmp_path / "run-count", MixedConfidenceCountAdapter(), settings.object)
    assert len(result.detections) == 3
    assert {item.raw_count_in_frame for item in result.detections} == {3}
    assert {item.count_in_frame for item in result.detections} == {1}
    assert sum(not item.below_threshold for item in result.detections) == 1
