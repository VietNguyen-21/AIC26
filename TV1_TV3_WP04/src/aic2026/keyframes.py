"""Shot detection, quality-aware keyframe selection, deduplication, and temporal gap
control."""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Literal

import cv2
import numpy as np

from .autoshot import (
    AutoShotError,
    AutoShotRuntimeConfig,
    OfficialAutoShotPredictor,
    collapse_boundary_runs,
)
from .contracts import FrameRecord, MediaRecord, ShotRecord
from .frame_index import FrameIndexError, OriginalFrameIndex
from .media import FrameResolver, ensure_original_frame_index
from .utils import (
    atomic_cv2_imwrite,
    stable_json_hash,
    utcnow_iso,
    write_json,
    write_jsonl,
    write_parquet_optional,
)

SelectionReason = Literal["shot_representative", "max_gap", "boundary_guard", "manual"]


class ShotDetectionError(RuntimeError):
    """Raised when a configured shot detector cannot return valid shots."""


@dataclass(frozen=True)
class QualityMetrics:
    composite: float
    sharpness: float
    blur_score: float
    black_ratio: float
    face_visibility: float
    text_visibility: float


@dataclass(frozen=True)
class CandidateAnchor:
    timestamp_ms: int
    reason: SelectionReason
    shot_id: str


@dataclass
class SelectedFrame:
    record: object
    frame: np.ndarray
    reason: SelectionReason
    shot_id: str
    quality: QualityMetrics
    image_hash: int | None = None


class ShotDetector:
    name = "abstract"
    version = "0"

    def detect(
        self,
        media: MediaRecord,
        index: OriginalFrameIndex,
        resolver: FrameResolver,
    ) -> list[ShotRecord]:
        raise NotImplementedError


def _records_to_shots(
    media: MediaRecord,
    index: OriginalFrameIndex,
    boundary_frames: Iterable[tuple[int, float]],
    detector_name: str,
    detector_version: str,
    min_shot_ms: int,
) -> list[ShotRecord]:
    """Convert start-of-next-shot frame IDs into inclusive shot records."""

    candidates: list[tuple[int, float]] = []
    for frame_id, confidence in sorted(boundary_frames):
        if frame_id <= 0 or frame_id >= index.frame_count:
            continue
        timestamp = index.get(frame_id).timestamp_ms
        if not candidates:
            candidates.append((frame_id, float(confidence)))
            continue
        previous_frame, previous_confidence = candidates[-1]
        previous_timestamp = index.get(previous_frame).timestamp_ms
        if timestamp - previous_timestamp < min_shot_ms:
            if confidence > previous_confidence:
                candidates[-1] = (frame_id, float(confidence))
        else:
            candidates.append((frame_id, float(confidence)))

    starts = [0] + [frame_id for frame_id, _ in candidates]
    confidence_by_start = {frame_id: score for frame_id, score in candidates}
    shots: list[ShotRecord] = []
    for shot_index, start_frame_id in enumerate(starts):
        end_frame_id = (
            starts[shot_index + 1] - 1
            if shot_index + 1 < len(starts)
            else index.frame_count - 1
        )
        start = index.get(start_frame_id)
        end = index.get(end_frame_id)
        if end.timestamp_ms < start.timestamp_ms:
            raise ShotDetectionError("Shot timestamps are not monotonic")
        confidence = confidence_by_start.get(starts[shot_index + 1], None) if shot_index + 1 < len(starts) else None
        shots.append(
            ShotRecord(
                preprocess_run_id=media.preprocess_run_id,
                video_id=media.video_id,
                shot_id=f"{media.video_id}:shot:{shot_index:06d}",
                start_frame_id=start_frame_id,
                end_frame_id=end_frame_id,
                start_timestamp_ms=start.timestamp_ms,
                end_timestamp_ms=end.timestamp_ms,
                start_pts=start.pts,
                end_pts=end.pts,
                detector_name=detector_name,
                detector_version=detector_version,
                confidence=confidence,
                created_at_utc=utcnow_iso(),
            )
        )
    if not shots:
        raise ShotDetectionError(f"{detector_name} returned no valid shots")
    return shots


