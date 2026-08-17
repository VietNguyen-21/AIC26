"""Persistent temporal registry linking frames, shots, ASR intervals, and search windows."""

from __future__ import annotations

import bisect
from pathlib import Path
from typing import Iterable, Literal, Sequence

from .contracts import (
    ASRSegment,
    FrameRecord,
    MediaRecord,
    SearchCandidate,
    ShotRecord,
    TemporalASRLinkRecord,
    TemporalFrameRecord,
    TemporalWindowRecord,
)
from .utils import (
    read_json,
    read_jsonl,
    stable_json_hash,
    utcnow_iso,
    write_json,
    write_jsonl,
    write_parquet_optional,
)

TemporalResolutionMode = Literal["nearest", "before", "after"]


class TemporalRegistryError(ValueError):
    """Raised when the persistent temporal registry is inconsistent."""


def _load_shots(run_root: Path) -> list[ShotRecord]:
    rows: list[ShotRecord] = []
    for path in sorted((run_root / "shots").glob("*.jsonl")):
        rows.extend(ShotRecord.model_validate(row) for row in read_jsonl(path))
    return rows


def _load_media(run_root: Path) -> list[MediaRecord]:
    return [
        MediaRecord.model_validate(row)
        for row in read_jsonl(run_root / "media" / "media.jsonl")
    ]


def _load_asr(run_root: Path) -> list[ASRSegment]:
    return [
        ASRSegment.model_validate(row)
        for row in read_jsonl(run_root / "asr" / "asr.jsonl")
    ]


def _group_by_video(items: Iterable, *, attribute: str = "video_id") -> dict[str, list]:
    grouped: dict[str, list] = {}
    for item in items:
        grouped.setdefault(str(getattr(item, attribute)), []).append(item)
    return grouped


def _validate_keyframes(video_id: str, frames: Sequence[FrameRecord]) -> None:
    frame_ids: set[int] = set()
    last_timestamp: int | None = None
    last_frame_id: int | None = None
    run_ids: set[str] = set()
    for frame in frames:
        run_ids.add(frame.preprocess_run_id)
        if frame.frame_id in frame_ids:
            raise TemporalRegistryError(
                f"Duplicate keyframe frame_id={frame.frame_id} for video {video_id}"
            )
        frame_ids.add(frame.frame_id)
        if last_timestamp is not None and frame.timestamp_ms < last_timestamp:
            raise TemporalRegistryError(
                f"Non-monotonic timestamp for video {video_id}: "
                f"{frame.timestamp_ms} < {last_timestamp}"
            )
        if (
            last_timestamp is not None
            and frame.timestamp_ms == last_timestamp
            and last_frame_id is not None
            and frame.frame_id <= last_frame_id
        ):
            raise TemporalRegistryError(
                f"Temporal tie must keep increasing original frame IDs for video {video_id}"
            )
        last_timestamp = frame.timestamp_ms
        last_frame_id = frame.frame_id
    if len(run_ids) > 1:
        raise TemporalRegistryError(
            f"Temporal frames for video {video_id} span multiple preprocessing runs"
        )


def _shot_for_timestamp(
    shots: Sequence[ShotRecord], timestamp_ms: int, shot_id: str | None = None
) -> ShotRecord | None:
    if shot_id is not None:
        for shot in shots:
            if shot.shot_id == shot_id:
                return shot
    if not shots:
        return None
    starts = [shot.start_timestamp_ms for shot in shots]
    position = bisect.bisect_right(starts, timestamp_ms) - 1
    if position < 0:
        return None
    shot = shots[position]
    return shot if timestamp_ms <= shot.end_timestamp_ms else None


