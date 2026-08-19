"""Focused T016 regressions for the tracked WP11/TV4 VQA boundary."""
from __future__ import annotations

import inspect

from tv4.contracts import EvidencePack, SearchCandidate, SearchRequest
from tv4.fixtures import VQA_EMPTY_EVIDENCE_RESPONSE, VQA_RESPONSE, VQA_RETRY_EXHAUSTED_RESPONSE, vqa_fixture_response
from tv4.wp11_vqa import RuleBasedFallbackEngine, answer_query, build_evidence_pack


def _candidate() -> SearchCandidate:
    return SearchCandidate(
        query_id="t016-001", video_id="V001", frame_id=120, timestamp_ms=4800,
        source="fusion", rank=1, preprocess_run_id="run-t016", provenance_sources=("visual",),
    )


class _Frames:
    def frames(self, video_id: str):
        assert video_id == "V001"
        return [
            {"video_id": "V001", "frame_id": 116, "timestamp_ms": 4600, "keyframe_path": "frames/116.jpg", "preprocess_run_id": "run-t016"},
            {"video_id": "V001", "frame_id": 120, "timestamp_ms": 4800, "keyframe_path": "frames/120.jpg", "preprocess_run_id": "run-t016"},
            {"video_id": "V001", "frame_id": 127, "timestamp_ms": 5050, "keyframe_path": "frames/127.jpg", "preprocess_run_id": "run-t016"},
        ]


class _RichTV3:
    def __init__(self, *, malformed_ocr: bool = False, unavailable: bool = False):
        self.calls: list[tuple[str, SearchRequest]] = []
        self.malformed_ocr = malformed_ocr
        self.unavailable = unavailable

    def search(self, route: str, request: SearchRequest):
        self.calls.append((route, request))
        if self.unavailable:
            raise RuntimeError("WP04 unavailable")
        return []

    def get_ocr_detections(self, **kwargs):
        return [{"schema_version": "1.1.0", "preprocess_run_id": "run-ocr", "detection_id": "ocr-1", "video_id": "V001", "frame_id": 120, "timestamp_ms": 4800, "raw_text": "BLUE CUP", "normalized_text": "blue cup", "bbox_xyxy_norm": [0.8, 0.2, 0.1, 0.3] if self.malformed_ocr else [0.1, 0.2, 0.8, 0.3], "polygon_norm": [[0.1, 0.2], [0.8, 0.2], [0.8, 0.3]], "confidence": 0.91, "crop_evidence_path": "crops/ocr-1.jpg", "crop_sha256": "a" * 64, "source_keyframe_sha256": "b" * 64, "model_name": "ocr-model", "model_version": "1", "created_at_utc": "2026-01-01T00:00:00Z"}]

    def get_asr_segments(self, **kwargs):
        return [{"schema_version": "1.1.0", "preprocess_run_id": "run-asr", "segment_id": "asr-1", "video_id": "V001", "start_ms": 4500, "end_ms": 5100, "text": "the cup is blue", "normalized_text": "the cup is blue", "confidence": 0.8, "words": [{"word": "blue", "start_ms": 4900, "end_ms": 5000, "probability": 0.9}], "model_name": "asr-model", "model_version": "1", "created_at_utc": "2026-01-01T00:00:00Z"}]

    def get_asr_context(self, **kwargs):
        return [{"segment_id": "asr-before", "video_id": "V001", "start_ms": 4000, "end_ms": 4400, "text": "host asks a question"}]

    def get_object_detections(self, **kwargs):
        return [{"schema_version": "1.2.0", "preprocess_run_id": "run-object", "detection_id": "object-1", "video_id": "V001", "frame_id": 120, "timestamp_ms": 4800, "label": "cup", "canonical_label": "cup", "bbox_xyxy_norm": [0.5, 0.4, 0.8, 0.9], "confidence": 0.75, "source_keyframe_path": "frames/120.jpg", "source_keyframe_sha256": "c" * 64, "model_name": "object-model", "model_version": "2", "created_at_utc": "2026-01-01T00:00:00Z"}]

    def get_metadata_records(self, **kwargs):
        return [{"schema_version": "1.1.0", "preprocess_run_id": "run-meta", "metadata_id": "meta-1", "video_id": "V001", "source": "manifest", "title": "award", "tags": ["cup"], "window_start_ms": 4000, "window_end_ms": 5200, "source_record_sha256": "d" * 64, "created_at_utc": "2026-01-01T00:00:00Z"}]


class _AcceptingEngine:
    def answer(self, question: str, evidence: EvidencePack) -> str:
        assert evidence.question == question
        return "blue"

    def verify(self, question: str, answer: str, evidence: EvidencePack) -> bool:
        return bool(evidence.asr_evidence and answer == "blue" and question == evidence.question)


class _RejectingEngine(_AcceptingEngine):
    def __init__(self):
        self.calls = 0

    def answer(self, question: str, evidence: EvidencePack) -> str:
        self.calls += 1
        return "blue"

    def verify(self, question: str, answer: str, evidence: EvidencePack) -> bool:
        return False


class _BrokenEngine:
    def answer(self, question: str, evidence: EvidencePack) -> str:
        raise RuntimeError("VLM unavailable")

    def verify(self, question: str, answer: str, evidence: EvidencePack) -> bool:
        raise AssertionError("must not run")


