from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from aic2026.asr import (
    ASRAdapterResolution,
    BaseASRAdapter,
    BaseVADAdapter,
    VADAdapterResolution,
    asr_search,
)
from aic2026.config import load_settings
from aic2026.preprocessing import run_preprocessing
from aic2026.utils import read_json, read_jsonl
from aic2026.validation import validate_run


class FixtureVAD(BaseVADAdapter):
    name = "fixture_vad"
    version = "1"

    def detect(self, audio_path, config):
        return [{"start_ms": 250, "end_ms": 1750}]


class FixtureASR(BaseASRAdapter):
    name = "fixture_asr"
    version = "1"

    def transcribe(self, audio_path, config):
        return [
            {
                "start_ms": 100,
                "end_ms": 1000,
                "text": "Xin chào AIC 2026",
                "language": "vi",
                "language_probability": 0.99,
                "avg_logprob": -0.1,
            }
        ]


@pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe missing",
)
def test_preprocess_wires_asr_vad_temporal_linkage_and_resume(tmp_path, monkeypatch):
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
            "color=c=blue:s=320x180:d=2",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=2:sample_rate=16000",
            "-shortest",
            "-r",
            "10",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            str(video),
        ],
        check=True,
    )
    config_path = Path(__file__).parents[2] / "configs" / "external_video_smoke.yaml"
    settings, _ = load_settings(config_path)
    settings.paths.runs_root = tmp_path / "runs"
    settings.asr.enabled = True
    settings.asr.adapter = "noop"
    settings.asr.vad_adapter = "none"
    settings.ocr.enabled = False
    raw = settings.model_dump(mode="json")
    monkeypatch.setattr(
        "aic2026.preprocessing.make_asr_adapter",
        lambda config: ASRAdapterResolution(FixtureASR(), "fixture", "fixture_asr"),
    )
    monkeypatch.setattr(
        "aic2026.preprocessing.make_vad_adapter",
        lambda config: VADAdapterResolution(FixtureVAD(), "fixture", "fixture_vad"),
    )

    first = run_preprocessing(
        source=source,
        run_id="asr-v1",
        settings=settings,
        raw_config=raw,
        repository_root=tmp_path,
    )
    assert first.errors == []
    run_root = settings.paths.runs_root / "asr-v1"
    segments = read_jsonl(run_root / "asr" / "asr.jsonl")
    assert len(segments) == 1
    assert segments[0]["start_ms"] == 350
    assert segments[0]["end_ms"] == 1250
    links = read_jsonl(run_root / "temporal" / "asr_links.jsonl")
    assert links and links[0]["segment_id"] == segments[0]["segment_id"]
    candidates = asr_search("q-asr", "xin chao aic", "asr-v1", run_root, 10)
    assert candidates
    assert candidates[0].representative_frame_id is not None
    assert candidates[0].frame_id == candidates[0].representative_frame_id
    assert "temporal_registry" in candidates[0].provenance_sources
    summary = read_json(run_root / "reports" / "asr_summary.json")
    assert summary["failed_segments"] == 0
    assert summary["transcript_segment_count"] == 1

    second = run_preprocessing(
        source=source,
        run_id="asr-v1",
        settings=settings,
        raw_config=raw,
        repository_root=tmp_path,
    )
    assert second.errors == []
    assert second.executed_modules == 0
    report = validate_run(run_root, settings)
    assert not any(issue.code.startswith("ASR_") for issue in report.issues)
