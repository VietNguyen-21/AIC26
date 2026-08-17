"""Validated YAML configuration for optional WP04 model runtimes."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


class ConfigError(ValueError):
    pass


def load_config(path: Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as stream:
        config = yaml.safe_load(stream)
    if not isinstance(config, dict) or not isinstance(config.get("modalities"), dict):
        raise ConfigError("config must contain a modalities mapping")
    for modality in ("ocr", "asr", "object", "metadata"):
        settings = config["modalities"].get(modality)
        if not isinstance(settings, dict) or "enabled" not in settings:
            raise ConfigError(f"missing enabled setting for {modality}")
    asr = config["modalities"]["asr"]
    if not isinstance(asr.get("vad"), dict) or not 0.0 <= float(asr["vad"].get("threshold", -1)) <= 1.0:
        raise ConfigError("ASR VAD threshold must be between 0 and 1")
    return config
