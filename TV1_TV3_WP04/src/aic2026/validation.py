"""G0 validator for the TV1 preprocessing foundation and shared TV3 evidence links.

The validator checks correctness of source checksums, PTS/time-base arithmetic,
original-frame mappings, keyframes, temporal relationships, registry artifacts
and downstream hand-off files.  Validation of a stable run is written outside
the stable run root so stable artifacts remain immutable.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any, Callable

import cv2

from .config import Settings
from .contracts import (
    ASRSegment,
    ASRSegmentManifest,
    ASRVideoMetrics,
    AudioRecord,
    CorpusManifestRecord,
    FrameRecord,
    MediaRecord,
    MetadataRecord,
    ModuleArtifactManifest,
    ObjectDetection,
    OCRDetection,
    PreprocessingRun,
    RunValidationReport,
    ShotRecord,
    TemporalFrameRecord,
    TextIndexManifest,
    ValidationCheckResult,
    ValidationCheckStatus,
    ValidationIssue,
)
from .fingerprints import source_manifest_hash
from .evidence_catalog import EvidenceCatalogError, validate_evidence_catalog
from .frame_index import load_original_frame_index
from .registry import RunRegistry
from .text_index import TextIndexValidationError, validate_text_index_artifacts
from .utils import (
    read_json,
    read_jsonl,
    sha256_file,
    stable_json_hash,
    utcnow_iso,
    write_json,
)


@dataclass(frozen=True)
class ValidationPolicy:
    timestamp_tolerance_ms: int = 2
    audio_duration_tolerance_ms: int = 1500
    mapping_audit_samples_per_video: int = 7
    require_pyav_for_stable: bool = True
    require_autoshot_for_stable: bool = True


class RunValidationError(RuntimeError):
    pass


def _load_models(path: Path, model) -> list:
    return [model.model_validate(row) for row in read_jsonl(path)]


def _artifact_manifest_files(run_root: Path) -> list[Path]:
    return sorted((run_root / "registry" / "artifacts").rglob("*.json"))


def compute_artifact_state_sha256(run_root: str | Path) -> str:
    """Fingerprint current module outputs, independent of validation reports/DB."""

    root = Path(run_root)
    payload: list[dict[str, Any]] = []
    for path in _artifact_manifest_files(root):
        try:
            manifest = ModuleArtifactManifest.model_validate(read_json(path))
        except Exception as exc:
            payload.append(
                {
                    "manifest": path.relative_to(root).as_posix(),
                    "invalid": f"{type(exc).__name__}: {exc}",
                }
            )
            continue
        actual: dict[str, str | None] = {}
        for relative in sorted(manifest.artifact_paths):
            artifact = root / relative
            actual[relative] = sha256_file(artifact) if artifact.is_file() else None
        payload.append(
            {
                "video_id": manifest.video_id,
                "module": manifest.module_name,
                "fingerprint": manifest.fingerprint,
                "config_sha256": manifest.config_sha256,
                "source_sha256": manifest.source_sha256,
                "artifacts": actual,
            }
        )
    root_artifacts = [
        "corpus_manifest.jsonl",
        "config.snapshot.json",
        "ocr/ocr.jsonl",
        "asr/asr.jsonl",
        "objects/objects.jsonl",
        "metadata/metadata.jsonl",
        "text_index/documents.jsonl",
        "text_index/local_bm25.sqlite3",
        "text_index/manifest.json",
        "evidence_catalog/evidence.sqlite3",
        "evidence_catalog/manifest.json",
    ]
    for relative in root_artifacts:
        path = root / relative
        payload.append(
            {
                "root_artifact": relative,
                "sha256": sha256_file(path) if path.is_file() else None,
            }
        )
    return stable_json_hash(payload)


class RunValidator:
    def __init__(
        self,
        run_id: str,
        run_root: Path,
        settings: Settings,
        policy: ValidationPolicy,
    ):
        self.run_id = run_id
        self.run_root = run_root
        self.settings = settings
        self.policy = policy
        self.issues: list[ValidationIssue] = []
        self.checks: list[ValidationCheckResult] = []
        self.production_blockers: set[str] = set()
        self.run: PreprocessingRun | None = None
        self.corpus: list[CorpusManifestRecord] = []
        self.media: list[MediaRecord] = []
        self.audio: list[AudioRecord] = []
        self.frames: list[FrameRecord] = []
        self.shots: list[ShotRecord] = []
        self.temporal: list[TemporalFrameRecord] = []
        self.frame_indexes: dict[str, list] = {}

    def issue(
        self,
        severity: str,
        code: str,
        module: str,
        message: str,
        *,
        video_id: str | None = None,
        artifact_path: str | Path | None = None,
        context: dict[str, Any] | None = None,
        production_blocker: bool = False,
    ) -> None:
        if production_blocker:
            self.production_blockers.add(code)
        payload = {
            "run": self.run_id,
            "severity": severity,
            "code": code,
            "module": module,
            "video_id": video_id,
            "artifact_path": str(artifact_path) if artifact_path else None,
            "context": context or {},
        }
        self.issues.append(
            ValidationIssue(
                issue_id=stable_json_hash(payload)[:20],
                preprocess_run_id=self.run_id,
                severity=severity,
                code=code,
                module=module,
                message=message,
                video_id=video_id,
                artifact_path=str(artifact_path) if artifact_path else None,
                context=context or {},
                created_at_utc=utcnow_iso(),
            )
        )

    def run_check(self, name: str, fn: Callable[[], tuple[int, dict[str, Any]]]) -> None:
        before = len(self.issues)
        started = time.perf_counter()
        try:
            records, details = fn()
        except Exception as exc:
            self.issue(
                "P0",
                f"{name.upper()}_CHECK_CRASHED",
                name,
                f"Validation check crashed: {type(exc).__name__}: {exc}",
            )
            records, details = 0, {"exception": f"{type(exc).__name__}: {exc}"}
        count = len(self.issues) - before
        relevant = self.issues[before:]
        if any(str(issue.severity) == "P0" for issue in relevant):
            status = ValidationCheckStatus.FAILED
        elif count:
            status = ValidationCheckStatus.WARNING
        else:
            status = ValidationCheckStatus.PASSED
        self.checks.append(
            ValidationCheckResult(
                name=name,
                status=status,
                issue_count=count,
                records_checked=records,
                duration_ms=(time.perf_counter() - started) * 1000.0,
                details=details,
            )
        )

    def check_run_and_corpus(self) -> tuple[int, dict[str, Any]]:
        manifest_path = self.run_root / "manifest.json"
        if not manifest_path.is_file():
            self.issue("P0", "RUN_MANIFEST_MISSING", "run", "manifest.json is missing")
            return 0, {}
        self.run = PreprocessingRun.model_validate(read_json(manifest_path))
        if self.run.preprocess_run_id != self.run_id:
            self.issue("P0", "RUN_ID_MISMATCH", "run", "Run manifest ID mismatch")
        if self.run.status == "partial":
            self.issue("P0", "RUN_PARTIAL", "run", "Run contains failed modules")

        self.corpus = _load_models(
            self.run_root / "corpus_manifest.jsonl", CorpusManifestRecord
        )
        if not self.corpus:
            self.issue("P0", "CORPUS_EMPTY", "ingest", "Corpus manifest is empty")
        ids: set[str] = set()
        accepted = 0
        for row in self.corpus:
            if row.video_id in ids:
                self.issue(
                    "P0", "VIDEO_ID_DUPLICATE", "ingest", "Duplicate video_id", video_id=row.video_id
                )
            ids.add(row.video_id)
            if row.ingest_status != "accepted":
                continue
            accepted += 1
            path = Path(row.original_video_path)
            if not path.is_file():
                self.issue(
                    "P0", "SOURCE_VIDEO_MISSING", "ingest", "Original video is missing", video_id=row.video_id, artifact_path=path
                )
            elif sha256_file(path) != row.source_sha256:
                self.issue(
                    "P0", "SOURCE_CHECKSUM_MISMATCH", "ingest", "Source video checksum changed", video_id=row.video_id, artifact_path=path
                )
        logical_hash = source_manifest_hash(self.corpus)
        if self.run.source_manifest_sha256 != logical_hash:
            self.issue("P0", "SOURCE_MANIFEST_HASH_MISMATCH", "ingest", "Logical corpus manifest hash mismatch")
        return len(self.corpus), {"accepted": accepted, "logical_sha256": logical_hash}

    def check_registry_artifacts(self) -> tuple[int, dict[str, Any]]:
        registry_path = self.run_root / "registry" / "run_registry.sqlite3"
        if not registry_path.is_file():
            self.issue("P0", "REGISTRY_MISSING", "registry", "Run registry is missing")
            return 0, {}
        checked = 0
        manifests = _artifact_manifest_files(self.run_root)
        if not manifests:
            self.issue("P0", "ARTIFACT_MANIFESTS_MISSING", "registry", "No module artifact manifests found")
        for path in manifests:
            checked += 1
            try:
                manifest = ModuleArtifactManifest.model_validate(read_json(path))
            except Exception as exc:
                self.issue("P0", "ARTIFACT_MANIFEST_INVALID", "registry", str(exc), artifact_path=path)
                continue
            if manifest.preprocess_run_id != self.run_id:
                self.issue("P0", "ARTIFACT_RUN_MISMATCH", "registry", "Artifact manifest has wrong run ID", video_id=manifest.video_id, artifact_path=path)
            for relative, expected in manifest.artifact_checksums.items():
                artifact = self.run_root / relative
                if not artifact.is_file():
                    self.issue("P0", "MODULE_ARTIFACT_MISSING_OR_CORRUPT", "registry", "Module artifact is missing", video_id=manifest.video_id, artifact_path=artifact)
                elif sha256_file(artifact) != expected:
                    self.issue("P0", "MODULE_ARTIFACT_MISSING_OR_CORRUPT", "registry", "Module artifact checksum mismatch", video_id=manifest.video_id, artifact_path=artifact)
        with RunRegistry(registry_path) as registry:
            row = registry.get_run(self.run_id)
            if row is None:
                self.issue("P0", "RUN_REGISTRY_ROW_MISSING", "registry", "Run registry row is missing")
            elif row["status"] not in {"completed", "validated", "stable"}:
                self.issue("P0", "RUN_REGISTRY_NOT_COMPLETE", "registry", f"Registry status is {row['status']}")
        return checked, {"manifests": len(manifests)}

    def check_media_audio(self) -> tuple[int, dict[str, Any]]:
        self.media = _load_models(self.run_root / "media" / "media.jsonl", MediaRecord)
        self.audio = _load_models(self.run_root / "media" / "audio.jsonl", AudioRecord)
        media_by_video = {row.video_id: row for row in self.media}
        audio_by_video = {row.video_id: row for row in self.audio}
        accepted = {row.video_id: row for row in self.corpus if row.ingest_status == "accepted"}
        for video_id, source in accepted.items():
            media = media_by_video.get(video_id)
            if media is None:
                self.issue("P0", "MEDIA_RECORD_MISSING", "media", "MediaRecord is missing", video_id=video_id)
                continue
            if media.source_sha256 != source.source_sha256:
                self.issue("P0", "MEDIA_SOURCE_MISMATCH", "media", "MediaRecord source checksum mismatch", video_id=video_id)
            if media.frame_count <= 0 or media.duration_ms <= 0:
                self.issue("P0", "MEDIA_INVALID_DIMENSIONS", "media", "Invalid frame count or duration", video_id=video_id)
            if self.policy.require_pyav_for_stable and media.frame_index_backend != "pyav":
                self.issue(
                    "P1", "DEGRADED_FRAME_INDEX_BACKEND", "media", "Production stable run requires real PyAV frame indexing", video_id=video_id, production_blocker=True
                )
            if not self.settings.media.create_audio:
                continue
            audio = audio_by_video.get(video_id)
            if audio is None:
                self.issue("P1", "AUDIO_RECORD_MISSING", "audio", "AudioRecord is missing", video_id=video_id)
                continue
            if media.has_audio and audio.status != "ready":
                self.issue("P1", "AUDIO_NOT_READY", "audio", f"Audio status is {audio.status}", video_id=video_id)
            if not media.has_audio and audio.status != "no_audio":
                self.issue("P1", "NO_AUDIO_STATUS_INCONSISTENT", "audio", "Video has no audio but status differs", video_id=video_id)
            if audio.status == "ready":
                path = Path(audio.audio_path or "")
                if not path.is_file():
                    self.issue("P1", "AUDIO_ARTIFACT_MISSING", "audio", "WAV artifact missing", video_id=video_id, artifact_path=path)
                elif audio.audio_sha256 and sha256_file(path) != audio.audio_sha256:
                    self.issue("P1", "AUDIO_CHECKSUM_MISMATCH", "audio", "WAV checksum mismatch", video_id=video_id, artifact_path=path)
                if audio.sample_rate_hz != self.settings.media.audio_sample_rate_hz or audio.channels != 1:
                    self.issue("P1", "AUDIO_FORMAT_MISMATCH", "audio", "WAV sample rate/channels mismatch", video_id=video_id)
                if audio.duration_ms is not None:
                    tolerance = max(
                        self.policy.audio_duration_tolerance_ms,
                        int(media.duration_ms * 0.02),
                    )
                    if abs(audio.duration_ms - media.duration_ms) > tolerance:
                        self.issue("P1", "AUDIO_DURATION_MISMATCH", "audio", "WAV/video duration differs beyond tolerance", video_id=video_id, context={"media_ms": media.duration_ms, "audio_ms": audio.duration_ms, "tolerance_ms": tolerance})
        return len(self.media) + len(self.audio), {"media": len(self.media), "audio": len(self.audio)}

    def check_frame_indexes(self) -> tuple[int, dict[str, Any]]:
        total = 0
        for media in self.media:
            path = Path(media.original_frame_index_path or self.run_root / "frame_indexes" / f"{media.video_id}.jsonl")
            if not path.is_file():
                self.issue("P0", "FRAME_INDEX_MISSING", "frame_index", "Original-frame index is missing", video_id=media.video_id, artifact_path=path)
                continue
            try:
                rows = load_original_frame_index(path)
            except Exception as exc:
                self.issue("P0", "FRAME_INDEX_INVALID", "frame_index", str(exc), video_id=media.video_id, artifact_path=path)
                continue
            self.frame_indexes[media.video_id] = rows
            total += len(rows)
            if rows[0].timestamp_ms != 0:
                self.issue("P0", "FRAME_INDEX_NOT_NORMALIZED", "frame_index", "First normalized timestamp must be zero", video_id=media.video_id)
            origins = {row.timeline_origin_ms for row in rows}
            if len(origins) != 1:
                self.issue("P0", "FRAME_INDEX_ORIGIN_INCONSISTENT", "frame_index", "timeline_origin_ms changes within video", video_id=media.video_id)
            for row in rows:
                if row.preprocess_run_id != self.run_id or row.video_id != media.video_id:
                    self.issue("P0", "FRAME_INDEX_ID_MISMATCH", "frame_index", "Frame index run/video mismatch", video_id=media.video_id)
                    break
                if row.pts is None:
                    self.issue("P0", "FRAME_INDEX_PTS_MISSING", "frame_index", "Original frame has no PTS", video_id=media.video_id, context={"frame_id": row.frame_id})
                    continue
                try:
                    expected_raw = int(round(float(row.pts * Fraction(row.time_base)) * 1000.0))
                except Exception:
                    self.issue("P0", "FRAME_INDEX_TIME_BASE_INVALID", "frame_index", "Invalid time_base", video_id=media.video_id, context={"frame_id": row.frame_id, "time_base": row.time_base})
                    continue
                actual_raw = row.raw_timestamp_ms if row.raw_timestamp_ms is not None else expected_raw
                if abs(actual_raw - expected_raw) > self.policy.timestamp_tolerance_ms:
                    self.issue("P0", "PTS_TIME_BASE_ARITHMETIC_MISMATCH", "frame_index", "raw timestamp does not equal PTS × time-base", video_id=media.video_id, context={"frame_id": row.frame_id, "expected_raw_ms": expected_raw, "actual_raw_ms": actual_raw})
                expected_normalized = actual_raw - row.timeline_origin_ms
                if abs(row.timestamp_ms - expected_normalized) > self.policy.timestamp_tolerance_ms:
                    self.issue("P0", "NORMALIZED_TIMESTAMP_MISMATCH", "frame_index", "normalized timestamp is inconsistent", video_id=media.video_id, context={"frame_id": row.frame_id, "expected_ms": expected_normalized, "actual_ms": row.timestamp_ms})
            manifest_path = self.run_root / "frame_indexes" / f"{media.video_id}.manifest.json"
            if not manifest_path.is_file():
                self.issue("P0", "FRAME_INDEX_MANIFEST_MISSING", "frame_index", "Frame-index manifest missing", video_id=media.video_id)
            else:
                manifest = read_json(manifest_path)
                payload = [row.model_dump(mode="json") for row in rows]
                if manifest.get("records_sha256") != stable_json_hash(payload):
                    self.issue("P0", "FRAME_INDEX_MANIFEST_HASH_MISMATCH", "frame_index", "Frame-index records hash mismatch", video_id=media.video_id)
                if int(manifest.get("frame_count", -1)) != len(rows):
                    self.issue("P0", "FRAME_INDEX_COUNT_MISMATCH", "frame_index", "Frame-index count mismatch", video_id=media.video_id)
        return total, {"videos": len(self.frame_indexes), "frames": total}

    def check_keyframes_shots(self) -> tuple[int, dict[str, Any]]:
        self.frames = _load_models(self.run_root / "frames.jsonl", FrameRecord)
        self.shots = []
        for path in sorted((self.run_root / "shots").glob("*.jsonl")):
            self.shots.extend(_load_models(path, ShotRecord))
        originals = {
            (video_id, row.frame_id): row
            for video_id, rows in self.frame_indexes.items()
            for row in rows
        }
        seen: set[tuple[str, int]] = set()
        frames_by_shot: dict[tuple[str, str], list[FrameRecord]] = {}
        for row in self.frames:
            key = (row.video_id, row.frame_id)
            if key in seen:
                self.issue("P0", "KEYFRAME_DUPLICATE", "keyframes", "Duplicate keyframe original ID", video_id=row.video_id, context={"frame_id": row.frame_id})
            seen.add(key)
            original = originals.get(key)
            if original is None:
                self.issue("P0", "KEYFRAME_ORIGINAL_MISSING", "keyframes", "Keyframe does not reference original-frame index", video_id=row.video_id, context={"frame_id": row.frame_id})
            else:
                mismatches = {
                    "pts": (row.pts, original.pts),
                    "time_base": (row.time_base, original.time_base),
                    "timestamp_ms": (row.timestamp_ms, original.timestamp_ms),
                    "decode_index": (row.decode_index, original.decode_index),
                }
                if any(left != right for left, right in mismatches.values()):
                    self.issue("P0", "KEYFRAME_MAPPING_MISMATCH", "keyframes", "Keyframe mapping differs from original index", video_id=row.video_id, context={"frame_id": row.frame_id, "mismatches": mismatches})
            image = Path(row.keyframe_path)
            if not image.is_file() or cv2.imread(str(image)) is None:
                self.issue("P0", "KEYFRAME_IMAGE_INVALID", "keyframes", "Keyframe image missing or unreadable", video_id=row.video_id, artifact_path=image)
            frames_by_shot.setdefault((row.video_id, row.shot_id), []).append(row)

        shots_by_video: dict[str, list[ShotRecord]] = {}
        for shot in self.shots:
            shots_by_video.setdefault(shot.video_id, []).append(shot)
            start = originals.get((shot.video_id, shot.start_frame_id))
            end = originals.get((shot.video_id, shot.end_frame_id))
            if start is None or end is None:
                self.issue("P0", "SHOT_ORIGINAL_REFERENCE_MISSING", "keyframes", "Shot boundary not found in original index", video_id=shot.video_id, context={"shot_id": shot.shot_id})
            elif start.timestamp_ms != shot.start_timestamp_ms or end.timestamp_ms != shot.end_timestamp_ms:
                self.issue("P0", "SHOT_MAPPING_MISMATCH", "keyframes", "Shot timestamps differ from original index", video_id=shot.video_id, context={"shot_id": shot.shot_id})
            shot_frames = frames_by_shot.get((shot.video_id, shot.shot_id), [])
            if not shot_frames:
                self.issue("P0", "SHOT_WITHOUT_KEYFRAME", "keyframes", "Shot has no selected keyframe", video_id=shot.video_id, context={"shot_id": shot.shot_id})
                continue
            if self.settings.keyframes.strategy != "uniform" and not any(
                frame.selection_reason == "shot_representative" for frame in shot_frames
            ):
                self.issue("P1", "SHOT_REPRESENTATIVE_MISSING", "keyframes", "Shot lost its representative after dedup", video_id=shot.video_id, context={"shot_id": shot.shot_id}, production_blocker=True)
            if self.settings.keyframes.strategy in {"uniform", "shot_max_gap", "hybrid_shot_max_gap"}:
                points = [shot.start_timestamp_ms] + sorted(frame.timestamp_ms for frame in shot_frames) + [shot.end_timestamp_ms]
                largest = max((right - left for left, right in zip(points, points[1:])), default=0)
                if largest > self.settings.keyframes.max_gap_ms + self.policy.timestamp_tolerance_ms:
                    self.issue("P0", "KEYFRAME_MAX_GAP_VIOLATION", "keyframes", "Final keyframes violate max_gap_ms", video_id=shot.video_id, context={"shot_id": shot.shot_id, "largest_gap_ms": largest, "max_gap_ms": self.settings.keyframes.max_gap_ms})
            if self.policy.require_autoshot_for_stable and self.settings.keyframes.shot_model in {"autoshoot", "autoshoot_or_fallback"} and not shot.detector_name.lower().startswith("autoshot"):
                self.issue("P1", "DEGRADED_SHOT_DETECTOR", "keyframes", f"Actual detector is {shot.detector_name}, not AutoShot", video_id=shot.video_id, context={"shot_id": shot.shot_id}, production_blocker=True)

        for video_id, shots in shots_by_video.items():
            ordered = sorted(shots, key=lambda row: (row.start_timestamp_ms, row.start_frame_id))
            for left, right in zip(ordered, ordered[1:]):
                if right.start_timestamp_ms < left.end_timestamp_ms:
                    self.issue("P0", "SHOT_OVERLAP", "keyframes", "Shot intervals overlap", video_id=video_id, context={"left": left.shot_id, "right": right.shot_id})
        return len(self.frames) + len(self.shots), {"frames": len(self.frames), "shots": len(self.shots)}

    def check_temporal(self) -> tuple[int, dict[str, Any]]:
        self.temporal = _load_models(
            self.run_root / "temporal" / "temporal_frames.jsonl", TemporalFrameRecord
        )
        frame_map = {(row.video_id, row.frame_id): row for row in self.frames}
        temporal_map = {(row.video_id, row.frame_id): row for row in self.temporal}
        if set(frame_map) != set(temporal_map):
            self.issue("P0", "TEMPORAL_FRAME_SET_MISMATCH", "temporal", "Temporal registry frame set differs from frames.jsonl")
        grouped: dict[str, list[TemporalFrameRecord]] = {}
        for row in self.temporal:
            grouped.setdefault(row.video_id, []).append(row)
            source = frame_map.get((row.video_id, row.frame_id))
            if source and (source.timestamp_ms != row.timestamp_ms or source.pts != row.pts or source.time_base != row.time_base):
                self.issue("P0", "TEMPORAL_MAPPING_MISMATCH", "temporal", "Temporal record differs from keyframe mapping", video_id=row.video_id, context={"frame_id": row.frame_id})
        for video_id, rows in grouped.items():
            rows.sort(key=lambda item: (item.timestamp_ms, item.frame_id))
            for index, row in enumerate(rows):
                expected_previous = rows[index - 1].frame_id if index else None
                expected_next = rows[index + 1].frame_id if index + 1 < len(rows) else None
                if row.previous_frame_id != expected_previous or row.next_frame_id != expected_next:
                    self.issue("P0", "TEMPORAL_NEIGHBOR_MISMATCH", "temporal", "prev/next keyframe linkage is wrong", video_id=video_id, context={"frame_id": row.frame_id})
        manifest_path = self.run_root / "temporal" / "manifest.json"
        if not manifest_path.is_file():
            self.issue("P0", "TEMPORAL_MANIFEST_MISSING", "temporal", "Temporal manifest missing")
        else:
            manifest = read_json(manifest_path)
            if int(manifest.get("temporal_frame_count", -1)) != len(self.temporal):
                self.issue("P0", "TEMPORAL_COUNT_MISMATCH", "temporal", "Temporal manifest count mismatch")
        return len(self.temporal), {"records": len(self.temporal), "videos": len(grouped)}

    def check_decode_and_handoff(self) -> tuple[int, dict[str, Any]]:
        decode_path = self.run_root / "reports" / "decode_probe.json"
        decode = read_json(decode_path) if decode_path.is_file() else {}
        checked = 0
        for video_id, rows in decode.items():
            for row in rows:
                checked += 1
                if not row.get("decoded"):
                    self.issue("P0", "DECODE_PROBE_FAILED", "media", "Decode probe failed", video_id=video_id, context=row)
        required = [
            "corpus_manifest.jsonl",
            "media/media.jsonl",
            "frames.jsonl",
            "temporal/temporal_frames.jsonl",
            "temporal/manifest.json",
        ]
        for relative in required:
            if not (self.run_root / relative).is_file():
                self.issue("P0", "HANDOFF_ARTIFACT_MISSING", "handoff", f"Required handoff artifact missing: {relative}")
        handoff_candidates = [self.run_root / "handoff_tv1_tv3.json", self.run_root / "handoff_tv1.json"]
        if not any(path.is_file() for path in handoff_candidates):
            self.issue("P0", "HANDOFF_ARTIFACT_MISSING", "handoff", "Required TV1/TV3 handoff artifact missing")
        required.append(next((path.name for path in handoff_candidates if path.is_file()), "handoff_tv1_tv3.json"))
        return checked + len(required), {"decode_samples": checked, "required_handoff": required}

    def check_wp04_modalities(self) -> tuple[int, dict[str, Any]]:
        """Validate TV3 artifacts without weakening TV1 P0 mapping checks."""
        checked = 0
        frame_keys = {(row.video_id, row.frame_id) for row in self.frames}
        media_by_video = {row.video_id: row for row in self.media}

        ocr_path = self.run_root / "ocr" / "ocr.jsonl"
        if self.settings.ocr.enabled and not ocr_path.is_file():
            self.issue("P1", "OCR_ARTIFACT_MISSING", "ocr", "OCR is enabled but ocr.jsonl is missing")
        if ocr_path.is_file():
            seen: set[str] = set()
            for raw in read_jsonl(ocr_path):
                checked += 1
                try:
                    row = OCRDetection.model_validate(raw)
                except Exception as exc:
                    self.issue("P1", "OCR_RECORD_INVALID", "ocr", str(exc))
                    continue
                if row.detection_id in seen:
                    self.issue("P1", "OCR_DETECTION_DUPLICATE", "ocr", "Duplicate OCR detection_id", video_id=row.video_id)
                seen.add(row.detection_id)
                if (row.video_id, row.frame_id) not in frame_keys:
                    self.issue("P0", "OCR_FRAME_IDENTITY_MISMATCH", "ocr", "OCR record does not resolve to a TV1 FrameRecord", video_id=row.video_id, context={"frame_id": row.frame_id})
                if row.crop_evidence_path:
                    crop = (self.run_root / row.crop_evidence_path).resolve()
                    try:
                        crop.relative_to(self.run_root.resolve())
                    except ValueError:
                        self.issue("P0", "OCR_CROP_PATH_TRAVERSAL", "ocr", "OCR crop escapes run root", video_id=row.video_id)
                    else:
                        if not crop.is_file():
                            self.issue("P1", "OCR_CROP_MISSING", "ocr", "OCR evidence crop is missing", video_id=row.video_id)
                        elif row.crop_sha256 and sha256_file(crop) != row.crop_sha256:
                            self.issue("P1", "OCR_CROP_CHECKSUM_MISMATCH", "ocr", "OCR crop checksum mismatch", video_id=row.video_id)

        asr_path = self.run_root / "asr" / "asr.jsonl"
        if self.settings.asr.enabled and not asr_path.is_file():
            self.issue("P1", "ASR_ARTIFACT_MISSING", "asr", "ASR is enabled but asr.jsonl is missing")
        if asr_path.is_file():
            seen: set[str] = set()
            for raw in read_jsonl(asr_path):
                checked += 1
                try:
                    row = ASRSegment.model_validate(raw)
                except Exception as exc:
                    self.issue("P1", "ASR_RECORD_INVALID", "asr", str(exc))
                    continue
                if row.segment_id in seen:
                    self.issue("P1", "ASR_SEGMENT_DUPLICATE", "asr", "Duplicate ASR segment_id", video_id=row.video_id)
                seen.add(row.segment_id)
                media = media_by_video.get(row.video_id)
                if media is None:
                    self.issue("P0", "ASR_VIDEO_UNKNOWN", "asr", "ASR segment references unknown video", video_id=row.video_id)
                elif row.end_ms > media.duration_ms + self.policy.audio_duration_tolerance_ms:
                    self.issue("P1", "ASR_INTERVAL_OUT_OF_RANGE", "asr", "ASR interval exceeds media duration", video_id=row.video_id)

        object_path = self.run_root / "objects" / "objects.jsonl"
        if self.settings.object.enabled and not object_path.is_file():
            self.issue("P1", "OBJECT_ARTIFACT_MISSING", "object", "Object detection is enabled but objects.jsonl is missing")
        if object_path.is_file():
            seen: set[str] = set()
            for raw in read_jsonl(object_path):
                checked += 1
                try:
                    row = ObjectDetection.model_validate(raw)
                except Exception as exc:
                    self.issue("P1", "OBJECT_RECORD_INVALID", "object", str(exc))
                    continue
                if row.detection_id in seen:
                    self.issue("P1", "OBJECT_DETECTION_DUPLICATE", "object", "Duplicate object detection_id", video_id=row.video_id)
                seen.add(row.detection_id)
                if (row.video_id, row.frame_id) not in frame_keys:
                    self.issue("P0", "OBJECT_FRAME_IDENTITY_MISMATCH", "object", "Object record does not resolve to a TV1 FrameRecord", video_id=row.video_id, context={"frame_id": row.frame_id})
                if row.below_threshold and row.count_in_frame > 0:
                    self.issue("P1", "OBJECT_LOW_CONFIDENCE_COUNTED", "object", "Low-confidence object contributes to retrieval count", video_id=row.video_id)

        metadata_path = self.run_root / "metadata" / "metadata.jsonl"
        if metadata_path.is_file():
            seen: set[tuple[str, str, str | None]] = set()
            for raw in read_jsonl(metadata_path):
                checked += 1
                try:
                    row = MetadataRecord.model_validate(raw)
                except Exception as exc:
                    self.issue("P2", "METADATA_RECORD_INVALID", "metadata", str(exc))
                    continue
                if row.video_id not in media_by_video:
                    self.issue("P1", "METADATA_VIDEO_UNKNOWN", "metadata", "Metadata references unknown video", video_id=row.video_id)
                key = (str(row.source), row.video_id, row.source_record_sha256)
                if row.source_record_sha256 and key in seen:
                    self.issue("P2", "METADATA_SOURCE_DUPLICATE", "metadata", "Duplicate metadata source record", video_id=row.video_id)
                seen.add(key)

        catalog_manifest = self.run_root / "evidence_catalog" / "manifest.json"
        if self.settings.evidence_catalog.enabled and not catalog_manifest.is_file():
            self.issue(
                "P1",
                "EVIDENCE_CATALOG_MISSING",
                "evidence_catalog",
                "Evidence catalog is enabled but manifest is missing",
            )
        if catalog_manifest.is_file():
            checked += 1
            try:
                validate_evidence_catalog(self.run_root, verify_sources=True)
            except (EvidenceCatalogError, ValueError, OSError) as exc:
                self.issue(
                    "P1",
                    "EVIDENCE_CATALOG_INVALID_OR_STALE",
                    "evidence_catalog",
                    str(exc),
                )

        text_manifest = self.run_root / "text_index" / "manifest.json"
        if self.settings.text_index.enabled and not text_manifest.is_file():
            self.issue("P1", "TEXT_INDEX_ARTIFACT_MISSING", "text_index", "Text index is enabled but manifest is missing")
        if text_manifest.is_file():
            checked += 1
            try:
                validate_text_index_artifacts(self.run_root, self.settings)
            except (TextIndexValidationError, ValueError, OSError) as exc:
                self.issue("P1", "TEXT_INDEX_INVALID_OR_STALE", "text_index", str(exc))

        return checked, {"records_checked": checked}

    def build_mapping_audit(self) -> dict[str, Any]:
        samples: list[dict[str, Any]] = []
        by_video: dict[str, list] = {}
        for video_id, rows in self.frame_indexes.items():
            by_video[video_id] = rows
        keyframe_ids = {(row.video_id, row.frame_id) for row in self.frames}
        shot_boundaries = {
            (shot.video_id, shot.start_frame_id) for shot in self.shots
        } | {(shot.video_id, shot.end_frame_id) for shot in self.shots}
        for video_id in sorted(by_video):
            rows = by_video[video_id]
            positions = {0, len(rows) // 2, len(rows) - 1}
            positions.update(
                index
                for index, row in enumerate(rows)
                if (video_id, row.frame_id) in shot_boundaries
            )
            ordered = sorted(positions)[: max(3, self.policy.mapping_audit_samples_per_video)]
            for index in ordered:
                row = rows[index]
                samples.append(
                    {
                        "video_id": video_id,
                        "frame_id": row.frame_id,
                        "decode_index": row.decode_index,
                        "pts": row.pts,
                        "time_base": row.time_base,
                        "raw_timestamp_ms": row.raw_timestamp_ms,
                        "timeline_origin_ms": row.timeline_origin_ms,
                        "timestamp_ms": row.timestamp_ms,
                        "is_selected_keyframe": (video_id, row.frame_id) in keyframe_ids,
                        "is_shot_boundary": (video_id, row.frame_id) in shot_boundaries,
                    }
                )
        return {
            "preprocess_run_id": self.run_id,
            "sample_count": len(samples),
            "samples": samples,
            "created_at_utc": utcnow_iso(),
        }

    def validate(self) -> RunValidationReport:
        self.run_check("run_and_corpus", self.check_run_and_corpus)
        self.run_check("registry_artifacts", self.check_registry_artifacts)
        self.run_check("media_audio", self.check_media_audio)
        self.run_check("frame_indexes", self.check_frame_indexes)
        self.run_check("keyframes_shots", self.check_keyframes_shots)
        self.run_check("temporal", self.check_temporal)
        self.run_check("decode_handoff", self.check_decode_and_handoff)
        self.run_check("wp04_modalities", self.check_wp04_modalities)
        severity_counts = {
            level: sum(str(issue.severity) == level for issue in self.issues)
            for level in ["P0", "P1", "P2"]
        }
        g0_pass = severity_counts["P0"] == 0
        status_ok = self.run is not None and self.run.status in {
            "completed", "validated", "stable"
        }
        stable_eligible = g0_pass and status_ok and not self.production_blockers
        return RunValidationReport(
            preprocess_run_id=self.run_id,
            status="passed" if g0_pass else "failed",
            g0_pass=g0_pass,
            stable_eligible=stable_eligible,
            source_manifest_sha256=(self.run.source_manifest_sha256 if self.run else None),
            config_sha256=(self.run.config_sha256 if self.run else None),
            artifact_state_sha256=compute_artifact_state_sha256(self.run_root),
            severity_counts=severity_counts,
            checks=self.checks,
            issues=self.issues,
            validation_policy={
                **self.policy.__dict__,
                "production_blockers": sorted(self.production_blockers),
            },
            validated_at_utc=utcnow_iso(),
        )


def _validation_output_dir(run_root: Path, run_id: str, stable: bool) -> Path:
    if not stable:
        return run_root / "reports"
    stamp = utcnow_iso().replace(":", "-").replace("+", "_")
    return run_root.parent / "_audits" / run_id / stamp


class ValidationOutcome(tuple):
    """Tuple-compatible result that also delegates report attributes.

    TV1 callers can unpack ``report, path`` while Round-13.1 callers may use
    ``validate_run(...).issues`` directly.
    """

    def __new__(cls, report: RunValidationReport, path: Path):
        return super().__new__(cls, (report, path))

    @property
    def report(self) -> RunValidationReport:
        return self[0]

    @property
    def path(self) -> Path:
        return self[1]

    def __getattr__(self, name: str):
        return getattr(self.report, name)


def validate_run(
    run_id: str | Path,
    settings: Settings,
    *,
    policy: ValidationPolicy | None = None,
) -> tuple[RunValidationReport, Path]:
    requested = Path(run_id)
    if requested.is_dir():
        run_root = requested
        run_id = run_root.name
    else:
        run_id = str(run_id)
        run_root = Path(settings.paths.runs_root) / run_id
    if not run_root.is_dir():
        raise RunValidationError(f"Run root does not exist: {run_root}")
    registry_path = run_root / "registry" / "run_registry.sqlite3"
    stable = False
    if registry_path.is_file():
        with RunRegistry(registry_path) as registry:
            row = registry.get_run(run_id)
            stable = bool(row and row["status"] == "stable")
    validator = RunValidator(
        run_id,
        run_root,
        settings,
        policy
        or ValidationPolicy(
            timestamp_tolerance_ms=settings.media.pts_timestamp_tolerance_ms,
            audio_duration_tolerance_ms=settings.media.audio_duration_tolerance_ms,
        ),
    )
    report = validator.validate()
    output_dir = _validation_output_dir(run_root, run_id, stable)
    output_dir.mkdir(parents=True, exist_ok=True)
    audit_path = output_dir / "mapping_audit.json"
    write_json(audit_path, validator.build_mapping_audit())

    report_path = output_dir / "validation.json"
    payload = report.model_dump(mode="json")
    payload["report_sha256"] = None
    write_json(report_path, payload)
    file_sha = sha256_file(report_path)
    payload["report_sha256"] = file_sha
    write_json(report_path, payload)
    # The final file checksum changes when embedding its own hash.  Store the
    # actual file checksum in the registry; report_sha256 remains a content hint.
    actual_file_sha = sha256_file(report_path)
    report = RunValidationReport.model_validate(payload)

    if not stable and registry_path.is_file():
        with RunRegistry(registry_path) as registry:
            if report.g0_pass:
                registry.mark_validated(
                    run_id,
                    validation_report_path=report_path,
                    validation_report_sha256=actual_file_sha,
                    artifact_state_sha256=report.artifact_state_sha256 or "",
                    severity_counts=report.severity_counts,
                )
            else:
                registry.record_validation_failure(
                    run_id,
                    validation_report_path=report_path,
                    validation_report_sha256=actual_file_sha,
                    severity_counts=report.severity_counts,
                )
        manifest_path = run_root / "manifest.json"
        if manifest_path.is_file():
            run_manifest = PreprocessingRun.model_validate(read_json(manifest_path))
            if report.g0_pass:
                run_manifest.status = "validated"
            elif run_manifest.status != "stable":
                run_manifest.status = "partial"
            run_manifest.validation_report_path = str(report_path)
            write_json(manifest_path, run_manifest.model_dump(mode="json"))
    return ValidationOutcome(report, report_path)
