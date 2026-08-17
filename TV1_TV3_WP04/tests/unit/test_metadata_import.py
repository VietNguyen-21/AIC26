from __future__ import annotations

import json
from pathlib import Path

import pytest

from aic2026.config import Settings
from aic2026.contracts import MediaRecord
from aic2026.metadata import (
    MetadataImportError,
    consolidate_metadata_artifacts,
    import_organizer_youtube_metadata,
    metadata_search,
    write_technical_metadata,
)
from aic2026.utils import utcnow_iso


def media_record(tmp_path: Path) -> MediaRecord:
    video = tmp_path / "L21_V001.mp4"
    video.write_bytes(b"fixture")
    return MediaRecord(
        preprocess_run_id="metadata-run",
        video_id="L21_V001",
        original_video_path=str(video),
        source_sha256="a" * 64,
        duration_ms=5000,
        width_px=320,
        height_px=180,
        has_audio=False,
        created_at_utc=utcnow_iso(),
    )


def test_organizer_metadata_import_preserves_technical_and_searches(tmp_path):
    media = [media_record(tmp_path)]
    source_root = tmp_path / "organizer"
    source_root.mkdir()
    (source_root / "youtube.json").write_text(
        json.dumps(
            [
                {
                    "video_id": "L21_V001",
                    "title": "Lễ hội áo dài Việt Nam",
                    "description": "Sự kiện tại Thành phố Hồ Chí Minh",
                    "tags": ["festival", "ao dai"],
                    "channel": "AIC Organizer",
                    "youtube_url": "https://www.youtube.com/watch?v=abcDEF12345",
                },
                {"video_id": "UNKNOWN", "title": "unmatched"},
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    settings = Settings()
    settings.metadata.organizer_metadata_root = source_root
    settings.metadata.organizer_metadata_globs = ["*.json"]
    run_root = tmp_path / "run"

    technical = write_technical_metadata(media, run_root)
    assert len(technical) == 1
    result = import_organizer_youtube_metadata(
        "metadata-run", run_root, media, settings.metadata
    )
    assert result.matched_rows == 1
    assert result.unmatched_rows == 1
    assert result.invalid_rows == 0
    combined = consolidate_metadata_artifacts(run_root)
    assert {str(item.source) for item in combined} == {"technical", "organizer_youtube"}
    organizer = next(item for item in combined if str(item.source) == "organizer_youtube")
    assert organizer.youtube_video_id == "abcDEF12345"
    assert organizer.matched_by == "video_id"

    # A representative frame is supplied, avoiding a misleading direct frame-0 claim.
    (run_root / "frames.jsonl").parent.mkdir(parents=True, exist_ok=True)
    (run_root / "frames.jsonl").write_text(
        json.dumps(
            {
                "preprocess_run_id": "metadata-run",
                "video_id": "L21_V001",
                "frame_id": 42,
                "keyframe_seq": 0,
                "timestamp_ms": 2100,
                "pts": 2100,
                "time_base": "1/1000",
                "decode_index": 42,
                "shot_id": "s0",
                "keyframe_path": "unused.jpg",
                "selection_reason": "max_gap",
                "created_at_utc": utcnow_iso(),
            },
            ensure_ascii=False,
        ) + "\n",
        encoding="utf-8",
    )
    results = metadata_search("q1", "le hoi ao dai", "metadata-run", run_root, 10)
    assert results
    assert results[0].frame_id == 42
    assert results[0].provenance["localization_required"] is True
    assert results[0].provenance["policy"] == "video_soft_boost_only"


def test_missing_organizer_metadata_is_optional(tmp_path):
    media = [media_record(tmp_path)]
    settings = Settings()
    settings.metadata.organizer_metadata_root = tmp_path / "missing"
    run_root = tmp_path / "run"
    write_technical_metadata(media, run_root)
    result = import_organizer_youtube_metadata(
        "metadata-run", run_root, media, settings.metadata
    )
    assert result.records == []
    assert result.matched_rows == 0
    report = json.loads((run_root / "reports" / "metadata_import.json").read_text())
    assert report["status"] == "missing_optional_source"


def _media_with_path(tmp_path: Path, video_id: str, relative_path: str, sha_char: str) -> MediaRecord:
    video = tmp_path / relative_path
    video.parent.mkdir(parents=True, exist_ok=True)
    video.write_bytes(video_id.encode("utf-8"))
    return MediaRecord(
        preprocess_run_id="metadata-run",
        video_id=video_id,
        original_video_path=str(video),
        source_sha256=sha_char * 64,
        duration_ms=5000,
        width_px=320,
        height_px=180,
        has_audio=False,
        created_at_utc=utcnow_iso(),
    )


def test_strict_unknown_video_fails_and_invalidates_stale_organizer_artifact(tmp_path):
    media = [media_record(tmp_path)]
    source_root = tmp_path / "organizer-strict"
    source_root.mkdir()
    (source_root / "youtube.json").write_text(
        json.dumps([{"video_id": "UNKNOWN", "title": "unknown"}]), encoding="utf-8"
    )
    settings = Settings()
    settings.metadata.organizer_metadata_root = source_root
    settings.metadata.organizer_metadata_globs = ["*.json"]
    settings.metadata.strict_unknown_video = True
    run_root = tmp_path / "run-strict"
    write_technical_metadata(media, run_root)
    stale = run_root / "metadata" / "organizer_youtube.jsonl"
    stale.parent.mkdir(parents=True, exist_ok=True)
    stale.write_text('{"metadata_id":"stale"}\n', encoding="utf-8")

    with pytest.raises(MetadataImportError, match="strict_unknown_video"):
        import_organizer_youtube_metadata("metadata-run", run_root, media, settings.metadata)

    report = json.loads((run_root / "reports" / "metadata_import.json").read_text())
    assert report["status"] == "failed"
    assert report["unmatched_rows"] == 1
    assert report["ambiguous_rows"] == 0
    assert not stale.exists()
    combined = consolidate_metadata_artifacts(run_root)
    assert {str(item.source) for item in combined} == {"technical"}


def test_ambiguous_filename_alias_is_reported_not_guessed(tmp_path):
    media = [
        _media_with_path(tmp_path, "V_A", "batch_a/shared.mp4", "a"),
        _media_with_path(tmp_path, "V_B", "batch_b/shared.mp4", "b"),
    ]
    source_root = tmp_path / "organizer-ambiguous"
    source_root.mkdir()
    (source_root / "youtube.json").write_text(
        json.dumps([{"filename": "shared.mp4", "title": "ambiguous"}]), encoding="utf-8"
    )
    settings = Settings()
    settings.metadata.organizer_metadata_root = source_root
    settings.metadata.organizer_metadata_globs = ["*.json"]
    run_root = tmp_path / "run-ambiguous"

    result = import_organizer_youtube_metadata("metadata-run", run_root, media, settings.metadata)
    assert result.records == []
    assert result.unmatched_rows == 0
    assert result.ambiguous_rows == 1
    assert sorted(result.ambiguous_examples[0]["matches"][0]["candidate_video_ids"]) == ["V_A", "V_B"]
    report = json.loads((run_root / "reports" / "metadata_import.json").read_text())
    assert report["ambiguous_rows"] == 1


def test_duplicate_organizer_rows_are_deduplicated_by_source_hash(tmp_path):
    media = [media_record(tmp_path)]
    source_root = tmp_path / "organizer-duplicate"
    source_root.mkdir()
    row = {"video_id": "L21_V001", "title": "Same title", "tags": ["aic"]}
    (source_root / "youtube-a.json").write_text(json.dumps([row]), encoding="utf-8")
    (source_root / "youtube-b.json").write_text(json.dumps([row]), encoding="utf-8")
    settings = Settings()
    settings.metadata.organizer_metadata_root = source_root
    settings.metadata.organizer_metadata_globs = ["*.json"]
    run_root = tmp_path / "run-duplicate"

    result = import_organizer_youtube_metadata("metadata-run", run_root, media, settings.metadata)
    assert result.matched_rows == 1
    assert result.duplicate_rows == 1
    assert len(result.records) == 1
    assert result.records[0].source_record_sha256
    combined = consolidate_metadata_artifacts(run_root)
    organizer = [item for item in combined if str(item.source) == "organizer_youtube"]
    assert len(organizer) == 1
    report = json.loads((run_root / "reports" / "metadata_import.json").read_text())
    assert report["duplicate_rows"] == 1
    assert report["record_count"] == 1


def test_ambiguous_filename_can_be_resolved_by_unique_checksum(tmp_path):
    media = [
        _media_with_path(tmp_path, "V_A", "batch_a/shared.mp4", "a"),
        _media_with_path(tmp_path, "V_B", "batch_b/shared.mp4", "b"),
    ]
    source_root = tmp_path / "organizer-checksum"
    source_root.mkdir()
    (source_root / "youtube.json").write_text(
        json.dumps(
            [
                {
                    "filename": "shared.mp4",
                    "sha256": "a" * 64,
                    "title": "resolved by checksum",
                }
            ]
        ),
        encoding="utf-8",
    )
    settings = Settings()
    settings.metadata.organizer_metadata_root = source_root
    settings.metadata.organizer_metadata_globs = ["*.json"]
    result = import_organizer_youtube_metadata(
        "metadata-run", tmp_path / "run-checksum", media, settings.metadata
    )
    assert result.ambiguous_rows == 0
    assert result.matched_rows == 1
    assert result.records[0].video_id == "V_A"
    assert result.records[0].matched_by == "sha256"


def test_strict_unknown_video_rejects_ambiguous_alias(tmp_path):
    media = [
        _media_with_path(tmp_path, "V_A", "batch_a/shared.mp4", "a"),
        _media_with_path(tmp_path, "V_B", "batch_b/shared.mp4", "b"),
    ]
    source_root = tmp_path / "organizer-strict-ambiguous"
    source_root.mkdir()
    (source_root / "youtube.json").write_text(
        json.dumps([{"filename": "shared.mp4", "title": "ambiguous"}]), encoding="utf-8"
    )
    settings = Settings()
    settings.metadata.organizer_metadata_root = source_root
    settings.metadata.organizer_metadata_globs = ["*.json"]
    settings.metadata.strict_unknown_video = True
    run_root = tmp_path / "run-strict-ambiguous"
    with pytest.raises(MetadataImportError, match="ambiguous_rows=1"):
        import_organizer_youtube_metadata("metadata-run", run_root, media, settings.metadata)
    report = json.loads((run_root / "reports" / "metadata_import.json").read_text())
    assert report["status"] == "failed"
    assert report["ambiguous_rows"] == 1
