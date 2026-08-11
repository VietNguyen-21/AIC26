from __future__ import annotations

import json
from pathlib import Path

import pytest

from aic2026.config import Settings
from aic2026.contracts import ASRSegment, MetadataRecord, OCRDetection
from aic2026.text_index import (
    TextIndexValidationError,
    build_text_index,
    invalidate_text_index_cache,
    search_text_index,
    validate_text_index_artifacts,
)
from aic2026.utils import utcnow_iso, write_jsonl


def _settings(tmp_path: Path) -> Settings:
    settings = Settings()
    settings.paths.runs_root = tmp_path / "runs"
    settings.text_index.auto_build_if_missing = False
    settings.text_index.adapter = "local_bm25"
    return settings


def _prepare_run(tmp_path: Path) -> tuple[Path, Settings]:
    settings = _settings(tmp_path)
    run_root = Path(settings.paths.runs_root) / "text-run"
    run_root.mkdir(parents=True)

    ocr_rows = [
        OCRDetection(
            preprocess_run_id="text-run",
            detection_id="ocr:exact",
            video_id="V1",
            frame_id=10,
            timestamp_ms=1000,
            raw_text="Đại học Kinh tế Thành phố Hồ Chí Minh",
            normalized_text="đại học kinh tế thành phố hồ chí minh",
            normalized_text_no_diacritics="dai hoc kinh te thanh pho ho chi minh",
            punctuation_aware_text="đại học kinh tế thành phố hồ chí minh",
            character_ngrams=[],
            bbox_xyxy_norm=(0.1, 0.1, 0.8, 0.2),
            confidence=0.95,
            model_name="fixture",
            model_version="1",
            created_at_utc=utcnow_iso(),
        ),
        OCRDetection(
            preprocess_run_id="text-run",
            detection_id="ocr:shuffled",
            video_id="V2",
            frame_id=20,
            timestamp_ms=2000,
            raw_text="Thành phố kinh tế đại học Hồ Chí Minh",
            normalized_text="thành phố kinh tế đại học hồ chí minh",
            normalized_text_no_diacritics="thanh pho kinh te dai hoc ho chi minh",
            punctuation_aware_text="thành phố kinh tế đại học hồ chí minh",
            character_ngrams=[],
            bbox_xyxy_norm=(0.1, 0.2, 0.8, 0.3),
            confidence=0.9,
            model_name="fixture",
            model_version="1",
            created_at_utc=utcnow_iso(),
        ),
    ]
    write_jsonl(
        run_root / "ocr" / "ocr.jsonl",
        [row.model_dump(mode="json") for row in ocr_rows],
    )

    asr_rows = [
        ASRSegment(
            preprocess_run_id="text-run",
            segment_id="asr:program",
            video_id="V3",
            start_ms=3000,
            end_ms=4500,
            text="Chương trình học bổng quốc tế",
            normalized_text="chương trình học bổng quốc tế",
            normalized_text_no_diacritics="chuong trinh hoc bong quoc te",
            language="vi",
            model_name="fixture",
            model_version="1",
            created_at_utc=utcnow_iso(),
        )
    ]
    write_jsonl(
        run_root / "asr" / "asr.jsonl",
        [row.model_dump(mode="json") for row in asr_rows],
    )

    metadata_rows = [
        MetadataRecord(
            preprocess_run_id="text-run",
            metadata_id="meta:title",
            video_id="V4",
            source="organizer_youtube",
            title="Lễ hội áo dài Việt Nam",
            description="Sự kiện văn hóa",
            tags=["áo dài", "festival"],
            channel="AIC Organizer",
            text="Lễ hội áo dài Việt Nam Sự kiện văn hóa áo dài festival",
            normalized_text="lễ hội áo dài việt nam sự kiện văn hóa áo dài festival",
            normalized_text_no_diacritics="le hoi ao dai viet nam su kien van hoa ao dai festival",
            created_at_utc=utcnow_iso(),
        ),
        MetadataRecord(
            preprocess_run_id="text-run",
            metadata_id="meta:description",
            video_id="V5",
            source="organizer_youtube",
            title="Bản tin thường ngày",
            description="Có nhắc thoáng qua lễ hội áo dài",
            tags=[],
            channel="AIC Organizer",
            text="Bản tin thường ngày Có nhắc thoáng qua lễ hội áo dài",
            normalized_text="bản tin thường ngày có nhắc thoáng qua lễ hội áo dài",
            normalized_text_no_diacritics="ban tin thuong ngay co nhac thoang qua le hoi ao dai",
            created_at_utc=utcnow_iso(),
        ),
    ]
    write_jsonl(
        run_root / "metadata" / "metadata.jsonl",
        [row.model_dump(mode="json") for row in metadata_rows],
    )
    write_jsonl(
        run_root / "frames.jsonl",
        [
            {
                "preprocess_run_id": "text-run",
                "video_id": video_id,
                "frame_id": frame_id,
                "keyframe_seq": 0,
                "timestamp_ms": timestamp_ms,
                "pts": timestamp_ms,
                "time_base": "1/1000",
                "decode_index": frame_id,
                "shot_id": "s0",
                "keyframe_path": "unused.jpg",
                "selection_reason": "max_gap",
                "created_at_utc": utcnow_iso(),
            }
            for video_id, frame_id, timestamp_ms in [
                ("V1", 10, 1000),
                ("V2", 20, 2000),
                ("V3", 30, 3750),
                ("V4", 40, 4000),
                ("V5", 50, 5000),
            ]
        ],
    )
    return run_root, settings


