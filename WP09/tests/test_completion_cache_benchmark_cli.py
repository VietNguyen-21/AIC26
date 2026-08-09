from __future__ import annotations

import json

from wp09.benchmark import LabeledResult, compare_refinement_runs
from wp09.cache import DecodedWindowCache, DecodedWindowKey
from wp09.cli import main
from wp09.decoder import DecodedFrame


def test_cache_key_never_crosses_mapping_runs() -> None:
    """Catches reuse of frames resolved under a stale PTS-to-frame mapping."""
    cache = DecodedWindowCache()
    first = DecodedWindowKey("run-a", "L21_V001", 10, 20, "pyav-1")
    other = DecodedWindowKey("run-b", "L21_V001", 10, 20, "pyav-1")
    cache.put(first, (DecodedFrame(7, 10, "1/1000", 10),))
    assert cache.get(other) is None


def test_benchmark_calculates_interval_and_latency_deltas() -> None:
    """Catches reporting a refinement comparison without literal ON/OFF metrics."""
    baseline = (LabeledResult("a", 100, 95, 105, 30), LabeledResult("b", 180, 190, 210, 70))
    refined = (LabeledResult("a", 100, 95, 105, 20), LabeledResult("b", 200, 190, 210, 50))
    report = compare_refinement_runs(baseline, refined, run_id="run-7", config_id="siglip2-b16-224")
    assert report.baseline.interval_hit_at_k == 0.5
    assert report.refined.interval_hit_at_k == 1.0
    assert report.interval_hit_delta == 0.5
    assert report.refined.p95_latency_ms == 50


def test_cli_emits_json_error_for_invalid_request(capsys) -> None:
    """Catches integration callers receiving a traceback instead of the JSON contract."""
    assert main(["refine", "--request", "missing-request.json", "--config", "configs/default.yaml"]) == 2
    assert json.loads(capsys.readouterr().err)["status"] == "error"
