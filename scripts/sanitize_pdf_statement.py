#!/usr/bin/env python3
"""Extract sanitized trade facts from a local text-based PDF statement."""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path
from typing import Any


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

CASH_ADJUSTMENT_FIELDS = [
    "trade_date",
    "trade_time",
    "stock_code",
    "stock_name",
    "category",
    "quantity",
    "price",
    "net_amount",
]

FIELD_ALIASES = {
    "trade_date": ["发生日期", "成交日期", "交易日期"],
    "trade_time": ["发生时间", "成交时间", "委托时间"],
    "side": ["买卖类别", "买卖方向", "交易方向", "交易类别", "业务名称"],
    "stock_code": ["证券代码", "股票代码", "代码"],
    "stock_name": ["证券名称", "股票名称", "名称"],
    "quantity": ["成交数量", "成交股数", "数量"],
    "price": ["成交价格", "成交均价", "价格"],
    "amount": ["成交金额", "成交额"],
    "net_amount": ["总发生金额", "发生金额", "资金发生额", "清算金额"],
    "commission": ["手续费", "佣金"],
    "stamp_tax": ["印花税"],
    "transfer_fee": ["过户费"],
    "other_fee": ["交易规费", "规费", "其他费用", "经手费", "证管费"],
    "cash_balance": ["资金余额", "余额", "可用余额"],
}

REQUIRED_FIELDS = ["trade_date", "side", "stock_code", "stock_name", "quantity", "price"]
SECURITY_CASH_KEYWORDS = ("红利", "股息", "派息", "扣税")


def normalize_text(value: object) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value).replace("\n", " ")).strip()


def normalize_header(value: object) -> str:
    return re.sub(r"[\s_\-:：/()（）]+", "", normalize_text(value).lower())


def normalize_side(value: object) -> str:
    text = normalize_text(value)
    upper = text.upper()
    if upper in {"BUY", "B"} or "证券买入" in text or "买入" in text:
        return "BUY"
    if upper in {"SELL", "S"} or "证券卖出" in text or "卖出" in text:
        return "SELL"
    return upper


def clean_number(value: object) -> str:
    text = normalize_text(value).replace(",", "").replace("￥", "").replace("¥", "")
    if text in {"", "--", "-", "无", "None"}:
        return ""
    negative = text.startswith("(") and text.endswith(")")
    text = text.strip("()")
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return ""
    number = match.group(0)
    if negative and not number.startswith("-"):
        number = "-" + number
    return number


def build_mapping(header_row: list[str]) -> dict[str, int]:
    mapping: dict[str, int] = {}
    normalized_cells = [normalize_header(cell) for cell in header_row]
    for canonical, aliases in FIELD_ALIASES.items():
        for index, cell in enumerate(normalized_cells):
            if not cell:
                continue
            if any(normalize_header(alias) == cell or normalize_header(alias) in cell for alias in aliases):
                mapping[canonical] = index
                break
    return mapping


def is_header_like(row: list[str]) -> bool:
    mapping = build_mapping(row)
    return len(set(mapping) & set(REQUIRED_FIELDS)) >= 4


def cell_at(row: list[str], index: int | None) -> str:
    if index is None or index >= len(row):
        return ""
    return normalize_text(row[index])


def gross_amount(quantity: str, price: str, explicit_amount: str) -> str:
    if explicit_amount:
        return explicit_amount
    try:
        return f"{float(quantity) * float(price):.3f}"
    except ValueError:
        return ""


def row_to_record(row: list[str], mapping: dict[str, int]) -> dict[str, str] | None:
    side = normalize_side(cell_at(row, mapping.get("side")))
    stock_code = cell_at(row, mapping.get("stock_code"))
    stock_name = cell_at(row, mapping.get("stock_name"))
    quantity = clean_number(cell_at(row, mapping.get("quantity")))
    price = clean_number(cell_at(row, mapping.get("price")))

    if side not in {"BUY", "SELL"}:
        return None
    if not re.fullmatch(r"\d{6}", stock_code or ""):
        return None
    if not stock_name or not quantity or not price:
        return None

    amount = gross_amount(quantity, price, clean_number(cell_at(row, mapping.get("amount"))))
    return {
        "trade_date": cell_at(row, mapping.get("trade_date")),
        "trade_time": cell_at(row, mapping.get("trade_time")),
        "stock_code": stock_code,
        "stock_name": stock_name,
        "side": side,
        "quantity": quantity,
        "price": price,
        "amount": amount,
        "net_amount": clean_number(cell_at(row, mapping.get("net_amount"))),
        "commission": clean_number(cell_at(row, mapping.get("commission"))),
        "stamp_tax": clean_number(cell_at(row, mapping.get("stamp_tax"))),
        "transfer_fee": clean_number(cell_at(row, mapping.get("transfer_fee"))),
        "other_fee": clean_number(cell_at(row, mapping.get("other_fee"))),
    }


