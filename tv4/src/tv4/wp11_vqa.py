"""WP11 retrieval-grounded VQA evidence and advisory-answer boundary.

TV4 consumes WP04 evidence through its public search and catalogue APIs. It
does not manufacture canonical frame identities, re-run preprocessing, or
promote an answer suggestion to an operator-approved answer.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping, Protocol, Sequence

from .clients.tv1_client import TV1Client
from .clients.tv3_client import TV3Client
from .contracts import (
    AsrEvidence, CanonicalFrameReference, ContractError, EvidencePack,
    MetadataEvidence, ObjectEvidence, OcrEvidence, SearchCandidate,
    SearchRequest,
)


class AnswerEngine(Protocol):
    def answer(self, question: str, evidence: EvidencePack) -> str: ...

    def verify(self, question: str, answer: str, evidence: EvidencePack) -> bool:
        """Return whether an advisory proposal is evidence-consistent."""
        ...


@dataclass(frozen=True)
class VqaResult:
    candidate: SearchCandidate
    evidence: EvidencePack
    # Legacy transport fields remain while TV5 migrates to proposal semantics.
    answer: str
    verified: bool
    manual_fallback: bool
    # The backend never creates an operator-approved answer.
    proposal: str
    approved: bool
    verifier_status: str
    retry_count: int
    manual_required: bool
    status: str
    degraded_reasons: Sequence[str] = ()


def _as_records(value: object) -> list[Mapping[str, Any]]:
    """Accept the WP04 list response or its optional catalogue envelope."""
    if isinstance(value, Mapping):
        value = value.get("items", ())
    if not isinstance(value, list):
        raise ContractError("WP04 evidence detail response must be a list or items envelope")
    return [item for item in value if isinstance(item, Mapping)]


def _candidate_text(candidate: SearchCandidate, key: str) -> str:
    value = candidate.provenance.get(key)
    if isinstance(value, str):
        return value
    return ", ".join(part for part in candidate.matched_filters if isinstance(part, str))


def _near_candidate(candidate: SearchCandidate, other: SearchCandidate, window_ms: int) -> bool:
    if other.video_id != candidate.video_id:
        return False
    if other.window_start_ms is not None and other.window_end_ms is not None:
        return other.window_start_ms <= candidate.timestamp_ms + window_ms and other.window_end_ms >= candidate.timestamp_ms - window_ms
    return abs(other.timestamp_ms - candidate.timestamp_ms) <= window_ms


def _record_in_window(record: Mapping[str, Any], candidate: SearchCandidate, window_ms: int, branch: str) -> bool:
    if record.get("video_id") != candidate.video_id:
        return False
    if branch == "asr":
        start, end = record.get("start_ms"), record.get("end_ms")
        return isinstance(start, int) and isinstance(end, int) and start <= candidate.timestamp_ms + window_ms and end >= candidate.timestamp_ms - window_ms
    if branch == "metadata":
        start, end = record.get("window_start_ms"), record.get("window_end_ms")
        if start is None and end is None:
            return True
        return isinstance(start, int) and isinstance(end, int) and start <= candidate.timestamp_ms + window_ms and end >= candidate.timestamp_ms - window_ms
    return record.get("frame_id") == candidate.frame_id


def _ocr_record(record: Mapping[str, Any]) -> OcrEvidence:
    return OcrEvidence(
        detection_id=str(record["detection_id"]), video_id=str(record["video_id"]),
        frame_id=int(record["frame_id"]), timestamp_ms=int(record["timestamp_ms"]),
        raw_text=str(record["raw_text"]), normalized_text=str(record.get("normalized_text") or ""),
        bbox_xyxy_norm=tuple(record["bbox_xyxy_norm"]), polygon_norm=record.get("polygon_norm"),
        confidence=record.get("confidence"), crop_evidence_path=record.get("crop_evidence_path"),
        crop_sha256=record.get("crop_sha256"), source_keyframe_sha256=record.get("source_keyframe_sha256"),
        preprocess_run_id=record.get("preprocess_run_id"), model_name=record.get("model_name"),
        model_version=record.get("model_version"),
        provenance={"branch": "ocr", "schema_version": record.get("schema_version")}, source_record=dict(record),
    )


def _asr_record(record: Mapping[str, Any], context: Sequence[Mapping[str, Any]]) -> AsrEvidence:
    words = record.get("words")
    return AsrEvidence(
        segment_id=str(record["segment_id"]), video_id=str(record["video_id"]),
        start_ms=int(record["start_ms"]), end_ms=int(record["end_ms"]), text=str(record["text"]),
        normalized_text=record.get("normalized_text"),
        words=tuple(word for word in words if isinstance(word, Mapping)) if isinstance(words, list) else (),
        context=tuple(context), confidence=record.get("confidence"), language=record.get("language"),
        preprocess_run_id=record.get("preprocess_run_id"), model_name=record.get("model_name"),
        model_version=record.get("model_version"),
        provenance={"branch": "asr", "schema_version": record.get("schema_version")}, source_record=dict(record),
    )


def _object_record(record: Mapping[str, Any]) -> ObjectEvidence:
    return ObjectEvidence(
        detection_id=str(record["detection_id"]), video_id=str(record["video_id"]),
        frame_id=int(record["frame_id"]), timestamp_ms=int(record["timestamp_ms"]),
        label=str(record["label"]), bbox_xyxy_norm=tuple(record["bbox_xyxy_norm"]),
        canonical_label=record.get("canonical_label"), confidence=record.get("confidence"),
        source_keyframe_path=record.get("source_keyframe_path"), source_keyframe_sha256=record.get("source_keyframe_sha256"),
        preprocess_run_id=record.get("preprocess_run_id"), model_name=record.get("model_name"),
        model_version=record.get("model_version"),
        provenance={"branch": "object", "schema_version": record.get("schema_version")}, source_record=dict(record),
    )


def _metadata_record(record: Mapping[str, Any]) -> MetadataEvidence:
    values = {name: record.get(name) for name in ("title", "description", "tags", "channel", "upload_date", "language", "text", "normalized_text", "raw_fields") if name in record}
    return MetadataEvidence(
        metadata_id=str(record["metadata_id"]), video_id=str(record["video_id"]), source=str(record["source"]), values=values,
        window_start_ms=record.get("window_start_ms"), window_end_ms=record.get("window_end_ms"),
        confidence=record.get("confidence"), preprocess_run_id=record.get("preprocess_run_id"),
        model_name=record.get("model_name"), model_version=record.get("model_version"),
        source_record_sha256=record.get("source_record_sha256"),
        provenance={"branch": "metadata", "schema_version": record.get("schema_version")}, source_record=dict(record),
    )


def _optional_detail(tv3: TV3Client, method: str, **kwargs: Any) -> list[Mapping[str, Any]] | None:
    """Use catalogue details when this TV3 implementation exposes them."""
    fn = getattr(tv3, method, None)
    if fn is None:
        return None
    return _as_records(fn(**kwargs))


def build_evidence_pack(
    candidate: SearchCandidate, tv1: TV1Client, tv3: TV3Client, *,
    request: SearchRequest | None = None, window_ms: int = 3_000,
) -> EvidencePack:
    """Build a WP11 pack without deriving any frame identity locally."""
    if window_ms < 0:
        raise ValueError("window_ms must be non-negative")
    request = request or SearchRequest(query_id=candidate.query_id, task="VQA", question=None, query_text=None, limit=20)
    availability: dict[str, str] = {}
    provenance: dict[str, Any] = {
        "candidate": candidate.to_json(),
        "retrieval_request": {"query_text": request.query_text, "question": request.question},
        "branches": {},
    }

    try:
        raw_frames = tv1.frames(candidate.video_id)
        if not isinstance(raw_frames, list):
            raise ContractError("TV1 frame response must be a list")
        selected_frames: list[CanonicalFrameReference] = []
        for raw in raw_frames:
            if not isinstance(raw, Mapping):
                availability["frames"] = "malformed"
                continue
            try:
                if any(isinstance(raw.get(name), bool) or not isinstance(raw.get(name), int) or raw[name] < 0 for name in ("frame_id", "timestamp_ms")):
                    raise ContractError("TV1 frame identity is malformed")
                frame_id = int(raw["frame_id"])
                timestamp_ms = int(raw["timestamp_ms"])
                if raw.get("video_id") not in (None, candidate.video_id):
                    raise ContractError("TV1 frame video identity mismatch")
                if abs(timestamp_ms - candidate.timestamp_ms) <= window_ms:
                    selected_frames.append(CanonicalFrameReference(
                        video_id=candidate.video_id, frame_id=frame_id, timestamp_ms=timestamp_ms,
                        keyframe_path=raw.get("keyframe_path"), preprocess_run_id=raw.get("preprocess_run_id"),
                        provenance={"source": "tv1.frames", "record": dict(raw)},
                    ))
            except (KeyError, TypeError, ValueError, ContractError):
                availability["frames"] = "malformed"
        selected_frames.sort(key=lambda frame: (frame.timestamp_ms, frame.frame_id))
        availability.setdefault("frames", "available" if selected_frames else "empty")
    except Exception as exc:
        selected_frames = []
        availability["frames"] = "unavailable"
        provenance["frames_error"] = type(exc).__name__

    keyframe_path = next((frame.keyframe_path for frame in selected_frames if frame.frame_id == candidate.frame_id), None)
    neighbor_frame_ids = tuple(frame.frame_id for frame in selected_frames if frame.frame_id != candidate.frame_id)

    searched: dict[str, list[SearchCandidate]] = {}
    for branch in ("ocr", "asr", "object", "metadata"):
        try:
            rows = tv3.search(branch, request)
            searched[branch] = [row for row in rows if isinstance(row, SearchCandidate) and _near_candidate(candidate, row, window_ms)]
            availability[branch] = "available" if searched[branch] else "empty"
            provenance["branches"][branch] = {"search_candidate_count": len(searched[branch])}
        except Exception as exc:
            searched[branch] = []
            availability[branch] = "unavailable"
            provenance["branches"][branch] = {"search_error": type(exc).__name__}

    ocr_records: list[Mapping[str, Any]] = []
    asr_records: list[Mapping[str, Any]] = []
    object_records: list[Mapping[str, Any]] = []
    metadata_records: list[Mapping[str, Any]] = []
    details = (
        ("ocr", "get_ocr_detections", {"video_id": candidate.video_id, "frame_id": candidate.frame_id}, ocr_records),
        ("asr", "get_asr_segments", {"video_id": candidate.video_id, "start_ms": max(0, candidate.timestamp_ms - window_ms), "end_ms": candidate.timestamp_ms + window_ms}, asr_records),
        ("object", "get_object_detections", {"video_id": candidate.video_id, "frame_id": candidate.frame_id}, object_records),
        ("metadata", "get_metadata_records", {"video_id": candidate.video_id}, metadata_records),
    )
    for branch, method, kwargs, collector in details:
        if availability[branch] == "unavailable":
            continue
        try:
            raw_records = _optional_detail(tv3, method, **kwargs)
            if raw_records is not None:
                collector.extend(record for record in raw_records if _record_in_window(record, candidate, window_ms, branch))
                availability[branch] = "available" if collector or searched[branch] else "empty"
                provenance["branches"][branch]["catalogue_record_count"] = len(collector)
        except Exception as exc:
            availability[branch] = "unavailable"
            provenance["branches"][branch]["catalogue_error"] = type(exc).__name__

    def materialize(records: Sequence[Mapping[str, Any]], branch: str, convert: Any) -> tuple[Any, ...]:
        converted: list[Any] = []
        for record in records:
            try:
                converted.append(convert(record))
            except (KeyError, TypeError, ValueError, ContractError):
                availability[branch] = "malformed"
        return tuple(converted)

    ocr_evidence = materialize(ocr_records, "ocr", _ocr_record)
    object_evidence = materialize(object_records, "object", _object_record)
    metadata_evidence = materialize(metadata_records, "metadata", _metadata_record)
    asr_evidence_list: list[AsrEvidence] = []
    for record in asr_records:
        try:
            context_rows = _optional_detail(tv3, "get_asr_context", segment_id=str(record["segment_id"])) or []
            asr_evidence_list.append(_asr_record(record, context_rows))
        except (KeyError, TypeError, ValueError, ContractError):
            availability["asr"] = "malformed"
        except Exception as exc:
            availability["asr"] = "unavailable"
            provenance["branches"]["asr"]["context_error"] = type(exc).__name__

    # Search candidates are compatibility text only. Rich catalogue records
    # remain intact whenever producer detail endpoints are available.
    ocr_texts = tuple(record.raw_text for record in ocr_evidence) or tuple(filter(None, (_candidate_text(row, "text") for row in searched["ocr"])))
    asr_texts = tuple(record.text for record in asr_evidence_list) or tuple(filter(None, (_candidate_text(row, "text") for row in searched["asr"])))
    object_labels = tuple(record.label for record in object_evidence) or tuple(filter(None, (_candidate_text(row, "label") for row in searched["object"])))
    return EvidencePack(
        query_id=request.query_id, video_id=candidate.video_id, frame_id=candidate.frame_id,
        timestamp_ms=candidate.timestamp_ms, keyframe_path=keyframe_path,
        query_text=request.query_text, question=request.question, selected_frames=tuple(selected_frames),
        ocr_evidence=ocr_evidence, asr_evidence=tuple(asr_evidence_list), object_evidence=object_evidence,
        metadata_evidence=metadata_evidence, availability=availability, ocr_texts=ocr_texts,
        asr_texts=asr_texts, object_labels=object_labels, neighbor_frame_ids=neighbor_frame_ids,
        provenance=provenance,
    )


_YES_NO = re.compile(r"^(có|không|yes|no)$", re.I)
_NUMBER = re.compile(r"^-?\d+([.,]\d+)?$")


def normalize_answer(raw_answer: str, *, language: str | None = "vi") -> str:
    text = raw_answer.strip()
    if _NUMBER.match(text):
        return text.replace(",", ".")
    if _YES_NO.match(text):
        return text.lower()
    return text


def _degraded_result(candidate: SearchCandidate, evidence: EvidencePack, *, status: str, verifier_status: str, reasons: Sequence[str], retry_count: int = 0) -> VqaResult:
    return VqaResult(
        candidate=candidate, evidence=evidence, answer="", verified=False, manual_fallback=True,
        proposal="", approved=False, verifier_status=verifier_status, retry_count=retry_count,
        manual_required=True, status=status, degraded_reasons=tuple(reasons),
    )


def _attempt(engine: AnswerEngine, question: str, evidence: EvidencePack, language: str | None) -> tuple[str, bool, str, str | None]:
    try:
        raw_answer = engine.answer(question, evidence)
    except Exception as exc:
        return "", False, "reasoning_unavailable", type(exc).__name__
    if not isinstance(raw_answer, str):
        return "", False, "reasoning_malformed", "non_string_answer"
    proposal = normalize_answer(raw_answer, language=language)
    if not proposal:
        return "", False, "abstained", None
    try:
        verified = engine.verify(question, proposal, evidence)
    except Exception as exc:
        return proposal, False, "verifier_unavailable", type(exc).__name__
    if not isinstance(verified, bool):
        return proposal, False, "verifier_malformed", "non_boolean_verifier_result"
    return proposal, verified, "verified" if verified else "rejected", None


def answer_query(
    candidate: SearchCandidate, question: str, tv1: TV1Client, tv3: TV3Client,
    engine: AnswerEngine, *, request: SearchRequest | None = None,
    language: str | None = "vi", max_controlled_retries: int = 1,
) -> VqaResult:
    """Produce an advisory answer with no more than one evidence-window retry."""
    if max_controlled_retries not in (0, 1):
        raise ValueError("max_controlled_retries must be 0 or 1")
    request = request or SearchRequest(query_id=candidate.query_id, task="VQA", query_text=None, question=question, limit=20)
    if request.question != question:
        request = SearchRequest(query_id=request.query_id, task="VQA", query_text=request.query_text, question=question, events=request.events, filters=request.filters, limit=request.limit, language=request.language, session_id=request.session_id, event_index=request.event_index)
    evidence = build_evidence_pack(candidate, tv1, tv3, request=request)
    unavailable = tuple(branch for branch, state in evidence.availability.items() if state == "unavailable")
    if evidence.has_malformed_evidence:
        return _degraded_result(candidate, evidence, status="degraded", verifier_status="evidence_malformed", reasons=("malformed_evidence",))
    wp04_branches = ("ocr", "asr", "object", "metadata")
    if all(evidence.availability.get(branch) == "unavailable" for branch in wp04_branches):
        return _degraded_result(candidate, evidence, status="degraded", verifier_status="evidence_unavailable", reasons=wp04_branches)
    if not evidence.has_usable_evidence:
        if unavailable:
            return _degraded_result(candidate, evidence, status="degraded", verifier_status="evidence_unavailable", reasons=unavailable)
        return _degraded_result(candidate, evidence, status="abstained", verifier_status="insufficient_evidence", reasons=("empty_evidence",))

    proposal, verified, verifier_status, failure = _attempt(engine, question, evidence, language)
    retry_count = 0
    if failure:
        return _degraded_result(candidate, evidence, status="degraded", verifier_status=verifier_status, reasons=(failure,))
    # A real verifier rejection with evidence is recoverable once by asking
    # upstream for a larger temporal window. The retry never calculates IDs.
    if not verified and proposal and max_controlled_retries == 1 and not getattr(engine, "is_safe_fallback", False):
        retry_count = 1
        retry_evidence = build_evidence_pack(candidate, tv1, tv3, request=request, window_ms=6_000)
        if retry_evidence.has_malformed_evidence:
            return _degraded_result(candidate, retry_evidence, status="degraded", verifier_status="evidence_malformed", reasons=("malformed_evidence",), retry_count=retry_count)
        if retry_evidence.has_usable_evidence:
            evidence = retry_evidence
            proposal, verified, verifier_status, failure = _attempt(engine, question, evidence, language)
            if failure:
                return _degraded_result(candidate, evidence, status="degraded", verifier_status=verifier_status, reasons=(failure,), retry_count=retry_count)
        else:
            evidence = retry_evidence
            verifier_status = "retry_evidence_unavailable"

    # `verified` is only an internal evidence-consistency outcome. Approval
    # remains an explicit operator action owned by the later UI workflow.
    status = "proposal" if verified else "manual_required"
    return VqaResult(
        candidate=candidate, evidence=evidence, answer=proposal, verified=verified,
        manual_fallback=not verified, proposal=proposal, approved=False,
        verifier_status=verifier_status, retry_count=retry_count,
        manual_required=not verified, status=status,
        degraded_reasons=("vlm_unavailable_rule_fallback",) if getattr(engine, "is_safe_fallback", False) else (),
    )


class RuleBasedFallbackEngine:
    """Deterministic conservative fallback for CI and unavailable VLMs.

    It may extract an evidence-derived suggestion, but has no semantic model
    with which to certify a Q&A answer. It therefore never verifies a
    proposal; a human or approved verifier must do that later.
    """

    is_safe_fallback = True

    def answer(self, question: str, evidence: EvidencePack) -> str:
        for text in (*evidence.ocr_texts, *evidence.asr_texts):
            if text:
                return text
        return ""

    def verify(self, question: str, answer: str, evidence: EvidencePack) -> bool:
        if not evidence.has_usable_evidence or not answer.strip() or not question.strip():
            return False
        return False
