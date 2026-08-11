"""Safe source-video discovery, checksums and deterministic corpus manifests."""

from __future__ import annotations

import hashlib
import stat
import zipfile
from pathlib import Path
from typing import Literal

from .contracts import CorpusManifestRecord
from .utils import (
    ensure_relative_to,
    sha256_file,
    utcnow_iso,
    write_json,
    write_jsonl,
    write_parquet_optional,
)

VIDEO_SUFFIXES = {".mp4", ".mkv", ".avi", ".mov", ".webm"}
VideoIdRule = Literal["stem", "relative_path_hash"]


class IngestSecurityError(ValueError):
    """Raised when an archive violates extraction safety limits."""



def safe_extract_zip(
    archive: str | Path,
    destination: str | Path,
    *,
    max_members: int = 10000,
    max_uncompressed_bytes: int = 500 * 1024**3,
    max_compression_ratio: float = 200.0,
) -> Path:
    """Extract a ZIP after path, symlink, count, size and ratio checks."""

    archive = Path(archive)
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as handle:
        infos = handle.infolist()
        if len(infos) > max_members:
            raise IngestSecurityError(f"ZIP has {len(infos)} members; limit is {max_members}")
        total = 0
        for info in infos:
            target = destination / info.filename
            try:
                ensure_relative_to(target, destination)
            except ValueError as exc:
                raise IngestSecurityError(
                    f"ZIP path traversal is forbidden: {info.filename}"
                ) from exc
            mode = info.external_attr >> 16
            if stat.S_ISLNK(mode):
                raise IngestSecurityError(f"ZIP symlink entries are forbidden: {info.filename}")
            total += int(info.file_size)
            if total > max_uncompressed_bytes:
                raise IngestSecurityError(
                    f"ZIP uncompressed size exceeds {max_uncompressed_bytes} bytes"
                )
            if info.file_size > 0:
                compressed = max(1, int(info.compress_size))
                ratio = float(info.file_size) / compressed
                if ratio > max_compression_ratio:
                    raise IngestSecurityError(
                        f"ZIP compression ratio {ratio:.1f} exceeds limit for {info.filename}"
                    )
        handle.extractall(destination)
    return destination


def discover_videos(
    source: str | Path,
    workspace: str | Path | None = None,
    *,
    max_members: int = 10000,
    max_uncompressed_bytes: int = 500 * 1024**3,
    max_compression_ratio: float = 200.0,
) -> tuple[list[Path], str | None, Path]:
    source = Path(source)
    archive_name = None
    if source.is_file() and source.suffix.lower() == ".zip":
        if workspace is None:
            raise ValueError("workspace is required for ZIP input")
        archive_name = source.name
        root = safe_extract_zip(
            source,
            workspace,
            max_members=max_members,
            max_uncompressed_bytes=max_uncompressed_bytes,
            max_compression_ratio=max_compression_ratio,
        )
    elif source.is_dir():
        root = source
    else:
        raise FileNotFoundError(source)
    videos = sorted(
        path
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in VIDEO_SUFFIXES
    )
    return videos, archive_name, root


def _video_id(path: Path, root: Path, rule: VideoIdRule) -> str:
    if rule == "stem":
        return path.stem
    relative = path.resolve().relative_to(root.resolve()).as_posix()
    digest = hashlib.sha256(relative.encode("utf-8")).hexdigest()[:10]
    safe_stem = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in path.stem)
    return f"{safe_stem}__{digest}"


def ingest(
    source: str | Path,
    output_dir: str | Path,
    batch_id: str | None = None,
    workspace: str | Path | None = None,
    *,
    video_id_rule: VideoIdRule = "relative_path_hash",
    max_archive_members: int = 10000,
    max_archive_uncompressed_bytes: int = 500 * 1024**3,
    max_archive_compression_ratio: float = 200.0,
) -> list[CorpusManifestRecord]:
    videos, archive_name, root = discover_videos(
        source,
        workspace,
        max_members=max_archive_members,
        max_uncompressed_bytes=max_archive_uncompressed_bytes,
        max_compression_ratio=max_archive_compression_ratio,
    )
    if not videos:
        raise ValueError(f"No supported videos found under {source}")

    checksum_owner: dict[str, str] = {}
    video_ids: set[str] = set()
    rows: list[CorpusManifestRecord] = []
    for path in videos:
        video_id = _video_id(path, root, video_id_rule)
        checksum = sha256_file(path)
        duplicate_of = checksum_owner.get(checksum)
        status: Literal["accepted", "duplicate", "rejected"] = (
            "duplicate" if duplicate_of else "accepted"
        )
        if video_id in video_ids:
            status = "rejected"
        elif not duplicate_of:
            checksum_owner[checksum] = video_id
        video_ids.add(video_id)
        rows.append(
            CorpusManifestRecord(
                video_id=video_id,
                source_archive=archive_name,
                original_video_path=str(path.resolve()),
                source_sha256=checksum,
                file_size_bytes=path.stat().st_size,
                batch_id=batch_id,
                duplicate_of_video_id=duplicate_of,
                ingest_status=status,
                created_at_utc=utcnow_iso(),
            )
        )

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    payload = [row.model_dump(mode="json") for row in rows]
    write_json(output / "corpus_manifest.json", payload)
    write_jsonl(output / "corpus_manifest.jsonl", payload)
    write_parquet_optional(output / "corpus_manifest.parquet", payload)
    write_jsonl(
        output / "duplicate_videos.jsonl",
        [row for row in payload if row["ingest_status"] == "duplicate"],
    )
    write_jsonl(
        output / "rejected_files.jsonl",
        [row for row in payload if row["ingest_status"] == "rejected"],
    )
    return rows
