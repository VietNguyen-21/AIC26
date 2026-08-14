"""Persistent field-aware local/remote text indexing for OCR, ASR, and metadata."""

from __future__ import annotations

import json
import math
import os
import re
import sqlite3
import threading
import unicodedata
from collections import Counter, OrderedDict, defaultdict
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Protocol, Sequence
from urllib.parse import urlparse

from .contracts import (
    ASRSegment,
    MetadataRecord,
    OCRDetection,
    SearchCandidate,
    TextIndexManifest,
)
from .utils import (
    normalized_tokens,
    read_json,
    read_jsonl,
    sha256_file,
    stable_json_hash,
    utcnow_iso,
    write_json,
    write_jsonl,
)


class TextIndexError(RuntimeError):
    """Base error for persistent text indexing and search."""


class TextIndexDependencyError(TextIndexError):
    """Raised when an explicitly requested optional text backend is unavailable."""


class TextIndexValidationError(TextIndexError):
    """Raised when a text index artifact is missing, stale, or corrupt."""


REMOTE_FIELD_MAPPING_VERSION = "text-fields-v2"
REMOTE_META_KEY = "aic2026_text_index"


@dataclass
class TextDocument:
    """Canonical document used by every text backend.

    The first three fields preserve compatibility with the earlier in-memory BM25
    helpers. ``fields`` carries the field-aware persistent retrieval representation.
    """

    doc_id: str
    text: str
    metadata: dict[str, Any]
    fields: dict[str, str] = field(default_factory=dict)
    source: str | None = None

    def __post_init__(self) -> None:
        if self.source is None:
            self.source = str(self.metadata.get("source", "metadata"))
        if not self.fields:
            self.fields = {"text": self.text}

    def as_row(self) -> dict[str, Any]:
        return {
            "doc_id": self.doc_id,
            "source": self.source,
            "text": self.text,
            "fields": self.fields,
            "metadata": self.metadata,
        }


@dataclass
class TextSearchHit:
    score: float
    document: TextDocument
    matched_fields: list[str] = field(default_factory=list)
    match_modes: list[str] = field(default_factory=list)
    term_contributions: dict[str, float] = field(default_factory=dict)
    requested_backend: str | None = None
    actual_backend: str | None = None
    fallback_used: bool = False
    fallback_reason: str | None = None


@dataclass
class TextIndexBuildResult:
    manifest: TextIndexManifest
    reused: bool
    requested_adapter: str
    selected_adapter: str
    degraded_reason: str | None = None


class TextIndexAdapter(Protocol):
    """Common build, load, validate, and search contract for local and remote text indexes."""
    name: str
    version: str

    def build(self, documents: Iterable[TextDocument]) -> None: ...

    def search(
        self,
        query: str,
        k: int = 100,
        *,
        source_filter: set[str] | None = None,
    ) -> list[TextSearchHit]: ...

    def validate(self) -> dict[str, Any]: ...

    def stats(self) -> dict[str, Any]: ...


class LocalBM25:
    """Legacy in-memory BM25 kept for unit compatibility and tiny diagnostics.

    Production query paths no longer call ``fit``. They use
    :class:`LocalPersistentBM25` and the persisted SQLite artifact.
    """

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.docs: list[TextDocument] = []
        self.term_freqs: list[Counter[str]] = []
        self.doc_freq: defaultdict[str, int] = defaultdict(int)
        self.avgdl = 0.0

    def fit(self, docs: list[TextDocument]):
        self.docs = docs
        self.term_freqs = []
        self.doc_freq.clear()
        lengths = []
        for doc in docs:
            tf = Counter(normalized_tokens(doc.text))
            self.term_freqs.append(tf)
            lengths.append(sum(tf.values()))
            for term in tf:
                self.doc_freq[term] += 1
        self.avgdl = sum(lengths) / max(1, len(lengths))
        return self

    def search(self, query: str, k: int = 100):
        tokens = normalized_tokens(query)
        n = len(self.docs)
        scored = []
        for index, (doc, tf) in enumerate(zip(self.docs, self.term_freqs)):
            dl = sum(tf.values())
            score = 0.0
            for term in tokens:
                df = self.doc_freq.get(term, 0)
                if df == 0:
                    continue
                idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
                freq = tf.get(term, 0)
                score += idf * freq * (self.k1 + 1) / (
                    freq + self.k1 * (1 - self.b + self.b * dl / max(self.avgdl, 1))
                )
            if score > 0:
                scored.append((score, index, doc))
        scored.sort(reverse=True, key=lambda item: item[0])
        return scored[:k]


def normalize_text(value: str) -> str:
    text = unicodedata.normalize("NFC", str(value or "")).lower()
    text = re.sub(r"\s+", " ", text).strip()
    return text


def strip_diacritics(value: str) -> str:
    text = unicodedata.normalize("NFD", str(value or ""))
    text = "".join(char for char in text if unicodedata.category(char) != "Mn")
    return unicodedata.normalize("NFC", text).replace("đ", "d").replace("Đ", "D")


def _char_ngrams(value: str, min_n: int, max_n: int, limit: int) -> list[str]:
    compact = re.sub(r"\s+", " ", normalize_text(strip_diacritics(value)))
    padded = f" {compact} " if compact else ""
    output: list[str] = []
    seen: set[str] = set()
    for size in range(min_n, max_n + 1):
        for index in range(max(0, len(padded) - size + 1)):
            gram = padded[index : index + size]
            if gram.strip() and gram not in seen:
                seen.add(gram)
                output.append(gram)
                if len(output) >= limit:
                    return output
    return output


def _field_tokens(field_name: str, value: str) -> list[str]:
    if field_name.endswith("char_ngrams"):
        return [token for token in str(value).split("\u241f") if token]
    return normalized_tokens(value)


def _quoted_phrases(query: str) -> list[str]:
    phrases = [normalize_text(item) for item in re.findall(r'["“”](.+?)["“”]', query)]
    if not phrases:
        normalized = normalize_text(query)
        if len(normalized_tokens(normalized)) >= 2:
            phrases.append(normalized)
    return list(dict.fromkeys(item for item in phrases if item))


def _contains_token_phrase(value: str, phrase_tokens: Sequence[str]) -> bool:
    """Return True only when *phrase_tokens* occur as contiguous full tokens.

    This deliberately avoids substring matching (for example, ``hoc`` must not
    match ``hocbong``) while preserving phrase matches across normalized
    whitespace and punctuation boundaries.
    """

    if not phrase_tokens:
        return False
    value_tokens = normalized_tokens(value)
    phrase_length = len(phrase_tokens)
    if phrase_length > len(value_tokens):
        return False
    expected = list(phrase_tokens)
    return any(
        value_tokens[index : index + phrase_length] == expected
        for index in range(len(value_tokens) - phrase_length + 1)
    )


def _edit_distance_limited(left: str, right: str, maximum: int) -> int:
    if abs(len(left) - len(right)) > maximum:
        return maximum + 1
    previous = list(range(len(right) + 1))
    for i, left_char in enumerate(left, start=1):
        current = [i]
        row_minimum = i
        for j, right_char in enumerate(right, start=1):
            cost = 0 if left_char == right_char else 1
            value = min(current[j - 1] + 1, previous[j] + 1, previous[j - 1] + cost)
            current.append(value)
            row_minimum = min(row_minimum, value)
        if row_minimum > maximum:
            return maximum + 1
        previous = current
    return previous[-1]


def _source_artifact_paths(run_root: Path) -> list[Path]:
    candidates = [
        run_root / "ocr" / "ocr.jsonl",
        run_root / "asr" / "asr.jsonl",
        run_root / "metadata" / "metadata.jsonl",
    ]
    return [path for path in candidates if path.is_file()]


def text_source_artifact_checksums(run_root: str | Path) -> dict[str, str]:
    root = Path(run_root)
    return {
        path.relative_to(root).as_posix(): sha256_file(path)
        for path in _source_artifact_paths(root)
    }


def _iter_jsonl_rows(path: str | Path) -> Iterable[dict[str, Any]]:
    target = Path(path)
    if not target.is_file():
        return
    with target.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as exc:
                raise TextIndexValidationError(
                    f"Invalid JSONL row at {target}:{line_number}: {exc}"
                ) from exc


