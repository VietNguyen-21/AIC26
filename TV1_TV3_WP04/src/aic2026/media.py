"""Media probing, audio extraction, decode checks, and exact original-frame access."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from collections import OrderedDict
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Iterable, Literal

import numpy as np

from .contracts import AudioRecord, CorpusManifestRecord, MediaRecord, OriginalFrameIndexRecord
from .frame_index import (
    FrameIndexError,
    OriginalFrameIndex,
    ResolvedOriginalFrame,
    build_original_frame_index,
)
from .utils import parse_fraction, sha256_file, utcnow_iso, write_jsonl, write_parquet_optional

DecodeBackend = Literal["pyav", "ffmpeg", "auto"]


@dataclass(frozen=True)
class DecodedOriginalFrame:
    record: OriginalFrameIndexRecord
    image_bgr: np.ndarray
    requested_timestamp_ms: int | None = None
    absolute_error_ms: int | None = None


def ffprobe(path: str | Path, timeout: int = 120) -> dict:
    command = [
        "ffprobe",
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]
    result = subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return json.loads(result.stdout)


def probe_media(record: CorpusManifestRecord, run_id: str, timeout: int = 120) -> MediaRecord:
    data = ffprobe(record.original_video_path, timeout)
    video = next(
        (stream for stream in data.get("streams", []) if stream.get("codec_type") == "video"),
        None,
    )
    if not video:
        raise ValueError(f"No video stream: {record.original_video_path}")
    audio = next(
        (stream for stream in data.get("streams", []) if stream.get("codec_type") == "audio"),
        None,
    )
    duration = video.get("duration") or data.get("format", {}).get("duration") or 0
    fps_nominal = parse_fraction(video.get("r_frame_rate"))
    fps_average = parse_fraction(video.get("avg_frame_rate"))
    vfr = None if fps_nominal is None or fps_average is None else abs(fps_nominal - fps_average) > 0.01
    frame_count = video.get("nb_frames")
    return MediaRecord(
        preprocess_run_id=run_id,
        video_id=record.video_id,
        original_video_path=record.original_video_path,
        source_sha256=record.source_sha256,
        time_base=video.get("time_base"),
        fps_nominal=fps_nominal,
        fps_average=fps_average,
        is_variable_frame_rate=vfr,
        frame_count=int(frame_count) if frame_count and str(frame_count).isdigit() else None,
        duration_ms=int(float(duration) * 1000),
        width_px=int(video.get("width", 0)),
        height_px=int(video.get("height", 0)),
        codec=video.get("codec_name"),
        has_audio=audio is not None,
        created_at_utc=utcnow_iso(),
    )


def infer_variable_frame_rate(records: list[OriginalFrameIndexRecord], tolerance_ms: float = 1.5) -> bool:
    """Infer VFR from presentation-timestamp deltas rather than nominal FPS fields."""

    if len(records) < 3:
        return False
    deltas = [
        current.timestamp_ms - previous.timestamp_ms
        for previous, current in zip(records, records[1:])
        if current.timestamp_ms > previous.timestamp_ms
    ]
    if len(deltas) < 2:
        return False
    median = float(np.median(np.asarray(deltas, dtype=np.float64)))
    return any(abs(delta - median) > tolerance_ms for delta in deltas)


def decode_probe(
    record: MediaRecord,
    points: int = 5,
    frame_index_path: str | Path | None = None,
    backend: DecodeBackend = "auto",
    allow_ffmpeg_fallback: bool = False,
) -> list[dict]:
    resolver = FrameResolver(
        record,
        frame_index_path=frame_index_path,
        backend=backend,
        allow_ffmpeg_fallback=allow_ffmpeg_fallback,
    )
    results: list[dict] = []
    try:
        for i in range(points):
            timestamp = int(record.duration_ms * (i + 1) / (points + 1))
            decoded = resolver.resolve_timestamp_to_frame(timestamp)
            results.append(
                {
                    "requested_timestamp_ms": timestamp,
                    "frame_id": decoded.record.frame_id,
                    "decode_index": decoded.record.decode_index,
                    "pts": decoded.record.pts,
                    "time_base": decoded.record.time_base,
                    "timestamp_ms": decoded.record.timestamp_ms,
                    "absolute_error_ms": decoded.absolute_error_ms,
                    "decoded": True,
                    "shape": list(decoded.image_bgr.shape),
                    "backend": resolver.backend,
                }
            )
    finally:
        resolver.close()
    return results


def _probe_audio_artifact(path: Path, timeout: int = 120) -> tuple[int, int, int]:
    payload = ffprobe(path, timeout=timeout)
    stream = next(
        (row for row in payload.get("streams", []) if row.get("codec_type") == "audio"),
        None,
    )
    if stream is None:
        raise RuntimeError(f"Extracted WAV has no audio stream: {path}")
    sample_rate = int(stream.get("sample_rate") or 0)
    channels = int(stream.get("channels") or 0)
    duration_value = stream.get("duration") or payload.get("format", {}).get("duration")
    duration_ms = int(round(float(duration_value or 0.0) * 1000.0))
    if sample_rate <= 0 or channels <= 0 or duration_ms <= 0:
        raise RuntimeError(f"Invalid extracted WAV metadata: {path}")
    return sample_rate, channels, duration_ms


def extract_audio(
    record: MediaRecord,
    output_dir: str | Path,
    sample_rate: int = 16000,
) -> AudioRecord:
    """Extract PCM WAV atomically and verify the produced artifact with FFprobe."""

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    if not record.has_audio:
        return AudioRecord(
            preprocess_run_id=record.preprocess_run_id,
            video_id=record.video_id,
            status="no_audio",
            created_at_utc=utcnow_iso(),
        )

    target = output_dir / f"{record.video_id}.wav"
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{record.video_id}.", suffix=".wav", dir=output_dir
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    command = [
        "ffmpeg",
        "-y",
        "-v",
        "error",
        "-i",
        record.original_video_path,
        "-vn",
        "-ac",
        "1",
        "-ar",
        str(sample_rate),
        "-c:a",
        "pcm_s16le",
        str(temporary),
    ]
    try:
        timeout = max(120, int(record.duration_ms / 1000) * 3 + 60)
        subprocess.run(command, check=True, timeout=timeout)
        actual_rate, channels, duration_ms = _probe_audio_artifact(temporary)
        if actual_rate != sample_rate or channels != 1:
            raise RuntimeError(
                f"Unexpected WAV format rate={actual_rate} channels={channels}"
            )
        os.replace(temporary, target)
        return AudioRecord(
            preprocess_run_id=record.preprocess_run_id,
            video_id=record.video_id,
            audio_path=str(target),
            audio_sha256=sha256_file(target),
            sample_rate_hz=actual_rate,
            channels=channels,
            duration_ms=duration_ms,
            status="ready",
            created_at_utc=utcnow_iso(),
        )
    except Exception:
        temporary.unlink(missing_ok=True)
        target.unlink(missing_ok=True)
        return AudioRecord(
            preprocess_run_id=record.preprocess_run_id,
            video_id=record.video_id,
            status="failed",
            created_at_utc=utcnow_iso(),
        )


def write_media_records(
    run_root: str | Path,
    media: Iterable[MediaRecord],
    audio: Iterable[AudioRecord],
):
    root = Path(run_root) / "media"
    media_rows = [x.model_dump(mode="json") for x in media]
    audio_rows = [x.model_dump(mode="json") for x in audio]
    write_jsonl(root / "media.jsonl", media_rows)
    write_jsonl(root / "audio.jsonl", audio_rows)
    write_parquet_optional(root / "media.parquet", media_rows)
    write_parquet_optional(root / "audio.parquet", audio_rows)


class FrameResolver:
    """Resolve and decode frames on the original PTS timeline.

    PyAV is the production backend. The FFmpeg backend is an explicit degraded
    fallback for diagnostics and CI environments where the PyAV wheel is not
    available. OpenCV seeking is deliberately not used.
    """

    def __init__(
        self,
        media: MediaRecord,
        frame_index_path: str | Path | None = None,
        index: OriginalFrameIndex | None = None,
        backend: DecodeBackend = "auto",
        allow_ffmpeg_fallback: bool = False,
        cache_size: int = 32,
    ):
        self.media = media
        resolved_index_path = frame_index_path or media.original_frame_index_path
        if index is None:
            if not resolved_index_path:
                raise FrameIndexError(
                    f"No original-frame index configured for video {media.video_id}. "
                    "Build it before decoding frames."
                )
            index = OriginalFrameIndex.from_jsonl(resolved_index_path)
        self.index = index
        self.cache_size = max(1, int(cache_size))
        self._cache: OrderedDict[int, np.ndarray] = OrderedDict()
        self._container = None
        self._stream = None

        selected_backend = backend
        if backend == "auto":
            try:
                import av  # type: ignore  # noqa: F401

                selected_backend = "pyav"
            except ImportError:
                if not allow_ffmpeg_fallback:
                    raise FrameIndexError(
                        "PyAV is unavailable and FFmpeg fallback is disabled. Install 'av' "
                        "or explicitly enable the degraded fallback."
                    )
                selected_backend = "ffmpeg"
        if selected_backend == "ffmpeg" and not allow_ffmpeg_fallback:
            raise FrameIndexError(
                "FFmpeg frame decode is a degraded fallback and must be explicitly enabled"
            )
        self.backend = selected_backend

    def __enter__(self) -> "FrameResolver":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()

    def close(self) -> None:
        if self._container is not None:
            self._container.close()
        self._container = None
        self._stream = None
        self._cache.clear()

    def _cache_get(self, frame_id: int) -> np.ndarray | None:
        image = self._cache.get(frame_id)
        if image is not None:
            self._cache.move_to_end(frame_id)
            return image.copy()
        return None

    def _cache_put(self, frame_id: int, image: np.ndarray) -> None:
        self._cache[frame_id] = image.copy()
        self._cache.move_to_end(frame_id)
        while len(self._cache) > self.cache_size:
            self._cache.popitem(last=False)

    def _open_pyav(self):
        if self._container is None:
            try:
                import av  # type: ignore
            except ImportError as exc:  # pragma: no cover - depends on optional runtime
                raise FrameIndexError("PyAV backend selected but package 'av' is unavailable") from exc
            self._container = av.open(self.media.original_video_path, mode="r")
            if not self._container.streams.video:
                raise FrameIndexError(f"No video stream: {self.media.original_video_path}")
            self._stream = self._container.streams.video[0]
        return self._container, self._stream

    def _decode_pyav(self, target: OriginalFrameIndexRecord) -> np.ndarray:
        container, stream = self._open_pyav()
        target_pts = target.pts
        if target_pts is None:
            container.close()
            self._container = None
            self._stream = None
            container, stream = self._open_pyav()
            for decode_index, frame in enumerate(container.decode(stream)):
                if decode_index == target.decode_index:
                    return frame.to_ndarray(format="bgr24")
            raise FrameIndexError(f"Could not decode original frame {target.frame_id}")

        try:
            container.seek(max(0, int(target_pts)), stream=stream, backward=True, any_frame=False)
            for frame in container.decode(stream):
                pts = getattr(frame, "pts", None)
                if pts == target_pts:
                    return frame.to_ndarray(format="bgr24")
                if pts is not None and pts > target_pts:
                    break
        except Exception:
            # Reopen and use a deterministic sequential fallback within PyAV.
            pass

        container.close()
        self._container = None
        self._stream = None
        container, stream = self._open_pyav()
        for decode_index, frame in enumerate(container.decode(stream)):
            if decode_index == target.decode_index:
                return frame.to_ndarray(format="bgr24")
        raise FrameIndexError(f"Could not decode original frame {target.frame_id}")

    def _decode_ffmpeg(self, target: OriginalFrameIndexRecord) -> np.ndarray:
        if shutil.which("ffmpeg") is None:
            raise FrameIndexError("ffmpeg is unavailable")
        command = [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            self.media.original_video_path,
            "-vf",
            f"select=eq(n\\,{target.decode_index})",
            "-frames:v",
            "1",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "bgr24",
            "pipe:1",
        ]
        completed = subprocess.run(
            command,
            check=True,
            capture_output=True,
            timeout=max(120, self.media.duration_ms // 1000 * 2),
        )
        expected = self.media.width_px * self.media.height_px * 3
        if len(completed.stdout) != expected:
            raise FrameIndexError(
                f"FFmpeg decoded {len(completed.stdout)} bytes for frame {target.frame_id}; "
                f"expected {expected}"
            )
        return np.frombuffer(completed.stdout, dtype=np.uint8).reshape(
            (self.media.height_px, self.media.width_px, 3)
        )

    def _decode_record(self, record: OriginalFrameIndexRecord) -> np.ndarray:
        cached = self._cache_get(record.frame_id)
        if cached is not None:
            return cached
        if self.backend == "pyav":
            image = self._decode_pyav(record)
        elif self.backend == "ffmpeg":
            image = self._decode_ffmpeg(record)
        else:  # pragma: no cover
            raise FrameIndexError(f"Unsupported decode backend: {self.backend}")
        self._cache_put(record.frame_id, image)
        return image.copy()

    def resolve_frame_to_timestamp(self, frame_id: int) -> OriginalFrameIndexRecord:
        return self.index.get(frame_id)

    def resolve_timestamp_record(
        self,
        timestamp_ms: int,
        mode: Literal["nearest", "before", "after"] = "nearest",
    ) -> ResolvedOriginalFrame:
        return self.index.resolve_timestamp(timestamp_ms, mode=mode)

    def resolve_timestamp_to_frame(
        self,
        timestamp_ms: int,
        mode: Literal["nearest", "before", "after"] = "nearest",
    ) -> DecodedOriginalFrame:
        resolved = self.resolve_timestamp_record(timestamp_ms, mode=mode)
        image = self._decode_record(resolved.record)
        return DecodedOriginalFrame(
            record=resolved.record,
            image_bgr=image,
            requested_timestamp_ms=timestamp_ms,
            absolute_error_ms=resolved.absolute_error_ms,
        )

    def get_frame_with_record(self, frame_id: int) -> DecodedOriginalFrame:
        record = self.index.get(frame_id)
        return DecodedOriginalFrame(record=record, image_bgr=self._decode_record(record))

    def get_frame_at_time(
        self,
        timestamp_ms: int,
        mode: Literal["nearest", "before", "after"] = "nearest",
    ):
        decoded = self.resolve_timestamp_to_frame(timestamp_ms, mode=mode)
        return decoded.record.frame_id, decoded.record.timestamp_ms, decoded.image_bgr

    def get_frame(self, frame_id: int):
        decoded = self.get_frame_with_record(frame_id)
        return decoded.record.frame_id, decoded.record.timestamp_ms, decoded.image_bgr

    def iter_window(
        self,
        start_ms: int,
        end_ms: int,
        step_ms: int,
    ) -> list[DecodedOriginalFrame]:
        output: list[DecodedOriginalFrame] = []
        for resolved in self.index.iter_window(start_ms, end_ms, step_ms):
            output.append(
                DecodedOriginalFrame(
                    record=resolved.record,
                    image_bgr=self._decode_record(resolved.record),
                    requested_timestamp_ms=resolved.requested_timestamp_ms,
                    absolute_error_ms=resolved.absolute_error_ms,
                )
            )
        return output


def ensure_original_frame_index(
    media: MediaRecord,
    run_root: str | Path,
    backend: Literal["pyav", "ffprobe", "auto"] = "pyav",
    timeout: int = 3600,
):
    existing = media.original_frame_index_path
    if existing and Path(existing).exists():
        return Path(existing)
    artifact = build_original_frame_index(media, run_root, backend=backend, timeout=timeout)
    media.original_frame_index_path = str(artifact.jsonl_path)
    media.frame_index_backend = artifact.backend
    media.frame_count = artifact.frame_count
    media.time_base = artifact.time_base
    return artifact.jsonl_path
