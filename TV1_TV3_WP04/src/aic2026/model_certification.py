"""Runtime certification for the selected TV3 competition stack.

Selected stack:
- OCR: DeepSolo + PARSeq external bridge
- ASR/VAD: ChunkFormer + Silero VAD
- Object: RF-DETR

The source-only repository never contains third-party checkpoints or personal
machine paths. Certification hashes the externally configured checkpoints and
optionally initializes the real adapters on the target machine.
"""
from __future__ import annotations

import importlib
import platform
from pathlib import Path
from typing import Any

from .asr import make_asr_adapter, make_vad_adapter
from .config import Settings
from .objects import make_object_adapter
from .ocr import make_ocr_adapter
from .utils import sha256_file, stable_json_hash, utcnow_iso, write_json


class ModelCertificationError(RuntimeError):
    pass


def _module_version(name: str) -> str | None:
    try:
        module = importlib.import_module(name)
    except Exception:
        return None
    return str(getattr(module, "__version__", "runtime"))


def _path_hash(path: Path) -> str:
    if path.is_file():
        return sha256_file(path)
    if not path.is_dir():
        raise ModelCertificationError(f"Model path does not exist: {path}")
    rows = []
    for item in sorted(candidate for candidate in path.rglob("*") if candidate.is_file()):
        rows.append(
            {
                "path": item.relative_to(path).as_posix(),
                "sha256": sha256_file(item),
                "bytes": item.stat().st_size,
            }
        )
    if not rows:
        raise ModelCertificationError(f"Model directory is empty: {path}")
    return stable_json_hash(rows)


def _checkpoint_result(path_value: str | Path | None, expected: str | None) -> dict[str, Any]:
    if path_value is None:
        return {
            "path": None,
            "exists": False,
            "sha256": None,
            "expected_sha256": expected,
            "matches": False,
        }
    path = Path(path_value)
    if not path.exists():
        return {
            "path": str(path),
            "exists": False,
            "sha256": None,
            "expected_sha256": expected,
            "matches": False,
        }
    actual = _path_hash(path)
    return {
        "path": str(path),
        "exists": True,
        "sha256": actual,
        "expected_sha256": expected,
        "matches": expected is None or actual == expected,
    }


def _gpu_info() -> dict[str, Any]:
    result: dict[str, Any] = {"cuda_available": False}
    try:
        import torch

        result.update(
            {
                "torch_version": str(torch.__version__),
                "cuda_available": bool(torch.cuda.is_available()),
                "cuda_version": str(torch.version.cuda),
            }
        )
        if torch.cuda.is_available():
            result.update(
                {
                    "device_count": int(torch.cuda.device_count()),
                    "device_name": str(torch.cuda.get_device_name(0)),
                    "total_memory_bytes": int(torch.cuda.get_device_properties(0).total_memory),
                }
            )
    except Exception as exc:
        result["torch_error"] = f"{type(exc).__name__}: {exc}"
    return result


