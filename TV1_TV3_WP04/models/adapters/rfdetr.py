"""RF-DETR integration bridge for the selected TV3 object detector.

The production implementation lives in :mod:`aic2026.objects`. This file keeps
model ownership discoverable for the team and exposes a tiny factory without
bundling third-party repositories or checkpoints in the source-only release.
"""

from __future__ import annotations

from pathlib import Path

from aic2026.objects import RFDETRAdapter


def create_rfdetr_adapter(
    *,
    model_name: str = "base",
    checkpoint_path: str | Path | None = None,
    device: str = "auto",
) -> RFDETRAdapter:
    return RFDETRAdapter(
        model_name=model_name,
        checkpoint_path=Path(checkpoint_path) if checkpoint_path else None,
        device=device,
    )
