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
)
from aic2026.config import load_settings
from aic2026.objects import BaseObjectAdapter, ObjectAdapterResolution
from aic2026.ocr import BaseOCRAdapter, OCRAdapterResolution
from aic2026.preprocessing import run_preprocessing
from aic2026.registry import RegistryError, RunRegistry
from aic2026.text_index import load_text_index_adapter, text_hits_to_candidates
from aic2026.utils import read_json, read_jsonl


class FixtureOCR(BaseOCRAdapter):
    name = "fixture_ocr"
    version = "1"

    def recognize_batch(self, image_paths):
        return [
            [
                {
                    "text": "Học bổng AIC Việt Nam",
                    "bbox": (0.05, 0.10, 0.95, 0.85),
                    "confidence": 0.99,
                }
            ]
            for _ in image_paths
        ]


class FixtureVAD(BaseVADAdapter):
    name = "fixture_vad"
    version = "1"

    def detect(self, audio_path, config):
        return [{"start_ms": 100, "end_ms": 900}]


class FixtureASR(BaseASRAdapter):
    name = "fixture_asr"
    version = "1"

    def transcribe(self, audio_path, config):
        return [
            {
                "start_ms": 0,
                "end_ms": 700,
                "text": "xin chào cuộc thi aic",
                "language": "vi",
                "language_probability": 0.99,
                "avg_logprob": -0.05,
            }
        ]


class FixtureObject(BaseObjectAdapter):
    name = "fixture_object"
    version = "1"

    def detect_batch(self, image_paths):
        return [
            [
                {
                    "label": "person",
                    "confidence": 0.95,
                    "bbox": (0.20, 0.10, 0.80, 0.95),
                }
            ]
            for _ in image_paths
        ]


@pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe missing",
)
def test_full_tv1_to_tv3_handoff_resume_and_selective_recompute(tmp_path, monkeypatch):
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
            "color=c=white:s=256x144:d=1.2",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=1.2:sample_rate=16000",
            "-shortest",
            "-r",
            "8",
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
    settings.keyframes.sample_every_ms = 200
    settings.keyframes.max_gap_ms = 1000
    settings.ocr.enabled = True
    settings.ocr.adapter = "noop"
    settings.asr.enabled = True
    settings.asr.adapter = "noop"
    settings.asr.vad_adapter = "none"
    settings.object.enabled = True
    settings.object.adapter = "noop"
    settings.metadata.organizer_youtube_enabled = False
    settings.metadata.technical_enabled = True
    settings.text_index.enabled = True
    settings.text_index.adapter = "local_bm25"
    settings.text_index.fail_open = False

    monkeypatch.setattr(
        "aic2026.preprocessing.make_ocr_adapter",
        lambda config: OCRAdapterResolution(FixtureOCR(), "fixture", "fixture_ocr"),
    )
    monkeypatch.setattr(
        "aic2026.preprocessing.make_asr_adapter",
        lambda config: ASRAdapterResolution(FixtureASR(), "fixture", "fixture_asr"),
    )
    monkeypatch.setattr(
        "aic2026.preprocessing.make_vad_adapter",
        lambda config: VADAdapterResolution(FixtureVAD(), "fixture", "fixture_vad"),
    )
    monkeypatch.setattr(
        "aic2026.preprocessing.make_object_adapter",
        lambda config: ObjectAdapterResolution(FixtureObject(), "fixture", "fixture_object"),
    )

    raw = settings.model_dump(mode="json")
    first = run_preprocessing(
        source=source,
        run_id="tv1-tv3",
        settings=settings,
        raw_config=raw,
        repository_root=tmp_path,
    )
    assert first.errors == []

    run_root = settings.paths.runs_root / "tv1-tv3"
    assert read_jsonl(run_root / "ocr" / "ocr.jsonl")
    assert read_jsonl(run_root / "asr" / "asr.jsonl")
    assert read_jsonl(run_root / "objects" / "objects.jsonl")
    assert read_jsonl(run_root / "metadata" / "metadata.jsonl")
    assert (run_root / "text_index" / "local_bm25.sqlite3").is_file()
    handoff = read_json(run_root / "handoff_tv1_tv3.json")
    assert handoff["candidate_policy"] == {
        "ocr": "exact_source_frame_submittable",
        "asr": "requires_temporal_resolution_before_submit",
        "metadata": "video_soft_boost_only_not_submittable",
        "object": "exact_source_frame_soft_constraint_submittable",
    }

    adapter, manifest = load_text_index_adapter(run_root, settings)
    hits = adapter.search("hoc bong aic", 10)
    candidates = text_hits_to_candidates(
        "q1",
        "tv1-tv3",
        run_root,
        hits,
        adapter_name=manifest.selected_adapter,
        manifest=manifest,
    )
    assert candidates
    ocr_candidates = [item for item in candidates if item.source == "ocr"]
    assert ocr_candidates
    assert all(item.provenance["submittable"] is True for item in ocr_candidates)
    assert all(
        item.provenance["localization_required"] is False for item in ocr_candidates
    )
    assert all(
        item.provenance["frame_resolution"] == "source_keyframe"
        for item in ocr_candidates
    )

    second = run_preprocessing(
        source=source,
        run_id="tv1-tv3",
        settings=settings,
        raw_config=raw,
        repository_root=tmp_path,
    )
    assert second.errors == []
    assert second.executed_modules == 0

    registry_path = run_root / "registry" / "run_registry.sqlite3"
    video_id = read_jsonl(run_root / "corpus_manifest.jsonl")[0]["video_id"]
    with RunRegistry(registry_path) as registry:
        before = {
            name: registry.get_status("tv1-tv3", video_id, name).attempt_count
            for name in ("media_probe", "frame_index", "keyframes", "ocr", "asr", "object")
        }

    settings.ocr.confidence_threshold = 1.0
    changed = run_preprocessing(
        source=source,
        run_id="tv1-tv3",
        settings=settings,
        raw_config=settings.model_dump(mode="json"),
        repository_root=tmp_path,
    )
    assert changed.errors == []

    with RunRegistry(registry_path) as registry:
        after = {
            name: registry.get_status("tv1-tv3", video_id, name).attempt_count
            for name in ("media_probe", "frame_index", "keyframes", "ocr", "asr", "object")
        }
    assert after["ocr"] == before["ocr"] + 1
    assert after["media_probe"] == before["media_probe"]
    assert after["frame_index"] == before["frame_index"]
    assert after["keyframes"] == before["keyframes"]
    assert after["asr"] == before["asr"]
    assert after["object"] == before["object"]


def test_stable_run_rejects_tv3_mutation(tmp_path):
    registry_path = tmp_path / "run" / "registry" / "run_registry.sqlite3"
    with RunRegistry(registry_path) as registry:
        registry.register_run(
            "stable-run",
            status="stable",
            source_manifest_sha256="a" * 64,
            config_sha256="b" * 64,
            details={"stable": True},
        )
        with pytest.raises(RegistryError, match="stable and immutable"):
            registry.assert_run_mutable("stable-run")
