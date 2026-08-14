"""TV4 CLI.

    python -m tv4 kis   --config configs/default.yaml --query "..." [--out outputs/kis.csv]
    python -m tv4 qa    --config configs/default.yaml --query "..." --question "..." [--out outputs/qa.csv]
    python -m tv4 trake --config configs/default.yaml --query "..." [--out outputs/trake.json]
    python -m tv4 batch --config configs/default.yaml --queries queries.json --out outputs/
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

from .clients.tv1_client import TV1Client
from .clients.tv2_refine_client import TV2RefineClient
from .clients.tv2_visual_client import TV2VisualClient
from .clients.tv3_client import TV3Client
from .kis_pipeline import KisServices, run_kis_query
from .submission import write_kis_csv, write_qa_csv, write_trake_json
from .trake_pipeline import run_trake_query
from .wp11_vqa import RuleBasedFallbackEngine, answer_query


def _load_config(path: str) -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def build_services(config: dict) -> KisServices:
    base = Path(config.get("_config_dir", "."))
    tv2v = config["tv2_visual"]
    tv2r = config.get("tv2_refine", {"enabled": False})
    visual = TV2VisualClient(
        python_executable=str((base / tv2v["python_executable"]).resolve()),
        wp03_cwd=(base / tv2v["wp03_cwd"]).resolve(),
        artifact_root=(base / tv2v["artifact_root"]).resolve(),
        runtime_root=(base / tv2v["runtime_root"]).resolve() if tv2v.get("runtime_root") else None,
        runtime_profile=(base / tv2v["runtime_profile"]).resolve() if tv2v.get("runtime_profile") else None,
        top_k=tv2v.get("top_k", 100),
        candidate_k_per_model=tv2v.get("candidate_k_per_model", 200),
        enabled=tv2v.get("enabled", True),
    )
    refine = None
    if tv2r.get("enabled"):
        refine = TV2RefineClient(
            python_executable=str((base / tv2r["python_executable"]).resolve()),
            wp09_cwd=(base / tv2r["wp09_cwd"]).resolve(),
            config_path=(base / tv2r["config_path"]).resolve(),
        )
    return KisServices(
        tv1=TV1Client(config["tv1"]["base_url"]),
        tv3=TV3Client(config["tv3"]["base_url"]),
        visual=visual,
        refine=refine,
        preprocess_run_id=config.get("preprocess_run_id", "unknown"),
    )


def _cmd_kis(args: argparse.Namespace) -> int:
    config = _load_config(args.config)
    config["_config_dir"] = str(Path(args.config).parent)
    services = build_services(config)
    ranked = run_kis_query(args.query, services, top_k=config["fusion"]["top_k"])
    out = Path(args.out) if args.out else Path(config["output_dir"]) / "kis.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    write_kis_csv(out, ranked[0].query_id if ranked else "kis-query", ranked)
    print(f"Wrote {len(ranked)} ranked candidates to {out}")
    return 0


def _cmd_qa(args: argparse.Namespace) -> int:
    config = _load_config(args.config)
    config["_config_dir"] = str(Path(args.config).parent)
    services = build_services(config)
    ranked = run_kis_query(args.query, services, top_k=config["fusion"]["top_k"])
    engine = RuleBasedFallbackEngine()
    results = [answer_query(c, args.question, services.tv1, services.tv3, engine) for c in ranked]
    out = Path(args.out) if args.out else Path(config["output_dir"]) / "qa.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    write_qa_csv(out, ranked[0].query_id if ranked else "qa-query", results)
    print(f"Wrote {len(results)} ranked (video,frame,answer) rows to {out}")
    return 0


def _cmd_trake(args: argparse.Namespace) -> int:
    config = _load_config(args.config)
    config["_config_dir"] = str(Path(args.config).parent)
    services = build_services(config)
    hyp = run_trake_query(args.query, services, strategy=args.strategy)
    out = Path(args.out) if args.out else Path(config["output_dir"]) / "trake.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    write_trake_json(out, hyp.query_id if hyp else "trake-query", hyp)
    print(f"Wrote TRAKE result ({'ok' if hyp else 'no monotonic alignment found'}) to {out}")
    return 0


def _cmd_batch(args: argparse.Namespace) -> int:
    config = _load_config(args.config)
    config["_config_dir"] = str(Path(args.config).parent)
    services = build_services(config)
    queries = json.loads(Path(args.queries).read_text(encoding="utf-8"))
    out_dir = Path(args.out) if args.out else Path(config["output_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)
    for q in queries:
        task = q["task"]
        qid = q.get("query_id", "q")
        if task == "KIS":
            ranked = run_kis_query(q["query_text"], services, query_id=qid, top_k=config["fusion"]["top_k"])
            write_kis_csv(out_dir / f"{qid}.csv", qid, ranked)
        elif task == "VQA":
            ranked = run_kis_query(q["query_text"], services, query_id=qid, top_k=config["fusion"]["top_k"])
            engine = RuleBasedFallbackEngine()
            results = [answer_query(c, q["question"], services.tv1, services.tv3, engine) for c in ranked]
            write_qa_csv(out_dir / f"{qid}.csv", qid, results)
        elif task == "TRAKE":
            hyp = run_trake_query(q["query_text"], services, events=q.get("events"), query_id=qid)
            write_trake_json(out_dir / f"{qid}.json", qid, hyp)
        else:
            print(f"skip unknown task {task!r} for {qid}", file=sys.stderr)
    print(f"Batch complete: {len(queries)} queries -> {out_dir}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tv4")
    sub = parser.add_subparsers(dest="command", required=True)

    p_kis = sub.add_parser("kis")
    p_kis.add_argument("--config", required=True)
    p_kis.add_argument("--query", required=True)
    p_kis.add_argument("--out")
    p_kis.set_defaults(func=_cmd_kis)

    p_qa = sub.add_parser("qa")
    p_qa.add_argument("--config", required=True)
    p_qa.add_argument("--query", required=True)
    p_qa.add_argument("--question", required=True)
    p_qa.add_argument("--out")
    p_qa.set_defaults(func=_cmd_qa)

    p_trake = sub.add_parser("trake")
    p_trake.add_argument("--config", required=True)
    p_trake.add_argument("--query", required=True)
    p_trake.add_argument("--strategy", default="dp", choices=["dp", "greedy"])
    p_trake.add_argument("--out")
    p_trake.set_defaults(func=_cmd_trake)

    p_batch = sub.add_parser("batch")
    p_batch.add_argument("--config", required=True)
    p_batch.add_argument("--queries", required=True)
    p_batch.add_argument("--out")
    p_batch.set_defaults(func=_cmd_batch)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
