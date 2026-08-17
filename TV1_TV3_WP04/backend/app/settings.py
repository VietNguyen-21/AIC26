from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class BackendRuntimeSettings:
    run_id: str
    config_path: Path
    cors_origins: list[str] | None = None

    @classmethod
    def from_environment(cls) -> "BackendRuntimeSettings":
        run_id = os.getenv("AIC_RUN_ID", "tv1-tv3-dev-v1")
        config_path = Path(os.getenv("AIC_CONFIG", "configs/default.yaml"))
        raw = os.getenv("AIC_CORS_ORIGINS", "").strip()
        origins = [item.strip() for item in raw.split(",") if item.strip()] or None
        return cls(run_id=run_id, config_path=config_path, cors_origins=origins)
