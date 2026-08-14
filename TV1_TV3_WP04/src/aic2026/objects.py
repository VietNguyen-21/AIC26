"""Object detector adapters, frame-level resume, spatial/count evidence, and retrieval."""

from __future__ import annotations

import re
import shutil
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, Sequence

import cv2

from .contracts import FrameRecord, ObjectDetection, SearchCandidate
from .evidence_catalog import EvidenceCatalog
from .ocr import normalize_search_text, strip_vietnamese_diacritics
from .utils import (
    read_json,
    read_jsonl,
    sha256_file,
    stable_json_hash,
    utcnow_iso,
    write_json,
    write_jsonl,
    write_parquet_optional,
)


# Retrieval counts exclude below-threshold detections while raw counts remain auditable.
class ObjectRuntimeError(RuntimeError):
    """Raised when a requested object detector cannot be initialized or executed."""


class ObjectAdapter(Protocol):
    name: str
    version: str

    def detect(self, image_path: str) -> list[dict[str, Any]]: ...

    def detect_batch(self, image_paths: Sequence[str]) -> list[list[dict[str, Any]]]: ...


class BaseObjectAdapter:
    name = "base"
    version = "0"

    def detect(self, image_path: str) -> list[dict[str, Any]]:
        raise NotImplementedError

    def detect_batch(self, image_paths: Sequence[str]) -> list[list[dict[str, Any]]]:
        return [self.detect(path) for path in image_paths]


class NoOpObjectAdapter(BaseObjectAdapter):
    name = "noop"
    version = "1"

    def detect(self, image_path: str) -> list[dict[str, Any]]:
        return []


class RFDETRAdapter(BaseObjectAdapter):
    """Optional RF-DETR adapter with a compatibility-oriented result parser.

    RF-DETR remains an optional runtime dependency. The adapter accepts the
    commonly exposed ``RFDETRBase`` class and parses supervision-like outputs
    (``xyxy``, ``confidence``, ``class_id``) without coupling the repository to
    one exact package release.
    """

    name = "rfdetr"

    def __init__(self, *, model_name: str = "base", checkpoint_path: Path | None = None, device: str = "auto"):
        try:
            import rfdetr  # type: ignore
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise ObjectRuntimeError("Install rfdetr to use the RF-DETR adapter") from exc
        class_name = {
            "base": "RFDETRBase",
            "large": "RFDETRLarge",
            "nano": "RFDETRNano",
            "small": "RFDETRSmall",
            "medium": "RFDETRMedium",
        }.get(model_name.lower(), model_name)
        model_class = getattr(rfdetr, class_name, None)
        if model_class is None:
            raise ObjectRuntimeError(f"RF-DETR class not found: {class_name}")
        kwargs: dict[str, Any] = {}
        if checkpoint_path is not None:
            if not checkpoint_path.is_file():
                raise ObjectRuntimeError(f"RF-DETR checkpoint not found: {checkpoint_path}")
            # Different package versions use either pretrain_weights or checkpoint.
            kwargs["pretrain_weights"] = str(checkpoint_path)
        try:
            self._model = model_class(**kwargs)
        except TypeError:
            if checkpoint_path is not None:
                kwargs = {"checkpoint": str(checkpoint_path)}
            self._model = model_class(**kwargs)
        self.device = device
        package_version = str(getattr(rfdetr, "__version__", "runtime"))
        checkpoint_tag = sha256_file(checkpoint_path)[:16] if checkpoint_path is not None else "default"
        self.version = f"{package_version}:{checkpoint_tag}"
        self._names = getattr(self._model, "class_names", None) or getattr(self._model, "names", None)

    def detect(self, image_path: str) -> list[dict[str, Any]]:
        try:
            output = self._model.predict(image_path)
        except TypeError:  # pragma: no cover - release-dependent
            output = self._model.predict(image_path, device=self.device)
        return _parse_detector_output(output, image_path, self._names)

