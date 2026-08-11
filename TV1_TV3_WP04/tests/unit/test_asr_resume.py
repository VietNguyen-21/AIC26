from __future__ import annotations

import math
import wave
from pathlib import Path

from aic2026.asr import (
    ASRAdapterResolution,
    BaseASRAdapter,
    BaseVADAdapter,
    VADAdapterResolution,
    asr_search,
    consolidate_asr_artifacts,
    run_asr_video,
)
from aic2026.config import Settings
from aic2026.contracts import AudioRecord, MediaRecord
from aic2026.utils import read_json, utcnow_iso


class FixtureVAD(BaseVADAdapter):
    name = "fixture_vad"
    version = "1"

    def detect(self, audio_path, config):
        return [
            {"start_ms": 1000, "end_ms": 3000},
            {"start_ms": 5000, "end_ms": 7000},
        ]


class CountingASR(BaseASRAdapter):
    name = "fixture_asr"
    version = "1"

    def __init__(self):
        self.calls: list[str] = []

    def transcribe(self, audio_path, config):
        self.calls.append(audio_path)
        return [
            {
                "start_ms": 100,
                "end_ms": 900,
                "text": "Cộng hòa Việt Nam",
                "language": "vi",
                "language_probability": 0.98,
                "avg_logprob": -0.2,
                "no_speech_probability": 0.01,
                "words": [
                    {"start_ms": 100, "end_ms": 350, "word": "Cộng", "probability": 0.9},
                    {"start_ms": 360, "end_ms": 900, "word": "hòa Việt Nam", "probability": 0.8},
                ],
            }
        ]


def write_wav(path: Path, duration_ms: int = 8000, rate: int = 16000):
    path.parent.mkdir(parents=True, exist_ok=True)
    frames = bytearray()
    for index in range(int(rate * duration_ms / 1000)):
        value = int(5000 * math.sin(2 * math.pi * 440 * index / rate))
        frames.extend(int(value).to_bytes(2, "little", signed=True))
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(bytes(frames))


def make_records(tmp_path: Path):
    audio_path = tmp_path / "audio.wav"
    write_wav(audio_path)
    media = MediaRecord(
        preprocess_run_id="asr-run",
        video_id="V1",
        original_video_path=str(tmp_path / "video.mp4"),
        source_sha256="a" * 64,
        duration_ms=8000,
        width_px=320,
        height_px=180,
        has_audio=True,
        created_at_utc=utcnow_iso(),
    )
    from aic2026.utils import sha256_file

    audio = AudioRecord(
        preprocess_run_id="asr-run",
        video_id="V1",
        audio_path=str(audio_path),
        audio_sha256=sha256_file(audio_path),
        sample_rate_hz=16000,
        channels=1,
        duration_ms=8000,
        status="ready",
        created_at_utc=utcnow_iso(),
    )
    return media, audio


def test_asr_segment_resume_absolute_timeline_and_search(tmp_path):
    media, audio = make_records(tmp_path)
    settings = Settings()
    settings.asr.enabled = True
    settings.asr.adapter = "noop"
    settings.asr.vad_adapter = "none"
    settings.asr.segment_max_ms = 30000
    settings.asr.segment_overlap_ms = 1000
    adapter = CountingASR()
    vad = FixtureVAD()
    run_root = tmp_path / "run"
    asr_resolution = ASRAdapterResolution(adapter, "fixture", "fixture_asr")
    vad_resolution = VADAdapterResolution(vad, "fixture", "fixture_vad")

    first = run_asr_video(
        media,
        audio,
        run_root,
        adapter,
        vad,
        settings.asr,
        asr_resolution=asr_resolution,
        vad_resolution=vad_resolution,
    )
    assert first.processed_segments == 2
    assert first.resumed_segments == 0
    assert len(adapter.calls) == 2
    assert first.segments[0].start_ms == 1100
    assert first.segments[0].end_ms == 1900
    assert first.segments[0].words[0].start_ms == 1100
    assert first.segments[0].normalized_text == "cộng hòa việt nam"
    assert first.segments[0].normalized_text_no_diacritics == "cong hoa viet nam"

    second = run_asr_video(
        media,
        audio,
        run_root,
        adapter,
        vad,
        settings.asr,
        asr_resolution=asr_resolution,
        vad_resolution=vad_resolution,
    )
    assert second.processed_segments == 0
    assert second.resumed_segments == 2
    assert len(adapter.calls) == 2

    consolidate_asr_artifacts(run_root)
    results = asr_search("q1", "cong hoa viet nam", "asr-run", run_root, 10)
    assert results
    assert results[0].source == "asr"
    assert results[0].window_start_ms == 1100
    assert results[0].window_end_ms == 1900

    # Corrupt exactly one per-segment manifest: only that chunk is transcribed again.
    manifests = sorted((run_root / "asr" / "segments" / "V1").glob("*.json"))
    manifests[0].write_text("{}", encoding="utf-8")
    third = run_asr_video(
        media,
        audio,
        run_root,
        adapter,
        vad,
        settings.asr,
        asr_resolution=asr_resolution,
        vad_resolution=vad_resolution,
    )
    assert third.processed_segments == 1
    assert third.resumed_segments == 1
    assert len(adapter.calls) == 3
    report = read_json(run_root / "reports" / "asr" / "V1.json")
    assert report["failed_segments"] == 0


def test_no_audio_is_valid_and_produces_empty_artifacts(tmp_path):
    media = MediaRecord(
        preprocess_run_id="asr-run",
        video_id="V0",
        original_video_path=str(tmp_path / "video.mp4"),
        source_sha256="b" * 64,
        duration_ms=1000,
        width_px=64,
        height_px=64,
        has_audio=False,
        created_at_utc=utcnow_iso(),
    )
    audio = AudioRecord(
        preprocess_run_id="asr-run",
        video_id="V0",
        status="no_audio",
        created_at_utc=utcnow_iso(),
    )
    settings = Settings()
    adapter = CountingASR()
    vad = FixtureVAD()
    result = run_asr_video(media, audio, tmp_path / "run", adapter, vad, settings.asr)
    assert result.status == "no_audio"
    assert result.segments == []
    assert (tmp_path / "run" / "asr" / "by_video" / "V0.jsonl").is_file()


class OOMThenSingleASR(CountingASR):
    def transcribe_batch(self, audio_paths, config):
        if len(audio_paths) > 1:
            raise RuntimeError("CUDA out of memory")
        return super().transcribe_batch(audio_paths, config)


def test_adaptive_asr_batch_reduces_after_oom_and_records_metrics(tmp_path):
    media, audio = make_records(tmp_path)
    settings = Settings()
    settings.asr.enabled = True
    settings.asr.batch_size = 8
    settings.asr.min_batch_size = 1
    settings.asr.max_oom_retries = 4
    settings.asr.allow_cpu_fallback = False
    adapter = OOMThenSingleASR()
    vad = FixtureVAD()
    run_root = tmp_path / "run"

    result = run_asr_video(media, audio, run_root, adapter, vad, settings.asr)
    assert result.processed_segments == 2
    report = read_json(run_root / "reports" / "asr" / "V1.json")
    assert report["initial_batch_size"] == 2
    assert report["final_batch_size"] == 1
    assert report["oom_retry_count"] == 1
    assert report["cpu_fallback_used"] is False
    assert report["segments_per_second"] > 0
    assert report["audio_realtime_factor"] >= 0
