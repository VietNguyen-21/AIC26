"""HTTP Range behavior is covered by backend/tests/test_app.py.

This file keeps the round-07 acceptance test discoverable under integration tests.
"""

from aic2026.api import _parse_byte_range


def test_byte_range_parser_open_ended_and_suffix():
    assert _parse_byte_range("bytes=4-", 10) == (4, 9)
    assert _parse_byte_range("bytes=-4", 10) == (6, 9)
