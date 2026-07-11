#!/usr/bin/env python3
"""Regression tests for ledger cost-basis calculations."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from ledger_analytics import CashAdjustment, Trade, broker_like_realized_by_stock, broker_like_realized_lots, rolling_cost_positions  # noqa: E402


def trade(
    rowid: int,
    trade_date: str,
    trade_time: str,
    side: str,
    quantity: float,
    amount: float,
    fees: float = 0.0,
    net_amount: float = 0.0,
) -> Trade:
    return Trade(
        rowid=rowid,
        trade_date=trade_date,
        trade_time=trade_time,
        stock_code="000001",
        stock_name="TEST",
        side=side,
        quantity=quantity,
        amount=amount,
        net_amount=net_amount,
        fees=fees,
    )


class RollingCostPositionsTest(unittest.TestCase):
    def test_same_day_reentry_carries_realized_pnl_into_display_cost(self) -> None:
        trades = [
            trade(1, "2026-01-01", "09:30:00", "BUY", 100, 1000),
            trade(2, "2026-01-02", "10:00:00", "SELL", 100, 1200),
            trade(3, "2026-01-02", "14:00:00", "BUY", 100, 1100),
        ]

        positions = rolling_cost_positions(trades, {"000001": "TEST"})

        self.assertEqual(positions["000001"]["broker_like_quantity"], 100)
        self.assertEqual(positions["000001"]["broker_like_cost_basis_after_fees"], 900)
        self.assertEqual(positions["000001"]["broker_like_average_cost_after_fees"], 9)

    def test_next_day_reentry_resets_display_cost(self) -> None:
        trades = [
            trade(1, "2026-01-01", "09:30:00", "BUY", 100, 1000),
            trade(2, "2026-01-02", "10:00:00", "SELL", 100, 1200),
            trade(3, "2026-01-03", "09:30:00", "BUY", 100, 1100),
        ]

        positions = rolling_cost_positions(trades, {"000001": "TEST"})

        self.assertEqual(positions["000001"]["broker_like_quantity"], 100)
        self.assertEqual(positions["000001"]["broker_like_cost_basis_after_fees"], 1100)
        self.assertEqual(positions["000001"]["broker_like_average_cost_after_fees"], 11)

    def test_close_uses_broker_display_cost_basis(self) -> None:
        trades = [
            trade(1, "2026-06-30", "", "BUY", 400, 40388, 5),
            trade(2, "2026-07-01", "11:14:25", "SELL", 400, 49040, 30.40),
            trade(3, "2026-07-01", "14:39:20", "BUY", 500, 59639, 7.16),
            trade(4, "2026-07-02", "09:37:26", "BUY", 500, 56795, 6.82),
            trade(5, "2026-07-02", "14:52:26", "SELL", 500, 55915, 34.66),
            trade(6, "2026-07-03", "09:54:18", "BUY", 800, 86608, 10.39),
            trade(7, "2026-07-07", "14:56:45", "SELL", 1200, 117516, 72.87),
            trade(8, "2026-07-08", "13:12:00", "BUY", 1500, 151080, 18.13),
            trade(9, "2026-07-09", "10:01:38", "SELL", 1600, 152000, 94.24),
        ]

        rows = broker_like_realized_lots(trades, {"000001": "TEST"})
        latest = rows[0]

        self.assertEqual(len(rows), 1)
        self.assertEqual(latest["close_trade_quantity"], 1600)
        self.assertEqual(latest["cycle_sell_quantity"], 3700)
        self.assertEqual(latest["broker_like_average_cost_before_sell"], 107.64)
        self.assertEqual(latest["broker_like_cost_basis_before_sell"], 172224.43)
        self.assertEqual(latest["sell_proceeds_after_fees"], 151905.76)
        self.assertEqual(latest["broker_like_realized_pnl_after_fees"], -20318.67)
        self.assertTrue(latest["is_position_close"])

    def test_partial_sells_are_not_double_counted_in_bill_pnl(self) -> None:
        trades = [
            trade(1, "2026-01-01", "09:30:00", "BUY", 100, 1000),
            trade(2, "2026-01-02", "10:00:00", "SELL", 50, 600),
            trade(3, "2026-01-03", "10:00:00", "SELL", 50, 600),
        ]

        rows = broker_like_realized_lots(trades, {"000001": "TEST"})
        by_stock = broker_like_realized_by_stock(rows, {"000001": "TEST"})

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["broker_like_realized_pnl_after_fees"], 200)
        self.assertEqual(by_stock[0]["broker_like_realized_pnl_after_fees"], 200)

    def test_net_amount_is_source_of_truth_when_fee_fields_do_not_reconcile(self) -> None:
        trades = [
            trade(1, "2026-06-11", "", "BUY", 1900, 140258, 16.83, -140274.83),
            trade(2, "2026-06-12", "", "SELL", 1900, 145941.09, 90.47, 145850.53),
        ]

        rows = broker_like_realized_lots(trades, {"000001": "TEST"})

        self.assertEqual(rows[0]["sell_proceeds_after_fees"], 145850.53)
        self.assertEqual(rows[0]["broker_like_realized_pnl_after_fees"], 5575.70)

    def test_stock_cash_adjustments_are_added_to_total_pnl_not_trade_close_pnl(self) -> None:
        trades = [
            trade(1, "2026-06-01", "", "BUY", 100, 1000),
            trade(2, "2026-06-02", "", "SELL", 100, 900),
        ]
        adjustments = [
            CashAdjustment(1, "2026-06-03", "", "000001", "TEST", "红利入账", 200),
            CashAdjustment(2, "2026-06-04", "", "000001", "TEST", "股息红利差异扣税", -40),
        ]

        lots = broker_like_realized_lots(trades, {"000001": "TEST"})
        by_stock = broker_like_realized_by_stock(lots, {"000001": "TEST"}, adjustments)

        self.assertEqual(by_stock[0]["broker_like_realized_pnl_after_fees"], -100)
        self.assertEqual(by_stock[0]["cash_adjustment_amount"], 160)
        self.assertEqual(by_stock[0]["broker_like_total_pnl_after_fees"], 60)


if __name__ == "__main__":
    unittest.main()
