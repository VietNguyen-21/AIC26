"""Safe video/ZIP inventory command without running preprocessing."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from aic2026.config import load_settings
from aic2026.ingest import ingest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("--output-root", type=Path, default=Path("reports/archive_scan"))
    parser.add_argument("--config", type=Path, default=Path("configs/default.yaml"))
    args = parser.parse_args()

    settings, _ = load_settings(args.config)
    records = ingest(
        args.source,
        args.output_root,
        workspace=args.output_root / "extracted",
        batch_id=settings.corpus.batch_id,
        video_id_rule=settings.corpus.video_id_rule,
        max_archive_members=settings.corpus.max_archive_members,
        max_archive_uncompressed_bytes=settings.corpus.max_archive_uncompressed_bytes,
        max_archive_compression_ratio=settings.corpus.max_archive_compression_ratio,
    )
    print(
        json.dumps(
            [record.model_dump(mode="json") for record in records],
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
