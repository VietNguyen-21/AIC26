"""Official AutoShot external-runtime adapter.

This source-only repository does not redistribute the AutoShot repository or
checkpoint. Configure their external paths under ``keyframes``. The production
implementation lives in :mod:`aic2026.autoshot` so it is installed with the
Python package.
"""

from aic2026.autoshot import (  # noqa: F401
    AutoShotError,
    AutoShotPrediction,
    AutoShotRuntimeConfig,
    OfficialAutoShotPredictor,
    collapse_boundary_runs,
)

__all__ = [
    "AutoShotError",
    "AutoShotPrediction",
    "AutoShotRuntimeConfig",
    "OfficialAutoShotPredictor",
    "collapse_boundary_runs",
]
