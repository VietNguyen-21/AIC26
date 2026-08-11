"""OCR adapters, Vietnamese normalization, crop evidence, frame resume, and retrieval."""

from __future__ import annotations

import json
import shutil
import subprocess
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, Sequence

import cv2

from .contracts import FrameRecord, OCRDetection, SearchCandidate
from .text_index import TextDocument, search_text_index
from .utils import (
    atomic_cv2_imwrite,
    read_json,
    read_jsonl,
    sha256_file,
    stable_json_hash,
    utcnow_iso,
    write_json,
    write_jsonl,
    write_parquet_optional,
)


# OCR detections retain raw low-confidence evidence, but retrieval can exclude it by policy.
class OCRRuntimeError(RuntimeError):
    """Raised when a requested OCR runtime cannot be initialized."""


class OCRAdapter(Protocol):
    name: str
    version: str

    def recognize(self, image_path: str) -> list[dict[str, Any]]: ...

    def recognize_batch(self, image_paths: Sequence[str]) -> list[list[dict[str, Any]]]: ...


class BaseOCRAdapter:
    name = "base"
    version = "0"

    def recognize(self, image_path: str) -> list[dict[str, Any]]:
        raise NotImplementedError

    def recognize_batch(self, image_paths: Sequence[str]) -> list[list[dict[str, Any]]]:
        return [self.recognize(path) for path in image_paths]


class DeepSoloParseqAdapter(BaseOCRAdapter):
    """External DeepSolo+PARSeq bridge.

    The upstream repositories/checkpoints remain external to this source-only
    package. The configured command must accept ``--image`` and ``--output`` and
    write a JSON list with ``text``, ``bbox`` and optional ``confidence`` fields.
    """

    name = "deep_solo_parseq"

    def __init__(self, *, command: Sequence[str], checkpoint_path: Path, timeout_seconds: int):
        if not command:
            raise OCRRuntimeError("deep_solo_parseq_command is required")
        if not checkpoint_path.is_file():
            raise OCRRuntimeError(f"DeepSolo+PARSeq checkpoint not found: {checkpoint_path}")
        self.command = list(command)
        self.checkpoint_path = checkpoint_path
        self.timeout_seconds = timeout_seconds
        self.version = sha256_file(checkpoint_path)[:16]

    def recognize(self, image_path: str) -> list[dict[str, Any]]:
        output = Path(image_path).with_suffix(Path(image_path).suffix + ".ocr-output.json")
        command = [
            part.format(
                image=str(Path(image_path).resolve()),
                output=str(output.resolve()),
                checkpoint=str(self.checkpoint_path.resolve()),
            )
            for part in self.command
        ]
        try:
            subprocess.run(command, check=True, timeout=self.timeout_seconds, capture_output=True, text=True)
            payload = json.loads(output.read_text(encoding="utf-8"))
        except Exception as exc:
            raise OCRRuntimeError(f"DeepSolo+PARSeq external command failed: {exc}") from exc
        finally:
            output.unlink(missing_ok=True)
        if not isinstance(payload, list):
            raise OCRRuntimeError("DeepSolo+PARSeq output must be a JSON list")
        return [dict(item) for item in payload]


class NoOpOCRAdapter(BaseOCRAdapter):
    name = "noop"
    version = "1"

    def recognize(self, image_path: str) -> list[dict[str, Any]]:
        return []


@dataclass(frozen=True)
class OCRAdapterResolution:
    adapter: OCRAdapter
    requested_adapter: str
    selected_adapter: str
    attempts: tuple[dict[str, str], ...] = ()


@dataclass
class OCRVideoResult:
    video_id: str
    detections: list[OCRDetection]
    frame_count: int
    processed_frames: int
    resumed_frames: int
    failed_frames: int
    below_threshold_count: int
    artifact_paths: list[Path] = field(default_factory=list)
    frame_errors: list[dict[str, Any]] = field(default_factory=list)



