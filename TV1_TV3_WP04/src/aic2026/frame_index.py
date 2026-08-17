"""PTS/time-base original-frame indexing and deterministic timestamp-to-frame resolution."""

from __future__ import annotations

import bisect
import json
import shutil
import subprocess
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Iterable, Literal, Sequence

from .contracts import MediaRecord, OriginalFrameIndexRecord
from .utils import (
    read_jsonl,
    stable_json_hash,
    utcnow_iso,
    write_json,
    write_jsonl,
    write_parquet_optional,
)

# The original-frame index is the only authority for submission frame IDs.
FrameIndexBackend = Literal["pyav", "ffprobe", "auto"]
ResolutionMode = Literal["nearest", "before", "after"]


class FrameIndexError(RuntimeError):
    """Raised when the original-frame timeline is invalid or cannot be built."""


@dataclass(frozen=True)
class FrameIndexArtifact:
    video_id: str
    backend: str
    jsonl_path: Path
    parquet_path: Path
    manifest_path: Path
    frame_count: int
    first_timestamp_ms: int
    last_timestamp_ms: int
    time_base: str


@dataclass(frozen=True)
class ResolvedOriginalFrame:
    requested_timestamp_ms: int | None
    record: OriginalFrameIndexRecord
    absolute_error_ms: int | None


def _fraction_text(value: object | None, default: str = "1/1000") -> str:
    if value is None:
        return default
    numerator = getattr(value, "numerator", None)
    denominator = getattr(value, "denominator", None)
    if numerator is not None and denominator:
        return f"{int(numerator)}/{int(denominator)}"
    text = str(value)
    if "/" in text:
        return text
    return default


def _timestamp_ms(pts: int | None, time_base: object | None, frame_time: float | None) -> int:
    # Prefer integer PTS and stream time-base; FPS arithmetic is intentionally excluded.
    if pts is not None and time_base is not None:
        return int(round(float(pts * time_base) * 1000.0))
    if frame_time is not None:
        return int(round(float(frame_time) * 1000.0))
    raise FrameIndexError("Decoded frame has neither PTS/time-base nor frame.time")


def _validate_records(records: Sequence[OriginalFrameIndexRecord]) -> None:
    if not records:
        raise FrameIndexError("Original-frame index is empty")
    expected_video = records[0].video_id
    previous_timestamp = -1
    seen_frame_ids: set[int] = set()
    seen_decode_indices: set[int] = set()
    for position, record in enumerate(records):
        if record.video_id != expected_video:
            raise FrameIndexError("Original-frame index mixes multiple video IDs")
        if record.frame_id in seen_frame_ids:
            raise FrameIndexError(f"Duplicate original frame_id: {record.frame_id}")
        if record.decode_index in seen_decode_indices:
            raise FrameIndexError(f"Duplicate decode_index: {record.decode_index}")
        if record.frame_id != position or record.decode_index != position:
            raise FrameIndexError(
                "Original frame IDs must be zero-based contiguous decode order; "
                f"expected {position}, got frame_id={record.frame_id}, "
                f"decode_index={record.decode_index}"
            )
        if record.timestamp_ms < previous_timestamp:
            raise FrameIndexError(
                "Original-frame timestamps are not monotonic: "
                f"{record.timestamp_ms} < {previous_timestamp} at frame {record.frame_id}"
            )
        previous_timestamp = record.timestamp_ms
        seen_frame_ids.add(record.frame_id)
        seen_decode_indices.add(record.decode_index)


def pyav_available() -> bool:
    try:
        import av  # type: ignore  # noqa: F401
    except ImportError:
        return False
    return True


def _normalised_records(
    *,
    media: MediaRecord,
    time_base_text: str,
    raw_rows: list[dict],
) -> list[OriginalFrameIndexRecord]:
    if not raw_rows:
        raise FrameIndexError("Original-frame index is empty")
    origin_ms = int(raw_rows[0]["raw_timestamp_ms"])
    records: list[OriginalFrameIndexRecord] = []
    for decode_index, row in enumerate(raw_rows):
        raw_timestamp_ms = int(row["raw_timestamp_ms"])
        timestamp_ms = raw_timestamp_ms - origin_ms
        if timestamp_ms < 0:
            # A decoder should emit presentation order.  A negative normalized
            # value indicates an invalid/reordered timeline and must not be
            # silently clamped because that creates duplicate timestamps.
            raise FrameIndexError(
                f"Frame {decode_index} precedes the timeline origin: "
                f"raw={raw_timestamp_ms} origin={origin_ms}"
            )
        records.append(
            OriginalFrameIndexRecord(
                preprocess_run_id=media.preprocess_run_id,
                video_id=media.video_id,
                frame_id=decode_index,
                decode_index=decode_index,
                pts=row.get("pts"),
                dts=row.get("dts"),
                time_base=time_base_text,
                raw_timestamp_ms=raw_timestamp_ms,
                timeline_origin_ms=origin_ms,
                timestamp_ms=timestamp_ms,
                is_technical_keyframe=row.get("is_technical_keyframe"),
                created_at_utc=utcnow_iso(),
            )
        )
    _validate_records(records)
    return records


