from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from aic2026.config import Settings
from aic2026.contracts import ASRSegment, MetadataRecord, SearchCandidate, TextIndexManifest
from aic2026.text_index import (
    DegradedRemoteFallbackAdapter,
    FallbackTextIndexAdapter,
    LocalPersistentBM25,
    REMOTE_FIELD_MAPPING_VERSION,
    RemoteTextIndexAdapter,
    TextDocument,
    TextIndexValidationError,
    TextSearchHit,
    _expected_remote_state,
    build_text_index,
    text_hits_to_candidates,
)
from aic2026.utils import utcnow_iso, write_jsonl


def _settings(tmp_path: Path) -> Settings:
    settings = Settings()
    settings.paths.runs_root = tmp_path / "runs"
    settings.text_index.auto_build_if_missing = False
    settings.text_index.adapter = "local_bm25"
    return settings


def _minimal_run(tmp_path: Path) -> tuple[Path, Settings]:
    settings = _settings(tmp_path)
    run_root = Path(settings.paths.runs_root) / "round13-1"
    run_root.mkdir(parents=True)
    write_jsonl(
        run_root / "asr" / "asr.jsonl",
        [
            ASRSegment(
                preprocess_run_id="round13-1",
                segment_id="asr:1",
                video_id="V1",
                start_ms=1000,
                end_ms=2000,
                text="Chương trình học bổng quốc tế",
                normalized_text="chương trình học bổng quốc tế",
                normalized_text_no_diacritics="chuong trinh hoc bong quoc te",
                model_name="fixture",
                model_version="1",
                created_at_utc=utcnow_iso(),
            ).model_dump(mode="json")
        ],
    )
    metadata_rows = [
        MetadataRecord(
            preprocess_run_id="round13-1",
            metadata_id="meta:1",
            video_id="V2",
            source="organizer_youtube",
            title="Lễ hội áo dài Việt Nam",
            description="Sự kiện văn hóa",
            text="Lễ hội áo dài Việt Nam Sự kiện văn hóa",
            normalized_text="lễ hội áo dài việt nam sự kiện văn hóa",
            normalized_text_no_diacritics="le hoi ao dai viet nam su kien van hoa",
            created_at_utc=utcnow_iso(),
        ),
        MetadataRecord(
            preprocess_run_id="round13-1",
            metadata_id="meta:substring",
            video_id="V3",
            source="organizer_youtube",
            title="kinhte hocbong",
            text="kinhte hocbong",
            normalized_text="kinhte hocbong",
            normalized_text_no_diacritics="kinhte hocbong",
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
                "video_id": "V1",
                "frame_id": 10,
                "timestamp_ms": 1500,
            },
            {
                "video_id": "V2",
                "frame_id": 20,
                "timestamp_ms": 2500,
            },
            {
                "video_id": "V2",
                "frame_id": 22,
                "timestamp_ms": 3500,
            },
            {
                "video_id": "V3",
                "frame_id": 30,
                "timestamp_ms": 4500,
            },
        ],
    )
    return run_root, settings


def _manifest() -> TextIndexManifest:
    return TextIndexManifest(
        preprocess_run_id="round13-1",
        requested_adapter="local_bm25",
        selected_adapter="local_bm25",
        index_name="test",
        backend_version="sqlite-bm25-v3",
        document_count=1,
        build_fingerprint="a" * 64,
        documents_path="text_index/documents.jsonl",
        documents_sha256="b" * 64,
        index_path="text_index/local.sqlite3",
        index_sha256="c" * 64,
        created_at_utc=utcnow_iso(),
    )


