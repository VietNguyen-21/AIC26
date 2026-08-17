"""SQLite run registry, artifact manifests, locking, idempotency, and stable-run controls."""

from __future__ import annotations

import json
import os
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Literal

from .contracts import ModuleArtifactManifest
from .utils import read_json, sha256_file, utcnow_iso, write_json

# Stable runs are immutable; module status changes are coordinated through this registry.
ModuleStatus = Literal["pending", "running", "completed", "failed", "skipped"]


class RegistryError(RuntimeError):
    pass


class RegistryLockError(RegistryError):
    pass


@dataclass(frozen=True)
class RegistryEntry:
    run_id: str
    video_id: str
    module: str
    fingerprint: str
    status: str
    details: dict[str, Any]
    attempt_count: int
    started_at: str | None
    finished_at: str | None
    updated_at: str


@dataclass(frozen=True)
class ModuleDecision:
    should_run: bool
    reason: str
    previous: RegistryEntry | None = None


class FileModuleLock:
    """Portable process lock based on atomic O_EXCL lock-file creation."""

    def __init__(
        self,
        path: str | Path,
        *,
        stale_after_seconds: int = 6 * 3600,
        poll_seconds: float = 0.1,
    ):
        self.path = Path(path)
        self.stale_after_seconds = stale_after_seconds
        self.poll_seconds = poll_seconds
        self.acquired = False

    def acquire(self, timeout_seconds: float = 0.0) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + max(0.0, timeout_seconds)
        while True:
            try:
                descriptor = os.open(
                    self.path,
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                    0o644,
                )
                with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                    json.dump(
                        {
                            "pid": os.getpid(),
                            "created_at": utcnow_iso(),
                            "created_epoch": time.time(),
                        },
                        handle,
                    )
                self.acquired = True
                return
            except FileExistsError:
                try:
                    payload = read_json(self.path)
                    created_epoch = float(payload.get("created_epoch", 0.0))
                except Exception:
                    created_epoch = self.path.stat().st_mtime
                if time.time() - created_epoch > self.stale_after_seconds:
                    self.path.unlink(missing_ok=True)
                    continue
                if time.monotonic() >= deadline:
                    raise RegistryLockError(f"Module is locked: {self.path}")
                time.sleep(self.poll_seconds)

    def release(self) -> None:
        if self.acquired:
            self.path.unlink(missing_ok=True)
            self.acquired = False

    def __enter__(self) -> "FileModuleLock":
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.release()


