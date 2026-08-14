"""Source-only release auditing and deterministic ZIP packaging helpers."""

from __future__ import annotations

import re
import zipfile
from pathlib import Path

FORBIDDEN_SUFFIXES = {
    ".mp4",
    ".mkv",
    ".avi",
    ".mov",
    ".webm",
    ".wav",
    ".flac",
    ".faiss",
    ".npy",
    ".npz",
    ".pt",
    ".pth",
    ".ckpt",
    ".onnx",
    ".pyc",
    ".rar",
    ".7z",
    ".xlsx",
    ".xlsm",
}

SECRET_PATTERNS = [
    re.compile(
        r"(?i)(api[_-]?key|secret|token|password)\s*[=:]\s*['\"]?[A-Za-z0-9_\-]{16,}"
    ),
    re.compile(r"-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----"),
]

# Detect machine-specific absolute paths while allowing URLs and relative examples.
ABSOLUTE_PATTERNS = [
    re.compile(r"(?<![A-Za-z0-9])(?:[A-Za-z]):[\\/](?![\\/])"),
    re.compile("/" + r"home/[^/\s]+/"),
    re.compile("/" + r"Users/[^/\s]+/"),
    re.compile("/" + r"mnt/[A-Za-z]/"),
]

TEXT_SUFFIXES = {
    ".py",
    ".md",
    ".yaml",
    ".yml",
    ".json",
    ".toml",
    ".txt",
    ".tsx",
    ".ts",
    ".js",
}


def _directory_issue(relative_path: Path) -> str | None:
    parts = relative_path.parts
    if any(
        part in {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".venv", ".tox"}
        for part in parts
    ):
        return "cache_artifact"
    if ".git" in parts:
        return "vcs_metadata"
    joined = "/".join(parts)
    if joined == "configs/local" or joined.startswith("configs/local/"):
        return "machine_local_config"
    if joined == "evaluation/ground_truth" or joined.startswith("evaluation/ground_truth/"):
        return "ground_truth_artifact"
    if joined == "scripts/ground_truth" or joined.startswith("scripts/ground_truth/"):
        return "ground_truth_tooling"
    if parts and parts[0] == "TEST_DATA":
        return "raw_or_ground_truth_data"
    if parts and parts[0] in {"data", "reports", "external_data", "outputs"}:
        return "runtime_artifact"
    return None


def audit_release(root: str | Path) -> list[dict[str, str]]:
    """Return source-release hygiene issues without mutating ``root``."""

    root = Path(root).resolve()
    issues: list[dict[str, str]] = []

    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root)
        rel_text = rel.as_posix()

        if path.is_symlink():
            issues.append({"path": rel_text, "reason": "symlink"})
            continue
        if not path.is_file():
            continue

        directory_reason = _directory_issue(rel)
        if directory_reason:
            issues.append({"path": rel_text, "reason": directory_reason})

        suffix = path.suffix.lower()
        if suffix in FORBIDDEN_SUFFIXES:
            issues.append({"path": rel_text, "reason": "forbidden_extension"})
        if suffix == ".zip":
            issues.append({"path": rel_text, "reason": "archive_inside_release"})
        if path.stat().st_size > 50 * 1024 * 1024:
            issues.append({"path": rel_text, "reason": "large_file"})

        if suffix not in TEXT_SUFFIXES:
            continue
        if len(rel.parts) >= 2 and rel.parts[:2] == ("docs", "reference"):
            continue

        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

        for pattern in SECRET_PATTERNS:
            if pattern.search(text):
                issues.append({"path": rel_text, "reason": "possible_secret"})
                break
        for pattern in ABSOLUTE_PATTERNS:
            if pattern.search(text):
                issues.append({"path": rel_text, "reason": "absolute_path"})
                break

    return issues


def package_release(root: str | Path, output: str | Path) -> Path:
    """Create a deterministic source-only ZIP after a successful audit."""

    root = Path(root).resolve()
    issues = audit_release(root)
    if issues:
        raise RuntimeError(f"Release audit failed: {issues[:10]}")

    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            archive_name = path.relative_to(root.parent).as_posix()
            info = zipfile.ZipInfo(archive_name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, path.read_bytes())

    return output
