#!/usr/bin/env python3
"""Ledger analytics for broker-like display cost and FIFO audit views."""

from __future__ import annotations

import hashlib
import json
import re
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
    price: float = 0.0
    net_amount: float = 0.0
    fees: float = 0.0


@dataclass
class CashAdjustment:
    rowid: int
    trade_date: str
    trade_time: str
    stock_code: str
    stock_name: str
    category: str
    net_amount: float


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


def buy_cost_after_fees(trade: Trade) -> float:
    if trade.net_amount < 0:
        return -trade.net_amount
    return trade.amount + trade.fees


def sell_proceeds_after_fees(trade: Trade) -> float:
    if trade.net_amount > 0:
        return trade.net_amount
    return trade.amount - trade.fees


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
          coalesce(price, 0) as price,
          coalesce(net_amount, 0) as net_amount,
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
                price=number(row["price"]),
                net_amount=number(row["net_amount"]),
                fees=number(row["fees"]),
            )
        )
    return trades


def load_cash_adjustments(conn: sqlite3.Connection) -> list[CashAdjustment]:
    table_exists = conn.execute(
        "select 1 from sqlite_master where type = 'table' and name = 'cash_adjustments'"
    ).fetchone()
    if not table_exists:
        return []
    rows = conn.execute(
        """
        select
          rowid,
          trade_date,
          trade_time,
          stock_code,
          stock_name,
          category,
          coalesce(net_amount, 0) as net_amount
        from cash_adjustments
        where stock_code glob '[0-9][0-9][0-9][0-9][0-9][0-9]'
          and abs(coalesce(net_amount, 0)) > 0
        order by trade_date, trade_time, rowid
        """
    ).fetchall()
    return [
        CashAdjustment(
            rowid=int(row["rowid"]),
            trade_date=str(row["trade_date"] or ""),
            trade_time=str(row["trade_time"] or ""),
            stock_code=str(row["stock_code"] or ""),
            stock_name=str(row["stock_name"] or ""),
            category=str(row["category"] or ""),
            net_amount=number(row["net_amount"]),
        )
        for row in rows
    ]


def display_names_by_code(trades: list[Trade], cash_adjustments: list[CashAdjustment] | None = None) -> dict[str, str]:
    names: dict[str, str] = {}
    fallback: dict[str, str] = {}
    for record in [*trades, *(cash_adjustments or [])]:
        code = record.stock_code
        name = record.stock_name
        if not code:
            continue
        if name:
            fallback[code] = name[2:] if name.startswith("XD") else name
        if name and not name.startswith("XD"):
            names[code] = name
    return {code: names.get(code) or fallback.get(code, "") for code in fallback}


def rolling_cost_positions(trades: list[Trade], display_names: dict[str, str]) -> dict[str, dict[str, Any]]:
    quantities: dict[str, float] = defaultdict(float)
    costs: dict[str, float] = defaultdict(float)
    last_flat_date: dict[str, str] = {}
    first_buy: dict[str, str] = {}
    last_buy: dict[str, str] = {}

    for trade in trades:
        code = trade.stock_code
        if not code or trade.quantity <= 0:
            continue

        if trade.side == "BUY":
            if quantities[code] <= 1e-9:
                if last_flat_date.get(code) != trade.trade_date:
                    costs[code] = 0.0
                    first_buy[code] = trade.trade_date
                elif code not in first_buy:
                    first_buy[code] = trade.trade_date
            quantities[code] += trade.quantity
            costs[code] += buy_cost_after_fees(trade)
            last_buy[code] = trade.trade_date
            continue

        sell_proceeds = sell_proceeds_after_fees(trade)
        quantities[code] -= trade.quantity
        costs[code] -= sell_proceeds
        if quantities[code] <= 1e-9:
            quantities[code] = 0.0
            last_flat_date[code] = trade.trade_date

    output: dict[str, dict[str, Any]] = {}
    for code, quantity in quantities.items():
        if quantity <= 1e-9:
            continue
        cost = costs[code]
        output[code] = {
            "stock_code": code,
            "stock_name": display_names.get(code, ""),
            "broker_like_quantity": money(quantity),
            "broker_like_cost_basis_after_fees": money(cost),
            "broker_like_average_cost_after_fees": money(cost / quantity) if quantity else None,
            "broker_like_first_buy_date": first_buy.get(code, ""),
            "broker_like_last_buy_date": last_buy.get(code, ""),
        }
    return output