class AutoShotDetector(ShotDetector):
    name = "autoshoot_official"

    def __init__(self, settings):
        keyframes = settings.keyframes
        repo_root = getattr(keyframes, "autoshoot_repo_root", None)
        checkpoint = getattr(keyframes, "autoshoot_checkpoint_path", None)
        if not repo_root or not checkpoint:
            raise AutoShotError(
                "AutoShot requires keyframes.autoshoot_repo_root and "
                "keyframes.autoshoot_checkpoint_path"
            )
        config = AutoShotRuntimeConfig(
            repo_root=Path(repo_root),
            checkpoint_path=Path(checkpoint),
            device=str(getattr(keyframes, "autoshoot_device", "auto")),
            model_filename=str(
                getattr(
                    keyframes,
                    "autoshoot_model_filename",
                    "supernet_flattransf_3_8_8_8_13_12_0_16_60.py",
                )
            ),
            checkpoint_key=str(getattr(keyframes, "autoshoot_checkpoint_key", "net")),
            threshold=float(getattr(keyframes, "autoshoot_threshold", 0.296)),
            min_loaded_parameter_ratio=float(
                getattr(keyframes, "autoshoot_min_loaded_parameter_ratio", 0.99)
            ),
        )
        self.predictor = OfficialAutoShotPredictor(config)
        self.threshold = config.threshold
        self.min_shot_ms = int(getattr(keyframes, "min_shot_ms", 500))
        self.version = "official-cvprw2023"

    def detect(self, media, index, resolver) -> list[ShotRecord]:
        prediction = self.predictor.predict_boundary_scores(media.original_video_path)
        scores = prediction.boundary_scores.reshape(-1)
        if abs(len(scores) - index.frame_count) > 2:
            raise ShotDetectionError(
                "AutoShot prediction/frame-index mismatch: "
                f"scores={len(scores)}, frames={index.frame_count}"
            )
        if len(scores) < index.frame_count:
            scores = np.pad(scores, (0, index.frame_count - len(scores)), mode="edge")
        elif len(scores) > index.frame_count:
            scores = scores[: index.frame_count]
        boundaries = collapse_boundary_runs(scores, self.threshold)
        version = f"{prediction.model_version}:{prediction.checkpoint_sha256[:12]}"
        return _records_to_shots(
            media,
            index,
            boundaries,
            self.name,
            version,
            self.min_shot_ms,
        )


class PySceneDetectAdapter(ShotDetector):
    name = "pyscenedetect_content"

    def __init__(self, threshold: float = 27.0, min_scene_len_frames: int = 15):
        self.threshold = threshold
        self.min_scene_len_frames = min_scene_len_frames
        self.version = "unavailable"

    def detect(self, media, index, resolver) -> list[ShotRecord]:
        try:
            import scenedetect
            from scenedetect import SceneManager, open_video
            from scenedetect.detectors import ContentDetector
        except ImportError as exc:
            raise ShotDetectionError("PySceneDetect is not installed") from exc

        self.version = str(getattr(scenedetect, "__version__", "unknown"))
        video = open_video(media.original_video_path)
        manager = SceneManager()
        manager.add_detector(
            ContentDetector(
                threshold=self.threshold,
                min_scene_len=self.min_scene_len_frames,
            )
        )
        manager.detect_scenes(video, show_progress=False)
        scenes = manager.get_scene_list(start_in_scene=True)
        if not scenes:
            return _records_to_shots(
                media,
                index,
                [],
                self.name,
                self.version,
                0,
            )
        boundaries: list[tuple[int, float]] = []
        for start, _end in scenes[1:]:
            frame_id = min(index.frame_count - 1, max(1, int(start.get_frames())))
            boundaries.append((frame_id, 1.0))
        return _records_to_shots(
            media,
            index,
            boundaries,
            self.name,
            self.version,
            0,
        )


