from __future__ import annotations

from pathlib import Path

import numpy as np

from wp03.index import build_flat_ip_index, search_flat_ip_index


def test_streaming_index_returns_the_vector_from_second_shard(tmp_path: Path) -> None:
    first = tmp_path / "a.npy"
    second = tmp_path / "b.npy"
    np.save(first, np.array([[1.0, 0.0]], dtype=np.float32))
    np.save(second, np.array([[0.0, 1.0]], dtype=np.float32))

    report = build_flat_ip_index((first, second), 2, tmp_path / "index.faiss")
    scores, ids = search_flat_ip_index(tmp_path / "index.faiss", np.array([0.0, 1.0], np.float32), 1)

    assert report.vector_count == 2
    assert scores.tolist() == [1.0]
    assert ids.tolist() == [1]
