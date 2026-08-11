from __future__ import annotations

import io
from pathlib import Path

import pytest
from openpyxl import Workbook

from aic2026 import batch_manifest


def _xlsx(path: Path, rows: list[list[object]]) -> Path:
    workbook = Workbook()
    sheet = workbook.active
    for row in rows:
        sheet.append(row)
    workbook.save(path)
    return path


def test_read_first_sheet_and_manifest_entries(tmp_path: Path):
    path = _xlsx(
        tmp_path / "manifest.xlsx",
        [
            ["Tên file", "Đường dẫn", "Batch"],
            ["Videos_A.mp4", "https://example.test/a", 1],
            ["", "", 2],
            ["Videos_B.mp4", "", 3],
        ],
    )
    rows = batch_manifest.read_first_sheet(path)
    assert rows[0][:2] == ["Tên file", "Đường dẫn"]
    entries = batch_manifest.manifest_entries(path)
    assert [entry["filename"] for entry in entries] == ["Videos_A.mp4", "Videos_B.mp4"]
    assert entries[0]["url"] == "https://example.test/a"
    assert entries[0]["batch"] == "1"


def test_manifest_entries_empty_sheet(tmp_path: Path):
    assert batch_manifest.manifest_entries(_xlsx(tmp_path / "empty.xlsx", [])) == []


class _Response:
    def __init__(self, payload: bytes):
        self._stream = io.BytesIO(payload)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self, size: int = -1) -> bytes:
        return self._stream.read(size)


def test_download_entries_success_skip_and_existing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    existing = tmp_path / "Videos_existing.mp4"
    existing.write_bytes(b"old")
    calls: list[str] = []

    def fake_urlopen(request, timeout):
        calls.append(request.full_url)
        assert timeout == 120
        return _Response(b"new-video")

    monkeypatch.setattr(batch_manifest.urllib.request, "urlopen", fake_urlopen)
    rows = batch_manifest.download_entries(
        [
            {"filename": "ignore.mp4", "url": "https://example.test/ignore"},
            {"filename": "Videos_missing-url.mp4", "url": ""},
            {"filename": existing.name, "url": "https://example.test/existing"},
            {"filename": "Videos_new.mp4", "url": "https://example.test/new"},
        ],
        tmp_path,
    )
    assert rows == [existing, tmp_path / "Videos_new.mp4"]
    assert (tmp_path / "Videos_new.mp4").read_bytes() == b"new-video"
    assert calls == ["https://example.test/new"]
    assert not (tmp_path / "Videos_new.mp4.part").exists()


def test_download_entries_retries_and_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    attempts = []
    sleeps = []

    def fail(*args, **kwargs):
        attempts.append(1)
        raise OSError("network down")

    monkeypatch.setattr(batch_manifest.urllib.request, "urlopen", fail)
    monkeypatch.setattr(batch_manifest.time, "sleep", sleeps.append)
    with pytest.raises(RuntimeError, match="Failed to download Videos_bad.mp4"):
        batch_manifest.download_entries(
            [{"filename": "Videos_bad.mp4", "url": "https://example.test/bad"}],
            tmp_path,
            retries=3,
        )
    assert len(attempts) == 3
    assert sleeps == [1, 2, 4]
