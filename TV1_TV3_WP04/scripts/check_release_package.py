"""CLI wrapper for the source-only release audit."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True

from aic2026.release import audit_release  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root",
        "--repository-root",
        dest="root",
        type=Path,
        default=Path("."),
    )
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()

    issues = audit_release(args.root)
    print(json.dumps({"issues": issues}, ensure_ascii=False, indent=2))
    return 1 if args.strict and issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