class HistogramShotDetector(ShotDetector):
    name = "pts_histogram"
    version = "2.0.0"

    def __init__(
        self,
        sample_every_ms: int = 500,
        threshold: float = 0.48,
        min_shot_ms: int = 500,
    ):
        self.sample_every_ms = sample_every_ms
        self.threshold = threshold
        self.min_shot_ms = min_shot_ms

    @staticmethod
    def feature(frame: np.ndarray) -> np.ndarray:
        small = cv2.resize(frame, (160, 90), interpolation=cv2.INTER_AREA)
        hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
        hist = cv2.calcHist([hsv], [0, 1], None, [24, 16], [0, 180, 0, 256])
        return cv2.normalize(hist, hist).flatten()

    def detect(self, media, index, resolver) -> list[ShotRecord]:
        previous: np.ndarray | None = None
        boundaries: list[tuple[int, float]] = []
        sampled = index.iter_window(0, max(0, media.duration_ms - 1), self.sample_every_ms)
        for resolved in sampled:
            decoded = resolver.get_frame_with_record(resolved.record.frame_id)
            current = self.feature(decoded.image_bgr)
            if previous is not None:
                distance = float(
                    cv2.compareHist(
                        previous.astype(np.float32),
                        current.astype(np.float32),
                        cv2.HISTCMP_BHATTACHARYYA,
                    )
                )
                if distance >= self.threshold:
                    boundaries.append((resolved.record.frame_id, min(1.0, distance)))
            previous = current
        return _records_to_shots(
            media,
            index,
            boundaries,
            self.name,
            self.version,
            self.min_shot_ms,
        )


class UniformShotDetector(ShotDetector):
    name = "uniform_single_shot"
    version = "1.0.0"

    def detect(self, media, index, resolver) -> list[ShotRecord]:
        return _records_to_shots(media, index, [], self.name, self.version, 0)


def _select_shot_detector(settings) -> tuple[ShotDetector, list[str]]:
    model = str(settings.keyframes.shot_model)
    warnings: list[str] = []
    if settings.keyframes.strategy == "uniform":
        return UniformShotDetector(), warnings
    if model in {"autoshoot", "autoshoot_or_fallback"}:
        try:
            return AutoShotDetector(settings), warnings
        except (AutoShotError, ValueError) as exc:
            if model == "autoshoot":
                raise ShotDetectionError(str(exc)) from exc
            warnings.append(f"AutoShot unavailable: {exc}")
    if model in {"pyscenedetect", "autoshoot_or_fallback"}:
        try:
            import scenedetect  # noqa: F401

            return PySceneDetectAdapter(
                threshold=float(settings.keyframes.pyscenedetect_threshold),
                min_scene_len_frames=int(
                    settings.keyframes.pyscenedetect_min_scene_len_frames
                ),
            ), warnings
        except ImportError:
            if model == "pyscenedetect":
                raise ShotDetectionError("PySceneDetect is not installed")
            warnings.append("PySceneDetect unavailable; using PTS histogram fallback")
    return (
        HistogramShotDetector(
            int(settings.keyframes.sample_every_ms),
            float(settings.keyframes.shot_threshold),
            int(settings.keyframes.min_shot_ms),
        ),
        warnings,
    )


def _face_visibility(gray: np.ndarray) -> float:
    cascade_path = Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"
    if not cascade_path.exists():
        return 0.0
    detector = cv2.CascadeClassifier(str(cascade_path))
    faces = detector.detectMultiScale(gray, scaleFactor=1.15, minNeighbors=4, minSize=(20, 20))
    area = float(gray.shape[0] * gray.shape[1])
    return min(1.0, sum(float(w * h) for _x, _y, w, h in faces) / max(1.0, area))


def _text_visibility(gray: np.ndarray) -> float:
    resized = cv2.resize(gray, (320, max(1, int(gray.shape[0] * 320 / gray.shape[1]))))
    gradient = cv2.morphologyEx(
        resized,
        cv2.MORPH_GRADIENT,
        cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)),
    )
    _, binary = cv2.threshold(gradient, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    closed = cv2.morphologyEx(
        binary,
        cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_RECT, (9, 3)),
    )
    contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    frame_area = float(closed.shape[0] * closed.shape[1])
    text_area = 0.0
    for contour in contours:
        _x, _y, width, height = cv2.boundingRect(contour)
        if width >= 12 and 2 <= height <= 60 and width / max(1, height) >= 1.5:
            text_area += float(width * height)
    return min(1.0, text_area / max(1.0, frame_area * 0.25))


def quality_score(frame: np.ndarray, settings) -> QualityMetrics:
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    black_ratio = float((gray < 12).mean())
    blur_score = float(1.0 / (1.0 + sharpness / 100.0))
    face_visibility = (
        _face_visibility(gray) if float(settings.keyframes.quality_face_weight) > 0 else 0.0
    )
    text_visibility = (
        _text_visibility(gray) if float(settings.keyframes.quality_text_weight) > 0 else 0.0
    )
    composite = (
        float(settings.keyframes.quality_sharpness_weight) * math.log1p(sharpness)
        - float(settings.keyframes.quality_black_weight) * black_ratio
        - float(settings.keyframes.quality_blur_weight) * blur_score
        + float(settings.keyframes.quality_face_weight) * face_visibility
        + float(settings.keyframes.quality_text_weight) * text_visibility
    )
    return QualityMetrics(
        composite=float(composite),
        sharpness=sharpness,
        blur_score=blur_score,
        black_ratio=black_ratio,
        face_visibility=face_visibility,
        text_visibility=text_visibility,
    )