def _iter_text_documents_from_run(
    run_root: str | Path,
    *,
    include_below_threshold_ocr: bool = False,
    character_ngram_min: int = 2,
    character_ngram_max: int = 4,
    max_character_ngrams: int = 64,
) -> Iterable[TextDocument]:
    root = Path(run_root)

    for row in _iter_jsonl_rows(root / "ocr" / "ocr.jsonl"):
        detection = OCRDetection.model_validate(row)
        if detection.below_threshold and not include_below_threshold_ocr:
            continue
        ngrams = detection.character_ngrams or _char_ngrams(
            detection.normalized_text_no_diacritics or detection.normalized_text,
            character_ngram_min,
            character_ngram_max,
            max_character_ngrams,
        )
        fields = {
            "ocr_text": detection.normalized_text or normalize_text(detection.raw_text),
            "ocr_text_no_diacritics": detection.normalized_text_no_diacritics
            or normalize_text(strip_diacritics(detection.raw_text)),
            "ocr_punctuation": detection.punctuation_aware_text,
            "ocr_char_ngrams": "\u241f".join(ngrams),
        }
        searchable = " ".join(
            value.replace("\u241f", " ") for value in fields.values() if value
        )
        yield TextDocument(
            doc_id=detection.detection_id,
            text=searchable,
            metadata={**detection.model_dump(mode="json"), "source": "ocr"},
            fields=fields,
            source="ocr",
        )

    for row in _iter_jsonl_rows(root / "asr" / "asr.jsonl"):
        segment = ASRSegment.model_validate(row)
        raw = segment.text or ""
        no_diacritics = segment.normalized_text_no_diacritics or normalize_text(
            strip_diacritics(raw)
        )
        fields = {
            "asr_text": segment.normalized_text or normalize_text(raw),
            "asr_text_no_diacritics": no_diacritics,
            "asr_char_ngrams": "\u241f".join(
                _char_ngrams(
                    no_diacritics,
                    character_ngram_min,
                    character_ngram_max,
                    max_character_ngrams,
                )
            ),
        }
        searchable = " ".join(
            value.replace("\u241f", " ") for value in fields.values() if value
        )
        yield TextDocument(
            doc_id=segment.segment_id,
            text=searchable,
            metadata={**segment.model_dump(mode="json"), "source": "asr"},
            fields=fields,
            source="asr",
        )

    for row in _iter_jsonl_rows(root / "metadata" / "metadata.jsonl"):
        record = MetadataRecord.model_validate(row)
        title = record.title or ""
        description = record.description or ""
        tags = " ".join(record.tags)
        channel = record.channel or ""
        combined = record.text or " ".join(
            value for value in [title, description, tags, channel] if value
        )
        normalized = record.normalized_text or normalize_text(combined)
        no_diacritics = record.normalized_text_no_diacritics or normalize_text(
            strip_diacritics(combined)
        )
        prefix = (
            "auto_metadata"
            if str(record.source) == "auto_semantic"
            else "organizer_metadata"
            if str(record.source) == "organizer_youtube"
            else "technical_metadata"
            if str(record.source) == "technical"
            else "metadata"
        )
        fields = {
            f"{prefix}_title": normalize_text(title),
            f"{prefix}_description": normalize_text(description),
            f"{prefix}_tags": normalize_text(tags),
            f"{prefix}_channel": normalize_text(channel),
            f"{prefix}_text": normalized,
            f"{prefix}_text_no_diacritics": no_diacritics,
            f"{prefix}_char_ngrams": "\u241f".join(
                _char_ngrams(
                    no_diacritics,
                    character_ngram_min,
                    character_ngram_max,
                    max_character_ngrams,
                )
            ),
        }
        searchable = " ".join(
            value.replace("\u241f", " ") for value in fields.values() if value
        )
        if not searchable.strip():
            continue
        yield TextDocument(
            doc_id=record.metadata_id,
            text=searchable,
            metadata={
                **record.model_dump(mode="json"),
                "source": "metadata",
                "metadata_source": str(record.source),
            },
            fields=fields,
            source="metadata",
        )


def build_text_documents_from_run(
    run_root: str | Path,
    *,
    include_below_threshold_ocr: bool = False,
    character_ngram_min: int = 2,
    character_ngram_max: int = 4,
    max_character_ngrams: int = 64,
) -> list[TextDocument]:
    documents = list(
        _iter_text_documents_from_run(
            run_root,
            include_below_threshold_ocr=include_below_threshold_ocr,
            character_ngram_min=character_ngram_min,
            character_ngram_max=character_ngram_max,
            max_character_ngrams=max_character_ngrams,
        )
    )
    documents.sort(key=lambda item: (str(item.source), item.doc_id))
    return documents


