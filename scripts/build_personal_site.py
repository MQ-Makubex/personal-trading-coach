#!/usr/bin/env python3
"""Build the private multi-page personal trading training site."""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import re
import sqlite3
from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import date, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from ledger_analytics import (
    broker_like_cycles,
    display_names_by_code,
    fifo_analytics,
    load_cash_adjustments,
    load_trades,
    number,
)
from personal_site_metrics import summarize_cycles
from personal_site_state import load_discipline_feed, load_trading_modes
from render_markdown import render_markdown


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SQLITE = ROOT / "state" / "account_ledger.sqlite"
DEFAULT_REPORTS = ROOT / "reports"
DEFAULT_STATE = ROOT / "state"
DEFAULT_OUTPUT = DEFAULT_REPORTS / "personal_site"
ASSET_SOURCE = ROOT / "templates" / "personal_site"


REPORT_LABELS = {
    "coach_note": "教练手记",
    "research_pool": "研究股票池",
    "pool_review": "股票池复盘",
    "trade_plan": "交易预案",
    "intraday_guard": "盘中纪律",
    "xueqiu_post": "雪球复盘",
    "market_snapshot": "市场快照",
}

TIMELINE_CATEGORIES = tuple(REPORT_LABELS)

STATE_SECTIONS = (
    ("coach_memory", "教练记忆", "coach_memory.md"),
    ("coach_lenses", "分析镜头", "coach_lenses.md"),
    ("personal_trading_modes", "个人交易模式", "personal_trading_modes.md"),
    ("research_pool_protocol", "股票池协议", "research_pool_protocol.md"),
    ("decision_events", "决策事件", "decision_events.md"),
    ("position_storylines", "持仓故事线", "position_storylines.md"),
)

NAV_ITEMS = (
    ("home", "今日", "index.html"),
    ("timeline", "训练时间线", "timeline.html"),
    ("stories", "股票故事", "stories.html"),
    ("ledger", "交易底账", "ledger.html"),
    ("rules", "纪律规则", "rules.html"),
)

MARKET_CODE_PATTERN = re.compile(
    r"(?<!\d)((?:000|001|002|003|159|300|301|500|501|502|506|510|511|512|513|515|516|517|518|520|560|561|562|563|588|600|601|603|605|688)\d{3})(?!\d)"
)

POOL_COLUMNS = {
    "stock_code": {"代码", "证券代码", "股票代码"},
    "stock_name": {"名称", "证券名称", "股票名称"},
    "theme": {"题材", "题材篮子", "产业方向", "方向"},
    "buy_point": {"买点", "买点类型", "触发", "触发条件"},
}


