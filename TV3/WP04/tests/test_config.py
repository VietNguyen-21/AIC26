from pathlib import Path

from wp04.config import load_config


def test_default_config_declares_pipeline_models_and_vad_fingerprint_settings():
    config = load_config(Path(__file__).parents[1] / "configs" / "default.yaml")
    assert config["modalities"]["ocr"]["model"]["name"] == "deepsolo-parseq-vn"
    assert config["modalities"]["asr"]["vad"]["threshold"] == 0.5
    assert config["modalities"]["object"]["model"]["name"] == "rf-detr"
    assert config["modalities"]["ocr"]["model"]["factory"] == "wp04.runtime_adapters:build_ocr_adapter"
