from __future__ import annotations

from pathlib import Path

import yaml
from fastapi.testclient import TestClient

from aic2026.api import create_app
from aic2026.config import Settings
from aic2026.evidence_catalog import build_evidence_catalog
from aic2026.contracts import MediaRecord, MetadataRecord
from aic2026.text_index import build_text_index
from aic2026.utils import sha256_file, utcnow_iso, write_json, write_jsonl


def _build_run(tmp_path: Path):
    runs_root = tmp_path / "runs"
    run_root = runs_root / "tv3-api"
    video = tmp_path / "video.mp4"
    video.write_bytes(b"fixture-video")
    crop = run_root / "ocr" / "crops" / "crop.jpg"
    crop.parent.mkdir(parents=True, exist_ok=True)
    crop.write_bytes(b"fixture-crop")

    media = MediaRecord(
        preprocess_run_id="tv3-api",
        video_id="V1",
        original_video_path=str(video),
        source_sha256=sha256_file(video),
        duration_ms=5000,
        width_px=320,
        height_px=180,
        has_audio=False,
        created_at_utc=utcnow_iso(),
    )
    write_jsonl(run_root / "media" / "media.jsonl", [media.model_dump(mode="json")])
    write_json(run_root / "manifest.json", {"status": "completed"})
    write_jsonl(
        run_root / "frames.jsonl",
        [
            {
                "preprocess_run_id": "tv3-api",
                "video_id": "V1",
                "frame_id": 12,
                "keyframe_seq": 0,
                "timestamp_ms": 1200,
                "pts": 1200,
                "time_base": "1/1000",
                "decode_index": 12,
                "shot_id": "s0",
                "keyframe_path": "unused.jpg",
                "selection_reason": "max_gap",
                "created_at_utc": utcnow_iso(),
            }
        ],
    )
    write_jsonl(
        run_root / "ocr" / "ocr.jsonl",
        [
            {
                "preprocess_run_id": "tv3-api",
                "detection_id": "ocr:1",
                "video_id": "V1",
                "frame_id": 12,
                "timestamp_ms": 1200,
                "raw_text": "Cộng hòa Việt Nam",
                "normalized_text": "cộng hòa việt nam",
                "normalized_text_no_diacritics": "cong hoa viet nam",
                "punctuation_aware_text": "cộng hòa việt nam",
                "character_ngrams": [],
                "bbox_xyxy_norm": [0.1, 0.1, 0.5, 0.2],
                "polygon_norm": None,
                "confidence": 0.95,
                "below_threshold": False,
                "crop_evidence_path": crop.relative_to(run_root).as_posix(),
                "crop_sha256": sha256_file(crop),
                "source_keyframe_sha256": None,
                "model_name": "fixture",
                "model_version": "1",
                "created_at_utc": utcnow_iso(),
            }
        ],
    )
    write_jsonl(
        run_root / "asr" / "asr.jsonl",
        [
            {
                "preprocess_run_id": "tv3-api",
                "segment_id": "asr:1",
                "video_id": "V1",
                "start_ms": 2000,
                "end_ms": 3000,
                "text": "AI Challenge 2026",
                "normalized_text": "ai challenge 2026",
                "normalized_text_no_diacritics": "ai challenge 2026",
                "language": "vi",
                "words": [],
                "model_name": "fixture",
                "model_version": "1",
                "created_at_utc": utcnow_iso(),
            }
        ],
    )
    write_jsonl(
        run_root / "objects" / "objects.jsonl",
        [
            {
                "preprocess_run_id": "tv3-api",
                "detection_id": "object:1",
                "video_id": "V1",
                "frame_id": 12,
                "timestamp_ms": 1200,
                "label": "car",
                "canonical_label": "car",
                "label_aliases": ["car", "ô tô", "oto"],
                "class_id": 2,
                "bbox_xyxy_norm": [0.6, 0.5, 0.9, 0.9],
                "center_xy_norm": [0.75, 0.7],
                "spatial_region": "bottom_right",
                "area_ratio": 0.12,
                "count_in_frame": 1,
                "raw_count_in_frame": 1,
                "confidence": 0.9,
                "below_threshold": False,
                "model_name": "fixture",
                "model_version": "1",
                "created_at_utc": utcnow_iso(),
            }
        ],
    )
    metadata = MetadataRecord(
        preprocess_run_id="tv3-api",
        metadata_id="metadata:1",
        video_id="V1",
        source="organizer_youtube",
        title="Lễ hội Việt Nam",
        text="Lễ hội Việt Nam",
        normalized_text="lễ hội việt nam",
        normalized_text_no_diacritics="le hoi viet nam",
        source_record_sha256="d" * 64,
        created_at_utc=utcnow_iso(),
    )
    write_jsonl(run_root / "metadata" / "metadata.jsonl", [metadata.model_dump(mode="json")])

    settings = Settings()
    settings.paths.runs_root = runs_root
    settings.text_index.auto_build_if_missing = False
    config = tmp_path / "config.yaml"
    config.write_text(yaml.safe_dump(settings.model_dump(mode="json"), sort_keys=False), encoding="utf-8")
    write_json(run_root / "config.snapshot.json", settings.model_dump(mode="json"))
    build_text_index("tv3-api", run_root, settings)
    build_evidence_catalog(run_root)
    return run_root, config


