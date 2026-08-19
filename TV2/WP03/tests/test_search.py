from __future__ import annotations

from pathlib import Path, PurePosixPath
import json

import numpy as np
import pytest

from wp03.corpus import load_corpus
from wp03.contracts import ContractError, SearchRequest
from wp03.orchestrator import BuildRequest, build_model_artifacts
from wp03.search import search_image, search_visual, search_visual_batch
from tests.conftest import write_jsonl
from tests.test_corpus import record


class FakeEncoder:
    def encode_images(self, image_paths: tuple[Path, ...]) -> np.ndarray:
        return np.array([[1.0, 0.0] if path.name == "000003.jpg" else [0.0, 1.0] for path in image_paths], dtype=np.float32)

    def encode_text(self, texts: tuple[str, ...]) -> np.ndarray:
        return np.array([[0.0, 1.0] for _ in texts], dtype=np.float32)


def test_search_returns_one_visual_response(data_root: Path) -> None:
    write_jsonl(data_root / "frames.jsonl", [record(3, "keyframes/L21_V001/000003.jpg"), record(42, "keyframes/L21_V001/000042.jpg")])
    corpus = load_corpus(data_root, PurePosixPath("frames.jsonl"), None)
    artifact_root = data_root / "artifacts"
    encoder = FakeEncoder()
    build_model_artifacts(BuildRequest("run", "fake", "rev", data_root, artifact_root, corpus, 2), encoder)

    response = search_visual(
        query_id="q-1",
        query_text="blue scene",
        event_index=None,
        artifact_root=artifact_root,
        encoders={"fake": encoder},
        requested_top_k=1,
        candidate_k_per_model=1,
        hard_candidate_cap=None,
    )

    assert response.degraded is False
    assert response.candidates[0].frame_id == 42
    assert response.candidates[0].source == "visual"


def test_search_consumes_pipeline_search_request(data_root: Path) -> None:
    write_jsonl(data_root / "frames.jsonl", [record(3, "keyframes/L21_V001/000003.jpg")])
    corpus = load_corpus(data_root, PurePosixPath("frames.jsonl"), None)
    artifact_root = data_root / "artifacts"
    encoder = FakeEncoder()
    build_model_artifacts(BuildRequest("run", "fake", "rev", data_root, artifact_root, corpus, 1), encoder)
    request = SearchRequest(
        query_id="q-1", task="KIS", query_text="blue scene", question=None,
        events=(), filters={}, limit=1, language="vi", session_id=None,
    )

    response = search_visual(
        request=request, artifact_root=artifact_root, encoders={"fake": encoder},
        candidate_k_per_model=1, hard_candidate_cap=None,
    )

    assert response.query_id == "q-1"
    assert response.requested_top_k == 1


def test_image_search_returns_the_same_visual_candidate_contract(data_root: Path) -> None:
    write_jsonl(data_root / "frames.jsonl", [record(3, "keyframes/L21_V001/000003.jpg")])
    corpus = load_corpus(data_root, PurePosixPath("frames.jsonl"), None)
    artifact_root = data_root / "artifacts"
    encoder = FakeEncoder()
    build_model_artifacts(BuildRequest("run", "fake", "rev", data_root, artifact_root, corpus, 1), encoder)
    request = SearchRequest(
        query_id="q-image", task="KIS", query_text="reference", question=None,
        events=(), filters={}, limit=1, language=None, session_id=None,
    )

    response = search_image(
        request=request, image_paths=(data_root / "keyframes/L21_V001/000003.jpg",), artifact_root=artifact_root,
        encoders={"fake": encoder}, candidate_k_per_model=1, hard_candidate_cap=None,
    )

    assert response.candidates[0].source == "visual"
    assert response.candidates[0].frame_id == 3


def test_search_excludes_model_with_incompatible_text_encoder(data_root: Path) -> None:
    write_jsonl(data_root / "frames.jsonl", [record(3, "keyframes/L21_V001/000003.jpg")])
    corpus = load_corpus(data_root, PurePosixPath("frames.jsonl"), None)
    artifact_root = data_root / "artifacts"
    build_model_artifacts(
        BuildRequest("run", "fake", "rev", data_root, artifact_root, corpus, 1, "expected"), FakeEncoder()
    )

    class WrongEncoder(FakeEncoder):
        def compatibility_fingerprint(self) -> str:
            return "wrong"

    with pytest.raises(ContractError, match="no usable visual model"):
        search_visual(
            query_id="q-1", query_text="scene", event_index=None, artifact_root=artifact_root,
            encoders={"fake": WrongEncoder()}, requested_top_k=1, candidate_k_per_model=1, hard_candidate_cap=None,
        )


