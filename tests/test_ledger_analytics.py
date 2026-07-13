#!/usr/bin/env python3
"""Regression tests for ledger cost-basis calculations."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from ledger_analytics import (  # noqa: E402
    CashAdjustment,
    Trade,
    broker_like_cycles,
    broker_like_realized_by_stock,
    broker_like_realized_lots,
    cycle_id_for_trade,
    rolling_cost_positions,
)


def trade(
    rowid: int,
    trade_date: str,
    trade_time: str,
    side: str,
    quantity: float,
    amount: float,
    fees: float = 0.0,
    net_amount: float = 0.0,
    price: float | None = None,
    stock_code: str = "000001",
    stock_name: str = "TEST",
) -> Trade:
    return Trade(
        rowid=rowid,
        trade_date=trade_date,
        trade_time=trade_time,
        stock_code=stock_code,
        stock_name=stock_name,
        side=side,
        quantity=quantity,
        amount=amount,
        price=amount / quantity if price is None and quantity else (price or 0.0),
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


class BrokerLikeCyclesTest(unittest.TestCase):
    def test_zero_quantity_buy_does_not_defer_same_day_close(self) -> None:
        trades = [
            trade(1, "2026-01-01", "09:30:00", "BUY", 100, 1000),
            trade(2, "2026-01-02", "10:00:00", "SELL", 100, 1200),
            trade(3, "2026-01-02", "14:00:00", "BUY", 0, 0),
        ]

        cycles = broker_like_cycles(trades, {"000001": "TEST"})

        self.assertEqual(len(cycles), 1)
        self.assertEqual(cycles[0]["status"], "closed")
        self.assertEqual(cycles[0]["close_date"], "2026-01-02")
        self.assertEqual([event["rowid"] for event in cycles[0]["events"]], [1, 2])

    def test_cycle_schema_events_and_order_are_canonical(self) -> None:
        trades = [
            trade(6, "2026-01-02", "09:00:00", "BUY", 100, 1200, stock_code="000003"),
            trade(
                3,
                "2026-01-02",
                "10:00:00",
                "SELL",
                100,
                1200,
                fees=2,
                net_amount=1198,
                stock_code="000001",
            ),
            trade(
                2,
                "2026-01-01",
                "09:30:00",
                "BUY",
                60,
                660,
                fees=1,
                net_amount=-661,
                stock_code="000001",
            ),
            trade(5, "2026-01-01", "09:30:00", "BUY", 100, 1000, stock_code="000002"),
            trade(
                1,
                "2026-01-01",
                "09:30:00",
                "BUY",
                40,
                400,
                fees=1,
                net_amount=-401,
                stock_code="000001",
            ),
        ]

        cycles = broker_like_cycles(
            trades,
            {"000001": "ONE", "000002": "TWO", "000003": "THREE"},
        )

        cycle_keys = {
            "cycle_id",
            "status",
            "stock_code",
            "stock_name",
            "first_buy_date",
            "first_buy_time",
            "last_buy_date",
            "last_buy_time",
            "close_date",
            "close_time",
            "holding_days",
            "buy_quantity",
            "sell_quantity",
            "open_quantity",
            "buy_cost_after_fees",
            "sell_proceeds_after_fees",
            "rolling_cost_basis_after_fees",
            "realized_pnl_after_fees",
            "return_pct",
            "position_quantity_before_close",
            "close_trade_quantity",
            "close_cost_basis_before_sell",
            "close_average_cost_before_sell",
            "close_sell_proceeds_after_fees",
            "events",
        }
        event_keys = {
            "rowid",
            "trade_date",
            "trade_time",
            "side",
            "quantity",
            "price",
            "amount",
            "net_amount",
            "fees",
        }

        self.assertEqual(
            [(row["first_buy_date"], row["first_buy_time"], row["stock_code"]) for row in cycles],
            [
                ("2026-01-01", "09:30:00", "000001"),
                ("2026-01-01", "09:30:00", "000002"),
                ("2026-01-02", "09:00:00", "000003"),
            ],
        )
        for cycle in cycles:
            self.assertEqual(set(cycle), cycle_keys)
            for event in cycle["events"]:
                self.assertEqual(set(event), event_keys)
        self.assertEqual([event["rowid"] for event in cycles[0]["events"]], [1, 2, 3])
        self.assertEqual(
            cycles[0]["events"][0],
            {
                "rowid": 1,
                "trade_date": "2026-01-01",
                "trade_time": "09:30:00",
                "side": "BUY",
                "quantity": 40,
                "price": 10.0,
                "amount": 400,
                "net_amount": -401,
                "fees": 1,
            },
        )

    def test_realized_lots_preserve_schema_and_descending_cycle_order(self) -> None:
        trades = [
            trade(6, "2026-01-05", "09:00:00", "SELL", 100, 1100, stock_code="000002"),
            trade(3, "2026-01-03", "09:30:00", "BUY", 100, 1000, stock_code="000001"),
            trade(1, "2026-01-01", "09:30:00", "BUY", 100, 1000, stock_code="000001"),
            trade(5, "2026-01-05", "09:00:00", "SELL", 100, 1200, stock_code="000001"),
            trade(4, "2026-01-04", "09:30:00", "BUY", 100, 1000, stock_code="000002"),
            trade(2, "2026-01-02", "10:00:00", "SELL", 100, 1100, stock_code="000001"),
        ]

        rows = broker_like_realized_lots(trades, {"000001": "ONE", "000002": "TWO"})

        expected_keys = {
            "stock_code",
            "stock_name",
            "buy_date",
            "last_buy_date",
            "sell_date",
            "sell_time",
            "close_trade_quantity",
            "cycle_buy_quantity",
            "cycle_sell_quantity",
            "position_quantity_before_sell",
            "broker_like_average_cost_before_sell",
            "broker_like_cost_basis_before_sell",
            "sell_proceeds_after_fees",
            "broker_like_realized_pnl_after_fees",
            "is_position_close",
            "cycle_id",
            "holding_days",
            "return_pct",
        }
        self.assertEqual(
            [(row["sell_date"], row["sell_time"], row["stock_code"]) for row in rows],
            [
                ("2026-01-05", "09:00:00", "000002"),
                ("2026-01-05", "09:00:00", "000001"),
                ("2026-01-02", "10:00:00", "000001"),
            ],
        )
        for row in rows:
            self.assertEqual(set(row), expected_keys)

    def test_same_day_flat_and_reentry_stays_in_one_cycle(self) -> None:
        trades = [
            trade(1, "2026-01-01", "09:30:00", "BUY", 100, 1000),
            trade(2, "2026-01-02", "10:00:00", "SELL", 100, 1200),
            trade(3, "2026-01-02", "14:00:00", "BUY", 100, 1100),
            trade(4, "2026-01-03", "10:00:00", "SELL", 100, 900),
        ]

        cycles = broker_like_cycles(trades, {"000001": "TEST"})

        self.assertEqual(len(cycles), 1)
        self.assertEqual(cycles[0]["status"], "closed")
        self.assertEqual(cycles[0]["first_buy_date"], "2026-01-01")
        self.assertEqual(cycles[0]["close_date"], "2026-01-03")
        self.assertEqual(cycles[0]["holding_days"], 2)
        self.assertEqual(cycles[0]["realized_pnl_after_fees"], 0.0)
        self.assertEqual(len(cycles[0]["events"]), 4)

    def test_next_day_reentry_starts_a_second_cycle(self) -> None:
        trades = [
            trade(1, "2026-01-01", "09:30:00", "BUY", 100, 1000),
            trade(2, "2026-01-02", "10:00:00", "SELL", 100, 1200),
            trade(3, "2026-01-03", "09:30:00", "BUY", 100, 1100),
        ]

        cycles = broker_like_cycles(trades, {"000001": "TEST"})

        self.assertEqual([row["status"] for row in cycles], ["closed", "open"])
        self.assertNotEqual(cycles[0]["cycle_id"], cycles[1]["cycle_id"])

    def test_cycle_id_is_unchanged_when_the_cycle_later_closes(self) -> None:
        first = trade(1, "2026-01-01", "09:30:00", "BUY", 100, 1000, net_amount=-1000)
        open_cycle = broker_like_cycles([first], {"000001": "TEST"})[0]
        closed_cycle = broker_like_cycles(
            [first, trade(2, "2026-01-02", "10:00:00", "SELL", 100, 1200, net_amount=1200)],
            {"000001": "TEST"},
        )[0]

        self.assertEqual(open_cycle["cycle_id"], closed_cycle["cycle_id"])
        self.assertEqual(open_cycle["cycle_id"], cycle_id_for_trade(first))

    def test_broker_cost_regression_is_preserved_in_canonical_cycle(self) -> None:
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

        cycle = broker_like_cycles(trades, {"000001": "TEST"})[0]

        self.assertEqual(cycle["close_average_cost_before_sell"], 107.64)
        self.assertEqual(cycle["realized_pnl_after_fees"], -20318.67)


if __name__ == "__main__":
    unittest.main()