def dhash(frame: np.ndarray, size: int = 8) -> int:
    gray = cv2.cvtColor(
        cv2.resize(frame, (size + 1, size), interpolation=cv2.INTER_AREA),
        cv2.COLOR_BGR2GRAY,
    )
    diff = gray[:, 1:] > gray[:, :-1]
    value = 0
    for bit in diff.flatten():
        value = (value << 1) | int(bit)
    return value


def phash(frame: np.ndarray, size: int = 8, high_frequency_factor: int = 4) -> int:
    dimension = size * high_frequency_factor
    gray = cv2.cvtColor(
        cv2.resize(frame, (dimension, dimension), interpolation=cv2.INTER_AREA),
        cv2.COLOR_BGR2GRAY,
    ).astype(np.float32)
    dct = cv2.dct(gray)
    low = dct[:size, :size]
    median = float(np.median(low[1:, :]))
    value = 0
    for bit in (low > median).flatten():
        value = (value << 1) | int(bit)
    return value


def hamming(left: int, right: int) -> int:
    return (left ^ right).bit_count()


def _hash_frame(frame: np.ndarray, method: str) -> int | None:
    if method == "none":
        return None
    if method == "dhash":
        return dhash(frame)
    if method == "phash":
        return phash(frame)
    if method == "embedding":
        raise NotImplementedError(
            "embedding dedup requires a visual adapter and is outside the TV1 + TV3 repository scope"
        )
    raise ValueError(f"Unsupported dedup method: {method}")


def _shot_anchor_candidates(shot: ShotRecord, settings) -> list[CandidateAnchor]:
    strategy = settings.keyframes.strategy
    start = shot.start_timestamp_ms
    end = shot.end_timestamp_ms
    duration = max(0, end - start)
    anchors: list[CandidateAnchor] = []

    if strategy == "uniform":
        cursor = start
        while cursor <= end:
            anchors.append(CandidateAnchor(cursor, "max_gap", shot.shot_id))
            cursor += int(settings.keyframes.max_gap_ms)
        return anchors

    policy = settings.keyframes.representative_policy
    if policy == "first":
        representative = start
    elif policy == "last":
        representative = end
    else:
        representative = (start + end) // 2
    anchors.append(CandidateAnchor(representative, "shot_representative", shot.shot_id))

    if strategy in {"shot_max_gap", "hybrid_shot_max_gap"} and duration > 0:
        segments = max(1, math.ceil(duration / int(settings.keyframes.max_gap_ms)))
        for position in range(1, segments):
            timestamp = start + int(round(position * duration / segments))
            anchors.append(CandidateAnchor(timestamp, "max_gap", shot.shot_id))

    if strategy == "hybrid_shot_max_gap" and duration > 2 * int(
        settings.keyframes.boundary_guard_ms
    ):
        guard = int(settings.keyframes.boundary_guard_ms)
        anchors.append(CandidateAnchor(start + guard, "boundary_guard", shot.shot_id))
        anchors.append(CandidateAnchor(end - guard, "boundary_guard", shot.shot_id))

    unique: dict[tuple[int, str], CandidateAnchor] = {}
    for anchor in anchors:
        unique[(anchor.timestamp_ms, anchor.reason)] = anchor
    return sorted(unique.values(), key=lambda item: (item.timestamp_ms, item.reason))