class RunRegistry:
    """Coordinate module decisions, locks, attempts, artifacts, and immutable stable runs."""
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn: sqlite3.Connection | None = sqlite3.connect(self.path, timeout=30)
        self._connection().row_factory = sqlite3.Row
        self._connection().execute("PRAGMA journal_mode=WAL")
        self._connection().execute("PRAGMA foreign_keys=ON")
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        self._connection().execute(
            """
            CREATE TABLE IF NOT EXISTS module_status (
                run_id TEXT NOT NULL,
                video_id TEXT NOT NULL,
                module TEXT NOT NULL,
                fingerprint TEXT NOT NULL,
                status TEXT NOT NULL,
                details TEXT NOT NULL DEFAULT '{}',
                attempt_count INTEGER NOT NULL DEFAULT 0,
                started_at TEXT,
                finished_at TEXT,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (run_id, video_id, module)
            )
            """
        )
        columns = {
            row["name"] for row in self._connection().execute("PRAGMA table_info(module_status)")
        }
        migrations = {
            "attempt_count": "ALTER TABLE module_status ADD COLUMN attempt_count INTEGER NOT NULL DEFAULT 0",
            "started_at": "ALTER TABLE module_status ADD COLUMN started_at TEXT",
            "finished_at": "ALTER TABLE module_status ADD COLUMN finished_at TEXT",
        }
        for column, statement in migrations.items():
            if column not in columns:
                self._connection().execute(statement)
        self._connection().execute(
            """
            CREATE TABLE IF NOT EXISTS run_status (
                run_id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                source_manifest_sha256 TEXT,
                config_sha256 TEXT,
                details TEXT NOT NULL DEFAULT '{}',
                started_at TEXT NOT NULL,
                finished_at TEXT,
                updated_at TEXT NOT NULL
            )
            """
        )
        self._connection().commit()

    def close(self) -> None:
        connection = self.conn
        if connection is None:
            return
        self.conn = None
        connection.close()

    def _connection(self) -> sqlite3.Connection:
        if self.conn is None:
            raise RegistryError("RunRegistry is closed")
        return self.conn

    def __enter__(self) -> "RunRegistry":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()

    def register_run(
        self,
        run_id: str,
        *,
        status: str,
        source_manifest_sha256: str | None,
        config_sha256: str | None,
        details: dict[str, Any] | None = None,
        started_at: str | None = None,
        finished_at: str | None = None,
    ) -> None:
        now = utcnow_iso()
        existing = self._connection().execute(
            "SELECT started_at,status,details FROM run_status WHERE run_id=?", (run_id,)
        ).fetchone()
        if existing is not None and str(existing["status"]) == "stable" and status != "stable":
            raise RegistryError(
                f"Run {run_id} is stable and immutable; create a new run_id instead"
            )
        effective_started = (
            str(existing["started_at"]) if existing else (started_at or now)
        )
        self._connection().execute(
            """
            INSERT INTO run_status(
                run_id,status,source_manifest_sha256,config_sha256,details,
                started_at,finished_at,updated_at
            ) VALUES(?,?,?,?,?,?,?,?)
            ON CONFLICT(run_id) DO UPDATE SET
                status=excluded.status,
                source_manifest_sha256=excluded.source_manifest_sha256,
                config_sha256=excluded.config_sha256,
                details=excluded.details,
                finished_at=excluded.finished_at,
                updated_at=excluded.updated_at
            """,
            (
                run_id,
                status,
                source_manifest_sha256,
                config_sha256,
                json.dumps(details or {}, ensure_ascii=False),
                effective_started,
                finished_at,
                now,
            ),
        )
        self._connection().commit()

    def assert_run_mutable(self, run_id: str) -> None:
        row = self.get_run(run_id)
        if row is not None and row["status"] == "stable":
            raise RegistryError(
                f"Run {run_id} is stable and immutable; create a new run_id instead"
            )

    def mark_validated(
        self,
        run_id: str,
        *,
        validation_report_path: str | Path,
        validation_report_sha256: str,
        artifact_state_sha256: str,
        severity_counts: dict[str, int],
    ) -> None:
        row = self.get_run(run_id)
        if row is None:
            raise RegistryError(f"Run {run_id} is not registered")
        if row["status"] == "stable":
            return
        details = {
            **row["details"],
            "validation": {
                "status": "passed",
                "report_path": str(validation_report_path),
                "report_sha256": validation_report_sha256,
                "severity_counts": severity_counts,
                "artifact_state_sha256": artifact_state_sha256,
                "validated_at": utcnow_iso(),
            },
        }
        self.register_run(
            run_id,
            status="validated",
            source_manifest_sha256=row.get("source_manifest_sha256"),
            config_sha256=row.get("config_sha256"),
            details=details,
            started_at=row.get("started_at"),
            finished_at=row.get("finished_at"),
        )

    def record_validation_failure(
        self,
        run_id: str,
        *,
        validation_report_path: str | Path,
        validation_report_sha256: str,
        severity_counts: dict[str, int],
    ) -> None:
        row = self.get_run(run_id)
        if row is None:
            raise RegistryError(f"Run {run_id} is not registered")
        details = {
            **row["details"],
            "validation": {
                "status": "failed",
                "report_path": str(validation_report_path),
                "report_sha256": validation_report_sha256,
                "severity_counts": severity_counts,
                "validated_at": utcnow_iso(),
            },
        }
        if row["status"] == "stable":
            # Stable-run audits are written outside the stable run root by the
            # validator.  Never mutate the stable registry database.
            return
        self.register_run(
            run_id,
            status="partial",
            source_manifest_sha256=row.get("source_manifest_sha256"),
            config_sha256=row.get("config_sha256"),
            details=details,
            started_at=row.get("started_at"),
            finished_at=row.get("finished_at"),
        )

    def mark_stable(
        self,
        run_id: str,
        *,
        validation_report_path: str | Path,
        validation_report_sha256: str,
        artifact_state_sha256: str,
    ) -> None:
        """Seal a freshly validated run.

        The method verifies the report file and the artifact-state fingerprint
        recorded by ``mark_validated``.  This prevents a stale validation report
        from being reused after artifacts were changed.
        """

        row = self.get_run(run_id)
        if row is None:
            raise RegistryError(f"Run {run_id} is not registered")
        if row["status"] == "stable":
            return
        if row["status"] != "validated":
            raise RegistryError(
                f"Run {run_id} must be validated before it can be marked stable"
            )
        report_path = Path(validation_report_path)
        if not report_path.is_file():
            raise RegistryError(f"Validation report is missing: {report_path}")
        actual_report_sha = sha256_file(report_path)
        if actual_report_sha != validation_report_sha256:
            raise RegistryError(
                "Validation report checksum changed after validation: "
                f"expected {validation_report_sha256}, got {actual_report_sha}"
            )
        report = read_json(report_path)
        if not bool(report.get("g0_pass")) or not bool(report.get("stable_eligible")):
            raise RegistryError("Validation report is not stable-eligible")
        if str(report.get("artifact_state_sha256") or "") != artifact_state_sha256:
            raise RegistryError("Validation report artifact state does not match current state")
        validation = row.get("details", {}).get("validation", {})
        if validation.get("report_sha256") != validation_report_sha256:
            raise RegistryError("Registry validation report checksum does not match")
        if validation.get("artifact_state_sha256") != artifact_state_sha256:
            raise RegistryError("Registry artifact state does not match validation report")
        # Recompute at the registry boundary as well, so callers cannot bypass
        # the CLI freshness check and seal changed artifacts with a stale report.
        from .validation import compute_artifact_state_sha256

        run_root = self.path.parent.parent
        current_artifact_state = compute_artifact_state_sha256(run_root)
        if current_artifact_state != artifact_state_sha256:
            raise RegistryError(
                "Artifacts changed after validation: "
                f"expected {artifact_state_sha256}, got {current_artifact_state}"
            )
        details = {
            **row["details"],
            "stable": {
                "marked_at": utcnow_iso(),
                "validation_report_path": str(report_path),
                "validation_report_sha256": validation_report_sha256,
                "artifact_state_sha256": artifact_state_sha256,
            },
        }
        self.register_run(
            run_id,
            status="stable",
            source_manifest_sha256=row.get("source_manifest_sha256"),
            config_sha256=row.get("config_sha256"),
            details=details,
            started_at=row.get("started_at"),
            finished_at=row.get("finished_at"),
        )

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        row = self._connection().execute(
            "SELECT * FROM run_status WHERE run_id=?", (run_id,)
        ).fetchone()
        if row is None:
            return None
        return {
            **dict(row),
            "details": json.loads(row["details"] or "{}"),
        }

    @staticmethod
    def _entry(row: sqlite3.Row | None) -> RegistryEntry | None:
        if row is None:
            return None
        return RegistryEntry(
            run_id=str(row["run_id"]),
            video_id=str(row["video_id"]),
            module=str(row["module"]),
            fingerprint=str(row["fingerprint"]),
            status=str(row["status"]),
            details=json.loads(row["details"] or "{}"),
            attempt_count=int(row["attempt_count"] or 0),
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            updated_at=str(row["updated_at"]),
        )

    def get_status(self, run_id: str, video_id: str, module: str) -> RegistryEntry | None:
        row = self._connection().execute(
            "SELECT * FROM module_status WHERE run_id=? AND video_id=? AND module=?",
            (run_id, video_id, module),
        ).fetchone()
        return self._entry(row)

    def _upsert(
        self,
        run_id: str,
        video_id: str,
        module: str,
        fingerprint: str,
        status: ModuleStatus,
        *,
        details: dict[str, Any] | None = None,
        increment_attempt: bool = False,
        started_at: str | None = None,
        finished_at: str | None = None,
    ) -> None:
        previous = self.get_status(run_id, video_id, module)
        attempt_count = (previous.attempt_count if previous else 0) + (
            1 if increment_attempt else 0
        )
        now = utcnow_iso()
        self._connection().execute(
            """
            INSERT INTO module_status(
                run_id,video_id,module,fingerprint,status,details,attempt_count,
                started_at,finished_at,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(run_id,video_id,module) DO UPDATE SET
                fingerprint=excluded.fingerprint,
                status=excluded.status,
                details=excluded.details,
                attempt_count=excluded.attempt_count,
                started_at=excluded.started_at,
                finished_at=excluded.finished_at,
                updated_at=excluded.updated_at
            """,
            (
                run_id,
                video_id,
                module,
                fingerprint,
                status,
                json.dumps(details or {}, ensure_ascii=False),
                attempt_count,
                started_at,
                finished_at,
                now,
            ),
        )
        self._connection().commit()

    def begin_module(
        self,
        run_id: str,
        video_id: str,
        module: str,
        fingerprint: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        self._upsert(
            run_id,
            video_id,
            module,
            fingerprint,
            "running",
            details=details,
            increment_attempt=True,
            started_at=utcnow_iso(),
            finished_at=None,
        )

    def complete_module(
        self,
        run_id: str,
        video_id: str,
        module: str,
        fingerprint: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        previous = self.get_status(run_id, video_id, module)
        self._upsert(
            run_id,
            video_id,
            module,
            fingerprint,
            "completed",
            details=details,
            started_at=previous.started_at if previous else None,
            finished_at=utcnow_iso(),
        )

    def fail_module(
        self,
        run_id: str,
        video_id: str,
        module: str,
        fingerprint: str,
        error: BaseException,
        details: dict[str, Any] | None = None,
    ) -> None:
        previous = self.get_status(run_id, video_id, module)
        payload = {
            **(details or {}),
            "error_type": type(error).__name__,
            "error_message": str(error),
        }
        self._upsert(
            run_id,
            video_id,
            module,
            fingerprint,
            "failed",
            details=payload,
            started_at=previous.started_at if previous else None,
            finished_at=utcnow_iso(),
        )

    def skip_module(
        self,
        run_id: str,
        video_id: str,
        module: str,
        fingerprint: str,
        reason: str,
    ) -> None:
        previous = self.get_status(run_id, video_id, module)
        self._upsert(
            run_id,
            video_id,
            module,
            fingerprint,
            "skipped",
            details={"reason": reason},
            started_at=previous.started_at if previous else None,
            finished_at=utcnow_iso(),
        )

    def artifacts_valid(self, entry: RegistryEntry, run_root: str | Path) -> bool:
        checksums = entry.details.get("artifact_checksums") or {}
        paths = entry.details.get("artifact_paths") or []
        root = Path(run_root)
        if not paths:
            return False
        for relative in paths:
            path = root / relative
            if not path.is_file():
                return False
            expected = checksums.get(relative)
            if expected and sha256_file(path) != expected:
                return False
        return True

    def decide(
        self,
        run_id: str,
        video_id: str,
        module: str,
        fingerprint: str,
        *,
        run_root: str | Path,
        retry_failed: bool = True,
        recompute: bool = False,
    ) -> ModuleDecision:
        previous = self.get_status(run_id, video_id, module)
        if recompute:
            return ModuleDecision(True, "explicit_recompute", previous)
        if previous is None:
            return ModuleDecision(True, "not_registered", None)
        if previous.fingerprint != fingerprint:
            return ModuleDecision(True, "fingerprint_changed", previous)
        if previous.status == "completed":
            if self.artifacts_valid(previous, run_root):
                return ModuleDecision(False, "completed_and_artifacts_valid", previous)
            return ModuleDecision(True, "artifact_missing_or_corrupt", previous)
        if previous.status == "failed" and not retry_failed:
            return ModuleDecision(False, "failed_retry_disabled", previous)
        if (
            previous.status == "skipped"
            and previous.details.get("reason") == "disabled_by_config"
        ):
            return ModuleDecision(False, "disabled_by_config", previous)
        if previous.status == "running":
            return ModuleDecision(True, "interrupted_running_attempt", previous)
        return ModuleDecision(True, f"status_{previous.status}", previous)

    def is_complete(
        self,
        run_id: str,
        video_id: str,
        module: str,
        fingerprint: str,
        *,
        run_root: str | Path | None = None,
    ) -> bool:
        entry = self.get_status(run_id, video_id, module)
        if not entry or entry.status != "completed" or entry.fingerprint != fingerprint:
            return False
        return True if run_root is None else self.artifacts_valid(entry, run_root)

    def list_status(self, run_id: str) -> list[dict[str, Any]]:
        rows = self._connection().execute(
            "SELECT * FROM module_status WHERE run_id=? ORDER BY video_id,module",
            (run_id,),
        ).fetchall()
        entries = [self._entry(row) for row in rows]
        return [
            {
                "video_id": entry.video_id,
                "module": entry.module,
                "fingerprint": entry.fingerprint,
                "status": entry.status,
                "details": entry.details,
                "attempt_count": entry.attempt_count,
                "started_at": entry.started_at,
                "finished_at": entry.finished_at,
                "updated_at": entry.updated_at,
            }
            for entry in entries
            if entry is not None
        ]

    def summarize_run(self, run_id: str) -> dict[str, Any]:
        rows = self.list_status(run_id)
        counts: dict[str, int] = {}
        for row in rows:
            counts[row["status"]] = counts.get(row["status"], 0) + 1
        return {"run_id": run_id, "module_count": len(rows), "status_counts": counts}

    def module_lock(
        self,
        run_root: str | Path,
        video_id: str,
        module: str,
        *,
        stale_after_seconds: int = 6 * 3600,
    ) -> FileModuleLock:
        safe_video = video_id.replace("/", "_").replace("\\", "_")
        safe_module = module.replace("/", "_").replace("\\", "_")
        return FileModuleLock(
            Path(run_root) / ".locks" / f"{safe_video}.{safe_module}.lock",
            stale_after_seconds=stale_after_seconds,
        )


def artifact_manifest_path(
    run_root: str | Path, video_id: str, module_name: str
) -> Path:
    safe_video = video_id.replace("/", "_").replace("\\", "_")
    safe_module = module_name.replace("/", "_").replace("\\", "_")
    return Path(run_root) / "registry" / "artifacts" / safe_video / f"{safe_module}.json"


def save_artifact_manifest(run_root: str | Path, manifest: ModuleArtifactManifest) -> Path:
    path = artifact_manifest_path(run_root, manifest.video_id or "__run__", manifest.module_name)
    write_json(path, manifest.model_dump(mode="json"))
    return path