class LocalPersistentBM25:
    """SQLite-backed field-aware BM25 index with phrase, fuzzy, no-diacritic, and n-gram search."""
    name = "local_bm25"
    version = "sqlite-bm25-v3"

    def __init__(self, database_path: str | Path, config: Any):
        self.database_path = Path(database_path)
        self.config = config
        self._lock = threading.RLock()

    @staticmethod
    def _schema(connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            PRAGMA foreign_keys=ON;
            CREATE TABLE IF NOT EXISTS documents (
                row_id INTEGER PRIMARY KEY,
                doc_id TEXT NOT NULL UNIQUE,
                source TEXT NOT NULL,
                video_id TEXT NOT NULL,
                frame_id INTEGER,
                timestamp_ms INTEGER,
                start_ms INTEGER,
                end_ms INTEGER,
                text TEXT NOT NULL,
                fields_json TEXT NOT NULL,
                metadata_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS field_values (
                doc_row_id INTEGER NOT NULL,
                field TEXT NOT NULL,
                normalized_text TEXT NOT NULL,
                normalized_no_diacritics TEXT NOT NULL,
                PRIMARY KEY (doc_row_id, field),
                FOREIGN KEY (doc_row_id) REFERENCES documents(row_id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS doc_lengths (
                doc_row_id INTEGER NOT NULL,
                field TEXT NOT NULL,
                length INTEGER NOT NULL,
                PRIMARY KEY (doc_row_id, field),
                FOREIGN KEY (doc_row_id) REFERENCES documents(row_id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS postings (
                field TEXT NOT NULL,
                term TEXT NOT NULL,
                doc_row_id INTEGER NOT NULL,
                tf INTEGER NOT NULL,
                PRIMARY KEY (field, term, doc_row_id),
                FOREIGN KEY (doc_row_id) REFERENCES documents(row_id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS vocabulary (
                field TEXT NOT NULL,
                term TEXT NOT NULL,
                df INTEGER NOT NULL,
                PRIMARY KEY (field, term)
            );
            CREATE TABLE IF NOT EXISTS field_stats (
                field TEXT PRIMARY KEY,
                document_count INTEGER NOT NULL,
                average_length REAL NOT NULL,
                total_length INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS index_metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            """
        )

    def build(self, documents: Iterable[TextDocument]) -> None:
        target = self.database_path
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.building")
        temporary.unlink(missing_ok=True)
        connection = sqlite3.connect(temporary)
        try:
            connection.execute("PRAGMA journal_mode=OFF")
            connection.execute("PRAGMA synchronous=OFF")
            connection.execute("PRAGMA temp_store=MEMORY")
            self._schema(connection)
            total_document_count = 0

            for document in documents:
                total_document_count += 1
                metadata = document.metadata
                cursor = connection.execute(
                    """
                    INSERT INTO documents(
                        doc_id, source, video_id, frame_id, timestamp_ms,
                        start_ms, end_ms, text, fields_json, metadata_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        document.doc_id,
                        str(document.source),
                        str(metadata.get("video_id", "")),
                        _optional_int(metadata.get("frame_id")),
                        _optional_int(metadata.get("timestamp_ms")),
                        _optional_int(metadata.get("start_ms")),
                        _optional_int(metadata.get("end_ms")),
                        document.text,
                        json.dumps(document.fields, ensure_ascii=False, sort_keys=True),
                        json.dumps(metadata, ensure_ascii=False, sort_keys=True),
                    ),
                )
                row_id = int(cursor.lastrowid)
                for field_name, field_value in sorted(document.fields.items()):
                    value = str(field_value or "")
                    tokens = _field_tokens(field_name, value)
                    frequencies = Counter(tokens)
                    length = sum(frequencies.values())
                    connection.execute(
                        "INSERT INTO doc_lengths(doc_row_id, field, length) VALUES (?, ?, ?)",
                        (row_id, field_name, length),
                    )
                    # Character n-gram fields are never used for phrase matching, so
                    # retaining their large delimiter-joined value in field_values
                    # only inflates the SQLite artifact. The postings remain complete.
                    if not field_name.endswith("char_ngrams"):
                        plain_value = value.replace("\u241f", " ")
                        connection.execute(
                            """
                            INSERT INTO field_values(
                                doc_row_id, field, normalized_text, normalized_no_diacritics
                            ) VALUES (?, ?, ?, ?)
                            """,
                            (
                                row_id,
                                field_name,
                                normalize_text(plain_value),
                                normalize_text(strip_diacritics(plain_value)),
                            ),
                        )
                    posting_rows = [
                        (field_name, term, row_id, frequency)
                        for term, frequency in sorted(frequencies.items())
                    ]
                    if posting_rows:
                        connection.executemany(
                            "INSERT INTO postings(field, term, doc_row_id, tf) VALUES (?, ?, ?, ?)",
                            posting_rows,
                        )
            # Aggregate document frequency and field statistics inside SQLite.
            # This keeps vocabulary cardinality out of Python RAM and makes build
            # memory scale with the current document rather than the whole corpus.
            connection.execute(
                """
                INSERT INTO vocabulary(field, term, df)
                SELECT field, term, COUNT(*) AS df
                FROM postings
                GROUP BY field, term
                """
            )
            connection.execute(
                """
                INSERT INTO field_stats(field, document_count, average_length, total_length)
                SELECT field,
                       COUNT(*) AS document_count,
                       COALESCE(AVG(length), 0.0) AS average_length,
                       COALESCE(SUM(length), 0) AS total_length
                FROM doc_lengths
                GROUP BY field
                """
            )
            metadata_rows = {
                "backend": self.name,
                "backend_version": self.version,
                "document_count": total_document_count,
                "vocabulary_aggregation": "sqlite_group_by",
                "created_at_utc": utcnow_iso(),
            }
            connection.executemany(
                "INSERT INTO index_metadata(key, value) VALUES (?, ?)",
                [(key, json.dumps(value, ensure_ascii=False)) for key, value in metadata_rows.items()],
            )
            # Secondary indexes are built after bulk insertion to avoid updating
            # them for every posting/document row during construction.
            connection.executescript(
                """
                CREATE INDEX IF NOT EXISTS idx_postings_lookup ON postings(field, term);
                CREATE INDEX IF NOT EXISTS idx_documents_source ON documents(source);
                CREATE INDEX IF NOT EXISTS idx_documents_video ON documents(video_id);
                CREATE INDEX IF NOT EXISTS idx_field_values_field ON field_values(field);
                """
            )
            connection.commit()
            connection.execute("PRAGMA optimize")
            connection.close()
            os.replace(temporary, target)
        except Exception:
            connection.close()
            temporary.unlink(missing_ok=True)
            raise

    def _connect(self) -> sqlite3.Connection:
        if not self.database_path.is_file():
            raise TextIndexValidationError(f"Local text index is missing: {self.database_path}")
        uri = f"file:{self.database_path.resolve().as_posix()}?mode=ro"
        connection = sqlite3.connect(uri, uri=True, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        return connection

    def validate(self) -> dict[str, Any]:
        try:
            with closing(self._connect()) as connection:
                integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
                if integrity != "ok":
                    raise TextIndexValidationError(f"SQLite integrity check failed: {integrity}")
                counts = {
                    "documents": int(connection.execute("SELECT COUNT(*) FROM documents").fetchone()[0]),
                    "postings": int(connection.execute("SELECT COUNT(*) FROM postings").fetchone()[0]),
                    "fields": int(connection.execute("SELECT COUNT(*) FROM field_stats").fetchone()[0]),
                }
                metadata_row = connection.execute(
                    "SELECT value FROM index_metadata WHERE key='document_count'"
                ).fetchone()
                if metadata_row is None:
                    raise TextIndexValidationError(
                        "SQLite text index is missing internal document_count metadata"
                    )
                internal_document_count = int(json.loads(str(metadata_row[0])))
                if internal_document_count != counts["documents"]:
                    raise TextIndexValidationError(
                        "SQLite internal document_count differs from documents table"
                    )
                counts["internal_document_count"] = internal_document_count
                return counts
        except sqlite3.DatabaseError as exc:
            raise TextIndexValidationError(f"Could not read local text index: {exc}") from exc

    def stats(self) -> dict[str, Any]:
        with closing(self._connect()) as connection:
            source_counts = {
                str(row["source"]): int(row["count"])
                for row in connection.execute(
                    "SELECT source, COUNT(*) AS count FROM documents GROUP BY source ORDER BY source"
                )
            }
            fields = {
                str(row["field"]): {
                    "document_count": int(row["document_count"]),
                    "average_length": float(row["average_length"]),
                    "total_length": int(row["total_length"]),
                }
                for row in connection.execute(
                    "SELECT field, document_count, average_length, total_length FROM field_stats"
                )
            }
            return {
                "backend": self.name,
                "backend_version": self.version,
                "document_count": sum(source_counts.values()),
                "source_counts": source_counts,
                "fields": fields,
                "database_bytes": self.database_path.stat().st_size,
            }

    def search(
        self,
        query: str,
        k: int = 100,
        *,
        source_filter: set[str] | None = None,
    ) -> list[TextSearchHit]:
        normalized_query = normalize_text(query)
        query_no_diacritics = normalize_text(strip_diacritics(query))
        word_tokens = normalized_tokens(normalized_query)
        no_diacritic_tokens = normalized_tokens(query_no_diacritics)
        query_ngrams = _char_ngrams(
            query_no_diacritics,
            int(self.config.character_ngram_min),
            int(self.config.character_ngram_max),
            int(self.config.max_query_character_ngrams),
        )
        if not word_tokens and not query_ngrams:
            return []

        scores: defaultdict[int, float] = defaultdict(float)
        fields_by_doc: defaultdict[int, set[str]] = defaultdict(set)
        modes_by_doc: defaultdict[int, set[str]] = defaultdict(set)
        contributions: defaultdict[int, defaultdict[str, float]] = defaultdict(
            lambda: defaultdict(float)
        )

        with closing(self._connect()) as connection:
            fields = [str(row[0]) for row in connection.execute("SELECT field FROM field_stats")]
            source_clause, source_parameters = _source_sql(source_filter)
            use_character_ngrams = self._query_needs_character_ngrams(
                connection, word_tokens, no_diacritic_tokens
            )
            for field_name in fields:
                field_weight = float(self.config.field_weights.get(field_name, 1.0))
                if field_name.endswith("char_ngrams"):
                    terms = query_ngrams if use_character_ngrams else []
                    mode = "character_ngram"
                    mode_boost = float(self.config.character_ngram_boost)
                elif field_name.endswith("no_diacritics"):
                    terms = no_diacritic_tokens
                    mode = "no_diacritic"
                    mode_boost = float(self.config.no_diacritic_boost)
                else:
                    terms = word_tokens
                    mode = "bm25"
                    mode_boost = 1.0
                unique_terms = list(dict.fromkeys(terms))
                if not unique_terms:
                    continue
                if field_name.endswith("char_ngrams"):
                    # Character postings can be extremely broad. Keep the rarest
                    # query grams so typo recovery stays bounded on large corpora.
                    lookup_placeholders = ",".join("?" for _ in unique_terms)
                    rare_rows = connection.execute(
                        f"""
                        SELECT term FROM vocabulary
                        WHERE field=? AND term IN ({lookup_placeholders})
                        ORDER BY df ASC, length(term) DESC, term
                        LIMIT ?
                        """,
                        [
                            field_name,
                            *unique_terms,
                            int(self.config.character_ngram_candidate_limit),
                        ],
                    ).fetchall()
                    unique_terms = [str(row["term"]) for row in rare_rows]
                    if not unique_terms:
                        continue
                placeholders = ",".join("?" for _ in unique_terms)
                rows = connection.execute(
                    f"""
                    SELECT p.term, p.doc_row_id, p.tf, v.df, dl.length,
                           fs.document_count, fs.average_length
                    FROM postings p
                    JOIN vocabulary v ON v.field=p.field AND v.term=p.term
                    JOIN doc_lengths dl ON dl.doc_row_id=p.doc_row_id AND dl.field=p.field
                    JOIN field_stats fs ON fs.field=p.field
                    JOIN documents d ON d.row_id=p.doc_row_id
                    WHERE p.field=? AND p.term IN ({placeholders}) {source_clause}
                    """,
                    [field_name, *unique_terms, *source_parameters],
                ).fetchall()
                for row in rows:
                    term = str(row["term"])
                    score = _bm25_score(
                        tf=int(row["tf"]),
                        df=int(row["df"]),
                        document_count=int(row["document_count"]),
                        document_length=int(row["length"]),
                        average_length=float(row["average_length"]),
                        k1=float(self.config.k1),
                        b=float(self.config.b),
                    )
                    contribution = score * field_weight * mode_boost
                    doc_row_id = int(row["doc_row_id"])
                    scores[doc_row_id] += contribution
                    fields_by_doc[doc_row_id].add(field_name)
                    modes_by_doc[doc_row_id].add(mode)
                    contributions[doc_row_id][f"{field_name}:{term}"] += contribution

            if self.config.exact_phrase_enabled:
                self._add_exact_phrase_scores(
                    connection,
                    query,
                    fields,
                    source_clause,
                    source_parameters,
                    scores,
                    fields_by_doc,
                    modes_by_doc,
                    contributions,
                )

            if self.config.fuzzy_enabled and word_tokens:
                self._add_fuzzy_scores(
                    connection,
                    word_tokens,
                    no_diacritic_tokens,
                    fields,
                    source_clause,
                    source_parameters,
                    scores,
                    fields_by_doc,
                    modes_by_doc,
                    contributions,
                )

            if not scores:
                return []
            ranked_ids = sorted(scores, key=lambda row_id: (-scores[row_id], row_id))[:k]
            placeholders = ",".join("?" for _ in ranked_ids)
            document_rows = connection.execute(
                f"SELECT * FROM documents WHERE row_id IN ({placeholders})", ranked_ids
            ).fetchall()
            by_id = {int(row["row_id"]): row for row in document_rows}

        hits: list[TextSearchHit] = []
        for row_id in ranked_ids:
            row = by_id[row_id]
            metadata = json.loads(str(row["metadata_json"]))
            fields = json.loads(str(row["fields_json"]))
            hits.append(
                TextSearchHit(
                    score=float(scores[row_id]),
                    document=TextDocument(
                        doc_id=str(row["doc_id"]),
                        text=str(row["text"]),
                        metadata=metadata,
                        fields=fields,
                        source=str(row["source"]),
                    ),
                    matched_fields=sorted(fields_by_doc[row_id]),
                    match_modes=sorted(modes_by_doc[row_id]),
                    term_contributions=dict(
                        sorted(
                            contributions[row_id].items(),
                            key=lambda item: (-item[1], item[0]),
                        )[:50]
                    ),
                    requested_backend=self.name,
                    actual_backend=self.name,
                )
            )
        return hits

    def _add_exact_phrase_scores(
        self,
        connection: sqlite3.Connection,
        query: str,
        fields: list[str],
        source_clause: str,
        source_parameters: list[str],
        scores: defaultdict[int, float],
        fields_by_doc: defaultdict[int, set[str]],
        modes_by_doc: defaultdict[int, set[str]],
        contributions: defaultdict[int, defaultdict[str, float]],
    ) -> None:
        """Boost exact phrases using posting prefilter and token boundaries.

        The first phrase token narrows candidate documents through ``postings``;
        only those field values are loaded and checked for a contiguous token
        sequence. This avoids a full ``field_values`` scan and substring false
        positives from ``instr``.
        """

        searchable_fields = [
            field_name for field_name in fields if not field_name.endswith("char_ngrams")
        ]
        for phrase in _quoted_phrases(query):
            phrase_tokens = normalized_tokens(phrase)
            phrase_no = normalize_text(strip_diacritics(phrase))
            phrase_no_tokens = normalized_tokens(phrase_no)
            for field_name in searchable_fields:
                use_no_diacritics = field_name.endswith("no_diacritics")
                tokens = phrase_no_tokens if use_no_diacritics else phrase_tokens
                if not tokens:
                    continue
                value_column = (
                    "fv.normalized_no_diacritics"
                    if use_no_diacritics
                    else "fv.normalized_text"
                )
                rows = connection.execute(
                    f"""
                    SELECT DISTINCT fv.doc_row_id, fv.field, {value_column} AS phrase_value
                    FROM postings p
                    JOIN field_values fv
                      ON fv.doc_row_id=p.doc_row_id AND fv.field=p.field
                    JOIN documents d ON d.row_id=p.doc_row_id
                    WHERE p.field=? AND p.term=? {source_clause}
                    """,
                    [field_name, tokens[0], *source_parameters],
                ).fetchall()
                for row in rows:
                    if not _contains_token_phrase(str(row["phrase_value"]), tokens):
                        continue
                    contribution = float(self.config.exact_phrase_boost) * float(
                        self.config.field_weights.get(field_name, 1.0)
                    )
                    doc_row_id = int(row["doc_row_id"])
                    scores[doc_row_id] += contribution
                    fields_by_doc[doc_row_id].add(field_name)
                    modes_by_doc[doc_row_id].add("exact_phrase")
                    contributions[doc_row_id][
                        f"{field_name}:phrase:{' '.join(tokens)}"
                    ] += contribution

    def _query_needs_character_ngrams(
        self,
        connection: sqlite3.Connection,
        word_tokens: list[str],
        no_diacritic_tokens: list[str],
    ) -> bool:
        """Use expensive character n-grams only for tokens missing lexically.

        Normal exact/no-diacritic queries should not fan out over hundreds of
        character postings. A misspelled or concatenated token still activates
        the n-gram branch, preserving OCR/ASR error tolerance.
        """

        token_pairs = list(zip(word_tokens, no_diacritic_tokens))
        all_tokens = list(
            dict.fromkeys(token for pair in token_pairs for token in pair if token)
        )
        if not all_tokens:
            return False
        placeholders = ",".join("?" for _ in all_tokens)
        present = {
            str(row[0])
            for row in connection.execute(
                f"""
                SELECT DISTINCT term FROM vocabulary
                WHERE field NOT LIKE '%char_ngrams' AND term IN ({placeholders})
                """,
                all_tokens,
            )
        }
        minimum_length = int(self.config.fuzzy_min_token_length)
        return any(
            max(len(word), len(no_diacritic)) >= minimum_length
            and word not in present
            and no_diacritic not in present
            for word, no_diacritic in token_pairs
        )

    def _add_fuzzy_scores(
        self,
        connection: sqlite3.Connection,
        query_tokens: list[str],
        no_diacritic_tokens: list[str],
        fields: list[str],
        source_clause: str,
        source_parameters: list[str],
        scores: defaultdict[int, float],
        fields_by_doc: defaultdict[int, set[str]],
        modes_by_doc: defaultdict[int, set[str]],
        contributions: defaultdict[int, defaultdict[str, float]],
    ) -> None:
        maximum_distance = int(self.config.fuzzy_max_edit_distance)
        candidate_limit = int(self.config.fuzzy_candidate_limit)
        minimum_length = int(self.config.fuzzy_min_token_length)
        for field_name in fields:
            if field_name.endswith("char_ngrams"):
                continue
            field_weight = float(self.config.field_weights.get(field_name, 1.0))
            field_query_tokens = (
                no_diacritic_tokens
                if field_name.endswith("no_diacritics")
                else query_tokens
            )
            for token in dict.fromkeys(field_query_tokens):
                if len(token) < minimum_length:
                    continue
                # Exact lexical matches already received BM25 credit and do not
                # need the much more expensive vocabulary expansion.
                exact = connection.execute(
                    "SELECT 1 FROM vocabulary WHERE field=? AND term=? LIMIT 1",
                    (field_name, token),
                ).fetchone()
                if exact is not None:
                    continue
                vocabulary_rows = connection.execute(
                    """
                    SELECT term, df FROM vocabulary
                    WHERE field=? AND length(term) BETWEEN ? AND ?
                    ORDER BY abs(length(term)-?), df DESC, term
                    LIMIT ?
                    """,
                    (
                        field_name,
                        max(1, len(token) - maximum_distance),
                        len(token) + maximum_distance,
                        len(token),
                        candidate_limit,
                    ),
                ).fetchall()
                similarities: dict[str, float] = {}
                for vocabulary_row in vocabulary_rows:
                    candidate = str(vocabulary_row["term"])
                    if candidate == token:
                        continue
                    distance = _edit_distance_limited(token, candidate, maximum_distance)
                    if distance <= maximum_distance:
                        similarities[candidate] = 1.0 - distance / max(
                            len(token), len(candidate), 1
                        )
                if not similarities:
                    continue
                candidates = list(similarities)
                placeholders = ",".join("?" for _ in candidates)
                rows = connection.execute(
                    f"""
                    SELECT p.term, p.doc_row_id, p.tf, v.df, dl.length,
                           fs.document_count, fs.average_length
                    FROM postings p
                    JOIN vocabulary v ON v.field=p.field AND v.term=p.term
                    JOIN doc_lengths dl ON dl.doc_row_id=p.doc_row_id AND dl.field=p.field
                    JOIN field_stats fs ON fs.field=p.field
                    JOIN documents d ON d.row_id=p.doc_row_id
                    WHERE p.field=? AND p.term IN ({placeholders}) {source_clause}
                    """,
                    [field_name, *candidates, *source_parameters],
                ).fetchall()
                for row in rows:
                    candidate = str(row["term"])
                    similarity = similarities[candidate]
                    contribution = (
                        _bm25_score(
                            tf=int(row["tf"]),
                            df=int(row["df"]),
                            document_count=int(row["document_count"]),
                            document_length=int(row["length"]),
                            average_length=float(row["average_length"]),
                            k1=float(self.config.k1),
                            b=float(self.config.b),
                        )
                        * field_weight
                        * float(self.config.fuzzy_boost)
                        * similarity
                    )
                    doc_row_id = int(row["doc_row_id"])
                    scores[doc_row_id] += contribution
                    fields_by_doc[doc_row_id].add(field_name)
                    modes_by_doc[doc_row_id].add("fuzzy")
                    contributions[doc_row_id][
                        f"{field_name}:fuzzy:{token}->{candidate}"
                    ] += contribution


class RemoteTextIndexAdapter:
    """Hardened optional OpenSearch/Elasticsearch adapter.

    Every remote index carries immutable build metadata in mapping ``_meta``.
    A remote backend is accepted only when its fingerprint, source document
    checksum, mapping version, and document count match the local manifest.
    """

    version = "remote-v2"

    def __init__(
        self,
        backend: str,
        index_name: str,
        config: Any,
        *,
        expected_state: dict[str, Any] | None = None,
    ):
        self.name = backend
        self.index_name = index_name
        self.config = config
        self.expected_state = dict(expected_state or {})
        self.client, self.bulk_helper = self._create_client()

    def _create_client(self):
        endpoint = str(self.config.remote_url)
        username = os.getenv(str(self.config.remote_username_env), "")
        password = os.getenv(str(self.config.remote_password_env), "")
        api_key = os.getenv(str(self.config.remote_api_key_env), "")
        if self.name == "opensearch":
            try:
                from opensearchpy import OpenSearch
                from opensearchpy.helpers import bulk
            except ImportError as exc:
                raise TextIndexDependencyError(
                    "Install opensearch-py to use text_index.adapter=opensearch"
                ) from exc
            parsed = urlparse(endpoint)
            auth = (username, password) if username or password else None
            client = OpenSearch(
                hosts=[
                    {
                        "host": parsed.hostname or "localhost",
                        "port": parsed.port or (443 if parsed.scheme == "https" else 9200),
                        "scheme": parsed.scheme or "http",
                    }
                ],
                http_auth=auth,
                verify_certs=bool(self.config.remote_verify_certs),
                timeout=int(self.config.remote_timeout_seconds),
            )
        elif self.name == "elasticsearch":
            try:
                from elasticsearch import Elasticsearch
                from elasticsearch.helpers import bulk
            except ImportError as exc:
                raise TextIndexDependencyError(
                    "Install elasticsearch to use text_index.adapter=elasticsearch"
                ) from exc
            kwargs: dict[str, Any] = {
                "verify_certs": bool(self.config.remote_verify_certs),
                "request_timeout": int(self.config.remote_timeout_seconds),
            }
            if api_key:
                kwargs["api_key"] = api_key
            elif username or password:
                kwargs["basic_auth"] = (username, password)
            client = Elasticsearch(endpoint, **kwargs)
        else:  # pragma: no cover - protected by config validation
            raise ValueError(f"Unsupported remote text adapter: {self.name}")
        try:
            if not client.ping():
                raise TextIndexDependencyError(f"{self.name} endpoint did not respond to ping")
        except Exception as exc:
            raise TextIndexDependencyError(f"Could not connect to {self.name}: {exc}") from exc
        return client, bulk

    @staticmethod
    def _remote_field(field_name: str) -> str:
        return f"fields.{field_name}"

    def _indexed_field_names(self) -> list[str]:
        configured = set(self.config.field_weights)
        configured.update(str(name) for name in self.expected_state.get("field_names", []))
        return sorted(configured)

    def _field_mapping(self) -> dict[str, Any]:
        return {
            field_name: (
                {"type": "keyword"}
                if field_name.endswith("char_ngrams")
                else {"type": "text", "analyzer": "standard"}
            )
            for field_name in self._indexed_field_names()
        }

    def _mapping_metadata(self) -> dict[str, Any]:
        return {REMOTE_META_KEY: dict(self.expected_state)}

    def _remote_metadata(self) -> dict[str, Any]:
        response = self.client.indices.get_mapping(index=self.index_name)
        if not isinstance(response, dict) or not response:
            raise TextIndexValidationError(
                f"Remote mapping response is empty for {self.index_name}"
            )
        entry = response.get(self.index_name)
        if entry is None:
            entry = next(iter(response.values()))
        mappings = dict((entry or {}).get("mappings") or {})
        metadata = dict(mappings.get("_meta") or {})
        state = metadata.get(REMOTE_META_KEY)
        if not isinstance(state, dict):
            raise TextIndexValidationError(
                f"Remote index is missing {REMOTE_META_KEY} mapping metadata"
            )
        return dict(state)

    def build(self, documents: Iterable[TextDocument]) -> None:
        if self.client.indices.exists(index=self.index_name):
            self.client.indices.delete(index=self.index_name)
        properties: dict[str, Any] = {
            "doc_id": {"type": "keyword"},
            "source": {"type": "keyword"},
            "video_id": {"type": "keyword"},
            "frame_id": {"type": "long"},
            "timestamp_ms": {"type": "long"},
            "start_ms": {"type": "long"},
            "end_ms": {"type": "long"},
            "text": {"type": "text", "analyzer": "standard"},
            "metadata_json": {"type": "keyword", "index": False, "ignore_above": 32766},
            "fields": {"type": "object", "properties": self._field_mapping()},
        }
        self.client.indices.create(
            index=self.index_name,
            body={
                "mappings": {
                    "dynamic": False,
                    "_meta": self._mapping_metadata(),
                    "properties": properties,
                }
            },
        )

        def actions() -> Iterable[dict[str, Any]]:
            for document in documents:
                metadata = document.metadata
                remote_fields: dict[str, Any] = {}
                for field_name, value in document.fields.items():
                    if field_name.endswith("char_ngrams"):
                        remote_fields[field_name] = [
                            token for token in str(value).split("\u241f") if token
                        ]
                    else:
                        remote_fields[field_name] = str(value)
                yield {
                    "_index": self.index_name,
                    "_id": document.doc_id,
                    "_source": {
                        "doc_id": document.doc_id,
                        "source": document.source,
                        "video_id": metadata.get("video_id", ""),
                        "frame_id": metadata.get("frame_id"),
                        "timestamp_ms": metadata.get("timestamp_ms"),
                        "start_ms": metadata.get("start_ms"),
                        "end_ms": metadata.get("end_ms"),
                        "text": document.text,
                        "fields": remote_fields,
                        "metadata_json": json.dumps(
                            metadata, ensure_ascii=False, sort_keys=True
                        ),
                    },
                }

        self.bulk_helper(
            self.client,
            actions(),
            chunk_size=int(self.config.remote_bulk_size),
            request_timeout=int(self.config.remote_timeout_seconds),
        )
        self.client.indices.refresh(index=self.index_name)
        self.validate()

    def validate(self) -> dict[str, Any]:
        if not self.client.indices.exists(index=self.index_name):
            raise TextIndexValidationError(f"Remote index does not exist: {self.index_name}")
        count_response = self.client.count(index=self.index_name)
        actual_count = int(count_response.get("count", 0))
        remote_state = self._remote_metadata()
        if self.expected_state:
            for key in (
                "preprocess_run_id",
                "build_fingerprint",
                "documents_sha256",
                "field_mapping_version",
                "field_names",
            ):
                expected = self.expected_state.get(key)
                actual = remote_state.get(key)
                if actual != expected:
                    raise TextIndexValidationError(
                        f"Remote index {key} mismatch: expected {expected!r}, got {actual!r}"
                    )
            expected_count = int(self.expected_state.get("document_count", -1))
            metadata_count = int(remote_state.get("document_count", -1))
            if metadata_count != expected_count:
                raise TextIndexValidationError(
                    "Remote mapping metadata document_count differs from expected count"
                )
            if actual_count != expected_count:
                raise TextIndexValidationError(
                    f"Remote index document count mismatch: expected {expected_count}, got {actual_count}"
                )
        return {
            "documents": actual_count,
            "backend": self.name,
            "remote_state": remote_state,
            "valid": True,
        }

    def stats(self) -> dict[str, Any]:
        return self.validate()

    def _remote_query(self, query: str) -> dict[str, Any]:
        weighted_fields = [
            (name, float(self.config.field_weights.get(name, 1.0)))
            for name in self._indexed_field_names()
        ]
        normal_fields = [
            f"fields.{name}^{weight}"
            for name, weight in weighted_fields
            if not name.endswith("char_ngrams")
            and not name.endswith("no_diacritics")
        ]
        no_diacritic_fields = [
            f"fields.{name}^{weight}"
            for name, weight in weighted_fields
            if name.endswith("no_diacritics")
        ]
        char_fields = [
            (f"fields.{name}", weight)
            for name, weight in weighted_fields
            if name.endswith("char_ngrams")
        ]
        query_no = normalize_text(strip_diacritics(query))
        should: list[dict[str, Any]] = []
        if normal_fields:
            should.append(
                {
                    "multi_match": {
                        "query": query,
                        "fields": normal_fields,
                        "type": "best_fields",
                        "_name": "bm25",
                    }
                }
            )
        if no_diacritic_fields:
            should.append(
                {
                    "multi_match": {
                        "query": query_no,
                        "fields": no_diacritic_fields,
                        "type": "best_fields",
                        "boost": float(self.config.no_diacritic_boost),
                        "_name": "no_diacritic",
                    }
                }
            )
        if self.config.exact_phrase_enabled:
            if normal_fields:
                should.append(
                    {
                        "multi_match": {
                            "query": query,
                            "fields": normal_fields,
                            "type": "phrase",
                            "boost": float(self.config.exact_phrase_boost),
                            "_name": "exact_phrase",
                        }
                    }
                )
            if no_diacritic_fields:
                should.append(
                    {
                        "multi_match": {
                            "query": query_no,
                            "fields": no_diacritic_fields,
                            "type": "phrase",
                            "boost": float(self.config.exact_phrase_boost)
                            * float(self.config.no_diacritic_boost),
                            "_name": "exact_phrase_no_diacritic",
                        }
                    }
                )
        if self.config.fuzzy_enabled:
            if normal_fields:
                should.append(
                    {
                        "multi_match": {
                            "query": query,
                            "fields": normal_fields,
                            "fuzziness": int(self.config.fuzzy_max_edit_distance),
                            "prefix_length": 1,
                            "boost": float(self.config.fuzzy_boost),
                            "_name": "fuzzy",
                        }
                    }
                )
            if no_diacritic_fields:
                should.append(
                    {
                        "multi_match": {
                            "query": query_no,
                            "fields": no_diacritic_fields,
                            "fuzziness": int(self.config.fuzzy_max_edit_distance),
                            "prefix_length": 1,
                            "boost": float(self.config.fuzzy_boost)
                            * float(self.config.no_diacritic_boost),
                            "_name": "fuzzy_no_diacritic",
                        }
                    }
                )
        grams = _char_ngrams(
            query_no,
            int(self.config.character_ngram_min),
            int(self.config.character_ngram_max),
            int(self.config.max_query_character_ngrams),
        )[: int(self.config.character_ngram_candidate_limit)]
        if grams and char_fields:
            gram_should: list[dict[str, Any]] = []
            for field_name, field_weight in char_fields:
                for gram in grams:
                    gram_should.append(
                        {
                            "term": {
                                field_name: {
                                    "value": gram,
                                    "boost": field_weight
                                    * float(self.config.character_ngram_boost),
                                }
                            }
                        }
                    )
            should.append(
                {
                    "bool": {
                        "should": gram_should,
                        "minimum_should_match": 1,
                        "_name": "character_ngram",
                    }
                }
            )
        return {"should": should, "minimum_should_match": 1}

    def search(
        self,
        query: str,
        k: int = 100,
        *,
        source_filter: set[str] | None = None,
    ) -> list[TextSearchHit]:
        bool_query = self._remote_query(query)
        filters = []
        if source_filter:
            filters.append({"terms": {"source": sorted(source_filter)}})
        bool_query["filter"] = filters
        response = self.client.search(
            index=self.index_name,
            body={"size": k, "query": {"bool": bool_query}},
        )
        hits: list[TextSearchHit] = []
        for item in response.get("hits", {}).get("hits", []):
            source = item.get("_source", {})
            metadata = json.loads(source.get("metadata_json", "{}"))
            raw_fields = source.get("fields", {}) or {}
            fields = {
                str(key): (
                    "\u241f".join(str(token) for token in value)
                    if isinstance(value, list)
                    else str(value)
                )
                for key, value in raw_fields.items()
            }
            matched_queries = [str(value) for value in item.get("matched_queries", [])]
            match_modes = sorted(
                {
                    "exact_phrase"
                    if mode.startswith("exact_phrase")
                    else "no_diacritic"
                    if mode == "no_diacritic"
                    else "fuzzy"
                    if mode.startswith("fuzzy")
                    else "character_ngram"
                    if mode == "character_ngram"
                    else "bm25"
                    for mode in matched_queries
                }
            ) or [self.name]
            hits.append(
                TextSearchHit(
                    score=float(item.get("_score") or 0.0),
                    document=TextDocument(
                        doc_id=str(source.get("doc_id") or item.get("_id")),
                        text=str(source.get("text", "")),
                        metadata=metadata,
                        fields=fields,
                        source=str(source.get("source", metadata.get("source", "metadata"))),
                    ),
                    matched_fields=[],
                    match_modes=match_modes,
                    term_contributions={},
                    requested_backend=self.name,
                    actual_backend=self.name,
                )
            )
        return hits


class FallbackTextIndexAdapter:
    """Use a validated remote backend when healthy and preserve an explicit local fallback trace."""
    def __init__(
        self,
        primary: TextIndexAdapter,
        fallback: TextIndexAdapter,
        *,
        initial_error: str | None = None,
    ):
        self.primary = primary
        self.fallback = fallback
        self.name = primary.name
        self.version = getattr(primary, "version", "runtime")
        self.last_error: str | None = initial_error

    def build(self, documents: Iterable[TextDocument]) -> None:
        # Main build orchestration builds local and remote from the persisted
        # documents artifact separately; this compatibility path remains for
        # tiny callers only.
        cached = list(documents)
        self.fallback.build(iter(cached))
        self.primary.build(iter(cached))

    def validate(self) -> dict[str, Any]:
        try:
            return self.primary.validate()
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            result = self.fallback.validate()
            result.update(
                {
                    "requested_backend": self.primary.name,
                    "actual_backend": self.fallback.name,
                    "fallback_used": True,
                    "fallback_reason": self.last_error,
                }
            )
            return result

    def stats(self) -> dict[str, Any]:
        return self.validate()

    def search(
        self,
        query: str,
        k: int = 100,
        *,
        source_filter: set[str] | None = None,
    ) -> list[TextSearchHit]:
        try:
            hits = self.primary.search(query, k, source_filter=source_filter)
            for hit in hits:
                hit.requested_backend = self.primary.name
                hit.actual_backend = self.primary.name
            return hits
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            hits = self.fallback.search(query, k, source_filter=source_filter)
            for hit in hits:
                hit.match_modes = list(
                    dict.fromkeys([*hit.match_modes, "remote_fallback_local"])
                )
                hit.requested_backend = self.primary.name
                hit.actual_backend = self.fallback.name
                hit.fallback_used = True
                hit.fallback_reason = self.last_error
            return hits


class DegradedRemoteFallbackAdapter:
    """Use local search while preserving why the requested remote was rejected."""

    def __init__(self, requested_backend: str, fallback: TextIndexAdapter, reason: str):
        self.requested_backend = requested_backend
        self.fallback = fallback
        self.name = requested_backend
        self.version = getattr(fallback, "version", "runtime")
        self.reason = reason

    def build(self, documents: Iterable[TextDocument]) -> None:
        self.fallback.build(documents)

    def validate(self) -> dict[str, Any]:
        result = self.fallback.validate()
        result.update(
            {
                "requested_backend": self.requested_backend,
                "actual_backend": self.fallback.name,
                "fallback_used": True,
                "fallback_reason": self.reason,
            }
        )
        return result

    def stats(self) -> dict[str, Any]:
        return self.validate()

    def search(
        self,
        query: str,
        k: int = 100,
        *,
        source_filter: set[str] | None = None,
    ) -> list[TextSearchHit]:
        hits = self.fallback.search(query, k, source_filter=source_filter)
        for hit in hits:
            hit.match_modes = list(
                dict.fromkeys([*hit.match_modes, "remote_fallback_local"])
            )
            hit.requested_backend = self.requested_backend
            hit.actual_backend = self.fallback.name
            hit.fallback_used = True
            hit.fallback_reason = self.reason
        return hits


def _optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    return int(value)


def _bm25_score(
    *,
    tf: int,
    df: int,
    document_count: int,
    document_length: int,
    average_length: float,
    k1: float,
    b: float,
) -> float:
    idf = math.log(1 + (document_count - df + 0.5) / (df + 0.5))
    denominator = tf + k1 * (
        1 - b + b * document_length / max(average_length, 1.0)
    )
    return idf * tf * (k1 + 1) / max(denominator, 1e-12)


def _source_sql(source_filter: set[str] | None) -> tuple[str, list[str]]:
    if not source_filter:
        return "", []
    placeholders = ",".join("?" for _ in source_filter)
    return f"AND d.source IN ({placeholders})", sorted(source_filter)


def _local_paths(run_root: Path, config: Any) -> tuple[Path, Path, Path]:
    index_root = run_root / "text_index"
    return (
        index_root / str(config.local_database_name),
        index_root / "documents.jsonl",
        index_root / "manifest.json",
    )


def _remote_index_name(run_id: str, config: Any) -> str:
    base = re.sub(r"[^a-z0-9._-]+", "-", str(config.index_name).lower()).strip("-._")
    run = re.sub(r"[^a-z0-9._-]+", "-", str(run_id).lower()).strip("-._")
    base = base or "aic2026-text"
    run = run or stable_json_hash({"run_id": run_id})[:12]
    # OpenSearch/Elasticsearch index names must remain comfortably below
    # their byte limit and cannot start with reserved punctuation.
    return f"{base}-{run}"[:200].strip("-._")


def _build_fingerprint(
    run_id: str,
    source_checksums: dict[str, str],
    config: Any,
) -> str:
    return stable_json_hash(
        {
            "run_id": run_id,
            "source_artifact_checksums": source_checksums,
            "config": config.model_dump(mode="json") if hasattr(config, "model_dump") else vars(config),
            "schema": "text-index-v3-sql-df-remote-locked",
        }
    )


def _iter_text_documents_artifact(path: str | Path) -> Iterable[TextDocument]:
    for row in _iter_jsonl_rows(path):
        yield TextDocument(
            doc_id=str(row["doc_id"]),
            source=str(row.get("source") or row.get("metadata", {}).get("source", "metadata")),
            text=str(row.get("text", "")),
            fields={str(key): str(value) for key, value in (row.get("fields") or {}).items()},
            metadata=dict(row.get("metadata") or {}),
        )


def _write_text_documents_artifact(
    path: str | Path,
    documents: Iterable[TextDocument],
) -> dict[str, Any]:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.building")
    temporary.unlink(missing_ok=True)
    document_count = 0
    source_counts: Counter[str] = Counter()
    metadata_source_counts: Counter[str] = Counter()
    field_names: set[str] = set()
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            for document in documents:
                row = document.as_row()
                handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
                handle.write("\n")
                document_count += 1
                source_counts[str(document.source)] += 1
                if document.source == "metadata":
                    metadata_source = str(document.metadata.get("metadata_source", ""))
                    if metadata_source:
                        metadata_source_counts[metadata_source] += 1
                field_names.update(document.fields)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return {
        "document_count": document_count,
        "source_counts": dict(sorted(source_counts.items())),
        "metadata_source_counts": dict(sorted(metadata_source_counts.items())),
        "field_names": sorted(field_names),
    }


def _expected_remote_state(
    *,
    run_id: str,
    build_fingerprint: str,
    document_count: int,
    documents_sha256: str,
    field_names: Sequence[str] = (),
) -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "preprocess_run_id": run_id,
        "build_fingerprint": build_fingerprint,
        "document_count": int(document_count),
        "documents_sha256": documents_sha256,
        "field_mapping_version": REMOTE_FIELD_MAPPING_VERSION,
        "field_names": sorted(str(name) for name in field_names),
    }


def _manifest_remote_state(manifest: TextIndexManifest) -> dict[str, Any]:
    return _expected_remote_state(
        run_id=manifest.preprocess_run_id,
        build_fingerprint=manifest.build_fingerprint,
        document_count=manifest.document_count,
        documents_sha256=manifest.documents_sha256,
        field_names=manifest.field_names,
    )


def build_text_index(
    run_id: str,
    run_root: str | Path,
    settings: Any,
    *,
    force: bool = False,
) -> TextIndexBuildResult:
    """Build local artifacts first, optionally mirror them remotely, and persist one manifest."""
    root = Path(run_root)
    config = settings.text_index
    database_path, documents_path, manifest_path = _local_paths(root, config)
    source_checksums = text_source_artifact_checksums(root)
    fingerprint = _build_fingerprint(run_id, source_checksums, config)

    if not force and manifest_path.is_file():
        try:
            existing = TextIndexManifest.model_validate(read_json(manifest_path))
            if existing.build_fingerprint == fingerprint:
                validate_text_index_artifacts(root, settings, verify_source_checksums=True)
                if existing.selected_adapter in {"opensearch", "elasticsearch"}:
                    remote = RemoteTextIndexAdapter(
                        existing.selected_adapter,
                        existing.remote_index_name
                        or _remote_index_name(existing.preprocess_run_id, config),
                        config,
                        expected_state=_manifest_remote_state(existing),
                    )
                    remote.validate()
                return TextIndexBuildResult(
                    manifest=existing,
                    reused=True,
                    requested_adapter=existing.requested_adapter,
                    selected_adapter=existing.selected_adapter,
                    degraded_reason=existing.degraded_reason,
                )
        except Exception:
            pass

    database_path.parent.mkdir(parents=True, exist_ok=True)
    document_summary = _write_text_documents_artifact(
        documents_path,
        _iter_text_documents_from_run(
            root,
            include_below_threshold_ocr=bool(config.include_below_threshold_ocr),
            character_ngram_min=int(config.character_ngram_min),
            character_ngram_max=int(config.character_ngram_max),
            max_character_ngrams=int(config.max_document_character_ngrams),
        ),
    )
    local = LocalPersistentBM25(database_path, config)
    local.build(_iter_text_documents_artifact(documents_path))
    local.validate()

    documents_sha256 = sha256_file(documents_path)
    requested_adapter = str(config.adapter)
    selected_adapter = "local_bm25"
    degraded_reason: str | None = None
    remote_index_name: str | None = None
    remote_backend_version: str | None = None
    remote_validation: dict[str, Any] | None = None
    if requested_adapter in {"opensearch", "elasticsearch"}:
        remote_index_name = _remote_index_name(run_id, config)
        try:
            expected_remote_state = _expected_remote_state(
                run_id=run_id,
                build_fingerprint=fingerprint,
                document_count=int(document_summary["document_count"]),
                documents_sha256=documents_sha256,
                field_names=list(document_summary["field_names"]),
            )
            remote = RemoteTextIndexAdapter(
                requested_adapter,
                remote_index_name,
                config,
                expected_state=expected_remote_state,
            )
            remote.build(_iter_text_documents_artifact(documents_path))
            remote_validation = remote.validate()
            selected_adapter = requested_adapter
            remote_backend_version = remote.version
        except Exception as exc:
            if not config.allow_local_fallback:
                raise
            degraded_reason = f"{type(exc).__name__}: {exc}"
            selected_adapter = "local_bm25"

    source_counts = dict(document_summary["source_counts"])
    metadata_source_counts = dict(document_summary["metadata_source_counts"])
    field_names = list(document_summary["field_names"])
    document_count = int(document_summary["document_count"])
    manifest = TextIndexManifest(
        preprocess_run_id=run_id,
        requested_adapter=requested_adapter,
        selected_adapter=selected_adapter,
        index_name=str(config.index_name),
        remote_index_name=remote_index_name,
        remote_document_count=(
            int(remote_validation["documents"]) if remote_validation is not None else None
        ),
        remote_build_fingerprint=(
            fingerprint if remote_validation is not None else None
        ),
        remote_documents_sha256=(
            documents_sha256 if remote_validation is not None else None
        ),
        remote_field_mapping_version=(
            REMOTE_FIELD_MAPPING_VERSION if remote_validation is not None else None
        ),
        remote_validated_at_utc=(utcnow_iso() if remote_validation is not None else None),
        backend_version=(remote_backend_version if selected_adapter != "local_bm25" else local.version),
        persistent=True,
        document_count=document_count,
        source_counts=source_counts,
        metadata_source_counts=metadata_source_counts,
        field_names=field_names,
        field_weights=dict(sorted(config.field_weights.items())),
        build_fingerprint=fingerprint,
        source_artifact_checksums=source_checksums,
        documents_path=documents_path.relative_to(root).as_posix(),
        documents_sha256=documents_sha256,
        index_path=database_path.relative_to(root).as_posix(),
        index_sha256=sha256_file(database_path),
        build_config=config.model_dump(mode="json"),
        degraded_reason=degraded_reason,
        created_at_utc=utcnow_iso(),
    )
    write_json(manifest_path, manifest.model_dump(mode="json"))
    write_json(
        root / "reports" / "text_index.json",
        {
            "status": "completed" if degraded_reason is None else "degraded_local_fallback",
            "requested_adapter": requested_adapter,
            "selected_adapter": selected_adapter,
            "degraded_reason": degraded_reason,
            "document_count": document_count,
            "source_counts": source_counts,
            "metadata_source_counts": metadata_source_counts,
            "field_names": field_names,
            "remote_validation": remote_validation,
            "manifest_path": manifest_path.relative_to(root).as_posix(),
            "created_at_utc": utcnow_iso(),
        },
    )
    invalidate_text_index_cache(root)
    return TextIndexBuildResult(
        manifest=manifest,
        reused=False,
        requested_adapter=requested_adapter,
        selected_adapter=selected_adapter,
        degraded_reason=degraded_reason,
    )


def validate_text_index_artifacts(
    run_root: str | Path,
    settings: Any,
    *,
    verify_source_checksums: bool = True,
) -> dict[str, Any]:
    """Verify source freshness, file checksums, internal counts, and optional remote state."""
    root = Path(run_root)
    config = settings.text_index
    database_path, documents_path, manifest_path = _local_paths(root, config)
    if not manifest_path.is_file():
        raise TextIndexValidationError("Text index manifest is missing")
    manifest = TextIndexManifest.model_validate(read_json(manifest_path))
    resolved_documents = root / manifest.documents_path
    resolved_index = root / manifest.index_path
    if not resolved_documents.is_file() or not resolved_index.is_file():
        raise TextIndexValidationError("Text index documents or local fallback database is missing")
    if sha256_file(resolved_documents) != manifest.documents_sha256:
        raise TextIndexValidationError("Text index documents checksum mismatch")
    if sha256_file(resolved_index) != manifest.index_sha256:
        raise TextIndexValidationError("Text index database checksum mismatch")
    if verify_source_checksums:
        current = text_source_artifact_checksums(root)
        if current != manifest.source_artifact_checksums:
            raise TextIndexValidationError("Text index is stale relative to OCR/ASR/metadata artifacts")
    document_count = sum(1 for _ in _iter_jsonl_rows(resolved_documents))
    if document_count != manifest.document_count:
        raise TextIndexValidationError("Text index manifest document count mismatch")
    local = LocalPersistentBM25(database_path, config)
    stats = local.validate()
    if stats["documents"] != manifest.document_count:
        raise TextIndexValidationError("SQLite document count differs from manifest")
    return {
        "manifest": manifest.model_dump(mode="json"),
        "local_stats": stats,
        "valid": True,
    }


_CACHE_LOCK = threading.RLock()
_INDEX_CACHE: OrderedDict[tuple[str, str], TextIndexAdapter] = OrderedDict()
_CACHE_LIMIT = 8


def invalidate_text_index_cache(run_root: str | Path | None = None) -> None:
    with _CACHE_LOCK:
        if run_root is None:
            _INDEX_CACHE.clear()
            return
        prefix = str(Path(run_root).resolve())
        for key in list(_INDEX_CACHE):
            if key[0] == prefix:
                _INDEX_CACHE.pop(key, None)


def _load_run_settings(run_root: Path):
    from .config import Settings

    snapshot = run_root / "config.snapshot.json"
    if snapshot.is_file():
        try:
            return Settings.model_validate(read_json(snapshot))
        except Exception:
            pass
    return Settings()


def load_text_index_adapter(
    run_root: str | Path,
    settings: Any | None = None,
) -> tuple[TextIndexAdapter, TextIndexManifest]:
    """Load the configured validated backend without rebuilding the index during a query."""
    root = Path(run_root)
    settings = settings or _load_run_settings(root)
    config = settings.text_index
    database_path, _, manifest_path = _local_paths(root, config)
    if not manifest_path.is_file():
        if config.auto_build_if_missing:
            build_text_index(root.name, root, settings)
        else:
            raise TextIndexValidationError(
                "Persistent text index is missing; run `aic build-text-index`"
            )
    manifest = TextIndexManifest.model_validate(read_json(manifest_path))
    source_signature = stable_json_hash(
        {
            path.relative_to(root).as_posix(): [path.stat().st_size, path.stat().st_mtime_ns]
            for path in _source_artifact_paths(root)
        }
    )
    cache_key = (
        str(root.resolve()),
        stable_json_hash(
            {
                "manifest_sha256": sha256_file(manifest_path),
                "source_signature": source_signature,
            }
        ),
    )
    with _CACHE_LOCK:
        cached = _INDEX_CACHE.get(cache_key)
        if cached is not None:
            _INDEX_CACHE.move_to_end(cache_key)
            return cached, manifest

    validation = validate_text_index_artifacts(root, settings, verify_source_checksums=True)
    manifest = TextIndexManifest.model_validate(validation["manifest"])
    local: TextIndexAdapter = LocalPersistentBM25(database_path, config)
    adapter: TextIndexAdapter = local
    if manifest.selected_adapter in {"opensearch", "elasticsearch"}:
        try:
            remote = RemoteTextIndexAdapter(
                manifest.selected_adapter,
                manifest.remote_index_name or _remote_index_name(root.name, config),
                config,
                expected_state=_manifest_remote_state(manifest),
            )
            remote.validate()
            adapter = (
                FallbackTextIndexAdapter(remote, local)
                if config.allow_local_fallback
                else remote
            )
        except Exception as exc:
            if not config.allow_local_fallback:
                raise
            reason = f"{type(exc).__name__}: {exc}"
            adapter = DegradedRemoteFallbackAdapter(
                manifest.selected_adapter,
                local,
                reason,
            )
    elif (
        manifest.requested_adapter in {"opensearch", "elasticsearch"}
        and manifest.selected_adapter == "local_bm25"
    ):
        adapter = DegradedRemoteFallbackAdapter(
            manifest.requested_adapter,
            local,
            manifest.degraded_reason or "remote backend was unavailable during build",
        )
    with _CACHE_LOCK:
        _INDEX_CACHE[cache_key] = adapter
        _INDEX_CACHE.move_to_end(cache_key)
        while len(_INDEX_CACHE) > _CACHE_LIMIT:
            _INDEX_CACHE.popitem(last=False)
    return adapter, manifest


def search_text_index(
    query_id: str,
    query: str,
    run_id: str,
    run_root: str | Path,
    k: int = 100,
    *,
    settings: Any | None = None,
    source_filter: set[str] | None = None,
) -> list[SearchCandidate]:
    """Execute field-aware text search through the cached validated adapter."""
    adapter, manifest = load_text_index_adapter(run_root, settings)
    hits = adapter.search(query, k, source_filter=source_filter)
    return text_hits_to_candidates(
        query_id,
        run_id,
        run_root,
        hits,
        adapter_name=adapter.name,
        manifest=manifest,
    )


def text_hits_to_candidates(
    query_id: str,
    run_id: str,
    run_root: str | Path,
    hits: Sequence[TextSearchHit],
    *,
    adapter_name: str,
    manifest: TextIndexManifest,
) -> list[SearchCandidate]:
    """Convert text hits into modality-aware candidates.

    Temporal artifacts are loaded once and reused for the complete ranked list.
    """
    root = Path(run_root)
    sources = {
        str(hit.document.source or hit.document.metadata.get("source", "metadata"))
        for hit in hits
    }

    temporal_registry = None
    if sources.intersection({"asr", "metadata"}):
        try:
            from .temporal import TemporalRegistry

            temporal_registry = TemporalRegistry.from_run_root(root)
        except Exception:
            temporal_registry = None

    metadata_video_ids = {
        str(hit.document.metadata.get("video_id", ""))
        for hit in hits
        if str(hit.document.source or hit.document.metadata.get("source", "metadata"))
        == "metadata"
    }
    # Build this map once so metadata canonicalization stays O(1) per hit.
    representative_frames = _build_representative_frame_map(
        root,
        video_ids=metadata_video_ids,
        temporal_registry=temporal_registry,
    )

    results: list[SearchCandidate] = []
    for rank, hit in enumerate(hits, start=1):
        document = hit.document
        metadata = document.metadata
        source = str(document.source or metadata.get("source", "metadata"))
        requested_backend = hit.requested_backend or manifest.requested_adapter
        actual_backend = hit.actual_backend or (
            manifest.selected_adapter if adapter_name == manifest.requested_adapter else adapter_name
        )
        base_provenance = {
            # Keep the legacy key, but make it truthful: it is the backend that
            # actually produced the ranked hit, not merely the requested one.
            "text_index_adapter": actual_backend,
            "text_index_requested_adapter": requested_backend,
            "text_index_actual_adapter": actual_backend,
            "text_index_fallback_used": bool(hit.fallback_used),
            "text_index_fallback_reason": hit.fallback_reason,
            "text_index_manifest_fingerprint": manifest.build_fingerprint,
            "matched_fields": hit.matched_fields,
            "match_modes": hit.match_modes,
            "term_contributions": hit.term_contributions,
            "persistent_text_index": True,
        }
        if source == "ocr":
            candidate = SearchCandidate(
                query_id=query_id,
                video_id=str(metadata["video_id"]),
                frame_id=int(metadata.get("frame_id", 0)),
                timestamp_ms=int(metadata.get("timestamp_ms", 0)),
                source="ocr",
                raw_score=float(hit.score),
                score=float(hit.score),
                rank=rank,
                evidence_refs=[document.doc_id],
                provenance_sources=["ocr"],
                provenance={
                    **base_provenance,
                    "bbox_xyxy_norm": metadata.get("bbox_xyxy_norm"),
                    "crop_evidence_path": metadata.get("crop_evidence_path"),
                    "raw_text": metadata.get("raw_text"),
                    "normalized_text": metadata.get("normalized_text"),
                    "normalized_text_no_diacritics": metadata.get(
                        "normalized_text_no_diacritics"
                    ),
                    "confidence": metadata.get("confidence"),
                    "frame_resolution": "source_keyframe",
                    "localization_required": False,
                    "submittable": True,
                },
                confidence=metadata.get("confidence"),
                preprocess_run_id=run_id,
                created_at_utc=utcnow_iso(),
            )
        elif source == "asr":
            start_ms = int(metadata.get("start_ms", 0))
            end_ms = int(metadata.get("end_ms", start_ms))
            candidate = SearchCandidate(
                query_id=query_id,
                video_id=str(metadata["video_id"]),
                frame_id=0,
                representative_frame_id=None,
                timestamp_ms=(start_ms + end_ms) // 2,
                window_start_ms=start_ms,
                window_end_ms=end_ms,
                source="asr",
                raw_score=float(hit.score),
                score=float(hit.score),
                rank=rank,
                evidence_refs=[document.doc_id],
                provenance_sources=["asr"],
                provenance={
                    **base_provenance,
                    "segment_id": document.doc_id,
                    "text": metadata.get("text", ""),
                    "language": metadata.get("language"),
                    "confidence": metadata.get("confidence"),
                    "model_name": metadata.get("model_name"),
                    "frame_resolution": "pending_temporal_registry",
                    "localization_required": True,
                    "submittable": False,
                },
                confidence=metadata.get("confidence"),
                preprocess_run_id=run_id,
                created_at_utc=utcnow_iso(),
            )
            if temporal_registry is not None:
                try:
                    candidate = temporal_registry.canonicalize_candidate(candidate)
                    provenance = dict(candidate.provenance)
                    provenance.update(
                        {
                            "frame_resolution": "temporal_registry",
                            "localization_required": False,
                            "submittable": True,
                        }
                    )
                    candidate = candidate.model_copy(update={"provenance": provenance})
                except Exception as exc:
                    provenance = dict(candidate.provenance)
                    provenance["frame_resolution_error"] = f"{type(exc).__name__}: {exc}"
                    candidate = candidate.model_copy(update={"provenance": provenance})
        else:
            frame_id, timestamp_ms, localized = representative_frames.get(
                str(metadata["video_id"]),
                (0, 0, False),
            )
            candidate = SearchCandidate(
                query_id=query_id,
                video_id=str(metadata["video_id"]),
                frame_id=frame_id,
                representative_frame_id=frame_id if localized else None,
                timestamp_ms=timestamp_ms,
                window_start_ms=metadata.get("window_start_ms"),
                window_end_ms=metadata.get("window_end_ms"),
                source="metadata",
                raw_score=float(hit.score),
                score=float(hit.score),
                rank=rank,
                evidence_refs=[document.doc_id],
                provenance_sources=["metadata"],
                provenance={
                    **base_provenance,
                    "metadata_source": metadata.get("metadata_source")
                    or metadata.get("source"),
                    "title": metadata.get("title"),
                    "description": metadata.get("description"),
                    "tags": metadata.get("tags", []),
                    "channel": metadata.get("channel"),
                    "youtube_video_id": metadata.get("youtube_video_id"),
                    "localization_required": True,
                    "temporal_representative_available": localized,
                    "submittable": False,
                    "policy": "video_soft_boost_only",
                },
                confidence=metadata.get("confidence"),
                preprocess_run_id=run_id,
                created_at_utc=utcnow_iso(),
            )
        results.append(candidate)
    return results


def _middle_frame(rows: Sequence[Any]) -> tuple[int, int, bool]:
    if not rows:
        return 0, 0, False
    ordered = sorted(
        rows,
        key=lambda row: (
            int(row.timestamp_ms if hasattr(row, "timestamp_ms") else row.get("timestamp_ms", 0)),
            int(row.frame_id if hasattr(row, "frame_id") else row.get("frame_id", 0)),
        ),
    )
    middle = ordered[len(ordered) // 2]
    frame_id = int(middle.frame_id if hasattr(middle, "frame_id") else middle["frame_id"])
    timestamp_ms = int(
        middle.timestamp_ms if hasattr(middle, "timestamp_ms") else middle["timestamp_ms"]
    )
    return frame_id, timestamp_ms, True


def _build_representative_frame_map(
    run_root: Path,
    *,
    video_ids: set[str],
    temporal_registry: Any | None,
) -> dict[str, tuple[int, int, bool]]:
    """Load frame artifacts at most once and precompute video representatives."""

    if not video_ids:
        return {}
    if temporal_registry is not None:
        return {
            video_id: _middle_frame(temporal_registry.frames_by_video.get(video_id, []))
            for video_id in video_ids
        }

    temporal_path = run_root / "temporal" / "temporal_frames.jsonl"
    source_path = temporal_path if temporal_path.is_file() else run_root / "frames.jsonl"
    grouped: dict[str, list[dict[str, Any]]] = {video_id: [] for video_id in video_ids}
    for row in read_jsonl(source_path):
        video_id = str(row.get("video_id", ""))
        if video_id in grouped:
            grouped[video_id].append(row)
    return {video_id: _middle_frame(rows) for video_id, rows in grouped.items()}

