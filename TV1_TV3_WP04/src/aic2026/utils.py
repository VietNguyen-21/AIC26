"""Shared deterministic I/O, hashing, normalization, and path-safety utilities."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: str | Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stable_json_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _atomic_replace_bytes(path: str | Path, payload: bytes) -> None:
    """Write bytes to a same-directory temporary file and atomically replace target.

    A same-directory temporary file is used because ``os.replace`` is only
    guaranteed to be atomic on the same filesystem. A best-effort fsync keeps a
    completed module from being registered before its bytes reach the filesystem.
    """

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def atomic_write_text(path: str | Path, text: str, encoding: str = "utf-8") -> None:
    _atomic_replace_bytes(path, text.encode(encoding))


def write_json(path: str | Path, value: Any) -> None:
    atomic_write_text(
        path,
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True),
    )


def read_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_jsonl(path: str | Path, rows: Iterable[Any]) -> None:
    lines: list[str] = []
    for row in rows:
        if hasattr(row, "model_dump"):
            row = row.model_dump(mode="json")
        lines.append(json.dumps(row, ensure_ascii=False))
    payload = "\n".join(lines)
    if lines:
        payload += "\n"
    atomic_write_text(path, payload)


def read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    target = Path(path)
    if not target.exists():
        return []
    return [
        json.loads(line)
        for line in target.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def write_parquet_optional(path: str | Path, rows: Sequence[dict[str, Any]]) -> bool:
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError:
        return False
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        pq.write_table(pa.Table.from_pylist(list(rows)), temporary)
        os.replace(temporary, target)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return True


def atomic_cv2_imwrite(path: str | Path, image, params: Sequence[int] | None = None) -> None:
    """Atomically write an OpenCV image without exposing a partial JPEG/PNG."""

    import cv2

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    suffix = target.suffix or ".img"
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.stem}.", suffix=suffix, dir=target.parent
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        ok = cv2.imwrite(str(temporary), image, list(params or []))
        if not ok:
            raise RuntimeError(f"Could not write image: {target}")
        os.replace(temporary, target)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def run_command(
    command: list[str], timeout: int | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command, check=True, text=True, capture_output=True, timeout=timeout
    )


def ensure_relative_to(path: Path, root: Path) -> None:
    path.resolve().relative_to(root.resolve())


def parse_fraction(value: str | None) -> float | None:
    if not value or value in {"0/0", "N/A"}:
        return None
    if "/" in value:
        left, right = value.split("/", 1)
        denominator = float(right)
        return None if denominator == 0 else float(left) / denominator
    return float(value)


def normalized_tokens(text: str) -> list[str]:
    import unicodedata

    text = unicodedata.normalize("NFKC", text).lower()
    text = re.sub(r"[^\wÀ-ỹ]+", " ", text, flags=re.UNICODE)
    return [token for token in text.split() if token]


def cosine_normalize(matrix):
    import numpy as np

    arr = np.asarray(matrix, dtype=np.float32)
    norms = np.linalg.norm(arr, axis=-1, keepdims=True)
    norms = np.where(norms == 0, 1.0, norms)
    return arr / norms


def remove_tree(path: str | Path) -> None:
    target = Path(path)
    if target.exists():
        shutil.rmtree(target)


def relative_artifact_paths(paths: Iterable[str | Path], root: str | Path) -> list[str]:
    root_path = Path(root).resolve()
    result: list[str] = []
    for value in paths:
        path = Path(value)
        if not path.exists():
            continue
        if path.is_dir():
            files = sorted(item for item in path.rglob("*") if item.is_file())
        else:
            files = [path]
        for file_path in files:
            try:
                result.append(file_path.resolve().relative_to(root_path).as_posix())
            except ValueError:
                # External source files are never recorded as generated artifacts.
                continue
    return sorted(set(result))


def artifact_checksums(paths: Iterable[str | Path], root: str | Path) -> dict[str, str]:
    root_path = Path(root)
    output: dict[str, str] = {}
    for relative in relative_artifact_paths(paths, root_path):
        file_path = root_path / relative
        output[relative] = sha256_file(file_path)
    return output
