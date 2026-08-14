"""WP11 — VQA: EvidencePack construction, pluggable VLM/LLM answering,
verification, and answer normalization/manual fallback.

TV4 does not ship a specific VLM: the plan calls for a swappable
VLM/Video-LLM + verifier, and AkiraVN's own stack (Qwen2.5-7B-Instruct,
served locally) is a reasonable default. `AnswerEngine` is a small Protocol
so any OpenAI-compatible endpoint (vLLM / Ollama / text-generation-webui /
Qwen2.5-VL server) can be plugged in without touching this module.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Protocol

from .clients.tv1_client import TV1Client
from .clients.tv3_client import TV3Client
from .contracts import EvidencePack, SearchCandidate


class AnswerEngine(Protocol):
    def answer(self, question: str, evidence: EvidencePack) -> str: ...

    def verify(self, question: str, answer: str, evidence: EvidencePack) -> bool:
        """Return True if the answer is consistent with the evidence."""
        ...


@dataclass(frozen=True)
class VqaResult:
    candidate: SearchCandidate
    evidence: EvidencePack
    answer: str
    verified: bool
    manual_fallback: bool


def build_evidence_pack(candidate: SearchCandidate, tv1: TV1Client, tv3: TV3Client, *, window_ms: int = 3_000) -> EvidencePack:
    frames = tv1.frames(candidate.video_id)
    keyframe_path = next((f.get("keyframe_path") for f in frames if int(f.get("frame_id", -1)) == candidate.frame_id), None)
    neighbors = [
        int(f["frame_id"]) for f in frames
        if abs(int(f["timestamp_ms"]) - candidate.timestamp_ms) <= window_ms and int(f["frame_id"]) != candidate.frame_id
    ]

    from .contracts import SearchRequest

    probe = SearchRequest(query_id=f"{candidate.query_id}-evidence", task="VQA", query_text=None, question=None, limit=20)
    ocr = tv3.search("ocr", probe)
    asr = tv3.search("asr", probe)
    obj = tv3.search("object", probe)

    def _near(cands: list[SearchCandidate]) -> list[SearchCandidate]:
        return [c for c in cands if c.video_id == candidate.video_id and abs(c.timestamp_ms - candidate.timestamp_ms) <= window_ms]

    ocr_texts = [", ".join(c.matched_filters) or c.provenance.get("text", "") for c in _near(ocr)]
    asr_texts = [c.provenance.get("text", "") for c in _near(asr)]
    object_labels = [c.provenance.get("label", "") for c in _near(obj)]

    return EvidencePack(
        query_id=candidate.query_id,
        video_id=candidate.video_id,
        frame_id=candidate.frame_id,
        timestamp_ms=candidate.timestamp_ms,
        keyframe_path=keyframe_path,
        ocr_texts=tuple(t for t in ocr_texts if t),
        asr_texts=tuple(t for t in asr_texts if t),
        object_labels=tuple(l for l in object_labels if l),
        neighbor_frame_ids=tuple(sorted(neighbors)),
        provenance={"candidate_source": candidate.provenance_sources},
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


def answer_query(
    candidate: SearchCandidate,
    question: str,
    tv1: TV1Client,
    tv3: TV3Client,
    engine: AnswerEngine,
    *,
    language: str | None = "vi",
) -> VqaResult:
    evidence = build_evidence_pack(candidate, tv1, tv3)
    raw_answer = engine.answer(question, evidence)
    normalized = normalize_answer(raw_answer, language=language)
    verified = engine.verify(question, normalized, evidence)
    manual_fallback = not verified and not (evidence.ocr_texts or evidence.asr_texts or evidence.object_labels)
    return VqaResult(candidate=candidate, evidence=evidence, answer=normalized, verified=verified, manual_fallback=manual_fallback)


class RuleBasedFallbackEngine:
    """No-LLM fallback: only ever answers when the question can be resolved
    directly from OCR/ASR text (exact substring), otherwise abstains and
    flags manual review. Useful for CI/tests and as a last-resort branch
    when no VLM endpoint is reachable.
    """

    def answer(self, question: str, evidence: EvidencePack) -> str:
        for text in (*evidence.ocr_texts, *evidence.asr_texts):
            if text:
                return text
        return ""

    def verify(self, question: str, answer: str, evidence: EvidencePack) -> bool:
        return bool(answer)
