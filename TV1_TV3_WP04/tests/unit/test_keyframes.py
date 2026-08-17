from __future__ import annotations

from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from aic2026.keyframes import (
    CandidateAnchor,
    SelectedFrame,
    _deduplicate,
    dhash,
    hamming,
    phash,
    quality_score,
)


def settings(**overrides):
    values = dict(
        quality_face_weight=0.0,
        quality_text_weight=0.0,
        quality_sharpness_weight=1.0,
        quality_black_weight=5.0,
        quality_blur_weight=1.0,
        quality_center_bias=0.25,
        dedup_method="dhash",
        dedup_threshold=8,
        dedup_temporal_window_ms=5000,
    )
    values.update(overrides)
    return SimpleNamespace(keyframes=SimpleNamespace(**values))


def test_quality_penalizes_black_blurry_frame():
    sharp = np.zeros((120, 160, 3), dtype=np.uint8)
    cv2.putText(sharp, "AIC", (15, 70), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (255, 255, 255), 3)
    black = np.zeros_like(sharp)
    assert quality_score(sharp, settings()).composite > quality_score(black, settings()).composite


def test_hashes_are_stable_and_near_identical():
    frame = np.zeros((64, 64, 3), dtype=np.uint8)
    frame[:, 32:] = 255
    altered = frame.copy()
    altered[0, 0] = 1
    assert hamming(dhash(frame), dhash(altered)) <= 2
    assert hamming(phash(frame), phash(altered)) <= 2


def test_embedding_dedup_is_explicitly_deferred():
    from aic2026.keyframes import _hash_frame

    with pytest.raises(NotImplementedError):
        _hash_frame(np.zeros((8, 8, 3), dtype=np.uint8), "embedding")
