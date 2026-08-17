"""Regression test for the operator-precedence bug in
wp07_router.py::_looks_like_intro (bug #5, tv4 review).

Old logic: `keyword_match and has_colon or ends_with_colon` parsed (due to
Python's `and`/`or` precedence) as `(keyword_match and has_colon) or
ends_with_colon` — so ANY fragment ending in ':' was treated as an intro
clause and dropped from the TRAKE event list, even a real event that simply
happened to end with a colon.
"""
from __future__ import annotations

from tv4.wp07_router import _looks_like_intro, split_trake_events


def test_real_event_ending_in_colon_is_not_mistaken_for_intro():
    # No "tìm/find/xác định/liệt kê" prefix -> must not be treated as intro,
    # even though it ends with ':'.
    assert _looks_like_intro("người chơi bấm chuông:") is False


def test_intro_clause_with_keyword_and_colon_is_still_detected():
    assert _looks_like_intro("Tìm 3 khoảnh khắc chính:") is True


def test_fragment_with_neither_keyword_nor_colon_is_not_intro():
    assert _looks_like_intro("người chơi bước lên sân khấu") is False


def test_split_trake_events_keeps_event_that_ends_with_colon():
    text = "(1) người dẫn chương trình giới thiệu: (2) khách mời bước ra (3) khán giả vỗ tay"
    events = split_trake_events(text)
    # All three numbered events must survive; none should be silently eaten
    # as a false "intro" just because part (1) ends with ':'.
    assert len(events) == 3