def _nearest_position(
    timestamps: Sequence[int], timestamp_ms: int, mode: TemporalResolutionMode
) -> int:
    if not timestamps:
        raise TemporalRegistryError("No keyframes are available for temporal lookup")
    position = bisect.bisect_left(timestamps, timestamp_ms)
    if mode == "before":
        if position < len(timestamps) and timestamps[position] == timestamp_ms:
            return position
        return max(0, position - 1)
    if mode == "after":
        return min(len(timestamps) - 1, position)
    if mode != "nearest":
        raise TemporalRegistryError(f"Unsupported temporal resolution mode: {mode}")
    if position <= 0:
        return 0
    if position >= len(timestamps):
        return len(timestamps) - 1
    before = position - 1
    after = position
    return (
        before
        if abs(timestamps[before] - timestamp_ms) <= abs(timestamps[after] - timestamp_ms)
        else after
    )


def _link_asr_segments(
    segments: Sequence[ASRSegment],
    frames_by_video: dict[str, list[FrameRecord]],
    shots_by_video: dict[str, list[ShotRecord]],
    durations_ms: dict[str, int],
) -> list[TemporalASRLinkRecord]:
    links: list[TemporalASRLinkRecord] = []
    for segment in sorted(segments, key=lambda row: (row.video_id, row.start_ms, row.end_ms)):
        frames = frames_by_video.get(segment.video_id, [])
        if not frames:
            continue
        duration = durations_ms.get(segment.video_id, frames[-1].timestamp_ms)
        if segment.start_ms > duration:
            raise TemporalRegistryError(
                f"ASR segment {segment.segment_id} starts beyond media duration"
            )
        end_ms = min(segment.end_ms, duration)
        timestamps = [frame.timestamp_ms for frame in frames]
        middle_ms = (segment.start_ms + end_ms) // 2
        representative = frames[_nearest_position(timestamps, middle_ms, "nearest")]
        before = frames[_nearest_position(timestamps, segment.start_ms, "before")]
        after = frames[_nearest_position(timestamps, end_ms, "after")]
        overlapping_frames = [
            frame for frame in frames if segment.start_ms <= frame.timestamp_ms <= end_ms
        ]
        overlapping_shots = [
            shot.shot_id
            for shot in shots_by_video.get(segment.video_id, [])
            if shot.start_timestamp_ms <= end_ms and shot.end_timestamp_ms >= segment.start_ms
        ]
        links.append(
            TemporalASRLinkRecord(
                preprocess_run_id=segment.preprocess_run_id,
                video_id=segment.video_id,
                segment_id=segment.segment_id,
                segment_start_ms=segment.start_ms,
                segment_end_ms=end_ms,
                representative_frame_id=representative.frame_id,
                representative_timestamp_ms=representative.timestamp_ms,
                nearest_before_frame_id=before.frame_id,
                nearest_after_frame_id=after.frame_id,
                overlapping_keyframe_ids=[frame.frame_id for frame in overlapping_frames],
                overlapping_shot_ids=overlapping_shots,
                created_at_utc=utcnow_iso(),
            )
        )
    return links