def _parse_detector_output(
    output: Any,
    image_path: str,
    names: Any,
) -> list[dict[str, Any]]:
    """Convert RF-DETR/Supervision-style detections to the TV3 object schema."""

    del image_path  # Kept in the signature for adapter compatibility.

    if isinstance(output, (list, tuple)):
        if not output:
            return []
        if len(output) != 1:
            raise ObjectRuntimeError(
                "RF-DETR returned multiple prediction objects for a single image"
            )
        output = output[0]

    if isinstance(output, dict):
        boxes = output.get("xyxy")
        confidences = output.get("confidence")
        class_ids = output.get("class_id")
        data = output.get("data", {}) or {}
    else:
        boxes = getattr(output, "xyxy", None)
        confidences = getattr(output, "confidence", None)
        class_ids = getattr(output, "class_id", None)
        data = getattr(output, "data", {}) or {}

    if boxes is None:
        raise ObjectRuntimeError("RF-DETR output does not contain xyxy boxes")

    class_names = data.get("class_name") if hasattr(data, "get") else None

    detections: list[dict[str, Any]] = []

    for index, bbox in enumerate(boxes):
        class_id: int | None = None
        if class_ids is not None:
            class_id = int(class_ids[index])

        label = ""

        if class_names is not None and index < len(class_names):
            label = str(class_names[index]).strip()

        if not label and class_id is not None:
            if isinstance(names, dict):
                value = names.get(class_id, names.get(str(class_id), ""))
                label = str(value).strip()
            elif isinstance(names, (list, tuple)) and 0 <= class_id < len(names):
                label = str(names[class_id]).strip()

        if not label:
            label = str(class_id) if class_id is not None else "unknown"

        row: dict[str, Any] = {
            "label": label,
            "bbox": [float(value) for value in bbox],
        }

        if confidences is not None:
            row["confidence"] = float(confidences[index])

        if class_id is not None:
            row["class_id"] = class_id

        detections.append(row)

    return detections

@dataclass(frozen=True)
class ObjectAdapterResolution:
    adapter: ObjectAdapter
    requested_adapter: str
    selected_adapter: str
    attempts: tuple[dict[str, str], ...] = ()


@dataclass
class ObjectVideoResult:
    video_id: str
    detections: list[ObjectDetection]
    frame_count: int
    processed_frames: int
    resumed_frames: int
    failed_frames: int
    below_threshold_count: int
    artifact_paths: list[Path] = field(default_factory=list)
    frame_errors: list[dict[str, Any]] = field(default_factory=list)



def make_object_adapter(config: Any) -> ObjectAdapterResolution:
    """Resolve RF-DETR explicitly; no alternative detector fallback is permitted."""

    requested = str(config.adapter).lower()
    attempts: list[dict[str, str]] = []
    try:
        if requested == "rfdetr":
            adapter: ObjectAdapter = RFDETRAdapter(
                model_name=str(config.rfdetr_model_name),
                checkpoint_path=config.rfdetr_checkpoint_path,
                device=str(config.device),
            )
        elif requested == "noop":
            adapter = NoOpObjectAdapter()
        else:
            raise ObjectRuntimeError(f"Unsupported object adapter: {requested}")
        return ObjectAdapterResolution(adapter, requested, requested, tuple(attempts))
    except Exception as exc:
        attempts.append({"adapter": requested, "error": f"{type(exc).__name__}: {exc}"})
        raise


def _normalize_label(value: str) -> str:
    text = unicodedata.normalize("NFC", str(value)).strip().lower().replace("_", " ")
    return " ".join(text.split())


def _alias_map(config: Any) -> dict[str, str]:
    aliases: dict[str, str] = {}
    defaults = {
        "person": ["person", "people", "man", "woman", "human", "nguoi", "người", "đàn ông", "phụ nữ"],
        "car": ["car", "automobile", "oto", "ô tô", "xe hơi"],
        "motorcycle": ["motorcycle", "motorbike", "xe máy"],
        "bicycle": ["bicycle", "bike", "xe đạp"],
        "bus": ["bus", "xe buýt"],
        "truck": ["truck", "xe tải"],
        "traffic light": ["traffic light", "đèn giao thông"],
        "cell phone": ["cell phone", "mobile phone", "smartphone", "điện thoại"],
        "laptop": ["laptop", "máy tính xách tay"],
        "book": ["book", "sách"],
        "chair": ["chair", "ghế"],
        "table": ["table", "dining table", "bàn"],
        "dog": ["dog", "chó"],
        "cat": ["cat", "mèo"],
    }
    configured = dict(getattr(config, "label_aliases", {}) or {})
    defaults.update({str(key): list(value) for key, value in configured.items()})
    for canonical, values in defaults.items():
        canonical_norm = _normalize_label(canonical)
        aliases[canonical_norm] = canonical_norm
        aliases[normalize_search_text(strip_vietnamese_diacritics(canonical_norm))] = canonical_norm
        for value in values:
            normalized = _normalize_label(value)
            aliases[normalized] = canonical_norm
            aliases[normalize_search_text(strip_vietnamese_diacritics(normalized))] = canonical_norm
    return aliases


