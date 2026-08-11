from __future__ import annotations

from pathlib import Path

import pytest

from aic2026 import benchmarking
from aic2026.config import Settings


def test_percentile_timed_and_report_writer(tmp_path: Path):
    assert benchmarking._percentile([], 0.95) == 0.0
    assert benchmarking._percentile([3.0, 1.0, 2.0], 0.5) == 2.0
    latency, value = benchmarking._timed(lambda: "done")
    assert latency >= 0
    assert value == "done"
    target = benchmarking.write_benchmark_report(tmp_path / "nested" / "report.json", {"x": 1})
    assert target.is_file()


def test_concurrent_query_benchmark(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    validation = {"counts": {"ocr": 2, "asr": 1, "object": 3, "metadata": 1}}
    monkeypatch.setattr(benchmarking, "validate_evidence_catalog", lambda root: validation)
    monkeypatch.setattr(
        benchmarking,
        "text_search",
        lambda query_id, query, run_id, root, top_k, settings: [{"video_id": "V1"}],
    )
    monkeypatch.setattr(
        benchmarking,
        "object_search",
        lambda query_id, query, run_id, root, top_k: [{"video_id": "V2"}, {"video_id": "V3"}],
    )
    report = benchmarking.benchmark_concurrent_queries(
        "run", tmp_path, Settings(), ["car", " speech ", ""], workers=2, repetitions=2, top_k=5
    )
    assert report["benchmark_type"] == "engineering_load_test"
    assert report["quality_metrics"] == "PENDING_GROUND_TRUTH"
    assert report["query_count"] == 2
    assert report["total_requests"] == 8
    assert report["metrics"]["text"]["request_count"] == 4
    assert report["metrics"]["object"]["mean_result_count"] == 2
    assert report["catalog"] == validation["counts"]
    assert report["throughput_requests_per_second"] > 0


def test_concurrent_query_benchmark_rejects_empty(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(benchmarking, "validate_evidence_catalog", lambda root: {"counts": {}})
    with pytest.raises(ValueError, match="non-empty"):
        benchmarking.benchmark_concurrent_queries("run", tmp_path, Settings(), ["", "  "])


def test_evaluate_empty_query_set():
    report = benchmarking.evaluate_ranked_results([], {}, cutoffs=(1,))
    assert report == {"query_count": 0, "mrr": 0.0, "video_hit_at_k": {"1": 0.0}, "per_query": []}
