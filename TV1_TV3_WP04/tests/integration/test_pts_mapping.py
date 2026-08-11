from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from aic2026.contracts import CorpusManifestRecord
from aic2026.frame_index import (
    OriginalFrameIndex,
    build_original_frame_index,
    load_original_frame_index,
    pyav_available,
)
from aic2026.media import FrameResolver, infer_variable_frame_rate, probe_media
from aic2026.utils import sha256_file, utcnow_iso


pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe missing",
)


def manifest(video: Path) -> CorpusManifestRecord:
    return CorpusManifestRecord(
        video_id=video.stem,
        original_video_path=str(video),
        source_sha256=sha256_file(video),
        file_size_bytes=video.stat().st_size,
        created_at_utc=utcnow_iso(),
    )


def create_cfr(video: Path, fps: int) -> None:
    video.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"testsrc=size=160x90:rate={fps}:duration=1",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(video),
        ],
        check=True,
    )


def create_vfr(video: Path) -> None:
    video.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=160x90:rate=30:duration=2",
            "-vf",
            "select='if(lt(t,1),not(mod(n,3)),1)'",
            "-fps_mode",
            "vfr",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(video),
        ],
        check=True,
    )


@pytest.mark.parametrize("fps", [25, 30])
def test_cfr_original_index_and_exact_decode(tmp_path: Path, fps: int):
    video = tmp_path / f"cfr{fps}.mp4"
    create_cfr(video, fps)
    media = probe_media(manifest(video), "run-cfr")
    artifact = build_original_frame_index(media, tmp_path / "run", backend="ffprobe")
    records = load_original_frame_index(artifact.jsonl_path)
    media.original_frame_index_path = str(artifact.jsonl_path)
    media.frame_index_backend = "ffprobe"
    media.frame_count = len(records)

    assert len(records) == fps
    assert records[0].frame_id == 0
    assert records[-1].frame_id == fps - 1
    assert all(a.timestamp_ms <= b.timestamp_ms for a, b in zip(records, records[1:]))
    assert not infer_variable_frame_rate(records)

    resolver = FrameResolver(media, backend="ffmpeg", allow_ffmpeg_fallback=True)
    try:
        middle = fps // 2
        frame_id, timestamp_ms, image = resolver.get_frame(middle)
        assert frame_id == middle
        assert image.shape == (90, 160, 3)
        resolved_id, resolved_ms, _ = resolver.get_frame_at_time(timestamp_ms)
        assert resolved_id == middle
        assert resolved_ms == timestamp_ms
    finally:
        resolver.close()


def test_vfr_mapping_uses_pts_not_fixed_fps(tmp_path: Path):
    video = tmp_path / "vfr.mp4"
    create_vfr(video)
    media = probe_media(manifest(video), "run-vfr")
    artifact = build_original_frame_index(media, tmp_path / "run", backend="ffprobe")
    records = load_original_frame_index(artifact.jsonl_path)
    index = OriginalFrameIndex(records)
    media.original_frame_index_path = str(artifact.jsonl_path)
    media.frame_index_backend = "ffprobe"
    media.frame_count = len(records)

    deltas = [
        current.timestamp_ms - previous.timestamp_ms
        for previous, current in zip(records, records[1:])
        if current.timestamp_ms > previous.timestamp_ms
    ]
    assert len(records) == 40
    assert min(deltas) <= 34
    assert max(deltas) >= 99
    assert infer_variable_frame_rate(records)

    # Around 950 ms the true PTS cadence is 100 ms; fixed 30-FPS arithmetic
    # would predict frame ~29, while the PTS index correctly resolves frame 9/10.
    resolved = index.resolve_timestamp(950, mode="nearest")
    assert resolved.record.frame_id in {9, 10}
    assert resolved.absolute_error_ms <= 50

    resolver = FrameResolver(media, backend="ffmpeg", allow_ffmpeg_fallback=True)
    try:
        decoded = resolver.resolve_timestamp_to_frame(1034)
        assert decoded.record.timestamp_ms in {1033, 1034}
        assert decoded.record.frame_id == 11
        assert decoded.image_bgr.shape == (90, 160, 3)
        last = resolver.get_frame_with_record(len(records) - 1)
        assert last.record.frame_id == len(records) - 1
    finally:
        resolver.close()


@pytest.mark.skipif(not pyav_available(), reason="PyAV is not installed in this runtime")
def test_pyav_backend_matches_ffprobe_index_on_cfr(tmp_path: Path):
    video = tmp_path / "pyav-cfr.mp4"
    create_cfr(video, 25)
    media = probe_media(manifest(video), "run-pyav")
    pyav_artifact = build_original_frame_index(media, tmp_path / "pyav", backend="pyav")
    ffprobe_artifact = build_original_frame_index(media, tmp_path / "ffprobe", backend="ffprobe")
    pyav_records = load_original_frame_index(pyav_artifact.jsonl_path)
    ffprobe_records = load_original_frame_index(ffprobe_artifact.jsonl_path)
    assert len(pyav_records) == len(ffprobe_records) == 25
    assert [row.timestamp_ms for row in pyav_records] == [
        row.timestamp_ms for row in ffprobe_records
    ]