def test_sqlite_internal_document_count_and_sql_vocabulary(tmp_path: Path):
    run_root, settings = _minimal_run(tmp_path)
    result = build_text_index("round13-1", run_root, settings)
    database = run_root / result.manifest.index_path
    with closing(sqlite3.connect(database)) as connection:
        document_count = int(connection.execute("SELECT COUNT(*) FROM documents").fetchone()[0])
        internal = int(
            json.loads(
                connection.execute(
                    "SELECT value FROM index_metadata WHERE key='document_count'"
                ).fetchone()[0]
            )
        )
        aggregation = json.loads(
            connection.execute(
                "SELECT value FROM index_metadata WHERE key='vocabulary_aggregation'"
            ).fetchone()[0]
        )
        mismatch_count = int(
            connection.execute(
                """
                SELECT COUNT(*)
                FROM (
                    SELECT p.field, p.term, COUNT(*) AS expected_df, v.df AS actual_df
                    FROM postings p
                    JOIN vocabulary v ON v.field=p.field AND v.term=p.term
                    GROUP BY p.field, p.term
                    HAVING expected_df != actual_df
                )
                """
            ).fetchone()[0]
        )
    assert document_count == result.manifest.document_count == 3
    assert internal == document_count
    assert aggregation == "sqlite_group_by"
    assert mismatch_count == 0


def test_exact_phrase_uses_token_boundaries(tmp_path: Path):
    run_root, settings = _minimal_run(tmp_path)
    result = build_text_index("round13-1", run_root, settings)
    local = LocalPersistentBM25(run_root / result.manifest.index_path, settings.text_index)
    hits = local.search('"kinh"', 10, source_filter={"metadata"})
    substring = next(hit for hit in hits if hit.document.doc_id == "meta:substring")
    assert "exact_phrase" not in substring.match_modes


@dataclass
class _Frame:
    frame_id: int
    timestamp_ms: int


class _FakeTemporalRegistry:
    def __init__(self):
        self.frames_by_video = {
            "V1": [_Frame(10, 1500)],
            "V2": [_Frame(20, 2500), _Frame(22, 3500)],
        }

    def canonicalize_candidate(self, candidate: SearchCandidate) -> SearchCandidate:
        return candidate.model_copy(
            update={
                "frame_id": 10,
                "representative_frame_id": 10,
                "timestamp_ms": 1500,
            }
        )


def test_temporal_registry_loaded_once_for_whole_query(tmp_path: Path, monkeypatch):
    run_root, _ = _minimal_run(tmp_path)
    calls = {"count": 0}

    def fake_load(_root):
        calls["count"] += 1
        return _FakeTemporalRegistry()

    from aic2026 import temporal

    monkeypatch.setattr(temporal.TemporalRegistry, "from_run_root", fake_load)
    hits = [
        TextSearchHit(
            score=2.0,
            document=TextDocument(
                doc_id=f"asr:{index}",
                text="aic",
                source="asr",
                fields={"asr_text": "aic"},
                metadata={
                    "source": "asr",
                    "video_id": "V1",
                    "start_ms": 1000 + index,
                    "end_ms": 2000 + index,
                },
            ),
        )
        for index in range(3)
    ]
    results = text_hits_to_candidates(
        "q", "round13-1", run_root, hits, adapter_name="local_bm25", manifest=_manifest()
    )
    assert calls["count"] == 1
    assert all(item.provenance["submittable"] is True for item in results)


def test_metadata_representative_map_reads_frames_once(tmp_path: Path, monkeypatch):
    run_root, _ = _minimal_run(tmp_path)

    from aic2026 import temporal
    from aic2026 import text_index as module

    monkeypatch.setattr(
        temporal.TemporalRegistry,
        "from_run_root",
        lambda _root: (_ for _ in ()).throw(FileNotFoundError("no registry")),
    )
    original = module.read_jsonl
    calls: list[Path] = []

    def counted(path):
        calls.append(Path(path))
        return original(path)

    monkeypatch.setattr(module, "read_jsonl", counted)
    hits = [
        TextSearchHit(
            score=1.0,
            document=TextDocument(
                doc_id=f"meta:{index}",
                text="aic",
                source="metadata",
                fields={"organizer_metadata_text": "aic"},
                metadata={"source": "metadata", "video_id": "V2"},
            ),
        )
        for index in range(5)
    ]
    results = text_hits_to_candidates(
        "q", "round13-1", run_root, hits, adapter_name="local_bm25", manifest=_manifest()
    )
    assert len(calls) == 1
    assert calls[0].name == "frames.jsonl"
    assert {item.frame_id for item in results} == {22}