def row_to_cash_adjustment(row: list[str], mapping: dict[str, int]) -> dict[str, str] | None:
    category = cell_at(row, mapping.get("side"))
    stock_code = cell_at(row, mapping.get("stock_code"))
    stock_name = cell_at(row, mapping.get("stock_name"))
    net_amount = clean_number(cell_at(row, mapping.get("net_amount")))

    if not any(keyword in category for keyword in SECURITY_CASH_KEYWORDS):
        return None
    if not re.fullmatch(r"\d{6}", stock_code or ""):
        return None
    if not stock_name or not net_amount:
        return None

    return {
        "trade_date": cell_at(row, mapping.get("trade_date")),
        "trade_time": cell_at(row, mapping.get("trade_time")),
        "stock_code": stock_code,
        "stock_name": stock_name,
        "category": category,
        "quantity": clean_number(cell_at(row, mapping.get("quantity"))),
        "price": clean_number(cell_at(row, mapping.get("price"))),
        "net_amount": net_amount,
    }


def extract_rows_from_pdf(pdf_path: Path) -> tuple[list[dict[str, str]], list[dict[str, str]], dict[str, Any]]:
    try:
        import pdfplumber  # type: ignore
    except ImportError as exc:
        raise RuntimeError("缺少 pdfplumber。请在本地安装 pdfplumber 后重试；本脚本不会联网。") from exc

    rows: list[dict[str, str]] = []
    cash_adjustments: list[dict[str, str]] = []
    mappings_seen: list[dict[str, Any]] = []
    table_count = 0
    pages_with_tables = 0

    with pdfplumber.open(pdf_path) as pdf:
        page_count = len(pdf.pages)
        for page_number, page in enumerate(pdf.pages, start=1):
            tables = page.extract_tables() or []
            if tables:
                pages_with_tables += 1
            table_count += len(tables)
            for table_index, table in enumerate(tables, start=1):
                current_mapping: dict[str, int] | None = None
                for raw_row in table:
                    row = [normalize_text(cell) for cell in (raw_row or [])]
                    if not any(row):
                        continue
                    if is_header_like(row):
                        current_mapping = build_mapping(row)
                        mappings_seen.append(
                            {
                                "page": page_number,
                                "table": table_index,
                                "mapped_fields": sorted(field for field in current_mapping if field != "cash_balance"),
                                "cash_balance_detected": "cash_balance" in current_mapping,
                            }
                        )
                        continue
                    if not current_mapping:
                        continue
                    record = row_to_record(row, current_mapping)
                    if record:
                        rows.append(record)
                        continue
                    adjustment = row_to_cash_adjustment(row, current_mapping)
                    if adjustment:
                        cash_adjustments.append(adjustment)

    return rows, cash_adjustments, {
        "page_count": page_count,
        "pages_with_tables": pages_with_tables,
        "table_count": table_count,
        "field_mappings_seen": mappings_seen,
    }


def luhn_valid(number: str) -> bool:
    digits = [int(ch) for ch in number if ch.isdigit()]
    checksum = 0
    parity = len(digits) % 2
    for index, digit in enumerate(digits):
        if index % 2 == parity:
            digit *= 2
            if digit > 9:
                digit -= 9
        checksum += digit
    return checksum % 10 == 0