def make_ocr_adapter(config: Any) -> OCRAdapterResolution:
    """Resolve the selected OCR backend without silent model fallback."""

    requested = str(config.adapter).lower()
    attempts: list[dict[str, str]] = []
    try:
        if requested == "deep_solo_parseq":
            checkpoint = config.deep_solo_parseq_checkpoint_path
            if checkpoint is None:
                raise OCRRuntimeError("deep_solo_parseq_checkpoint_path is required")
            adapter: OCRAdapter = DeepSoloParseqAdapter(
                command=list(config.deep_solo_parseq_command),
                checkpoint_path=Path(checkpoint),
                timeout_seconds=int(config.deep_solo_parseq_timeout_seconds),
            )
        elif requested == "noop":
            adapter = NoOpOCRAdapter()
        else:
            raise OCRRuntimeError(f"Unsupported OCR adapter: {requested}")
        return OCRAdapterResolution(adapter, requested, requested, tuple(attempts))
    except Exception as exc:
        attempts.append({"adapter": requested, "error": f"{type(exc).__name__}: {exc}"})
        raise


def normalize_unicode_nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text).strip()


def normalize_search_text(text: str) -> str:
    value = normalize_unicode_nfc(text).lower()
    output: list[str] = []
    previous_space = False
    for character in value:
        if character.isalnum() or character == "_":
            output.append(character)
            previous_space = False
        elif not previous_space:
            output.append(" ")
            previous_space = True
    return " ".join("".join(output).split())


def strip_vietnamese_diacritics(text: str) -> str:
    value = normalize_unicode_nfc(text).replace("đ", "d").replace("Đ", "D")
    return "".join(
        character
        for character in unicodedata.normalize("NFD", value)
        if unicodedata.category(character) != "Mn"
    )


def punctuation_aware_text(text: str) -> str:
    value = normalize_unicode_nfc(text).lower()
    tokens: list[str] = []
    current: list[str] = []
    for character in value:
        if character.isalnum() or character == "_":
            current.append(character)
            continue
        if current:
            tokens.append("".join(current))
            current = []
        if not character.isspace():
            tokens.append(character)
    if current:
        tokens.append("".join(current))
    return " ".join(tokens)


def character_ngrams(text: str, min_n: int, max_n: int, max_items: int) -> list[str]:
    compact = normalize_search_text(strip_vietnamese_diacritics(text)).replace(" ", "_")
    values: list[str] = []
    seen: set[str] = set()
    for size in range(min_n, max_n + 1):
        for index in range(max(0, len(compact) - size + 1)):
            value = compact[index : index + size]
            if value and value not in seen:
                values.append(value)
                seen.add(value)
                if len(values) >= max_items:
                    return values
    return values


def _frame_fingerprint(frame: FrameRecord, config: Any, adapter: OCRAdapter) -> str:
    return stable_json_hash(
        {
            "keyframe_sha256": sha256_file(frame.keyframe_path),
            "video_id": frame.video_id,
            "frame_id": frame.frame_id,
            "timestamp_ms": frame.timestamp_ms,
            "adapter": adapter.name,
            "adapter_version": adapter.version,
            "config": config.model_dump(mode="json") if hasattr(config, "model_dump") else dict(config),
        }
    )


def _frame_manifest_path(run_root: Path, frame: FrameRecord) -> Path:
    return run_root / "ocr" / "frames" / frame.video_id / f"{frame.frame_id:012d}.json"


def _load_resumable_frame(path: Path, fingerprint: str, run_root: Path) -> list[OCRDetection] | None:
    if not path.is_file():
        return None
    try:
        payload = read_json(path)
        if payload.get("status") != "completed" or payload.get("fingerprint") != fingerprint:
            return None
        detections = [OCRDetection.model_validate(row) for row in payload.get("detections", [])]
        for detection in detections:
            if detection.crop_evidence_path:
                crop = run_root / detection.crop_evidence_path
                if not crop.is_file() or sha256_file(crop) != detection.crop_sha256:
                    return None
        return detections
    except Exception:
        return None


