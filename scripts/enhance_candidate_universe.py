#!/usr/bin/env python3
"""Enrich a local candidate universe with AKShare/BaoStock daily MA facts."""

from __future__ import annotations

import argparse
import csv
import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from market_data import fetch_daily_bars, normalize_stock_code, summarize_daily_series


ENRICH_FIELDS = [
    "data_status",
    "data_provider",
    "data_source",
    "latest_trade_date",
    "bar_count",
    "close",
    "change_pct",
    "volume",
    "avg_volume20",
    "amount",
    "turnover",
    "ma5",
    "ma10",
    "ma20",
    "ma50",
    "ma200",
    "ma5_relation_pct",
    "ma10_relation_pct",
    "ma20_relation_pct",
    "ma50_relation_pct",
    "ma200_relation_pct",
    "ma5_state",
    "ma10_state",
    "ma20_state",
    "ma50_state",
    "ma200_state",
    "ma_summary",
    "ma_first_hand_score",
    "ma_first_hand_reasons",
    "ma_first_hand_risks",
    "data_notes",
]


def read_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), list(reader)


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    output_fields = fieldnames + [field for field in ENRICH_FIELDS if field not in fieldnames]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=output_fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def parse_date(value: str) -> date:
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"unsupported date format: {value}")


def row_code(row: dict[str, str]) -> str:
    return normalize_stock_code(row.get("stock_code") or row.get("code") or row.get("证券代码") or "")


def is_excluded(code: str, prefixes: list[str]) -> bool:
    return any(code.startswith(prefix) for prefix in prefixes)


def enrich_rows(args: argparse.Namespace) -> tuple[list[str], list[dict[str, Any]], dict[str, Any]]:
    fieldnames, rows = read_rows(args.universe_csv)
    end = parse_date(args.trade_date)
    start = end - timedelta(days=args.lookback_days)
    exclude_prefixes = [] if args.include_688 else args.exclude_prefix
    enriched: list[dict[str, Any]] = []
    summary: dict[str, Any] = {
        "trade_date": args.trade_date,
        "provider": args.provider,
        "adjust": args.adjust,
        "exclude_prefixes": exclude_prefixes,
        "rows": len(rows),
        "ok": 0,
        "excluded": 0,
        "failed": 0,
        "notes": [],
    }
    for row in rows:
        output: dict[str, Any] = dict(row)
        code = row_code(row)
        if not code:
            output.update({"data_status": "failed", "data_notes": "缺少证券代码。"})
            summary["failed"] += 1
            enriched.append(output)
            continue
        output.setdefault("stock_code", code)
        if is_excluded(code, exclude_prefixes):
            output.update(
                {
                    "data_status": "excluded",
                    "data_notes": f"按账户可交易范围剔除：{code} 属于排除前缀。",
                }
            )
            summary["excluded"] += 1
            enriched.append(output)
            continue
        try:
            series = fetch_daily_bars(
                code,
                start.isoformat(),
                end.isoformat(),
                provider=args.provider,
                adjust=args.adjust,
            )
            metrics = summarize_daily_series(series)
            output.update(metrics)
            output["data_status"] = "ok" if metrics.get("close") is not None else "partial"
            summary["ok"] += 1
        except Exception as exc:  # noqa: BLE001 - preserve per-stock degradation.
            output.update(
                {
                    "data_status": "failed",
                    "data_notes": f"{exc.__class__.__name__}: {exc}",
                }
            )
            summary["failed"] += 1
        enriched.append(output)
    return fieldnames, enriched, summary


def main() -> int:
    parser = argparse.ArgumentParser(description="用 AKShare/BaoStock 给候选池补齐日线、均线和均线先手分。")
    parser.add_argument("universe_csv", type=Path)
    parser.add_argument("--trade-date", default=date.today().isoformat())
    parser.add_argument("--provider", choices=["auto", "akshare", "baostock"], default="auto")
    parser.add_argument("--adjust", choices=["qfq", "hfq", "none"], default="qfq")
    parser.add_argument("--lookback-days", type=int, default=460)
    parser.add_argument("--exclude-prefix", action="append", default=["688"])
    parser.add_argument("--include-688", action="store_true", help="不剔除 688，仅用于板块温度计观察。")
    parser.add_argument("--output", type=Path, default=Path("reports/enriched_candidate_universe.csv"))
    parser.add_argument("--json", type=Path, default=Path("reports/enriched_candidate_universe.json"))
    args = parser.parse_args()

    fieldnames, rows, summary = enrich_rows(args)
    write_csv(args.output, fieldnames, rows)
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"enriched_csv: {args.output}")
    print(f"enriched_json: {args.json}")
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
