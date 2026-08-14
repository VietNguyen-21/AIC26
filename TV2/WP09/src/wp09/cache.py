"""Internal cache for frames already resolved by a canonical mapping run."""

from __future__ import annotations

from dataclasses import dataclass

from .decoder import DecodedFrame


@dataclass(frozen=True)
class DecodedWindowKey:
    preprocess_run_id: str
    video_id: str
    start_pts: int
    end_pts: int
    decoder_config: str


@dataclass(frozen=True)
class WindowRequestKey:
    """Lookup identity available before any decode. Values are not canonical IDs."""
    preprocess_run_id: str
    video_id: str
    center_ms: int
    radius_ms: int
    budget_signature: tuple[int, int, int | None, int]
    decoder_config: str


@dataclass(frozen=True)
class CachedWindow:
    key: DecodedWindowKey
    frames: tuple[DecodedFrame, ...]
    window_start_ms: int
    window_end_ms: int
    best_frame_id: int
    budget_exhausted: bool


class DecodedWindowCache:
    """Small in-memory cache. Its identity intentionally includes mapping/run truth."""

    def __init__(self) -> None:
        self._entries: dict[DecodedWindowKey, tuple[DecodedFrame, ...]] = {}
        self._request_index: dict[WindowRequestKey, CachedWindow] = {}

    def get(self, key: DecodedWindowKey) -> tuple[DecodedFrame, ...] | None:
        return self._entries.get(key)

    def put(self, key: DecodedWindowKey, frames: tuple[DecodedFrame, ...]) -> None:
        self._entries[key] = frames

    def get_for_request(self, key: WindowRequestKey) -> CachedWindow | None:
        return self._request_index.get(key)

    def put_for_request(self, request_key: WindowRequestKey, entry: CachedWindow) -> None:
        self._entries[entry.key] = entry.frames
        self._request_index[request_key] = entry
