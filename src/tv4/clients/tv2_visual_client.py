"""Subprocess client for TV2's WP03 visual retrieval CLI.

WP03 ships as a CLI (`python -m wp03 search ...`) that must run inside its
own GPU-enabled virtualenv (see WP03/envs/*.txt and configs/runtime.*.yaml).
TV4 therefore shells out to that interpreter instead of importing wp03
in-process, so TV4 itself keeps working on machines without the four visual
model stacks installed.
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from ..contracts import SearchCandidate


class TV2VisualClientError(RuntimeError):
    pass


@dataclass
class TV2VisualClient:
    python_executable: str  # path to WP03's venv python, e.g. WP03/.venv/Scripts/python.exe
    wp03_cwd: Path          # WP03 repo root (so `-m wp03` resolves)
    artifact_root: Path
    runtime_root: Path | None = None
    runtime_profile: Path | None = None
    top_k: int = 100
    candidate_k_per_model: int = 200
    enabled: bool = True

    def search(self, query_id: str, query_text: str, event_index: int | None = None) -> list[SearchCandidate]:
        if not self.enabled:
            return []
        cmd = [
            self.python_executable, "-m", "wp03", "search",
            "--artifact-root", str(self.artifact_root),
            "--query", query_text,
            "--query-id", query_id,
            "--top-k", str(self.top_k),
            "--candidate-k-per-model", str(self.candidate_k_per_model),
        ]
        if event_index is not None:
            cmd += ["--event-index", str(event_index)]
        if self.runtime_root:
            cmd += ["--runtime-root", str(self.runtime_root)]
        if self.runtime_profile:
            cmd += ["--runtime-profile", str(self.runtime_profile)]
        try:
            proc = subprocess.run(
                cmd, cwd=str(self.wp03_cwd), capture_output=True, text=True, timeout=180,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise TV2VisualClientError(f"failed to invoke wp03 search: {exc}") from exc
        if proc.returncode != 0:
            # Degrade gracefully: visual branch unavailable (e.g. BEiT-3
            # locked pending validation) should not abort the whole query.
            return []
        try:
            payload = json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            raise TV2VisualClientError(f"wp03 search returned non-JSON output: {proc.stdout[:300]}") from exc
        candidates = payload.get("candidates", [])
        return [SearchCandidate.from_json(c) for c in candidates]
