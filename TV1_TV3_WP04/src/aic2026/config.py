"""Strict configuration for the integrated TV1 + TV3 WP04 source release."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictConfigModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class Device(StrEnum):
    AUTO = "auto"
    CPU = "cpu"
    CUDA = "cuda"


class CorpusConfig(StrictConfigModel):
    video_glob: str = "**/*.mp4"
    video_id_rule: Literal["stem", "relative_path_hash"] = "relative_path_hash"
    batch_id: str | None = "local"
    max_archive_members: int = Field(default=10000, ge=1, le=1_000_000)
    max_archive_uncompressed_bytes: int = Field(
        default=500 * 1024**3, ge=1, le=10 * 1024**4
    )
    max_archive_compression_ratio: float = Field(default=200.0, ge=1.0, le=100000.0)

    @field_validator("video_glob")
    @classmethod
    def non_empty_glob(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("video_glob must not be empty")
        return value


class MediaConfig(StrictConfigModel):
    ffprobe_timeout_seconds: int = Field(default=120, ge=1, le=3600)
    decode_probe_points: int = Field(default=5, ge=1, le=100)
    create_audio: bool = True
    audio_sample_rate_hz: int = Field(default=16000, ge=8000, le=192000)
    create_proxy: bool = False
    build_full_frame_index: bool = True
    frame_index_backend: Literal["pyav", "ffprobe", "auto"] = "pyav"
    allow_ffmpeg_decode_fallback: bool = False
    frame_index_timeout_seconds: int = Field(default=3600, ge=1, le=86400)
    pts_timestamp_tolerance_ms: int = Field(default=2, ge=0, le=1000)
    audio_duration_tolerance_ms: int = Field(default=1500, ge=0, le=60000)

    @model_validator(mode="after")
    def production_truth_requirements(self):
        if not self.build_full_frame_index:
            raise ValueError("TV1 preprocessing requires build_full_frame_index=true")
        return self


class KeyframeConfig(StrictConfigModel):
    strategy: Literal[
        "uniform", "shot_only", "shot_max_gap", "hybrid_shot_max_gap"
    ] = "hybrid_shot_max_gap"
    shot_model: Literal[
        "autoshoot", "autoshoot_or_fallback", "pyscenedetect", "histogram"
    ] = "autoshoot_or_fallback"
    sample_every_ms: int = Field(default=500, ge=20, le=60000)
    shot_threshold: float = Field(default=0.48, gt=0.0, le=1.0)
    max_gap_ms: int = Field(default=5000, ge=100)
    min_shot_ms: int = Field(default=500, ge=0)
    representative_policy: Literal["quality_center", "center", "first", "last"] = (
        "quality_center"
    )
    representative_search_radius_ms: int = Field(default=600, ge=0, le=10000)
    representative_candidate_step_ms: int = Field(default=200, ge=1, le=5000)
    representative_candidate_cache_size: int = Field(default=64, ge=1, le=4096)
    boundary_guard_ms: int = Field(default=250, ge=0, le=10000)
    dedup_method: Literal["none", "dhash", "phash"] = "dhash"
    dedup_threshold: int = Field(default=8, ge=0, le=64)
    dedup_temporal_window_ms: int = Field(default=15000, ge=0, le=3600000)
    thumbnail_width: int = Field(default=320, ge=32, le=4096)

    autoshoot_repo_root: Path | None = None
    autoshoot_checkpoint_path: Path | None = None
    autoshoot_model_filename: str = "supernet_flattransf_3_8_8_8_13_12_0_16_60.py"
    autoshoot_checkpoint_key: str = "net"
    autoshoot_threshold: float = Field(default=0.296, gt=0.0, le=1.0)
    autoshoot_device: Device = Device.AUTO
    autoshoot_min_loaded_parameter_ratio: float = Field(default=0.99, gt=0.0, le=1.0)

    pyscenedetect_threshold: float = Field(default=27.0, gt=0.0, le=255.0)
    pyscenedetect_min_scene_len_frames: int = Field(default=15, ge=1, le=100000)

    quality_sharpness_weight: float = Field(default=1.0, ge=0.0, le=100.0)
    quality_black_weight: float = Field(default=5.0, ge=0.0, le=100.0)
    quality_blur_weight: float = Field(default=1.0, ge=0.0, le=100.0)
    quality_face_weight: float = Field(default=0.0, ge=0.0, le=100.0)
    quality_text_weight: float = Field(default=0.0, ge=0.0, le=100.0)
    quality_center_bias: float = Field(default=0.25, ge=0.0, le=100.0)

    @field_validator("autoshoot_model_filename", "autoshoot_checkpoint_key")
    @classmethod
    def non_empty_autoshot_identifier(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("AutoShot identifiers must not be empty")
        return value

    @model_validator(mode="after")
    def validate_spacing_and_model(self):
        if self.max_gap_ms < self.min_shot_ms:
            raise ValueError("max_gap_ms must be >= min_shot_ms")
        if (
            self.representative_search_radius_ms > 0
            and self.representative_candidate_step_ms
            > 2 * self.representative_search_radius_ms
        ):
            raise ValueError(
                "representative_candidate_step_ms is too large for the search radius"
            )
        if self.shot_model == "autoshoot" and (
            self.autoshoot_repo_root is None or self.autoshoot_checkpoint_path is None
        ):
            raise ValueError(
                "shot_model='autoshoot' requires autoshoot_repo_root and checkpoint"
            )
        return self



class OCRConfig(StrictConfigModel):
    """Selected OCR stack: DeepSolo detector + PARSeq recognizer.

    The heavy upstream repositories/checkpoints stay outside this source-only
    repository. ``noop`` is retained only for deterministic unit/integration
    fixtures and is forbidden for an enabled competition profile.
    """

    enabled: bool = False
    adapter: Literal["deep_solo_parseq", "noop"] = "deep_solo_parseq"
    device: Literal["auto", "cpu", "cuda"] = "auto"
    batch_size: int = Field(default=8, ge=1, le=512)
    confidence_threshold: float = Field(default=0.25, ge=0.0, le=1.0)
    keep_raw_below_threshold: bool = True
    crop_evidence: bool = True
    crop_padding_px: int = Field(default=4, ge=0, le=128)
    frame_resume: bool = True
    fail_fast: bool = False
    character_ngram_min: int = Field(default=2, ge=1, le=8)
    character_ngram_max: int = Field(default=4, ge=1, le=12)
    max_character_ngrams: int = Field(default=256, ge=1, le=4096)
    deep_solo_parseq_checkpoint_path: Path | None = None
    deep_solo_parseq_command: list[str] = Field(default_factory=list)
    deep_solo_parseq_timeout_seconds: int = Field(default=120, ge=1, le=3600)
    checkpoint_sha256: str | None = None
    allow_runtime_downloads: bool = False

    @model_validator(mode="after")
    def validate_ocr_options(self):
        if self.character_ngram_min > self.character_ngram_max:
            raise ValueError("character_ngram_min must be <= character_ngram_max")
        return self


class ASRConfig(StrictConfigModel):
    """Selected speech stack: Silero VAD + ChunkFormer-CTC-Large-Vie bridge."""

    enabled: bool = False
    adapter: Literal["chunkformer", "noop"] = "chunkformer"
    vad_adapter: Literal["silero", "none"] = "silero"
    device: Literal["auto", "cpu", "cuda"] = "auto"
    language: str | None = "vi"
    task: Literal["transcribe"] = "transcribe"
    batch_size: int = Field(default=8, ge=1, le=256)
    min_batch_size: int = Field(default=1, ge=1, le=256)
    max_oom_retries: int = Field(default=4, ge=0, le=20)
    allow_cpu_fallback: bool = False
    vad_threshold: float = Field(default=0.5, ge=0.0, le=1.0)
    vad_min_speech_ms: int = Field(default=250, ge=30, le=60000)
    vad_min_silence_ms: int = Field(default=500, ge=30, le=60000)
    vad_speech_pad_ms: int = Field(default=200, ge=0, le=10000)
    segment_max_ms: int = Field(default=30000, ge=1000, le=600000)
    segment_overlap_ms: int = Field(default=1000, ge=0, le=60000)
    segment_merge_gap_ms: int = Field(default=300, ge=0, le=10000)
    segment_resume: bool = True
    fail_fast: bool = False
    keep_chunk_audio: bool = False
    chunkformer_checkpoint_path: Path | None = None
    chunkformer_command: list[str] = Field(default_factory=list)
    chunkformer_timeout_seconds: int = Field(default=600, ge=1, le=7200)
    checkpoint_sha256: str | None = None
    allow_runtime_downloads: bool = False

    @model_validator(mode="after")
    def validate_asr_options(self):
        if self.segment_overlap_ms >= self.segment_max_ms:
            raise ValueError("segment_overlap_ms must be smaller than segment_max_ms")
        if self.min_batch_size > self.batch_size:
            raise ValueError("min_batch_size must be <= batch_size")
        if self.language is not None and not self.language.strip():
            raise ValueError("language must be null or a non-empty language code")
        return self


class ObjectConfig(StrictConfigModel):
    """Selected object detector: RF-DETR.

    ``noop`` is retained only for deterministic fixtures; production/competition
    runs must use ``rfdetr`` explicitly.
    """

    enabled: bool = False
    adapter: Literal["rfdetr", "noop"] = "rfdetr"
    device: Device = Device.AUTO
    batch_size: int = Field(default=8, ge=1, le=512)
    frame_resume: bool = True
    fail_fast: bool = False
    confidence_threshold: float = Field(default=0.25, ge=0.0, le=1.0)
    keep_raw_below_threshold: bool = True
    max_detections_per_frame: int = Field(default=300, ge=1, le=5000)
    default_mode: Literal["soft_boost", "hard_filter"] = "soft_boost"
    allowed_labels: list[str] = Field(default_factory=list)
    label_aliases: dict[str, list[str]] = Field(default_factory=dict)
    rfdetr_model_name: str = "base"
    rfdetr_checkpoint_path: Path | None = None
    checkpoint_sha256: str | None = None
    allow_runtime_downloads: bool = False

    @field_validator("rfdetr_model_name")
    @classmethod
    def non_empty_rfdetr_model_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("rfdetr_model_name must not be empty")
        return value.strip()

class MetadataConfig(StrictConfigModel):
    technical_enabled: bool = True
    organizer_youtube_enabled: bool = True
    auto_semantic_enabled: bool = False
    organizer_metadata_root: Path = Field(
        default_factory=lambda: Path("data/organizer_support/metadata"),
        json_schema_extra={"default": "data/organizer_support/metadata"},
    )
    organizer_metadata_globs: list[str] = Field(
        default_factory=lambda: ["*.jsonl", "*.json", "*.csv", "*.tsv", "*.xlsx", "*.xlsm"]
    )
    strict_unknown_video: bool = False
    max_unmatched_examples: int = Field(default=20, ge=0, le=1000)

    @field_validator("organizer_metadata_globs")
    @classmethod
    def metadata_globs_not_empty(cls, value: list[str]) -> list[str]:
        if not value or any(not item.strip() for item in value):
            raise ValueError("organizer_metadata_globs must contain non-empty patterns")
        return value


class EvidenceCatalogConfig(StrictConfigModel):
    enabled: bool = True
    database_name: str = "evidence.sqlite3"
    auto_build: bool = True
    fail_open: bool = False
    default_page_size: int = Field(default=100, ge=1, le=1000)
    maximum_page_size: int = Field(default=1000, ge=1, le=10000)

    @model_validator(mode="after")
    def validate_page_sizes(self):
        if self.default_page_size > self.maximum_page_size:
            raise ValueError("default_page_size must be <= maximum_page_size")
        if not self.database_name.strip() or Path(self.database_name).name != self.database_name:
            raise ValueError("database_name must be a simple file name")
        return self

class TextIndexConfig(StrictConfigModel):
    enabled: bool = True
    adapter: Literal["local_bm25", "opensearch", "elasticsearch"] = "local_bm25"
    persistent: bool = True
    index_name: str = "aic2026_text"
    local_database_name: str = "local_bm25.sqlite3"
    auto_build_if_missing: bool = True
    fail_open: bool = True
    allow_local_fallback: bool = True
    include_below_threshold_ocr: bool = False
    k1: float = Field(default=1.5, gt=0.0, le=10.0)
    b: float = Field(default=0.75, ge=0.0, le=1.0)
    exact_phrase_enabled: bool = True
    exact_phrase_boost: float = Field(default=4.0, ge=0.0, le=100.0)
    no_diacritic_boost: float = Field(default=1.0, ge=0.0, le=20.0)
    fuzzy_enabled: bool = True
    fuzzy_boost: float = Field(default=0.35, ge=0.0, le=20.0)
    fuzzy_max_edit_distance: int = Field(default=1, ge=0, le=3)
    fuzzy_min_token_length: int = Field(default=4, ge=1, le=32)
    fuzzy_candidate_limit: int = Field(default=128, ge=1, le=10000)
    character_ngram_min: int = Field(default=2, ge=1, le=8)
    character_ngram_max: int = Field(default=4, ge=1, le=12)
    max_document_character_ngrams: int = Field(default=64, ge=1, le=4096)
    max_query_character_ngrams: int = Field(default=64, ge=1, le=2048)
    character_ngram_candidate_limit: int = Field(default=16, ge=1, le=256)
    character_ngram_boost: float = Field(default=0.18, ge=0.0, le=20.0)
    field_weights: dict[str, float] = Field(
        default_factory=lambda: {
            "ocr_text": 2.4,
            "ocr_text_no_diacritics": 2.0,
            "ocr_punctuation": 1.2,
            "ocr_char_ngrams": 0.35,
            "asr_text": 2.0,
            "asr_text_no_diacritics": 1.7,
            "asr_char_ngrams": 0.25,
            "organizer_metadata_title": 3.0,
            "organizer_metadata_description": 1.4,
            "organizer_metadata_tags": 2.2,
            "organizer_metadata_channel": 1.1,
            "organizer_metadata_text": 1.2,
            "organizer_metadata_text_no_diacritics": 1.0,
            "organizer_metadata_char_ngrams": 0.18,
            "auto_metadata_title": 1.8,
            "auto_metadata_description": 1.0,
            "auto_metadata_tags": 1.4,
            "auto_metadata_channel": 0.8,
            "auto_metadata_text": 1.0,
            "auto_metadata_text_no_diacritics": 0.8,
            "auto_metadata_char_ngrams": 0.15,
            "technical_metadata_title": 0.8,
            "technical_metadata_description": 0.5,
            "technical_metadata_tags": 0.5,
            "technical_metadata_channel": 0.4,
            "technical_metadata_text": 0.6,
            "technical_metadata_text_no_diacritics": 0.5,
            "technical_metadata_char_ngrams": 0.08,
        }
    )
    remote_url: str = "http://localhost:9200"
    remote_verify_certs: bool = True
    remote_timeout_seconds: int = Field(default=30, ge=1, le=600)
    remote_bulk_size: int = Field(default=500, ge=1, le=10000)
    remote_username_env: str = "AIC_TEXT_INDEX_USERNAME"
    remote_password_env: str = "AIC_TEXT_INDEX_PASSWORD"
    remote_api_key_env: str = "AIC_TEXT_INDEX_API_KEY"

    @field_validator(
        "index_name",
        "local_database_name",
        "remote_url",
        "remote_username_env",
        "remote_password_env",
        "remote_api_key_env",
    )
    @classmethod
    def non_empty_text_index_value(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("text index string settings must not be empty")
        return value.strip()

    @field_validator("field_weights")
    @classmethod
    def valid_field_weights(cls, value: dict[str, float]) -> dict[str, float]:
        if not value:
            raise ValueError("text index field_weights must not be empty")
        if any(not name.strip() or weight < 0 for name, weight in value.items()):
            raise ValueError("text index field weights require non-empty names and non-negative values")
        return value

    @model_validator(mode="after")
    def validate_text_index_options(self):
        if self.character_ngram_min > self.character_ngram_max:
            raise ValueError("character_ngram_min must be <= character_ngram_max")
        if self.adapter != "local_bm25" and not self.persistent:
            raise ValueError("remote text adapters still require persistent local fallback artifacts")
        return self

class RuntimeConfig(StrictConfigModel):
    profile: Literal["development", "competition"] = "development"
    seed: int = Field(default=42, ge=0)
    workers_cpu: int = Field(default=4, ge=1, le=256)
    lock_timeout_seconds: int = Field(default=21600, ge=60, le=604800)


class PathsConfig(StrictConfigModel):
    data_root: Path = Field(
        default_factory=lambda: Path("data"),
        json_schema_extra={"default": "data"},
    )
    runs_root: Path = Field(
        default_factory=lambda: Path("data/runs"),
        json_schema_extra={"default": "data/runs"},
    )

    @field_validator("data_root", "runs_root")
    @classmethod
    def validate_path(cls, value: Path) -> Path:
        text = str(value)
        if not text.strip() or "\x00" in text:
            raise ValueError("paths must be non-empty and contain no null bytes")
        return value


class APIConfig(StrictConfigModel):
    cors_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ]
    )
    cors_allow_credentials: bool = False
    cors_allow_methods: list[str] = Field(
        default_factory=lambda: ["GET", "POST", "HEAD", "OPTIONS"]
    )
    cors_allow_headers: list[str] = Field(default_factory=lambda: ["*"])
    stream_chunk_size_bytes: int = Field(
        default=1024 * 1024, ge=4096, le=64 * 1024 * 1024
    )
    resolver_cache_size: int = Field(default=8, ge=1, le=256)
    default_page_size: int = Field(default=100, ge=1, le=1000)
    maximum_page_size: int = Field(default=1000, ge=1, le=10000)

    @field_validator("cors_origins", "cors_allow_methods", "cors_allow_headers")
    @classmethod
    def non_empty_list(cls, value: list[str]) -> list[str]:
        cleaned = [item.strip() for item in value if item.strip()]
        if not cleaned:
            raise ValueError("API lists must not be empty")
        return cleaned

    @model_validator(mode="after")
    def validate_cors(self):
        if self.cors_allow_credentials and "*" in self.cors_origins:
            raise ValueError("Wildcard CORS origin cannot be used with credentials")
        if self.default_page_size > self.maximum_page_size:
            raise ValueError("default_page_size must be <= maximum_page_size")
        return self


class Settings(StrictConfigModel):
    corpus: CorpusConfig = Field(default_factory=CorpusConfig)
    media: MediaConfig = Field(default_factory=MediaConfig)
    keyframes: KeyframeConfig = Field(default_factory=KeyframeConfig)
    ocr: OCRConfig = Field(default_factory=OCRConfig)
    asr: ASRConfig = Field(default_factory=ASRConfig)
    object: ObjectConfig = Field(default_factory=ObjectConfig)
    metadata: MetadataConfig = Field(default_factory=MetadataConfig)
    evidence_catalog: EvidenceCatalogConfig = Field(default_factory=EvidenceCatalogConfig)
    text_index: TextIndexConfig = Field(default_factory=TextIndexConfig)
    runtime: RuntimeConfig = Field(default_factory=RuntimeConfig)
    paths: PathsConfig = Field(default_factory=PathsConfig)
    api: APIConfig = Field(default_factory=APIConfig)

    @model_validator(mode="after")
    def validate_cross_module_dependencies(self):
        if self.asr.enabled and not self.media.create_audio:
            raise ValueError("media.create_audio must be true when ASR is enabled")
        if self.text_index.enabled and not any(
            [self.ocr.enabled, self.asr.enabled, self.metadata.technical_enabled, self.metadata.organizer_youtube_enabled]
        ):
            raise ValueError("text_index.enabled requires at least one text-producing modality")
        if self.runtime.profile == "competition":
            if self.ocr.enabled and self.ocr.adapter != "deep_solo_parseq":
                raise ValueError("competition OCR must use deep_solo_parseq")
            if self.asr.enabled and self.asr.adapter != "chunkformer":
                raise ValueError("competition ASR must use chunkformer")
            if self.asr.enabled and self.asr.vad_adapter != "silero":
                raise ValueError("competition VAD must use silero")
            if self.object.enabled and self.object.adapter != "rfdetr":
                raise ValueError("competition object detector must use rfdetr")
            if self.ocr.enabled and (
                self.ocr.deep_solo_parseq_checkpoint_path is None
                or not self.ocr.deep_solo_parseq_command
            ):
                raise ValueError("competition OCR requires external DeepSolo+PARSeq checkpoint/command")
            if self.asr.enabled and (
                self.asr.chunkformer_checkpoint_path is None
                or not self.asr.chunkformer_command
            ):
                raise ValueError("competition ASR requires external ChunkFormer checkpoint/command")
            if self.object.enabled and self.object.rfdetr_checkpoint_path is None:
                raise ValueError("competition RF-DETR requires an external checkpoint path")
            enabled_configs = [
                (self.ocr.enabled, self.ocr.allow_runtime_downloads, "OCR"),
                (self.asr.enabled, self.asr.allow_runtime_downloads, "ASR"),
                (self.object.enabled, self.object.allow_runtime_downloads, "object"),
            ]
            for enabled, allow_downloads, name in enabled_configs:
                if enabled and allow_downloads:
                    raise ValueError(f"competition profile forbids {name} runtime downloads")
        if self.object.default_mode == "hard_filter":
            # Hard filtering is allowed only as an explicit experimental choice.
            pass
        return self


def _load_yaml(path: str | Path) -> dict[str, Any]:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError("configuration root must be a mapping")
    return payload


def load_settings(path: str | Path) -> tuple[Settings, dict[str, Any]]:
    raw = _load_yaml(path)
    settings = Settings.model_validate(raw)
    return settings, raw
