"""Canonical PTS-to-original-frame mapping seam for decoded video frames."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .contracts import ContractError, RefinementContext, RefinementUnavailable
from .decoder import DecodeBudgetExhausted, DecodedFrame


@dataclass(frozen=True)
class RawDecodedFrame:
    pts: int
    time_base: str
    timestamp_ms: int
    image_rgb: object | None = None


@dataclass(frozen=True)
class ResolvedFrameIdentity:
    frame_id: int
    timestamp_ms: int
    pts: int


class FrameMappingResolver(Protocol):
    def resolve_frame(
        self, video_id: str, pts: int, time_base: str, context: RefinementContext
    ) -> ResolvedFrameIdentity: ...


class RawVideoDecoder(Protocol):
    def duration_ms(self, video_path: Path) -> int: ...

    def raw_frames_between(
        self, video_path: Path, start_ms: int, end_ms: int, max_fps: float, max_frames: int | None = None
    ) -> tuple[RawDecodedFrame, ...]: ...


class MappedVideoDecoder:
    """Adapts raw PTS frames through the sole canonical mapping resolver."""

    def __init__(self, raw_decoder: RawVideoDecoder, resolver: FrameMappingResolver, *, video_id: str, context: RefinementContext) -> None:
        self._raw_decoder = raw_decoder
        self._resolver = resolver
        self._video_id = video_id
        self._context = context

    def duration_ms(self, video_path: Path) -> int:
        return self._raw_decoder.duration_ms(video_path)

    def frames_between(self, video_path: Path, start_ms: int, end_ms: int, max_fps: float, max_frames: int | None = None) -> tuple[DecodedFrame, ...]:
        frames: list[DecodedFrame] = []
        try:
            raw_frames = self._raw_decoder.raw_frames_between(video_path, start_ms, end_ms, max_fps, max_frames)
        except DecodeBudgetExhausted:
            raise
        except Exception as exc:
            raise RefinementUnavailable("decode_failure") from exc
        for raw in raw_frames:
            try:
                identity = self._resolver.resolve_frame(self._video_id, raw.pts, raw.time_base, self._context)
            except Exception as exc:
                raise RefinementUnavailable("mapping_failure") from exc
            if identity.pts != raw.pts or identity.timestamp_ms != raw.timestamp_ms:
                raise RefinementUnavailable("mapping_failure")
            frames.append(DecodedFrame(identity.frame_id, raw.pts, raw.time_base, raw.timestamp_ms, raw.image_rgb))
        return tuple(frames)
    mapping_guaranteed = True
