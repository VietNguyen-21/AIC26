from __future__ import annotations

import sys
from fractions import Fraction
from types import SimpleNamespace

import numpy as np

from aic2026.contracts import MediaRecord
from aic2026.frame_index import build_original_frame_index, load_original_frame_index
from aic2026.media import FrameResolver


class FakeFrame:
    def __init__(self, pts: int, value: int, key_frame: bool = False):
        self.pts = pts
        self.dts = pts
        self.time = pts / 1000.0
        self.key_frame = key_frame
        self._value = value

    def to_ndarray(self, format: str):
        assert format == "bgr24"
        return np.full((2, 3, 3), self._value, dtype=np.uint8)


class FakeContainer:
    def __init__(self):
        self.stream = SimpleNamespace(time_base=Fraction(1, 1000))
        self.streams = SimpleNamespace(video=[self.stream])
        self.frames = [FakeFrame(0, 10, True), FakeFrame(40, 20), FakeFrame(80, 30)]
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.close()

    def decode(self, stream):
        assert stream is self.stream
        yield from self.frames

    def seek(self, offset, stream, backward=True, any_frame=False):
        assert stream is self.stream
        assert backward is True
        assert any_frame is False

    def close(self):
        self.closed = True


def test_pyav_build_and_decode_code_path(monkeypatch, tmp_path):
    fake_module = SimpleNamespace(open=lambda *args, **kwargs: FakeContainer())
    monkeypatch.setitem(sys.modules, "av", fake_module)
    media = MediaRecord(
        preprocess_run_id="run-pyav-fake",
        video_id="fake",
        original_video_path="fake.mp4",
        source_sha256="0" * 64,
        time_base="1/1000",
        fps_nominal=25.0,
        fps_average=25.0,
        is_variable_frame_rate=False,
        frame_count=3,
        duration_ms=120,
        width_px=3,
        height_px=2,
        codec="fake",
        has_audio=False,
        created_at_utc="2026-08-04T00:00:00Z",
    )
    artifact = build_original_frame_index(media, tmp_path, backend="pyav")
    records = load_original_frame_index(artifact.jsonl_path)
    assert [row.pts for row in records] == [0, 40, 80]
    assert [row.timestamp_ms for row in records] == [0, 40, 80]

    media.original_frame_index_path = str(artifact.jsonl_path)
    media.frame_index_backend = "pyav"
    resolver = FrameResolver(media, backend="pyav")
    try:
        decoded = resolver.get_frame_with_record(1)
        assert decoded.record.frame_id == 1
        assert int(decoded.image_bgr.mean()) == 20
    finally:
        resolver.close()