def build_temporal_registry(
    frames: list[FrameRecord],
    run_root: str | Path,
    *,
    shots: Sequence[ShotRecord] | None = None,
    asr_segments: Sequence[ASRSegment] | None = None,
    media: Sequence[MediaRecord] | None = None,
) -> list[TemporalFrameRecord]:
    """Build a persistent registry on the original video timeline.

    The registry stores only temporal relationships and provenance. It does not
    infer semantic events or perform retrieval ranking.
    """

    root = Path(run_root)
    shots = list(shots) if shots is not None else _load_shots(root)
    asr_segments = list(asr_segments) if asr_segments is not None else _load_asr(root)
    media = list(media) if media is not None else _load_media(root)

    frames_by_video = _group_by_video(frames)
    shots_by_video = _group_by_video(shots)
    durations_ms = {item.video_id: item.duration_ms for item in media}
    for video_id, video_frames in frames_by_video.items():
        video_frames.sort(key=lambda row: (row.timestamp_ms, row.frame_id))
        _validate_keyframes(video_id, video_frames)
        shots_by_video.setdefault(video_id, []).sort(
            key=lambda row: (row.start_timestamp_ms, row.start_frame_id)
        )
        durations_ms.setdefault(video_id, video_frames[-1].timestamp_ms)

    asr_links = _link_asr_segments(
        asr_segments, frames_by_video, shots_by_video, durations_ms
    )
    asr_links_by_video = _group_by_video(asr_links)

    temporal_rows: list[TemporalFrameRecord] = []
    for video_id in sorted(frames_by_video):
        video_frames = frames_by_video[video_id]
        video_shots = shots_by_video.get(video_id, [])
        video_links = asr_links_by_video.get(video_id, [])
        for index, frame in enumerate(video_frames):
            previous = video_frames[index - 1] if index > 0 else None
            following = video_frames[index + 1] if index + 1 < len(video_frames) else None
            shot = _shot_for_timestamp(video_shots, frame.timestamp_ms, frame.shot_id)
            linked_segments = [
                link.segment_id
                for link in video_links
                if link.segment_start_ms <= frame.timestamp_ms <= link.segment_end_ms
            ]
            temporal_rows.append(
                TemporalFrameRecord(
                    preprocess_run_id=frame.preprocess_run_id,
                    video_id=video_id,
                    frame_id=frame.frame_id,
                    keyframe_seq=frame.keyframe_seq,
                    timestamp_ms=frame.timestamp_ms,
                    pts=frame.pts,
                    time_base=frame.time_base,
                    shot_id=shot.shot_id if shot is not None else frame.shot_id,
                    shot_start_frame_id=shot.start_frame_id if shot is not None else None,
                    shot_end_frame_id=shot.end_frame_id if shot is not None else None,
                    shot_start_timestamp_ms=(
                        shot.start_timestamp_ms if shot is not None else None
                    ),
                    shot_end_timestamp_ms=shot.end_timestamp_ms if shot is not None else None,
                    previous_frame_id=previous.frame_id if previous is not None else None,
                    next_frame_id=following.frame_id if following is not None else None,
                    previous_timestamp_ms=(
                        previous.timestamp_ms if previous is not None else None
                    ),
                    next_timestamp_ms=(
                        following.timestamp_ms if following is not None else None
                    ),
                    linked_asr_segment_ids=linked_segments,
                    created_at_utc=utcnow_iso(),
                )
            )

    temporal_root = root / "temporal"
    frame_payload = [row.model_dump(mode="json") for row in temporal_rows]
    link_payload = [row.model_dump(mode="json") for row in asr_links]
    frames_jsonl = temporal_root / "temporal_frames.jsonl"
    frames_parquet = temporal_root / "temporal_frames.parquet"
    links_jsonl = temporal_root / "asr_links.jsonl"
    links_parquet = temporal_root / "asr_links.parquet"
    shots_jsonl = temporal_root / "shots.jsonl"
    shots_parquet = temporal_root / "shots.parquet"
    shot_payload = [row.model_dump(mode="json") for row in shots]
    write_jsonl(frames_jsonl, frame_payload)
    frames_parquet_written = write_parquet_optional(frames_parquet, frame_payload)
    write_jsonl(links_jsonl, link_payload)
    links_parquet_written = write_parquet_optional(links_parquet, link_payload)
    write_jsonl(shots_jsonl, shot_payload)
    shots_parquet_written = write_parquet_optional(shots_parquet, shot_payload)

    run_ids = sorted({row.preprocess_run_id for row in temporal_rows})
    manifest = {
        "schema_version": "1.0.0",
        "preprocess_run_ids": run_ids,
        "video_count": len(frames_by_video),
        "temporal_frame_count": len(temporal_rows),
        "shot_count": len(shots),
        "asr_link_count": len(asr_links),
        "temporal_frames_sha256": stable_json_hash(frame_payload),
        "shots_sha256": stable_json_hash(shot_payload),
        "asr_links_sha256": stable_json_hash(link_payload),
        "frames_jsonl_path": str(frames_jsonl),
        "frames_parquet_path": str(frames_parquet) if frames_parquet_written else None,
        "asr_links_jsonl_path": str(links_jsonl),
        "asr_links_parquet_path": str(links_parquet) if links_parquet_written else None,
        "shots_jsonl_path": str(shots_jsonl),
        "shots_parquet_path": str(shots_parquet) if shots_parquet_written else None,
        "created_at_utc": utcnow_iso(),
    }
    write_json(temporal_root / "manifest.json", manifest)
    return temporal_rows


