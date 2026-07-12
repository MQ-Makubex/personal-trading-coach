from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import build_personal_site as site  # noqa: E402
from ledger_import import write_sqlite  # noqa: E402


class MarkToMarketTests(unittest.TestCase):
    def test_total_pnl_includes_open_position_without_subtracting_fees_again(self) -> None:
        positions = [
            {
                "stock_code": "300260",
                "stock_name": "新莱应材",
                "open_quantity": 1000,
                "broker_like_cost_basis_after_fees": 96538.30,
            }
        ]
        quotes = {
            "300260": {
                "stock_code": "300260",
                "stock_name": "新莱应材",
                "price": 83.35,
                "date": "2026-07-10",
                "source": "run_20260710_review/market_snapshot.md",
            }
        }

        result = site.mark_to_market_summary(-45430.00, positions, quotes)

        self.assertTrue(result["complete"])
        self.assertEqual(result["realized_pnl"], -45430.00)
        self.assertEqual(result["unrealized_pnl"], -13188.30)
        self.assertEqual(result["total_pnl"], -58618.30)
        self.assertEqual(result["market_value"], 83350.00)
        self.assertEqual(result["quote_date"], "2026-07-10")

    def test_total_pnl_is_unavailable_when_an_open_position_has_no_quote(self) -> None:
        positions = [
            {
                "stock_code": "300260",
                "stock_name": "新莱应材",
                "open_quantity": 1000,
                "broker_like_cost_basis_after_fees": 96538.30,
            }
        ]

        result = site.mark_to_market_summary(-45430.00, positions, {})

        self.assertFalse(result["complete"])
        self.assertIsNone(result["unrealized_pnl"])
        self.assertIsNone(result["total_pnl"])
        self.assertEqual(result["missing_quote_codes"], ["300260"])


