#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from market_data import DailyBar, DailySeries, summarize_daily_series  # noqa: E402
from research_pool_builder import build_pool  # noqa: E402
import daily_prepare  # noqa: E402
import market_data  # noqa: E402


class FakeHttpResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def __enter__(self) -> "FakeHttpResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, _limit: int) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


class MarketDataSummaryTests(unittest.TestCase):
    def test_tencent_fallback_parses_qfq_a_share_daily_bars(self) -> None:
        fetcher = getattr(market_data, "fetch_daily_bars_tencent", None)
        self.assertIsNotNone(fetcher)
        payload = {
            "code": 0,
            "msg": "",
            "data": {
                "sz002475": {
                    "qfqday": [
                        ["2026-07-22", "59.880", "59.160", "61.680", "58.800", "1062223.000"],
                        ["2026-07-23", "59.160", "61.190", "61.980", "58.650", "1209696.000"],
                    ]
                }
            },
        }
        with patch("market_data.urllib.request.urlopen", return_value=FakeHttpResponse(payload)) as urlopen:
            series = fetcher("002475", "2026-07-01", "2026-07-23", "qfq")

        requested = urlopen.call_args[0][0]
        requested_url = requested.full_url if hasattr(requested, "full_url") else str(requested)
        self.assertIn("sz002475%2Cday", requested_url)
        self.assertIn("%2Cqfq", requested_url)
        self.assertEqual(series.provider, "tencent_qfq")
        self.assertEqual(series.source, "web.ifzq.gtimg.cn/appstock/app/fqkline/get")
        self.assertEqual(series.bars[-1].trade_date, "2026-07-23")
        self.assertEqual(series.bars[-1].close, 61.19)
        self.assertEqual(series.bars[-1].volume, 1209696.0)

    def test_yahoo_fallback_parses_adjusted_a_share_daily_bars(self) -> None:
        fetcher = getattr(market_data, "fetch_daily_bars_yahoo", None)
        self.assertIsNotNone(fetcher)
        payload = {
            "chart": {
                "error": None,
                "result": [
                    {
                        "timestamp": [1784241000, 1784327400],
                        "indicators": {
                            "quote": [
                                {
                                    "open": [10.0, 10.5],
                                    "high": [10.8, 11.3],
                                    "low": [9.8, 10.4],
                                    "close": [10.6, 11.1],
                                    "volume": [1000, 1200],
                                }
                            ],
                            "adjclose": [{"adjclose": [10.4, 10.9]}],
                        },
                    }
                ],
            }
        }
        with patch("market_data.urllib.request.urlopen", return_value=FakeHttpResponse(payload)) as urlopen:
            series = fetcher("000001", "2026-07-16", "2026-07-17", "qfq")

        requested = urlopen.call_args[0][0]
        requested_url = requested.full_url if hasattr(requested, "full_url") else str(requested)
        self.assertIn("000001.SZ", requested_url)
        self.assertEqual(series.provider, "yahoo_chart")
        self.assertEqual([bar.close for bar in series.bars], [10.4, 10.9])
        self.assertEqual(series.bars[-1].volume, 1200.0)

    def test_summary_contains_facts_without_automated_scores_or_judgments(self) -> None:
        series = DailySeries(
            code="000001",
            provider="test",
            source="fixture",
            notes=["auditable note"],
            bars=[
                DailyBar(
                    trade_date=f"2026-06-{day:02d}",
                    open=10.0,
                    high=11.0,
                    low=9.0,
                    close=float(day),
                    volume=1000.0 + day,
                    amount=10000.0 + day,
                )
                for day in range(1, 21)
            ],
        )

        summary = summarize_daily_series(series)

        self.assertEqual(summary["data_provider"], "test")
        self.assertIn("ma20_state", summary)
        self.assertNotIn("ma_first_hand_score", summary)
        self.assertNotIn("ma_first_hand_reasons", summary)
        self.assertNotIn("ma_first_hand_risks", summary)


class ResearchPoolBuilderTests(unittest.TestCase):
    def test_pool_preserves_input_order_and_limit_without_derived_classification(self) -> None:
        rows = [
            {"stock_code": "000001", "stock_name": "First", "theme": "A", "notes": "manual one", "close": "10", "ma200": "9"},
            {"stock_code": "688001", "stock_name": "Excluded", "theme": "B", "notes": "manual two", "close": "20", "ma200": "19"},
            {"stock_code": "000002", "stock_name": "Second", "theme": "C", "notes": "manual three", "close": "30", "ma200": "29"},
            {"stock_code": "000003", "stock_name": "Beyond limit", "theme": "D", "notes": "manual four", "close": "40", "ma200": "39"},
        ]

        pool = build_pool(rows, limit=2, exclude_prefixes=["688"])

        self.assertEqual([row["stock_code"] for row in pool], ["000001", "000002"])
        self.assertEqual(pool[0]["notes"], "manual one")
        for row in pool:
            for forbidden in ("score", "status", "mode_fit", "ma_first_hand_score", "reasons", "risks"):
                self.assertNotIn(forbidden, row)

    def test_pool_excludes_stocks_at_or_below_ma200(self) -> None:
        rows = [
            {"stock_code": "000001", "stock_name": "Below", "close": "9", "ma200": "10"},
            {"stock_code": "000002", "stock_name": "At", "close": "10", "ma200": "10"},
            {"stock_code": "000003", "stock_name": "Above", "close": "11", "ma200": "10"},
        ]

        pool = build_pool(rows, limit=15, exclude_prefixes=["688"])

        self.assertEqual([row["stock_code"] for row in pool], ["000003"])


class DailyPrepareTests(unittest.TestCase):
    def test_candidate_universe_is_automatically_enriched_before_pool_build(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            universe = root / "manual-universe.csv"
            universe.write_text("stock_code\n000001\n", encoding="utf-8")
            args = SimpleNamespace(
                trade_date="2026-07-13",
                run_id="review-run",
                private_dir=root / "private",
                reports_dir=root / "reports",
                state_dir=root / "state",
                skip_market=True,
                offline_market=True,
                skip_article=True,
                article_url=[],
                affected_trade="",
                skip_research_pool=False,
                skip_enrichment=False,
                candidate_universe=universe,
                strict_balance=False,
            )
            commands: list[list[str]] = []
            inputs = {
                "pasted_trades": None,
                "trades_csv": None,
                "journal": None,
                "market_view": None,
                "positions": None,
                "article_files": [],
            }
            with patch.object(daily_prepare, "parse_args", return_value=args), patch.object(
                daily_prepare, "prepare_inputs", return_value=inputs
            ), patch.object(daily_prepare, "run_command", side_effect=commands.append):
                daily_prepare.main()

        self.assertEqual(Path(commands[0][0]).name, "enhance_candidate_universe.py")
        self.assertEqual(commands[0][1], str(universe))
        self.assertEqual(Path(commands[1][0]).name, "research_pool_builder.py")
        self.assertEqual(commands[1][1], str(root / "reports" / "review-run" / "enriched_candidate_universe.csv"))


if __name__ == "__main__":
    unittest.main()