def _canonical_label(label: str, config: Any) -> tuple[str, list[str]]:
    normalized = _normalize_label(label)
    aliases = _alias_map(config)
    canonical = aliases.get(normalized) or aliases.get(normalize_search_text(strip_vietnamese_diacritics(normalized))) or normalized
    canonical_aliases = sorted({key for key, value in aliases.items() if value == canonical})
    return canonical, canonical_aliases


def _spatial_region(bbox: tuple[float, float, float, float]) -> tuple[str, tuple[float, float], float]:
    x1, y1, x2, y2 = bbox
    center_x = (x1 + x2) / 2.0
    center_y = (y1 + y2) / 2.0
    horizontal = "left" if center_x < 1 / 3 else "right" if center_x > 2 / 3 else "center"
    vertical = "top" if center_y < 1 / 3 else "bottom" if center_y > 2 / 3 else "center"
    if vertical == "center" and horizontal == "center":
        region = "center"
    elif vertical == "center":
        region = horizontal
    elif horizontal == "center":
        region = vertical
    else:
        region = f"{vertical}_{horizontal}"
    return region, (center_x, center_y), max(0.0, (x2 - x1) * (y2 - y1))


def _frame_fingerprint(frame: FrameRecord, config: Any, adapter: ObjectAdapter) -> str:
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
    return run_root / "objects" / "frames" / frame.video_id / f"{frame.frame_id:012d}.json"


def _load_resumable_frame(path: Path, fingerprint: str) -> list[ObjectDetection] | None:
    if not path.is_file():
        return None
    try:
        payload = read_json(path)
        if payload.get("status") != "completed" or payload.get("fingerprint") != fingerprint:
            return None
        return [ObjectDetection.model_validate(row) for row in payload.get("detections", [])]
    except Exception:
        return None


def _normalize_bbox(item: dict[str, Any], image_path: str) -> tuple[float, float, float, float]:
    bbox_value = item.get("bbox") or item.get("bbox_xyxy_norm") or item.get("xyxy")
    if bbox_value is None:
        raise ObjectRuntimeError("Object detection is missing bbox")
    values = [float(value) for value in bbox_value]
    if len(values) != 4:
        raise ObjectRuntimeError("Object bbox must contain four coordinates")
    if max(values) > 1.0:
        image = cv2.imread(image_path)
        if image is None:
            raise ObjectRuntimeError(f"Could not read object image: {image_path}")
        height, width = image.shape[:2]
        values = [values[0] / width, values[1] / height, values[2] / width, values[3] / height]
    x1, y1, x2, y2 = [max(0.0, min(1.0, value)) for value in values]
    if x1 > x2:
        x1, x2 = x2, x1
    if y1 > y2:
        y1, y2 = y2, y1
    return x1, y1, x2, y2


