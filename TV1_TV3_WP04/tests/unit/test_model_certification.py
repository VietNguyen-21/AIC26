from __future__ import annotations

from pathlib import Path

from aic2026.config import Settings
from aic2026.model_certification import certify_models


def test_default_selected_stack_is_explicit_but_disabled(tmp_path: Path):
    settings = Settings()
    report = certify_models(settings, output_path=tmp_path / "report.json")
    assert report["selected_stack"] == {
        "ocr": "deep_solo_parseq",
        "asr": "chunkformer",
        "vad": "silero",
        "object": "rfdetr",
    }
    assert report["acceptance"]["selected_stack_only"] is True
    assert report["acceptance"]["runtime_downloads_disabled"] is True
    assert report["acceptance"]["all_modalities_enabled"] is False
    assert report["acceptance"]["competition_ready"] is False
    assert (tmp_path / "report.json").is_file()


def test_missing_chunkformer_checkpoint_is_reported(tmp_path: Path):
    settings = Settings()
    settings.asr.adapter = "chunkformer"
    settings.asr.chunkformer_checkpoint_path = tmp_path / "missing-model.pt"
    settings.asr.chunkformer_command = ["python", "chunkformer_bridge.py"]
    settings.asr.checkpoint_sha256 = "a" * 64
    settings.asr.enabled = True
    report = certify_models(settings)
    checkpoint = report["modules"]["asr"]["checkpoint"]
    assert checkpoint["exists"] is False
    assert checkpoint["matches"] is False
    assert report["acceptance"]["checkpoint_hashes_verified"] is False
