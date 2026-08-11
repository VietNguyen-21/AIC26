"""Engineering and retrieval-quality benchmarks for TV3 evidence services."""
from __future__ import annotations

import json
import math
import statistics
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable, Iterable

from .config import Settings
from .evidence_catalog import EvidenceCatalog, validate_evidence_catalog
from .modalities import text_search
from .objects import object_search
from .utils import read_jsonl, utcnow_iso, write_json


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, math.ceil(percentile * len(ordered)) - 1))
    return float(ordered[index])


def _timed(call: Callable[[], Any]) -> tuple[float, Any]:
    started = time.perf_counter()
    result = call()
    return (time.perf_counter() - started) * 1000.0, result


def benchmark_concurrent_queries(
    run_id: str,
    run_root: str | Path,
    settings: Settings,
    queries: Iterable[str],
    *,
    workers: int = 4,
    repetitions: int = 3,
    top_k: int = 20,
) -> dict[str, Any]:
    """Run concurrent text/object queries and report latency without inventing quality metrics."""

    root = Path(run_root)
    validate_evidence_catalog(root)
    query_list = [query.strip() for query in queries if query.strip()]
    if not query_list:
        raise ValueError("At least one non-empty query is required")
    jobs: list[tuple[str, str, int]] = []
    for repetition in range(repetitions):
        for query in query_list:
            jobs.append(("text", query, repetition))
            jobs.append(("object", query, repetition))

    latencies: dict[str, list[float]] = {"text": [], "object": []}
    result_counts: dict[str, list[int]] = {"text": [], "object": []}

    def execute(job: tuple[str, str, int]) -> tuple[str, float, int]:
        kind, query, repetition = job
        query_id = f"benchmark:{kind}:{repetition}:{abs(hash(query))}"
        if kind == "text":
            latency, rows = _timed(
                lambda: text_search(
                    query_id,
                    query,
                    run_id,
                    root,
                    top_k,
                    settings=settings,
                )
            )
        else:
            latency, rows = _timed(
                lambda: object_search(query_id, query, run_id, root, top_k)
            )
        return kind, latency, len(rows)

    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        futures = [executor.submit(execute, job) for job in jobs]
        for future in as_completed(futures):
            kind, latency, count = future.result()
            latencies[kind].append(latency)
            result_counts[kind].append(count)
    wall_seconds = time.perf_counter() - started

    metrics: dict[str, Any] = {}
    for kind, values in latencies.items():
        metrics[kind] = {
            "request_count": len(values),
            "p50_ms": statistics.median(values) if values else 0.0,
            "p95_ms": _percentile(values, 0.95),
            "p99_ms": _percentile(values, 0.99),
            "max_ms": max(values, default=0.0),
            "mean_ms": statistics.fmean(values) if values else 0.0,
            "mean_result_count": statistics.fmean(result_counts[kind]) if values else 0.0,
        }
    return {
        "schema_version": "1.0.0",
        "benchmark_type": "engineering_load_test",
        "quality_metrics": "PENDING_GROUND_TRUTH",
        "run_id": run_id,
        "workers": workers,
        "repetitions": repetitions,
        "query_count": len(query_list),
        "total_requests": len(jobs),
        "wall_seconds": wall_seconds,
        "throughput_requests_per_second": len(jobs) / wall_seconds if wall_seconds else 0.0,
        "metrics": metrics,
        "catalog": validate_evidence_catalog(root)["counts"],
        "created_at_utc": utcnow_iso(),
    }


def load_labeled_query_set(path: str | Path) -> list[dict[str, Any]]:
    rows = read_jsonl(path)
    required = {"query_id", "query_text", "query_type", "relevant_video_ids"}
    for index, row in enumerate(rows, start=1):
        missing = required.difference(row)
        if missing:
            raise ValueError(f"Labeled query row {index} is missing: {sorted(missing)}")
        if not isinstance(row["relevant_video_ids"], list):
            raise ValueError(f"Labeled query row {index} relevant_video_ids must be a list")
    return rows


def evaluate_ranked_results(
    query_rows: list[dict[str, Any]],
    ranked_by_query: dict[str, list[dict[str, Any]]],
    *,
    cutoffs: tuple[int, ...] = (1, 5, 20, 50, 100),
) -> dict[str, Any]:
    """Evaluate video-level Hit@K/MRR only when real labels are provided."""

    per_query = []
    reciprocal_ranks: list[float] = []
    hit_totals = {cutoff: 0 for cutoff in cutoffs}
    for row in query_rows:
        relevant = set(str(value) for value in row["relevant_video_ids"])
        ranked = ranked_by_query.get(str(row["query_id"]), [])
        first_rank = None
        for rank, candidate in enumerate(ranked, start=1):
            if str(candidate.get("video_id")) in relevant:
                first_rank = rank
                break
        reciprocal_ranks.append(0.0 if first_rank is None else 1.0 / first_rank)
        hits = {str(cutoff): bool(first_rank and first_rank <= cutoff) for cutoff in cutoffs}
        for cutoff in cutoffs:
            hit_totals[cutoff] += int(hits[str(cutoff)])
        per_query.append(
            {
                "query_id": row["query_id"],
                "query_type": row["query_type"],
                "first_relevant_rank": first_rank,
                "reciprocal_rank": reciprocal_ranks[-1],
                "hits": hits,
            }
        )
    count = len(query_rows)
    return {
        "query_count": count,
        "mrr": statistics.fmean(reciprocal_ranks) if reciprocal_ranks else 0.0,
        "video_hit_at_k": {
            str(cutoff): hit_totals[cutoff] / count if count else 0.0 for cutoff in cutoffs
        },
        "per_query": per_query,
    }


def write_benchmark_report(path: str | Path, report: dict[str, Any]) -> Path:
    target = Path(path)
    write_json(target, report)
    return target
