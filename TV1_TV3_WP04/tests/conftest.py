from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from aic2026.config import load_settings
from aic2026.preprocessing import run_preprocessing


@pytest.fixture(scope="session")
def ffmpeg_tools_available() -> bool:
    return bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


@pytest.fixture(scope="session")
def real_smoke_run(tmp_path_factory, ffmpeg_tools_available):
    if not ffmpeg_tools_available:
        pytest.skip("ffmpeg/ffprobe are required for the real-video smoke fixture")
    root = tmp_path_factory.mktemp("tv1-real-smoke")
    videos = root / "videos"
    runs = root / "runs"
    videos.mkdir()
    video = videos / "three-scenes.mp4"
    command = [
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", "color=c=red:s=320x180:r=10:d=1",
        "-f", "lavfi", "-i", "color=c=green:s=320x180:r=10:d=1",
        "-f", "lavfi", "-i", "color=c=blue:s=320x180:r=10:d=1",
        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=16000:duration=3",
        "-filter_complex", "[0:v][1:v][2:v]concat=n=3:v=1:a=0[v]",
        "-map", "[v]", "-map", "3:a", "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-shortest", str(video),
    ]
    subprocess.run(command, check=True)
    config_path = Path(__file__).parents[1] / "configs" / "external_video_smoke.yaml"
    settings, raw = load_settings(config_path)

    # Keep the shared smoke fixture deterministic on machines with or without PyAV.
    # This fixture intentionally verifies the degraded FFprobe fallback path.
    settings.media.frame_index_backend = "ffprobe"
    raw["media"]["frame_index_backend"] = "ffprobe"

    settings.paths.runs_root = runs
    result = run_preprocessing(
        source=videos,
        run_id="real-smoke",
        settings=settings,
        raw_config=raw,
        repository_root=Path(__file__).parents[1],
    )
    assert result.errors == []
    return {"root": root, "runs": runs, "run_root": runs / "real-smoke", "settings": settings}
