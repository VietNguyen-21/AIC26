from tv4.contracts import SearchCandidate
from tv4.wp12_trake import EventPool, align_dp, align_greedy, align_trake


def _cand(frame_id, ts, score):
    return SearchCandidate(
        query_id="q1", video_id="L10_V010", frame_id=frame_id, timestamp_ms=ts,
        source="fusion", rank=1, score=score,
    )


def test_align_dp_prefers_monotonic_path():
    pools = [
        EventPool(0, (_cand(1, 100, 0.9), _cand(2, 300, 0.5))),
        EventPool(1, (_cand(3, 150, 0.9), _cand(4, 400, 0.4))),  # frame 3 (ts=150) is best but breaks monotonicity with frame 1 only if event0 picks 2
    ]
    result = align_dp(pools)
    assert result is not None
    assert result[0].timestamp_ms <= result[1].timestamp_ms


def test_align_dp_returns_none_when_no_monotonic_path_exists():
    pools = [
        EventPool(0, (_cand(1, 900, 0.9),)),
        EventPool(1, (_cand(2, 100, 0.9),)),
    ]
    assert align_dp(pools) is None


def test_align_trake_falls_back_to_greedy():
    pools = [
        EventPool(0, (_cand(1, 900, 0.9),)),
        EventPool(1, (_cand(2, 100, 0.9),)),
    ]
    result = align_trake(pools, strategy="dp")
    assert result is not None  # greedy fallback still returns a (repaired) sequence


def test_align_trake_missing_event_pool_is_none():
    pools = [EventPool(0, ()), EventPool(1, (_cand(2, 100, 0.9),))]
    assert align_trake(pools) is None


class MockVisualBatchClient:
    def __init__(self):
        self.batch_calls = []

    def search_batch(self, requests):
        self.batch_calls.append(requests)
        # requests: [(qid, qtxt, ev_idx)]
        results = []
        for qid, qtxt, ev_idx in requests:
            if ev_idx is None:
                # Whole query
                results.append([_cand(10, 100, 0.95), _cand(20, 200, 0.9)])
            elif ev_idx == 0:
                results.append([_cand(10, 100, 0.9), _cand(15, 150, 0.5)])
            elif ev_idx == 1:
                results.append([_cand(20, 200, 0.9), _cand(10, 100, 0.3)])
        return results


class MockTv3Client:
    def search_all(self, req, routes):
        return {}


def test_run_trake_query_invokes_visual_search_batch():
    from tv4.kis_pipeline import KisServices
    from tv4.trake_pipeline import run_trake_query

    mock_visual = MockVisualBatchClient()
    mock_tv3 = MockTv3Client()
    services = KisServices(
        tv1=None,
        tv3=mock_tv3,
        visual=mock_visual,
        refine=None,
        preprocess_run_id="run_v1_batch1",
    )

    hyp = run_trake_query(
        "Vận động viên thực hiện cú nhảy cao",
        services,
        events=["Giậm nhảy", "Bay qua xà"],
        query_id="trake-test-01",
    )

    assert hyp is not None
    assert hyp.video_id == "L10_V010"
    assert len(hyp.frame_ids) == 2
    # Ensure visual search_batch was called exactly ONCE with 3 requests (whole + 2 events)
    assert len(mock_visual.batch_calls) == 1
    assert len(mock_visual.batch_calls[0]) == 3
    assert mock_visual.batch_calls[0][0][1] == "Vận động viên thực hiện cú nhảy cao"
    assert mock_visual.batch_calls[0][1][1] == "Giậm nhảy"
    assert mock_visual.batch_calls[0][2][1] == "Bay qua xà"
