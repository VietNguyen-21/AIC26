"""Deterministic corpus identity and shard-resume digests."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Sequence

from .contracts import FrameRecord
from .corpus import resolve_keyframe


class ContentValidationMode(StrEnum):
    FAST = "fast"
    STRICT = "strict"


@dataclass(frozen=True)
class CorpusDigests:
    frames_jsonl_digest: str
    corpus_content_digest: str
    content_integrity_source: str


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical_record(record: FrameRecord) -> bytes:
    payload = {
        "preprocess_run_id": record.preprocess_run_id,
        "video_id": record.video_id,
        "frame_id": record.frame_id,
        "keyframe_seq": record.keyframe_seq,
        "timestamp_ms": record.timestamp_ms,
        "keyframe_path": record.keyframe_path.replace("\\", "/"),
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")


def _record_digest(record: FrameRecord, data_root: Path, mode: ContentValidationMode) -> str:
    material = _canonical_record(record)
    if mode is ContentValidationMode.STRICT:
        material += b"\n" + sha256_bytes(resolve_keyframe(data_root, record).read_bytes()).encode("ascii")
    return sha256_bytes(material)


def _ordered_digest(record_digests: Sequence[str]) -> str:
    return sha256_bytes("\n".join(record_digests).encode("ascii"))


def compute_corpus_digests(
    corpus: Sequence[FrameRecord],
    data_root: Path,
    mode: ContentValidationMode,
    frames_jsonl_digest: str,
    tv1_manifest_sha256: str | None,
) -> CorpusDigests:
    """Compute the identity used to decide whether a build can be resumed."""

    record_digests = [_record_digest(record, data_root, mode) for record in corpus]
    if mode is ContentValidationMode.STRICT:
        source = "strict_image_bytes"
        material = record_digests
    elif tv1_manifest_sha256:
        source = "tv1_manifest"
        material = [tv1_manifest_sha256, frames_jsonl_digest, *record_digests]
    else:
        source = "frames_jsonl_fallback"
        material = [corpus[0].preprocess_run_id, frames_jsonl_digest, *record_digests]
    return CorpusDigests(
        frames_jsonl_digest=frames_jsonl_digest,
        corpus_content_digest=_ordered_digest(material),
        content_integrity_source=source,
    )


def compute_shard_input_digest(
    corpus_slice: Sequence[FrameRecord],
    data_root: Path,
    mode: ContentValidationMode,
    frames_jsonl_digest: str,
    tv1_manifest_sha256: str | None,
) -> str:
    """Return a shard-local digest using the same validation policy as corpus."""

    return compute_corpus_digests(
        corpus_slice, data_root, mode, frames_jsonl_digest, tv1_manifest_sha256
    ).corpus_content_digest