def _build_with_pyav(media: MediaRecord) -> list[OriginalFrameIndexRecord]:
    try:
        import av  # type: ignore
    except ImportError as exc:
        raise FrameIndexError(
            "PyAV is required for frame_index_backend='pyav'. Install the 'av' package "
            "or use the explicitly degraded ffprobe backend for diagnostics/tests."
        ) from exc

    raw_rows: list[dict] = []
    with av.open(media.original_video_path, mode="r") as container:
        if not container.streams.video:
            raise FrameIndexError(f"No video stream: {media.original_video_path}")
        stream = container.streams.video[0]
        time_base = stream.time_base
        time_base_text = _fraction_text(time_base, media.time_base or "1/1000")
        for frame in container.decode(stream):
            pts = getattr(frame, "pts", None)
            dts = getattr(frame, "dts", None)
            raw_rows.append(
                {
                    "pts": int(pts) if pts is not None else None,
                    "dts": int(dts) if dts is not None else None,
                    "raw_timestamp_ms": _timestamp_ms(
                        pts, time_base, getattr(frame, "time", None)
                    ),
                    "is_technical_keyframe": bool(getattr(frame, "key_frame", False)),
                }
            )
    return _normalised_records(
        media=media, time_base_text=time_base_text, raw_rows=raw_rows
    )


def _first_present(row: dict, *keys: str):
    for key in keys:
        value = row.get(key)
        if value not in (None, "N/A", ""):
            return value
    return None


def _build_with_ffprobe(media: MediaRecord, timeout: int = 3600) -> list[OriginalFrameIndexRecord]:
    """Build a PTS-based index without OpenCV.

    This backend exists as an explicit degraded diagnostic/test path when PyAV is
    unavailable. Production profiles should use PyAV because it shares the same
    decoder semantics used to fetch frames.
    """

    if shutil.which("ffprobe") is None:
        raise FrameIndexError("ffprobe is unavailable")
    command = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_frames",
        "-show_entries",
        (
            "frame=pts,pts_time,pkt_dts,pkt_dts_time,best_effort_timestamp,"
            "best_effort_timestamp_time,key_frame"
        ),
        "-of",
        "json",
        media.original_video_path,
    ]
    completed = subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    payload = json.loads(completed.stdout)
    frames = payload.get("frames", [])
    time_base_text = media.time_base or "1/1000"
    time_base = Fraction(time_base_text)
    raw_rows: list[dict] = []
    for row in frames:
        pts_raw = _first_present(row, "best_effort_timestamp", "pts")
        dts_raw = _first_present(row, "pkt_dts")
        time_raw = _first_present(
            row,
            "best_effort_timestamp_time",
            "pts_time",
            "pkt_dts_time",
        )
        pts = int(pts_raw) if pts_raw is not None else None
        dts = int(dts_raw) if dts_raw is not None else None
        frame_time = float(time_raw) if time_raw is not None else None
        raw_rows.append(
            {
                "pts": pts,
                "dts": dts,
                "raw_timestamp_ms": _timestamp_ms(pts, time_base, frame_time),
                "is_technical_keyframe": bool(int(row.get("key_frame", 0))),
            }
        )
    return _normalised_records(
        media=media, time_base_text=time_base_text, raw_rows=raw_rows
    )


