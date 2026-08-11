"""AutoShot integration helpers used by the hybrid shot and keyframe pipeline."""

from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import numpy as np

from .utils import sha256_file


class AutoShotError(RuntimeError):
    """Raised when the external official AutoShot runtime cannot be used."""


@dataclass(frozen=True)
class AutoShotRuntimeConfig:
    repo_root: Path
    checkpoint_path: Path
    device: str = "auto"
    model_filename: str = "supernet_flattransf_3_8_8_8_13_12_0_16_60.py"
    checkpoint_key: str = "net"
    threshold: float = 0.296
    min_loaded_parameter_ratio: float = 0.99


@dataclass(frozen=True)
class AutoShotPrediction:
    boundary_scores: np.ndarray
    model_name: str
    model_version: str
    checkpoint_sha256: str


def _load_module(module_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise AutoShotError(f"Cannot import AutoShot module from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def collapse_boundary_runs(scores: Iterable[float], threshold: float) -> list[tuple[int, float]]:
    """Collapse adjacent positive boundary frames to one peak per transition."""

    values = np.asarray(list(scores), dtype=np.float32).reshape(-1)
    positives = np.flatnonzero(values >= float(threshold))
    if positives.size == 0:
        return []
    groups: list[list[int]] = [[int(positives[0])]]
    for index in positives[1:]:
        value = int(index)
        if value == groups[-1][-1] + 1:
            groups[-1].append(value)
        else:
            groups.append([value])
    output: list[tuple[int, float]] = []
    for group in groups:
        peak = max(group, key=lambda frame_id: float(values[frame_id]))
        output.append((peak, float(values[peak])))
    return output


class OfficialAutoShotPredictor:
    """Bridge to the official AutoShot CVPRW 2023 repository.

    The source-only release deliberately does not redistribute the external
    repository or checkpoint. When the user provides both paths, this class
    imports the official architecture and follows the inference procedure shown
    in the repository's evaluation script: batches from ``utils.get_batches``,
    sigmoid logits, then retain the central 50 predictions per 100-frame batch.
    """

    def __init__(self, config: AutoShotRuntimeConfig):
        self.config = config
        self._model: Any | None = None
        self._torch: Any | None = None
        self._utils: Any | None = None
        self._device: str | None = None

    @property
    def model_path(self) -> Path:
        return self.config.repo_root / self.config.model_filename

    @property
    def utils_path(self) -> Path:
        return self.config.repo_root / "utils.py"

    def validate_runtime(self) -> None:
        if not self.config.repo_root.is_dir():
            raise AutoShotError(f"AutoShot repository not found: {self.config.repo_root}")
        if not self.model_path.is_file():
            raise AutoShotError(f"AutoShot model source not found: {self.model_path}")
        if not self.utils_path.is_file():
            raise AutoShotError(f"AutoShot utils.py not found: {self.utils_path}")
        if not self.config.checkpoint_path.is_file():
            raise AutoShotError(
                f"AutoShot checkpoint not found: {self.config.checkpoint_path}"
            )

    def _load(self) -> None:
        if self._model is not None:
            return
        self.validate_runtime()
        try:
            import torch
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise AutoShotError("AutoShot requires PyTorch") from exc

        requested = self.config.device
        if requested == "auto":
            device = "cuda" if torch.cuda.is_available() else "cpu"
        elif requested == "cuda" and not torch.cuda.is_available():
            raise AutoShotError("AutoShot device='cuda' but CUDA is unavailable")
        else:
            device = requested

        repo_text = str(self.config.repo_root.resolve())
        inserted = repo_text not in sys.path
        if inserted:
            sys.path.insert(0, repo_text)
        try:
            architecture = _load_module("aic2026_external_autoshot_model", self.model_path)
            utilities = _load_module("aic2026_external_autoshot_utils", self.utils_path)
            model_cls = getattr(architecture, "TransNetV2Supernet", None)
            if model_cls is None:
                raise AutoShotError(
                    "Official AutoShot architecture does not expose TransNetV2Supernet"
                )
            model = model_cls().eval()
            checkpoint = torch.load(
                self.config.checkpoint_path,
                map_location=device,
                weights_only=False,
            )
            state = checkpoint
            if isinstance(checkpoint, dict) and self.config.checkpoint_key in checkpoint:
                state = checkpoint[self.config.checkpoint_key]
            if not isinstance(state, dict):
                raise AutoShotError("AutoShot checkpoint does not contain a state dictionary")
            current = model.state_dict()
            compatible: dict[str, Any] = {}
            mismatched_shapes: list[str] = []
            unexpected = sorted(key for key in state if key not in current)
            for key, value in state.items():
                if key not in current:
                    continue
                if tuple(getattr(value, "shape", ())) != tuple(current[key].shape):
                    mismatched_shapes.append(key)
                    continue
                compatible[key] = value
            if not compatible:
                raise AutoShotError("No shape-compatible parameters found in checkpoint")
            loaded_parameters = sum(int(value.numel()) for value in compatible.values())
            total_parameters = sum(int(value.numel()) for value in current.values())
            loaded_ratio = loaded_parameters / max(1, total_parameters)
            missing = sorted(key for key in current if key not in compatible)
            if loaded_ratio < float(self.config.min_loaded_parameter_ratio):
                raise AutoShotError(
                    "AutoShot checkpoint coverage is unsafe: "
                    f"loaded_ratio={loaded_ratio:.4f}, required="
                    f"{self.config.min_loaded_parameter_ratio:.4f}, "
                    f"missing_keys={len(missing)}, unexpected_keys={len(unexpected)}, "
                    f"shape_mismatches={len(mismatched_shapes)}"
                )
            load_result = model.load_state_dict(compatible, strict=False)
            if mismatched_shapes or load_result.unexpected_keys:
                raise AutoShotError(
                    "AutoShot checkpoint contains incompatible tensors: "
                    f"shape_mismatches={mismatched_shapes[:10]}, "
                    f"unexpected={list(load_result.unexpected_keys)[:10]}"
                )
            model = model.to(device).eval()
        finally:
            if inserted:
                try:
                    sys.path.remove(repo_text)
                except ValueError:  # pragma: no cover
                    pass

        self._torch = torch
        self._utils = utilities
        self._model = model
        self._device = device

    @staticmethod
    def _central_predictions(probabilities: np.ndarray) -> np.ndarray:
        values = np.asarray(probabilities, dtype=np.float32).reshape(-1)
        if values.size >= 100:
            return values[25:75]
        return values

    def predict_boundary_scores(self, video_path: str | Path) -> AutoShotPrediction:
        self._load()
        assert self._torch is not None
        assert self._utils is not None
        assert self._model is not None
        assert self._device is not None

        frames = self._utils.get_frames(str(video_path))
        predictions: list[np.ndarray] = []
        with self._torch.inference_mode():
            for batch in self._utils.get_batches(frames):
                array = np.asarray(batch)
                if array.ndim != 4:
                    raise AutoShotError(
                        f"AutoShot batch must be [T,H,W,C], received shape {array.shape}"
                    )
                tensor = self._torch.from_numpy(
                    array.transpose((3, 0, 1, 2))[np.newaxis, ...]
                ).float().to(self._device)
                logits = self._model(tensor)
                if isinstance(logits, tuple):
                    logits = logits[0]
                probabilities = self._torch.sigmoid(logits[0]).detach().cpu().numpy()
                predictions.append(self._central_predictions(probabilities))

        if not predictions:
            raise AutoShotError("AutoShot returned no prediction batches")
        scores = np.concatenate(predictions, axis=0)[: len(frames)]
        model_version = (
            f"official-cvprw2023:{self.config.model_filename}:"
            f"{self.config.checkpoint_path.name}"
        )
        return AutoShotPrediction(
            boundary_scores=scores.astype(np.float32, copy=False),
            model_name="AutoShot",
            model_version=model_version,
            checkpoint_sha256=sha256_file(self.config.checkpoint_path),
        )