def certify_models(
    settings: Settings,
    *,
    load_models: bool = False,
    output_path: str | Path | None = None,
) -> dict[str, Any]:
    """Inspect and optionally initialize the selected TV3 model stack."""

    report: dict[str, Any] = {
        "schema_version": "2.0.0",
        "profile": settings.runtime.profile,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "selected_stack": {
            "ocr": "deep_solo_parseq",
            "asr": "chunkformer",
            "vad": "silero",
            "object": "rfdetr",
        },
        "gpu": _gpu_info(),
        "dependencies": {
            name: _module_version(name)
            for name in ["silero_vad", "rfdetr", "torch"]
        },
        "modules": {},
        "created_at_utc": utcnow_iso(),
    }

    ocr = {
        "enabled": settings.ocr.enabled,
        "adapter": settings.ocr.adapter,
        "device": str(settings.ocr.device),
        "allow_runtime_downloads": settings.ocr.allow_runtime_downloads,
        "checkpoint": _checkpoint_result(
            settings.ocr.deep_solo_parseq_checkpoint_path,
            settings.ocr.checkpoint_sha256,
        ),
        "bridge_command_configured": bool(settings.ocr.deep_solo_parseq_command),
    }
    if settings.ocr.enabled and load_models:
        try:
            resolution = make_ocr_adapter(settings.ocr)
            ocr.update(
                load_status="passed",
                selected_adapter=resolution.selected_adapter,
                adapter_version=resolution.adapter.version,
            )
        except Exception as exc:
            ocr.update(load_status="failed", error=f"{type(exc).__name__}: {exc}")
    else:
        ocr["load_status"] = "not_run" if settings.ocr.enabled else "disabled"
    report["modules"]["ocr"] = ocr

    asr = {
        "enabled": settings.asr.enabled,
        "adapter": settings.asr.adapter,
        "vad_adapter": settings.asr.vad_adapter,
        "device": settings.asr.device,
        "language": settings.asr.language,
        "allow_runtime_downloads": settings.asr.allow_runtime_downloads,
        "checkpoint": _checkpoint_result(
            settings.asr.chunkformer_checkpoint_path,
            settings.asr.checkpoint_sha256,
        ),
        "bridge_command_configured": bool(settings.asr.chunkformer_command),
    }
    if settings.asr.enabled and load_models:
        try:
            resolution = make_asr_adapter(settings.asr)
            vad_resolution = make_vad_adapter(settings.asr)
            asr.update(
                load_status="passed",
                selected_adapter=resolution.selected_adapter,
                adapter_version=resolution.adapter.version,
                selected_vad_adapter=vad_resolution.selected_adapter,
                vad_adapter_version=vad_resolution.adapter.version,
            )
        except Exception as exc:
            asr.update(load_status="failed", error=f"{type(exc).__name__}: {exc}")
    else:
        asr["load_status"] = "not_run" if settings.asr.enabled else "disabled"
    report["modules"]["asr"] = asr

    obj = {
        "enabled": settings.object.enabled,
        "adapter": str(settings.object.adapter),
        "device": str(settings.object.device),
        "model_name": settings.object.rfdetr_model_name,
        "allow_runtime_downloads": settings.object.allow_runtime_downloads,
        "checkpoint": _checkpoint_result(
            settings.object.rfdetr_checkpoint_path,
            settings.object.checkpoint_sha256,
        ),
    }
    if settings.object.enabled and load_models:
        try:
            resolution = make_object_adapter(settings.object)
            obj.update(
                load_status="passed",
                selected_adapter=resolution.selected_adapter,
                adapter_version=resolution.adapter.version,
            )
        except Exception as exc:
            obj.update(load_status="failed", error=f"{type(exc).__name__}: {exc}")
    else:
        obj["load_status"] = "not_run" if settings.object.enabled else "disabled"
    report["modules"]["object"] = obj

    selected = (
        settings.ocr.adapter == "deep_solo_parseq"
        and settings.asr.adapter == "chunkformer"
        and settings.asr.vad_adapter == "silero"
        and settings.object.adapter == "rfdetr"
    )
    no_downloads = all(
        not module["enabled"] or not module["allow_runtime_downloads"]
        for module in report["modules"].values()
    )
    hashes_ok = all(
        not module["enabled"]
        or bool(module["checkpoint"].get("matches") and module["checkpoint"].get("sha256"))
        for module in report["modules"].values()
    )
    bridges_ok = (
        (not settings.ocr.enabled or bool(settings.ocr.deep_solo_parseq_command))
        and (not settings.asr.enabled or bool(settings.asr.chunkformer_command))
    )
    load_passed = all(
        not module["enabled"] or module["load_status"] == "passed"
        for module in report["modules"].values()
    )
    all_modalities_enabled = all(module["enabled"] for module in report["modules"].values())

    report["acceptance"] = {
        "selected_stack_only": selected,
        "runtime_downloads_disabled": no_downloads,
        "checkpoint_hashes_verified": hashes_ok,
        "external_bridges_configured": bridges_ok,
        "real_adapter_load_passed": load_passed,
        "all_modalities_enabled": all_modalities_enabled,
        "competition_ready": bool(
            settings.runtime.profile == "competition"
            and selected
            and no_downloads
            and hashes_ok
            and bridges_ok
            and load_passed
            and all_modalities_enabled
        ),
    }
    if output_path is not None:
        write_json(output_path, report)
    return report
