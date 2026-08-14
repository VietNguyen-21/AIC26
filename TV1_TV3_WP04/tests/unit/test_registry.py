from __future__ import annotations

import pytest

from aic2026.registry import RegistryLockError, RunRegistry
from aic2026.utils import sha256_file


def completed_details(run_root, artifact):
    relative = artifact.relative_to(run_root).as_posix()
    return {
        "artifact_paths": [relative],
        "artifact_checksums": {relative: sha256_file(artifact)},
    }


def test_completed_module_is_skipped_until_artifact_changes(tmp_path):
    run_root = tmp_path / "run"
    artifact = run_root / "outputs" / "item.json"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("one", encoding="utf-8")
    with RunRegistry(run_root / "registry.sqlite3") as registry:
        registry.begin_module("r1", "v1", "media_probe", "fp")
        registry.complete_module(
            "r1", "v1", "media_probe", "fp", completed_details(run_root, artifact)
        )
        decision = registry.decide(
            "r1", "v1", "media_probe", "fp", run_root=run_root
        )
        assert not decision.should_run
        assert decision.reason == "completed_and_artifacts_valid"

        artifact.write_text("corrupt", encoding="utf-8")
        decision = registry.decide(
            "r1", "v1", "media_probe", "fp", run_root=run_root
        )
        assert decision.should_run
        assert decision.reason == "artifact_missing_or_corrupt"


def test_failed_module_respects_retry_flag(tmp_path):
    run_root = tmp_path / "run"
    with RunRegistry(run_root / "registry.sqlite3") as registry:
        registry.begin_module("r1", "v1", "keyframes", "fp")
        registry.fail_module("r1", "v1", "keyframes", "fp", RuntimeError("boom"))
        no_retry = registry.decide(
            "r1",
            "v1",
            "keyframes",
            "fp",
            run_root=run_root,
            retry_failed=False,
        )
        retry = registry.decide(
            "r1",
            "v1",
            "keyframes",
            "fp",
            run_root=run_root,
            retry_failed=True,
        )
        assert not no_retry.should_run
        assert no_retry.reason == "failed_retry_disabled"
        assert retry.should_run


def test_module_lock_prevents_concurrent_writer(tmp_path):
    run_root = tmp_path / "run"
    with RunRegistry(run_root / "registry.sqlite3") as registry:
        first = registry.module_lock(run_root, "v1", "audio")
        second = registry.module_lock(run_root, "v1", "audio")
        first.acquire()
        try:
            with pytest.raises(RegistryLockError):
                second.acquire(timeout_seconds=0)
        finally:
            first.release()
        second.acquire(timeout_seconds=0)
        second.release()
