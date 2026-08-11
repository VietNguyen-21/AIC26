from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from aic2026.autoshot import (
    AutoShotRuntimeConfig,
    OfficialAutoShotPredictor,
    collapse_boundary_runs,
)


def test_collapse_boundary_runs_keeps_peak():
    scores = [0.0, 0.3, 0.8, 0.6, 0.0, 0.7, 0.1]
    assert collapse_boundary_runs(scores, 0.296) == [(2, pytest.approx(0.8)), (5, pytest.approx(0.7))]


def test_official_autoshot_bridge_executes_external_runtime(tmp_path: Path):
    torch = pytest.importorskip("torch")
    repo = tmp_path / "AutoShot"
    repo.mkdir()
    (repo / "linear.py").write_text("# fake dependency\n", encoding="utf-8")
    (repo / "supernet_flattransf_3_8_8_8_13_12_0_16_60.py").write_text(
        """
import torch
class TransNetV2Supernet(torch.nn.Module):
    def __init__(self):
        super().__init__()
        self.weight = torch.nn.Parameter(torch.tensor(1.0))
    def forward(self, batch):
        length = batch.shape[2]
        logits = torch.full((1, length), -10.0, device=batch.device)
        logits[0, 3] = 10.0
        logits[0, 7] = 8.0
        return logits
""",
        encoding="utf-8",
    )
    (repo / "utils.py").write_text(
        """
import numpy as np
def get_frames(_path):
    return np.zeros((10, 8, 8, 3), dtype=np.uint8)
def get_batches(frames):
    yield frames
""",
        encoding="utf-8",
    )
    checkpoint = tmp_path / "ckpt.pth"
    torch.save({"net": {"weight": torch.tensor(1.0)}}, checkpoint)
    predictor = OfficialAutoShotPredictor(
        AutoShotRuntimeConfig(repo_root=repo, checkpoint_path=checkpoint, device="cpu")
    )
    result = predictor.predict_boundary_scores(tmp_path / "ignored.mp4")
    assert result.boundary_scores.shape == (10,)
    assert result.boundary_scores[3] > 0.99
    assert result.boundary_scores[7] > 0.99
    assert result.checkpoint_sha256
