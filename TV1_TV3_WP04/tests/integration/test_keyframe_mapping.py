from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from aic2026.config import load_settings
from aic2026.contracts import CorpusManifestRecord, ShotRecord
from aic2026.keyframes import extract_keyframes
from aic2026.media import probe_media
from aic2026.utils import read_jsonl, sha256_file, utcnow_iso

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


def create_cut_video(video: Path) -> None:
    video.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error",
            "-f", "lavfi", "-i", "color=c=red:s=160x90:r=10:d=1.5",
            "-f", "lavfi", "-i", "color=c=blue:s=160x90:r=10:d=1.5",
            "-f", "lavfi", "-i", "color=c=red:s=160x90:r=10:d=1.5",
            "-filter_complex", "[0:v][1:v][2:v]concat=n=3:v=1:a=0",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video),
        ],
        check=True,
    )


def create_long_shot(video: Path) -> None:
    video.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
            "testsrc2=size=160x90:rate=10:duration=6",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video),
        ],
        check=True,
    )


def smoke_settings():
    root = Path(__file__).parents[2]
    settings, _ = load_settings(root / "configs" / "external_video_smoke.yaml")
    settings.keyframes.shot_model = "histogram"
    settings.keyframes.sample_every_ms = 100
    settings.keyframes.shot_threshold = 0.15
    settings.keyframes.max_gap_ms = 1500
    settings.keyframes.min_shot_ms = 300
    settings.keyframes.representative_search_radius_ms = 200
    settings.keyframes.representative_candidate_step_ms = 100
    settings.keyframes.boundary_guard_ms = 100
    return settings


def test_hybrid_shots_and_keyframes_use_original_pts(tmp_path: Path):
    video = tmp_path / "cuts.mp4"
    create_cut_video(video)
    media = probe_media(manifest(video), "round03")
    settings = smoke_settings()
    run_root = tmp_path / "run"
    frames = extract_keyframes(media, run_root, settings)
    shots = [ShotRecord.model_validate(row) for row in read_jsonl(run_root / "shots" / "cuts.jsonl")]

    assert len(shots) >= 3
    assert shots[0].detector_name == "pts_histogram"
    assert all(shot.start_frame_id <= shot.end_frame_id for shot in shots)
    assert all(frame.pts is not None and frame.time_base for frame in frames)
    assert {frame.shot_id for frame in frames}.issubset({shot.shot_id for shot in shots})
    # The same red scene occurs far apart and must not be globally deduplicated away.
    assert any(frame.timestamp_ms < 1500 for frame in frames)
    assert any(frame.timestamp_ms >= 3000 for frame in frames)


def test_long_shot_max_gap_coverage_guard(tmp_path: Path):
    video = tmp_path / "long.mp4"
    create_long_shot(video)
    media = probe_media(manifest(video), "round03")
    settings = smoke_settings()
    settings.keyframes.shot_threshold = 1.0
    run_root = tmp_path / "run"
    frames = extract_keyframes(media, run_root, settings)
    points = [0] + sorted(frame.timestamp_ms for frame in frames) + [media.duration_ms - 1]
    assert max(right - left for left, right in zip(points, points[1:])) <= 1600
    assert any(frame.selection_reason == "max_gap" for frame in frames)
    assert any(frame.selection_reason == "boundary_guard" for frame in frames)
