"""Formats TV4 output to match `Thong-tin-vong-So-tuyen-AIC2026`'s submission
rules exactly: up to 100 ranked answers per query, ordering matters because
Final Score = mean(R@1, R@5, R@20, R@50, R@100), so the *best* answer must be
ranked first, not just present somewhere in the 100.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

from .contracts import SearchCandidate, TrakeHypothesis
from .wp11_vqa import VqaResult


def kis_rows(candidates: list[SearchCandidate]) -> list[dict]:
    return [{"rank": c.rank, "video_id": c.video_id, "frame_id": c.frame_id} for c in candidates]


def qa_rows(results: list[VqaResult]) -> list[dict]:
    return [
        {
            "rank": r.candidate.rank,
            "video_id": r.candidate.video_id,
            "frame_id": r.candidate.frame_id,
            "answer": r.answer,
            "manual_review": r.manual_fallback,
        }
        for r in results
    ]


def trake_row(hypothesis: TrakeHypothesis) -> dict:
    return {"video_id": hypothesis.video_id, "frame_ids": list(hypothesis.frame_ids)}


def write_kis_csv(path: Path, query_id: str, candidates: list[SearchCandidate]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["query_id", "rank", "video_id", "frame_id"])
        for row in kis_rows(candidates):
            writer.writerow([query_id, row["rank"], row["video_id"], row["frame_id"]])


def write_qa_csv(path: Path, query_id: str, results: list[VqaResult]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["query_id", "rank", "video_id", "frame_id", "answer"])
        for row in qa_rows(results):
            writer.writerow([query_id, row["rank"], row["video_id"], row["frame_id"], row["answer"]])


def write_trake_json(path: Path, query_id: str, hypothesis: TrakeHypothesis | None) -> None:
    payload = {"query_id": query_id, "result": trake_row(hypothesis) if hypothesis else None}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
