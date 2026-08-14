import os

os.environ["TV4_FIXTURE_MODE"] = "1"

from fastapi.testclient import TestClient

from tv4.api import app

client = TestClient(app)


def test_health_fixture_mode():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["mode"] == "fixture"


def test_kis_search_shape():
    resp = client.post("/kis/search", json={"query_text": "một diễn giả mặc áo đỏ"})
    assert resp.status_code == 200
    body = resp.json()
    assert "query_id" in body and "candidates" in body
    first = body["candidates"][0]
    for field in ("video_id", "frame_id", "timestamp_ms", "rank", "score", "provenance_sources"):
        assert field in first


def test_vqa_answer_shape():
    resp = client.post("/vqa/answer", json={"query_text": "video lễ trao giải", "question": "màu ly?"})
    assert resp.status_code == 200
    body = resp.json()
    first = body["results"][0]
    for field in ("video_id", "frame_id", "answer", "verified", "manual_review", "evidence"):
        assert field in first


def test_trake_align_shape():
    resp = client.post("/trake/align", json={"query_text": "giậm nhảy; bay qua xà; tiếp đất; đứng dậy"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["result"]["video_id"]
    assert len(body["result"]["frame_ids"]) == 4


def test_request_validation_rejects_bad_strategy():
    resp = client.post("/trake/align", json={"query_text": "x", "strategy": "not-a-real-strategy"})
    assert resp.status_code == 422


def test_live_mode_missing_config_returns_clean_500(monkeypatch):
    """Outside fixture mode, a broken/missing config must surface as a clear
    500 with a message pointing at the config path, not a raw traceback."""
    import tv4.api as api_module

    monkeypatch.setattr(api_module, "FIXTURE_MODE", False)
    monkeypatch.setattr(api_module, "CONFIG_PATH", "configs/does-not-exist.yaml")
    monkeypatch.setattr(api_module, "_services", None)

    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "degraded"
    assert "does-not-exist.yaml" in body["error"]

    resp = client.post("/kis/search", json={"query_text": "x"})
    assert resp.status_code == 500
    assert "does-not-exist.yaml" in resp.json()["detail"]