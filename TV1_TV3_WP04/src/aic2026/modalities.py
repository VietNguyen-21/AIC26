"""Compatibility entry points that expose modality-specific search functions."""

from __future__ import annotations

from pathlib import Path

from .asr import asr_search, build_asr_documents
from .contracts import SearchCandidate
from .metadata import build_metadata_documents, metadata_search, write_technical_metadata
from .objects import object_search
from .ocr import build_ocr_documents, ocr_search
from .text_index import TextDocument, build_text_documents_from_run, search_text_index
from .utils import utcnow_iso


def build_text_documents(run_root: str | Path) -> list[TextDocument]:
    return build_text_documents_from_run(run_root)


def text_search(
    query_id: str,
    query: str,
    run_id: str,
    run_root: str | Path,
    k: int = 100,
    *,
    settings=None,
    source_filter: set[str] | None = None,
) -> list[SearchCandidate]:
    return search_text_index(
        query_id,
        query,
        run_id,
        run_root,
        k,
        settings=settings,
        source_filter=source_filter,
    )
