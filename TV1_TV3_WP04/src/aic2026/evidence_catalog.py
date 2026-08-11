"""Persistent indexed catalog for OCR, ASR, object and metadata evidence.

The catalog is an acceleration layer. Canonical JSONL artifacts remain the source of
truth and are fingerprinted in ``manifest.json``.  Every connection is short-lived
and closed deterministically so API workers do not leak file descriptors.
"""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Literal

from .contracts import ASRSegment, MetadataRecord, ObjectDetection, OCRDetection
from .utils import read_json, read_jsonl, sha256_file, stable_json_hash, utcnow_iso, write_json

CatalogKind = Literal["ocr", "asr", "object", "metadata"]


class EvidenceCatalogError(RuntimeError):
    """Raised when catalog artifacts are missing, stale or corrupt."""


@dataclass(frozen=True)
class CatalogPage:
    rows: list[dict[str, Any]]
    next_cursor: str | None
    limit: int


@dataclass(frozen=True)
class CatalogBuildResult:
    database_path: Path
    manifest_path: Path
    reused: bool
    counts: dict[str, int]


_SOURCE_FILES: dict[CatalogKind, str] = {
    "ocr": "ocr/ocr.jsonl",
    "asr": "asr/asr.jsonl",
    "object": "objects/objects.jsonl",
    "metadata": "metadata/metadata.jsonl",
}


def _source_fingerprints(run_root: Path) -> dict[str, dict[str, Any]]:
    payload: dict[str, dict[str, Any]] = {}
    for kind, relative in _SOURCE_FILES.items():
        path = run_root / relative
        payload[kind] = {
            "path": relative,
            "exists": path.is_file(),
            "sha256": sha256_file(path) if path.is_file() else None,
            "bytes": path.stat().st_size if path.is_file() else 0,
        }
    return payload