def _crop_detection(
    frame: FrameRecord,
    detection_id: str,
    bbox: tuple[float, float, float, float],
    run_root: Path,
    padding: int,
) -> tuple[str | None, str | None]:
    image = cv2.imread(frame.keyframe_path)
    if image is None:
        return None, None
    height, width = image.shape[:2]
    x1, y1, x2, y2 = bbox
    left = max(0, int(x1 * width) - padding)
    top = max(0, int(y1 * height) - padding)
    right = min(width, max(left + 1, int(round(x2 * width)) + padding))
    bottom = min(height, max(top + 1, int(round(y2 * height)) + padding))
    crop = image[top:bottom, left:right]
    if crop.size == 0:
        return None, None
    safe_id = detection_id.replace(":", "_")
    path = run_root / "ocr" / "crops" / frame.video_id / f"{safe_id}.jpg"
    atomic_cv2_imwrite(path, crop, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
    return path.relative_to(run_root).as_posix(), sha256_file(path)


def _build_detection(
    *,
    frame: FrameRecord,
    item: dict[str, Any],
    index: int,
    run_root: Path,
    adapter: OCRAdapter,
    config: Any,
) -> OCRDetection:
    raw_text = normalize_unicode_nfc(str(item.get("text", "")))
    bbox_value = item.get("bbox", (0.0, 0.0, 1.0, 1.0))
    bbox = tuple(float(value) for value in bbox_value)
    if len(bbox) != 4:
        raise OCRRuntimeError("OCR bbox must contain four normalized coordinates")
    confidence_value = item.get("confidence")
    confidence = None if confidence_value is None else max(0.0, min(1.0, float(confidence_value)))
    detection_id = f"ocr:{frame.video_id}:{frame.frame_id}:{index}"
    crop_path = crop_sha = None
    if config.crop_evidence:
        crop_path, crop_sha = _crop_detection(
            frame, detection_id, bbox, run_root, int(config.crop_padding_px)
        )
    polygon_value = item.get("polygon")
    polygon = None
    if polygon_value:
        polygon = tuple((float(point[0]), float(point[1])) for point in polygon_value)
    with_diacritics = normalize_search_text(raw_text)
    no_diacritics = normalize_search_text(strip_vietnamese_diacritics(raw_text))
    return OCRDetection(
        preprocess_run_id=frame.preprocess_run_id,
        detection_id=detection_id,
        video_id=frame.video_id,
        frame_id=frame.frame_id,
        timestamp_ms=frame.timestamp_ms,
        raw_text=raw_text,
        normalized_text=with_diacritics,
        normalized_text_no_diacritics=no_diacritics,
        punctuation_aware_text=punctuation_aware_text(raw_text),
        character_ngrams=character_ngrams(
            raw_text,
            int(config.character_ngram_min),
            int(config.character_ngram_max),
            int(config.max_character_ngrams),
        ),
        bbox_xyxy_norm=bbox,
        polygon_norm=polygon,
        confidence=confidence,
        below_threshold=confidence is not None and confidence < float(config.confidence_threshold),
        crop_evidence_path=crop_path,
        crop_sha256=crop_sha,
        source_keyframe_sha256=sha256_file(frame.keyframe_path),
        model_name=adapter.name,
        model_version=adapter.version,
        created_at_utc=utcnow_iso(),
    )


def run_ocr_video(
    frames: Sequence[FrameRecord],
    run_root: str | Path,
    adapter: OCRAdapter,
    config: Any,
    *,
    resolution: OCRAdapterResolution | None = None,
) -> OCRVideoResult:
    """Run resumable frame-level OCR and persist text, geometry, crops, and checksums."""
    if not frames:
        raise ValueError("run_ocr_video requires at least one frame")
    root = Path(run_root)
    video_id = frames[0].video_id
    ordered = sorted(frames, key=lambda row: (row.timestamp_ms, row.frame_id))
    detections: list[OCRDetection] = []
    pending: list[tuple[FrameRecord, str, Path]] = []
    resumed = 0
    processed = 0
    failed = 0
    frame_errors: list[dict[str, Any]] = []
    artifact_paths: set[Path] = set()

    for frame in ordered:
        fingerprint = _frame_fingerprint(frame, config, adapter)
        manifest_path = _frame_manifest_path(root, frame)
        if config.frame_resume:
            cached = _load_resumable_frame(manifest_path, fingerprint, root)
            if cached is not None:
                detections.extend(cached)
                resumed += 1
                artifact_paths.add(manifest_path)
                for item in cached:
                    if item.crop_evidence_path:
                        artifact_paths.add(root / item.crop_evidence_path)
                continue
        pending.append((frame, fingerprint, manifest_path))

    batch_size = max(1, int(config.batch_size))
    for offset in range(0, len(pending), batch_size):
        batch = pending[offset : offset + batch_size]
        paths = [item[0].keyframe_path for item in batch]
        try:
            outputs = adapter.recognize_batch(paths)
            if len(outputs) != len(batch):
                raise OCRRuntimeError("OCR batch output length differs from input length")
        except Exception:
            outputs = []
            for path in paths:
                try:
                    outputs.append(adapter.recognize(path))
                except Exception as exc:
                    outputs.append([{"__error__": f"{type(exc).__name__}: {exc}"}])
        for (frame, fingerprint, manifest_path), raw_items in zip(batch, outputs):
            try:
                if raw_items and "__error__" in raw_items[0]:
                    raise OCRRuntimeError(str(raw_items[0]["__error__"]))
                frame_detections = [
                    _build_detection(
                        frame=frame,
                        item=item,
                        index=index,
                        run_root=root,
                        adapter=adapter,
                        config=config,
                    )
                    for index, item in enumerate(raw_items)
                    if str(item.get("text", "")).strip()
                ]
                if not config.keep_raw_below_threshold:
                    frame_detections = [item for item in frame_detections if not item.below_threshold]
                write_json(
                    manifest_path,
                    {
                        "schema_version": "1.0.0",
                        "status": "completed",
                        "preprocess_run_id": frame.preprocess_run_id,
                        "video_id": frame.video_id,
                        "frame_id": frame.frame_id,
                        "timestamp_ms": frame.timestamp_ms,
                        "fingerprint": fingerprint,
                        "adapter_name": adapter.name,
                        "adapter_version": adapter.version,
                        "detections": [item.model_dump(mode="json") for item in frame_detections],
                        "created_at_utc": utcnow_iso(),
                    },
                )
                detections.extend(frame_detections)
                processed += 1
                artifact_paths.add(manifest_path)
                for item in frame_detections:
                    if item.crop_evidence_path:
                        artifact_paths.add(root / item.crop_evidence_path)
            except Exception as exc:
                failed += 1
                error = f"{type(exc).__name__}: {exc}"
                frame_errors.append({"frame_id": frame.frame_id, "error": error})
                write_json(
                    manifest_path,
                    {
                        "schema_version": "1.0.0",
                        "status": "failed",
                        "preprocess_run_id": frame.preprocess_run_id,
                        "video_id": frame.video_id,
                        "frame_id": frame.frame_id,
                        "timestamp_ms": frame.timestamp_ms,
                        "fingerprint": fingerprint,
                        "adapter_name": adapter.name,
                        "adapter_version": adapter.version,
                        "error": error,
                        "created_at_utc": utcnow_iso(),
                    },
                )
                artifact_paths.add(manifest_path)
                if config.fail_fast:
                    raise

    detections.sort(key=lambda row: (row.timestamp_ms, row.frame_id, row.detection_id))
    by_video = root / "ocr" / "by_video" / f"{video_id}.jsonl"
    write_jsonl(by_video, [item.model_dump(mode="json") for item in detections])
    parquet = root / "ocr" / "by_video" / f"{video_id}.parquet"
    write_parquet_optional(parquet, [item.model_dump(mode="json") for item in detections])
    report_path = root / "reports" / "ocr" / f"{video_id}.json"
    report = {
        "preprocess_run_id": frames[0].preprocess_run_id,
        "video_id": video_id,
        "requested_adapter": resolution.requested_adapter if resolution else adapter.name,
        "selected_adapter": resolution.selected_adapter if resolution else adapter.name,
        "adapter_name": adapter.name,
        "adapter_version": adapter.version,
        "adapter_attempts": list(resolution.attempts) if resolution else [],
        "frame_count": len(ordered),
        "processed_frames": processed,
        "resumed_frames": resumed,
        "failed_frames": failed,
        "detection_count": len(detections),
        "below_threshold_count": sum(item.below_threshold for item in detections),
        "frame_errors": frame_errors,
        "created_at_utc": utcnow_iso(),
    }
    write_json(report_path, report)
    artifact_paths.update({by_video, report_path})
    if parquet.exists():
        artifact_paths.add(parquet)
    return OCRVideoResult(
        video_id=video_id,
        detections=detections,
        frame_count=len(ordered),
        processed_frames=processed,
        resumed_frames=resumed,
        failed_frames=failed,
        below_threshold_count=sum(item.below_threshold for item in detections),
        artifact_paths=sorted(artifact_paths),
        frame_errors=frame_errors,
    )


def load_ocr_video_result(run_root: str | Path, video_id: str) -> OCRVideoResult | None:
    root = Path(run_root)
    path = root / "ocr" / "by_video" / f"{video_id}.jsonl"
    report_path = root / "reports" / "ocr" / f"{video_id}.json"
    if not path.is_file() or not report_path.is_file():
        return None
    report = read_json(report_path)
    detections = [OCRDetection.model_validate(row) for row in read_jsonl(path)]
    artifacts = [path, report_path]
    parquet = path.with_suffix(".parquet")
    if parquet.exists():
        artifacts.append(parquet)
    frames_dir = root / "ocr" / "frames" / video_id
    crops_dir = root / "ocr" / "crops" / video_id
    if frames_dir.exists():
        artifacts.append(frames_dir)
    if crops_dir.exists():
        artifacts.append(crops_dir)
    return OCRVideoResult(
        video_id=video_id,
        detections=detections,
        frame_count=int(report.get("frame_count", 0)),
        processed_frames=int(report.get("processed_frames", 0)),
        resumed_frames=int(report.get("resumed_frames", 0)),
        failed_frames=int(report.get("failed_frames", 0)),
        below_threshold_count=int(report.get("below_threshold_count", 0)),
        artifact_paths=artifacts,
        frame_errors=list(report.get("frame_errors", [])),
    )


def cleanup_ocr_video(run_root: str | Path, video_id: str, *, preserve_frame_cache: bool = True) -> None:
    root = Path(run_root)
    (root / "ocr" / "by_video" / f"{video_id}.jsonl").unlink(missing_ok=True)
    (root / "ocr" / "by_video" / f"{video_id}.parquet").unlink(missing_ok=True)
    (root / "reports" / "ocr" / f"{video_id}.json").unlink(missing_ok=True)
    if not preserve_frame_cache:
        shutil.rmtree(root / "ocr" / "frames" / video_id, ignore_errors=True)
        shutil.rmtree(root / "ocr" / "crops" / video_id, ignore_errors=True)


def consolidate_ocr_artifacts(run_root: str | Path) -> list[OCRDetection]:
    root = Path(run_root)
    detections: list[OCRDetection] = []
    for path in sorted((root / "ocr" / "by_video").glob("*.jsonl")):
        detections.extend(OCRDetection.model_validate(row) for row in read_jsonl(path))
    detections.sort(key=lambda row: (row.video_id, row.timestamp_ms, row.frame_id, row.detection_id))
    payload = [item.model_dump(mode="json") for item in detections]
    write_jsonl(root / "ocr" / "ocr.jsonl", payload)
    write_parquet_optional(root / "ocr" / "ocr.parquet", payload)
    reports = [read_json(path) for path in sorted((root / "reports" / "ocr").glob("*.json"))]
    write_json(
        root / "reports" / "ocr_summary.json",
        {
            "video_count": len(reports),
            "frame_count": sum(int(item.get("frame_count", 0)) for item in reports),
            "processed_frames": sum(int(item.get("processed_frames", 0)) for item in reports),
            "resumed_frames": sum(int(item.get("resumed_frames", 0)) for item in reports),
            "failed_frames": sum(int(item.get("failed_frames", 0)) for item in reports),
            "detection_count": len(detections),
            "below_threshold_count": sum(item.below_threshold for item in detections),
            "created_at_utc": utcnow_iso(),
        },
    )
    return detections


def build_ocr_documents(run_root: str | Path, *, include_below_threshold: bool = False) -> list[TextDocument]:
    documents: list[TextDocument] = []
    for row in read_jsonl(Path(run_root) / "ocr" / "ocr.jsonl"):
        detection = OCRDetection.model_validate(row)
        if detection.below_threshold and not include_below_threshold:
            continue
        searchable = " ".join(
            value
            for value in [
                detection.normalized_text,
                detection.normalized_text_no_diacritics,
                detection.punctuation_aware_text,
                " ".join(detection.character_ngrams),
            ]
            if value
        )
        documents.append(
            TextDocument(
                detection.detection_id,
                searchable,
                {**detection.model_dump(mode="json"), "source": "ocr"},
            )
        )
    return documents


def ocr_search(
    query_id: str,
    query: str,
    run_id: str,
    run_root: str | Path,
    k: int = 100,
    *,
    settings: Any | None = None,
) -> list[SearchCandidate]:
    """Search persistent OCR evidence and return frame-localized candidates."""
    return search_text_index(
        query_id,
        query,
        run_id,
        run_root,
        k,
        settings=settings,
        source_filter={"ocr"},
    )
