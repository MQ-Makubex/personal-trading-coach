#!/usr/bin/env python3
"""Parse copied broker trade-table text into canonical trade facts."""

from __future__ import annotations

import argparse
import csv
import json
import re
from datetime import date
from pathlib import Path


OUTPUT_FIELDS = [
    "trade_date",
    "trade_time",
    "stock_code",
    "stock_name",
    "side",
    "quantity",
    "price",
    "amount",
    "net_amount",
    "commission",
    "stamp_tax",
    "transfer_fee",
    "other_fee",
]

ALIASES = {
    "trade_date": ["发生日期", "成交日期", "交收日期", "交易日期", "trade_date"],
    "trade_time": ["发生时间", "成交时间", "委托时间", "时间", "trade_time"],
    "stock_code": ["证券代码", "股票代码", "代码", "stock_code", "symbol"],
    "stock_name": ["证券名称", "股票名称", "名称", "stock_name", "security_name"],
    "side": ["交易类别", "委托方向", "买卖方向", "买卖类别", "交易方向", "操作", "side"],
    "quantity": ["成交数量", "成交股数", "数量", "股数", "quantity", "qty"],
    "price": ["成交价格", "成交均价", "成交价", "价格", "price"],
    "amount": ["成交金额", "成交额", "amount"],
    "net_amount": ["发生金额", "总发生金额", "资金发生额", "net_amount", "cash_amount"],
    "commission": ["佣金", "手续费", "交易佣金", "commission"],
    "stamp_tax": ["印花税", "stamp_tax"],
    "transfer_fee": ["过户费", "transfer_fee"],
    "other_fee": ["交易规费", "规费", "其他费用", "经手费", "证管费", "other_fee"],
}

REQUIRED_FIELDS = ["stock_code", "stock_name", "side", "quantity", "price"]


def normalize_text(value: object) -> str:
    return re.sub(r"[\s_\-:：/()（）]+", "", str(value or "").strip().lower())


def split_line(line: str) -> list[str]:
    stripped = line.strip()
    if "\t" in stripped:
        return [cell.strip() for cell in stripped.split("\t") if cell.strip()]
    return [cell.strip() for cell in re.split(r"\s{2,}", stripped) if cell.strip()]


def normalize_side(value: object) -> str:
    text = str(value or "").strip()
    upper = text.upper()
    if upper in {"BUY", "B"} or "证券买入" in text or "买入" in text:
        return "BUY"
    if upper in {"SELL", "S"} or "证券卖出" in text or "卖出" in text:
        return "SELL"
    return upper


def clean_number(value: object) -> str:
    text = str(value or "").strip().replace(",", "").replace("￥", "").replace("¥", "")
    if text in {"", "--", "-", "无", "None"}:
        return ""
    is_parenthesized_negative = text.startswith("(") and text.endswith(")")
    text = text.strip("()")
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return ""
    number = match.group(0)
    if is_parenthesized_negative and not number.startswith("-"):
        number = "-" + number
    return number


def find_header(lines: list[str]) -> tuple[int, list[str]]:
    best_index = -1
    best_score = -1
    best_cells: list[str] = []
    alias_tokens = {token for aliases in ALIASES.values() for token in aliases}
    for index, line in enumerate(lines):
        cells = split_line(line)
        if len(cells) < 4:
            continue
        score = 0
        for cell in cells:
            normalized = normalize_text(cell)
            if any(normalize_text(alias) == normalized or normalize_text(alias) in normalized for alias in alias_tokens):
                score += 1
        if score > best_score:
            best_index = index
            best_score = score
            best_cells = cells
    if best_index < 0 or best_score < 3:
        raise ValueError("无法识别表头：请粘贴包含证券代码、证券名称、买卖方向、成交数量、成交价格的表格文本。")
    return best_index, best_cells