def test_cpu_fixture_search_uses_four_models_and_one_visual_list(data_root: Path) -> None:
    write_jsonl(data_root / "frames.jsonl", [record(3, "keyframes/L21_V001/000003.jpg")])
    corpus = load_corpus(data_root, PurePosixPath("frames.jsonl"), None)
    artifact_root = data_root / "artifacts"
    encoders = {model: FakeEncoder() for model in ("beit3", "bge_vl", "metaclip2", "perception")}
    for model_key, encoder in encoders.items():
        build_model_artifacts(BuildRequest("run", model_key, f"{model_key}-rev", data_root, artifact_root, corpus, 1), encoder)

    response = search_visual(
        query_id="q-1", query_text="intersection", event_index=None, artifact_root=artifact_root,
        encoders=encoders, requested_top_k=3, candidate_k_per_model=20, hard_candidate_cap=None,
    )

    assert response.degraded is False
    assert response.models_used == ("beit3", "bge_vl", "metaclip2", "perception")
    assert {candidate.source for candidate in response.candidates} == {"visual"}


def test_search_rejects_manifest_with_invalid_mapping_digest(data_root: Path) -> None:
    write_jsonl(data_root / "frames.jsonl", [record(3, "keyframes/L21_V001/000003.jpg")])
    corpus = load_corpus(data_root, PurePosixPath("frames.jsonl"), None)
    artifact_root = data_root / "artifacts"
    encoder = FakeEncoder()
    build_model_artifacts(BuildRequest("run", "fake", "rev", data_root, artifact_root, corpus, 1), encoder)
    manifest_path = artifact_root / "manifests" / "fake.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["mapping_sha256"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ContractError, match="mapping digest"):
        search_visual(
            query_id="q", query_text="scene", event_index=None, artifact_root=artifact_root,
            encoders={"fake": encoder}, requested_top_k=1, candidate_k_per_model=1, hard_candidate_cap=None,
        )


def test_search_uses_configured_rrf_constant(data_root: Path) -> None:
    write_jsonl(data_root / "frames.jsonl", [record(3, "keyframes/L21_V001/000003.jpg")])
    corpus = load_corpus(data_root, PurePosixPath("frames.jsonl"), None)
    artifact_root = data_root / "artifacts"
    encoder = FakeEncoder()
    build_model_artifacts(BuildRequest("run", "fake", "rev", data_root, artifact_root, corpus, 1), encoder)

    response = search_visual(
        query_id="q", query_text="scene", event_index=None, artifact_root=artifact_root,
        encoders={"fake": encoder}, requested_top_k=1, candidate_k_per_model=1,
        hard_candidate_cap=None, rrf_k=10, dedup_window_ms=None,
    )

    assert response.candidates[0].score == pytest.approx(1 / 11)


def test_search_visual_batch_matches_single_search(data_root: Path) -> None:
    write_jsonl(data_root / "frames.jsonl", [record(3, "keyframes/L21_V001/000003.jpg"), record(42, "keyframes/L21_V001/000042.jpg")])
    corpus = load_corpus(data_root, PurePosixPath("frames.jsonl"), None)
    artifact_root = data_root / "artifacts"
    encoder = FakeEncoder()
    build_model_artifacts(BuildRequest("run", "fake", "rev", data_root, artifact_root, corpus, 2), encoder)

    req1 = SearchRequest(
        query_id="q-whole", task="TRAKE", query_text="whole action sequence", question=None,
        events=(), filters={}, limit=2, language="vi", session_id=None,
    )
    req2 = SearchRequest(
        query_id="q-ev0", task="TRAKE", query_text="event one jump", question=None,
        events=(), filters={}, limit=2, language="vi", session_id=None, event_index=0,
    )
    req3 = SearchRequest(
        query_id="q-ev1", task="TRAKE", query_text="event two land", question=None,
        events=(), filters={}, limit=2, language="vi", session_id=None, event_index=1,
    )

    batch_responses = search_visual_batch(
        [req1, req2, req3],
        artifact_root=artifact_root,
        encoders={"fake": encoder},
        candidate_k_per_model=2,
        hard_candidate_cap=None,
        rrf_k=60,
    )

    assert len(batch_responses) == 3
    single_resp1 = search_visual(
        request=req1, artifact_root=artifact_root, encoders={"fake": encoder},
        candidate_k_per_model=2, hard_candidate_cap=None, rrf_k=60,
    )
    assert batch_responses[0].candidates[0].frame_id == single_resp1.candidates[0].frame_id
    assert batch_responses[0].candidates[0].score == single_resp1.candidates[0].score
    assert batch_responses[1].query_id == "q-ev0"
    assert batch_responses[1].candidates[0].event_index == 0
    assert batch_responses[2].query_id == "q-ev1"
    assert batch_responses[2].candidates[0].event_index == 1