def relink_asr_segments(
    run_root: str | Path, segments: Sequence[ASRSegment]
) -> list[TemporalASRLinkRecord]:
    """Persist ASR-to-timeline links after ASR becomes available.

    This can be called after ASR becomes available without rebuilding keyframes or the full registry.
    """

    registry = TemporalRegistry.from_run_root(run_root)
    frame_rows = [
        FrameRecord(
            preprocess_run_id=row.preprocess_run_id,
            video_id=row.video_id,
            frame_id=row.frame_id,
            keyframe_seq=row.keyframe_seq or 0,
            timestamp_ms=row.timestamp_ms,
            pts=row.pts,
            time_base=row.time_base,
            decode_index=None,
            shot_id=row.shot_id or "unknown",
            keyframe_path="",
            thumbnail_path=None,
            selection_reason="manual",
            created_at_utc=row.created_at_utc,
        )
        for row in registry.all_frames()
    ]
    frames_by_video = _group_by_video(frame_rows)
    links = _link_asr_segments(
        list(segments), frames_by_video, registry.shots_by_video, registry.durations_ms
    )
    temporal_root = Path(run_root) / "temporal"
    payload = [row.model_dump(mode="json") for row in links]
    write_jsonl(temporal_root / "asr_links.jsonl", payload)
    write_parquet_optional(temporal_root / "asr_links.parquet", payload)

    links_by_video = _group_by_video(links)
    updated_frames: list[TemporalFrameRecord] = []
    for row in registry.all_frames():
        segment_ids = [
            link.segment_id
            for link in links_by_video.get(row.video_id, [])
            if link.segment_start_ms <= row.timestamp_ms <= link.segment_end_ms
        ]
        updated_frames.append(row.model_copy(update={"linked_asr_segment_ids": segment_ids}))
    frame_payload = [row.model_dump(mode="json") for row in updated_frames]
    write_jsonl(temporal_root / "temporal_frames.jsonl", frame_payload)
    write_parquet_optional(temporal_root / "temporal_frames.parquet", frame_payload)

    manifest_path = temporal_root / "manifest.json"
    manifest = read_json(manifest_path) if manifest_path.exists() else {}
    manifest["asr_link_count"] = len(links)
    manifest["asr_links_sha256"] = stable_json_hash(payload)
    manifest["temporal_frames_sha256"] = stable_json_hash(frame_payload)
    manifest["updated_at_utc"] = utcnow_iso()
    write_json(manifest_path, manifest)
    return links


