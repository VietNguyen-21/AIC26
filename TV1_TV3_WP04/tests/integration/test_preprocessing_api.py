from __future__ import annotations

from pathlib import Path

import yaml
from fastapi.testclient import TestClient

from aic2026.api import create_app
from aic2026.config import load_settings


def _config_for_smoke(real_smoke_run, tmp_path: Path) -> Path:
    settings, _ = load_settings(Path(__file__).parents[2] / "configs" / "external_video_smoke.yaml")
    settings.paths.runs_root = real_smoke_run["runs"]
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(settings.model_dump(mode="json"), sort_keys=False), encoding="utf-8")
    return path


def test_api_health_registry_keyframes_window_and_range(real_smoke_run, tmp_path):
    app = create_app("real-smoke", _config_for_smoke(real_smoke_run, tmp_path))
    with TestClient(app) as client:
        health = client.get("/health")
        assert health.status_code == 200
        assert health.json()["video_count"] == 1
        video = client.get("/videos").json()[0]
        video_id = video["video_id"]
        assert client.get("/runs/active").json()["active_run_id"] == "real-smoke"
        registry = client.get("/runs/real-smoke/registry")
        assert registry.status_code == 200
        assert registry.json()["summary"]["status_counts"]["completed"] >= 6
        keyframes = client.get(f"/videos/{video_id}/keyframes")
        assert keyframes.status_code == 200
        assert len(keyframes.json()) >= 1
        window = client.get(f"/videos/{video_id}/window", params={"center_ms": 1200, "radius_ms": 700})
        assert window.status_code == 200
        assert window.json()["window_start_ms"] <= 1200 <= window.json()["window_end_ms"]
        head = client.head(f"/videos/{video_id}/stream")
        assert head.status_code == 200
        assert head.headers["accept-ranges"] == "bytes"
        partial = client.get(f"/videos/{video_id}/stream", headers={"Range": "bytes=0-255"})
        assert partial.status_code == 206
        assert len(partial.content) == 256
        invalid = client.get(f"/videos/{video_id}/stream", headers={"Range": "bytes=999999999-"})
        assert invalid.status_code == 416


def test_api_original_frame_resolve_and_error_paths(real_smoke_run, tmp_path):
    app = create_app("real-smoke", _config_for_smoke(real_smoke_run, tmp_path))
    with TestClient(app) as client:
        video_id = client.get("/videos").json()[0]["video_id"]
        resolved = client.get(f"/videos/{video_id}/resolve", params={"timestamp_ms": 500, "mode": "nearest"})
        assert resolved.status_code == 200
        frame_id = resolved.json()["record"]["frame_id"]
        image = client.get(f"/videos/{video_id}/frames/{frame_id}.jpg")
        assert image.status_code == 200
        assert image.headers["content-type"].startswith("image/jpeg")
        assert int(image.headers["x-original-frame-id"]) == frame_id
        assert client.get(f"/videos/{video_id}/resolve", params={"timestamp_ms": 1, "mode": "bad"}).status_code == 422
        assert client.get("/videos/unknown/keyframes").status_code == 404
        assert client.get("/runs/not-active/registry").status_code == 409
        assert client.post("/runs/../activate").status_code in {404, 405}
