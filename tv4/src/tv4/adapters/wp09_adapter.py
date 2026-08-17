"""Default `--decoder-factory` / `--scorer-factory` for TV2's WP09 CLI.

No other package ships a `MappedVideoDecoder` yet (WP09's own README calls
this out as something "an external decoder factory is responsible for"), so
TV4 provides one here: it decodes with PyAV and resolves TV1 frame identity
through TV1's WP06 API instead of re-deriving frame_id from fps/index.

`frame_id` MUST be the same integer index used everywhere else in the system
(`frame_index`/`frames.parquet`, `objects.py`/`ocr.py` lookups, and the
submission key). PyAV's raw PTS is a different numbering entirely and must
never be written into `DecodedFrame.frame_id` — doing so silently corrupts
any candidate that goes through refine (see bug report #1, tv4 review).

Instead, each decoded frame's `timestamp_ms` (which *is* accurate — it comes
straight from the container, not from fps math) is resolved against TV1's
`/frames/{video_id}` list via `TV1Client.nearest_frame`, exactly the helper
TV1Client already exposes for this purpose. If TV1 is unreachable or has no
frames for the video, we raise instead of fabricating an id: WP09's service
layer catches decoder exceptions and reports `RefinementUnavailable`
("decode_failure"), which TV4's `TV2RefineClient` turns into `None` and
`_refine_top` treats as "leave the candidate as-is" — a loud, safe failure
instead of a silent, wrong one.
"""
from __future__ import annotations

import os
from pathlib import Path

from tv4.clients.tv1_client import TV1Client, TV1ClientError

TV1_BASE_URL = os.environ.get("TV4_TV1_BASE_URL", "http://127.0.0.1:8000")


class MappedPyAVDecoder:
    mapping_guaranteed = True

    def __init__(self, video_id: str, base_url: str = TV1_BASE_URL) -> None:
        self.base_url = base_url
        self.video_id = video_id
        from wp09.pyav_decoder import PyAVVideoDecoder  # local import: only needed in WP09's venv

        self._raw = PyAVVideoDecoder()
        self._tv1 = TV1Client(base_url)
        # Fetched once per decoder instance (one refine request), not once
        # per frame, to avoid re-downloading the whole frame list per frame.
        self._frames_cache: list[dict] | None = None

    def duration_ms(self, video_path: Path) -> int:
        return self._raw.duration_ms(video_path)

    def frames_between(self, video_path: Path, start_ms: int, end_ms: int, max_fps: float, max_frames: int | None = None):
        from wp09.decoder import DecodedFrame

        raw = self._raw.raw_frames_between(video_path, start_ms, end_ms, max_fps, max_frames)
        frames = self._tv1_frames()
        return tuple(
            DecodedFrame(
                frame_id=self._resolve_frame_id(r, frames),
                pts=r.pts,
                time_base=r.time_base,
                timestamp_ms=r.timestamp_ms,
                image_rgb=r.image_rgb,
            )
            for r in raw
        )

    def _tv1_frames(self) -> list[dict]:
        if self._frames_cache is None:
            try:
                self._frames_cache = self._tv1.frames(self.video_id) or []
            except TV1ClientError:
                self._frames_cache = []
        return self._frames_cache

    def _resolve_frame_id(self, raw_frame, frames: list[dict]) -> int:
        if not frames:
            raise RuntimeError(
                f"wp09_adapter: cannot resolve canonical frame_id for video "
                f"'{self.video_id}' — TV1 /frames/{self.video_id} returned no "
                "data. Refusing to fall back to raw PTS, which would silently "
                "corrupt the refined candidate's frame_id."
            )
        nearest = min(frames, key=lambda f: abs(int(f["timestamp_ms"]) - int(raw_frame.timestamp_ms)))
        return int(nearest["frame_id"])


def decoder_for_request(request) -> "MappedPyAVDecoder":
    return MappedPyAVDecoder(video_id=request.candidate.video_id)


def scorer_for_request(request):
    """Optional SigLIP2-based frame scorer; returns None (manual_only) if unavailable."""
    try:
        from wp09.scoring import Siglip2Scorer
    except Exception:
        return None
    try:
        return Siglip2Scorer()
    except Exception:
        return None
