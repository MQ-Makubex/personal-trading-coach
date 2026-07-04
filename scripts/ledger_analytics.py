#!/usr/bin/env python3
"""FIFO ledger analytics for sanitized local trade facts."""

from __future__ import annotations

import sqlite3
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass
class Trade:
    rowid: int
    trade_date: str
    trade_time: str
    stock_code: str
    stock_name: str
    side: str
    quantity: float
    amount: float
    fees: float


@dataclass
class Lot:
    trade_date: str
    quantity: float
    unit_cost: float


def number(value: Any) -> float:
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def money(value: float) -> float:
    return round(value, 2)


def parse_date(value: str) -> datetime | None:
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def holding_days(buy_date: str, sell_date: str) -> int | None:
    buy = parse_date(buy_date)
    sell = parse_date(sell_date)
    if not buy or not sell:
        return None
    return max((sell - buy).days, 0)


def load_trades(conn: sqlite3.Connection) -> list[Trade]:
    rows = conn.execute(
        """
        select
          rowid,
          trade_date,
          trade_time,
          stock_code,
          stock_name,
          side,
          coalesce(quantity, 0) as quantity,
          coalesce(amount, 0) as amount,
          coalesce(commission, 0)
            + coalesce(stamp_tax, 0)
            + coalesce(transfer_fee, 0)
            + coalesce(other_fee, 0) as fees
        from trades
        where side in ('BUY', 'SELL')
        order by trade_date, trade_time, rowid
        """
    ).fetchall()
    trades: list[Trade] = []
    for row in rows:
        trades.append(
            Trade(
                rowid=int(row["rowid"]),
                trade_date=str(row["trade_date"] or ""),
                trade_time=str(row["trade_time"] or ""),
                stock_code=str(row["stock_code"] or ""),
                stock_name=str(row["stock_name"] or ""),
                side=str(row["side"] or ""),
                quantity=number(row["quantity"]),
                amount=number(row["amount"]),
                fees=number(row["fees"]),
            )
        )
    return trades


