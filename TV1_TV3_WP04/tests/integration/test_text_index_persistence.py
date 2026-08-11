from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from aic2026.api import create_app
from aic2026.config import Settings
from aic2026.contracts import MediaRecord, MetadataRecord
from aic2026.text_index import build_text_index
from aic2026.utils import utcnow_iso, write_json, write_jsonl


def test_text_index_survives_api_restart_and_keeps_ranked_lists_separate(tmp_path: Path):
    runs_root = tmp_path / "runs"
    run_root = runs_root / "api-text-run"
    video_path = tmp_path / "video.mp4"
    video_path.write_bytes(b"fixture")
    media = MediaRecord(
        preprocess_run_id="api-text-run",
        video_id="V1",
        original_video_path=str(video_path),
        source_sha256="a" * 64,
        duration_ms=5000,
        width_px=320,
        height_px=180,
        has_audio=False,
        created_at_utc=utcnow_iso(),
    )
    write_jsonl(run_root / "media" / "media.jsonl", [media.model_dump(mode="json")])
    write_json(run_root / "manifest.json", {"status": "completed"})
    write_jsonl(
        run_root / "ocr" / "ocr.jsonl",
        [
            {
                "schema_version": "1.1.0",
                "preprocess_run_id": "api-text-run",
                "detection_id": "ocr:1",
                "video_id": "V1",
                "frame_id": 12,
                "timestamp_ms": 1200,
                "raw_text": "AIC 2026",
                "normalized_text": "aic 2026",
                "normalized_text_no_diacritics": "aic 2026",
                "punctuation_aware_text": "aic 2026",
                "character_ngrams": [],
                "bbox_xyxy_norm": [0.1, 0.1, 0.5, 0.2],
                "polygon_norm": None,
                "confidence": 0.95,
                "below_threshold": False,
                "crop_evidence_path": None,
                "crop_sha256": None,
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
                "schema_version": "1.1.0",
                "preprocess_run_id": "api-text-run",
                "segment_id": "asr:1",
                "video_id": "V1",
                "start_ms": 2000,
                "end_ms": 3000,
                "text": "AIC 2026",
                "normalized_text": "aic 2026",
                "normalized_text_no_diacritics": "aic 2026",
                "language": "vi",
                "language_probability": None,
                "confidence": 0.9,
                "avg_logprob": None,
                "no_speech_probability": None,
                "words": [],
                "vad_segment_id": None,
                "source_audio_sha256": None,
                "model_name": "fixture",
                "model_version": "1",
                "created_at_utc": utcnow_iso(),
            }
        ],
    )
    metadata = MetadataRecord(
        preprocess_run_id="api-text-run",
        metadata_id="metadata:1",
        video_id="V1",
        source="organizer_youtube",
        title="AIC 2026",
        text="AIC 2026",
        normalized_text="aic 2026",
        normalized_text_no_diacritics="aic 2026",
        created_at_utc=utcnow_iso(),
    )
    write_jsonl(
        run_root / "metadata" / "metadata.jsonl",
        [metadata.model_dump(mode="json")],
    )
    write_jsonl(
        run_root / "frames.jsonl",
        [
            {
                "preprocess_run_id": "api-text-run",
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

    settings = Settings()
    settings.paths.runs_root = runs_root
    settings.text_index.auto_build_if_missing = False
    config_path = tmp_path / "config.yaml"
    import yaml

    config_path.write_text(
        yaml.safe_dump(settings.model_dump(mode="json"), sort_keys=False),
        encoding="utf-8",
    )
    write_json(run_root / "config.snapshot.json", settings.model_dump(mode="json"))
    build_text_index("api-text-run", run_root, settings)

    request = {
        "query_id": "q1",
        "task": "KIS",
        "query_text": "AIC 2026",
        "limit": 10,
    }
    with TestClient(create_app("api-text-run", str(config_path))) as client:
        all_rows = client.post("/text/search", json=request)
        assert all_rows.status_code == 200
        assert {row["source"] for row in all_rows.json()} == {"ocr", "asr", "metadata"}
        ocr_rows = client.post("/ocr/search", json=request)
        assert ocr_rows.status_code == 200
        assert {row["source"] for row in ocr_rows.json()} == {"ocr"}

    # A new app instance loads the persisted index rather than fitting BM25 again.
    with TestClient(create_app("api-text-run", str(config_path))) as client:
        asr_rows = client.post("/asr/search", json=request)
        metadata_rows = client.post("/metadata/search", json=request)
        assert {row["source"] for row in asr_rows.json()} == {"asr"}
        assert {row["source"] for row in metadata_rows.json()} == {"metadata"}
        status = client.get("/text/index/status")
        assert status.status_code == 200
        assert status.json()["valid"] is True
        assert status.json()["manifest"]["document_count"] == 3