def _decode_best_candidate(
    resolver: FrameResolver,
    shot: ShotRecord,
    anchor: CandidateAnchor,
    settings,
) -> SelectedFrame | None:
    policy = settings.keyframes.representative_policy
    radius = int(settings.keyframes.representative_search_radius_ms)
    step = int(settings.keyframes.representative_candidate_step_ms)
    if policy != "quality_center" or anchor.reason == "boundary_guard":
        requested = [anchor.timestamp_ms]
    else:
        lower = max(shot.start_timestamp_ms, anchor.timestamp_ms - radius)
        upper = min(shot.end_timestamp_ms, anchor.timestamp_ms + radius)
        requested = list(range(lower, upper + 1, step))
        if anchor.timestamp_ms not in requested:
            requested.append(anchor.timestamp_ms)

    best: SelectedFrame | None = None
    best_score = float("-inf")
    seen_frames: set[int] = set()
    for timestamp_ms in sorted(set(requested)):
        try:
            decoded = resolver.resolve_timestamp_to_frame(timestamp_ms)
        except (ValueError, FrameIndexError):
            continue
        if decoded.record.frame_id in seen_frames:
            continue
        seen_frames.add(decoded.record.frame_id)
        if not (shot.start_frame_id <= decoded.record.frame_id <= shot.end_frame_id):
            continue
        metrics = quality_score(decoded.image_bgr, settings)
        center_penalty = 0.0
        if radius > 0:
            center_penalty = float(settings.keyframes.quality_center_bias) * (
                abs(decoded.record.timestamp_ms - anchor.timestamp_ms) / radius
            )
        score = metrics.composite - center_penalty
        if score > best_score:
            best_score = score
            best = SelectedFrame(
                record=decoded.record,
                frame=decoded.image_bgr,
                reason=anchor.reason,
                shot_id=shot.shot_id,
                quality=metrics,
            )
    return best


def _reason_priority(reason: SelectionReason) -> int:
    return {
        "manual": 5,
        "shot_representative": 4,
        "boundary_guard": 3,
        "max_gap": 2,
    }[reason]


def _deduplicate(selected: list[SelectedFrame], settings) -> list[SelectedFrame]:
    method = settings.keyframes.dedup_method
    if method == "none":
        return sorted(selected, key=lambda item: item.record.timestamp_ms)
    threshold = int(settings.keyframes.dedup_threshold)
    temporal_window = int(settings.keyframes.dedup_temporal_window_ms)
    output: list[SelectedFrame] = []
    for candidate in sorted(selected, key=lambda item: item.record.timestamp_ms):
        candidate.image_hash = _hash_frame(candidate.frame, method)
        duplicate_position: int | None = None
        for position in range(len(output) - 1, -1, -1):
            existing = output[position]
            delta = candidate.record.timestamp_ms - existing.record.timestamp_ms
            if delta > temporal_window:
                break
            if candidate.shot_id != existing.shot_id:
                continue
            if candidate.image_hash is not None and existing.image_hash is not None:
                if hamming(candidate.image_hash, existing.image_hash) <= threshold:
                    duplicate_position = position
                    break
        if duplicate_position is None:
            output.append(candidate)
            continue
        existing = output[duplicate_position]
        candidate_key = (_reason_priority(candidate.reason), candidate.quality.composite)
        existing_key = (_reason_priority(existing.reason), existing.quality.composite)
        if candidate_key > existing_key:
            output[duplicate_position] = candidate
    return sorted(output, key=lambda item: item.record.timestamp_ms)


def _enforce_max_gap(
    selected: list[SelectedFrame],
    shots: list[ShotRecord],
    resolver: FrameResolver,
    settings,
) -> list[SelectedFrame]:
    """Guarantee configured temporal coverage after deduplication.

    Coverage frames never replace the best shot representative.  If the nearest
    requested timestamp resolves to an already selected frame, the function
    selects the nearest unused original frame inside the gap instead of silently
    leaving the invariant broken.
    """

    if settings.keyframes.strategy not in {
        "shot_max_gap",
        "hybrid_shot_max_gap",
        "uniform",
    }:
        return selected
    max_gap = int(settings.keyframes.max_gap_ms)
    output = list(selected)
    for shot in shots:
        attempts = 0
        while True:
            timestamps = sorted(
                item.record.timestamp_ms for item in output if item.shot_id == shot.shot_id
            )
            points = [shot.start_timestamp_ms] + timestamps + [shot.end_timestamp_ms]
            gaps = [(right - left, left, right) for left, right in zip(points, points[1:])]
            largest, left, right = max(gaps, default=(0, 0, 0))
            if largest <= max_gap:
                break
            attempts += 1
            if attempts > resolver.index.frame_count:
                raise ShotDetectionError(
                    f"Could not enforce max_gap_ms={max_gap} for shot {shot.shot_id}"
                )
            target = min(right - 1, left + max_gap)
            used = {item.record.frame_id for item in output}
            candidates = [
                record
                for record in resolver.index.records
                if left < record.timestamp_ms < right and record.frame_id not in used
            ]
            if not candidates:
                raise ShotDetectionError(
                    f"No unused original frame can fill {largest} ms gap in {shot.shot_id}"
                )
            record = min(
                candidates,
                key=lambda item: (abs(item.timestamp_ms - target), item.frame_id),
            )
            decoded = resolver.get_frame_with_record(record.frame_id)
            metrics = quality_score(decoded.image_bgr, settings)
            output.append(
                SelectedFrame(
                    record=decoded.record,
                    frame=decoded.image_bgr,
                    reason="max_gap",
                    shot_id=shot.shot_id,
                    quality=metrics,
                )
            )
    return sorted(output, key=lambda item: item.record.timestamp_ms)


