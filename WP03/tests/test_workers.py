from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from wp03.contracts import ContractError
from wp03.worker_protocol import WorkerRequest
from wp03.workers.beit3 import Adapter as Beit3Adapter
from wp03.workers.common import run_worker


class FakeAdapter:
    def encode_images(self, paths):
        return np.ones((len(paths), 2), dtype=np.float32)

    def encode_text(self, texts):
        return np.ones((len(texts), 2), dtype=np.float32)


def test_worker_writes_failed_status_for_unknown_operation(tmp_path) -> None:
    request = WorkerRequest.create(
        tmp_path, "encode_images", "fake", "rev", "cpu", "float32", 1, 1, (), ()
    )
    payload = request.to_dict()
    payload["operation"] = "bad"
    request.request_path.write_text(json.dumps(payload), encoding="utf-8")

    exit_code = run_worker(FakeAdapter(), request.request_path)

    status = json.loads(request.status_path.read_text(encoding="utf-8"))
    assert exit_code != 0
    assert status["error_type"] == "unsupported_operation"


def test_beit3_adapter_refuses_missing_model_lock_before_backend_import(tmp_path: Path) -> None:
    with pytest.raises(ContractError, match="model lock"):
        Beit3Adapter.from_runtime(
            checkpoint_path=tmp_path / "beit3.pth",
            lock_path=tmp_path / "beit3.json",
            source_dir=tmp_path / "unilm" / "beit3",
        )


def test_worker_applies_request_batch_size_without_reordering(tmp_path: Path) -> None:
    class BatchRecordingAdapter(FakeAdapter):
        def __init__(self) -> None:
            self.batch_sizes: list[int] = []

        def encode_text(self, texts):
            self.batch_sizes.append(len(texts))
            return np.asarray([[float(index + 1), 0.0] for index in range(len(texts))], dtype=np.float32)

    adapter = BatchRecordingAdapter()
    request = WorkerRequest.create(
        tmp_path, "encode_text", "fake", "rev", "cpu", "float32", 2, 1, (), ("one", "two", "three", "four", "five")
    )
    request.write()

    assert run_worker(adapter, request.request_path) == 0
    assert adapter.batch_sizes == [2, 2, 1]
