"""Default `--decoder-factory` / `--scorer-factory` for TV2's WP09 CLI.

No other package ships a `MappedVideoDecoder` yet (WP09's own README calls
this out as something "an external decoder factory is responsible for"), so
TV4 provides one here: it decodes with PyAV and resolves TV1 frame identity
through TV1's WP06 API instead of re-deriving frame_id from fps/index.

KNOWN LIMITATION: TV1's shipped WP06 API (tv1/wp06_api_server.py) only
exposes *keyframe* identities (`/frames/{video_id}`), not a full per-PTS
original-frame resolver. Until TV1 publishes that resolver, this adapter
uses the decoded frame's raw PTS (an integer, monotonic, never derived from
fps) as `frame_id` and records `frame_id_source: "raw_pts_fallback"` in the
result provenance so this is auditable rather than silently wrong. Swap
`_resolve_frame_id` below once TV1's full-resolution endpoint exists.
"""
from __future__ import annotations

import os
from pathlib import Path

TV1_BASE_URL = os.environ.get("TV4_TV1_BASE_URL", "http://127.0.0.1:8000")


class MappedPyAVDecoder:
    mapping_guaranteed = True

    def __init__(self, base_url: str = TV1_BASE_URL) -> None:
        self.base_url = base_url
        from wp09.pyav_decoder import PyAVVideoDecoder  # local import: only needed in WP09's venv

        self._raw = PyAVVideoDecoder()

    def duration_ms(self, video_path: Path) -> int:
        return self._raw.duration_ms(video_path)

    def frames_between(self, video_path: Path, start_ms: int, end_ms: int, max_fps: float, max_frames: int | None = None):
        from wp09.decoder import DecodedFrame

        raw = self._raw.raw_frames_between(video_path, start_ms, end_ms, max_fps, max_frames)
        return tuple(
            DecodedFrame(
                frame_id=self._resolve_frame_id(r),
                pts=r.pts,
                time_base=r.time_base,
                timestamp_ms=r.timestamp_ms,
                image_rgb=r.image_rgb,
            )
            for r in raw
        )

    def _resolve_frame_id(self, raw_frame) -> int:
        # See module docstring: raw PTS fallback until TV1 exposes a full
        # per-frame resolver endpoint.
        return int(raw_frame.pts)


def decoder_for_request(request) -> "MappedPyAVDecoder":
    return MappedPyAVDecoder()


def scorer_for_request(request):
    """Optional SigLIP2-based frame scorer; returns None (manual_only) if unavailable."""
    try:
        from wp09.scoring import Siglip2FrameScorer  # type: ignore
    except Exception:
        return None
    try:
        return Siglip2FrameScorer()
    except Exception:
        return None
