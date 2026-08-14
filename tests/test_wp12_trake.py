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
