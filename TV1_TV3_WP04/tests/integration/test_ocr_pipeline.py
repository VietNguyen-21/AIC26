from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from aic2026.config import load_settings
from aic2026.ocr import BaseOCRAdapter, OCRAdapterResolution
from aic2026.preprocessing import run_preprocessing
from aic2026.utils import read_json, read_jsonl
from aic2026.validation import validate_run


class FixtureOCRAdapter(BaseOCRAdapter):
    name = "fixture_ocr"
    version = "1"

    def recognize_batch(self, image_paths):
        return [
            [
                {
                    "text": "Trường Đại học Tài chính Marketing",
                    "bbox": (0.05, 0.1, 0.95, 0.8),
                    "confidence": 0.99,
                }
            ]
            for _ in image_paths
        ]


@pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe missing",
)
def test_preprocess_wires_ocr_and_resumes_per_frame(tmp_path, monkeypatch):
    source = tmp_path / "raw"
    source.mkdir()
    video = source / "demo.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=white:s=320x180:r=10:d=2",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(video),
        ],
        check=True,
    )
    config_path = Path(__file__).parents[2] / "configs" / "external_video_smoke.yaml"
    settings, _ = load_settings(config_path)
    settings.paths.runs_root = tmp_path / "runs"
    settings.media.create_audio = False
    settings.keyframes.sample_every_ms = 200
    settings.keyframes.max_gap_ms = 500
    settings.ocr.enabled = True
    settings.ocr.adapter = "noop"
    settings.ocr.batch_size = 4
    raw = settings.model_dump(mode="json")
    resolution = OCRAdapterResolution(
        adapter=FixtureOCRAdapter(),
        requested_adapter="fixture",
        selected_adapter="fixture_ocr",
    )
    monkeypatch.setattr("aic2026.preprocessing.make_ocr_adapter", lambda config: resolution)

    first = run_preprocessing(
        source=source,
        run_id="ocr-v1",
        settings=settings,
        raw_config=raw,
        repository_root=tmp_path,
    )
    assert first.errors == []
    run_root = settings.paths.runs_root / "ocr-v1"
    detections = read_jsonl(run_root / "ocr" / "ocr.jsonl")
    assert detections
    assert all(row["crop_evidence_path"] for row in detections)
    assert all((run_root / row["crop_evidence_path"]).is_file() for row in detections)
    report = read_json(run_root / "reports" / "ocr_summary.json")
    assert report["detection_count"] == len(detections)
    assert report["failed_frames"] == 0

    second = run_preprocessing(
        source=source,
        run_id="ocr-v1",
        settings=settings,
        raw_config=raw,
        repository_root=tmp_path,
    )
    assert second.errors == []
    assert second.executed_modules == 0
    validation = validate_run(run_root, settings)
    assert not any(issue.code == "OCR_ARTIFACT_MISSING" for issue in validation.issues)