def _build_frame_detections(
    frame: FrameRecord,
    raw_items: Sequence[dict[str, Any]],
    adapter: ObjectAdapter,
    config: Any,
) -> list[ObjectDetection]:
    allowed = {_normalize_label(value) for value in getattr(config, "allowed_labels", [])}
    prepared: list[dict[str, Any]] = []

    # Parse every valid detector row first. Applying the frame limit before sorting
    # can discard a strong detection merely because a backend returned it later.
    for index, item in enumerate(raw_items):
        raw_label = str(item.get("label", item.get("class_name", ""))).strip()
        if not raw_label:
            continue
        canonical, aliases = _canonical_label(raw_label, config)
        if allowed and canonical not in allowed:
            continue
        bbox = _normalize_bbox(item, frame.keyframe_path)
        confidence_raw = item.get("confidence", item.get("score"))
        confidence = None if confidence_raw is None else max(0.0, min(1.0, float(confidence_raw)))
        below = confidence is not None and confidence < float(config.confidence_threshold)
        if below and not bool(config.keep_raw_below_threshold):
            continue
        region, center, area = _spatial_region(bbox)
        prepared.append(
            {
                "index": index,
                "raw_label": raw_label,
                "canonical": canonical,
                "aliases": aliases,
                "bbox": bbox,
                "confidence": confidence,
                "below": below,
                "region": region,
                "center": center,
                "area": area,
                "class_id": item.get("class_id"),
            }
        )

    # Deterministic top-confidence truncation. Rows without confidence are kept
    # after scored rows and original detector order breaks ties.
    prepared.sort(
        key=lambda item: (
            item["confidence"] is None,
            -(item["confidence"] if item["confidence"] is not None else 0.0),
            item["index"],
        )
    )
    prepared = prepared[: int(config.max_detections_per_frame)]

    # count_in_frame is retrieval evidence and therefore excludes detections
    # below the configured threshold. raw_count_in_frame remains available for
    # auditing how many retained detector rows existed before that quality gate.
    raw_counts = Counter(item["canonical"] for item in prepared)
    retrieval_counts = Counter(item["canonical"] for item in prepared if not item["below"])
    frame_sha = sha256_file(frame.keyframe_path)
    detections: list[ObjectDetection] = []
    for item in prepared:
        detections.append(
            ObjectDetection(
                preprocess_run_id=frame.preprocess_run_id,
                detection_id=f"object:{frame.video_id}:{frame.frame_id}:{item['index']}",
                video_id=frame.video_id,
                frame_id=frame.frame_id,
                timestamp_ms=frame.timestamp_ms,
                label=item["raw_label"],
                canonical_label=item["canonical"],
                label_aliases=item["aliases"],
                class_id=None if item["class_id"] is None else int(item["class_id"]),
                bbox_xyxy_norm=item["bbox"],
                center_xy_norm=item["center"],
                spatial_region=item["region"],
                area_ratio=item["area"],
                count_in_frame=retrieval_counts[item["canonical"]],
                raw_count_in_frame=raw_counts[item["canonical"]],
                confidence=item["confidence"],
                below_threshold=item["below"],
                source_keyframe_path=frame.keyframe_path,
                source_keyframe_sha256=frame_sha,
                model_name=adapter.name,
                model_version=adapter.version,
                created_at_utc=utcnow_iso(),
            )
        )
    return detections


