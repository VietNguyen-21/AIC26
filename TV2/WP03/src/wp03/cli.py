"""Operational CLI for validating, building, inspecting and searching WP03."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Mapping, Sequence

import yaml

from .artifacts import sha256_file
from .config import RuntimeProfile, load_build_config
from .contracts import ContractError
from .corpus import load_corpus
from .digests import ContentValidationMode
from .model_lock import create_model_lock
from .orchestrator import BuildRequest, build_all_models
from .search import SearchEncoder, search_visual
from .worker_launcher import WorkerProcessEncoder
from .worker_protocol import compatibility_fingerprint
from .workers.beit3 import Adapter as Beit3Adapter
from .workers.beit3 import BEIT3_EXPECTED_SIZE_BYTES


SAFE_RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")


@dataclass(frozen=True)
class CliServices:
    """Injection seam used by CPU tests; normal CLI does not load model code in-process."""

    encoders: Mapping[str, SearchEncoder] = field(default_factory=dict)


def validate_run_id(run_id: str) -> str:
    if not SAFE_RUN_ID.fullmatch(run_id):
        raise ContractError("run_id must be a safe filename component")
    return run_id


def _print_json(payload: object) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def _load_config(path: Path) -> dict[str, object]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ContractError("config cannot be read") from exc
    if not isinstance(value, dict):
        raise ContractError("config must be a mapping")
    return value


def _validate(args: argparse.Namespace) -> dict[str, object]:
    corpus = load_corpus(Path(args.data_root), PurePosixPath(args.frames), None)
    return {"status": "ok", "records": len(corpus), "preprocess_run_id": corpus[0].preprocess_run_id}


def _build(args: argparse.Namespace, services: CliServices) -> dict[str, object]:
    run_id = validate_run_id(args.run_id)
    config = _load_config(Path(args.config))
    profile = RuntimeProfile.load(Path(args.runtime_profile), Path(args.runtime_root))
    mode = ContentValidationMode(args.content_validation)
    corpus = load_corpus(Path(args.data_root), PurePosixPath(args.frames), None)
    selected = config.get("selected_videos")
    if selected is not None:
        if not isinstance(selected, list) or not all(isinstance(item, str) for item in selected):
            raise ContractError("selected_videos must be null or strings")
        corpus = tuple(record for record in corpus if record.video_id in selected)
    if not corpus:
        raise ContractError("selected corpus is empty")
    rows_per_shard = config.get("rows_per_shard")
    if not isinstance(rows_per_shard, int) or rows_per_shard <= 0:
        raise ContractError("rows_per_shard must be positive")
    if mode is ContentValidationMode.STRICT:
        # Strict digest verification occurs when the build orchestrator is invoked.
        pass
    build_config = load_build_config(config)
    requests: list[BuildRequest] = []
    encoders: dict[str, object] = {}
    config_digest = sha256_file(Path(args.config))
    frames_digest = sha256_file(Path(args.data_root) / args.frames)
    for model_key, spec in build_config.models.items():
        fingerprint = compatibility_fingerprint(spec=spec)
        encoder = services.encoders.get(model_key)
        if encoder is None:
            encoder = WorkerProcessEncoder(
                command=profile.command_for(model_key),
                job_root=Path(args.artifact_root) / "jobs" / model_key,
                model_key=model_key,
                revision=spec.revision,
                device="cuda",
                dtype=spec.dtype,
                batch_size=spec.batch_size,
                timeout_seconds=spec.timeout_seconds,
                fallback_dtype=spec.fallback_dtype,
                expected_dimension=spec.expected_dimension,
                _compatibility_fingerprint=fingerprint,
                environment=profile.environment_for(model_key),
            )
        if not hasattr(encoder, "encode_images"):
            raise ContractError(f"configured encoder for {model_key} cannot encode images")
        encoders[model_key] = encoder
        requests.append(
            BuildRequest(
                run_id, model_key, spec.revision, Path(args.data_root),
                Path(args.artifact_root), corpus, rows_per_shard, resume=args.resume,
                content_validation=mode, config_digest=config_digest, frames_input_digest=frames_digest,
                code_version=args.code_version, compatibility_fingerprint=fingerprint,
                expected_dimension=spec.expected_dimension,
                rrf_k=build_config.rrf_k, dedup_window_ms=build_config.dedup_window_ms,
            )
        )
    return build_all_models(requests, encoders).to_dict()


def _search(args: argparse.Namespace, services: CliServices) -> dict[str, object]:
    if args.top_k <= 0:
        raise ContractError("top_k must be positive")
    if not args.query.strip():
        raise ContractError("query must not be empty")
    encoders: Mapping[str, SearchEncoder] = services.encoders
    completed_manifests = sorted((Path(args.artifact_root) / "manifests").glob("*.json"))
    policy = next(
        (
            json.loads(path.read_text(encoding="utf-8"))
            for path in completed_manifests
            if json.loads(path.read_text(encoding="utf-8")).get("status") == "complete"
        ),
        {},
    )
    rrf_k = args.rrf_k if args.rrf_k is not None else int(policy.get("rrf_k", 60))
    dedup_window_ms = args.dedup_window_ms if args.dedup_window_ms is not None else policy.get("dedup_window_ms", 1_000)
    if not encoders:
        if not args.runtime_root or not args.runtime_profile:
            raise ContractError("search requires runtime root/profile unless test encoders are injected")
        profile = RuntimeProfile.load(Path(args.runtime_profile), Path(args.runtime_root))
        encoders = {}
        for manifest_path in sorted((Path(args.artifact_root) / "manifests").glob("*.json")):
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            model_key = str(manifest.get("model_key", ""))
            if manifest.get("status") == "complete" and model_key:
                encoders[model_key] = WorkerProcessEncoder(
                    command=profile.command_for(model_key),
                    job_root=Path(args.artifact_root) / "jobs" / model_key,
                    model_key=model_key, revision=str(manifest.get("model_version", "")),
                    device="cuda", dtype="float16", batch_size=1,
                    _compatibility_fingerprint=str(manifest.get("compatibility_fingerprint", "")),
                    environment=profile.environment_for(model_key),
                )
        if not encoders:
            raise ContractError("no complete model manifest is available")
    response = search_visual(
        query_id=args.query_id,
        query_text=args.query,
        event_index=args.event_index,
        artifact_root=Path(args.artifact_root),
        encoders=dict(encoders),
        requested_top_k=args.top_k,
        candidate_k_per_model=args.candidate_k_per_model,
        hard_candidate_cap=args.hard_candidate_cap,
        rrf_k=rrf_k,
        dedup_window_ms=dedup_window_ms,
    )
    return response.to_dict()


def _inspect(args: argparse.Namespace) -> dict[str, object]:
    root = Path(args.artifact_root)
    manifests = sorted((root / "manifests").glob("*.json"))
    if not manifests:
        raise ContractError("no manifests found")
    results: dict[str, object] = {}
    for path in manifests:
        body = json.loads(path.read_text(encoding="utf-8"))
        model_key = str(body.get("model_key", ""))
        if body.get("status") != "complete" or not model_key:
            raise ContractError(f"manifest {path.name} is not complete")
        for kind, suffix, field in (("indexes", ".faiss", "index_sha256"), ("embedding_maps", ".parquet", "mapping_sha256")):
            artifact = root / kind / f"{model_key}{suffix}"
            if sha256_file(artifact) != body.get(field):
                raise ContractError(f"{model_key} {kind} digest mismatch")
        results[model_key] = {"vector_count": body.get("vector_count"), "status": "complete"}
    return {"status": "ok", "models": results}


def _lock_model(args: argparse.Namespace) -> dict[str, object]:
    if args.model != "beit3":
        raise ContractError("only beit3 has a checkpoint lock command")
    lock = create_model_lock(
        Path(args.checkpoint), Path(args.lock_path), Beit3Adapter.identity(), BEIT3_EXPECTED_SIZE_BYTES
    )
    return {"status": "locked", "model": lock.identity.name, "sha256": lock.sha256, "lock_path": str(lock.path)}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="wp03")
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate")
    validate.add_argument("--data-root", required=True)
    validate.add_argument("--frames", required=True)
    build = commands.add_parser("build")
    build.add_argument("--data-root", required=True)
    build.add_argument("--frames", required=True)
    build.add_argument("--run-id", required=True)
    build.add_argument("--config", required=True)
    build.add_argument("--runtime-root", required=True)
    build.add_argument("--runtime-profile", required=True)
    build.add_argument("--content-validation", choices=[item.value for item in ContentValidationMode], required=True)
    build.add_argument("--artifact-root", default="artifacts")
    build.add_argument("--code-version", required=True)
    build.add_argument("--resume", action="store_true")
    search = commands.add_parser("search")
    search.add_argument("--artifact-root", required=True)
    search.add_argument("--query", required=True)
    search.add_argument("--query-id", default="wp03-query")
    search.add_argument("--event-index", type=int)
    search.add_argument("--top-k", type=int, required=True)
    search.add_argument("--candidate-k-per-model", type=int, default=200)
    search.add_argument("--hard-candidate-cap", type=int)
    search.add_argument("--rrf-k", type=int)
    search.add_argument("--dedup-window-ms", type=int)
    search.add_argument("--runtime-root")
    search.add_argument("--runtime-profile")
    inspect = commands.add_parser("inspect")
    inspect.add_argument("--artifact-root", required=True)
    lock = commands.add_parser("lock-model")
    lock.add_argument("--model", required=True)
    lock.add_argument("--checkpoint", required=True)
    lock.add_argument("--lock-path", default="model-locks/beit3.json")
    return parser


def main(argv: Sequence[str] | None = None, services: CliServices | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
        selected = services or CliServices()
        if args.command == "validate":
            result = _validate(args)
        elif args.command == "build":
            result = _build(args, selected)
        elif args.command == "search":
            result = _search(args, selected)
        elif args.command == "inspect":
            result = _inspect(args)
        else:
            result = _lock_model(args)
        _print_json(result)
        if args.command == "build" and isinstance(result, dict) and result.get("status") == "failed":
            return 2
        return 0
    except (ContractError, OSError, ValueError) as exc:
        print(json.dumps({"status": "error", "error": str(exc)}), file=sys.stderr)
        return 2