def future_same_day_buys(trades: list[Trade]) -> set[int]:
    future_buy_keys: set[tuple[str, str]] = set()
    rows_with_future_buy: set[int] = set()
    for trade in reversed(trades):
        key = (trade.stock_code, trade.trade_date)
        if trade.side == "SELL" and key in future_buy_keys:
            rows_with_future_buy.add(trade.rowid)
        elif trade.side == "BUY" and trade.quantity > 0:
            future_buy_keys.add(key)
    return rows_with_future_buy


def cycle_id_for_trade(trade: Trade) -> str:
    price = trade.price if trade.price else (trade.amount / trade.quantity if trade.quantity else 0.0)
    net_amount = trade.net_amount
    if abs(net_amount) <= 1e-9:
        net_amount = -buy_cost_after_fees(trade) if trade.side == "BUY" else sell_proceeds_after_fees(trade)
    facts = {
        "stock_code": trade.stock_code,
        "trade_date": trade.trade_date,
        "trade_time": trade.trade_time,
        "side": trade.side,
        "quantity": round(trade.quantity, 6),
        "price": round(price, 6),
        "net_amount": round(net_amount, 6),
    }
    digest = hashlib.sha1(
        json.dumps(facts, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:8]
    compact_date = re.sub(r"\D", "", trade.trade_date)
    return f"cyc_{trade.stock_code}_{compact_date}_{digest}"


def _cycle_event(trade: Trade) -> dict[str, Any]:
    price = trade.price if trade.price else (trade.amount / trade.quantity if trade.quantity else 0.0)
    return {
        "rowid": trade.rowid,
        "trade_date": trade.trade_date,
        "trade_time": trade.trade_time,
        "side": trade.side,
        "quantity": money(trade.quantity),
        "price": round(price, 4),
        "amount": money(trade.amount),
        "net_amount": money(trade.net_amount),
        "fees": money(trade.fees),
    }


def broker_like_cycles(trades: list[Trade], display_names: dict[str, str]) -> list[dict[str, Any]]:
    ordered = sorted(trades, key=lambda row: (row.trade_date, row.trade_time, row.rowid))
    same_day_reentry_after_sell = future_same_day_buys(ordered)
    active: dict[str, dict[str, Any]] = {}
    completed: list[dict[str, Any]] = []

    for trade in ordered:
        code = trade.stock_code
        if not code or trade.quantity <= 0:
            continue
        state = active.get(code)
        if trade.side == "BUY":
            if state is None:
                state = {
                    "cycle_id": cycle_id_for_trade(trade),
                    "status": "open",
                    "stock_code": code,
                    "stock_name": display_names.get(code, trade.stock_name),
                    "first_buy_date": trade.trade_date,
                    "first_buy_time": trade.trade_time,
                    "last_buy_date": trade.trade_date,
                    "last_buy_time": trade.trade_time,
                    "quantity": 0.0,
                    "rolling_cost": 0.0,
                    "buy_quantity": 0.0,
                    "sell_quantity": 0.0,
                    "buy_cost": 0.0,
                    "sell_proceeds": 0.0,
                    "events": [],
                }
                active[code] = state
            state["last_buy_date"] = trade.trade_date
            state["last_buy_time"] = trade.trade_time
            state["quantity"] += trade.quantity
            state["rolling_cost"] += buy_cost_after_fees(trade)
            state["buy_quantity"] += trade.quantity
            state["buy_cost"] += buy_cost_after_fees(trade)
            state["events"].append(_cycle_event(trade))
            continue

        if state is None:
            continue
        before_quantity = state["quantity"]
        before_cost = state["rolling_cost"]
        proceeds = sell_proceeds_after_fees(trade)
        state["quantity"] = max(before_quantity - trade.quantity, 0.0)
        state["rolling_cost"] -= proceeds
        state["sell_quantity"] += min(trade.quantity, before_quantity)
        state["sell_proceeds"] += proceeds
        state["events"].append(_cycle_event(trade))
        if state["quantity"] > 1e-9 or trade.rowid in same_day_reentry_after_sell:
            continue

        realized = -state["rolling_cost"]
        duration = holding_days(state["first_buy_date"], trade.trade_date)
        completed.append(
            {
                "cycle_id": state["cycle_id"],
                "status": "closed",
                "stock_code": code,
                "stock_name": state["stock_name"],
                "first_buy_date": state["first_buy_date"],
                "first_buy_time": state["first_buy_time"],
                "last_buy_date": state["last_buy_date"],
                "last_buy_time": state["last_buy_time"],
                "close_date": trade.trade_date,
                "close_time": trade.trade_time,
                "holding_days": duration,
                "buy_quantity": money(state["buy_quantity"]),
                "sell_quantity": money(state["sell_quantity"]),
                "open_quantity": 0.0,
                "buy_cost_after_fees": money(state["buy_cost"]),
                "sell_proceeds_after_fees": money(state["sell_proceeds"]),
                "rolling_cost_basis_after_fees": 0.0,
                "realized_pnl_after_fees": money(realized),
                "return_pct": round(realized / state["buy_cost"] * 100, 2) if state["buy_cost"] else None,
                "position_quantity_before_close": money(before_quantity),
                "close_trade_quantity": money(min(trade.quantity, before_quantity)),
                "close_cost_basis_before_sell": money(before_cost),
                "close_average_cost_before_sell": money(before_cost / before_quantity) if before_quantity else None,
                "close_sell_proceeds_after_fees": money(proceeds),
                "events": list(state["events"]),
            }
        )
        del active[code]

    open_cycles = []
    for state in active.values():
        open_cycles.append(
            {
                "cycle_id": state["cycle_id"],
                "status": "open",
                "stock_code": state["stock_code"],
                "stock_name": state["stock_name"],
                "first_buy_date": state["first_buy_date"],
                "first_buy_time": state["first_buy_time"],
                "last_buy_date": state["last_buy_date"],
                "last_buy_time": state["last_buy_time"],
                "close_date": "",
                "close_time": "",
                "holding_days": None,
                "buy_quantity": money(state["buy_quantity"]),
                "sell_quantity": money(state["sell_quantity"]),
                "open_quantity": money(state["quantity"]),
                "buy_cost_after_fees": money(state["buy_cost"]),
                "sell_proceeds_after_fees": money(state["sell_proceeds"]),
                "rolling_cost_basis_after_fees": money(state["rolling_cost"]),
                "realized_pnl_after_fees": None,
                "return_pct": None,
                "position_quantity_before_close": None,
                "close_trade_quantity": None,
                "close_cost_basis_before_sell": None,
                "close_average_cost_before_sell": None,
                "close_sell_proceeds_after_fees": None,
                "events": list(state["events"]),
            }
        )
    return sorted(
        [*completed, *open_cycles],
        key=lambda row: (row["first_buy_date"], row["first_buy_time"], row["stock_code"]),
    )


def broker_like_realized_lots(trades: list[Trade], display_names: dict[str, str]) -> list[dict[str, Any]]:
    rows = []
    for cycle in broker_like_cycles(trades, display_names):
        if cycle["status"] != "closed":
            continue
        rows.append(
            {
                "stock_code": cycle["stock_code"],
                "stock_name": cycle["stock_name"],
                "buy_date": cycle["first_buy_date"],
                "last_buy_date": cycle["last_buy_date"],
                "sell_date": cycle["close_date"],
                "sell_time": cycle["close_time"],
                "close_trade_quantity": cycle["close_trade_quantity"],
                "cycle_buy_quantity": cycle["buy_quantity"],
                "cycle_sell_quantity": cycle["sell_quantity"],
                "position_quantity_before_sell": cycle["position_quantity_before_close"],
                "broker_like_average_cost_before_sell": cycle["close_average_cost_before_sell"],
                "broker_like_cost_basis_before_sell": cycle["close_cost_basis_before_sell"],
                "sell_proceeds_after_fees": cycle["close_sell_proceeds_after_fees"],
                "broker_like_realized_pnl_after_fees": cycle["realized_pnl_after_fees"],
                "is_position_close": True,
                "cycle_id": cycle["cycle_id"],
                "holding_days": cycle["holding_days"],
                "return_pct": cycle["return_pct"],
            }
        )
    return sorted(
        rows,
        key=lambda row: (row["sell_date"], row["sell_time"], row["stock_code"]),
        reverse=True,
    )


def broker_like_sell_impacts(trades: list[Trade], display_names: dict[str, str]) -> list[dict[str, Any]]:
    quantities: dict[str, float] = defaultdict(float)
    costs: dict[str, float] = defaultdict(float)
    last_flat_date: dict[str, str] = {}
    rows: list[dict[str, Any]] = []

    for trade in trades:
        code = trade.stock_code
        if not code or trade.quantity <= 0:
            continue
        if trade.side == "BUY":
            if quantities[code] <= 1e-9 and last_flat_date.get(code) != trade.trade_date:
                costs[code] = 0.0
            quantities[code] += trade.quantity
            costs[code] += buy_cost_after_fees(trade)
            continue

        before_quantity = quantities[code]
        before_cost = costs[code]
        sell_proceeds = sell_proceeds_after_fees(trade)
        if before_quantity > 1e-9:
            matched_qty = min(trade.quantity, before_quantity)
            sell_net_unit = sell_proceeds / trade.quantity if trade.quantity else 0.0
            average_cost = before_cost / before_quantity
            cost_basis = average_cost * matched_qty
            matched_proceeds = sell_net_unit * matched_qty
            after_quantity = max(before_quantity - trade.quantity, 0.0)
            rows.append(
                {
                    "stock_code": trade.stock_code,
                    "stock_name": display_names.get(trade.stock_code, trade.stock_name),
                    "sell_date": trade.trade_date,
                    "sell_time": trade.trade_time,
                    "quantity": money(matched_qty),
                    "position_quantity_before_sell": money(before_quantity),
                    "position_quantity_after_sell": money(after_quantity),
                    "broker_like_average_cost_before_sell": money(average_cost),
                    "broker_like_cost_basis_before_sell": money(cost_basis),
                    "sell_proceeds_after_fees": money(matched_proceeds),
                    "broker_like_sell_impact_after_fees": money(matched_proceeds - cost_basis),
                    "is_position_close": after_quantity <= 1e-9,
                }
            )
        quantities[code] -= trade.quantity
        costs[code] -= sell_proceeds
        if quantities[code] <= 1e-9:
            quantities[code] = 0.0
            last_flat_date[code] = trade.trade_date

    rows.sort(key=lambda row: (row["sell_date"], row["sell_time"], row["stock_code"]), reverse=True)
    return rows


def broker_like_realized_by_stock(
    rows: list[dict[str, Any]],
    display_names: dict[str, str],
    cash_adjustments: list[CashAdjustment] | None = None,
) -> list[dict[str, Any]]:
    by_stock: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = str(row["stock_code"])
        item = by_stock.setdefault(
            key,
            {
                "stock_code": row["stock_code"],
                "stock_name": display_names.get(key, str(row["stock_name"])),
                "closed_quantity": 0.0,
                "broker_like_cost_basis_after_fees": 0.0,
                "sell_proceeds_after_fees": 0.0,
                "broker_like_realized_pnl_after_fees": 0.0,
                "closed_lots": 0,
                "winning_lots": 0,
                "losing_lots": 0,
                "cash_adjustment_amount": 0.0,
                "cash_adjustment_rows": 0,
            },
        )
        pnl = number(row["broker_like_realized_pnl_after_fees"])
        item["closed_quantity"] += number(row["cycle_sell_quantity"])
        item["broker_like_cost_basis_after_fees"] += number(row["broker_like_cost_basis_before_sell"])
        item["sell_proceeds_after_fees"] += number(row["sell_proceeds_after_fees"])
        item["broker_like_realized_pnl_after_fees"] += pnl
        item["closed_lots"] += 1
        if pnl > 0:
            item["winning_lots"] += 1
        elif pnl < 0:
            item["losing_lots"] += 1

    for adjustment in cash_adjustments or []:
        key = adjustment.stock_code
        item = by_stock.setdefault(
            key,
            {
                "stock_code": adjustment.stock_code,
                "stock_name": display_names.get(key, adjustment.stock_name),
                "closed_quantity": 0.0,
                "broker_like_cost_basis_after_fees": 0.0,
                "sell_proceeds_after_fees": 0.0,
                "broker_like_realized_pnl_after_fees": 0.0,
                "closed_lots": 0,
                "winning_lots": 0,
                "losing_lots": 0,
                "cash_adjustment_amount": 0.0,
                "cash_adjustment_rows": 0,
            },
        )
        item["cash_adjustment_amount"] += adjustment.net_amount
        item["cash_adjustment_rows"] += 1

    output: list[dict[str, Any]] = []
    for item in by_stock.values():
        closed_lots = number(item["closed_lots"])
        cost_basis = number(item["broker_like_cost_basis_after_fees"])
        pnl = number(item["broker_like_realized_pnl_after_fees"])
        cash_adjustment_amount = number(item["cash_adjustment_amount"])
        total_pnl = pnl + cash_adjustment_amount
        output.append(
            {
                "stock_code": item["stock_code"],
                "stock_name": item["stock_name"],
                "closed_quantity": money(number(item["closed_quantity"])),
                "broker_like_cost_basis_after_fees": money(cost_basis),
                "sell_proceeds_after_fees": money(number(item["sell_proceeds_after_fees"])),
                "broker_like_realized_pnl_after_fees": money(pnl),
                "cash_adjustment_amount": money(cash_adjustment_amount),
                "cash_adjustment_rows": int(number(item["cash_adjustment_rows"])),
                "broker_like_total_pnl_after_fees": money(total_pnl),
                "broker_like_realized_return_pct": round(total_pnl / cost_basis * 100, 2) if cost_basis else None,
                "closed_lots": int(closed_lots),
                "win_rate_pct": round(number(item["winning_lots"]) / closed_lots * 100, 2) if closed_lots else None,
            }
        )
    output.sort(key=lambda row: (row["broker_like_total_pnl_after_fees"], row["stock_code"]))
    return output


def fifo_analytics(conn: sqlite3.Connection) -> dict[str, list[dict[str, Any]]]:
    trades = load_trades(conn)
    cash_adjustments = load_cash_adjustments(conn)
    display_names = display_names_by_code(trades, cash_adjustments)
    rolling_positions = rolling_cost_positions(trades, display_names)
    broker_realized_lots = broker_like_realized_lots(trades, display_names)
    broker_realized_by_stock = broker_like_realized_by_stock(
        broker_realized_lots,
        display_names,
        cash_adjustments,
    )
    broker_sell_impacts = broker_like_sell_impacts(trades, display_names)
    lots_by_stock: dict[str, deque[Lot]] = defaultdict(deque)
    realized_rows: list[dict[str, Any]] = []
    unmatched: dict[str, float] = defaultdict(float)

    for trade in trades:
        key = trade.stock_code
        if trade.quantity <= 0:
            continue

        if trade.side == "BUY":
            unit_cost = buy_cost_after_fees(trade) / trade.quantity if trade.quantity else 0.0
            lots_by_stock[key].append(Lot(trade.trade_date, trade.quantity, unit_cost))
            continue

        sell_qty = trade.quantity
        sell_net_unit = sell_proceeds_after_fees(trade) / trade.quantity if trade.quantity else 0.0
        while sell_qty > 1e-9 and lots_by_stock[key]:
            lot = lots_by_stock[key][0]
            matched_qty = min(sell_qty, lot.quantity)
            cost_basis = matched_qty * lot.unit_cost
            proceeds = matched_qty * sell_net_unit
            days = holding_days(lot.trade_date, trade.trade_date)
            realized_rows.append(
                {
                    "stock_code": trade.stock_code,
                    "stock_name": display_names.get(trade.stock_code, trade.stock_name),
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
    for stock_code, lots in lots_by_stock.items():
        quantity = sum(lot.quantity for lot in lots)
        cost_basis = sum(lot.quantity * lot.unit_cost for lot in lots)
        if quantity <= 1e-9:
            continue
        dates = [lot.trade_date for lot in lots if lot.quantity > 1e-9 and lot.trade_date]
        open_positions.append(
            {
                "stock_code": stock_code,
                "stock_name": display_names.get(stock_code, ""),
                "open_quantity": money(quantity),
                "open_cost_basis_after_fees": money(cost_basis),
                "average_cost_after_fees": money(cost_basis / quantity) if quantity else None,
                "broker_like_cost_basis_after_fees": rolling_positions.get(stock_code, {}).get("broker_like_cost_basis_after_fees"),
                "broker_like_average_cost_after_fees": rolling_positions.get(stock_code, {}).get("broker_like_average_cost_after_fees"),
                "first_buy_date": min(dates) if dates else "",
                "last_buy_date": max(dates) if dates else "",
            }
        )

    by_stock: dict[str, dict[str, Any]] = {}
    for row in realized_rows:
        key = str(row["stock_code"])
        item = by_stock.setdefault(
            key,
            {
                "stock_code": row["stock_code"],
                "stock_name": display_names.get(str(row["stock_code"]), str(row["stock_name"])),
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
        key = str(row["stock_code"])
        item = by_stock.setdefault(
            key,
            {
                "stock_code": row["stock_code"],
                "stock_name": display_names.get(str(row["stock_code"]), str(row["stock_name"])),
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
        if row.get("broker_like_cost_basis_after_fees") is not None:
            item["broker_like_cost_basis_after_fees"] = number(row["broker_like_cost_basis_after_fees"])
            item["broker_like_average_cost_after_fees"] = number(row["broker_like_average_cost_after_fees"])

    for stock_code, qty in unmatched.items():
        item = by_stock.setdefault(
            stock_code,
            {
                "stock_code": stock_code,
                "stock_name": display_names.get(stock_code, ""),
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
        "broker_like_realized_lots": broker_realized_lots,
        "broker_like_realized_by_stock": broker_realized_by_stock,
        "broker_like_sell_impacts": broker_sell_impacts,
        "cash_adjustments": [
            {
                "trade_date": adjustment.trade_date,
                "trade_time": adjustment.trade_time,
                "stock_code": adjustment.stock_code,
                "stock_name": display_names.get(adjustment.stock_code, adjustment.stock_name),
                "category": adjustment.category,
                "net_amount": money(adjustment.net_amount),
            }
            for adjustment in cash_adjustments
        ],
    }
