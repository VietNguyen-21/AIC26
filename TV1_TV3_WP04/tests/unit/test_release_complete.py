from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from aic2026.release import audit_release, package_release


def _reasons(root: Path) -> set[str]:
    return {issue["reason"] for issue in audit_release(root)}


def test_release_audit_detects_archive_secret_absolute_and_large_file(tmp_path: Path):
    (tmp_path / "nested.zip").write_bytes(b"zip")
    (tmp_path / "secret.txt").write_text("api_key=" + ("a" * 16), encoding="utf-8")
    (tmp_path / "path.md").write_text("machine path /" + "home/student/project", encoding="utf-8")
    large = tmp_path / "large.bin"
    with large.open("wb") as handle:
        handle.truncate(51 * 1024 * 1024)

    reasons = _reasons(tmp_path)
    assert {"archive_inside_release", "possible_secret", "absolute_path", "large_file"} <= reasons


def test_release_audit_ignores_reference_absolute_paths_and_detects_symlink(tmp_path: Path):
    reference = tmp_path / "docs" / "reference"
    reference.mkdir(parents=True)
    (reference / "source.md").write_text("/mnt/" + "data/example", encoding="utf-8")
    target = tmp_path / "target.txt"
    target.write_text("ok", encoding="utf-8")
    link = tmp_path / "link.txt"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symlinks unavailable")
    issues = audit_release(tmp_path)
    assert not any(item["path"].endswith("source.md") for item in issues)
    assert any(item["reason"] == "symlink" for item in issues)


def test_package_release_clean_tree_and_rejects_dirty_tree(tmp_path: Path):
    root = tmp_path / "clean_release"
    (root / "src").mkdir(parents=True)
    (root / "src" / "app.py").write_text("print('ok')\n", encoding="utf-8")
    output = tmp_path / "dist" / "release.zip"
    assert package_release(root, output) == output
    with zipfile.ZipFile(output) as archive:
        assert archive.namelist() == ["clean_release/src/app.py"]

    (root / "model.pt").write_bytes(b"weights")
    with pytest.raises(RuntimeError, match="Release audit failed"):
        package_release(root, tmp_path / "dist" / "bad.zip")


def test_release_audit_detects_generic_machine_absolute_paths(tmp_path: Path):
    slash = chr(92)
    (tmp_path / "windows.yaml").write_text(
        "checkpoint: " + "D:" + slash + "Models" + slash + "checkpoint.pth\n",
        encoding="utf-8",
    )
    (tmp_path / "wsl.md").write_text(
        "workspace: /" + "mnt/d/private/workspace\n",
        encoding="utf-8",
    )
    issues = audit_release(tmp_path)
    flagged = {item["path"] for item in issues if item["reason"] == "absolute_path"}
    assert {"windows.yaml", "wsl.md"} <= flagged