def _connect_readonly(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise EvidenceCatalogError(f"Evidence catalog is missing: {path}")
    uri = f"file:{path.resolve().as_posix()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    return connection


def _cursor_value(cursor: str | None) -> int:
    if cursor is None:
        return 0
    try:
        value = int(cursor)
    except (TypeError, ValueError) as exc:
        raise EvidenceCatalogError("cursor must be a positive integer string") from exc
    if value < 0:
        raise EvidenceCatalogError("cursor must be non-negative")
    return value


def _bounded_limit(limit: int, maximum: int) -> int:
    if limit < 1 or limit > maximum:
        raise EvidenceCatalogError(f"limit must be within [1, {maximum}]")
    return limit


def build_evidence_catalog(
    run_root: str | Path,
    *,
    database_name: str = "evidence.sqlite3",
    force: bool = False,
) -> CatalogBuildResult:
    """Build an atomic, indexed catalog from canonical modality JSONL files."""

    root = Path(run_root)
    catalog_root = root / "evidence_catalog"
    catalog_root.mkdir(parents=True, exist_ok=True)
    database = catalog_root / database_name
    manifest_path = catalog_root / "manifest.json"
    sources = _source_fingerprints(root)
    fingerprint = stable_json_hash({"schema_version": "1.0.0", "sources": sources})

    if not force and database.is_file() and manifest_path.is_file():
        manifest = read_json(manifest_path)
        if manifest.get("build_fingerprint") == fingerprint:
            counts = validate_evidence_catalog(root, verify_sources=True)["counts"]
            return CatalogBuildResult(database, manifest_path, True, counts)

    temporary = database.with_suffix(database.suffix + ".tmp")
    temporary.unlink(missing_ok=True)
    connection = sqlite3.connect(temporary)
    try:
        connection.execute("PRAGMA journal_mode=OFF")
        connection.execute("PRAGMA synchronous=OFF")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.executescript(
            """
            CREATE TABLE catalog_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE ocr(
                row_id INTEGER PRIMARY KEY AUTOINCREMENT,
                detection_id TEXT NOT NULL UNIQUE,
                video_id TEXT NOT NULL,
                frame_id INTEGER NOT NULL,
                timestamp_ms INTEGER NOT NULL,
                raw_json TEXT NOT NULL
            );
            CREATE TABLE asr(
                row_id INTEGER PRIMARY KEY AUTOINCREMENT,
                segment_id TEXT NOT NULL UNIQUE,
                video_id TEXT NOT NULL,
                start_ms INTEGER NOT NULL,
                end_ms INTEGER NOT NULL,
                raw_json TEXT NOT NULL
            );
            CREATE TABLE objects(
                row_id INTEGER PRIMARY KEY AUTOINCREMENT,
                detection_id TEXT NOT NULL UNIQUE,
                video_id TEXT NOT NULL,
                frame_id INTEGER NOT NULL,
                timestamp_ms INTEGER NOT NULL,
                label TEXT NOT NULL,
                canonical_label TEXT,
                confidence REAL,
                below_threshold INTEGER NOT NULL,
                spatial_region TEXT,
                raw_json TEXT NOT NULL
            );
            CREATE TABLE object_aliases(
                detection_id TEXT NOT NULL,
                alias TEXT NOT NULL,
                PRIMARY KEY(detection_id, alias),
                FOREIGN KEY(detection_id) REFERENCES objects(detection_id) ON DELETE CASCADE
            );
            CREATE TABLE metadata(
                row_id INTEGER PRIMARY KEY AUTOINCREMENT,
                metadata_id TEXT NOT NULL UNIQUE,
                video_id TEXT NOT NULL,
                source TEXT NOT NULL,
                raw_json TEXT NOT NULL
            );
            """
        )
        counts = {kind: 0 for kind in _SOURCE_FILES}
        batch_size = 1000

        def chunks(rows: list[tuple[Any, ...]]) -> Iterable[list[tuple[Any, ...]]]:
            for start in range(0, len(rows), batch_size):
                yield rows[start : start + batch_size]

        ocr_rows: list[tuple[Any, ...]] = []
        for raw in read_jsonl(root / _SOURCE_FILES["ocr"]):
            item = OCRDetection.model_validate(raw)
            ocr_rows.append((item.detection_id, item.video_id, item.frame_id, item.timestamp_ms, json.dumps(item.model_dump(mode="json"), ensure_ascii=False)))
        for batch in chunks(ocr_rows):
            connection.executemany("INSERT INTO ocr(detection_id,video_id,frame_id,timestamp_ms,raw_json) VALUES(?,?,?,?,?)", batch)
        counts["ocr"] = len(ocr_rows)

        asr_rows: list[tuple[Any, ...]] = []
        for raw in read_jsonl(root / _SOURCE_FILES["asr"]):
            item = ASRSegment.model_validate(raw)
            asr_rows.append((item.segment_id, item.video_id, item.start_ms, item.end_ms, json.dumps(item.model_dump(mode="json"), ensure_ascii=False)))
        for batch in chunks(asr_rows):
            connection.executemany("INSERT INTO asr(segment_id,video_id,start_ms,end_ms,raw_json) VALUES(?,?,?,?,?)", batch)
        counts["asr"] = len(asr_rows)

        object_rows: list[tuple[Any, ...]] = []
        alias_rows: list[tuple[str, str]] = []
        for raw in read_jsonl(root / _SOURCE_FILES["object"]):
            item = ObjectDetection.model_validate(raw)
            canonical = item.canonical_label or item.label
            object_rows.append((item.detection_id, item.video_id, item.frame_id, item.timestamp_ms, item.label, canonical, item.confidence, int(item.below_threshold), item.spatial_region, json.dumps(item.model_dump(mode="json"), ensure_ascii=False)))
            aliases = {item.label.casefold(), canonical.casefold(), *(alias.casefold() for alias in item.label_aliases)}
            alias_rows.extend((item.detection_id, alias) for alias in sorted(aliases) if alias)
        for batch in chunks(object_rows):
            connection.executemany("INSERT INTO objects(detection_id,video_id,frame_id,timestamp_ms,label,canonical_label,confidence,below_threshold,spatial_region,raw_json) VALUES(?,?,?,?,?,?,?,?,?,?)", batch)
        for batch in chunks(alias_rows):
            connection.executemany("INSERT INTO object_aliases(detection_id,alias) VALUES(?,?)", batch)
        counts["object"] = len(object_rows)

        metadata_rows: list[tuple[Any, ...]] = []
        for raw in read_jsonl(root / _SOURCE_FILES["metadata"]):
            item = MetadataRecord.model_validate(raw)
            metadata_rows.append((item.metadata_id, item.video_id, str(item.source), json.dumps(item.model_dump(mode="json"), ensure_ascii=False)))
        for batch in chunks(metadata_rows):
            connection.executemany("INSERT INTO metadata(metadata_id,video_id,source,raw_json) VALUES(?,?,?,?)", batch)
        counts["metadata"] = len(metadata_rows)

        connection.executescript(
            """
            CREATE INDEX idx_ocr_video_frame ON ocr(video_id, frame_id, row_id);
            CREATE INDEX idx_asr_video_time ON asr(video_id, start_ms, end_ms, row_id);
            CREATE INDEX idx_object_video_frame ON objects(video_id, frame_id, row_id);
            CREATE INDEX idx_object_label ON objects(canonical_label, below_threshold, row_id);
            CREATE INDEX idx_object_spatial ON objects(spatial_region, canonical_label, row_id);
            CREATE INDEX idx_object_alias ON object_aliases(alias, detection_id);
            CREATE INDEX idx_metadata_video_source ON metadata(video_id, source, row_id);
            """
        )
        meta = {
            "schema_version": "1.0.0",
            "build_fingerprint": fingerprint,
            "counts": counts,
            "sources": sources,
            "created_at_utc": utcnow_iso(),
        }
        connection.executemany(
            "INSERT INTO catalog_meta(key,value) VALUES(?,?)",
            [(key, json.dumps(value, ensure_ascii=False)) for key, value in meta.items()],
        )
        connection.commit()
        connection.execute("PRAGMA optimize")
    except Exception:
        connection.close()
        temporary.unlink(missing_ok=True)
        raise
    connection.close()
    os.replace(temporary, database)
    manifest = {
        "schema_version": "1.0.0",
        "database_path": str(database.relative_to(root)),
        "database_sha256": sha256_file(database),
        "build_fingerprint": fingerprint,
        "counts": counts,
        "sources": sources,
        "created_at_utc": utcnow_iso(),
    }
    write_json(manifest_path, manifest)
    return CatalogBuildResult(database, manifest_path, False, counts)


def validate_evidence_catalog(run_root: str | Path, *, verify_sources: bool = True) -> dict[str, Any]:
    root = Path(run_root)
    manifest_path = root / "evidence_catalog" / "manifest.json"
    if not manifest_path.is_file():
        raise EvidenceCatalogError("Evidence catalog manifest is missing")
    manifest = read_json(manifest_path)
    database = root / str(manifest.get("database_path", "evidence_catalog/evidence.sqlite3"))
    if not database.is_file():
        raise EvidenceCatalogError("Evidence catalog database is missing")
    if sha256_file(database) != manifest.get("database_sha256"):
        raise EvidenceCatalogError("Evidence catalog database checksum mismatch")
    if verify_sources and _source_fingerprints(root) != manifest.get("sources"):
        raise EvidenceCatalogError("Evidence catalog is stale relative to canonical artifacts")
    with closing(_connect_readonly(database)) as connection:
        integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
        if integrity != "ok":
            raise EvidenceCatalogError(f"Evidence catalog integrity check failed: {integrity}")
        counts = {
            "ocr": int(connection.execute("SELECT COUNT(*) FROM ocr").fetchone()[0]),
            "asr": int(connection.execute("SELECT COUNT(*) FROM asr").fetchone()[0]),
            "object": int(connection.execute("SELECT COUNT(*) FROM objects").fetchone()[0]),
            "metadata": int(connection.execute("SELECT COUNT(*) FROM metadata").fetchone()[0]),
        }
    if counts != manifest.get("counts"):
        raise EvidenceCatalogError("Evidence catalog row counts differ from manifest")
    return {"status": "ready", "counts": counts, "manifest": manifest}


class EvidenceCatalog:
    """Read-only indexed evidence access with cursor pagination."""

    def __init__(self, run_root: str | Path, *, maximum_page_size: int = 1000):
        self.run_root = Path(run_root)
        manifest = read_json(self.run_root / "evidence_catalog" / "manifest.json")
        self.database_path = self.run_root / str(manifest["database_path"])
        self.maximum_page_size = maximum_page_size

    def _page(self, table: str, where: str, parameters: list[Any], *, limit: int, cursor: str | None) -> CatalogPage:
        page_limit = _bounded_limit(limit, self.maximum_page_size)
        after = _cursor_value(cursor)
        query = f"SELECT row_id,raw_json FROM {table} WHERE row_id>? {where} ORDER BY row_id LIMIT ?"
        with closing(_connect_readonly(self.database_path)) as connection:
            records = connection.execute(query, [after, *parameters, page_limit + 1]).fetchall()
        has_more = len(records) > page_limit
        selected = records[:page_limit]
        rows = [json.loads(str(row["raw_json"])) for row in selected]
        next_cursor = str(selected[-1]["row_id"]) if has_more and selected else None
        return CatalogPage(rows, next_cursor, page_limit)

    def list_ocr(self, *, video_id: str | None = None, frame_id: int | None = None, limit: int = 100, cursor: str | None = None) -> CatalogPage:
        clauses: list[str] = []
        params: list[Any] = []
        if video_id is not None:
            clauses.append("video_id=?")
            params.append(video_id)
        if frame_id is not None:
            clauses.append("frame_id=?")
            params.append(frame_id)
        where = (" AND " + " AND ".join(clauses)) if clauses else ""
        return self._page("ocr", where, params, limit=limit, cursor=cursor)

    def get_ocr(self, detection_id: str) -> dict[str, Any] | None:
        with closing(_connect_readonly(self.database_path)) as connection:
            row = connection.execute("SELECT raw_json FROM ocr WHERE detection_id=?", (detection_id,)).fetchone()
        return json.loads(str(row[0])) if row else None

    def list_asr(self, *, video_id: str | None = None, start_ms: int | None = None, end_ms: int | None = None, limit: int = 100, cursor: str | None = None) -> CatalogPage:
        clauses: list[str] = []
        params: list[Any] = []
        if video_id is not None:
            clauses.append("video_id=?")
            params.append(video_id)
        if start_ms is not None:
            clauses.append("end_ms>=?")
            params.append(start_ms)
        if end_ms is not None:
            clauses.append("start_ms<=?")
            params.append(end_ms)
        where = (" AND " + " AND ".join(clauses)) if clauses else ""
        return self._page("asr", where, params, limit=limit, cursor=cursor)

    def get_asr_context(self, segment_id: str, radius_ms: int) -> dict[str, Any] | None:
        with closing(_connect_readonly(self.database_path)) as connection:
            target = connection.execute("SELECT video_id,start_ms,end_ms FROM asr WHERE segment_id=?", (segment_id,)).fetchone()
            if target is None:
                return None
            lower = max(0, int(target["start_ms"]) - radius_ms)
            upper = int(target["end_ms"]) + radius_ms
            rows = connection.execute("SELECT raw_json FROM asr WHERE video_id=? AND end_ms>=? AND start_ms<=? ORDER BY start_ms,end_ms", (str(target["video_id"]), lower, upper)).fetchall()
        return {"target_segment_id": segment_id, "video_id": str(target["video_id"]), "window_start_ms": lower, "window_end_ms": upper, "segments": [json.loads(str(row[0])) for row in rows]}

    def list_objects(self, *, video_id: str | None = None, frame_id: int | None = None, label: str | None = None, min_confidence: float | None = None, include_below_threshold: bool = True, limit: int = 100, cursor: str | None = None) -> CatalogPage:
        clauses: list[str] = []
        params: list[Any] = []
        if video_id is not None:
            clauses.append("video_id=?")
            params.append(video_id)
        if frame_id is not None:
            clauses.append("frame_id=?")
            params.append(frame_id)
        if min_confidence is not None:
            clauses.append("COALESCE(confidence,0)>=?")
            params.append(min_confidence)
        if not include_below_threshold:
            clauses.append("below_threshold=0")
        if label is not None:
            clauses.append("detection_id IN (SELECT detection_id FROM object_aliases WHERE alias=?)")
            params.append(label.casefold())
        where = (" AND " + " AND ".join(clauses)) if clauses else ""
        return self._page("objects", where, params, limit=limit, cursor=cursor)

    def representative_object_vocabulary(self) -> list[ObjectDetection]:
        with closing(_connect_readonly(self.database_path)) as connection:
            rows = connection.execute(
                "SELECT raw_json FROM objects GROUP BY canonical_label ORDER BY canonical_label"
            ).fetchall()
        return [ObjectDetection.model_validate(json.loads(str(row[0]))) for row in rows]

    def object_rows_for_labels(self, labels: list[str]) -> list[ObjectDetection]:
        with closing(_connect_readonly(self.database_path)) as connection:
            if labels:
                placeholders = ",".join("?" for _ in labels)
                rows = connection.execute(
                    f"""SELECT DISTINCT o.raw_json FROM objects o JOIN object_aliases a ON a.detection_id=o.detection_id WHERE o.below_threshold=0 AND a.alias IN ({placeholders})""",
                    [label.casefold() for label in labels],
                ).fetchall()
            else:
                rows = connection.execute("SELECT raw_json FROM objects WHERE below_threshold=0").fetchall()
        return [ObjectDetection.model_validate(json.loads(str(row[0]))) for row in rows]

    def list_metadata(self, *, video_id: str | None = None, source: str | None = None, limit: int = 100, cursor: str | None = None) -> CatalogPage:
        clauses: list[str] = []
        params: list[Any] = []
        if video_id is not None:
            clauses.append("video_id=?")
            params.append(video_id)
        if source is not None:
            clauses.append("source=?")
            params.append(source)
        where = (" AND " + " AND ".join(clauses)) if clauses else ""
        return self._page("metadata", where, params, limit=limit, cursor=cursor)
