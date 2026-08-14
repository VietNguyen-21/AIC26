"""Subprocess client for TV2's WP09 exact-frame refinement JSON CLI.

TV4 provides the request payload (coarse candidate + task + refinement text
+ policy) via a temp JSON file and reads back one `RefineResult` JSON object
from stdout, per WP09's documented CLI contract:

    python -m wp09 refine --request request.json --config configs/default.yaml \
        --decoder-factory <module:callable> --scorer-factory <module:callable>

`--decoder-factory` / `--scorer-factory` point at TV4's own adapter
(`tv4.adapters.wp09_adapter`) because no other team member has published one
yet; see that module for the implementation.
"""
from __future__ import annotations

import json
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path


class TV2RefineClientError(RuntimeError):
    pass


@dataclass
class TV2RefineClient:
    python_executable: str
    wp09_cwd: Path
    config_path: Path
    decoder_factory: str = "tv4.adapters.wp09_adapter:decoder_for_request"
    scorer_factory: str | None = "tv4.adapters.wp09_adapter:scorer_for_request"
    enabled: bool = True

    def refine(self, request_payload: dict) -> dict | None:
        if not self.enabled:
            return None
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as fh:
            json.dump(request_payload, fh, ensure_ascii=False)
            request_path = Path(fh.name)
        try:
            cmd = [
                self.python_executable, "-m", "wp09", "refine",
                "--request", str(request_path),
                "--config", str(self.config_path),
                "--decoder-factory", self.decoder_factory,
            ]
            if self.scorer_factory:
                cmd += ["--scorer-factory", self.scorer_factory]
            try:
                proc = subprocess.run(
                    cmd, cwd=str(self.wp09_cwd), capture_output=True, text=True, timeout=60,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise TV2RefineClientError(f"failed to invoke wp09 refine: {exc}") from exc
            if proc.returncode != 0:
                return None
            try:
                return json.loads(proc.stdout)
            except json.JSONDecodeError:
                return None
        finally:
            request_path.unlink(missing_ok=True)
