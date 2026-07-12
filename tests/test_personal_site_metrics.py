#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from personal_site_metrics import (  # noqa: E402
    DateWindow,
    period_stock_results,
    resolve_window,
    shift_period,
    summarize_cycles,
    summarize_period,
)


def cycle(code: str, close_date: str, pnl: float, days: int, status: str = "closed") -> dict:
    return {
        "cycle_id": f"{code}-{close_date}-{pnl}",
        "status": status,
        "stock_code": code,
        "stock_name": code,
        "close_date": close_date if status == "closed" else "",
        "realized_pnl_after_fees": pnl if status == "closed" else None,
        "holding_days": days if status == "closed" else None,
    }


class AbilitySummaryTest(unittest.TestCase):
    def test_closed_cycles_define_all_ability_metrics(self) -> None:
        rows = [
            cycle("000001", "2026-07-01", 100, 2),
            cycle("000002", "2026-07-02", -50, 4),
            cycle("000003", "2026-07-03", 25, 6),
            cycle("000004", "", 0, 0, status="open"),
        ]

        result = summarize_cycles(rows)

        self.assertEqual(result["closed_cycles"], 3)
        self.assertEqual(result["win_rate"], 66.67)
        self.assertEqual(result["average_payoff_ratio"], 1.25)
        self.assertEqual(result["profit_factor"], 2.5)
        self.assertEqual(result["expectancy"], 25.0)
        self.assertEqual(result["average_holding_days"], 4.0)
        self.assertEqual(result["median_holding_days"], 4.0)

    def test_ratio_states_do_not_emit_infinity(self) -> None:
        no_losses = summarize_cycles([cycle("000001", "2026-07-01", 100, 2)])
        no_wins = summarize_cycles([cycle("000001", "2026-07-01", -100, 2)])
        empty = summarize_cycles([])

        self.assertEqual(no_losses["profit_factor_state"], "no_losses")
        self.assertIsNone(no_losses["profit_factor"])
        self.assertEqual(no_wins["average_payoff_ratio_state"], "no_wins")
        self.assertEqual(no_wins["profit_factor"], 0.0)
        self.assertEqual(empty["win_rate_state"], "no_samples")


class DateWindowTest(unittest.TestCase):
    def test_day_week_month_year_and_custom_boundaries(self) -> None:
        minimum = date(2025, 12, 15)
        maximum = date(2026, 7, 10)

        self.assertEqual(resolve_window("day", "2026-07-10", "", "", minimum, maximum).label, "2026-07-10")
        week = resolve_window("week", "2026-07-06", "", "", minimum, maximum)
        self.assertEqual((week.start, week.end), (date(2026, 7, 6), date(2026, 7, 12)))
        month = resolve_window("month", "2026-02", "", "", minimum, maximum)
        self.assertEqual((month.start, month.end), (date(2026, 2, 1), date(2026, 2, 28)))
        year = resolve_window("year", "2026", "", "", minimum, maximum)
        self.assertEqual((year.start, year.end), (date(2026, 1, 1), date(2026, 12, 31)))
        custom = resolve_window("custom", "", "2026-01-01", "2026-07-10", minimum, maximum)
        self.assertEqual(custom.label, "2026-01-01 至 2026-07-10")
        self.assertEqual(shift_period("month", "2026-01", -1), "2025-12")

    def test_leap_month_and_year_rollover(self) -> None:
        minimum = date(2024, 2, 1)
        maximum = date(2025, 1, 5)

        february = resolve_window("month", "2024-02", "", "", minimum, maximum)

        self.assertEqual((february.start, february.end), (date(2024, 2, 1), date(2024, 2, 29)))
        self.assertEqual(shift_period("month", "2024-12", 1), "2025-01")
        self.assertEqual(shift_period("year", "2024", 1), "2025")

    def test_invalid_or_out_of_bounds_custom_range_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "结束日期不能早于开始日期"):
            resolve_window("custom", "", "2026-07-10", "2026-07-01", date(2026, 1, 1), date(2026, 7, 10))
        with self.assertRaisesRegex(ValueError, "超出底账日期范围"):
            resolve_window("custom", "", "2025-12-31", "2026-07-01", date(2026, 1, 1), date(2026, 7, 10))


class PeriodSummaryTest(unittest.TestCase):
    def test_cycles_use_close_date_while_trades_adjustments_and_fees_use_event_date(self) -> None:
        cycles = [
            cycle("000001", "2026-07-02", 100, 5),
            cycle("000002", "2026-06-30", -40, 2),
        ]
        trades = [
            {"trade_date": "2026-07-01", "stock_code": "000001", "fees": 2.5},
            {"trade_date": "2026-06-30", "stock_code": "000002", "fees": 3.0},
        ]
        adjustments = [
            {"trade_date": "2026-07-03", "stock_code": "000001", "stock_name": "A", "net_amount": 8.0},
            {"trade_date": "2026-06-30", "stock_code": "000002", "stock_name": "B", "net_amount": 5.0},
        ]
        window = DateWindow("custom", "2026-07-01 至 2026-07-03", date(2026, 7, 1), date(2026, 7, 3), "")

        summary = summarize_period(cycles, trades, adjustments, window)
        stocks = period_stock_results(cycles, adjustments, window)

        self.assertEqual(summary["realized_pnl"], 108.0)
        self.assertEqual(summary["closed_cycles"], 1)
        self.assertEqual(summary["fees"], 2.5)
        self.assertEqual(summary["stock_count"], 1)
        self.assertEqual(stocks[0]["total_pnl"], 108.0)


if __name__ == "__main__":
    unittest.main()
