#!/usr/bin/env python3
"""Normalize broker CSV/XLSX statements into canonical trade facts."""

from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path


FIELDS = [
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
    "trade_date": ["发生日期", "成交日期", "交收日期", "交易日期", "日期"],
    "trade_time": ["发生时间", "成交时间", "委托时间", "时间"],
    "stock_code": ["证券代码", "股票代码", "代码"],
    "stock_name": ["证券名称", "股票名称", "名称"],
    "side": ["交易类别", "委托方向", "买卖方向", "买卖类别", "交易方向", "操作"],
    "quantity": ["成交数量", "成交股数", "数量", "股数"],
    "price": ["成交价格", "成交均价", "成交价", "价格"],
    "amount": ["成交金额", "成交额"],
    "net_amount": ["发生金额", "总发生金额", "资金发生额"],
    "commission": ["佣金", "手续费", "交易佣金"],
    "stamp_tax": ["印花税"],
    "transfer_fee": ["过户费"],
    "other_fee": ["交易规费", "规费", "其他费用", "经手费", "证管费"],
}

REQUIRED = ["trade_date", "stock_code", "stock_name", "side", "quantity", "price"]
FORBIDDEN_HEADERS = ["姓名", "身份证", "手机号", "资金账号", "资金帐号", "客户号", "股东账号", "股东帐号", "银行卡", "营业部", "地址", "资金余额", "可用余额"]


def normalize(value: object) -> str:
    return re.sub(r"[\s_\-:：/()（）]+", "", str(value or "").strip().lower())


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


def normalize_side(value: object) -> str:
    text = str(value or "").strip()
    upper = text.upper()
    if upper in {"BUY", "B"} or "证券买入" in text or "买入" in text:
        return "BUY"
    if upper in {"SELL", "S"} or "证券卖出" in text or "卖出" in text:
        return "SELL"
    return upper


def read_csv_rows(path: Path) -> list[list[str]]:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "gbk"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ValueError("无法识别 CSV 编码，请另存为 UTF-8 或 GBK。")
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",\t;")
    except csv.Error:
        dialect = csv.excel_tab if "\t" in sample else csv.excel
    return [[str(cell or "").strip() for cell in row] for row in csv.reader(text.splitlines(), dialect)]


def read_xlsx_rows(path: Path) -> list[list[str]]:
    try:
        import openpyxl  # type: ignore
    except ImportError as exc:
        raise RuntimeError("当前 Python 环境未安装 openpyxl。请先把 XLSX 导出为 CSV，或安装 openpyxl 后重试。") from exc
    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    sheet = workbook.active
    rows: list[list[str]] = []
    for row in sheet.iter_rows(values_only=True):
        rows.append([str(cell or "").strip() for cell in row])
    workbook.close()
    return rows


def read_table(path: Path) -> list[list[str]]:
    suffix = path.suffix.lower()
    if suffix in {".xlsx", ".xlsm"}:
        return read_xlsx_rows(path)
    if suffix == ".xls":
        raise RuntimeError("暂不直接读取 .xls。请先另存为 CSV 或 XLSX。")
    return read_csv_rows(path)


def find_header(rows: list[list[str]]) -> tuple[int, list[str]]:
    alias_values = {normalize(alias) for aliases in ALIASES.values() for alias in aliases}
    best_index = -1
    best_score = -1
    best_header: list[str] = []
    for index, row in enumerate(rows[:30]):
        cells = [cell for cell in row if cell]
        if len(cells) < 4:
            continue
        score = sum(1 for cell in cells if normalize(cell) in alias_values or any(alias in normalize(cell) for alias in alias_values))
        if score > best_score:
            best_index = index
            best_score = score
            best_header = row
    if best_index < 0 or best_score < 3:
        raise ValueError("无法识别表头。需要至少包含日期、证券代码、证券名称、买卖方向、数量、价格等字段。")
    return best_index, best_header


def check_forbidden_headers(headers: list[str]) -> list[str]:
    normalized_headers = [normalize(header) for header in headers]
    return [keyword for keyword in FORBIDDEN_HEADERS if any(normalize(keyword) in header for header in normalized_headers)]


def build_mapping(headers: list[str]) -> dict[str, int]:
    mapping: dict[str, int] = {}
    for field, aliases in ALIASES.items():
        candidates = [field, *aliases]
        for index, header in enumerate(headers):
            normalized_header = normalize(header)
            if any(normalize(alias) == normalized_header or normalize(alias) in normalized_header for alias in candidates):
                mapping[field] = index
                break
    missing = [field for field in REQUIRED if field not in mapping]
    if missing:
        raise ValueError("字段不足，缺少：" + "、".join(missing))
    return mapping


def cell(row: list[str], mapping: dict[str, int], field: str) -> str:
    index = mapping.get(field)
    if index is None or index >= len(row):
        return ""
    return row[index].strip()


def normalize_rows(rows: list[list[str]], default_trade_date: str = "") -> tuple[list[dict[str, str]], dict[str, object]]:
    header_index, headers = find_header(rows)
    forbidden = check_forbidden_headers(headers)
    if forbidden:
        raise ValueError("输入表头包含禁止字段：" + "、".join(forbidden))
    mapping = build_mapping(headers)
    output_rows: list[dict[str, str]] = []

    for row in rows[header_index + 1 :]:
        stock_code = cell(row, mapping, "stock_code")
        side = normalize_side(cell(row, mapping, "side"))
        quantity = clean_number(cell(row, mapping, "quantity"))
        price = clean_number(cell(row, mapping, "price"))
        if not re.fullmatch(r"\d{6}", stock_code or ""):
            continue
        if side not in {"BUY", "SELL"}:
            continue
        if not quantity or not price:
            continue
        amount = clean_number(cell(row, mapping, "amount"))
        if not amount:
            try:
                amount = f"{float(quantity) * float(price):.3f}"
            except ValueError:
                amount = ""
        output_rows.append(
            {
                "trade_date": cell(row, mapping, "trade_date") or default_trade_date,
                "trade_time": cell(row, mapping, "trade_time"),
                "stock_code": stock_code,
                "stock_name": cell(row, mapping, "stock_name"),
                "side": side,
                "quantity": quantity,
                "price": price,
                "amount": amount,
                "net_amount": clean_number(cell(row, mapping, "net_amount")),
                "commission": clean_number(cell(row, mapping, "commission")),
                "stamp_tax": clean_number(cell(row, mapping, "stamp_tax")),
                "transfer_fee": clean_number(cell(row, mapping, "transfer_fee")),
                "other_fee": clean_number(cell(row, mapping, "other_fee")),
            }
        )
    if not output_rows:
        raise ValueError("没有识别到有效证券买卖成交。")
    return output_rows, {"status": "ok", "row_count": len(output_rows), "source_headers": headers, "mapped_fields": mapping, "output_fields": FIELDS}


def write_output(rows: list[dict[str, str]], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows({field: row.get(field, "") for field in FIELDS} for row in rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="把券商 CSV/XLSX 交割单标准化为交易事实 CSV。")
    parser.add_argument("statement", type=Path)
    parser.add_argument("-o", "--output", type=Path, default=Path("reports/normalized_trades.csv"))
    parser.add_argument("--report", type=Path, default=Path("reports/normalize_statement_report.json"))
    parser.add_argument("--default-trade-date", default="")
    args = parser.parse_args()

    rows = read_table(args.statement)
    normalized_rows, report = normalize_rows(rows, default_trade_date=args.default_trade_date)
    write_output(normalized_rows, args.output)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {args.output} ({len(normalized_rows)} rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