def _save_selected_frames(
    selected: list[SelectedFrame],
    media: MediaRecord,
    run_root: Path,
    settings,
) -> list[FrameRecord]:
    key_dir = run_root / "keyframes" / media.video_id
    thumb_dir = run_root / "thumbnails" / media.video_id
    key_dir.mkdir(parents=True, exist_ok=True)
    thumb_dir.mkdir(parents=True, exist_ok=True)
    rows: list[FrameRecord] = []
    for sequence, item in enumerate(sorted(selected, key=lambda row: row.record.timestamp_ms)):
        key_path = key_dir / f"{sequence:06d}.jpg"
        thumb_path = thumb_dir / f"{sequence:06d}.jpg"
        atomic_cv2_imwrite(key_path, item.frame)
        height, width = item.frame.shape[:2]
        thumb_width = int(settings.keyframes.thumbnail_width)
        thumb_height = max(1, int(height * thumb_width / width))
        atomic_cv2_imwrite(
            thumb_path,
            cv2.resize(item.frame, (thumb_width, thumb_height), interpolation=cv2.INTER_AREA),
        )
        rows.append(
            FrameRecord(
                preprocess_run_id=media.preprocess_run_id,
                video_id=media.video_id,
                frame_id=item.record.frame_id,
                keyframe_seq=sequence,
                timestamp_ms=item.record.timestamp_ms,
                pts=item.record.pts,
                time_base=item.record.time_base,
                decode_index=item.record.decode_index,
                shot_id=item.shot_id,
                keyframe_path=str(key_path),
                thumbnail_path=str(thumb_path),
                selection_reason=item.reason,
                sharpness_score=item.quality.sharpness,
                blur_score=item.quality.blur_score,
                quality_score=item.quality.composite,
                black_frame_ratio=item.quality.black_ratio,
                face_visibility_score=item.quality.face_visibility,
                text_visibility_score=item.quality.text_visibility,
                created_at_utc=utcnow_iso(),
            )
        )
    return rows


