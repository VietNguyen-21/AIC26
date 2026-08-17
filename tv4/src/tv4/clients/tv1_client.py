"""Thin client for TV1's WP06 API server (tv1/wp06_api_server.py).

TV4 never re-derives frame_id/timestamp itself: any frame/window/neighbor
information always comes from this service so TV4's output stays consistent
with the "video gốc là sự thật cuối cùng" rule TV1 documents.
"""
from __future__ import annotations

import json
import threading
import urllib.request
import urllib.error
from typing import Any


class TV1ClientError(RuntimeError):
    pass


class TV1Client:
    def __init__(self, base_url: str, timeout: float = 15.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        # `frames(video_id)` downloads the video's *entire* frame list; it is
        # called repeatedly for the same video (once per candidate in
        # build_evidence_pack, once per refine decoder instance, etc). Cache
        # per video_id for the lifetime of this client to turn that N+1
        # pattern into effectively one GET per video.
        self._frames_cache: dict[str, list[dict]] = {}
        self._media_cache: dict[str, dict] | None = None
        # `batch --parallel` (cli.py) can drive this client from several
        # threads at once; guard the caches so concurrent first-fetches for
        # different videos can't corrupt the dicts or race on the media
        # cache's lazy-init check-then-set.
        self._cache_lock = threading.Lock()

    def _get(self, path: str) -> Any:
        url = f"{self.base_url}{path}"
        try:
            with urllib.request.urlopen(url, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            raise TV1ClientError(f"GET {url} failed: {exc}") from exc

    def health(self) -> dict:
        return self._get("/health")

    def summary(self) -> dict:
        return self._get("/summary")

    def manifest(self) -> Any:
        return self._get("/manifest")

    def frames(self, video_id: str, *, use_cache: bool = True) -> list[dict]:
        """List of {frame_id, timestamp_ms, keyframe_path, ...} for a video.

        Cached per video_id (see __init__) since callers frequently ask for
        the same video's frame list many times in a row. Pass
        use_cache=False to force a fresh fetch (e.g. long-lived processes
        where the active run may have changed).
        """
        if use_cache:
            with self._cache_lock:
                cached = self._frames_cache.get(video_id)
            if cached is not None:
                return cached
        frames = self._get(f"/frames/{video_id}")
        with self._cache_lock:
            self._frames_cache[video_id] = frames
        return frames

    def media_record(self, video_id: str) -> dict | None:
        """Media record for a video, e.g. {video_id, original_video_path, ...}.

        Used to resolve the real video file (and its real extension) instead
        of assuming `.mp4`. Cached: `/media` returns every video at once, so
        one GET covers the whole run.
        """
        with self._cache_lock:
            cache = self._media_cache
        if cache is None:
            fetched = {row["video_id"]: row for row in self._get("/media")}
            with self._cache_lock:
                if self._media_cache is None:
                    self._media_cache = fetched
                cache = self._media_cache
        return cache.get(video_id)

    def keyframe_image_url(self, video_id: str, filename: str) -> str:
        return f"{self.base_url}/keyframe-image/{video_id}/{filename}"

    def validate_run(self, run_id: str) -> dict:
        return self._get(f"/runs/{run_id}/validate")

    def nearest_frame(self, video_id: str, timestamp_ms: int) -> dict | None:
        """Best-effort: pick the frame whose timestamp is closest to the target.

        Used by WP10/WP12 when a modality only returns a timestamp window
        (e.g. an ASR segment) and needs a concrete representative frame_id.
        """
        frames = self.frames(video_id)
        if not frames:
            return None
        return min(frames, key=lambda f: abs(int(f["timestamp_ms"]) - int(timestamp_ms)))

    def frames_in_window(self, video_id: str, start_ms: int, end_ms: int) -> list[dict]:
        return [f for f in self.frames(video_id) if start_ms <= int(f["timestamp_ms"]) <= end_ms]

    def clear_frames_cache(self, video_id: str | None = None) -> None:
        """Drop cached frame lists (all videos, or just one)."""
        with self._cache_lock:
            if video_id is None:
                self._frames_cache.clear()
            else:
                self._frames_cache.pop(video_id, None)
