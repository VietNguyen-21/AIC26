from pathlib import Path
import pytest
from pydantic import ValidationError

from aic2026.config import APIConfig, KeyframeConfig, MediaConfig, Settings, load_settings

ROOT = Path(__file__).parents[2]


def test_default_and_smoke_profiles_are_strict_and_intentional():
    production, _ = load_settings(ROOT / "configs/default.yaml")
    smoke, _ = load_settings(ROOT / "configs/external_video_smoke.yaml")
    assert production.media.frame_index_backend == "pyav"
    assert production.media.allow_ffmpeg_decode_fallback is False
    assert smoke.media.frame_index_backend == "auto"
    assert smoke.media.allow_ffmpeg_decode_fallback is True
    assert production.corpus.video_id_rule == "relative_path_hash"
    assert production.keyframes.autoshoot_min_loaded_parameter_ratio >= 0.99


def test_unknown_configuration_key_is_rejected():
    with pytest.raises(ValidationError):
        Settings.model_validate({"media": {"frame_indx_backend": "pyav"}})


def test_full_original_frame_index_is_mandatory():
    with pytest.raises(ValidationError):
        MediaConfig(build_full_frame_index=False)


def test_wildcard_cors_with_credentials_is_rejected():
    with pytest.raises(ValidationError):
        APIConfig(cors_origins=["*"], cors_allow_credentials=True)


def test_strict_autoshot_requires_external_paths():
    with pytest.raises(ValidationError):
        KeyframeConfig(shot_model="autoshoot")


def test_unimplemented_embedding_dedup_cannot_be_selected():
    with pytest.raises(ValidationError):
        KeyframeConfig.model_validate({"dedup_method": "embedding"})


def test_selected_tv3_stack_is_locked_in_shared_configs():
    default, _ = load_settings(ROOT / "configs/default.yaml")
    competition, _ = load_settings(ROOT / "configs/competition.example.yaml")
    for settings in (default, competition):
        assert settings.ocr.adapter == "deep_solo_parseq"
        assert settings.asr.vad_adapter == "silero"
        assert settings.asr.adapter == "chunkformer"
        assert settings.object.adapter == "rfdetr"


def test_legacy_production_model_names_are_rejected():
    with pytest.raises(ValidationError):
        Settings.model_validate({"ocr": {"adapter": "tesseract"}})
    with pytest.raises(ValidationError):
        Settings.model_validate({"asr": {"adapter": "faster_whisper"}})
    with pytest.raises(ValidationError):
        Settings.model_validate({"asr": {"vad_adapter": "webrtc"}})
    with pytest.raises(ValidationError):
        Settings.model_validate({"object": {"adapter": "yolo"}})
