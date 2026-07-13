#!/usr/bin/env python3
"""Build a research-only candidate pool from a local universe CSV."""

from __future__ import annotations

import argparse
import csv
import json
from datetime import date
from pathlib import Path


OUTPUT_FIELDS = [
    "stock_code",
    "stock_name",
    "theme",
    "buy_point",
    "notes",
    "close",
    "volume",
    "amount",
    "turnover",
    "change_pct",
    "avg_volume20",
    "ma5",
    "ma10",
    "ma20",
    "ma50",
    "ma200",
    "ma_summary",
    "data_provider",
    "data_source",
    "data_notes",
]


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def excluded_by_prefix(row: dict[str, str], prefixes: list[str]) -> bool:
    code = (row.get("stock_code") or row.get("code") or "").strip()
    return any(code.startswith(prefix) for prefix in prefixes)


def build_pool(rows: list[dict[str, str]], limit: int, exclude_prefixes: list[str]) -> list[dict[str, str]]:
    output: list[dict[str, str]] = []
    for row in rows:
        if excluded_by_prefix(row, exclude_prefixes):
            continue
        item = {field: str(row.get(field, "") or "").strip() for field in OUTPUT_FIELDS}
        item["stock_code"] = str(row.get("stock_code") or row.get("code") or "").strip()
        item["stock_name"] = str(row.get("stock_name") or row.get("name") or "").strip()
        output.append(item)
        if len(output) >= limit:
            break
    return output


def write_csv(rows: list[dict[str, str]], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def markdown(rows: list[dict[str, str]], trade_date: str) -> str:
    lines = [
        f"# 明日研究股票池 - {trade_date}",
        "",
        "本股票池用于研究预案训练，不是推荐名单，不构成买入或卖出建议。",
        "",
        "| 股票 | 题材 | 买点 | 均线事实 | 人工备注 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        label = f"{row.get('stock_code','')} {row.get('stock_name','')}".strip()
        lines.append(
            "| "
            + " | ".join(
                [
                    label,
                    row.get("theme", ""),
                    row.get("buy_point", ""),
                    row.get("ma_summary", ""),
                    row.get("notes", ""),
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## 使用规则",
            "",
            "- 用户最多选择 3 支进入明日交易预案。",
            "- 没有明确触发条件、失效条件、止损锚点和仓位上限，不能从研究池升级为预案。",
            "- 默认剔除 688 科创板股票；如需观察，只能作为板块温度计，不进入候选池。",
            "- 研究池结果需要次日复盘验证，并反馈到 `state/research_pool_protocol.md`。",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="基于本地行情/候选 CSV 生成研究股票池。")
    parser.add_argument("universe_csv", type=Path)
    parser.add_argument("--trade-date", default=date.today().isoformat())
    parser.add_argument("--limit", type=int, default=15)
    parser.add_argument("--exclude-prefix", action="append", default=["688"], help="默认剔除无法交易的代码前缀，可重复传入。")
    parser.add_argument("--include-688", action="store_true", help="允许 688 进入研究池，仅在账户可交易时使用。")
    parser.add_argument("--csv", type=Path, default=Path("reports/research_pool_candidates.csv"))
    parser.add_argument("--json", type=Path, default=Path("reports/research_pool_candidates.json"))
    parser.add_argument("--md", type=Path, default=Path("reports/research_pool_candidates.md"))
    args = parser.parse_args()

    exclude_prefixes = [] if args.include_688 else args.exclude_prefix
    rows = build_pool(read_rows(args.universe_csv), args.limit, exclude_prefixes)
    write_csv(rows, args.csv)
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.md.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps({"trade_date": args.trade_date, "rows": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    args.md.write_text(markdown(rows, args.trade_date), encoding="utf-8")
    print(f"research_pool_csv: {args.csv}")
    print(f"research_pool_md: {args.md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