class TimelineIndexTests(unittest.TestCase):
    def test_stock_reference_label_caps_dense_code_lists(self) -> None:
        self.assertEqual(site.stock_reference_label([]), "全市场")
        self.assertEqual(site.stock_reference_label(["300260"]), "300260")
        self.assertEqual(
            site.stock_reference_label(["300260", "301171", "301421", "600330"]),
            "300260 301171 301421 等 4 支",
        )

    def test_first_sentence_keeps_dashboard_judgement_compact(self) -> None:
        text = "今天先处理风险，不做预测。后续完整说明不应进入首页风险条。"
        self.assertEqual(site.first_sentence(text), "今天先处理风险，不做预测。")

    def test_markdown_reports_become_canonical_timeline_documents(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reports = root / "reports"
            output = reports / "personal_site"
            run = reports / "run_20260710_review"
            run.mkdir(parents=True)
            (run / "coach_note.md").write_text(
                "# 每日教练手记 - 2026-07-10\n\n300260 新莱应材需要先处理风险，成交金额不是代码：152000。\n",
                encoding="utf-8",
            )
            (run / "coach_note.html").write_text("legacy", encoding="utf-8")
            (run / "research_pool.md").write_text("# 明日研究股票池\n\n只做条件研究。\n", encoding="utf-8")
            (run / "xueqiu_post.md").write_text("# 雪球复盘草稿\n\n今日复盘。\n", encoding="utf-8")
            (run / "finalize_report.json").write_text("{}", encoding="utf-8")

            documents = site.collect_timeline_documents(reports, output)

        self.assertEqual(len(documents), 3)
        self.assertEqual({item["category"] for item in documents}, {"coach_note", "research_pool", "xueqiu_post"})
        coach = next(item for item in documents if item["category"] == "coach_note")
        self.assertEqual(coach["date"], "2026-07-10")
        self.assertEqual(coach["stock_codes"], ["300260"])
        self.assertTrue(coach["document_path"].startswith("documents/"))
        self.assertTrue(coach["document_path"].endswith(".html"))

    def test_latest_local_close_is_extracted_for_open_positions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            reports = Path(tmp) / "reports"
            old_run = reports / "run_20260709_close"
            new_run = reports / "run_20260710_review"
            old_run.mkdir(parents=True)
            new_run.mkdir(parents=True)
            (old_run / "market_snapshot.md").write_text("- 新莱应材: 收盘 90.10，跌 2.00%。\n", encoding="utf-8")
            (new_run / "market_snapshot.md").write_text(
                "# 市场快照\n\n- 新莱应材: 收盘 83.35，跌 12.26%。\n",
                encoding="utf-8",
            )
            positions = [{"stock_code": "300260", "stock_name": "新莱应材"}]

            quotes = site.extract_latest_quotes(reports, positions)

        self.assertEqual(quotes["300260"]["price"], 83.35)
        self.assertEqual(quotes["300260"]["date"], "2026-07-10")
        self.assertEqual(quotes["300260"]["source"], "run_20260710_review/market_snapshot.md")


class WorkbenchArtifactTest(unittest.TestCase):
    def test_explicit_target_date_beats_run_directory_date(self) -> None:
        markdown = "# 2026-07-13 明日交易预案\n\n目标交易日：2026-07-13\n"

        result = site.infer_document_target_date("2026-07-13 明日交易预案", markdown, "2026-07-11")

        self.assertEqual(result, "2026-07-13")

    def test_title_then_content_then_artifact_date_supply_target_date(self) -> None:
        self.assertEqual(site.infer_document_target_date("2026/7/13 明日预案", "", "2026-07-11"), "2026-07-13")
        self.assertEqual(site.infer_document_target_date("明日预案", "适用日期 2026年7月14日", "2026-07-11"), "2026-07-14")
        self.assertEqual(site.infer_document_target_date("明日预案", "无日期", "2026-07-11"), "2026-07-11")

    def test_invalid_calendar_dates_become_unusable_instead_of_raising(self) -> None:
        self.assertEqual(
            site.infer_document_target_date(
                "2026-02-31 明日预案",
                "目标交易日：2026-02-31",
                "2026-07-11",
            ),
            "2026-07-11",
        )
        self.assertEqual(site.infer_document_target_date("明日预案", "", "2026-02-31"), "")

    def test_invalid_target_dates_are_ignored_by_resolution_and_fallback(self) -> None:
        documents = [
            {"category": "trade_plan", "target_date": "2027-99-99", "date": "2026-07-12", "mtime": "2026-07-12 18:00"},
            {"category": "trade_plan", "target_date": "2026-07-10", "date": "2026-07-10", "mtime": "2026-07-10 18:00"},
        ]

        self.assertEqual(site.resolve_workbench_target_date(documents, date(2026, 7, 11)), "2026-07-11")
        selected = site.select_daily_document(documents, "trade_plan", "2026-07-11")
        self.assertEqual(selected["target_date"], "2026-07-10")
        self.assertEqual(selected["document"]["target_date"], "2026-07-10")

    def test_research_pool_parser_stops_at_a_new_table_header(self) -> None:
        markdown = (
            "| 代码 | 名称 | 题材 | 买点 |\n"
            "| --- | --- | --- | --- |\n"
            "| 300001 | 候选1 | 先进封装 | 20日线 |\n"
            "\n"
            "| 代码 | 名称 | 题材 | 买点 |\n"
            "| --- | --- | --- | --- |\n"
            "| 300002 | 后续表格 | 其他 | 突破 |\n"
        )

        rows = site.extract_research_pool_candidates(markdown)

        self.assertEqual([row["stock_code"] for row in rows], ["300001"])

    def test_research_pool_parser_stops_at_a_non_table_boundary(self) -> None:
        markdown = (
            "| 代码 | 名称 | 题材 | 买点 |\n"
            "| --- | --- | --- | --- |\n"
            "| 300001 | 候选1 | 先进封装 | 20日线 |\n"
            "说明：下面是独立的手工记录。\n"
            "| 300002 | 不应读取 | 其他 | 突破 |\n"
        )

        rows = site.extract_research_pool_candidates(markdown)

        self.assertEqual([row["stock_code"] for row in rows], ["300001"])

    def test_research_pool_parser_stops_at_pipe_bearing_prose(self) -> None:
        markdown = (
            "| 代码 | 名称 | 题材 | 买点 |\n"
            "| --- | --- | --- | --- |\n"
            "| 300001 | 候选1 | 先进封装 | 20日线 |\n"
            "说明 | 额外 | 不是表格\n"
            "| 300002 | 不应读取 | 其他 | 突破 |\n"
        )

        rows = site.extract_research_pool_candidates(markdown)

        self.assertEqual([row["stock_code"] for row in rows], ["300001"])

    def test_research_pool_parser_stops_at_short_malformed_pipe_row(self) -> None:
        markdown = (
            "| 代码 | 名称 | 题材 | 买点 |\n"
            "| --- | --- | --- | --- |\n"
            "| 300001 | 候选1 | 先进封装 | 20日线 |\n"
            "| 300002 |\n"
            "| 300003 | 不应读取 | 其他 | 突破 |\n"
        )

        rows = site.extract_research_pool_candidates(markdown)

        self.assertEqual([row["stock_code"] for row in rows], ["300001"])

    def test_missing_target_document_falls_back_and_marks_stale(self) -> None:
        documents = [
            {
                "category": "trade_plan",
                "target_date": "2026-07-10",
                "date": "2026-07-10",
                "mtime": "2026-07-10 18:00",
                "title": "旧预案",
                "document_path": "documents/old-plan.html",
            }
        ]

        selected = site.select_daily_document(documents, "trade_plan", "2026-07-11")

        self.assertEqual(selected["document"]["title"], "旧预案")
        self.assertTrue(selected["stale"])
        self.assertEqual(selected["target_date"], "2026-07-10")
        self.assertEqual(selected["document"]["document_path"], "documents/old-plan.html")

    def test_fallback_uses_latest_valid_document_not_input_order(self) -> None:
        documents = [
            {"category": "research_pool", "target_date": "2026-07-09", "date": "2026-07-11", "mtime": "2026-07-11 20:00"},
            {"category": "research_pool", "target_date": "2026-07-10", "date": "2026-07-10", "mtime": "2026-07-10 18:00"},
        ]

        selected = site.select_daily_document(documents, "research_pool", "2026-07-11")

        self.assertEqual(selected["target_date"], "2026-07-10")

    def test_research_pool_parser_returns_all_fifteen_rows(self) -> None:
        body = "\n".join(
            f"| {index} | {300000 + index:06d} | 候选{index} | 先进封装 | 20日线回踩 |"
            for index in range(1, 16)
        )
        markdown = "| 序号 | 证券代码 | 证券名称 | 题材篮子 | 买点类型 |\n| --- | --- | --- | --- | --- |\n" + body

        rows = site.extract_research_pool_candidates(markdown)

        self.assertEqual(len(rows), 15)
        self.assertEqual(rows[0]["stock_name"], "候选1")
        self.assertEqual(rows[-1]["buy_point"], "20日线回踩")

    def test_short_pool_stays_short_instead_of_inventing_candidates(self) -> None:
        markdown = "| 代码 | 名称 | 题材 | 买点 |\n| --- | --- | --- | --- |\n| 300001 | 候选1 | 先进封装 | 20日线 |"

        self.assertEqual(len(site.extract_research_pool_candidates(markdown)), 1)


class SiteGenerationTests(unittest.TestCase):
    def test_write_site_generates_multiple_pages_and_unified_markdown_details(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sqlite_path = root / "state" / "ledger.sqlite"
            reports = root / "reports"
            state = root / "state"
            output = reports / "personal_site"
            run = reports / "run_20260710_review"
            run.mkdir(parents=True)
            state.mkdir(parents=True, exist_ok=True)

            rows = [
                trade("2026-07-08", "09:30:00", "000001", "已平仓样本", "BUY", 100, 10.00, 1000.00, -1001.00, 1.00),
                trade("2026-07-09", "14:50:00", "000001", "已平仓样本", "SELL", 100, 12.00, 1200.00, 1198.00, 1.00, 1.00),
                trade("2026-07-10", "10:12:00", "300260", "新莱应材", "BUY", 60, 10.00, 600.00, -601.00, 1.00),
            ]
            write_sqlite(rows, sqlite_path)

            (run / "coach_note.md").write_text(
                "# 每日教练手记 - 2026-07-10\n\n## 风险判断\n\n统一渲染验证句。\n",
                encoding="utf-8",
            )
            (run / "research_pool.md").write_text(
                "# 2026-07-11 明日研究股票池\n\n"
                "| 代码 | 名称 | 题材 | 买点 |\n| --- | --- | --- | --- |\n"
                "| 688037 | 芯源微 | 先进封装 | 20日线回踩 |\n\n"
                "688037 仅为候选，不存在底账故事页。\n",
                encoding="utf-8",
            )
            (run / "trade_plan.md").write_text(
                "# 2026-07-11 明日交易预案\n\n目标交易日：2026-07-11\n",
                encoding="utf-8",
            )
            (run / "xueqiu_post.md").write_text("# 雪球复盘草稿\n\n个人复盘。\n", encoding="utf-8")
            (run / "market_snapshot.md").write_text("# 市场快照\n\n- 新莱应材: 收盘 12.00，涨 1.00%。\n", encoding="utf-8")
            for filename in (
                "coach_memory.md",
                "coach_lenses.md",
                "personal_trading_modes.md",
                "research_pool_protocol.md",
                "decision_events.md",
                "position_storylines.md",
            ):
                (state / filename).write_text(f"# {filename}\n\n本地状态。\n", encoding="utf-8")

            written = site.write_site(sqlite_path, reports, output, state_dir=state, as_of_date=date(2026, 7, 11))

            expected_pages = {"index", "timeline", "stories", "ledger", "rules", "data"}
            self.assertTrue(expected_pages.issubset(written))
            for key in expected_pages:
                self.assertTrue(written[key].exists(), key)

            index_html = written["index"].read_text(encoding="utf-8")
            timeline_html = written["timeline"].read_text(encoding="utf-8")
            stories_html = written["stories"].read_text(encoding="utf-8")
            ledger_html = written["ledger"].read_text(encoding="utf-8")
            rules_html = written["rules"].read_text(encoding="utf-8")
            detail_pages = sorted((output / "documents").glob("*.html"))
            stock_pages = sorted((output / "stocks").glob("*.html"))
            data = json.loads(written["data"].read_text(encoding="utf-8"))
            coach_detail = next(page for page in detail_pages if "coach-note" in page.name)
            coach_html = coach_detail.read_text(encoding="utf-8")
            current_stock_html = (output / "stocks" / "300260.html").read_text(encoding="utf-8")
            closed_stock_html = (output / "stocks" / "000001.html").read_text(encoding="utf-8")
            pool_detail = next(page for page in detail_pages if "research-pool" in page.name)
            pool_html = pool_detail.read_text(encoding="utf-8")

        self.assertIn('href="timeline.html"', index_html)
        self.assertIn("总盈亏（含持仓）", index_html)
        self.assertIn("¥316.00", index_html)
        self.assertIn("总费用", index_html)
        self.assertIn("¥4.00", index_html)
        self.assertIn('<span>总费用</span><strong class="mono">¥4.00</strong>', index_html)
        self.assertIn("data-timeline-item", timeline_html)
        self.assertIn("data-calendar-date", timeline_html)
        self.assertIn("当前持仓", stories_html)
        self.assertIn("历史故事", stories_html)
        self.assertIn("data-pnl-app", ledger_html)
        self.assertIn("data-pnl-row", ledger_html)
        self.assertIn('id="pnlSearch"', ledger_html)
        self.assertIn('id="pnlPage"', ledger_html)
        self.assertGreaterEqual(len(detail_pages), 4)
        self.assertGreaterEqual(len(stock_pages), 2)
        self.assertIn("统一渲染验证句", coach_html)
        self.assertIn("../assets/site.css", coach_html)
        self.assertEqual(coach_html.count("<h1>"), 1)
        self.assertEqual(rules_html.count("<h1>"), 1)
        self.assertNotIn("coach_note.html", timeline_html)
        self.assertIn('<span>当前数量</span><strong class="mono">60</strong>', current_stock_html)
        self.assertIn('<span>券商式持仓成本</span><strong class="mono">¥10.02</strong>', current_stock_html)
        self.assertIn("已清仓，不再计算持仓成本", closed_stock_html)
        self.assertNotIn("行情截至 待核验", closed_stock_html)
        self.assertNotIn('href="../stocks/688037.html"', pool_html)
        self.assertIn('<span class="inline-code mono">688037</span>', pool_html)
        self.assertEqual(data["mark_to_market"]["realized_pnl"], 197.00)
        self.assertEqual(data["mark_to_market"]["unrealized_pnl"], 119.00)
        self.assertEqual(data["mark_to_market"]["total_pnl"], 316.00)
        self.assertEqual(data["workbench"]["target_date"], "2026-07-11")
        self.assertFalse(data["workbench"]["trade_plan"]["stale"])
        self.assertEqual(len(data["workbench"]["research_pool"]["candidates"]), 1)
        self.assertEqual(data["workbench"]["research_pool"]["candidates"][0]["stock_code"], "688037")
        self.assertEqual(data["ability"]["closed_cycles"], 1)
        self.assertEqual(len(data["cycles"]), 2)
        self.assertEqual(data["ledger_dataset"]["bounds"], {"minimum": "2026-07-08", "maximum": "2026-07-10"})
        self.assertEqual(len(data["ledger_dataset"]["cycles"]), 2)
        self.assertIn("modes", data["trading_state"])
        self.assertIn("messages", data["discipline_feed"])
        self.assertNotIn(str(root), json.dumps(data, ensure_ascii=False))

    def test_story_order_keeps_current_first_and_closed_most_recent_first(self) -> None:
        trades = [
            {"stock_code": "000001", "stock_name": "旧故事", "trade_date": "2026-01-01", "trade_time": "10:00"},
            {"stock_code": "000002", "stock_name": "新故事", "trade_date": "2026-07-01", "trade_time": "10:00"},
            {"stock_code": "300260", "stock_name": "当前持仓", "trade_date": "2026-06-01", "trade_time": "10:00"},
        ]
        positions = [{"stock_code": "300260", "stock_name": "当前持仓", "open_quantity": 1, "broker_like_cost_basis_after_fees": 10}]

        stories = site.build_stories(trades, positions, [], {}, [], "")

        self.assertEqual([story["stock_code"] for story in stories], ["300260", "000002", "000001"])


class SummaryContractTests(unittest.TestCase):
    def test_summary_stock_count_ignores_non_six_digit_transaction_symbols(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sqlite_path = root / "state" / "ledger.sqlite"
            reports = root / "reports"
            output = reports / "personal_site"
            state = root / "state"
            rows = [
                trade("2026-07-08", "09:30:00", "ABC", "非六位代码", "BUY", 100, 10.00, 1000.00, -1000.00, 0),
                trade("2026-07-08", "10:30:00", "ABC", "非六位代码", "SELL", 100, 10.00, 1000.00, 1000.00, 0),
                trade("2026-07-08", "11:30:00", "000001", "六位代码", "BUY", 100, 10.00, 1000.00, -1000.00, 0),
            ]
            write_sqlite(rows, sqlite_path)

            data = site.build_data(sqlite_path, reports, output, state_dir=state, as_of_date=date(2026, 7, 11))

        self.assertEqual(data["summary"]["stock_count"], 1)


def trade(
    trade_date: str,
    trade_time: str,
    stock_code: str,
    stock_name: str,
    side: str,
    quantity: float,
    price: float,
    amount: float,
    net_amount: float,
    commission: float,
    stamp_tax: float = 0.0,
) -> dict[str, str]:
    return {
        "trade_date": trade_date,
        "trade_time": trade_time,
        "stock_code": stock_code,
        "stock_name": stock_name,
        "side": side,
        "quantity": str(quantity),
        "price": str(price),
        "amount": str(amount),
        "net_amount": str(net_amount),
        "commission": str(commission),
        "stamp_tax": str(stamp_tax),
        "transfer_fee": "0",
        "other_fee": "0",
    }


if __name__ == "__main__":
    unittest.main()
