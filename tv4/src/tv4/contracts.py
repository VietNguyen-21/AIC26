"""TV4 shared data contracts.

Deliberately mirrors the SearchRequest / SearchCandidate contract already
defined by TV1/TV3 (see TV1_TV3_WP04/src/aic2026/contracts.py) and by TV2's
WP03 (see WP03/src/wp03/contracts.py) so JSON produced by any of the three
upstream services can be loaded here without translation, and so TV4's own
output can be consumed by TV5 unchanged.

Only the standard library is used here on purpose: TV4 must be importable
even in a bare CPU environment before any heavy retrieval dependency is
installed.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Literal, Mapping, Sequence

Task = Literal["KIS", "VQA", "TRAKE"]
Source = Literal["visual", "ocr", "asr", "metadata", "object", "feedback", "fusion"]


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class ContractError(ValueError):
    """Raised when a payload does not satisfy the TV4 contract."""


@dataclass(frozen=True)
class SearchRequest:
    query_id: str
    task: Task
    query_text: str | None = None
    question: str | None = None
    events: Sequence[str] = field(default_factory=tuple)
    filters: Mapping[str, Any] = field(default_factory=dict)
    limit: int = 100
    language: str | None = "vi"
    session_id: str | None = None
    event_index: int | None = None

    def __post_init__(self) -> None:
        if not self.query_id:
            raise ContractError("query_id is required")
        if self.task not in ("KIS", "VQA", "TRAKE"):
            raise ContractError("task must be KIS, VQA or TRAKE")
        if not (1 <= self.limit <= 100):
            raise ContractError("limit must be in [1, 100]")

    def to_json(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0.0",
            "query_id": self.query_id,
            "task": self.task,
            "query_text": self.query_text,
            "question": self.question,
            "events": list(self.events),
            "filters": dict(self.filters),
            "limit": self.limit,
            "language": self.language,
            "session_id": self.session_id,
            "event_index": self.event_index,
        }


@dataclass(frozen=True)
class SearchCandidate:
    query_id: str
    video_id: str
    frame_id: int
    timestamp_ms: int
    source: Source
    rank: int
    schema_version: str = "1.0.0"
    event_index: int | None = None
    representative_frame_id: int | None = None
    window_start_ms: int | None = None
    window_end_ms: int | None = None
    raw_score: float | None = None
    score: float | None = None
    model_scores: Mapping[str, float] = field(default_factory=dict)
    model_ranks: Mapping[str, int] = field(default_factory=dict)
    matched_filters: Sequence[str] = field(default_factory=tuple)
    evidence_refs: Sequence[str] = field(default_factory=tuple)
    provenance_sources: Sequence[str] = field(default_factory=tuple)
    provenance: Mapping[str, Any] = field(default_factory=dict)
    confidence: float | None = None
    preprocess_run_id: str = "unknown"
    created_at_utc: str = field(default_factory=now_utc)

    @classmethod
    def from_json(cls, payload: Mapping[str, Any]) -> "SearchCandidate":
        known = {f: payload[f] for f in _CANDIDATE_FIELDS if f in payload}
        return cls(**known)

    def to_json(self) -> dict[str, Any]:
        d = asdict(self)
        return d


_CANDIDATE_FIELDS = {
    "query_id", "video_id", "frame_id", "timestamp_ms", "source", "rank",
    "schema_version", "event_index", "representative_frame_id",
    "window_start_ms", "window_end_ms", "raw_score", "score",
    "model_scores", "model_ranks", "matched_filters", "evidence_refs",
    "provenance_sources", "provenance", "confidence", "preprocess_run_id",
    "created_at_utc",
}


@dataclass(frozen=True)
class EvidencePack:
    """Bundled evidence handed to the VQA answerer / verifier (WP11)."""

    query_id: str
    video_id: str
    frame_id: int
    timestamp_ms: int
    keyframe_path: str | None
    ocr_texts: Sequence[str] = field(default_factory=tuple)
    asr_texts: Sequence[str] = field(default_factory=tuple)
    object_labels: Sequence[str] = field(default_factory=tuple)
    neighbor_frame_ids: Sequence[int] = field(default_factory=tuple)
    provenance: Mapping[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TrakeEvent:
    event_index: int
    text: str


@dataclass(frozen=True)
class TrakeHypothesis:
    query_id: str
    video_id: str
    frame_ids: Sequence[int]
    event_scores: Sequence[float]
    aggregate_score: float
    preprocess_run_id: str
