#!/usr/bin/env python3
"""Prepare a private Cloudflare Pages bundle without modifying the local site."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path


FORBIDDEN_SUFFIXES = {".csv", ".db", ".pdf", ".sqlite", ".sqlite3", ".xls", ".xlsx"}


def prepare(source: Path, worker: Path, output: Path) -> Path:
    if not (source / "index.html").is_file():
        raise ValueError(f"site index is missing: {source / 'index.html'}")
    if not worker.is_file():
        raise ValueError(f"auth worker is missing: {worker}")

    forbidden = [path for path in source.rglob("*") if path.is_file() and path.suffix.lower() in FORBIDDEN_SUFFIXES]
    if forbidden:
        names = ", ".join(str(path.relative_to(source)) for path in forbidden[:5])
        raise ValueError(f"private source files found in generated site: {names}")

    if output.exists():
        shutil.rmtree(output)
    shutil.copytree(source, output)
    shutil.copy2(worker, output / "_worker.js")
    return output


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=root / "reports" / "personal_site")
    parser.add_argument("--worker", type=Path, default=root / "deploy" / "cloudflare" / "worker.mjs")
    parser.add_argument("--output", type=Path, default=Path("/private/tmp/personal-trading-coach-deploy"))
    args = parser.parse_args()

    output = prepare(args.source.resolve(), args.worker.resolve(), args.output.resolve())
    file_count = sum(1 for path in output.rglob("*") if path.is_file())
    print(f"deployment_bundle={output}")
    print(f"file_count={file_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
