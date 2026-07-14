#!/usr/bin/env python3
"""Build and verify the Xueqiu watchlist payload for the canonical stock pool."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Iterable

try:
    from build_personal_site import extract_research_pool_candidates, xueqiu_quote_url
except ModuleNotFoundError:  # Importable as scripts.xueqiu_watchlist_sync in tests.
    from scripts.build_personal_site import extract_research_pool_candidates, xueqiu_quote_url


EXPECTED_POOL_SIZE = 15


def _normalise_codes(codes: Iterable[str]) -> list[str]:
    return [str(code).strip().zfill(6) for code in codes if str(code).strip()]


def build_watchlist_manifest(
    research_pool_path: str | Path,
    *,
    run_id: str = "",
    trade_date: str = "",
) -> dict:
    """Build a public-code-only manifest without claiming Chrome sync occurred."""
    pool_path = Path(research_pool_path)
    candidates = extract_research_pool_candidates(pool_path.read_text(encoding="utf-8"))
    stocks = []
    for candidate in candidates:
        code = str(candidate.get("stock_code", "")).strip().zfill(6)
        name = str(candidate.get("stock_name", "")).strip()
        stocks.append(
            {
                "stock_code": code,
                "stock_name": name,
                "xueqiu_symbol": ("SH" if code.startswith("6") else "SZ") + code,
                "quote_url": xueqiu_quote_url(code),
            }
        )

    codes = [stock["stock_code"] for stock in stocks]
    errors = []
    if len(stocks) != EXPECTED_POOL_SIZE:
        errors.append(f"expected_{EXPECTED_POOL_SIZE}_stocks_got_{len(stocks)}")
    if len(set(codes)) != len(codes):
        errors.append("duplicate_stock_code")
    if any(code.startswith("688") for code in codes):
        errors.append("688_stock_not_tradable_for_account")

    return {
        "schema_version": 1,
        "run_id": run_id,
        "trade_date": trade_date,
        "source": pool_path.name,
        "status": "pending_chrome_sync" if not errors else "blocked_incomplete_pool",
        "errors": errors,
        "clear_existing": True,
        "count": len(stocks),
        "stocks": stocks,
        "synced_at": None,
        "verified_codes": [],
    }


def write_watchlist_manifest(
    research_pool_path: str | Path,
    output_path: str | Path,
    *,
    run_id: str = "",
    trade_date: str = "",
) -> dict:
    manifest = build_watchlist_manifest(
        research_pool_path,
        run_id=run_id,
        trade_date=trade_date,
    )
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def mark_manifest_synced(manifest_path: str | Path, verified_codes: Iterable[str]) -> dict:
    path = Path(manifest_path)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    expected = _normalise_codes(stock["stock_code"] for stock in manifest.get("stocks", []))
    verified = _normalise_codes(verified_codes)
    if sorted(expected) != sorted(verified):
        raise ValueError("verified Xueqiu codes do not exactly match the canonical 15-stock pool")
    if manifest.get("status") == "blocked_incomplete_pool":
        raise ValueError("cannot mark an incomplete stock pool as synced")
    manifest["status"] = "synced"
    manifest["synced_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    manifest["verified_codes"] = verified
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--research-pool", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--run-id", default="")
    parser.add_argument("--trade-date", default="")
    parser.add_argument("--mark-synced", type=Path, metavar="MANIFEST")
    parser.add_argument("--verified-codes", nargs="+", default=[])
    args = parser.parse_args()

    if args.mark_synced:
        mark_manifest_synced(args.mark_synced, args.verified_codes)
        return 0
    if not args.research_pool or not args.output:
        parser.error("--research-pool and --output are required when creating a manifest")
    manifest = write_watchlist_manifest(
        args.research_pool,
        args.output,
        run_id=args.run_id,
        trade_date=args.trade_date,
    )
    print(json.dumps({"status": manifest["status"], "count": manifest["count"]}, ensure_ascii=False))
    return 0 if manifest["status"] == "pending_chrome_sync" else 1


if __name__ == "__main__":
    raise SystemExit(main())
