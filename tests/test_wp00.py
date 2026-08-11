"""
Tests for WP00 — Data Intake & Corpus Manifest
"""
from __future__ import annotations

import json
import hashlib
import zipfile
import pytest
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from wp00_data_intake import DataIntake


# ── Helpers ──

def _create_dummy_mp4(path: Path, content: bytes = b"fake_mp4_data_12345") -> None:
    """Create a minimal dummy .mp4 file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def _create_test_zip(zip_path: Path, files: dict[str, bytes]) -> None:
    """Create a ZIP archive with given files."""
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ── Test SHA-256 ──

class TestSHA256:
    def test_sha256_deterministic(self, tmp_path):
        f = tmp_path / "test.mp4"
        f.write_bytes(b"hello world")
        intake = DataIntake(tmp_path, tmp_path / "raw", tmp_path / "run")
        h1 = intake._sha256(f)
        h2 = intake._sha256(f)
        assert h1 == h2
        assert len(h1) == 64

    def test_sha256_matches_hashlib(self, tmp_path):
        content = b"test content for sha256"
        f = tmp_path / "test.mp4"
        f.write_bytes(content)
        intake = DataIntake(tmp_path, tmp_path / "raw", tmp_path / "run")
        result = intake._sha256(f)
        expected = _sha256(content)
        assert result == expected


# ── Test ZIP Extraction ──

class TestExtraction:
    def test_extract_zip_safe(self, tmp_path):
        zip_dir = tmp_path / "archives"
        raw_dir = tmp_path / "raw"
        run_dir = tmp_path / "run"
        _create_test_zip(zip_dir / "test.zip", {
            "video1.mp4": b"video1_data",
            "subdir/video2.mp4": b"video2_data",
        })
        intake = DataIntake(zip_dir, raw_dir, run_dir)
        files, membership = intake.extract_all()
        assert len(files) >= 1
        # At least one MP4 should be extracted
        assert any(f.suffix == ".mp4" for f in files)

    def test_zipslip_blocked(self, tmp_path):
        zip_dir = tmp_path / "archives"
        raw_dir = tmp_path / "raw"
        run_dir = tmp_path / "run"
        _create_test_zip(zip_dir / "evil.zip", {
            "../../../evil.mp4": b"evil_data",
        })
        intake = DataIntake(zip_dir, raw_dir, run_dir)
        files, membership = intake.extract_all()
        # Evil file should NOT be extracted outside raw_dir
        evil_path = tmp_path / "evil.mp4"
        assert not evil_path.exists()

    def test_skip_junk_files(self, tmp_path):
        zip_dir = tmp_path / "archives"
        raw_dir = tmp_path / "raw"
        run_dir = tmp_path / "run"
        _create_test_zip(zip_dir / "test.zip", {
            "video.mp4": b"video_data",
            "__MACOSX/video.mp4": b"junk",
            ".DS_Store": b"junk",
            "readme.txt": b"text",
        })
        intake = DataIntake(zip_dir, raw_dir, run_dir)
        files, _ = intake.extract_all()
        names = [f.name for f in files]
        assert ".DS_Store" not in names
        assert "readme.txt" not in names

    def test_idempotent_extraction(self, tmp_path):
        zip_dir = tmp_path / "archives"
        raw_dir = tmp_path / "raw"
        run_dir = tmp_path / "run"
        _create_test_zip(zip_dir / "test.zip", {"video.mp4": b"data"})
        intake = DataIntake(zip_dir, raw_dir, run_dir)
        files1, _ = intake.extract_all()
        files2, _ = intake.extract_all()
        assert len(files1) == len(files2)


# ── Test Duplicate Detection ──

class TestDuplicateDetection:
    def test_detect_duplicates(self, tmp_path):
        zip_dir = tmp_path / "archives"
        raw_dir = tmp_path / "raw"
        run_dir = tmp_path / "run"
        same_content = b"identical_video_content"
        _create_test_zip(zip_dir / "a.zip", {"v1.mp4": same_content})
        _create_test_zip(zip_dir / "b.zip", {"v2.mp4": same_content})
        intake = DataIntake(zip_dir, raw_dir, run_dir)
        files, _ = intake.extract_all()
        checksums = intake.compute_checksums(files)
        duplicates = intake.detect_duplicates(checksums)
        assert len(duplicates) >= 1

    def test_no_duplicates_different_content(self, tmp_path):
        zip_dir = tmp_path / "archives"
        raw_dir = tmp_path / "raw"
        run_dir = tmp_path / "run"
        _create_test_zip(zip_dir / "a.zip", {"v1.mp4": b"content_A"})
        _create_test_zip(zip_dir / "b.zip", {"v2.mp4": b"content_B"})
        intake = DataIntake(zip_dir, raw_dir, run_dir)
        files, _ = intake.extract_all()
        checksums = intake.compute_checksums(files)
        duplicates = intake.detect_duplicates(checksums)
        assert len(duplicates) == 0


# ── Test Output Files ──

class TestOutputFiles:
    def test_all_four_outputs(self, tmp_path):
        zip_dir = tmp_path / "archives"
        raw_dir = tmp_path / "raw"
        run_dir = tmp_path / "run"
        _create_test_zip(zip_dir / "test.zip", {
            "v1.mp4": b"video_1",
            "v2.mp4": b"video_2",
        })
        intake = DataIntake(zip_dir, raw_dir, run_dir)
        intake.run()
        
        manifest_dir = run_dir / "manifest"
        assert (manifest_dir / "corpus_manifest.parquet").exists()
        assert (manifest_dir / "corpus_manifest.json").exists()
        assert (run_dir / "duplicate_videos.jsonl").exists()
        assert (run_dir / "rejected_files.jsonl").exists()


# ── Test Schema ──

class TestSchema:
    def test_manifest_schema_fields(self, tmp_path):
        zip_dir = tmp_path / "archives"
        raw_dir = tmp_path / "raw"
        run_dir = tmp_path / "run"
        _create_test_zip(zip_dir / "test.zip", {"video.mp4": b"data"})
        intake = DataIntake(zip_dir, raw_dir, run_dir)
        df = intake.run()
        
        required_fields = [
            "schema_version", "video_id", "source_archive",
            "original_video_path", "source_sha256", "file_size_bytes",
            "batch_id", "duplicate_of_video_id", "ingest_status",
            "created_at_utc"
        ]
        for field in required_fields:
            assert field in df.columns, f"Missing field: {field}"

    def test_ingest_status_values(self, tmp_path):
        zip_dir = tmp_path / "archives"
        raw_dir = tmp_path / "raw"
        run_dir = tmp_path / "run"
        same = b"same_content"
        _create_test_zip(zip_dir / "a.zip", {"v1.mp4": same})
        _create_test_zip(zip_dir / "b.zip", {"v2.mp4": same})
        intake = DataIntake(zip_dir, raw_dir, run_dir)
        df = intake.run()
        
        statuses = set(df["ingest_status"].values)
        assert statuses.issubset({"accepted", "duplicate", "rejected"})
        assert "accepted" in statuses or "duplicate" in statuses

    def test_video_id_no_extension(self, tmp_path):
        zip_dir = tmp_path / "archives"
        raw_dir = tmp_path / "raw"
        run_dir = tmp_path / "run"
        _create_test_zip(zip_dir / "test.zip", {"my_video.mp4": b"data"})
        intake = DataIntake(zip_dir, raw_dir, run_dir)
        df = intake.run()
        
        for vid in df["video_id"]:
            assert not vid.endswith(".mp4"), f"video_id should not have .mp4: {vid}"
