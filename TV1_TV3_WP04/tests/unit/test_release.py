from aic2026.release import audit_release

def test_release_detects_video(tmp_path):
    (tmp_path/'x.mp4').write_bytes(b'x')
    assert any(x['reason']=='forbidden_extension' for x in audit_release(tmp_path))


def test_release_detects_python_cache(tmp_path):
    cache = tmp_path / "src" / "__pycache__"
    cache.mkdir(parents=True)
    (cache / "module.cpython-313.pyc").write_bytes(b"cache")
    issues = audit_release(tmp_path)
    assert any(item["reason"] == "cache_artifact" for item in issues)
    assert any(item["reason"] == "forbidden_extension" for item in issues)