def fifo_analytics(conn: sqlite3.Connection) -> dict[str, list[dict[str, Any]]]:
    lots_by_stock: dict[tuple[str, str], deque[Lot]] = defaultdict(deque)
    realized_rows: list[dict[str, Any]] = []
    unmatched: dict[tuple[str, str], float] = defaultdict(float)

    for trade in load_trades(conn):
        key = (trade.stock_code, trade.stock_name)
        if trade.quantity <= 0:
            continue

        if trade.side == "BUY":
            unit_cost = (trade.amount + trade.fees) / trade.quantity if trade.quantity else 0.0
            lots_by_stock[key].append(Lot(trade.trade_date, trade.quantity, unit_cost))
            continue

        sell_qty = trade.quantity
        sell_net_unit = (trade.amount - trade.fees) / trade.quantity if trade.quantity else 0.0
        while sell_qty > 1e-9 and lots_by_stock[key]:
            lot = lots_by_stock[key][0]
            matched_qty = min(sell_qty, lot.quantity)
            cost_basis = matched_qty * lot.unit_cost
            proceeds = matched_qty * sell_net_unit
            days = holding_days(lot.trade_date, trade.trade_date)
            realized_rows.append(
                {
                    "stock_code": trade.stock_code,
                    "stock_name": trade.stock_name,
                    "buy_date": lot.trade_date,
                    "sell_date": trade.trade_date,
                    "sell_time": trade.trade_time,
                    "quantity": money(matched_qty),
                    "cost_basis": money(cost_basis),
                    "sell_proceeds_after_fees": money(proceeds),
                    "realized_pnl_after_fees": money(proceeds - cost_basis),
                    "holding_days": days,
                }
            )
            lot.quantity -= matched_qty
            sell_qty -= matched_qty
            if lot.quantity <= 1e-9:
                lots_by_stock[key].popleft()

        if sell_qty > 1e-9:
            unmatched[key] += sell_qty

    open_positions: list[dict[str, Any]] = []
    for (stock_code, stock_name), lots in lots_by_stock.items():
        quantity = sum(lot.quantity for lot in lots)
        cost_basis = sum(lot.quantity * lot.unit_cost for lot in lots)
        if quantity <= 1e-9:
            continue
        dates = [lot.trade_date for lot in lots if lot.quantity > 1e-9 and lot.trade_date]
        open_positions.append(
            {
                "stock_code": stock_code,
                "stock_name": stock_name,
                "open_quantity": money(quantity),
                "open_cost_basis_after_fees": money(cost_basis),
                "average_cost_after_fees": money(cost_basis / quantity) if quantity else None,
                "first_buy_date": min(dates) if dates else "",
                "last_buy_date": max(dates) if dates else "",
            }
        )

    by_stock: dict[tuple[str, str], dict[str, Any]] = {}
    for row in realized_rows:
        key = (row["stock_code"], row["stock_name"])
        item = by_stock.setdefault(
            key,
            {
                "stock_code": row["stock_code"],
                "stock_name": row["stock_name"],
                "closed_quantity": 0.0,
                "cost_basis": 0.0,
                "sell_proceeds_after_fees": 0.0,
                "realized_pnl_after_fees": 0.0,
                "closed_lots": 0,
                "winning_lots": 0,
                "losing_lots": 0,
                "holding_day_sum": 0.0,
                "holding_day_weight": 0.0,
                "unmatched_sell_quantity": 0.0,
                "open_quantity": 0.0,
                "open_cost_basis_after_fees": 0.0,
            },
        )
        qty = number(row["quantity"])
        pnl = number(row["realized_pnl_after_fees"])
        item["closed_quantity"] += qty
        item["cost_basis"] += number(row["cost_basis"])
        item["sell_proceeds_after_fees"] += number(row["sell_proceeds_after_fees"])
        item["realized_pnl_after_fees"] += pnl
        item["closed_lots"] += 1
        if pnl > 0:
            item["winning_lots"] += 1
        elif pnl < 0:
            item["losing_lots"] += 1
        if row["holding_days"] is not None:
            item["holding_day_sum"] += number(row["holding_days"]) * qty
            item["holding_day_weight"] += qty

    for row in open_positions:
        key = (row["stock_code"], row["stock_name"])
        item = by_stock.setdefault(
            key,
            {
                "stock_code": row["stock_code"],
                "stock_name": row["stock_name"],
                "closed_quantity": 0.0,
                "cost_basis": 0.0,
                "sell_proceeds_after_fees": 0.0,
                "realized_pnl_after_fees": 0.0,
                "closed_lots": 0,
                "winning_lots": 0,
                "losing_lots": 0,
                "holding_day_sum": 0.0,
                "holding_day_weight": 0.0,
                "unmatched_sell_quantity": 0.0,
                "open_quantity": 0.0,
                "open_cost_basis_after_fees": 0.0,
            },
        )
        item["open_quantity"] += number(row["open_quantity"])
        item["open_cost_basis_after_fees"] += number(row["open_cost_basis_after_fees"])

    for (stock_code, stock_name), qty in unmatched.items():
        item = by_stock.setdefault(
            (stock_code, stock_name),
            {
                "stock_code": stock_code,
                "stock_name": stock_name,
                "closed_quantity": 0.0,
                "cost_basis": 0.0,
                "sell_proceeds_after_fees": 0.0,
                "realized_pnl_after_fees": 0.0,
                "closed_lots": 0,
                "winning_lots": 0,
                "losing_lots": 0,
                "holding_day_sum": 0.0,
                "holding_day_weight": 0.0,
                "unmatched_sell_quantity": 0.0,
                "open_quantity": 0.0,
                "open_cost_basis_after_fees": 0.0,
            },
        )
        item["unmatched_sell_quantity"] += qty

    by_stock_rows: list[dict[str, Any]] = []
    for item in by_stock.values():
        closed_lots = number(item["closed_lots"])
        holding_weight = number(item["holding_day_weight"])
        cost_basis = number(item["cost_basis"])
        row = {
            "stock_code": item["stock_code"],
            "stock_name": item["stock_name"],
            "closed_quantity": money(number(item["closed_quantity"])),
            "cost_basis": money(cost_basis),
            "sell_proceeds_after_fees": money(number(item["sell_proceeds_after_fees"])),
            "realized_pnl_after_fees": money(number(item["realized_pnl_after_fees"])),
            "realized_return_pct": round(number(item["realized_pnl_after_fees"]) / cost_basis * 100, 2) if cost_basis else None,
            "closed_lots": int(closed_lots),
            "win_rate_pct": round(number(item["winning_lots"]) / closed_lots * 100, 2) if closed_lots else None,
            "avg_holding_days": round(number(item["holding_day_sum"]) / holding_weight, 2) if holding_weight else None,
            "open_quantity": money(number(item["open_quantity"])),
            "open_cost_basis_after_fees": money(number(item["open_cost_basis_after_fees"])),
            "unmatched_sell_quantity": money(number(item["unmatched_sell_quantity"])),
        }
        by_stock_rows.append(row)

    realized_rows.sort(key=lambda row: (row["sell_date"], row["sell_time"], row["stock_code"]), reverse=True)
    open_positions.sort(key=lambda row: (row["stock_code"], row["stock_name"]))
    by_stock_rows.sort(key=lambda row: (row["realized_pnl_after_fees"], row["stock_code"]))
    return {
        "realized_lots": realized_rows,
        "open_positions": open_positions,
        "realized_by_stock": by_stock_rows,
    }