def test_tv3_evidence_api_and_backend_provenance(tmp_path: Path):
    run_root, config = _build_run(tmp_path)
    request = {"query_id": "q1", "task": "KIS", "query_text": "viet nam", "limit": 10}
    with TestClient(create_app("tv3-api", config)) as client:
        status = client.get("/text/index/status")
        assert status.status_code == 200
        assert status.json()["valid"] is True
        assert status.json()["manifest"]["selected_adapter"] == "local_bm25"

        text_rows = client.post("/text/search", json=request)
        assert text_rows.status_code == 200
        assert {row["source"] for row in text_rows.json()} >= {"ocr", "metadata"}

        ocr_rows = client.post("/ocr/search", json=request)
        assert ocr_rows.status_code == 200
        assert all(row["source"] == "ocr" for row in ocr_rows.json())
        crop = client.get("/ocr/ocr:1/crop")
        assert crop.status_code == 200

        asr_rows = client.post(
            "/asr/search",
            json={"query_id": "q2", "task": "KIS", "query_text": "challenge", "limit": 10},
        )
        assert asr_rows.status_code == 200
        assert all(row["source"] == "asr" for row in asr_rows.json())
        context = client.get("/asr/asr:1/context")
        assert context.status_code == 200

        object_rows = client.post(
            "/object/search",
            json={"query_id": "q3", "task": "KIS", "query_text": "car", "limit": 10},
        )
        assert object_rows.status_code == 200
        assert object_rows.json()[0]["source"] == "object"

        metadata_rows = client.post(
            "/metadata/search",
            json={"query_id": "q4", "task": "KIS", "query_text": "le hoi", "limit": 10},
        )
        assert metadata_rows.status_code == 200
        assert all(row["provenance"]["submittable"] is False for row in metadata_rows.json())


def test_asr_interval_validation_and_crop_path_safety(tmp_path: Path):
    run_root, config = _build_run(tmp_path)
    rows = list(__import__("json").loads(line) for line in (run_root / "ocr" / "ocr.jsonl").read_text().splitlines())
    rows[0]["crop_evidence_path"] = "../../outside.jpg"
    write_jsonl(run_root / "ocr" / "ocr.jsonl", rows)
    build_evidence_catalog(run_root, force=True)
    with TestClient(create_app("tv3-api", config)) as client:
        invalid = client.get("/asr/segments?start_ms=3000&end_ms=1000")
        assert invalid.status_code == 422
        unsafe = client.get("/ocr/ocr:1/crop")
        assert unsafe.status_code == 400


def test_evidence_catalog_pagination_filters_and_status(tmp_path: Path):
    _, config = _build_run(tmp_path)
    with TestClient(create_app("tv3-api", config)) as client:
        status = client.get("/evidence/catalog/status")
        assert status.status_code == 200
        assert status.json()["counts"] == {
            "ocr": 1,
            "asr": 1,
            "object": 1,
            "metadata": 1,
        }

        ocr = client.get("/ocr/detections", params={"limit": 1, "envelope": True})
        assert ocr.status_code == 200
        assert ocr.json()["items"][0]["detection_id"] == "ocr:1"

        objects = client.get(
            "/objects/detections",
            params={
                "label": "ô tô",
                "min_confidence": 0.5,
                "include_below_threshold": False,
                "envelope": True,
            },
        )
        assert objects.status_code == 200
        assert objects.json()["items"][0]["detection_id"] == "object:1"

        metadata = client.get(
            "/metadata/records",
            params={"source": "organizer_youtube", "envelope": True},
        )
        assert metadata.status_code == 200
        assert metadata.json()["items"][0]["metadata_id"] == "metadata:1"

        assert client.get("/ocr/detections", params={"cursor": "bad"}).status_code == 422
        assert client.get("/objects/detections", params={"min_confidence": 2}).status_code == 422
