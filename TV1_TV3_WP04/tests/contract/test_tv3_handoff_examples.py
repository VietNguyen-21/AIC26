from __future__ import annotations

import json
from pathlib import Path

from aic2026.benchmarking import load_labeled_query_set
from aic2026.contracts import SearchCandidate

ROOT = Path(__file__).parents[2]


def test_tv4_candidate_examples_conform_to_search_candidate_contract():
    payload = json.loads((ROOT / "tests" / "fixtures" / "tv4_search_candidates.json").read_text(encoding="utf-8"))
    candidates = {name: SearchCandidate.model_validate(row) for name, row in payload.items()}
    assert candidates["ocr_exact_frame"].provenance["submittable"] is True
    assert candidates["ocr_exact_frame"].provenance["frame_resolution"] == "source_keyframe"
    assert candidates["asr_unresolved"].provenance["submittable"] is False
    assert candidates["object_exact_frame"].provenance["submittable"] is True
    assert candidates["object_exact_frame"].provenance["frame_resolution"] == "source_keyframe"
    assert candidates["metadata_video_level"].provenance["policy"] == "video_soft_boost_only"


def test_labeled_query_examples_are_loadable_templates():
    rows = load_labeled_query_set(ROOT / "benchmarks" / "examples" / "labeled_queries.example.jsonl")
    assert {row["query_type"] for row in rows} == {"ocr", "asr"}
    assert all(row["relevant_video_ids"] == ["REPLACE_VIDEO_ID"] for row in rows)
