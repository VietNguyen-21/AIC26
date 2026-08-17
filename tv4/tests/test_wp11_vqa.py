"""Regression test for the manual_fallback gate fix in wp11_vqa.py (bug #3).

The old gate only flagged manual review when the answer was unverified AND
no evidence existed at all. That meant an unverified answer *contradicting*
real evidence — the highest-risk hallucination case — went straight to
submission with manual_review=False. This test locks in the fix: gating is
on verification alone.
"""
from __future__ import annotations

from tv4.contracts import EvidencePack, SearchCandidate
from tv4 import wp11_vqa
from tv4.wp11_vqa import answer_query


def _candidate() -> SearchCandidate:
    return SearchCandidate(
        query_id="q1", video_id="L01_V001", frame_id=10, timestamp_ms=5000,
        source="fusion", rank=1,
    )


class _FixedEvidenceEngine:
    """AnswerEngine stub with a controllable verified/unverified answer."""

    def __init__(self, verified: bool):
        self._verified = verified

    def answer(self, question, evidence):
        return "42"

    def verify(self, question, answer, evidence):
        return self._verified


def _run(monkeypatch, *, verified: bool, has_evidence: bool) -> wp11_vqa.VqaResult:
    evidence = EvidencePack(
        query_id="q1", video_id="L01_V001", frame_id=10, timestamp_ms=5000,
        keyframe_path=None,
        ocr_texts=("some ocr text",) if has_evidence else (),
    )
    monkeypatch.setattr(wp11_vqa, "build_evidence_pack", lambda *a, **k: evidence)
    engine = _FixedEvidenceEngine(verified=verified)
    return answer_query(_candidate(), "how many?", tv1=None, tv3=None, engine=engine)


def test_unverified_with_contradicting_evidence_is_flagged(monkeypatch):
    """This is the case the old gate missed: unverified answer, but real
    evidence exists (and presumably contradicts it) — must go to review."""
    result = _run(monkeypatch, verified=False, has_evidence=True)
    assert result.manual_fallback is True


def test_unverified_with_no_evidence_is_flagged(monkeypatch):
    result = _run(monkeypatch, verified=False, has_evidence=False)
    assert result.manual_fallback is True


def test_verified_answer_is_not_flagged_regardless_of_evidence(monkeypatch):
    result = _run(monkeypatch, verified=True, has_evidence=False)
    assert result.manual_fallback is False