class TemporalRegistry:
    """Read-only temporal/window service backed by persistent run artifacts."""

    def __init__(
        self,
        frames: Sequence[TemporalFrameRecord],
        *,
        shots: Sequence[ShotRecord] = (),
        asr_links: Sequence[TemporalASRLinkRecord] = (),
        durations_ms: dict[str, int] | None = None,
    ):
        self.frames_by_video: dict[str, list[TemporalFrameRecord]] = _group_by_video(frames)
        self.shots_by_video: dict[str, list[ShotRecord]] = _group_by_video(shots)
        self.asr_links_by_video: dict[str, list[TemporalASRLinkRecord]] = _group_by_video(
            asr_links
        )
        self.durations_ms = dict(durations_ms or {})
        self._timestamps: dict[str, list[int]] = {}
        self._frame_positions: dict[str, dict[int, int]] = {}
        for video_id, items in self.frames_by_video.items():
            items.sort(key=lambda row: (row.timestamp_ms, row.frame_id))
            timestamps = [row.timestamp_ms for row in items]
            if any(right < left for left, right in zip(timestamps, timestamps[1:])):
                raise TemporalRegistryError(f"Non-monotonic registry for video {video_id}")
            frame_positions = {row.frame_id: index for index, row in enumerate(items)}
            if len(frame_positions) != len(items):
                raise TemporalRegistryError(f"Duplicate temporal frame IDs for {video_id}")
            self._timestamps[video_id] = timestamps
            self._frame_positions[video_id] = frame_positions
            self.durations_ms.setdefault(video_id, timestamps[-1])
        for video_id, items in self.shots_by_video.items():
            items.sort(key=lambda row: (row.start_timestamp_ms, row.start_frame_id))
        for video_id, items in self.asr_links_by_video.items():
            items.sort(key=lambda row: (row.segment_start_ms, row.segment_end_ms))

    @classmethod
    def from_run_root(cls, run_root: str | Path) -> "TemporalRegistry":
        root = Path(run_root)
        frames = [
            TemporalFrameRecord.model_validate(row)
            for row in read_jsonl(root / "temporal" / "temporal_frames.jsonl")
        ]
        if not frames:
            raise TemporalRegistryError(
                f"Temporal registry is missing or empty under {root / 'temporal'}"
            )
        temporal_shot_rows = read_jsonl(root / "temporal" / "shots.jsonl")
        shots = (
            [ShotRecord.model_validate(row) for row in temporal_shot_rows]
            if temporal_shot_rows
            else _load_shots(root)
        )
        asr_links = [
            TemporalASRLinkRecord.model_validate(row)
            for row in read_jsonl(root / "temporal" / "asr_links.jsonl")
        ]
        media = _load_media(root)
        return cls(
            frames,
            shots=shots,
            asr_links=asr_links,
            durations_ms={item.video_id: item.duration_ms for item in media},
        )

    def all_frames(self) -> list[TemporalFrameRecord]:
        return [
            frame
            for video_id in sorted(self.frames_by_video)
            for frame in self.frames_by_video[video_id]
        ]

    def videos(self) -> list[str]:
        return sorted(self.frames_by_video)

    def _require_video(self, video_id: str) -> list[TemporalFrameRecord]:
        frames = self.frames_by_video.get(video_id)
        if not frames:
            raise TemporalRegistryError(f"Unknown or empty video in temporal registry: {video_id}")
        return frames

    def get_frame(self, video_id: str, frame_id: int) -> TemporalFrameRecord:
        frames = self._require_video(video_id)
        position = self._frame_positions[video_id].get(frame_id)
        if position is None:
            raise TemporalRegistryError(
                f"Keyframe {frame_id} is not present in temporal registry for {video_id}"
            )
        return frames[position]

    def nearest_keyframe(
        self,
        video_id: str,
        timestamp_ms: int,
        mode: TemporalResolutionMode = "nearest",
    ) -> TemporalFrameRecord:
        frames = self._require_video(video_id)
        position = _nearest_position(self._timestamps[video_id], max(0, timestamp_ms), mode)
        return frames[position]

    def previous_keyframe(
        self, video_id: str, frame_id: int
    ) -> TemporalFrameRecord | None:
        frames = self._require_video(video_id)
        position = self._frame_positions[video_id].get(frame_id)
        if position is None:
            raise TemporalRegistryError(f"Unknown keyframe {frame_id} for {video_id}")
        return frames[position - 1] if position > 0 else None

    def next_keyframe(self, video_id: str, frame_id: int) -> TemporalFrameRecord | None:
        frames = self._require_video(video_id)
        position = self._frame_positions[video_id].get(frame_id)
        if position is None:
            raise TemporalRegistryError(f"Unknown keyframe {frame_id} for {video_id}")
        return frames[position + 1] if position + 1 < len(frames) else None

    def shot_at(self, video_id: str, timestamp_ms: int) -> ShotRecord | None:
        self._require_video(video_id)
        return _shot_for_timestamp(self.shots_by_video.get(video_id, []), timestamp_ms)

    def interval_to_keyframes(
        self,
        video_id: str,
        start_ms: int,
        end_ms: int,
        *,
        include_nearest_if_empty: bool = True,
    ) -> list[TemporalFrameRecord]:
        if end_ms < start_ms:
            raise TemporalRegistryError("end_ms must be >= start_ms")
        frames = self._require_video(video_id)
        duration = self.durations_ms[video_id]
        start = min(max(0, start_ms), duration)
        end = min(max(start, end_ms), duration)
        timestamps = self._timestamps[video_id]
        left = bisect.bisect_left(timestamps, start)
        right = bisect.bisect_right(timestamps, end)
        selected = frames[left:right]
        if selected or not include_nearest_if_empty:
            return list(selected)
        before = self.nearest_keyframe(video_id, start, "before")
        after = self.nearest_keyframe(video_id, end, "after")
        return [before] if before.frame_id == after.frame_id else [before, after]

    def window_by_radius(
        self, video_id: str, center_timestamp_ms: int, radius_ms: int
    ) -> TemporalWindowRecord:
        if radius_ms < 0:
            raise TemporalRegistryError("radius_ms must be non-negative")
        self._require_video(video_id)
        duration = self.durations_ms[video_id]
        requested_start = center_timestamp_ms - radius_ms
        requested_end = center_timestamp_ms + radius_ms
        start = min(max(0, requested_start), duration)
        end = min(max(start, requested_end), duration)
        center = min(max(start, center_timestamp_ms), end)
        representative = self.nearest_keyframe(video_id, center, "nearest")
        keyframes = self.interval_to_keyframes(video_id, start, end)
        shot_ids = list(
            dict.fromkeys(frame.shot_id for frame in keyframes if frame.shot_id is not None)
        )
        asr_ids = [
            link.segment_id
            for link in self.asr_links_by_video.get(video_id, [])
            if link.segment_start_ms <= end and link.segment_end_ms >= start
        ]
        return TemporalWindowRecord(
            preprocess_run_id=representative.preprocess_run_id,
            video_id=video_id,
            window_start_ms=start,
            window_end_ms=end,
            center_timestamp_ms=center,
            representative_frame_id=representative.frame_id,
            representative_timestamp_ms=representative.timestamp_ms,
            keyframe_ids=[frame.frame_id for frame in keyframes],
            shot_ids=shot_ids,
            asr_segment_ids=asr_ids,
            clamped_to_media=(start != requested_start or end != requested_end),
            created_at_utc=utcnow_iso(),
        )

    def canonicalize_candidate(
        self, candidate: SearchCandidate, *, default_radius_ms: int = 1500
    ) -> SearchCandidate:
        if default_radius_ms < 0:
            raise TemporalRegistryError("default_radius_ms must be non-negative")
        duration = self.durations_ms.get(candidate.video_id)
        if duration is None:
            raise TemporalRegistryError(f"Unknown video: {candidate.video_id}")
        if candidate.window_start_ms is None and candidate.window_end_ms is None:
            start = candidate.timestamp_ms - default_radius_ms
            end = candidate.timestamp_ms + default_radius_ms
        else:
            start = (
                candidate.window_start_ms
                if candidate.window_start_ms is not None
                else candidate.timestamp_ms
            )
            end = (
                candidate.window_end_ms
                if candidate.window_end_ms is not None
                else candidate.timestamp_ms
            )
        start = min(max(0, start), duration)
        end = min(max(start, end), duration)
        target = min(max(start, candidate.timestamp_ms), end)
        representative = self.nearest_keyframe(candidate.video_id, target, "nearest")
        provenance = dict(candidate.provenance)
        provenance["temporal_registry"] = {
            "requested_timestamp_ms": candidate.timestamp_ms,
            "canonical_window_start_ms": start,
            "canonical_window_end_ms": end,
            "representative_timestamp_ms": representative.timestamp_ms,
        }
        sources = list(dict.fromkeys([*candidate.provenance_sources, "temporal_registry"]))
        return candidate.model_copy(
            update={
                "frame_id": representative.frame_id,
                "representative_frame_id": representative.frame_id,
                "timestamp_ms": representative.timestamp_ms,
                "window_start_ms": start,
                "window_end_ms": end,
                "provenance_sources": sources,
                "provenance": provenance,
            }
        )
