from pathlib import Path
from zipfile import ZipFile, ZipInfo

import pytest

from aic2026.ingest import IngestSecurityError, ingest


def test_same_stem_in_different_folders_gets_distinct_ids(tmp_path: Path):
    source = tmp_path / "source"
    (source / "a").mkdir(parents=True)
    (source / "b").mkdir()
    (source / "a" / "video.mp4").write_bytes(b"a")
    (source / "b" / "video.mp4").write_bytes(b"b")
    rows = ingest(source, tmp_path / "run", video_id_rule="relative_path_hash")
    accepted = [r for r in rows if r.ingest_status == "accepted"]
    assert len(accepted) == 2
    assert len({r.video_id for r in accepted}) == 2


def test_archive_member_limit_is_enforced(tmp_path: Path):
    archive = tmp_path / "many.zip"
    with ZipFile(archive, "w") as z:
        z.writestr("a.mp4", b"a")
        z.writestr("b.mp4", b"b")
    with pytest.raises(IngestSecurityError):
        ingest(archive, tmp_path / "run", workspace=tmp_path / "extract", max_archive_members=1)


def test_archive_symlink_is_rejected(tmp_path: Path):
    archive = tmp_path / "link.zip"
    info = ZipInfo("link.mp4")
    info.create_system = 3
    info.external_attr = 0o120777 << 16
    with ZipFile(archive, "w") as z:
        z.writestr(info, b"target")
    with pytest.raises(IngestSecurityError):
        ingest(archive, tmp_path / "run", workspace=tmp_path / "extract")
