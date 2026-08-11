import zipfile
import pytest
from aic2026.ingest import safe_extract_zip


def test_zip_path_traversal(tmp_path):
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("../evil.txt", "x")
    with pytest.raises(ValueError):
        safe_extract_zip(archive, tmp_path / "out")