class _VerifierBrokenEngine(_AcceptingEngine):
    def verify(self, question: str, answer: str, evidence: EvidencePack) -> bool:
        raise RuntimeError("verifier unavailable")


class _PartialTV3:
    def search(self, route: str, request: SearchRequest):
        if route == "ocr":
            return [SearchCandidate(query_id=request.query_id, video_id="V001", frame_id=120, timestamp_ms=4800, source="ocr", rank=1, provenance={"text": "BLUE CUP"})]
        return []


def _request() -> SearchRequest:
    return SearchRequest(query_id="t016-001", task="VQA", query_text="award ceremony with a blue cup", question="What color is the cup?", limit=20)


def test_rich_wp04_records_and_canonical_multiframe_provenance_round_trip():
    tv3 = _RichTV3()
    evidence = build_evidence_pack(_candidate(), _Frames(), tv3, request=_request())
    assert [route for route, _ in tv3.calls] == ["ocr", "asr", "object", "metadata"]
    assert all(call.query_text == _request().query_text and call.question == _request().question for _, call in tv3.calls)
    assert [frame.frame_id for frame in evidence.selected_frames] == [116, 120, 127]
    assert evidence.ocr_evidence[0].bbox_xyxy_norm == (0.1, 0.2, 0.8, 0.3)
    assert evidence.asr_evidence[0].start_ms == 4500 and evidence.asr_evidence[0].context[0]["segment_id"] == "asr-before"
    assert evidence.object_evidence[0].bbox_xyxy_norm == (0.5, 0.4, 0.8, 0.9)
    assert evidence.metadata_evidence[0].values["title"] == "award"
    assert evidence.ocr_evidence[0].source_record["model_name"] == "ocr-model"


def test_malformed_evidence_and_dependency_failures_fail_closed():
    malformed = answer_query(_candidate(), _request().question or "", _Frames(), _RichTV3(malformed_ocr=True), _AcceptingEngine(), request=_request())
    unavailable = answer_query(_candidate(), _request().question or "", _Frames(), _RichTV3(unavailable=True), _AcceptingEngine(), request=_request())
    broken = answer_query(_candidate(), _request().question or "", _Frames(), _RichTV3(), _BrokenEngine(), request=_request())
    verifier_broken = answer_query(_candidate(), _request().question or "", _Frames(), _RichTV3(), _VerifierBrokenEngine(), request=_request())
    assert (malformed.status, malformed.verified, malformed.manual_required) == ("degraded", False, True)
    assert (unavailable.status, unavailable.verified, unavailable.manual_required) == ("degraded", False, True)
    assert (broken.status, broken.verifier_status, broken.manual_required) == ("degraded", "reasoning_unavailable", True)
    assert (verifier_broken.status, verifier_broken.verifier_status, verifier_broken.verified) == ("degraded", "verifier_unavailable", False)


def test_partial_evidence_remains_explicit_and_advisory():
    result = answer_query(_candidate(), _request().question or "", _Frames(), _PartialTV3(), RuleBasedFallbackEngine(), request=_request())
    assert result.evidence.ocr_texts == ("BLUE CUP",)
    assert result.evidence.availability["asr"] == "empty"
    assert result.proposal == "BLUE CUP" and result.verified is False
    assert result.manual_required is True and result.approved is False


def test_proposal_is_advisory_and_rejection_gets_exactly_one_retry():
    approved = answer_query(_candidate(), _request().question or "", _Frames(), _RichTV3(), _AcceptingEngine(), request=_request())
    rejecting_engine = _RejectingEngine()
    exhausted = answer_query(_candidate(), _request().question or "", _Frames(), _RichTV3(), rejecting_engine, request=_request())
    assert approved.proposal == "blue" and approved.verified is True and approved.approved is False
    assert (exhausted.retry_count, rejecting_engine.calls, exhausted.manual_required, exhausted.status) == (1, 2, True, "manual_required")


def test_rule_fallback_and_fixture_never_auto_approve_or_select():
    evidence = EvidencePack(query_id="q", video_id="V001", frame_id=120, timestamp_ms=4800, keyframe_path=None, ocr_texts=("unrelated sign",))
    assert RuleBasedFallbackEngine().verify("What color is the cup?", "unrelated sign", evidence) is False
    assert VQA_RESPONSE["results"][0]["approved"] is False
    assert VQA_RESPONSE["results"][0]["evidence"]["selected_frames"][0]["submission_selectable"] is False
    assert vqa_fixture_response("qa-fixture-empty") == VQA_EMPTY_EVIDENCE_RESPONSE
    assert VQA_EMPTY_EVIDENCE_RESPONSE["results"][0]["verified"] is False
    assert vqa_fixture_response("qa-fixture-retry-exhausted") == VQA_RETRY_EXHAUSTED_RESPONSE
    assert VQA_RETRY_EXHAUSTED_RESPONSE["results"][0]["retry_count"] == 1


def test_no_local_frame_arithmetic_is_used_for_vqa_evidence_or_retry():
    source = inspect.getsource(build_evidence_pack) + inspect.getsource(answer_query)
    assert "candidate.frame_id +" not in source and "candidate.frame_id -" not in source
    assert "fps" not in source.casefold() and "pts" not in source.casefold()
