"""Regression tests for adapters/wp09_adapter.py.

This file had zero test coverage per the tv4 review (04_tv4.md), and both
🔴 bugs in it (raw-PTS-as-frame_id corrupting submissions, and the
Siglip2FrameScorer/Siglip2Scorer typo silently disabling refine scoring)
were only reachable through wp09's own subprocess CLI end-to-end, which is
why they went unnoticed. These tests exercise the adapter in isolation by
faking TV1Client and the wp09 module boundary, so they run without a WP09
environment or network access.
"""
from __future__ import annotations

import sys
import types
from types import SimpleNamespace

import pytest

from tv4.adapters import wp09_adapter as adapter_module
from tv4.adapters.wp09_adapter import MappedPyAVDecoder
from tv4.clients.tv1_client import TV1ClientError


class _FakeTV1:
    def __init__(self, frames):
        self._frames = frames
        self.calls: list[str] = []

    def frames(self, video_id):
        self.calls.append(video_id)
        return self._frames


class _FailingTV1:
    def frames(self, video_id):
        raise TV1ClientError("tv1 unreachable")


def _make_decoder(tv1, video_id: str = "L01_V001") -> MappedPyAVDecoder:
    # Bypass __init__ (which imports wp09.pyav_decoder, unavailable outside
    # WP09's own venv) and wire up just what _resolve_frame_id/_tv1_frames need.
    dec = object.__new__(MappedPyAVDecoder)
    dec.video_id = video_id
    dec.base_url = "http://fake"
    dec._tv1 = tv1
    dec._frames_cache = None
    return dec


def test_resolve_frame_id_uses_tv1_timestamp_lookup_not_raw_pts():
    """Bug #1: frame_id must come from TV1's real frame index, never PTS."""
    frames = [
        {"frame_id": 10, "timestamp_ms": 1000},
        {"frame_id": 11, "timestamp_ms": 2000},
        {"frame_id": 12, "timestamp_ms": 3000},
    ]
    dec = _make_decoder(_FakeTV1(frames))
    raw = SimpleNamespace(pts=999_999, timestamp_ms=2050)  # PTS is a decoy value

    resolved = dec._resolve_frame_id(raw, dec._tv1_frames())

    assert resolved == 11  # nearest by timestamp_ms, not raw.pts
    assert resolved != raw.pts


def test_resolve_frame_id_raises_instead_of_fabricating_an_id():
    """When TV1 has nothing to resolve against, fail loudly rather than
    silently writing a bogus (PTS-based) frame_id that would corrupt a
    refined submission row."""
    dec = _make_decoder(_FakeTV1([]))
    raw = SimpleNamespace(pts=42, timestamp_ms=1234)

    with pytest.raises(RuntimeError):
        dec._resolve_frame_id(raw, dec._tv1_frames())


def test_resolve_frame_id_raises_when_tv1_unreachable():
    dec = _make_decoder(_FailingTV1())
    raw = SimpleNamespace(pts=42, timestamp_ms=1234)

    with pytest.raises(RuntimeError):
        dec._resolve_frame_id(raw, dec._tv1_frames())


def test_tv1_frames_fetched_once_per_decoder_instance():
    """Guards against re-introducing a per-frame TV1 call (N+1)."""
    tv1 = _FakeTV1([{"frame_id": 1, "timestamp_ms": 0}])
    dec = _make_decoder(tv1)

    dec._tv1_frames()
    dec._tv1_frames()
    dec._tv1_frames()

    assert tv1.calls == ["L01_V001"]


def test_decoder_for_request_extracts_video_id_from_candidate(monkeypatch):
    captured = {}

    def _fake_init(self, video_id, base_url=adapter_module.TV1_BASE_URL):
        captured["video_id"] = video_id

    monkeypatch.setattr(MappedPyAVDecoder, "__init__", _fake_init)
    request = SimpleNamespace(candidate=SimpleNamespace(video_id="L05_V009"))

    adapter_module.decoder_for_request(request)

    assert captured["video_id"] == "L05_V009"


def test_scorer_for_request_returns_none_when_wp09_scoring_unavailable(monkeypatch):
    real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __builtins__.__import__

    def _fake_import(name, *args, **kwargs):
        if name == "wp09.scoring":
            raise ImportError("wp09 not installed in this env")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", _fake_import)

    assert adapter_module.scorer_for_request(SimpleNamespace()) is None


def test_scorer_for_request_uses_the_real_siglip2_class_name(monkeypatch):
    """Bug #2 regression guard: the import must be `Siglip2Scorer`. If this
    reverts to the old `Siglip2FrameScorer` typo, the ImportError gets
    swallowed and this test fails because the fake scorer never gets built.
    """
    built = {}

    class FakeScorer:
        def __init__(self):
            built["constructed"] = True

    fake_wp09 = types.ModuleType("wp09")
    fake_scoring = types.ModuleType("wp09.scoring")
    fake_scoring.Siglip2Scorer = FakeScorer
    monkeypatch.setitem(sys.modules, "wp09", fake_wp09)
    monkeypatch.setitem(sys.modules, "wp09.scoring", fake_scoring)

    result = adapter_module.scorer_for_request(SimpleNamespace())

    assert built.get("constructed") is True
    assert isinstance(result, FakeScorer)
