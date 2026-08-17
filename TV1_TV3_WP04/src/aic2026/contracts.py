"""Typed contracts for the TV1 preprocessing foundation and TV3 evidence layers.

Only contracts produced or consumed by ingest, media/frame indexing, hybrid
keyframes, temporal infrastructure, registry/resume, validation and the
preprocessing inspection API are retained.  ``ASRSegment`` and
``SearchCandidate`` remain as narrow hand-off interfaces so later members can
link evidence without changing the preprocessing source of truth.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class RunStatus(StrEnum):
    RUNNING = "running"
    PARTIAL = "partial"
    COMPLETED = "completed"
    VALIDATED = "validated"
    STABLE = "stable"


class MetadataSource(StrEnum):
    TECHNICAL = "technical"
    ORGANIZER_YOUTUBE = "organizer_youtube"
    AUTO_SEMANTIC = "auto_semantic"
    USER_ANNOTATION = "user_annotation"

class ModuleArtifactStatus(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class PreprocessingRun(Contract):
    schema_version: str = "1.0.0"
    pipeline_version: str
    preprocess_run_id: str
    source_manifest_sha256: str
    config_sha256: str
    code_commit: str
    status: Literal["running", "partial", "completed", "validated", "stable"]
    video_count: int = Field(ge=0)
    keyframe_count: int = Field(ge=0)
    started_at_utc: str
    finished_at_utc: str | None = None
    artifact_root: str
    validation_report_path: str | None = None


class CorpusManifestRecord(Contract):
    schema_version: str = "1.0.0"
    video_id: str
    source_archive: str | None = None
    original_video_path: str
    source_sha256: str
    file_size_bytes: int = Field(ge=0)
    batch_id: str | None = None
    duplicate_of_video_id: str | None = None
    ingest_status: Literal["accepted", "duplicate", "rejected"] = "accepted"
    created_at_utc: str


class MediaRecord(Contract):
    schema_version: str = "1.1.0"
    preprocess_run_id: str
    video_id: str
    original_video_path: str
    remux_path: str | None = None
    proxy_path: str | None = None
    source_sha256: str
    time_base: str | None = None
    fps_nominal: float | None = Field(default=None, gt=0)
    fps_average: float | None = Field(default=None, gt=0)
    # Backward-compatible probe fields kept for existing artifacts/tools.
    avg_fps: float | None = Field(default=None, ge=0)
    r_frame_rate: str | None = None
    avg_frame_rate: str | None = None
    is_variable_frame_rate: bool | None = None
    frame_count: int | None = Field(default=None, ge=0)
    duration_ms: int = Field(ge=0)
    width_px: int = Field(ge=1)
    height_px: int = Field(ge=1)
    codec: str | None = None
    has_audio: bool
    original_frame_index_path: str | None = None
    frame_index_backend: Literal["pyav", "ffprobe"] | None = None
    created_at_utc: str


class AudioRecord(Contract):
    schema_version: str = "1.1.0"
    preprocess_run_id: str
    video_id: str
    audio_path: str | None = None
    audio_sha256: str | None = None
    sample_rate_hz: int | None = Field(default=None, ge=1)
    channels: int | None = Field(default=None, ge=1)
    duration_ms: int | None = Field(default=None, ge=0)
    status: Literal["ready", "no_audio", "failed"]
    created_at_utc: str


class OriginalFrameIndexRecord(Contract):
    schema_version: str = "1.1.0"
    preprocess_run_id: str
    video_id: str
    frame_id: int = Field(ge=0)
    decode_index: int = Field(ge=0)
    pts: int | None = None
    dts: int | None = None
    time_base: str
    raw_timestamp_ms: int | None = None
    timeline_origin_ms: int = 0
    timestamp_ms: int = Field(ge=0)
    is_technical_keyframe: bool | None = None
    created_at_utc: str


class ShotRecord(Contract):
    schema_version: str = "1.0.0"
    preprocess_run_id: str
    video_id: str
    shot_id: str
    start_frame_id: int = Field(ge=0)
    end_frame_id: int = Field(ge=0)
    start_timestamp_ms: int = Field(ge=0)
    end_timestamp_ms: int = Field(ge=0)
    start_pts: int | None = None
    end_pts: int | None = None
    detector_name: str
    detector_version: str
    confidence: float | None = Field(default=None, ge=0, le=1)
    created_at_utc: str

    @model_validator(mode="after")
    def validate_bounds(self):
        if self.start_frame_id > self.end_frame_id:
            raise ValueError("shot start_frame_id must be <= end_frame_id")
        if self.start_timestamp_ms > self.end_timestamp_ms:
            raise ValueError("shot start_timestamp_ms must be <= end_timestamp_ms")
        return self


class FrameRecord(Contract):
    schema_version: str = "1.1.0"
    preprocess_run_id: str
    video_id: str
    frame_id: int = Field(ge=0)
    keyframe_seq: int = Field(ge=0)
    timestamp_ms: int = Field(ge=0)
    pts: int | None = None
    time_base: str | None = None
    decode_index: int | None = Field(default=None, ge=0)
    shot_id: str
    keyframe_path: str
    thumbnail_path: str | None = None
    selection_reason: Literal["shot_representative", "max_gap", "boundary_guard", "manual"]
    sharpness_score: float | None = None
    blur_score: float | None = None
    quality_score: float | None = None
    black_frame_ratio: float | None = Field(default=None, ge=0, le=1)
    face_visibility_score: float | None = Field(default=None, ge=0, le=1)
    text_visibility_score: float | None = Field(default=None, ge=0, le=1)
    created_at_utc: str


class OCRDetection(Contract):
    schema_version: str = "1.1.0"
    preprocess_run_id: str
    detection_id: str
    video_id: str
    frame_id: int = Field(ge=0)
    timestamp_ms: int = Field(ge=0)
    raw_text: str
    normalized_text: str
    normalized_text_no_diacritics: str = ""
    punctuation_aware_text: str = ""
    character_ngrams: list[str] = Field(default_factory=list)
    bbox_xyxy_norm: tuple[float, float, float, float]
    polygon_norm: tuple[tuple[float, float], ...] | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    below_threshold: bool = False
    crop_evidence_path: str | None = None
    crop_sha256: str | None = None
    source_keyframe_sha256: str | None = None
    model_name: str
    model_version: str
    created_at_utc: str

    @field_validator("bbox_xyxy_norm")
    @classmethod
    def bbox_is_normalized(cls, value: tuple[float, float, float, float]):
        x1, y1, x2, y2 = value
        if not all(0.0 <= coordinate <= 1.0 for coordinate in value):
            raise ValueError("bbox coordinates must be normalized to [0, 1]")
        if x1 > x2 or y1 > y2:
            raise ValueError("bbox min coordinates must be <= max coordinates")
        return value

    @field_validator("polygon_norm")
    @classmethod
    def polygon_is_normalized(cls, value):
        if value is None:
            return value
        if len(value) < 3:
            raise ValueError("polygon_norm must contain at least three points")
        if not all(0.0 <= coordinate <= 1.0 for point in value for coordinate in point):
            raise ValueError("polygon coordinates must be normalized to [0, 1]")
        return value

    @model_validator(mode="after")
    def crop_integrity_fields(self):
        if bool(self.crop_evidence_path) != bool(self.crop_sha256):
            raise ValueError("crop_evidence_path and crop_sha256 must be set together")
        return self

class OCRFrameManifest(Contract):
    schema_version: str = "1.0.0"
    status: Literal["completed", "failed"]
    preprocess_run_id: str
    video_id: str
    frame_id: int = Field(ge=0)
    timestamp_ms: int = Field(ge=0)
    fingerprint: str
    adapter_name: str
    adapter_version: str
    detections: list[OCRDetection] = Field(default_factory=list)
    error: str | None = None
    created_at_utc: str

class OCRVideoMetrics(Contract):
    schema_version: str = "1.0.0"
    preprocess_run_id: str
    video_id: str
    requested_adapter: str
    selected_adapter: str
    adapter_name: str
    adapter_version: str
    adapter_attempts: list[dict[str, str]] = Field(default_factory=list)
    frame_count: int = Field(ge=0)
    processed_frames: int = Field(ge=0)
    resumed_frames: int = Field(ge=0)
    failed_frames: int = Field(ge=0)
    detection_count: int = Field(ge=0)
    below_threshold_count: int = Field(ge=0)
    frame_errors: list[dict[str, Any]] = Field(default_factory=list)
    created_at_utc: str

class ASRWord(Contract):
    """Narrow ASR hand-off word contract; TV1 never generates it."""

    schema_version: str = "1.0.0"
    start_ms: int = Field(ge=0)
    end_ms: int = Field(ge=0)
    word: str
    probability: float | None = Field(default=None, ge=0, le=1)

    @model_validator(mode="after")
    def validate_interval(self):
        if self.start_ms > self.end_ms:
            raise ValueError("ASR word start_ms must be <= end_ms")
        return self


class VADSegmentRecord(Contract):
    schema_version: str = "1.0.0"
    preprocess_run_id: str
    vad_segment_id: str
    video_id: str
    start_ms: int = Field(ge=0)
    end_ms: int = Field(ge=0)
    vad_adapter: str
    confidence: float | None = Field(default=None, ge=0, le=1)
    created_at_utc: str

    @model_validator(mode="after")
    def valid_interval(self):
        if self.start_ms >= self.end_ms:
            raise ValueError("VAD start_ms must be smaller than end_ms")
        return self

class ASRSegment(Contract):
    """Stable future hand-off contract; TV1 links but does not generate ASR."""

    schema_version: str = "1.1.0"
    preprocess_run_id: str
    segment_id: str
    video_id: str
    start_ms: int = Field(ge=0)
    end_ms: int = Field(ge=0)
    text: str
    normalized_text: str = ""
    normalized_text_no_diacritics: str = ""
    language: str = "vi"
    language_probability: float | None = Field(default=None, ge=0, le=1)
    confidence: float | None = Field(default=None, ge=0, le=1)
    avg_logprob: float | None = None
    no_speech_probability: float | None = Field(default=None, ge=0, le=1)
    words: list[ASRWord] = Field(default_factory=list)
    vad_segment_id: str | None = None
    source_audio_sha256: str | None = None
    model_name: str = "future_handoff"
    model_version: str = "unknown"
    created_at_utc: str

    @model_validator(mode="after")
    def validate_interval(self):
        if self.start_ms > self.end_ms:
            raise ValueError("ASR start_ms must be <= end_ms")
        for word in self.words:
            if word.start_ms < self.start_ms or word.end_ms > self.end_ms:
                raise ValueError("ASR word timestamps must stay inside the segment interval")
        return self


class ASRSegmentManifest(Contract):
    schema_version: str = "1.0.0"
    status: Literal["completed", "failed"]
    preprocess_run_id: str
    video_id: str
    vad_segment_id: str
    start_ms: int = Field(ge=0)
    end_ms: int = Field(ge=0)
    fingerprint: str
    adapter_name: str
    adapter_version: str
    vad_adapter_name: str
    source_audio_sha256: str
    transcript_segments: list[ASRSegment] = Field(default_factory=list)
    error: str | None = None
    created_at_utc: str

    @model_validator(mode="after")
    def valid_interval(self):
        if self.start_ms >= self.end_ms:
            raise ValueError("ASR chunk start_ms must be smaller than end_ms")
        return self

class ASRVideoMetrics(Contract):
    schema_version: str = "1.0.0"
    preprocess_run_id: str
    video_id: str
    status: Literal["completed", "partial", "no_audio", "failed"]
    requested_adapter: str
    selected_adapter: str
    requested_vad_adapter: str
    selected_vad_adapter: str
    adapter_name: str
    adapter_version: str
    vad_adapter_name: str
    vad_adapter_version: str
    audio_duration_ms: int = Field(ge=0)
    vad_segment_count: int = Field(ge=0)
    processed_segments: int = Field(ge=0)
    resumed_segments: int = Field(ge=0)
    failed_segments: int = Field(ge=0)
    transcript_segment_count: int = Field(ge=0)
    detected_languages: list[str] = Field(default_factory=list)
    runtime_seconds: float = Field(default=0.0, ge=0)
    initial_batch_size: int = Field(default=1, ge=1)
    final_batch_size: int = Field(default=1, ge=1)
    oom_retry_count: int = Field(default=0, ge=0)
    cpu_fallback_used: bool = False
    segments_per_second: float = Field(default=0.0, ge=0)
    audio_realtime_factor: float = Field(default=0.0, ge=0)
    segment_errors: list[dict[str, Any]] = Field(default_factory=list)
    created_at_utc: str

class TemporalFrameRecord(Contract):
    schema_version: str = "1.1.0"
    preprocess_run_id: str
    video_id: str
    frame_id: int = Field(ge=0)
    keyframe_seq: int | None = Field(default=None, ge=0)
    timestamp_ms: int = Field(ge=0)
    pts: int | None = None
    time_base: str | None = None
    shot_id: str | None = None
    shot_start_frame_id: int | None = Field(default=None, ge=0)
    shot_end_frame_id: int | None = Field(default=None, ge=0)
    shot_start_timestamp_ms: int | None = Field(default=None, ge=0)
    shot_end_timestamp_ms: int | None = Field(default=None, ge=0)
    previous_frame_id: int | None = Field(default=None, ge=0)
    next_frame_id: int | None = Field(default=None, ge=0)
    previous_timestamp_ms: int | None = Field(default=None, ge=0)
    next_timestamp_ms: int | None = Field(default=None, ge=0)
    linked_asr_segment_ids: list[str] = Field(default_factory=list)
    created_at_utc: str

    @model_validator(mode="after")
    def validate_temporal_bounds(self):
        if self.previous_timestamp_ms is not None and self.previous_timestamp_ms > self.timestamp_ms:
            raise ValueError("previous_timestamp_ms must be <= timestamp_ms")
        if self.next_timestamp_ms is not None and self.next_timestamp_ms < self.timestamp_ms:
            raise ValueError("next_timestamp_ms must be >= timestamp_ms")
        if (
            self.shot_start_timestamp_ms is not None
            and self.shot_end_timestamp_ms is not None
            and self.shot_start_timestamp_ms > self.shot_end_timestamp_ms
        ):
            raise ValueError("shot start timestamp must be <= shot end timestamp")
        return self


class TemporalASRLinkRecord(Contract):
    schema_version: str = "1.0.0"
    preprocess_run_id: str
    video_id: str
    segment_id: str
    segment_start_ms: int = Field(ge=0)
    segment_end_ms: int = Field(ge=0)
    representative_frame_id: int | None = Field(default=None, ge=0)
    representative_timestamp_ms: int | None = Field(default=None, ge=0)
    nearest_before_frame_id: int | None = Field(default=None, ge=0)
    nearest_after_frame_id: int | None = Field(default=None, ge=0)
    overlapping_keyframe_ids: list[int] = Field(default_factory=list)
    overlapping_shot_ids: list[str] = Field(default_factory=list)
    created_at_utc: str

    @model_validator(mode="after")
    def validate_bounds(self):
        if self.segment_start_ms > self.segment_end_ms:
            raise ValueError("segment_start_ms must be <= segment_end_ms")
        return self


class TemporalWindowRecord(Contract):
    schema_version: str = "1.0.0"
    preprocess_run_id: str
    video_id: str
    window_start_ms: int = Field(ge=0)
    window_end_ms: int = Field(ge=0)
    center_timestamp_ms: int = Field(ge=0)
    representative_frame_id: int = Field(ge=0)
    representative_timestamp_ms: int = Field(ge=0)
    keyframe_ids: list[int] = Field(default_factory=list)
    shot_ids: list[str] = Field(default_factory=list)
    asr_segment_ids: list[str] = Field(default_factory=list)
    clamped_to_media: bool = False
    created_at_utc: str

    @model_validator(mode="after")
    def validate_window_bounds(self):
        if self.window_start_ms > self.window_end_ms:
            raise ValueError("window_start_ms must be <= window_end_ms")
        if not self.window_start_ms <= self.center_timestamp_ms <= self.window_end_ms:
            raise ValueError("center_timestamp_ms must be inside the window")
        return self


class ObjectDetection(Contract):
    schema_version: str = "1.2.0"
    preprocess_run_id: str
    detection_id: str
    video_id: str
    frame_id: int = Field(ge=0)
    timestamp_ms: int = Field(ge=0)
    label: str
    canonical_label: str | None = None
    label_aliases: list[str] = Field(default_factory=list)
    class_id: int | None = Field(default=None, ge=0)
    bbox_xyxy_norm: tuple[float, float, float, float]
    center_xy_norm: tuple[float, float] | None = None
    spatial_region: Literal[
        "top_left", "top", "top_right", "left", "center", "right",
        "bottom_left", "bottom", "bottom_right"
    ] | None = None
    area_ratio: float | None = Field(default=None, ge=0, le=1)
    # Retrieval-eligible count. It may be zero on a retained low-confidence
    # audit record when no detection of the same class passes the threshold.
    count_in_frame: int = Field(default=0, ge=0)
    # Count before the confidence gate, retained for audit/debugging only.
    raw_count_in_frame: int = Field(default=1, ge=1)
    confidence: float | None = Field(default=None, ge=0, le=1)
    below_threshold: bool = False
    source_keyframe_path: str | None = None
    source_keyframe_sha256: str | None = None
    model_name: str
    model_version: str
    created_at_utc: str

    @field_validator("bbox_xyxy_norm")
    @classmethod
    def bbox_is_normalized(cls, value: tuple[float, float, float, float]):
        x1, y1, x2, y2 = value
        if not all(0.0 <= coordinate <= 1.0 for coordinate in value):
            raise ValueError("bbox coordinates must be normalized to [0, 1]")
        if x1 > x2 or y1 > y2:
            raise ValueError("bbox min coordinates must be <= max coordinates")
        return value

    @field_validator("center_xy_norm")
    @classmethod
    def center_is_normalized(cls, value: tuple[float, float] | None):
        if value is not None and not all(0.0 <= coordinate <= 1.0 for coordinate in value):
            raise ValueError("object center coordinates must be normalized to [0, 1]")
        return value

class ObjectFrameManifest(Contract):
    schema_version: str = "1.0.0"
    status: Literal["completed", "failed"]
    preprocess_run_id: str
    video_id: str
    frame_id: int = Field(ge=0)
    timestamp_ms: int = Field(ge=0)
    fingerprint: str
    adapter_name: str
    adapter_version: str
    detections: list[ObjectDetection] = Field(default_factory=list)
    error: str | None = None
    created_at_utc: str

class ObjectVideoMetrics(Contract):
    schema_version: str = "1.0.0"
    preprocess_run_id: str
    video_id: str
    status: Literal["completed", "partial", "failed"]
    requested_adapter: str
    selected_adapter: str
    adapter_name: str
    adapter_version: str
    frame_count: int = Field(ge=0)
    processed_frames: int = Field(ge=0)
    resumed_frames: int = Field(ge=0)
    failed_frames: int = Field(ge=0)
    detection_count: int = Field(ge=0)
    below_threshold_count: int = Field(ge=0)
    label_counts: dict[str, int] = Field(default_factory=dict)
    runtime_seconds: float = Field(default=0.0, ge=0)
    frame_errors: list[dict[str, Any]] = Field(default_factory=list)
    created_at_utc: str

class MetadataRecord(Contract):
    schema_version: str = "1.1.0"
    preprocess_run_id: str
    metadata_id: str
    video_id: str
    source: MetadataSource
    title: str | None = None
    description: str | None = None
    tags: list[str] = Field(default_factory=list)
    channel: str | None = None
    upload_date: str | None = None
    language: str | None = None
    youtube_video_id: str | None = None
    window_start_ms: int | None = Field(default=None, ge=0)
    window_end_ms: int | None = Field(default=None, ge=0)
    text: str | None = None
    normalized_text: str | None = None
    normalized_text_no_diacritics: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    model_name: str | None = None
    model_version: str | None = None
    source_path: str | None = None
    source_record_sha256: str | None = None
    matched_by: str | None = None
    raw_fields: dict[str, Any] = Field(default_factory=dict)
    created_at_utc: str

    @model_validator(mode="after")
    def validate_window(self):
        if (
            self.window_start_ms is not None
            and self.window_end_ms is not None
            and self.window_start_ms > self.window_end_ms
        ):
            raise ValueError("metadata window_start_ms must be <= window_end_ms")
        return self

class MetadataImportReport(Contract):
    schema_version: str = "1.1.0"
    preprocess_run_id: str
    source_root: str
    source_files: list[str] = Field(default_factory=list)
    source_fingerprint: str
    total_rows: int = Field(default=0, ge=0)
    matched_rows: int = Field(ge=0)
    unmatched_rows: int = Field(ge=0)
    ambiguous_rows: int = Field(default=0, ge=0)
    duplicate_rows: int = Field(default=0, ge=0)
    invalid_rows: int = Field(ge=0)
    record_count: int = Field(ge=0)
    strict_unknown_video: bool = False
    status: Literal["completed", "missing_optional_source", "failed"]
    unmatched_examples: list[dict[str, Any]] = Field(default_factory=list)
    ambiguous_examples: list[dict[str, Any]] = Field(default_factory=list)
    duplicate_examples: list[dict[str, Any]] = Field(default_factory=list)
    created_at_utc: str

class TextIndexManifest(Contract):
    schema_version: str = "1.1.0"
    preprocess_run_id: str
    requested_adapter: Literal["local_bm25", "opensearch", "elasticsearch"]
    selected_adapter: Literal["local_bm25", "opensearch", "elasticsearch"]
    index_name: str
    remote_index_name: str | None = None
    remote_document_count: int | None = Field(default=None, ge=0)
    remote_build_fingerprint: str | None = None
    remote_documents_sha256: str | None = None
    remote_field_mapping_version: str | None = None
    remote_validated_at_utc: str | None = None
    backend_version: str
    persistent: bool = True
    document_count: int = Field(ge=0)
    source_counts: dict[str, int] = Field(default_factory=dict)
    metadata_source_counts: dict[str, int] = Field(default_factory=dict)
    field_names: list[str] = Field(default_factory=list)
    field_weights: dict[str, float] = Field(default_factory=dict)
    build_fingerprint: str
    source_artifact_checksums: dict[str, str] = Field(default_factory=dict)
    documents_path: str
    documents_sha256: str
    index_path: str
    index_sha256: str
    build_config: dict[str, Any] = Field(default_factory=dict)
    degraded_reason: str | None = None
    created_at_utc: str

    @field_validator("documents_sha256", "index_sha256", "build_fingerprint")
    @classmethod
    def validate_digest(cls, value: str) -> str:
        if len(value) != 64 or any(char not in "0123456789abcdef" for char in value.lower()):
            raise ValueError("text index digest fields must be SHA-256 hex strings")
        return value.lower()

    @field_validator("remote_build_fingerprint", "remote_documents_sha256")
    @classmethod
    def validate_optional_digest(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if len(value) != 64 or any(char not in "0123456789abcdef" for char in value.lower()):
            raise ValueError("remote text index digest fields must be SHA-256 hex strings")
        return value.lower()

    @field_validator("source_counts", "metadata_source_counts")
    @classmethod
    def validate_counts(cls, value: dict[str, int]) -> dict[str, int]:
        if any(count < 0 for count in value.values()):
            raise ValueError("text index source counts must be non-negative")
        return value

class SearchRequest(Contract):
    schema_version: str = "1.0.0"
    query_id: str
    task: Literal["KIS", "VQA", "TRAKE"]
    query_text: str | None = None
    question: str | None = None
    events: list[str] = Field(default_factory=list)
    filters: dict[str, Any] = Field(default_factory=dict)
    limit: int = Field(default=100, ge=1, le=100)
    language: str | None = "vi"
    session_id: str | None = None

class SearchCandidate(Contract):
    """Stable downstream hand-off used by temporal canonicalization.

    The class is retained even in the TV1-only source so TV2/TV3 can consume the
    preprocessing artifacts later without changing the frame/timestamp contract.
    """

    schema_version: str = "1.0.0"
    query_id: str
    event_index: int | None = Field(default=None, ge=0)
    video_id: str
    frame_id: int = Field(ge=0)
    representative_frame_id: int | None = Field(default=None, ge=0)
    timestamp_ms: int = Field(ge=0)
    window_start_ms: int | None = Field(default=None, ge=0)
    window_end_ms: int | None = Field(default=None, ge=0)
    source: Literal["visual", "ocr", "asr", "metadata", "object", "feedback", "fusion"]
    raw_score: float | None = None
    score: float | None = None
    rank: int = Field(ge=1)
    model_scores: dict[str, float] = Field(default_factory=dict)
    model_ranks: dict[str, int] = Field(default_factory=dict)
    matched_filters: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    provenance_sources: list[str] = Field(default_factory=list)
    provenance: dict[str, Any] = Field(default_factory=dict)
    confidence: float | None = Field(default=None, ge=0, le=1)
    preprocess_run_id: str
    created_at_utc: str

    @model_validator(mode="after")
    def validate_window(self):
        if (
            self.window_start_ms is not None
            and self.window_end_ms is not None
            and self.window_start_ms > self.window_end_ms
        ):
            raise ValueError("candidate window_start_ms must be <= window_end_ms")
        return self


class ModuleArtifactManifest(Contract):
    schema_version: str = "1.0.0"
    preprocess_run_id: str
    video_id: str | None = None
    module_name: str
    module_version: str
    status: ModuleArtifactStatus
    fingerprint: str | None = None
    dependency_fingerprints: dict[str, str] = Field(default_factory=dict)
    config_sha256: str
    source_sha256: str | None = None
    model_name: str | None = None
    model_version: str | None = None
    artifact_paths: list[str] = Field(default_factory=list)
    artifact_checksums: dict[str, str] = Field(default_factory=dict)
    record_count: int | None = Field(default=None, ge=0)
    started_at_utc: str | None = None
    finished_at_utc: str | None = None
    error_code: str | None = None
    error_message: str | None = None


class ValidationSeverity(StrEnum):
    P0 = "P0"
    P1 = "P1"
    P2 = "P2"


class ValidationCheckStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    WARNING = "warning"
    SKIPPED = "skipped"


class ValidationIssue(Contract):
    schema_version: str = "1.0.0"
    issue_id: str
    preprocess_run_id: str
    severity: ValidationSeverity
    code: str
    module: str
    message: str
    video_id: str | None = None
    artifact_path: str | None = None
    context: dict[str, Any] = Field(default_factory=dict)
    created_at_utc: str


class ValidationCheckResult(Contract):
    schema_version: str = "1.0.0"
    name: str
    status: ValidationCheckStatus
    issue_count: int = Field(default=0, ge=0)
    records_checked: int = Field(default=0, ge=0)
    duration_ms: float = Field(default=0.0, ge=0.0)
    details: dict[str, Any] = Field(default_factory=dict)


class RunValidationReport(Contract):
    schema_version: str = "1.1.0"
    preprocess_run_id: str
    status: Literal["passed", "failed"]
    g0_pass: bool
    stable_eligible: bool
    source_manifest_sha256: str | None = None
    config_sha256: str | None = None
    artifact_state_sha256: str | None = None
    severity_counts: dict[str, int] = Field(default_factory=dict)
    checks: list[ValidationCheckResult] = Field(default_factory=list)
    issues: list[ValidationIssue] = Field(default_factory=list)
    validation_policy: dict[str, Any] = Field(default_factory=dict)
    validated_at_utc: str
    report_sha256: str | None = None

    @model_validator(mode="after")
    def validate_consistency(self):
        p0 = int(self.severity_counts.get("P0", 0))
        if self.g0_pass and p0:
            raise ValueError("g0_pass cannot be true when P0 issues exist")
        if self.status == "passed" and not self.g0_pass:
            raise ValueError("passed status requires g0_pass=true")
        if self.stable_eligible and not self.g0_pass:
            raise ValueError("stable_eligible requires g0_pass=true")
        return self