def esc(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def money(value: Any) -> str:
    if value is None or value == "":
        return "待核验"
    amount = number(value)
    sign = "-" if amount < 0 else ""
    return f"{sign}¥{abs(amount):,.2f}"


def qty(value: Any) -> str:
    amount = number(value)
    if amount == int(amount):
        return f"{int(amount):,}"
    return f"{amount:,.2f}"


def pct(value: Any) -> str:
    if value is None or value == "":
        return "—"
    return f"{number(value):.2f}%"


def first_sentence(value: Any, limit: int = 120) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if not text:
        return ""
    match = re.search(r"[。！？!?]", text)
    sentence = text[: match.end()] if match else text
    if len(sentence) <= limit:
        return sentence
    return sentence[: max(1, limit - 1)].rstrip() + "…"


def stock_reference_label(codes: list[str]) -> str:
    if not codes:
        return "全市场"
    if len(codes) <= 3:
        return " ".join(codes)
    return f"{' '.join(codes[:3])} 等 {len(codes)} 支"


def connect(sqlite_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(sqlite_path)
    conn.row_factory = sqlite3.Row
    return conn


def fetch_one(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any]:
    row = conn.execute(sql, params).fetchone()
    return dict(row) if row else {}


def fetch_all(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    return [dict(row) for row in conn.execute(sql, params).fetchall()]


def classify_report(path: Path) -> str:
    name = path.name.lower()
    stem = path.stem.lower()
    if "research_pool_review" in name or stem.startswith("review_"):
        return "pool_review"
    if "coach_note" in name:
        return "coach_note"
    if "research_pool" in name:
        return "research_pool"
    if "trade_plan" in name:
        return "trade_plan"
    if "intraday_guard" in name:
        return "intraday_guard"
    if "xueqiu" in name:
        return "xueqiu_post"
    if "market_snapshot" in name:
        return "market_snapshot"
    return "other"


def infer_date(path: Path) -> str:
    text = "/".join(path.parts)
    compact = re.search(r"20\d{6}", text)
    if compact:
        value = compact.group(0)
        return f"{value[:4]}-{value[4:6]}-{value[6:]}"
    expanded = re.search(r"20\d{2}-\d{2}-\d{2}", text)
    return expanded.group(0) if expanded else ""


def valid_iso_date(value: Any) -> str:
    text = str(value or "")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return ""
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
        return ""


def date_from_match(match: re.Match[str]) -> str:
    year, month, day = (int(value) for value in match.groups())
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return ""


def infer_document_target_date(title: str, markdown_text: str, fallback_date: str) -> str:
    normalized = markdown_text[:4000]
    labeled = re.search(
        r"(?:目标交易日|交易日期|适用日期)\s*[：:]?\s*(20\d{2})[-年/](\d{1,2})[-月/](\d{1,2})日?",
        normalized,
    )
    if labeled:
        result = date_from_match(labeled)
        if result:
            return result
    for source in (title, normalized[:800]):
        expanded = re.search(r"(20\d{2})[-年/](\d{1,2})[-月/](\d{1,2})日?", source)
        if expanded:
            result = date_from_match(expanded)
            if result:
                return result
        compact = re.search(r"(?<!\d)(20\d{6})(?!\d)", source)
        if compact:
            result = valid_iso_date(f"{compact.group(1)[:4]}-{compact.group(1)[4:6]}-{compact.group(1)[6:]}")
            if result:
                return result
    return valid_iso_date(fallback_date)


def resolve_workbench_target_date(documents: list[dict[str, Any]], as_of_date: date) -> str:
    explicit: list[date] = []
    for item in documents:
        if item.get("category") not in {"trade_plan", "research_pool"}:
            continue
        normalized = valid_iso_date(item.get("target_date"))
        if normalized:
            explicit.append(date.fromisoformat(normalized))
    return max([as_of_date, *explicit]).isoformat()


def select_daily_document(
    documents: list[dict[str, Any]], category: str, target_date: str
) -> dict[str, Any]:
    requested_target = valid_iso_date(target_date)
    candidates: list[tuple[date, dict[str, Any]]] = []
    for item in documents:
        if item.get("category") != category:
            continue
        normalized = valid_iso_date(item.get("target_date"))
        if normalized:
            candidates.append((date.fromisoformat(normalized), item))
    exact = next((item for parsed, item in candidates if parsed.isoformat() == requested_target), None)
    selected = exact or max(
        candidates,
        key=lambda candidate: (
            candidate[0],
            str(candidate[1].get("date") or ""),
            str(candidate[1].get("mtime") or ""),
        ),
        default=(None, None),
    )[1]
    selected_target = valid_iso_date((selected or {}).get("target_date"))
    return {
        "document": selected,
        "target_date": selected_target,
        "stale": bool(selected and selected_target != requested_target),
    }


def parse_pool_row(raw_line: str) -> list[str] | None:
    if raw_line.count("|") < 2:
        return None
    row = next(csv.reader([raw_line.strip().strip("|")], delimiter="|"))
    return [cell.strip() for cell in row]


def pool_column_indices(row: list[str]) -> dict[str, int] | None:
    columns: dict[str, int | None] = {}
    for field, aliases in POOL_COLUMNS.items():
        columns[field] = next((index for index, cell in enumerate(row) if cell in aliases), None)
    if columns["stock_code"] is None or columns["stock_name"] is None:
        return None
    return {field: index for field, index in columns.items() if index is not None}


def is_table_separator(row: list[str]) -> bool:
    return bool(row) and all(re.fullmatch(r":?-{3,}:?", cell) for cell in row)


def extract_research_pool_candidates(markdown_text: str) -> list[dict[str, str]]:
    lines = markdown_text.splitlines()
    for header_index, raw_header in enumerate(lines):
        header = parse_pool_row(raw_header)
        columns = pool_column_indices(header or [])
        if columns is None:
            continue
        output: list[dict[str, str]] = []
        required_width = max(columns.values())
        row_index = header_index + 1
        while row_index < len(lines):
            row = parse_pool_row(lines[row_index])
            if row is None:
                break
            if pool_column_indices(row) is not None:
                break
            if is_table_separator(row):
                row_index += 1
                continue
            if len(row) <= required_width:
                row_index += 1
                continue
            code = row[columns["stock_code"]]
            name = row[columns["stock_name"]]
            if not re.fullmatch(r"\d{6}", code) or not name:
                row_index += 1
                continue
            output.append(
                {
                    "stock_code": code,
                    "stock_name": name,
                    "theme": row[columns["theme"]] if columns["theme"] is not None else "待核验",
                    "buy_point": row[columns["buy_point"]] if columns["buy_point"] is not None else "待核验",
                }
            )
            row_index += 1
        return output
    return []


def title_from_markdown(path: Path) -> str:
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return path.stem.replace("_", " ")


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        text = data.strip()
        if text:
            self.parts.append(text)


def markdown_plain_text(markdown_text: str) -> str:
    parser = _TextExtractor()
    parser.feed(render_markdown(markdown_text))
    return re.sub(r"\s+", " ", " ".join(parser.parts)).strip()


def render_embedded_markdown(markdown_text: str) -> str:
    lines = markdown_text.splitlines()
    for index, line in enumerate(lines):
        if not line.strip():
            continue
        if line.startswith("# "):
            del lines[index]
        break
    return render_markdown("\n".join(lines))


def document_slug(path: Path) -> str:
    stem = re.sub(r"[^a-z0-9]+", "-", path.stem.lower()).strip("-") or "document"
    digest = hashlib.sha1(str(path).encode("utf-8")).hexdigest()[:8]
    return f"{stem}-{digest}.html"


def collect_timeline_documents(reports_dir: Path, output_dir: Path) -> list[dict[str, Any]]:
    documents: list[dict[str, Any]] = []
    skip_root = output_dir.resolve()
    for path in sorted(reports_dir.rglob("*.md")):
        try:
            path.resolve().relative_to(skip_root)
            continue
        except ValueError:
            pass
        category = classify_report(path)
        if category not in TIMELINE_CATEGORIES:
            continue
        markdown_text = path.read_text(encoding="utf-8", errors="ignore")
        title = title_from_markdown(path)
        plain = markdown_plain_text(markdown_text)
        if plain.startswith(title):
            plain = plain[len(title) :].strip()
        rel = path.relative_to(reports_dir)
        stat = path.stat()
        codes = sorted(set(MARKET_CODE_PATTERN.findall(markdown_text)))
        artifact_date = infer_date(rel)
        documents.append(
            {
                "title": title,
                "category": category,
                "category_label": REPORT_LABELS[category],
                "date": artifact_date,
                "target_date": infer_document_target_date(title, markdown_text, artifact_date),
                "source_path": str(rel).replace("\\", "/"),
                "document_path": f"documents/{document_slug(rel)}",
                "mtime": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
                "stock_codes": codes,
                "summary": plain[:220] or "暂无摘要。",
                "search_text": f"{title} {plain}"[:4000],
                "markdown": markdown_text,
            }
        )
    documents.sort(key=lambda item: (item["date"], item["mtime"], item["category"]), reverse=True)
    return documents


def extract_latest_quotes(reports_dir: Path, positions: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    wanted = {
        str(position.get("stock_code") or ""): (
            str(position.get("stock_name") or "")[2:]
            if str(position.get("stock_name") or "").startswith("XD")
            else str(position.get("stock_name") or "")
        )
        for position in positions
        if position.get("stock_code")
    }
    if not wanted:
        return {}
    snapshots = sorted(
        (path for path in reports_dir.rglob("*.md") if "market_snapshot" in path.name.lower()),
        key=lambda path: (infer_date(path.relative_to(reports_dir)), path.stat().st_mtime),
        reverse=True,
    )
    quotes: dict[str, dict[str, Any]] = {}
    quote_pattern = re.compile(
        r"^\s*-\s*(?:(?P<code>\d{6})\s+)?(?P<name>[^:：]+)[:：].*?收盘\s*(?P<price>\d+(?:\.\d+)?)"
    )
    for path in snapshots:
        if len(quotes) == len(wanted):
            break
        rel = path.relative_to(reports_dir)
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            match = quote_pattern.search(line)
            if not match:
                continue
            matched_code = str(match.group("code") or "")
            matched_name = str(match.group("name") or "").strip()
            if matched_name.startswith("XD"):
                matched_name = matched_name[2:]
            for code, name in wanted.items():
                if code in quotes:
                    continue
                if matched_code == code or (name and matched_name == name):
                    quotes[code] = {
                        "stock_code": code,
                        "stock_name": name,
                        "price": round(float(match.group("price")), 4),
                        "date": infer_date(rel),
                        "source": str(rel).replace("\\", "/"),
                    }
    return quotes


def mark_to_market_summary(
    realized_pnl: float,
    positions: list[dict[str, Any]],
    quotes: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    missing: list[str] = []
    market_value = 0.0
    unrealized = 0.0
    quote_dates: list[str] = []
    position_values: list[dict[str, Any]] = []
    for position in positions:
        code = str(position.get("stock_code") or "")
        quantity = number(position.get("open_quantity", position.get("broker_like_quantity")))
        cost_basis = number(
            position.get("broker_like_cost_basis_after_fees", position.get("open_cost_basis_after_fees"))
        )
        quote = quotes.get(code)
        if not quote:
            missing.append(code)
            position_values.append({"stock_code": code, "complete": False})
            continue
        value = quantity * number(quote.get("price"))
        floating = value - cost_basis
        market_value += value
        unrealized += floating
        if quote.get("date"):
            quote_dates.append(str(quote["date"]))
        position_values.append(
            {
                "stock_code": code,
                "complete": True,
                "quantity": round(quantity, 2),
                "cost_basis": round(cost_basis, 2),
                "price": round(number(quote.get("price")), 4),
                "market_value": round(value, 2),
                "unrealized_pnl": round(floating, 2),
                "quote_date": quote.get("date"),
                "quote_source": quote.get("source"),
            }
        )
    complete = not missing
    return {
        "complete": complete,
        "realized_pnl": round(number(realized_pnl), 2),
        "unrealized_pnl": round(unrealized, 2) if complete else None,
        "total_pnl": round(number(realized_pnl) + unrealized, 2) if complete else None,
        "market_value": round(market_value, 2) if complete else None,
        "quote_date": min(quote_dates) if complete and quote_dates else None,
        "quote_dates": sorted(set(quote_dates)),
        "missing_quote_codes": sorted(missing),
        "positions": position_values,
    }


def load_state_documents(state_dir: Path) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for key, label, filename in STATE_SECTIONS:
        path = state_dir / filename
        markdown_text = path.read_text(encoding="utf-8", errors="ignore") if path.exists() else f"# {label}\n\n暂无记录。\n"
        output.append(
            {
                "key": key,
                "label": label,
                "filename": filename,
                "markdown": markdown_text,
                "html": render_embedded_markdown(markdown_text),
                "summary": markdown_plain_text(markdown_text)[:180],
            }
        )
    return output


def _storyline_excerpt(markdown_text: str, code: str, name: str) -> str:
    heading = re.compile(rf"^###\s+{re.escape(code)}(?:\s+{re.escape(name)})?\s*$", re.MULTILINE)
    match = heading.search(markdown_text)
    if not match:
        return ""
    tail = markdown_text[match.start() :]
    next_heading = re.search(r"\n##{2,3}\s+", tail[1:])
    return tail[: next_heading.start() + 1].strip() if next_heading else tail.strip()


def build_stories(
    trades: list[dict[str, Any]],
    positions: list[dict[str, Any]],
    realized_rows: list[dict[str, Any]],
    quotes: dict[str, dict[str, Any]],
    documents: list[dict[str, Any]],
    storyline_markdown: str,
) -> list[dict[str, Any]]:
    trades_by_code: dict[str, list[dict[str, Any]]] = defaultdict(list)
    names: dict[str, str] = {}
    for trade in trades:
        code = str(trade.get("stock_code") or "")
        if not re.fullmatch(r"\d{6}", code):
            continue
        trades_by_code[code].append(trade)
        names[code] = str(trade.get("stock_name") or names.get(code, ""))
    position_map = {str(row.get("stock_code") or ""): row for row in positions}
    realized_map = {str(row.get("stock_code") or ""): row for row in realized_rows}
    codes = sorted(set(trades_by_code) | set(position_map) | set(realized_map))
    stories: list[dict[str, Any]] = []
    for code in codes:
        stock_trades = sorted(
            trades_by_code.get(code, []),
            key=lambda row: (str(row.get("trade_date") or ""), str(row.get("trade_time") or "")),
            reverse=True,
        )
        position = position_map.get(code)
        realized = realized_map.get(code, {})
        name = str((position or {}).get("stock_name") or realized.get("stock_name") or names.get(code, ""))
        realized_pnl = number(
            realized.get("broker_like_total_pnl_after_fees", realized.get("broker_like_realized_pnl_after_fees"))
        )
        quote = quotes.get(code)
        quantity = number((position or {}).get("open_quantity", (position or {}).get("broker_like_quantity")))
        cost_basis = number(
            (position or {}).get(
                "broker_like_cost_basis_after_fees", (position or {}).get("open_cost_basis_after_fees")
            )
        )
        unrealized_pnl = quantity * number((quote or {}).get("price")) - cost_basis if position and quote else None
        total_pnl = realized_pnl + unrealized_pnl if unrealized_pnl is not None else (realized_pnl if not position else None)
        linked_documents = [
            item
            for item in documents
            if code in item.get("stock_codes", []) or (name and name in str(item.get("search_text") or ""))
        ]
        first_date = min((str(row.get("trade_date") or "") for row in stock_trades), default="")
        latest_date = max((str(row.get("trade_date") or "") for row in stock_trades), default="")
        excerpt = _storyline_excerpt(storyline_markdown, code, name)
        stories.append(
            {
                "stock_code": code,
                "stock_name": name,
                "status": "current" if position else "closed",
                "status_label": "当前持仓" if position else "历史关闭",
                "open_quantity": round(quantity, 2),
                "cost_basis": round(cost_basis, 2) if position else None,
                "average_cost": round(cost_basis / quantity, 2) if position and quantity else None,
                "latest_price": quote.get("price") if quote else None,
                "quote_date": quote.get("date") if quote else None,
                "realized_pnl": round(realized_pnl, 2),
                "unrealized_pnl": round(unrealized_pnl, 2) if unrealized_pnl is not None else None,
                "total_pnl": round(total_pnl, 2) if total_pnl is not None else None,
                "first_trade_date": first_date,
                "latest_trade_date": latest_date,
                "trade_count": len(stock_trades),
                "trades": stock_trades,
                "documents": linked_documents[:30],
                "document_count": len(linked_documents),
                "storyline_markdown": excerpt,
                "storyline_review_status": "待人工审核" if excerpt and "待人工审核" in storyline_markdown else "账本事实",
                "page_path": f"stocks/{code}.html",
            }
        )
    stories.sort(key=lambda item: (item["latest_trade_date"], item["stock_code"]), reverse=True)
    stories.sort(key=lambda item: item["status"] != "current")
    return stories


def build_data(
    sqlite_path: Path,
    reports_dir: Path,
    output_dir: Path,
    state_dir: Path = DEFAULT_STATE,
    as_of_date: date | None = None,
) -> dict[str, Any]:
    conn = connect(sqlite_path)
    analytics = fifo_analytics(conn)
    summary = fetch_one(
        conn,
        """
        select
          count(*) as trade_rows,
          count(distinct case when stock_code glob '[0-9][0-9][0-9][0-9][0-9][0-9]' then stock_code end) as stock_count,
          round(sum(case when side = 'BUY' then amount else 0 end), 2) as buy_amount,
          round(sum(case when side = 'SELL' then amount else 0 end), 2) as sell_amount,
          round(sum(coalesce(commission,0) + coalesce(stamp_tax,0) + coalesce(transfer_fee,0) + coalesce(other_fee,0)), 2) as total_fees,
          min(trade_date) as first_trade_date,
          max(trade_date) as latest_trade_date
        from trades
        where side in ('BUY', 'SELL')
        """,
    )
    trades = fetch_all(
        conn,
        """
        select trade_date, trade_time, stock_code, stock_name, side, quantity, price, amount, net_amount,
          round(coalesce(commission,0) + coalesce(stamp_tax,0) + coalesce(transfer_fee,0) + coalesce(other_fee,0), 2) as fees
        from trades
        where side in ('BUY', 'SELL')
        order by trade_date desc, trade_time desc, rowid desc
        """,
    )
    activity = fetch_all(
        conn,
        """
        select trade_date, count(*) as trade_rows, count(distinct stock_code) as stocks,
          round(sum(abs(coalesce(amount,0))), 2) as gross_turnover,
          round(sum(coalesce(commission,0) + coalesce(stamp_tax,0) + coalesce(transfer_fee,0) + coalesce(other_fee,0)), 2) as fees
        from trades
        where side in ('BUY', 'SELL')
        group by trade_date
        order by trade_date desc
        limit 20
        """,
    )
    canonical_trades = load_trades(conn)
    cash_adjustments = load_cash_adjustments(conn)
    display_names = display_names_by_code(canonical_trades, cash_adjustments)
    cycles = broker_like_cycles(canonical_trades, display_names)
    ability = summarize_cycles(cycles)
    conn.close()

    documents = collect_timeline_documents(reports_dir, output_dir)
    trading_state = load_trading_modes(state_dir / "trading_modes.json", {row["cycle_id"]: row for row in cycles})
    discipline_feed = load_discipline_feed(state_dir / "discipline_feed.json")
    target_date = resolve_workbench_target_date(documents, as_of_date or datetime.now().date())
    selected_plan = select_daily_document(documents, "trade_plan", target_date)
    selected_pool = select_daily_document(documents, "research_pool", target_date)
    pool_document = selected_pool["document"]
    selected_pool["candidates"] = extract_research_pool_candidates(str((pool_document or {}).get("markdown") or ""))
    ledger_dataset = {
        "bounds": {
            "minimum": str(summary.get("first_trade_date") or ""),
            "maximum": str(summary.get("latest_trade_date") or ""),
        },
        "cycles": cycles,
        "trades": trades,
        "adjustments": [asdict(row) for row in cash_adjustments],
    }
    positions = analytics["open_positions"]
    realized_rows = analytics["broker_like_realized_by_stock"]
    all_time_realized = round(
        sum(
            number(row.get("broker_like_total_pnl_after_fees", row.get("broker_like_realized_pnl_after_fees")))
            for row in realized_rows
        ),
        2,
    )
    quotes = extract_latest_quotes(reports_dir, positions)
    mark_to_market = mark_to_market_summary(all_time_realized, positions, quotes)
    position_value_map = {row["stock_code"]: row for row in mark_to_market["positions"]}
    enriched_positions: list[dict[str, Any]] = []
    for position in positions:
        row = dict(position)
        row.update(position_value_map.get(str(position.get("stock_code") or ""), {}))
        enriched_positions.append(row)

    states = load_state_documents(state_dir)
    storyline_state = next((item for item in states if item["key"] == "position_storylines"), None)
    storyline_markdown = str((storyline_state or {}).get("markdown") or "")
    stories = build_stories(trades, enriched_positions, realized_rows, quotes, documents, storyline_markdown)
    latest_by_category = {
        category: next((item for item in documents if item["category"] == category), None)
        for category in TIMELINE_CATEGORIES
    }
    return {
        "summary": summary,
        "trades": trades,
        "activity": activity,
        "open_positions": enriched_positions,
        "realized_by_stock": realized_rows,
        "all_time_total_realized": all_time_realized,
        "mark_to_market": mark_to_market,
        "quotes": quotes,
        "documents": documents,
        "document_counts": dict(Counter(item["category"] for item in documents)),
        "latest_by_category": latest_by_category,
        "cycles": cycles,
        "ability": ability,
        "ledger_dataset": ledger_dataset,
        "trading_state": trading_state,
        "discipline_feed": discipline_feed,
        "workbench": {
            "target_date": target_date,
            "trade_plan": selected_plan,
            "research_pool": selected_pool,
        },
        "stories": stories,
        "states": states,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def value_class(value: Any) -> str:
    if value is None:
        return "pending"
    return "gain" if number(value) >= 0 else "loss"


def nav_html(active: str, prefix: str) -> str:
    links = []
    for key, label, href in NAV_ITEMS:
        current = ' aria-current="page"' if key == active else ""
        links.append(f'<a href="{prefix}{href}"{current}>{label}</a>')
    return "".join(links)


def page_shell(title: str, active: str, content: str, generated_at: str, depth: int = 0) -> str:
    prefix = "../" * depth
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="theme-color" content="#0c0d0f">
  <title>{esc(title)} · Makubex 交易训练</title>
  <link rel="stylesheet" href="{prefix}assets/site.css">
</head>
<body data-page="{esc(active)}">
  <a class="skip-link" href="#main">跳到主内容</a>
  <header class="command-bar">
    <a class="brand" href="{prefix}index.html"><span class="brand-mark">M</span><span><strong>交易训练</strong><small>风险指挥台</small></span></a>
    <nav class="primary-nav" aria-label="主导航">{nav_html(active, prefix)}</nav>
    <form class="global-search" action="{prefix}timeline.html" method="get" role="search">
      <label class="sr-only" for="globalSearch">全站搜索</label>
      <input id="globalSearch" name="q" type="search" placeholder="股票 / 日期 / 手记…" autocomplete="off">
      <button type="submit">检索</button>
    </form>
  </header>
  <main id="main" class="page-shell">
    {content}
  </main>
  <footer class="site-footer"><span>本地私密站 · 生成于 {esc(generated_at)}</span><span>不荐股，不预测涨跌。</span></footer>
  <script src="{prefix}assets/site.js" defer></script>
</body>
</html>"""


def metric_cell(label: str, value: Any, note: str, primary: bool = False, semantic: bool = True) -> str:
    value_text = value if isinstance(value, str) else money(value)
    cls = value_class(None if value_text == "待核验" else value) if semantic else ""
    value_classes = f"mono {cls}".strip()
    primary_cls = " metric-primary" if primary else ""
    return f"""<div class="metric-cell{primary_cls}"><span>{esc(label)}</span><strong class="{value_classes}">{esc(value_text)}</strong><small>{esc(note)}</small></div>"""


def metrics_html(data: dict[str, Any]) -> str:
    mark = data["mark_to_market"]
    total_note = (
        f"行情截至 {mark['quote_date']}"
        if mark["complete"] and mark.get("quote_date")
        else f"缺少行情：{', '.join(mark['missing_quote_codes']) or '待核验'}"
    )
    return f"""<section class="metrics-band" aria-label="账户关键指标">
      {metric_cell('总盈亏（含持仓）', mark['total_pnl'], total_note, True)}
      {metric_cell('已实现盈亏', mark['realized_pnl'], '含交易费用及证券现金调整')}
      {metric_cell('持仓浮动盈亏', mark['unrealized_pnl'], '最新行情市值减券商式持仓成本')}
      {metric_cell('总费用', data['summary'].get('total_fees'), '单独披露，不重复扣减', semantic=False)}
    </section>"""


def document_link(item: dict[str, Any], prefix: str = "") -> str:
    stocks = stock_reference_label(item.get("stock_codes", []))
    return f"""<a class="timeline-row" href="{prefix}{esc(item['document_path'])}">
      <span class="event-kind">{esc(item['category_label'])}</span>
      <span class="event-copy"><strong>{esc(item['title'])}</strong><small>{esc(item['summary'])}</small></span>
      <span class="event-meta"><time datetime="{esc(item['date'])}">{esc(item['date'] or item['mtime'])}</time><small>{esc(stocks)}</small></span>
    </a>"""


def render_home(data: dict[str, Any]) -> str:
    latest_date = str(data["summary"].get("latest_trade_date") or "—")
    latest_coach = data["latest_by_category"].get("coach_note")
    risk_copy = first_sentence(
        str(latest_coach.get("summary") or "")
        if latest_coach
        else "暂无教练手记。先完成当日事实核验，再形成判断。"
    )
    risk_href = str(latest_coach.get("document_path") or "timeline.html") if latest_coach else "timeline.html"
    recent_documents = data["documents"][:6]
    recent_rows = "".join(document_link(item) for item in recent_documents) or '<div class="empty-state">暂无训练记录。</div>'
    positions = []
    for row in data["open_positions"]:
        code = str(row.get("stock_code") or "")
        positions.append(
            f"""<a class="position-row" href="stocks/{esc(code)}.html">
              <span><strong>{esc(row.get('stock_name'))}</strong><small class="mono">{esc(code)}</small></span>
              <span><small>数量</small><strong class="mono">{qty(row.get('open_quantity'))}</strong></span>
              <span><small>券商成本</small><strong class="mono">{money(row.get('broker_like_average_cost_after_fees'))}</strong></span>
              <span><small>浮动盈亏</small><strong class="mono {value_class(row.get('unrealized_pnl'))}">{money(row.get('unrealized_pnl'))}</strong></span>
            </a>"""
        )
    positions_html = "".join(positions) or '<div class="empty-state">当前无持仓故事。</div>'
    dates = Counter(item["date"] for item in data["documents"] if item["date"])
    calendar = "".join(
        f'<a href="timeline.html?date={esc(date)}"><strong class="mono">{esc(date[8:])}</strong><span>{esc(date[5:7])} 月</span><small>{count} 项</small></a>'
        for date, count in sorted(dates.items(), reverse=True)[:5]
    )
    return f"""
      <header class="page-heading"><div><span class="page-context mono">TODAY / {esc(latest_date)}</span><h1>先暴露风险，再允许看机会</h1></div><a class="text-action" href="timeline.html">进入完整时间线</a></header>
      {metrics_html(data)}
      <section class="risk-band"><div><span class="risk-label">当前教练判断</span><strong>{esc(risk_copy)}</strong></div><a class="evidence-state" href="{esc(risk_href)}">查看来源：{esc(latest_coach['title'] if latest_coach else '暂无')}</a></section>
      <div class="work-grid">
        <section class="work-surface">
          <div class="section-heading"><div><h2>最近训练日</h2><p>手记、股票池、复盘与成交按交易日归档。</p></div><span class="count-label">{len(data['documents'])} 篇</span></div>
          <div class="calendar-strip" aria-label="最近训练日期">{calendar}</div>
          <div class="timeline-list compact">{recent_rows}</div>
        </section>
        <aside class="inspector-surface">
          <div class="section-heading"><div><h2>当前持仓</h2><p>先看风险锚和可处理仓位。</p></div><span class="count-label">{len(data['open_positions'])} 支</span></div>
          <div class="position-list">{positions_html}</div>
          <a class="full-action" href="stories.html?status=current">查看持仓故事</a>
        </aside>
      </div>
    """


def render_timeline(data: dict[str, Any]) -> str:
    counts = data["document_counts"]
    filters = ['<button type="button" data-timeline-filter="all" aria-pressed="true">全部</button>']
    for category in TIMELINE_CATEGORIES:
        filters.append(
            f'<button type="button" data-timeline-filter="{category}" aria-pressed="false">{esc(REPORT_LABELS[category])}<span>{counts.get(category, 0)}</span></button>'
        )
    dates = Counter(item["date"] for item in data["documents"] if item["date"])
    calendar = ['<button type="button" data-calendar-date="all" aria-pressed="true"><strong>全部</strong><small>所有日期</small></button>']
    for date, count in sorted(dates.items(), reverse=True):
        calendar.append(
            f'<button type="button" data-calendar-date="{esc(date)}" aria-pressed="false"><strong class="mono">{esc(date[8:])}</strong><span>{esc(date[5:7])} 月</span><small>{count} 项</small></button>'
        )
    rows = []
    for item in data["documents"]:
        search = f"{item['title']} {item['summary']} {' '.join(item['stock_codes'])}"
        rows.append(
            f"""<article class="timeline-item" data-timeline-item data-category="{esc(item['category'])}" data-date="{esc(item['date'])}" data-stocks="{esc(' '.join(item['stock_codes']))}" data-search="{esc(search)}">
              {document_link(item)}
            </article>"""
        )
    return f"""
      <header class="page-heading"><div><span class="page-context mono">TRAINING TIMELINE</span><h1>训练时间线</h1><p>按交易日阅读教练手记、股票池、复盘、纪律与市场证据。</p></div></header>
      <section class="filter-surface" data-timeline-app data-page-size="8">
        <div class="filter-row"><label class="field"><span>全文检索</span><input id="timelineSearch" type="search" placeholder="股票、日期、标题或正文…" autocomplete="off"></label><label class="field compact-field"><span>股票代码</span><input id="timelineStock" inputmode="numeric" type="search" placeholder="例如 300260…" autocomplete="off"></label></div>
        <div class="segmented filters" role="group" aria-label="文档类型">{''.join(filters)}</div>
        <div class="timeline-layout">
          <aside class="calendar-rail" aria-label="日期筛选">{''.join(calendar)}</aside>
          <div class="timeline-results"><div class="result-status" id="timelineStatus" aria-live="polite"></div><div class="timeline-list">{''.join(rows)}</div><div class="empty-state" id="timelineEmpty" hidden>没有符合条件的训练记录。请缩短关键词或清除筛选。</div><nav class="pagination" aria-label="时间线分页"><button type="button" data-page-prev>上一页</button><span id="timelinePage" class="mono"></span><button type="button" data-page-next>下一页</button></nav></div>
        </div>
      </section>
    """


def render_stories(data: dict[str, Any]) -> str:
    rows = []
    for story in data["stories"]:
        rows.append(
            f"""<article class="story-row" data-story-item data-status="{esc(story['status'])}" data-search="{esc(story['stock_code'] + ' ' + story['stock_name'])}">
              <a href="{esc(story['page_path'])}">
                <span class="story-identity"><strong>{esc(story['stock_name'])}</strong><small class="mono">{esc(story['stock_code'])}</small></span>
                <span><small>状态</small><strong>{esc(story['status_label'])}</strong></span>
                <span><small>最近交易</small><strong class="mono">{esc(story['latest_trade_date'] or '—')}</strong></span>
                <span><small>交易事件</small><strong class="mono">{story['trade_count']}</strong></span>
                <span><small>总盈亏</small><strong class="mono {value_class(story['total_pnl'])}">{money(story['total_pnl'])}</strong></span>
              </a>
            </article>"""
        )
    current_count = sum(1 for story in data["stories"] if story["status"] == "current")
    closed_count = len(data["stories"]) - current_count
    return f"""
      <header class="page-heading"><div><span class="page-context mono">POSITION STORIES</span><h1>股票故事</h1><p>从观察、买入、加减仓到关闭复盘，按股票连续追踪。</p></div></header>
      <section class="filter-surface" data-story-app data-page-size="12">
        <div class="filter-row"><label class="field"><span>搜索股票</span><input id="storySearch" type="search" placeholder="股票名称或代码…" autocomplete="off"></label></div>
        <div class="segmented" role="group" aria-label="故事状态"><button type="button" data-story-filter="current" aria-pressed="true">当前持仓 <span>{current_count}</span></button><button type="button" data-story-filter="closed" aria-pressed="false">历史故事 <span>{closed_count}</span></button><button type="button" data-story-filter="all" aria-pressed="false">全部 <span>{len(data['stories'])}</span></button></div>
        <div class="story-list">{''.join(rows)}</div>
        <div class="empty-state" id="storyEmpty" hidden>没有符合条件的股票故事。</div>
        <nav class="pagination" aria-label="故事分页"><button type="button" data-page-prev>上一页</button><span id="storyPage" class="mono"></span><button type="button" data-page-next>下一页</button></nav>
      </section>
    """


def trade_rows_html(trades: list[dict[str, Any]], prefix: str = "") -> str:
    rows = []
    for trade in trades:
        side = str(trade.get("side") or "")
        label = "买入" if side == "BUY" else "卖出"
        cls = "buy" if side == "BUY" else "sell"
        code = str(trade.get("stock_code") or "")
        rows.append(
            f"""<tr data-ledger-row data-side="{esc(side.lower())}" data-search="{esc(code + ' ' + str(trade.get('stock_name') or '') + ' ' + str(trade.get('trade_date') or ''))}">
              <td><span class="mono">{esc(trade.get('trade_date'))}</span><small>{esc(trade.get('trade_time'))}</small></td>
              <td><a href="{prefix}stocks/{esc(code)}.html"><strong>{esc(trade.get('stock_name'))}</strong><small class="mono">{esc(code)}</small></a></td>
              <td><span class="side-label {cls}">{label}</span></td>
              <td class="num">{qty(trade.get('quantity'))}</td><td class="num">{number(trade.get('price')):.3f}</td><td class="num">{money(trade.get('amount'))}</td><td class="num">{money(trade.get('fees'))}</td>
            </tr>"""
        )
    return "".join(rows)


def render_ledger(data: dict[str, Any]) -> str:
    pnl_rows = []
    story_map = {story["stock_code"]: story for story in data["stories"]}
    for row in sorted(
        data["realized_by_stock"],
        key=lambda item: number(item.get("broker_like_total_pnl_after_fees", item.get("broker_like_realized_pnl_after_fees"))),
    ):
        code = str(row.get("stock_code") or "")
        pnl = number(row.get("broker_like_total_pnl_after_fees", row.get("broker_like_realized_pnl_after_fees")))
        story = story_map.get(code)
        status = story["status_label"] if story else "历史关闭"
        search = f"{code} {row.get('stock_name') or ''} {status}"
        pnl_rows.append(
            f"""<tr data-pnl-row data-search="{esc(search)}"><td><a href="stocks/{esc(code)}.html"><strong>{esc(row.get('stock_name'))}</strong><small class="mono">{esc(code)}</small></a></td><td class="num">{qty(row.get('closed_quantity'))}</td><td class="num {value_class(pnl)}">{money(pnl)}</td><td class="num">{pct(row.get('broker_like_realized_return_pct'))}</td><td>{esc(status)}</td></tr>"""
        )
    return f"""
      <header class="page-heading"><div><span class="page-context mono">ACCOUNT LEDGER</span><h1>交易底账</h1><p>费用、成交、已实现与持仓浮动使用同一套可复核口径。</p></div></header>
      {metrics_html(data)}
      <section class="formula-band"><strong>核算公式</strong><code>总盈亏 = 已实现盈亏 + 当前持仓市值 - 券商式持仓成本</code><span>费用已进入买入成本和卖出净收入，总费用只披露，不再次扣减。</span></section>
      <section class="work-surface" data-ledger-app data-page-size="20">
        <div class="section-heading"><div><h2>成交流水</h2><p>可按股票、日期和方向检索。</p></div><span class="count-label">{len(data['trades'])} 笔</span></div>
        <div class="filter-row"><label class="field"><span>搜索流水</span><input id="ledgerSearch" type="search" placeholder="股票、代码或日期…" autocomplete="off"></label><div class="segmented" role="group" aria-label="买卖方向"><button type="button" data-ledger-filter="all" aria-pressed="true">全部</button><button type="button" data-ledger-filter="buy" aria-pressed="false">买入</button><button type="button" data-ledger-filter="sell" aria-pressed="false">卖出</button></div></div>
        <div class="table-scroll"><table><thead><tr><th>日期 / 时间</th><th>股票</th><th>方向</th><th class="num">数量</th><th class="num">价格</th><th class="num">金额</th><th class="num">费用</th></tr></thead><tbody>{trade_rows_html(data['trades'])}</tbody></table></div>
        <div class="empty-state" id="ledgerEmpty" hidden>没有符合条件的成交记录。</div>
        <nav class="pagination" aria-label="成交分页"><button type="button" data-page-prev>上一页</button><span id="ledgerPage" class="mono"></span><button type="button" data-page-next>下一页</button></nav>
      </section>
      <section class="work-surface" data-pnl-app data-page-size="20">
        <div class="section-heading"><div><h2>全历史单票盈亏</h2><p>证券现金调整已计入对应股票，可按名称或代码检索。</p></div><span class="count-label">{len(pnl_rows)} 支</span></div>
        <div class="filter-row"><label class="field"><span>搜索单票盈亏</span><input id="pnlSearch" type="search" placeholder="股票名称或代码…" autocomplete="off"></label></div>
        <div class="table-scroll"><table><thead><tr><th>股票</th><th class="num">平仓数量</th><th class="num">已实现总盈亏</th><th class="num">收益率</th><th>故事状态</th></tr></thead><tbody>{''.join(pnl_rows)}</tbody></table></div>
        <div class="empty-state" id="pnlEmpty" hidden>没有符合条件的单票盈亏记录。</div>
        <nav class="pagination" aria-label="单票盈亏分页"><button type="button" data-page-prev>上一页</button><span id="pnlPage" class="mono"></span><button type="button" data-page-next>下一页</button></nav>
      </section>
    """


def render_rules(data: dict[str, Any]) -> str:
    tabs = []
    panels = []
    for index, state in enumerate(data["states"]):
        tabs.append(
            f'<button type="button" data-rule-tab="{esc(state["key"])}" aria-pressed="{"true" if index == 0 else "false"}">{esc(state["label"])}</button>'
        )
        panels.append(
            f'<section class="rule-panel markdown-body" data-rule-panel="{esc(state["key"])}"{"" if index == 0 else " hidden"}>{state["html"]}</section>'
        )
    return f"""
      <header class="page-heading"><div><span class="page-context mono">DISCIPLINE SYSTEM</span><h1>纪律规则</h1><p>长期弱点、个人模式、筛选协议和决策事件共同构成训练约束。</p></div></header>
      <section class="rules-layout" data-rules-app><nav class="rule-tabs" aria-label="纪律文档">{''.join(tabs)}</nav><div class="rule-content">{''.join(panels)}</div></section>
    """


def render_document(
    item: dict[str, Any],
    generated_at: str,
    previous_item: dict[str, Any] | None,
    next_item: dict[str, Any] | None,
    story_codes: set[str],
) -> str:
    stock_links = "".join(
        (
            f'<a href="../stocks/{esc(code)}.html" class="inline-link mono">{esc(code)}</a>'
            if code in story_codes
            else f'<span class="inline-code mono">{esc(code)}</span>'
        )
        for code in item["stock_codes"]
    ) or '<span class="muted">未识别单票关联</span>'
    previous_link = (
        f'<a href="../{esc(previous_item["document_path"])}">上一篇<br><strong>{esc(previous_item["title"])}</strong></a>'
        if previous_item
        else '<span class="disabled">没有上一篇</span>'
    )
    next_link = (
        f'<a href="../{esc(next_item["document_path"])}">下一篇<br><strong>{esc(next_item["title"])}</strong></a>'
        if next_item
        else '<span class="disabled">没有下一篇</span>'
    )
    content = f"""
      <nav class="breadcrumbs" aria-label="面包屑"><a href="../timeline.html">训练时间线</a><span>/</span><span>{esc(item['category_label'])}</span></nav>
      <header class="document-heading"><span class="page-context mono">{esc(item['category_label'])} / {esc(item['date'])}</span><h1>{esc(item['title'])}</h1><div class="document-meta"><span>关联股票：{stock_links}</span><span>源文件：<code>{esc(item['source_path'])}</code></span></div></header>
      <div class="document-layout"><article class="markdown-body document-body">{render_embedded_markdown(item['markdown'])}</article><aside class="document-inspector"><strong>阅读口径</strong><p>本页直接读取本地 Markdown，并使用个人站统一样式重渲染。</p><dl><div><dt>类型</dt><dd>{esc(item['category_label'])}</dd></div><div><dt>归档日期</dt><dd class="mono">{esc(item['date'])}</dd></div><div><dt>源格式</dt><dd>Markdown</dd></div></dl></aside></div>
      <nav class="document-pager" aria-label="文档前后导航">{previous_link}{next_link}</nav>
    """
    return page_shell(item["title"], "timeline", content, generated_at, depth=1)


def render_stock(story: dict[str, Any], generated_at: str) -> str:
    documents = "".join(document_link(item, "../") for item in story["documents"]) or '<div class="empty-state">暂无关联训练文档。</div>'
    storyline = (
        f'<article class="markdown-body">{render_markdown(story["storyline_markdown"])}</article>'
        if story["storyline_markdown"]
        else '<div class="empty-state">账本事实已形成，但教练故事线尚未人工沉淀。</div>'
    )
    is_current = story["status"] == "current"
    cost_value = story["average_cost"] if is_current else "—"
    cost_note = f"行情截至 {story['quote_date'] or '待核验'}" if is_current else "已清仓，不再计算持仓成本"
    floating_value = story["unrealized_pnl"] if is_current else "—"
    floating_note = "最新行情市值减持仓成本" if is_current else "已清仓，无持仓浮动盈亏"
    content = f"""
      <nav class="breadcrumbs" aria-label="面包屑"><a href="../stories.html">股票故事</a><span>/</span><span class="mono">{esc(story['stock_code'])}</span></nav>
      <header class="stock-heading"><div><span class="page-context mono">{esc(story['status_label'])}</span><h1>{esc(story['stock_name'])} <span class="mono">{esc(story['stock_code'])}</span></h1><p>{esc(story['first_trade_date'])} 至 {esc(story['latest_trade_date'])} · {story['trade_count']} 个成交事件</p></div><span class="review-badge">{esc(story['storyline_review_status'])}</span></header>
      <section class="metrics-band stock-metrics">
        {metric_cell('当前数量', qty(story['open_quantity']) if story['status'] == 'current' else '0', story['status_label'], True, semantic=False)}
        {metric_cell('券商式持仓成本', cost_value, cost_note, semantic=False)}
        {metric_cell('已实现盈亏', story['realized_pnl'], '含费用及证券现金调整')}
        {metric_cell('持仓浮动盈亏', floating_value, floating_note, semantic=is_current)}
        {metric_cell('故事总盈亏', story['total_pnl'], '已实现 + 未实现')}
      </section>
      <div class="work-grid stock-work-grid"><section class="work-surface"><div class="section-heading"><div><h2>成交生命周期</h2><p>账本事实，按时间倒序。</p></div></div><div class="table-scroll"><table><thead><tr><th>日期 / 时间</th><th>股票</th><th>方向</th><th class="num">数量</th><th class="num">价格</th><th class="num">金额</th><th class="num">费用</th></tr></thead><tbody>{trade_rows_html(story['trades'], '../')}</tbody></table></div></section><aside class="inspector-surface"><div class="section-heading"><div><h2>教练故事线</h2><p>与账本事实分开显示。</p></div></div>{storyline}</aside></div>
      <section class="work-surface"><div class="section-heading"><div><h2>关联训练记录</h2><p>手记、股票池和复盘中出现的相关证据。</p></div><span class="count-label">{story['document_count']} 篇</span></div><div class="timeline-list">{documents}</div></section>
    """
    return page_shell(f"{story['stock_name']} {story['stock_code']}", "stories", content, generated_at, depth=1)


def public_site_data(data: dict[str, Any]) -> dict[str, Any]:
    documents = [
        {key: value for key, value in item.items() if key not in {"markdown", "search_text"}}
        for item in data["documents"]
    ]
    stories = [
        {
            key: value
            for key, value in story.items()
            if key not in {"trades", "documents", "storyline_markdown"}
        }
        for story in data["stories"]
    ]
    return {
        "summary": data["summary"],
        "mark_to_market": data["mark_to_market"],
        "open_positions": data["open_positions"],
        "documents": documents,
        "stories": stories,
        "cycles": data["cycles"],
        "ability": data["ability"],
        "ledger_dataset": data["ledger_dataset"],
        "trading_state": data["trading_state"],
        "discipline_feed": data["discipline_feed"],
        "workbench": data["workbench"],
        "generated_at": data["generated_at"],
    }


def write_site(
    sqlite_path: Path = DEFAULT_SQLITE,
    reports_dir: Path = DEFAULT_REPORTS,
    output_dir: Path = DEFAULT_OUTPUT,
    state_dir: Path = DEFAULT_STATE,
    as_of_date: date | None = None,
) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    assets_dir = output_dir / "assets"
    documents_dir = output_dir / "documents"
    stocks_dir = output_dir / "stocks"
    for directory in (assets_dir, documents_dir, stocks_dir):
        directory.mkdir(parents=True, exist_ok=True)

    data = build_data(sqlite_path, reports_dir, output_dir, state_dir, as_of_date)
    (assets_dir / "site.css").write_text((ASSET_SOURCE / "site.css").read_text(encoding="utf-8"), encoding="utf-8")
    (assets_dir / "site.js").write_text((ASSET_SOURCE / "site.js").read_text(encoding="utf-8"), encoding="utf-8")

    pages = {
        "index": output_dir / "index.html",
        "timeline": output_dir / "timeline.html",
        "stories": output_dir / "stories.html",
        "ledger": output_dir / "ledger.html",
        "rules": output_dir / "rules.html",
        "data": output_dir / "site_data.json",
    }
    pages["index"].write_text(page_shell("今日", "home", render_home(data), data["generated_at"]), encoding="utf-8")
    pages["timeline"].write_text(page_shell("训练时间线", "timeline", render_timeline(data), data["generated_at"]), encoding="utf-8")
    pages["stories"].write_text(page_shell("股票故事", "stories", render_stories(data), data["generated_at"]), encoding="utf-8")
    pages["ledger"].write_text(page_shell("交易底账", "ledger", render_ledger(data), data["generated_at"]), encoding="utf-8")
    pages["rules"].write_text(page_shell("纪律规则", "rules", render_rules(data), data["generated_at"]), encoding="utf-8")
    pages["data"].write_text(json.dumps(public_site_data(data), ensure_ascii=False, indent=2), encoding="utf-8")

    for index, item in enumerate(data["documents"]):
        previous_item = data["documents"][index - 1] if index > 0 else None
        next_item = data["documents"][index + 1] if index + 1 < len(data["documents"]) else None
        target = output_dir / item["document_path"]
        target.write_text(
            render_document(
                item,
                data["generated_at"],
                previous_item,
                next_item,
                {story["stock_code"] for story in data["stories"]},
            ),
            encoding="utf-8",
        )
    for story in data["stories"]:
        target = output_dir / story["page_path"]
        target.write_text(render_stock(story, data["generated_at"]), encoding="utf-8")

    pages["site"] = pages["index"]
    return pages


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the private multi-page personal trading site.")
    parser.add_argument("--sqlite", type=Path, default=DEFAULT_SQLITE)
    parser.add_argument("--reports", type=Path, default=DEFAULT_REPORTS)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    written = write_site(args.sqlite, args.reports, args.output, state_dir=args.state)
    for key in ("index", "timeline", "stories", "ledger", "rules", "data"):
        print(f"{key}: {written[key]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
