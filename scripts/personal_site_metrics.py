from __future__ import annotations

import calendar
import re
import statistics
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any


@dataclass(frozen=True)
class DateWindow:
    grain: str
    label: str
    start: date | None
    end: date | None
    period: str

    def contains(self, value: str) -> bool:
        if self.start is None or self.end is None:
            return True
        try:
            current = date.fromisoformat(value)
        except ValueError:
            return False
        return self.start <= current <= self.end


def _value(record: Any, key: str, default: Any = None) -> Any:
    if isinstance(record, dict):
        return record.get(key, default)
    return getattr(record, key, default)


def _round(value: float) -> float:
    return round(value + 0.0, 2)


def summarize_cycles(cycles: list[dict[str, Any]]) -> dict[str, Any]:
    closed = [row for row in cycles if row.get("status") == "closed"]
    wins = [float(row["realized_pnl_after_fees"]) for row in closed if float(row["realized_pnl_after_fees"]) > 0]
    losses = [float(row["realized_pnl_after_fees"]) for row in closed if float(row["realized_pnl_after_fees"]) < 0]
    durations = [float(row["holding_days"]) for row in closed if row.get("holding_days") is not None]
    no_samples = not closed
    payoff_state = "no_samples" if no_samples else "no_losses" if not losses else "no_wins" if not wins else "value"
    factor_state = "no_samples" if no_samples else "no_losses" if not losses else "value"
    payoff = None if payoff_state != "value" else _round((sum(wins) / len(wins)) / abs(sum(losses) / len(losses)))
    factor = None if factor_state in {"no_samples", "no_losses"} else _round(sum(wins) / abs(sum(losses))) if losses else None
    return {
        "closed_cycles": len(closed),
        "winning_cycles": len(wins),
        "losing_cycles": len(losses),
        "win_rate": None if no_samples else _round(len(wins) / len(closed) * 100),
        "win_rate_state": "no_samples" if no_samples else "value",
        "average_payoff_ratio": payoff,
        "average_payoff_ratio_state": payoff_state,
        "profit_factor": factor,
        "profit_factor_state": factor_state,
        "expectancy": None if no_samples else _round(sum(float(row["realized_pnl_after_fees"]) for row in closed) / len(closed)),
        "expectancy_state": "no_samples" if no_samples else "value",
        "average_holding_days": None if not durations else _round(sum(durations) / len(durations)),
        "median_holding_days": None if not durations else _round(float(statistics.median(durations))),
    }