def build_original_frame_index(
    media: MediaRecord,
    run_root: str | Path,
    backend: FrameIndexBackend = "pyav",
    timeout: int = 3600,
) -> FrameIndexArtifact:
    """Decode or probe every original frame and persist the PTS-based source-of-truth timeline."""
    selected_backend = backend
    if backend == "auto":
        selected_backend = "pyav" if pyav_available() else "ffprobe"
    if selected_backend == "pyav":
        records = _build_with_pyav(media)
    elif selected_backend == "ffprobe":
        records = _build_with_ffprobe(media, timeout=timeout)
    else:  # pragma: no cover - protected by typed config
        raise FrameIndexError(f"Unsupported frame-index backend: {selected_backend}")

    root = Path(run_root) / "frame_indexes"
    root.mkdir(parents=True, exist_ok=True)
    jsonl_path = root / f"{media.video_id}.jsonl"
    parquet_path = root / f"{media.video_id}.parquet"
    manifest_path = root / f"{media.video_id}.manifest.json"
    rows = [record.model_dump(mode="json") for record in records]
    write_jsonl(jsonl_path, rows)
    parquet_written = write_parquet_optional(parquet_path, rows)
    manifest = {
        "schema_version": "1.1.0",
        "preprocess_run_id": media.preprocess_run_id,
        "video_id": media.video_id,
        "source_sha256": media.source_sha256,
        "backend": selected_backend,
        "frame_count": len(records),
        "first_timestamp_ms": records[0].timestamp_ms,
        "last_timestamp_ms": records[-1].timestamp_ms,
        "time_base": records[0].time_base,
        "timeline_origin_ms": records[0].timeline_origin_ms,
        "records_sha256": stable_json_hash(rows),
        "jsonl_path": str(jsonl_path),
        "parquet_path": str(parquet_path) if parquet_written else None,
        "created_at_utc": utcnow_iso(),
    }
    write_json(manifest_path, manifest)
    return FrameIndexArtifact(
        video_id=media.video_id,
        backend=str(selected_backend),
        jsonl_path=jsonl_path,
        parquet_path=parquet_path,
        manifest_path=manifest_path,
        frame_count=len(records),
        first_timestamp_ms=records[0].timestamp_ms,
        last_timestamp_ms=records[-1].timestamp_ms,
        time_base=records[0].time_base,
    )


def load_original_frame_index(path: str | Path) -> list[OriginalFrameIndexRecord]:
    records = [OriginalFrameIndexRecord.model_validate(row) for row in read_jsonl(path)]
    _validate_records(records)
    return records


class OriginalFrameIndex:
    """Read-only timestamp resolver backed by the persistent original-frame index."""
    def __init__(self, records: Iterable[OriginalFrameIndexRecord]):
        self.records = list(records)
        _validate_records(self.records)
        self._timestamps = [record.timestamp_ms for record in self.records]

    @classmethod
    def from_jsonl(cls, path: str | Path) -> "OriginalFrameIndex":
        return cls(load_original_frame_index(path))

    @property
    def frame_count(self) -> int:
        return len(self.records)

    def get(self, frame_id: int) -> OriginalFrameIndexRecord:
        if frame_id < 0 or frame_id >= len(self.records):
            raise FrameIndexError(
                f"frame_id {frame_id} is outside [0, {len(self.records) - 1}]"
            )
        record = self.records[frame_id]
        if record.frame_id != frame_id:
            raise FrameIndexError("Frame index is not contiguous")
        return record

    def resolve_timestamp(
        self,
        timestamp_ms: int,
        mode: ResolutionMode = "nearest",
    ) -> ResolvedOriginalFrame:
        if timestamp_ms < 0:
            timestamp_ms = 0
        position = bisect.bisect_left(self._timestamps, timestamp_ms)
        if mode == "before":
            index = max(0, position - 1 if position == len(self._timestamps) or self._timestamps[position] > timestamp_ms else position)
        elif mode == "after":
            index = min(len(self.records) - 1, position)
        elif mode == "nearest":
            if position <= 0:
                index = 0
            elif position >= len(self.records):
                index = len(self.records) - 1
            else:
                before = position - 1
                after = position
                before_error = abs(self._timestamps[before] - timestamp_ms)
                after_error = abs(self._timestamps[after] - timestamp_ms)
                index = before if before_error <= after_error else after
        else:  # pragma: no cover - typed callers should prevent this
            raise FrameIndexError(f"Unknown resolution mode: {mode}")
        record = self.records[index]
        return ResolvedOriginalFrame(
            requested_timestamp_ms=timestamp_ms,
            record=record,
            absolute_error_ms=abs(record.timestamp_ms - timestamp_ms),
        )

    def iter_window(
        self,
        start_ms: int,
        end_ms: int,
        step_ms: int,
        mode: ResolutionMode = "nearest",
    ) -> list[ResolvedOriginalFrame]:
        if end_ms < start_ms:
            raise FrameIndexError("end_ms must be >= start_ms")
        if step_ms <= 0:
            raise FrameIndexError("step_ms must be positive")
        output: list[ResolvedOriginalFrame] = []
        seen: set[int] = set()
        cursor = max(0, start_ms)
        while cursor <= end_ms:
            resolved = self.resolve_timestamp(cursor, mode=mode)
            if resolved.record.frame_id not in seen:
                output.append(resolved)
                seen.add(resolved.record.frame_id)
            cursor += step_ms
        if not output:
            output.append(self.resolve_timestamp(start_ms, mode=mode))
        return output