def test_unresolved_asr_candidate_is_not_submittable(tmp_path: Path, monkeypatch):
    run_root, _ = _minimal_run(tmp_path)
    from aic2026 import temporal

    monkeypatch.setattr(
        temporal.TemporalRegistry,
        "from_run_root",
        lambda _root: (_ for _ in ()).throw(FileNotFoundError("no registry")),
    )
    hit = TextSearchHit(
        score=1.0,
        document=TextDocument(
            doc_id="asr:unresolved",
            text="aic",
            source="asr",
            fields={"asr_text": "aic"},
            metadata={
                "source": "asr",
                "video_id": "V1",
                "start_ms": 1000,
                "end_ms": 2000,
            },
        ),
    )
    candidate = text_hits_to_candidates(
        "q", "round13-1", run_root, [hit], adapter_name="local_bm25", manifest=_manifest()
    )[0]
    assert candidate.frame_id == 0
    assert candidate.representative_frame_id is None
    assert candidate.provenance["submittable"] is False
    assert candidate.provenance["localization_required"] is True
    assert candidate.provenance["frame_resolution"] == "pending_temporal_registry"


class _FakeIndices:
    def __init__(self, index_name: str, remote_state: dict[str, Any]):
        self.index_name = index_name
        self.remote_state = remote_state

    def exists(self, *, index: str) -> bool:
        return index == self.index_name

    def get_mapping(self, *, index: str) -> dict[str, Any]:
        return {
            index: {
                "mappings": {
                    "_meta": {"aic2026_text_index": dict(self.remote_state)}
                }
            }
        }


class _FakeValidationClient:
    def __init__(self, index_name: str, remote_state: dict[str, Any], count: int):
        self.indices = _FakeIndices(index_name, remote_state)
        self._count = count

    def count(self, *, index: str) -> dict[str, int]:
        return {"count": self._count}


def _remote_without_connection(
    settings: Settings, state: dict[str, Any], count: int
) -> RemoteTextIndexAdapter:
    adapter = object.__new__(RemoteTextIndexAdapter)
    adapter.name = "opensearch"
    adapter.index_name = "aic2026-test"
    adapter.config = settings.text_index
    adapter.expected_state = dict(state)
    adapter.client = _FakeValidationClient(adapter.index_name, state, count)
    adapter.bulk_helper = None
    return adapter


def test_remote_fingerprint_and_count_validation(tmp_path: Path):
    settings = _settings(tmp_path)
    state = _expected_remote_state(
        run_id="run",
        build_fingerprint="a" * 64,
        document_count=3,
        documents_sha256="b" * 64,
    )
    assert state["field_mapping_version"] == REMOTE_FIELD_MAPPING_VERSION
    adapter = _remote_without_connection(settings, state, 3)
    assert adapter.validate()["documents"] == 3

    stale = dict(state)
    stale["build_fingerprint"] = "c" * 64
    adapter.client = _FakeValidationClient(adapter.index_name, stale, 3)
    with pytest.raises(TextIndexValidationError, match="build_fingerprint mismatch"):
        adapter.validate()

    adapter.client = _FakeValidationClient(adapter.index_name, state, 2)
    with pytest.raises(TextIndexValidationError, match="document count mismatch"):
        adapter.validate()


class _FailingPrimary:
    name = "opensearch"
    version = "test"

    def search(self, query: str, k: int = 100, *, source_filter=None):
        raise TimeoutError("remote timeout")

    def validate(self):
        raise TimeoutError("remote timeout")

    def stats(self):
        return self.validate()

    def build(self, documents):
        raise TimeoutError("remote timeout")


class _OneHitFallback:
    name = "local_bm25"
    version = "test"

    def search(self, query: str, k: int = 100, *, source_filter=None):
        return [
            TextSearchHit(
                score=1.0,
                document=TextDocument(
                    doc_id="meta:1",
                    text="aic",
                    source="metadata",
                    fields={"metadata_text": "aic"},
                    metadata={"source": "metadata", "video_id": "V2"},
                ),
                requested_backend=self.name,
                actual_backend=self.name,
            )
        ]

    def validate(self):
        return {"documents": 1}

    def stats(self):
        return self.validate()

    def build(self, documents):
        return None