def test_persistent_field_aware_search_modes(tmp_path: Path):
    run_root, settings = _prepare_run(tmp_path)
    built = build_text_index("text-run", run_root, settings)
    assert built.reused is False
    assert built.manifest.document_count == 5
    assert built.manifest.source_counts == {"asr": 1, "metadata": 2, "ocr": 2}

    phrase = search_text_index(
        "q1",
        '"đại học kinh tế thành phố hồ chí minh"',
        "text-run",
        run_root,
        10,
        settings=settings,
        source_filter={"ocr"},
    )
    assert phrase[0].evidence_refs == ["ocr:exact"]
    assert "exact_phrase" in phrase[0].provenance["match_modes"]

    no_diacritics = search_text_index(
        "q2",
        "le hoi ao dai",
        "text-run",
        run_root,
        10,
        settings=settings,
        source_filter={"metadata"},
    )
    assert no_diacritics[0].evidence_refs == ["meta:title"]
    assert no_diacritics[0].source == "metadata"
    assert no_diacritics[0].provenance["submittable"] is False
    assert "character_ngram" not in no_diacritics[0].provenance["match_modes"]

    fuzzy = search_text_index(
        "q3",
        "chuoong trinh",
        "text-run",
        run_root,
        10,
        settings=settings,
        source_filter={"asr"},
    )
    assert fuzzy
    assert fuzzy[0].evidence_refs == ["asr:program"]
    assert "fuzzy" in fuzzy[0].provenance["match_modes"]
    assert fuzzy[0].window_start_ms == 3000
    assert fuzzy[0].window_end_ms == 4500

    character = search_text_index(
        "q4",
        "kinhte thanhphoo",
        "text-run",
        run_root,
        10,
        settings=settings,
        source_filter={"ocr"},
    )
    assert character
    assert "character_ngram" in character[0].provenance["match_modes"]


def test_persistence_does_not_fit_again_per_query(tmp_path: Path, monkeypatch):
    run_root, settings = _prepare_run(tmp_path)
    result = build_text_index("text-run", run_root, settings)
    database = run_root / result.manifest.index_path
    mtime_before = database.stat().st_mtime_ns

    from aic2026 import text_index as module

    def forbidden_build(*args, **kwargs):
        raise AssertionError("query path must not rebuild or fit the BM25 index")

    monkeypatch.setattr(module.LocalPersistentBM25, "build", forbidden_build)
    invalidate_text_index_cache(run_root)
    first = search_text_index(
        "q1", "le hoi ao dai", "text-run", run_root, 10, settings=settings
    )
    invalidate_text_index_cache(run_root)
    second = search_text_index(
        "q2", "le hoi ao dai", "text-run", run_root, 10, settings=settings
    )
    assert [item.evidence_refs for item in first] == [item.evidence_refs for item in second]
    assert database.stat().st_mtime_ns == mtime_before


def test_manifest_detects_stale_or_corrupt_artifacts(tmp_path: Path):
    run_root, settings = _prepare_run(tmp_path)
    result = build_text_index("text-run", run_root, settings)
    validate_text_index_artifacts(run_root, settings)

    documents_path = run_root / result.manifest.documents_path
    documents_path.write_text(documents_path.read_text(encoding="utf-8") + "{}\n", encoding="utf-8")
    with pytest.raises(TextIndexValidationError, match="checksum mismatch"):
        validate_text_index_artifacts(run_root, settings)


def test_opensearch_request_falls_back_to_persistent_local(tmp_path: Path):
    run_root, settings = _prepare_run(tmp_path)
    settings.text_index.adapter = "opensearch"
    settings.text_index.allow_local_fallback = True
    result = build_text_index("text-run", run_root, settings)
    assert result.requested_adapter == "opensearch"
    assert result.selected_adapter == "local_bm25"
    assert result.degraded_reason
    results = search_text_index(
        "q", "le hoi ao dai", "text-run", run_root, 10, settings=settings
    )
    assert results
