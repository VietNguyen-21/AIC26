from __future__ import annotations

from pathlib import Path

import pytest

from aic2026.evidence_catalog import (
    EvidenceCatalog,
    EvidenceCatalogError,
    build_evidence_catalog,
    validate_evidence_catalog,
)
from aic2026.utils import utcnow_iso, write_jsonl


def _records(run_root: Path) -> None:
    write_jsonl(
        run_root / "ocr" / "ocr.jsonl",
        [
            {
                "preprocess_run_id": "run",
                "detection_id": f"ocr:{index}",
                "video_id": "V1",
                "frame_id": index,
                "timestamp_ms": index * 100,
                "raw_text": f"Text {index}",
                "normalized_text": f"text {index}",
                "normalized_text_no_diacritics": f"text {index}",
                "punctuation_aware_text": f"text {index}",
                "character_ngrams": [],
                "bbox_xyxy_norm": [0.1, 0.1, 0.2, 0.2],
                "model_name": "fixture",
                "model_version": "1",
                "created_at_utc": utcnow_iso(),
            }
            for index in range(3)
        ],
    )
    write_jsonl(
        run_root / "asr" / "asr.jsonl",
        [
            {
                "preprocess_run_id": "run",
                "segment_id": f"asr:{index}",
                "video_id": "V1",
                "start_ms": index * 1000,
                "end_ms": index * 1000 + 800,
                "text": f"speech {index}",
                "words": [],
                "created_at_utc": utcnow_iso(),
            }
            for index in range(3)
        ],
    )
    write_jsonl(
        run_root / "objects" / "objects.jsonl",
        [
            {
                "preprocess_run_id": "run",
                "detection_id": "obj:car",
                "video_id": "V1",
                "frame_id": 1,
                "timestamp_ms": 100,
                "label": "car",
                "canonical_label": "car",
                "label_aliases": ["ô tô", "oto"],
                "bbox_xyxy_norm": [0.1, 0.1, 0.5, 0.5],
                "center_xy_norm": [0.3, 0.3],
                "spatial_region": "top_left",
                "confidence": 0.9,
                "model_name": "fixture",
                "model_version": "1",
                "created_at_utc": utcnow_iso(),
            },
            {
                "preprocess_run_id": "run",
                "detection_id": "obj:person",
                "video_id": "V1",
                "frame_id": 2,
                "timestamp_ms": 200,
                "label": "person",
                "canonical_label": "person",
                "label_aliases": ["người"],
                "bbox_xyxy_norm": [0.5, 0.5, 0.9, 0.9],
                "center_xy_norm": [0.7, 0.7],
                "spatial_region": "bottom_right",
                "confidence": 0.2,
                "below_threshold": True,
                "model_name": "fixture",
                "model_version": "1",
                "created_at_utc": utcnow_iso(),
            },
        ],
    )
    write_jsonl(
        run_root / "metadata" / "metadata.jsonl",
        [
            {
                "preprocess_run_id": "run",
                "metadata_id": "meta:1",
                "video_id": "V1",
                "source": "technical",
                "tags": [],
                "raw_fields": {},
                "created_at_utc": utcnow_iso(),
            }
        ],
    )


def test_catalog_build_reuse_pagination_and_indexed_access(tmp_path: Path):
    run_root = tmp_path / "run"
    _records(run_root)
    first = build_evidence_catalog(run_root)
    assert first.reused is False
    assert first.counts == {"ocr": 3, "asr": 3, "object": 2, "metadata": 1}
    assert validate_evidence_catalog(run_root)["status"] == "ready"

    second = build_evidence_catalog(run_root)
    assert second.reused is True

    catalog = EvidenceCatalog(run_root, maximum_page_size=2)
    page1 = catalog.list_ocr(limit=2)
    assert [row["detection_id"] for row in page1.rows] == ["ocr:0", "ocr:1"]
    assert page1.next_cursor is not None
    page2 = catalog.list_ocr(limit=2, cursor=page1.next_cursor)
    assert [row["detection_id"] for row in page2.rows] == ["ocr:2"]
    assert catalog.get_ocr("ocr:1")["frame_id"] == 1

    asr = catalog.list_asr(video_id="V1", start_ms=900, end_ms=1900, limit=2)
    assert [row["segment_id"] for row in asr.rows] == ["asr:1"]
    context = catalog.get_asr_context("asr:1", 500)
    assert context and context["target_segment_id"] == "asr:1"

    objects = catalog.list_objects(label="ô tô", include_below_threshold=False, limit=2)
    assert [row["detection_id"] for row in objects.rows] == ["obj:car"]
    assert {row.canonical_label for row in catalog.representative_object_vocabulary()} == {
        "car",
        "person",
    }
    assert [row.detection_id for row in catalog.object_rows_for_labels(["car"])] == [
        "obj:car"
    ]
    metadata = catalog.list_metadata(source="technical", limit=2)
    assert metadata.rows[0]["metadata_id"] == "meta:1"


def test_catalog_rejects_stale_sources_invalid_cursor_and_limit(tmp_path: Path):
    run_root = tmp_path / "run"
    _records(run_root)
    build_evidence_catalog(run_root)
    catalog = EvidenceCatalog(run_root, maximum_page_size=2)
    with pytest.raises(EvidenceCatalogError, match="limit"):
        catalog.list_ocr(limit=3)
    with pytest.raises(EvidenceCatalogError, match="cursor"):
        catalog.list_ocr(limit=1, cursor="bad")

    with (run_root / "ocr" / "ocr.jsonl").open("a", encoding="utf-8") as handle:
        handle.write("\n")
    with pytest.raises(EvidenceCatalogError, match="stale"):
        validate_evidence_catalog(run_root)


def test_catalog_detects_database_corruption_and_missing_artifacts(tmp_path: Path):
    run_root = tmp_path / "run"
    _records(run_root)
    result = build_evidence_catalog(run_root)
    result.database_path.write_bytes(b"corrupt")
    with pytest.raises(EvidenceCatalogError, match="checksum"):
        validate_evidence_catalog(run_root)

    empty = tmp_path / "empty"
    with pytest.raises(EvidenceCatalogError, match="manifest"):
        validate_evidence_catalog(empty)