def extract_keyframes(
    media: MediaRecord,
    run_root: str | Path,
    settings,
) -> list[FrameRecord]:
    """Select quality-aware keyframes while preserving original frame IDs and timestamps."""
    root = Path(run_root)
    frame_index_path = ensure_original_frame_index(
        media,
        root,
        backend=settings.media.frame_index_backend,
        timeout=int(settings.media.frame_index_timeout_seconds),
    )
    resolver = FrameResolver(
        media,
        frame_index_path=frame_index_path,
        backend="auto",
        allow_ffmpeg_fallback=bool(settings.media.allow_ffmpeg_decode_fallback),
        cache_size=max(32, int(settings.keyframes.representative_candidate_cache_size)),
    )
    started = time.perf_counter()
    warnings: list[str] = []
    try:
        detector, detector_warnings = _select_shot_detector(settings)
        warnings.extend(detector_warnings)
        try:
            shots = detector.detect(media, resolver.index, resolver)
        except (AutoShotError, ShotDetectionError, RuntimeError) as exc:
            if settings.keyframes.shot_model != "autoshoot_or_fallback":
                raise
            warnings.append(f"Selected detector failed: {type(exc).__name__}: {exc}")
            try:
                fallback = PySceneDetectAdapter(
                    threshold=float(settings.keyframes.pyscenedetect_threshold),
                    min_scene_len_frames=int(
                        settings.keyframes.pyscenedetect_min_scene_len_frames
                    ),
                )
                shots = fallback.detect(media, resolver.index, resolver)
                detector = fallback
            except ShotDetectionError as scene_error:
                warnings.append(f"PySceneDetect failed: {scene_error}")
                detector = HistogramShotDetector(
                    int(settings.keyframes.sample_every_ms),
                    float(settings.keyframes.shot_threshold),
                    int(settings.keyframes.min_shot_ms),
                )
                shots = detector.detect(media, resolver.index, resolver)

        anchors: list[CandidateAnchor] = []
        for shot in shots:
            anchors.extend(_shot_anchor_candidates(shot, settings))
        selected: list[SelectedFrame] = []
        shots_by_id = {shot.shot_id: shot for shot in shots}
        for anchor in anchors:
            candidate = _decode_best_candidate(
                resolver,
                shots_by_id[anchor.shot_id],
                anchor,
                settings,
            )
            if candidate is not None:
                selected.append(candidate)
        selected = _deduplicate(selected, settings)
        selected = _enforce_max_gap(selected, shots, resolver, settings)
        rows = _save_selected_frames(selected, media, root, settings)
    finally:
        resolver.close()

    mapping_dir = root / "mappings"
    mapping_dir.mkdir(parents=True, exist_ok=True)
    frame_payload = [row.model_dump(mode="json") for row in rows]
    write_jsonl(mapping_dir / f"{media.video_id}.jsonl", frame_payload)
    write_parquet_optional(mapping_dir / f"{media.video_id}.parquet", frame_payload)

    shots_dir = root / "shots"
    shots_dir.mkdir(parents=True, exist_ok=True)
    shot_payload = [shot.model_dump(mode="json") for shot in shots]
    write_jsonl(shots_dir / f"{media.video_id}.jsonl", shot_payload)
    write_parquet_optional(shots_dir / f"{media.video_id}.parquet", shot_payload)

    report = {
        "schema_version": "1.0.0",
        "video_id": media.video_id,
        "preprocess_run_id": media.preprocess_run_id,
        "strategy": settings.keyframes.strategy,
        "configured_shot_model": settings.keyframes.shot_model,
        "detector_name": shots[0].detector_name if shots else None,
        "detector_version": shots[0].detector_version if shots else None,
        "shot_count": len(shots),
        "candidate_anchor_count": len(anchors),
        "keyframe_count": len(rows),
        "selection_reason_counts": {
            reason: sum(1 for row in rows if row.selection_reason == reason)
            for reason in ["shot_representative", "max_gap", "boundary_guard", "manual"]
        },
        "runtime_seconds": round(time.perf_counter() - started, 6),
        "warnings": warnings,
        "keyframe_config_sha256": stable_json_hash(
            settings.keyframes.model_dump(mode="json")
        ),
        "created_at_utc": utcnow_iso(),
    }
    write_json(root / "reports" / "keyframes" / f"{media.video_id}.json", report)
    return rows


def benchmark_keyframe_strategies(media: MediaRecord, run_root: str | Path, settings) -> dict:
    """Runtime-only ablation; quality metrics are added only after reviewed GT exists."""

    root = Path(run_root)
    strategies = ["uniform", "shot_only", "shot_max_gap", "hybrid_shot_max_gap"]
    results: list[dict] = []
    for strategy in strategies:
        benchmark_settings = settings.model_copy(deep=True)
        benchmark_settings.keyframes.strategy = strategy
        output_root = root / "benchmarks" / "keyframes" / strategy
        started = time.perf_counter()
        rows = extract_keyframes(media.model_copy(deep=True), output_root, benchmark_settings)
        storage_bytes = sum(
            Path(row.keyframe_path).stat().st_size + Path(row.thumbnail_path).stat().st_size
            for row in rows
            if row.thumbnail_path
        )
        results.append(
            {
                "strategy": strategy,
                "keyframe_count": len(rows),
                "storage_bytes": storage_bytes,
                "runtime_seconds": round(time.perf_counter() - started, 6),
                "quality_status": "PENDING_GROUND_TRUTH",
            }
        )
    report = {
        "schema_version": "1.0.0",
        "video_id": media.video_id,
        "preprocess_run_id": media.preprocess_run_id,
        "metric_scope": "runtime_only",
        "results": results,
        "created_at_utc": utcnow_iso(),
    }
    write_json(root / "reports" / "keyframe_ablation_runtime.json", report)
    return report
