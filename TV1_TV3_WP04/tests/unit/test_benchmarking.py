from __future__ import annotations

from pathlib import Path

import pytest

from aic2026.benchmarking import (
    evaluate_ranked_results,
    load_labeled_query_set,
)
from aic2026.utils import write_jsonl


def test_labeled_query_validation_and_video_metrics(tmp_path: Path):
    path = tmp_path / "queries.jsonl"
    write_jsonl(
        path,
        [
            {
                "query_id": "q1",
                "query_text": "a car",
                "query_type": "object",
                "relevant_video_ids": ["V2"],
            },
            {
                "query_id": "q2",
                "query_text": "speech",
                "query_type": "asr",
                "relevant_video_ids": ["V3"],
            },
        ],
    )
    rows = load_labeled_query_set(path)
    report = evaluate_ranked_results(
        rows,
        {
            "q1": [{"video_id": "V1"}, {"video_id": "V2"}],
            "q2": [{"video_id": "V3"}],
        },
        cutoffs=(1, 2),
    )
    assert report["query_count"] == 2
    assert report["mrr"] == pytest.approx(0.75)
    assert report["video_hit_at_k"] == {"1": 0.5, "2": 1.0}


def test_labeled_query_rejects_missing_fields(tmp_path: Path):
    path = tmp_path / "bad.jsonl"
    write_jsonl(path, [{"query_id": "q"}])
    with pytest.raises(ValueError, match="missing"):
        load_labeled_query_set(path)