def run_object_video(
    frames: Sequence[FrameRecord],
    run_root: str | Path,
    adapter: ObjectAdapter,
    config: Any,
    *,
    resolution: ObjectAdapterResolution | None = None,
) -> ObjectVideoResult:
    """Run resumable keyframe detection and persist normalized spatial/count evidence."""
    if not frames:
        raise ValueError("run_object_video requires at least one frame")
    root = Path(run_root)
    video_id = frames[0].video_id
    ordered = sorted(frames, key=lambda row: (row.timestamp_ms, row.frame_id))
    detections: list[ObjectDetection] = []
    pending: list[tuple[FrameRecord, str, Path]] = []
    resumed = processed = failed = 0
    frame_errors: list[dict[str, Any]] = []
    artifact_paths: set[Path] = set()

    for frame in ordered:
        fingerprint = _frame_fingerprint(frame, config, adapter)
        manifest_path = _frame_manifest_path(root, frame)
        if bool(config.frame_resume):
            cached = _load_resumable_frame(manifest_path, fingerprint)
            if cached is not None:
                detections.extend(cached)
                resumed += 1
                artifact_paths.add(manifest_path)
                continue
        pending.append((frame, fingerprint, manifest_path))

    batch_size = max(1, int(config.batch_size))
    for offset in range(0, len(pending), batch_size):
        batch = pending[offset : offset + batch_size]
        paths = [item[0].keyframe_path for item in batch]
        try:
            outputs = adapter.detect_batch(paths)
            if len(outputs) != len(batch):
                raise ObjectRuntimeError("Object batch output length differs from input length")
        except Exception:
            outputs = []
            for path in paths:
                try:
                    outputs.append(adapter.detect(path))
                except Exception as exc:
                    outputs.append([{"__error__": f"{type(exc).__name__}: {exc}"}])
        for (frame, fingerprint, manifest_path), raw_items in zip(batch, outputs):
            try:
                if raw_items and "__error__" in raw_items[0]:
                    raise ObjectRuntimeError(str(raw_items[0]["__error__"]))
                frame_detections = _build_frame_detections(frame, raw_items, adapter, config)
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
                if bool(config.fail_fast):
                    raise

    detections.sort(key=lambda row: (row.timestamp_ms, row.frame_id, row.detection_id))
    by_video = root / "objects" / "by_video" / f"{video_id}.jsonl"
    payload = [item.model_dump(mode="json") for item in detections]
    write_jsonl(by_video, payload)
    parquet = root / "objects" / "by_video" / f"{video_id}.parquet"
    write_parquet_optional(parquet, payload)
    report_path = root / "reports" / "objects" / f"{video_id}.json"
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
        "label_counts": dict(sorted(Counter(item.canonical_label or item.label for item in detections).items())),
        "frame_errors": frame_errors,
        "created_at_utc": utcnow_iso(),
    }
    write_json(report_path, report)
    artifact_paths.update({by_video, report_path})
    if parquet.exists():
        artifact_paths.add(parquet)
    return ObjectVideoResult(
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


def load_object_video_result(run_root: str | Path, video_id: str) -> ObjectVideoResult | None:
    root = Path(run_root)
    path = root / "objects" / "by_video" / f"{video_id}.jsonl"
    report_path = root / "reports" / "objects" / f"{video_id}.json"
    if not path.is_file() or not report_path.is_file():
        return None
    report = read_json(report_path)
    detections = [ObjectDetection.model_validate(row) for row in read_jsonl(path)]
    artifacts = [path, report_path]
    parquet = path.with_suffix(".parquet")
    if parquet.exists():
        artifacts.append(parquet)
    frames_dir = root / "objects" / "frames" / video_id
    if frames_dir.exists():
        artifacts.append(frames_dir)
    return ObjectVideoResult(
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


def cleanup_object_video(run_root: str | Path, video_id: str, *, preserve_frame_cache: bool = True) -> None:
    root = Path(run_root)
    (root / "objects" / "by_video" / f"{video_id}.jsonl").unlink(missing_ok=True)
    (root / "objects" / "by_video" / f"{video_id}.parquet").unlink(missing_ok=True)
    (root / "reports" / "objects" / f"{video_id}.json").unlink(missing_ok=True)
    if not preserve_frame_cache:
        shutil.rmtree(root / "objects" / "frames" / video_id, ignore_errors=True)


def consolidate_object_artifacts(run_root: str | Path) -> list[ObjectDetection]:
    root = Path(run_root)
    detections: list[ObjectDetection] = []
    for path in sorted((root / "objects" / "by_video").glob("*.jsonl")):
        detections.extend(ObjectDetection.model_validate(row) for row in read_jsonl(path))
    detections.sort(key=lambda row: (row.video_id, row.timestamp_ms, row.frame_id, row.detection_id))
    payload = [item.model_dump(mode="json") for item in detections]
    write_jsonl(root / "objects" / "objects.jsonl", payload)
    write_parquet_optional(root / "objects" / "objects.parquet", payload)
    reports = [read_json(path) for path in sorted((root / "reports" / "objects").glob("*.json"))]
    write_json(
        root / "reports" / "object_summary.json",
        {
            "video_count": len(reports),
            "frame_count": sum(int(item.get("frame_count", 0)) for item in reports),
            "processed_frames": sum(int(item.get("processed_frames", 0)) for item in reports),
            "resumed_frames": sum(int(item.get("resumed_frames", 0)) for item in reports),
            "failed_frames": sum(int(item.get("failed_frames", 0)) for item in reports),
            "detection_count": len(detections),
            "below_threshold_count": sum(item.below_threshold for item in detections),
            "label_counts": dict(sorted(Counter(item.canonical_label or item.label for item in detections).items())),
            "created_at_utc": utcnow_iso(),
        },
    )
    return detections


_NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "một": 1, "mot": 1, "hai": 2, "ba": 3, "bốn": 4, "bon": 4, "năm": 5, "nam": 5,
}
_SPATIAL_TERMS = {
    "left": {"left", "bên trái", "trái"},
    "right": {"right", "bên phải", "phải"},
    "top": {"top", "phía trên", "trên"},
    "bottom": {"bottom", "phía dưới", "dưới"},
    "center": {"center", "centre", "middle", "ở giữa", "trung tâm"},
}


def _parse_object_query(query: str, detections: Sequence[ObjectDetection]) -> dict[str, Any]:
    normalized = normalize_search_text(query)
    no_diacritics = normalize_search_text(strip_vietnamese_diacritics(query))
    text = f"{normalized} {no_diacritics}"
    labels: list[str] = []
    known: dict[str, set[str]] = defaultdict(set)
    for item in detections:
        canonical = item.canonical_label or _normalize_label(item.label)
        known[canonical].add(canonical)
        known[canonical].update(item.label_aliases)
        known[canonical].add(_normalize_label(item.label))
    ordered_matches: list[tuple[int, str]] = []
    query_for_position = no_diacritics
    for canonical, aliases in known.items():
        positions = []
        for alias in aliases:
            alias_normalized = normalize_search_text(strip_vietnamese_diacritics(alias))
            if alias_normalized:
                position = query_for_position.find(alias_normalized)
                if position >= 0:
                    positions.append(position)
        if positions:
            ordered_matches.append((min(positions), canonical))
    labels = [canonical for _, canonical in sorted(ordered_matches)]
    count = None
    match = re.search(r"\b(\d{1,2})\b", text)
    if match:
        count = int(match.group(1))
    else:
        for word, value in _NUMBER_WORDS.items():
            if re.search(rf"\b{re.escape(word)}\b", text):
                count = value
                break
    spatial = None
    for region, terms in _SPATIAL_TERMS.items():
        if any(term in text for term in terms):
            spatial = region
            break
    relation = None
    if "left of" in text or "bên trái của" in text or "trai cua" in text:
        relation = "left_of"
    elif "right of" in text or "bên phải của" in text or "phai cua" in text:
        relation = "right_of"
    elif "above" in text or "phía trên" in text or "tren" in text:
        relation = "above"
    elif "below" in text or "phía dưới" in text or "duoi" in text:
        relation = "below"
    return {"labels": list(dict.fromkeys(labels)), "count": count, "spatial": spatial, "relation": relation}


def _relation_satisfied(first: ObjectDetection, second: ObjectDetection, relation: str) -> bool:
    first_center = first.center_xy_norm or ((first.bbox_xyxy_norm[0] + first.bbox_xyxy_norm[2]) / 2, (first.bbox_xyxy_norm[1] + first.bbox_xyxy_norm[3]) / 2)
    second_center = second.center_xy_norm or ((second.bbox_xyxy_norm[0] + second.bbox_xyxy_norm[2]) / 2, (second.bbox_xyxy_norm[1] + second.bbox_xyxy_norm[3]) / 2)
    if relation == "left_of":
        return first_center[0] < second_center[0]
    if relation == "right_of":
        return first_center[0] > second_center[0]
    if relation == "above":
        return first_center[1] < second_center[1]
    if relation == "below":
        return first_center[1] > second_center[1]
    return False


def object_search(
    query_id: str,
    query: str,
    run_id: str,
    run_root: str | Path,
    k: int = 100,
    *,
    mode: str = "soft_boost",
) -> list[SearchCandidate]:
    """Score object labels, counts, regions, and pair relations as soft retrieval evidence."""
    root = Path(run_root)
    catalog_manifest = root / "evidence_catalog" / "manifest.json"
    catalog = EvidenceCatalog(root) if catalog_manifest.is_file() else None
    if catalog is not None:
        vocabulary = catalog.representative_object_vocabulary()
        parsed = _parse_object_query(query, vocabulary)
        detections = catalog.object_rows_for_labels(parsed["labels"])
    else:
        detections = [
            ObjectDetection.model_validate(row)
            for row in read_jsonl(root / "objects" / "objects.jsonl")
        ]
        detections = [item for item in detections if not item.below_threshold]
        parsed = _parse_object_query(query, detections)
    if not detections:
        return []
    if not any([parsed["labels"], parsed["count"], parsed["spatial"], parsed["relation"]]):
        return []
    grouped: dict[tuple[str, int], list[ObjectDetection]] = defaultdict(list)
    for item in detections:
        grouped[(item.video_id, item.frame_id)].append(item)
    scored: list[tuple[float, tuple[str, int], list[ObjectDetection], dict[str, Any]]] = []
    for key, rows in grouped.items():
        labels = Counter(item.canonical_label or item.label for item in rows)
        matched_labels = [label for label in parsed["labels"] if labels.get(label, 0) > 0]
        if parsed["labels"] and mode == "hard_filter" and len(matched_labels) != len(parsed["labels"]):
            continue
        score = 0.0
        if parsed["labels"]:
            score += 2.0 * len(matched_labels) / len(parsed["labels"])
        else:
            score += max((item.confidence or 0.0) for item in rows) * 0.25
        count_ok = None
        if parsed["count"] is not None and parsed["labels"]:
            count_ok = labels.get(parsed["labels"][0], 0) == parsed["count"]
            score += 1.5 if count_ok else -0.5
            if mode == "hard_filter" and not count_ok:
                continue
        spatial_ok = None
        if parsed["spatial"] and parsed["labels"]:
            candidates = [item for item in rows if (item.canonical_label or item.label) == parsed["labels"][0]]
            spatial_ok = any(parsed["spatial"] in (item.spatial_region or "") for item in candidates)
            score += 1.0 if spatial_ok else -0.25
            if mode == "hard_filter" and not spatial_ok:
                continue
        relation_ok = None
        if parsed["relation"] and len(parsed["labels"]) >= 2:
            first = [item for item in rows if (item.canonical_label or item.label) == parsed["labels"][0]]
            second = [item for item in rows if (item.canonical_label or item.label) == parsed["labels"][1]]
            relation_ok = any(_relation_satisfied(a, b, parsed["relation"]) for a in first for b in second)
            score += 1.5 if relation_ok else -0.5
            if mode == "hard_filter" and not relation_ok:
                continue
        score += max((item.confidence or 0.0) for item in rows) * 0.5
        if score <= 0 and parsed["labels"]:
            continue
        scored.append((score, key, rows, {"matched_labels": matched_labels, "count_ok": count_ok, "spatial_ok": spatial_ok, "relation_ok": relation_ok}))
    scored.sort(key=lambda item: (-item[0], item[1][0], item[1][1]))
    results: list[SearchCandidate] = []
    for rank, (score, _, rows, evidence) in enumerate(scored[:k], start=1):
        representative = max(rows, key=lambda item: item.confidence or 0.0)
        results.append(
            SearchCandidate(
                query_id=query_id,
                video_id=representative.video_id,
                frame_id=representative.frame_id,
                representative_frame_id=representative.frame_id,
                timestamp_ms=representative.timestamp_ms,
                source="object",
                raw_score=float(score),
                score=float(score),
                rank=rank,
                evidence_refs=[item.detection_id for item in rows],
                provenance_sources=["object"],
                provenance={
                    "query_parse": parsed,
                    "evidence": evidence,
                    "labels": dict(Counter(item.canonical_label or item.label for item in rows)),
                    "detections": [
                        {
                            "detection_id": item.detection_id,
                            "label": item.label,
                            "canonical_label": item.canonical_label,
                            "bbox_xyxy_norm": item.bbox_xyxy_norm,
                            "spatial_region": item.spatial_region,
                            "confidence": item.confidence,
                        }
                        for item in rows
                    ],
                    "mode": mode,
                    "frame_resolution": "source_keyframe",
                    "localization_required": False,
                    "submittable": True,
                },
                confidence=representative.confidence,
                preprocess_run_id=run_id,
                created_at_utc=utcnow_iso(),
            )
        )
    return results