def test_fallback_provenance_reports_actual_backend(tmp_path: Path):
    run_root, _ = _minimal_run(tmp_path)
    adapter = FallbackTextIndexAdapter(_FailingPrimary(), _OneHitFallback())
    hits = adapter.search("aic")
    candidate = text_hits_to_candidates(
        "q", "round13-1", run_root, hits, adapter_name=adapter.name, manifest=_manifest()
    )[0]
    assert candidate.provenance["text_index_requested_adapter"] == "opensearch"
    assert candidate.provenance["text_index_actual_adapter"] == "local_bm25"
    assert candidate.provenance["text_index_adapter"] == "local_bm25"
    assert candidate.provenance["text_index_fallback_used"] is True
    assert "remote timeout" in candidate.provenance["text_index_fallback_reason"]


class _EmulatedRemoteClient:
    """Remote contract harness backed by the exact local ranked list.

    This is deterministic and dependency-free; live-cluster validation remains a
    deployment check, while this test locks request/result parity in CI.
    """

    def __init__(self, local: LocalPersistentBM25):
        self.local = local
        self.last_body: dict[str, Any] | None = None

    def search(self, *, index: str, body: dict[str, Any]) -> dict[str, Any]:
        self.last_body = body
        should = body["query"]["bool"]["should"]
        query = ""
        for clause in should:
            if "multi_match" in clause:
                query = str(clause["multi_match"]["query"])
                if clause["multi_match"].get("_name") == "bm25":
                    break
        local_hits = self.local.search(query, int(body["size"]))
        return {
            "hits": {
                "hits": [
                    {
                        "_id": hit.document.doc_id,
                        "_score": hit.score,
                        "matched_queries": hit.match_modes,
                        "_source": {
                            "doc_id": hit.document.doc_id,
                            "source": hit.document.source,
                            "text": hit.document.text,
                            "fields": {
                                key: (
                                    value.split("\u241f")
                                    if key.endswith("char_ngrams")
                                    else value
                                )
                                for key, value in hit.document.fields.items()
                            },
                            "metadata_json": json.dumps(
                                hit.document.metadata, ensure_ascii=False, sort_keys=True
                            ),
                        },
                    }
                    for hit in local_hits
                ]
            }
        }


def test_local_remote_contract_parity_for_all_text_modes(tmp_path: Path):
    run_root, settings = _minimal_run(tmp_path)
    result = build_text_index("round13-1", run_root, settings)
    local = LocalPersistentBM25(run_root / result.manifest.index_path, settings.text_index)

    remote = object.__new__(RemoteTextIndexAdapter)
    remote.name = "opensearch"
    remote.index_name = "emulated"
    remote.config = settings.text_index
    remote.expected_state = {}
    remote.client = _EmulatedRemoteClient(local)
    remote.bulk_helper = None

    queries = {
        "phrase": '"lễ hội áo dài"',
        "fuzzy": "chuoong trinh",
        "no_diacritic": "le hoi ao dai",
        "character_ngram": "kinhte hocbongg",
    }
    for query in queries.values():
        local_ids = [hit.document.doc_id for hit in local.search(query, 10)]
        remote_ids = [hit.document.doc_id for hit in remote.search(query, 10)]
        assert remote_ids == local_ids

    assert remote.client.last_body is not None
    names = []
    for clause in remote.client.last_body["query"]["bool"]["should"]:
        if "multi_match" in clause:
            names.append(clause["multi_match"].get("_name"))
        elif "bool" in clause:
            names.append(clause["bool"].get("_name"))
    assert {"bm25", "no_diacritic", "exact_phrase", "fuzzy", "character_ngram"}.issubset(
        set(names)
    )


def test_degraded_adapter_marks_local_as_actual_backend():
    adapter = DegradedRemoteFallbackAdapter(
        "elasticsearch", _OneHitFallback(), "stale remote fingerprint"
    )
    hit = adapter.search("aic")[0]
    assert hit.requested_backend == "elasticsearch"
    assert hit.actual_backend == "local_bm25"
    assert hit.fallback_used is True
    assert hit.fallback_reason == "stale remote fingerprint"