def _iso(value: str, message: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(message) from exc


def _month_period(anchor: date) -> str:
    return f"{anchor.year:04d}-{anchor.month:02d}"


def _period_window(grain: str, period: str) -> DateWindow:
    if grain == "day":
        current = _iso(period, "日期格式无效")
        return DateWindow(grain, current.isoformat(), current, current, current.isoformat())
    if grain == "week":
        current = _iso(period, "周起始日期格式无效")
        start = current - timedelta(days=current.weekday())
        end = start + timedelta(days=6)
        return DateWindow(grain, f"{start.isoformat()} 至 {end.isoformat()}", start, end, start.isoformat())
    if grain == "month":
        if not re.fullmatch(r"\d{4}-\d{2}", period):
            raise ValueError("月份格式无效")
        year, month = (int(value) for value in period.split("-"))
        start = date(year, month, 1)
        end = date(year, month, calendar.monthrange(year, month)[1])
        return DateWindow(grain, period, start, end, period)
    if grain == "year":
        if not re.fullmatch(r"\d{4}", period):
            raise ValueError("年份格式无效")
        year = int(period)
        return DateWindow(grain, period, date(year, 1, 1), date(year, 12, 31), period)
    raise ValueError("不支持的时间粒度")


def resolve_window(
    grain: str,
    period: str,
    start_text: str,
    end_text: str,
    ledger_min: date,
    ledger_max: date,
) -> DateWindow:
    if grain == "all":
        return DateWindow("all", "全部历史", None, None, "")
    if grain == "custom":
        if not start_text or not end_text:
            raise ValueError("请输入完整的开始和结束日期")
        start = _iso(start_text, "开始日期格式无效")
        end = _iso(end_text, "结束日期格式无效")
        if end < start:
            raise ValueError("结束日期不能早于开始日期")
        if start < ledger_min or end > ledger_max:
            raise ValueError("所选日期超出底账日期范围")
        return DateWindow(grain, f"{start.isoformat()} 至 {end.isoformat()}", start, end, "")
    anchor = period
    if not anchor:
        anchor = (
            ledger_max.isoformat()
            if grain in {"day", "week"}
            else _month_period(ledger_max)
            if grain == "month"
            else str(ledger_max.year)
        )
    window = _period_window(grain, anchor)
    if window.end is not None and window.start is not None and (window.end < ledger_min or window.start > ledger_max):
        raise ValueError("所选周期超出底账日期范围")
    return window


def shift_period(grain: str, period: str, delta: int) -> str:
    if grain in {"day", "week"}:
        current = _iso(period, "日期格式无效")
        days = delta if grain == "day" else delta * 7
        return (current + timedelta(days=days)).isoformat()
    if grain == "month":
        if not re.fullmatch(r"\d{4}-\d{2}", period):
            raise ValueError("月份格式无效")
        year, month = (int(value) for value in period.split("-"))
        index = year * 12 + month - 1 + delta
        return f"{index // 12:04d}-{index % 12 + 1:02d}"
    if grain == "year":
        if not re.fullmatch(r"\d{4}", period):
            raise ValueError("年份格式无效")
        return str(int(period) + delta)
    raise ValueError("当前粒度不支持前后导航")


def summarize_period(
    cycles: list[dict[str, Any]],
    trades: list[Any],
    adjustments: list[Any],
    window: DateWindow,
) -> dict[str, Any]:
    closed = [row for row in cycles if row.get("status") == "closed" and window.contains(str(row.get("close_date") or ""))]
    event_trades = [row for row in trades if window.contains(str(_value(row, "trade_date", "")))]
    event_adjustments = [row for row in adjustments if window.contains(str(_value(row, "trade_date", "")))]
    ability = summarize_cycles(closed)
    cycle_pnl = sum(float(row.get("realized_pnl_after_fees") or 0) for row in closed)
    adjustment_pnl = sum(float(_value(row, "net_amount", 0) or 0) for row in event_adjustments)
    codes = {
        str(_value(row, "stock_code", ""))
        for row in event_trades
        if re.fullmatch(r"\d{6}", str(_value(row, "stock_code", "")))
    }
    return {
        "label": window.label,
        "realized_pnl": _round(cycle_pnl + adjustment_pnl),
        "closed_cycles": ability["closed_cycles"],
        "win_rate": ability["win_rate"],
        "win_rate_state": ability["win_rate_state"],
        "profit_factor": ability["profit_factor"],
        "profit_factor_state": ability["profit_factor_state"],
        "fees": _round(sum(float(_value(row, "fees", 0) or 0) for row in event_trades)),
        "stock_count": len(codes),
    }


def period_stock_results(
    cycles: list[dict[str, Any]],
    adjustments: list[Any],
    window: DateWindow,
) -> list[dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}

    def ensure(code: str, name: str) -> dict[str, Any]:
        return rows.setdefault(
            code,
            {
                "stock_code": code,
                "stock_name": name,
                "cycle_pnl": 0.0,
                "cash_adjustments": 0.0,
                "total_pnl": 0.0,
                "closed_cycles": 0,
            },
        )

    for cycle in cycles:
        if cycle.get("status") != "closed" or not window.contains(str(cycle.get("close_date") or "")):
            continue
        item = ensure(str(cycle.get("stock_code") or ""), str(cycle.get("stock_name") or ""))
        item["cycle_pnl"] += float(cycle.get("realized_pnl_after_fees") or 0)
        item["closed_cycles"] += 1
    for adjustment in adjustments:
        if not window.contains(str(_value(adjustment, "trade_date", ""))):
            continue
        item = ensure(
            str(_value(adjustment, "stock_code", "")),
            str(_value(adjustment, "stock_name", "")),
        )
        item["cash_adjustments"] += float(_value(adjustment, "net_amount", 0) or 0)
    for item in rows.values():
        item["cycle_pnl"] = _round(item["cycle_pnl"])
        item["cash_adjustments"] = _round(item["cash_adjustments"])
        item["total_pnl"] = _round(item["cycle_pnl"] + item["cash_adjustments"])
    return sorted(rows.values(), key=lambda row: (-abs(row["total_pnl"]), row["stock_code"]))