def scan_sensitive_output(csv_path: Path) -> list[dict[str, Any]]:
    id_pattern = re.compile(r"(?<!\d)[1-9]\d{5}(?:18|19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx](?!\d)")
    phone_pattern = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
    long_number_pattern = re.compile(r"(?<!\d)\d{8,24}(?!\d)")
    safe_numeric_fields = {"trade_date", "trade_time", "stock_code", "quantity", "price", "amount", "net_amount", "commission", "stamp_tax", "transfer_fee", "other_fee"}
    findings: list[dict[str, Any]] = []
    with csv_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row_number, row in enumerate(reader, start=2):
            for field, value in row.items():
                text = value or ""
                if id_pattern.search(text):
                    findings.append({"risk_type": "id_card", "field": field, "row_number": row_number})
                if phone_pattern.search(text):
                    findings.append({"risk_type": "phone_number", "field": field, "row_number": row_number})
                if field not in safe_numeric_fields:
                    for match in long_number_pattern.findall(text):
                        if 16 <= len(match) <= 19 or (len(match) >= 13 and luhn_valid(match)):
                            findings.append({"risk_type": "bank_card", "field": field, "row_number": row_number})
                        elif len(match) >= 8:
                            findings.append({"risk_type": "account_like_long_number", "field": field, "row_number": row_number})
    return findings


def write_csv(rows: list[dict[str, str]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        writer.writerows({field: row.get(field, "") for field in OUTPUT_FIELDS} for row in rows)


def write_cash_adjustments_csv(rows: list[dict[str, str]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CASH_ADJUSTMENT_FIELDS)
        writer.writeheader()
        writer.writerows({field: row.get(field, "") for field in CASH_ADJUSTMENT_FIELDS} for row in rows)


def write_report(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="从本地文字型 PDF 交割单提取脱敏标准交易 CSV。")
    parser.add_argument("pdf_file", type=Path)
    parser.add_argument("-o", "--output", type=Path, default=Path("reports/sanitized_pdf_trades.csv"))
    parser.add_argument("--cash-adjustments-output", type=Path)
    parser.add_argument("--report", type=Path, default=Path("reports/sanitize_pdf_report.json"))
    args = parser.parse_args()

    if not args.pdf_file.exists():
        raise SystemExit(f"PDF 文件不存在: {args.pdf_file}")

    report: dict[str, Any] = {
        "input_file_recorded": False,
        "output_file": str(args.output),
        "status": "started",
        "warnings": [],
        "privacy": [
            "未在终端打印 PDF 原文。",
            "只输出标准交易字段和证券相关现金调整字段。",
            "资金余额字段默认删除，不进入输出 CSV。",
        ],
    }

    try:
        rows, cash_adjustments, meta = extract_rows_from_pdf(args.pdf_file)
        report.update(meta)
    except Exception as exc:  # noqa: BLE001
        report["status"] = "error"
        report["error"] = exc.__class__.__name__
        report["message"] = str(exc)
        write_report(args.report, report)
        print(f"PDF 脱敏失败，详情见 {args.report}", file=sys.stderr)
        return 1

    if not rows:
        report["status"] = "needs_ocr"
        report["warnings"].append("未从 PDF 提取到表格。该文件可能是扫描版 PDF，需要本地 OCR；本阶段不要联网。")
        write_report(args.report, report)
        print(f"未提取到表格，可能是扫描版 PDF，需要本地 OCR。详情见 {args.report}", file=sys.stderr)
        return 2

    write_csv(rows, args.output)
    if args.cash_adjustments_output:
        write_cash_adjustments_csv(cash_adjustments, args.cash_adjustments_output)
    findings = scan_sensitive_output(args.output)
    if args.cash_adjustments_output:
        findings.extend(scan_sensitive_output(args.cash_adjustments_output))
    report["rows_extracted"] = len(rows)
    report["cash_adjustment_rows_extracted"] = len(cash_adjustments)
    if args.cash_adjustments_output:
        report["cash_adjustments_output_file"] = str(args.cash_adjustments_output)
    report["sensitive_scan_findings"] = findings
    if findings:
        report["status"] = "blocked_sensitive_data"
        report["warnings"].append("脱敏 CSV 二次扫描发现疑似敏感信息，已停止。")
        write_report(args.report, report)
        print(f"脱敏输出发现疑似敏感信息，已停止。详情见 {args.report}", file=sys.stderr)
        return 3

    report["status"] = "ok"
    write_report(args.report, report)
    print(f"wrote {args.output}")
    print(f"wrote {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