def build_mapping(headers: list[str]) -> dict[str, int]:
    normalized_headers = {normalize_text(header): index for index, header in enumerate(headers)}
    mapping: dict[str, int] = {}
    for canonical, aliases in ALIASES.items():
        for alias in [canonical, *aliases]:
            key = normalize_text(alias)
            if key in normalized_headers:
                mapping[canonical] = normalized_headers[key]
                break
        if canonical in mapping:
            continue
        for index, header in enumerate(headers):
            normalized = normalize_text(header)
            if any(normalize_text(alias) in normalized or normalized in normalize_text(alias) for alias in aliases):
                mapping[canonical] = index
                break
    missing = [field for field in REQUIRED_FIELDS if field not in mapping]
    if missing:
        raise ValueError("字段不足，缺少：" + "、".join(missing))
    return mapping


def get_cell(cells: list[str], mapping: dict[str, int], field: str) -> str:
    index = mapping.get(field)
    if index is None or index >= len(cells):
        return ""
    return cells[index].strip()


def parse_text(text: str, default_trade_date: str) -> tuple[list[dict[str, str]], dict[str, object]]:
    lines = [line for line in text.splitlines() if line.strip()]
    header_index, headers = find_header(lines)
    mapping = build_mapping(headers)
    rows: list[dict[str, str]] = []

    for source_line, line in enumerate(lines[header_index + 1 :], start=header_index + 2):
        cells = split_line(line)
        if len(cells) < len(headers):
            cells = cells + [""] * (len(headers) - len(cells))

        stock_code = get_cell(cells, mapping, "stock_code")
        side = normalize_side(get_cell(cells, mapping, "side"))
        quantity = clean_number(get_cell(cells, mapping, "quantity"))
        price = clean_number(get_cell(cells, mapping, "price"))

        if not re.fullmatch(r"\d{6}", stock_code or ""):
            continue
        if side not in {"BUY", "SELL"}:
            continue
        if not quantity or not price:
            continue

        amount = clean_number(get_cell(cells, mapping, "amount"))
        if not amount:
            try:
                amount = f"{float(quantity) * float(price):.3f}"
            except ValueError:
                amount = ""

        rows.append(
            {
                "trade_date": get_cell(cells, mapping, "trade_date") or default_trade_date,
                "trade_time": get_cell(cells, mapping, "trade_time"),
                "stock_code": stock_code,
                "stock_name": get_cell(cells, mapping, "stock_name"),
                "side": side,
                "quantity": quantity,
                "price": price,
                "amount": amount,
                "net_amount": clean_number(get_cell(cells, mapping, "net_amount")),
                "commission": clean_number(get_cell(cells, mapping, "commission")),
                "stamp_tax": clean_number(get_cell(cells, mapping, "stamp_tax")),
                "transfer_fee": clean_number(get_cell(cells, mapping, "transfer_fee")),
                "other_fee": clean_number(get_cell(cells, mapping, "other_fee")),
                "_source_line": str(source_line),
            }
        )

    if not rows:
        raise ValueError("没有解析到有效成交记录。")
    report = {
        "status": "ok",
        "row_count": len(rows),
        "source_headers": headers,
        "mapped_fields": mapping,
        "output_fields": OUTPUT_FIELDS,
        "privacy_note": "原始粘贴文本只能保存在 private/ 或 reports/ 下，不能提交 Git。",
    }
    return rows, report


def write_csv(rows: list[dict[str, str]], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in OUTPUT_FIELDS})


def main() -> int:
    parser = argparse.ArgumentParser(description="从复制粘贴的券商成交表格文本中提取标准交易 CSV。")
    parser.add_argument("input_text_file", type=Path)
    parser.add_argument("-o", "--output", type=Path, default=Path("reports/pasted_trades_extracted.csv"))
    parser.add_argument("--trade-date", default=date.today().isoformat())
    parser.add_argument("--report", type=Path, default=Path("reports/pasted_trades_parse_report.json"))
    args = parser.parse_args()

    text = args.input_text_file.read_text(encoding="utf-8")
    rows, report = parse_text(text, args.trade_date)
    write_csv(rows, args.output)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {args.output} ({len(rows)} rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
