from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from aic2026 import model_certification
from aic2026.config import Settings
from aic2026.utils import sha256_file


def test_path_hash_directory_and_errors(tmp_path: Path):
    directory = tmp_path / "model"
    directory.mkdir()
    (directory / "a.bin").write_bytes(b"a")
    (directory / "b.bin").write_bytes(b"b")
    assert len(model_certification._path_hash(directory)) == 64
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(model_certification.ModelCertificationError, match="empty"):
        model_certification._path_hash(empty)
    with pytest.raises(model_certification.ModelCertificationError, match="does not exist"):
        model_certification._path_hash(tmp_path / "missing")


def test_checkpoint_result_none_file_and_mismatch(tmp_path: Path):
    assert model_certification._checkpoint_result(None, None)["matches"] is False
    path = tmp_path / "checkpoint.bin"
    path.write_bytes(b"model")
    actual = sha256_file(path)
    assert model_certification._checkpoint_result(path, actual)["matches"] is True
    assert model_certification._checkpoint_result(path, "0" * 64)["matches"] is False


def test_full_competition_certification_with_selected_fake_adapters(tmp_path: Path, monkeypatch):
    ocr_ckpt = tmp_path / "ocr.bin"
    ocr_ckpt.write_bytes(b"ocr")
    asr_ckpt = tmp_path / "asr.bin"
    asr_ckpt.write_bytes(b"asr")
    object_ckpt = tmp_path / "object.bin"
    object_ckpt.write_bytes(b"object")

    settings = Settings.model_validate(
        {
            "runtime": {"profile": "competition"},
            "ocr": {
                "enabled": True,
                "adapter": "deep_solo_parseq",
                "deep_solo_parseq_checkpoint_path": str(ocr_ckpt),
                "deep_solo_parseq_command": ["python", "ocr_bridge.py"],
                "checkpoint_sha256": sha256_file(ocr_ckpt),
                "allow_runtime_downloads": False,
            },
            "asr": {
                "enabled": True,
                "adapter": "chunkformer",
                "vad_adapter": "silero",
                "chunkformer_checkpoint_path": str(asr_ckpt),
                "chunkformer_command": ["python", "chunkformer_bridge.py"],
                "checkpoint_sha256": sha256_file(asr_ckpt),
                "allow_runtime_downloads": False,
            },
            "object": {
                "enabled": True,
                "adapter": "rfdetr",
                "rfdetr_checkpoint_path": str(object_ckpt),
                "checkpoint_sha256": sha256_file(object_ckpt),
                "allow_runtime_downloads": False,
            },
        }
    )

    def resolution(name: str):
        return SimpleNamespace(
            selected_adapter=name, adapter=SimpleNamespace(version="fixture-real-1")
        )

    monkeypatch.setattr(
        model_certification, "make_ocr_adapter", lambda config: resolution("deep_solo_parseq")
    )
    monkeypatch.setattr(
        model_certification, "make_asr_adapter", lambda config: resolution("chunkformer")
    )
    monkeypatch.setattr(
        model_certification, "make_vad_adapter", lambda config: resolution("silero")
    )
    monkeypatch.setattr(
        model_certification, "make_object_adapter", lambda config: resolution("rfdetr")
    )
    monkeypatch.setattr(
        model_certification, "_gpu_info", lambda: {"cuda_available": True, "device_name": "fixture"}
    )

    output = tmp_path / "certification.json"
    report = model_certification.certify_models(settings, load_models=True, output_path=output)
    assert report["acceptance"] == {
        "selected_stack_only": True,
        "runtime_downloads_disabled": True,
        "checkpoint_hashes_verified": True,
        "external_bridges_configured": True,
        "real_adapter_load_passed": True,
        "all_modalities_enabled": True,
        "competition_ready": True,
    }
    assert report["modules"]["asr"]["selected_adapter"] == "chunkformer"
    assert report["modules"]["asr"]["selected_vad_adapter"] == "silero"
    assert output.is_file()


def test_certification_records_ocr_adapter_load_failure(tmp_path: Path, monkeypatch):
    checkpoint = tmp_path / "ocr.bin"
    checkpoint.write_bytes(b"ocr")
    settings = Settings()
    settings.ocr.deep_solo_parseq_checkpoint_path = checkpoint
    settings.ocr.deep_solo_parseq_command = ["python", "ocr_bridge.py"]
    settings.ocr.enabled = True
    monkeypatch.setattr(
        model_certification,
        "make_ocr_adapter",
        lambda config: (_ for _ in ()).throw(RuntimeError("adapter broken")),
    )
    report = model_certification.certify_models(settings, load_models=True)
    assert report["modules"]["ocr"]["load_status"] == "failed"
    assert "adapter broken" in report["modules"]["ocr"]["error"]
    assert report["acceptance"]["competition_ready"] is False


def test_asr_and_object_adapter_failures_are_reported(tmp_path: Path, monkeypatch):
    model = tmp_path / "model.bin"
    model.write_bytes(b"model")
    settings = Settings()
    settings.asr.chunkformer_checkpoint_path = model
    settings.asr.chunkformer_command = ["python", "chunkformer_bridge.py"]
    settings.asr.enabled = True
    settings.object.rfdetr_checkpoint_path = model
    settings.object.enabled = True
    monkeypatch.setattr(
        model_certification,
        "make_asr_adapter",
        lambda config: (_ for _ in ()).throw(RuntimeError("asr fail")),
    )
    monkeypatch.setattr(
        model_certification,
        "make_object_adapter",
        lambda config: (_ for _ in ()).throw(RuntimeError("object fail")),
    )
    report = model_certification.certify_models(settings, load_models=True)
    assert report["modules"]["asr"]["load_status"] == "failed"
    assert report["modules"]["object"]["load_status"] == "failed"
