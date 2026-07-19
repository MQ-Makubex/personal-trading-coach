from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import date
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import build_personal_site as site  # noqa: E402
from ledger_import import write_sqlite  # noqa: E402


class LocalHrefParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.hrefs: list[str] = []
        self.ids: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        element_id = dict(attrs).get("id")
        if element_id:
            self.ids.add(element_id)
        if tag.lower() != "a":
            return
        href = dict(attrs).get("href")
        if href is not None:
            self.hrefs.append(href)


def assert_generated_site_integrity(test: unittest.TestCase, output: Path) -> None:
    html_files = sorted(output.rglob("*.html"))
    parsers: dict[Path, LocalHrefParser] = {}
    for source in html_files:
        content = source.read_text(encoding="utf-8")
        test.assertNotIn("file://", content, str(source.relative_to(output)))
        test.assertNotIn("/Users/", content, str(source.relative_to(output)))

        parser = LocalHrefParser()
        parser.feed(content)
        parsers[source.resolve()] = parser
        for href in parser.hrefs:
            parsed = urlsplit(href)
            if parsed.scheme.lower() in {"http", "https", "mailto"}:
                continue
            target = (source.parent / unquote(parsed.path)).resolve() if parsed.path else source.resolve()
            test.assertTrue(
                target.exists(),
                f"{source.relative_to(output)} -> {href} (missing target: {target})",
            )
            if parsed.fragment and target.suffix.lower() == ".html":
                target_parser = parsers.get(target)
                if target_parser is None:
                    target_parser = LocalHrefParser()
                    target_parser.feed(target.read_text(encoding="utf-8"))
                    parsers[target] = target_parser
                test.assertIn(
                    unquote(parsed.fragment),
                    target_parser.ids,
                    f"{source.relative_to(output)} -> {href} (missing fragment)",
                )

    site_data = output / "site_data.json"
    content = site_data.read_text(encoding="utf-8")
    test.assertNotIn("file://", content, "site_data.json")
    test.assertNotIn("/Users/", content, "site_data.json")


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

    def test_xueqiu_quote_url_uses_stock_exchange_prefix(self) -> None:
        self.assertEqual(site.xueqiu_quote_url("600036"), "https://xueqiu.com/S/SH600036")
        self.assertEqual(site.xueqiu_quote_url("301396"), "https://xueqiu.com/S/SZ301396")

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

    def test_enriched_candidate_quote_is_used_when_snapshot_is_summary_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            reports = Path(tmp) / "reports"
            run = reports / "run_20260713_close"
            run.mkdir(parents=True)
            (run / "enriched_candidate_universe.csv").write_text(
                "stock_code,stock_name,latest_trade_date,close\n301396,宏景科技,2026-07-13,234.99\n",
                encoding="utf-8",
            )
            quotes = site.extract_latest_quotes(
                reports,
                [{"stock_code": "301396", "stock_name": "宏景科技"}],
            )

        self.assertEqual(quotes["301396"]["price"], 234.99)
        self.assertEqual(quotes["301396"]["date"], "2026-07-13")
        self.assertEqual(quotes["301396"]["source"], "run_20260713_close/enriched_candidate_universe.csv")

    def test_latest_enriched_variant_quote_wins_when_current_pool_omits_position(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            reports = Path(tmp) / "reports"
            old_run = reports / "run_20260714_close"
            new_run = reports / "run_20260715_close"
            old_run.mkdir(parents=True)
            new_run.mkdir(parents=True)
            (old_run / "enriched_candidate_universe.csv").write_text(
                "stock_code,stock_name,latest_trade_date,close\n300604,长川科技,2026-07-14,335.62\n",
                encoding="utf-8",
            )
            (new_run / "enriched_candidate_universe.csv").write_text(
                "stock_code,stock_name,latest_trade_date,close\n000063,中兴通讯,2026-07-15,39.45\n",
                encoding="utf-8",
            )
            (new_run / "enriched_candidate_universe_all.csv").write_text(
                "stock_code,stock_name,latest_trade_date,close\n300604,长川科技,2026-07-15,304.44\n",
                encoding="utf-8",
            )

            quotes = site.extract_latest_quotes(
                reports,
                [{"stock_code": "300604", "stock_name": "长川科技", "last_buy_date": "2026-07-15"}],
            )

        self.assertEqual(quotes["300604"]["price"], 304.44)
        self.assertEqual(quotes["300604"]["date"], "2026-07-15")
        self.assertEqual(
            quotes["300604"]["source"],
            "run_20260715_close/enriched_candidate_universe_all.csv",
        )

    def test_quote_before_last_buy_date_is_not_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            reports = Path(tmp) / "reports"
            run = reports / "run_20260714_close"
            run.mkdir(parents=True)
            (run / "enriched_candidate_universe.csv").write_text(
                "stock_code,stock_name,latest_trade_date,close\n300604,长川科技,2026-07-14,335.62\n",
                encoding="utf-8",
            )

            quotes = site.extract_latest_quotes(
                reports,
                [{"stock_code": "300604", "stock_name": "长川科技", "last_buy_date": "2026-07-15"}],
            )

        self.assertNotIn("300604", quotes)


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

    def test_research_pool_parser_accepts_combined_stock_column(self) -> None:
        markdown = (
            "| 序 | 股票 | 篮子/题材 | 买点类型 |\n"
            "| ---: | --- | --- | --- |\n"
            "| 1 | 300260 新莱应材 | 持仓风险 | 风险修复观察 |\n"
            "| 2 | 603259 药明康德 | 医疗研发外包 | 强轮动回踩 |\n"
        )

        rows = site.extract_research_pool_candidates(markdown)

        self.assertEqual(
            rows,
            [
                {
                    "stock_code": "300260",
                    "stock_name": "新莱应材",
                    "theme": "持仓风险",
                    "buy_point": "风险修复观察",
                    "ma_summary": "待核验",
                },
                {
                    "stock_code": "603259",
                    "stock_name": "药明康德",
                    "theme": "医疗研发外包",
                    "buy_point": "强轮动回踩",
                    "ma_summary": "待核验",
                },
            ],
        )

    def test_research_pool_parser_accepts_dated_ma_header(self) -> None:
        markdown = (
            "| 股票 | 篮子/题材 | 2026-07-14 均线事实 | 观察触发 |\n"
            "| --- | --- | --- | --- |\n"
            "| 301396 宏景科技 | 国产算力 | 收盘 236.60；200 日线远上方 | 站稳 50 日线 |\n"
        )

        rows = site.extract_research_pool_candidates(markdown)

        self.assertEqual(rows[0]["ma_summary"], "收盘 236.60；200 日线远上方")

    def test_trade_plan_home_summary_only_accepts_selected_stock_plans(self) -> None:
        markdown = (
            "# 明日交易预案\n\n"
            "## 已选个股预案 1\n\n"
            "- 股票：301396 宏景科技\n"
            "- 触发条件：站回日内均价线并出现板块扩散\n"
            "- 一句话预案：若算力板块扩散且宏景站回均价线，则小仓观察；跌破 50 日线则按失效处理。\n\n"
            "## 预案 2：医药篮子\n\n"
            "- 股票：从 603259、300347 中选择 1 支\n"
            "- 一句话预案：不应进入首页。\n"
        )

        summaries = site.extract_trade_plan_summaries(markdown)

        self.assertEqual(len(summaries), 1)
        self.assertEqual(summaries[0]["stock_code"], "301396")
        self.assertIn("板块扩散", summaries[0]["summary"])

    def test_short_pool_stays_short_instead_of_inventing_candidates(self) -> None:
        markdown = "| 代码 | 名称 | 题材 | 买点 |\n| --- | --- | --- | --- |\n| 300001 | 候选1 | 先进封装 | 20日线 |"

        self.assertEqual(len(site.extract_research_pool_candidates(markdown)), 1)


def gate(status: str, **overrides: object) -> dict[str, object]:
    result: dict[str, object] = {
        "status": status,
        "target_date": None,
        "reasons": [],
        "next_check": "",
        "source_path": "",
    }
    result.update(overrides)
    return result


class HomepageRendererTests(unittest.TestCase):
    def test_gate_renderer_maps_all_statuses_to_published_copy(self) -> None:
        expected = {
            "pending": "待核验",
            "locked": "风险锁定",
            "observe": "仅观察",
            "eligible": "可进入验证",
        }
        for status, copy in expected.items():
            with self.subTest(status=status):
                html = site.render_coach_state(
                    {"trading_state": {"coach_gate": gate(status), "mode_eligibility": [], "modes": [], "error": None}}
                )

                self.assertIn(copy, html)

    def test_gate_and_eligibility_render_reasons_dates_next_check_and_source(self) -> None:
        html = site.render_coach_state(
            {
                "state_source_documents": {
                    "reports/run-20260711/coach_note.md": "documents/coach-note.html",
                },
                "trading_state": {
                    "coach_gate": gate(
                        "observe",
                        target_date="2026-07-12",
                        reasons=["先处理持仓风险"],
                        next_check="收盘后复核",
                        source_path="reports/run-20260711/coach_note.md",
                    ),
                    "mode_eligibility": [
                        {
                            "mode_id": "mode-a",
                            "status": "eligible",
                            "target_date": "2026-07-13",
                            "reasons": ["已有三次正式样本", '<先核验 & "边界"'],
                            "source_path": "reports/run-20260712/mode_check.md",
                        }
                    ],
                    "modes": [{"id": "mode-a", "name": "模式 A"}],
                    "error": None,
                }
            }
        )

        self.assertIn("先处理持仓风险", html)
        self.assertIn("收盘后复核", html)
        self.assertIn("2026-07-12", html)
        self.assertIn("模式 A", html)
        self.assertIn("可进入验证", html)
        self.assertIn("已有三次正式样本", html)
        self.assertIn("&lt;先核验 &amp; &quot;边界&quot;", html)
        self.assertIn("2026-07-13", html)
        self.assertIn('href="documents/coach-note.html"', html)
        self.assertNotIn('href="reports/run-20260712/mode_check.md"', html)
        self.assertIn("reports/run-20260712/mode_check.md", html)

    def test_discipline_renderer_shows_active_message_metadata_and_escapes_text(self) -> None:
        html = site.render_discipline_feed(
            {
                "messages": [
                    {
                        "level": "red_card",
                        "message": '<不要追涨 & "确认"',
                        "created_at": "2026-07-12T09:30:00+08:00",
                        "source_path": "reports/run-20260712/guard.md",
                    }
                ],
                "error": None,
            },
            {"reports/run-20260712/guard.md": "documents/guard.html"},
        )

        self.assertIn("红牌", html)
        self.assertIn("2026-07-12T09:30:00+08:00", html)
        self.assertIn("&lt;不要追涨 &amp; &quot;确认&quot;", html)
        self.assertIn('href="documents/guard.html"', html)

    def test_empty_and_error_states_are_rendered_explicitly(self) -> None:
        empty_html = site.render_discipline_feed({"messages": [], "error": None})
        error_html = site.render_discipline_feed({"messages": [], "error": "状态数据待修复：JSON 格式无效"})
        coach_error_html = site.render_coach_state(
            {"trading_state": {"coach_gate": gate("pending"), "mode_eligibility": [], "modes": [], "error": "坏状态"}}
        )

        self.assertIn("暂无已发布纪律消息", empty_html)
        self.assertNotIn("状态数据待修复", empty_html)
        self.assertIn("状态数据待修复", error_html)
        self.assertNotIn("暂无已发布纪律消息", error_html)
        self.assertIn("当前没有已发布的模式资格判断", coach_error_html)
        self.assertIn("状态数据待修复", coach_error_html)

    def test_unsafe_state_sources_are_plain_text_in_gate_eligibility_and_discipline(self) -> None:
        unsafe_paths = (
            "javascript:alert(1)",
            "java\nscript:alert(1)",
            "java\tscript:alert(1)",
            "java\rscript:alert(1)",
            "data:text/html,<p>bad</p>",
            "https://example.com/source.md",
            "//example.com/source.md",
            "/absolute/source.md",
            "../private/source.md",
            "..\\private\\source.md",
            "C:\\private\\source.md",
        )
        for unsafe_path in unsafe_paths:
            with self.subTest(unsafe_path=unsafe_path):
                state_html = site.render_coach_state(
                    {
                        "trading_state": {
                            "coach_gate": gate("pending", source_path=unsafe_path),
                            "mode_eligibility": [
                                {
                                    "mode_id": "mode-a",
                                    "status": "observe",
                                    "target_date": "2026-07-12",
                                    "reasons": [],
                                    "source_path": unsafe_path,
                                }
                            ],
                            "modes": [{"id": "mode-a", "name": "模式 A"}],
                            "error": None,
                        }
                    }
                )
                discipline_html = site.render_discipline_feed(
                    {
                        "messages": [
                            {
                                "level": "reminder",
                                "message": "消息",
                                "created_at": "2026-07-12T01:00:00+00:00",
                                "source_path": unsafe_path,
                            }
                        ],
                        "error": None,
                    }
                )
                escaped_path = site.esc(unsafe_path)

                self.assertNotIn(f'href="{escaped_path}"', state_html)
                self.assertNotIn(f'href="{escaped_path}"', discipline_html)
                self.assertIn(escaped_path, state_html)
                self.assertIn(escaped_path, discipline_html)

    def test_safe_relative_href_rejects_ascii_controls_inside_obfuscated_scheme(self) -> None:
        for codepoint in (*range(0x20), 0x7F):
            with self.subTest(codepoint=codepoint):
                self.assertIsNone(site.safe_relative_href(f"java{chr(codepoint)}script:alert(1)"))


class SiteGenerationTests(unittest.TestCase):
    def test_integrity_check_rejects_missing_local_targets_and_fragments(self) -> None:
        for href in ("missing.html", "target.html#missing"):
            with self.subTest(href=href), tempfile.TemporaryDirectory() as tmp:
                output = Path(tmp)
                (output / "index.html").write_text(f'<a href="{href}">broken</a>', encoding="utf-8")
                (output / "target.html").write_text('<div id="present"></div>', encoding="utf-8")
                (output / "site_data.json").write_text("{}", encoding="utf-8")

                with self.assertRaises(AssertionError):
                    assert_generated_site_integrity(self, output)

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
                trade("2026-07-10", "09:31:00", "000001", "已平仓样本", "BUY", 100, 10.00, 1000.00, -1000.00, 0),
                trade("2026-07-10", "09:32:00", "000001", "已平仓样本", "SELL", 100, 10.00, 1000.00, 1000.00, 0),
                trade("2026-07-10", "10:12:00", "300260", "新莱应材", "BUY", 60, 10.00, 600.00, -601.00, 1.00),
            ]
            write_sqlite(rows, sqlite_path)

            (run / "coach_note.md").write_text(
                "# 每日教练手记 - 2026-07-10\n\n## 风险判断\n\n统一渲染验证句。\n",
                encoding="utf-8",
            )
            pool_rows = "\n".join(
                f"| {300000 + index:06d} | 候选{index} | 先进封装 | 20日线回踩 |"
                for index in range(1, 16)
            )
            (run / "research_pool.md").write_text(
                "# 2026-07-11 明日研究股票池\n\n"
                "| 代码 | 名称 | 题材 | 买点 |\n| --- | --- | --- | --- |\n"
                f"{pool_rows}\n\n"
                "300001 仅为候选，不存在底账故事页。\n",
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

            cycle_data = site.build_data(sqlite_path, reports, output, state, date(2026, 7, 11))["cycles"]
            cycle_ids = [str(cycle["cycle_id"]) for cycle in cycle_data]
            (state / "trading_modes.json").write_text(
                json.dumps(
                    {
                        "version": 1,
                        "coach_gate": gate("observe", source_path=f"reports/{run.name}/coach_note.md"),
                        "mode_eligibility": [
                            {
                                "mode_id": "mode-a",
                                "status": "observe",
                                "target_date": "2026-07-11",
                                "reasons": ["等待人工核验"],
                                "source_path": "reports/missing/mode_check.md",
                            }
                        ],
                        "modes": [
                            {
                                "id": "mode-a",
                                "name": "模式 A",
                                "status": "validating",
                                "version": "0.1",
                                "applicable_environment": ["指数震荡，个股结构清晰"],
                                "trigger_conditions": ["盘前条件已经绑定"],
                                "execution_boundaries": ["只执行预案内动作"],
                                "invalidation_conditions": ["触发条件消失"],
                                "max_risk": "一单位风险",
                                "next_validation_requirement": "人工复核三个正式样本",
                                "samples": [
                                    {
                                        "cycle_id": cycle_id,
                                        "evidence_type": "formal",
                                        "execution_result": "planned",
                                        "evidence_direction": "support",
                                        "note": "按计划执行",
                                        "source_paths": [f"reports/{run.name}/coach_note.md"],
                                    }
                                    for cycle_id in cycle_ids
                                ]
                                + [
                                    {
                                        "cycle_id": "missing-historical-cycle",
                                        "evidence_type": "historical_reference",
                                        "execution_result": "insufficient",
                                        "evidence_direction": "indeterminate",
                                        "note": "待修复历史关联",
                                        "source_paths": ["reports/missing/sample_evidence.md"],
                                    }
                                ],
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (state / "discipline_feed.json").write_text(
                json.dumps(
                    {
                        "version": 1,
                        "messages": [
                            {
                                "id": "fixture-reminder",
                                "status": "active",
                                "level": "reminder",
                                "scope": "global",
                                "stock_code": "",
                                "mode_id": "",
                                "message": "复核来源链接",
                                "source_path": f"reports/{run.name}/coach_note.md",
                                "effective_at": "2026-07-01T00:00:00+00:00",
                                "expires_at": "",
                                "created_at": "2026-07-01T00:00:00+00:00",
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (state / "mentor_lenses.json").write_text(
                json.dumps(
                    {
                        "version": 1,
                        "mentor": {
                            "id": "bingbing-xiaomei",
                            "name": "冰冰小美",
                            "profile_url": "https://xueqiu.com/u/7143769715",
                            "summary": "风险优先的宏观产业交易视角。",
                            "updated_at": "2026-07-19",
                            "notice": "基于公开表达整理，非本人授权或收益背书。",
                            "principles": [
                                {
                                    "name": "风险先于机会",
                                    "summary": "先判断环境，再决定仓位。",
                                    "source_url": "https://xueqiu.com/7143769715/319174752",
                                }
                            ],
                            "modes": [
                                {
                                    "id": "macro-risk-gate",
                                    "name": "宏观风险闸门",
                                    "horizon": "portfolio",
                                    "evidence": "behavior",
                                    "environment": ["海外与流动性风险升高"],
                                    "signals": ["汇率、利率、融资余额"],
                                    "actions": ["降低总仓位"],
                                    "exit_conditions": ["风险停止扩散"],
                                    "anti_patterns": ["用个股利好覆盖系统风险"],
                                    "source_urls": ["https://xueqiu.com/7143769715/396191476"],
                                }
                            ],
                            "risk_prompts": [
                                {
                                    "id": "risk-first",
                                    "text": "驱动没有修复，反弹也可能只是情绪回摆。先把仓位放到能承受判断错误的位置。",
                                    "source_url": "https://xueqiu.com/7143769715/319174752",
                                }
                            ],
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            written = site.write_site(sqlite_path, reports, output, state_dir=state, as_of_date=date(2026, 7, 11))
            assert_generated_site_integrity(self, output)

            expected_pages = {"index", "timeline", "stories", "modes", "mentor", "ledger", "rules", "data"}
            self.assertTrue(expected_pages.issubset(written))
            for key in expected_pages:
                self.assertTrue(written[key].exists(), key)

            index_html = written["index"].read_text(encoding="utf-8")
            timeline_html = written["timeline"].read_text(encoding="utf-8")
            stories_html = written["stories"].read_text(encoding="utf-8")
            modes_html = written["modes"].read_text(encoding="utf-8")
            mentor_html = written["mentor"].read_text(encoding="utf-8")
            ledger_html = written["ledger"].read_text(encoding="utf-8")
            ledger_js_exists = (output / "assets" / "ledger.js").exists()
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
        self.assertIn('href="modes.html"', index_html)
        self.assertIn('href="mentor.html"', index_html)
        self.assertIn("交易模式", modes_html)
        self.assertIn('data-mode-app', modes_html)
        self.assertIn('data-mode-filter="validating"', modes_html)
        self.assertIn('id="mode-mode-a"', modes_html)
        self.assertIn("3 / 3", modes_html)
        self.assertIn("已达人工评审门槛", modes_html)
        self.assertIn('正式样本</h3></div><span class="count-label">3 项', modes_html)
        self.assertIn('历史参考</h3></div><span class="count-label">1 项', modes_html)
        self.assertIn("周期关联待修复", modes_html)
        self.assertIn("missing-historical-cycle", modes_html)
        self.assertIn(f'href="documents/{coach_detail.name}"', modes_html)
        self.assertIn(f"reports/{run.name}/coach_note.md", modes_html)
        self.assertIn("reports/missing/sample_evidence.md", modes_html)
        self.assertNotIn('href="reports/missing/sample_evidence.md"', modes_html)
        closed_cycle_id = next(
            str(cycle["cycle_id"])
            for cycle in cycle_data
            if cycle["stock_code"] == "000001"
        )
        self.assertIn(f'href="stocks/000001.html?cycle={closed_cycle_id}"', modes_html)
        self.assertNotIn("自动升级", modes_html)
        self.assertIn("冰冰小美交易视角", mentor_html)
        self.assertIn('data-mentor-app', mentor_html)
        self.assertIn('id="mentor-mode-macro-risk-gate"', mentor_html)
        self.assertIn('data-mentor-filter="portfolio"', mentor_html)
        self.assertIn("行为证据", mentor_html)
        self.assertIn("视角改写 · 非本人原话", index_html)
        self.assertIn("驱动没有修复", index_html)
        self.assertIn("总盈亏（含持仓）", index_html)
        self.assertIn("¥316.00", index_html)
        self.assertIn("总费用", index_html)
        self.assertIn("¥4.00", index_html)
        self.assertIn('<span>总费用</span><strong class="mono">¥4.00</strong>', index_html)
        self.assertIn("data-account-total", index_html)
        self.assertIn("data-ability-rail", index_html)
        self.assertIn("data-coach-gate", index_html)
        self.assertIn("data-mode-eligibility", index_html)
        self.assertEqual(index_html.count("data-pool-row"), 15)
        self.assertIn("data-pool-scroll", index_html)
        self.assertIn("data-discipline-feed", index_html)
        self.assertIn("复核来源链接", index_html)
        self.assertGreaterEqual(index_html.count(f'href="documents/{coach_detail.name}"'), 2)
        self.assertNotIn('href="reports/missing/mode_check.md"', index_html)
        self.assertIn("reports/missing/mode_check.md", index_html)
        self.assertIn("交易股票数", index_html)
        self.assertIn("完整周期", index_html)
        self.assertIn("平均持股自然日", index_html)
        self.assertNotIn("最近训练日", index_html)
        self.assertIn("data-timeline-item", timeline_html)
        self.assertIn("data-calendar-date", timeline_html)
        self.assertIn("当前持仓", stories_html)
        self.assertIn("历史故事", stories_html)
        self.assertTrue(ledger_js_exists)
        self.assertIn('src="assets/ledger.js"', ledger_html)
        self.assertIn('id="ledgerData"', ledger_html)
        self.assertIn("data-current-account-facts", ledger_html)
        self.assertLess(ledger_html.index("data-current-account-facts"), ledger_html.index("data-ledger-app"))
        self.assertIn('data-ledger-prev aria-label="上一周期" title="上一周期"', ledger_html)
        self.assertIn('data-ledger-next aria-label="下一周期" title="下一周期"', ledger_html)
        for grain in ("all", "day", "week", "month", "year", "custom"):
            self.assertIn(f'data-ledger-grain="{grain}"', ledger_html)
        for target in (
            "data-period-realized",
            "data-period-cycles",
            "data-period-win-rate",
            "data-period-profit-factor",
            "data-period-fees",
            "data-period-stocks",
            "data-ledger-trades",
            "data-ledger-stocks",
        ):
            self.assertIn(target, ledger_html)
        self.assertIn('id="pnlSearch"', ledger_html)
        self.assertIn('id="pnlPage"', ledger_html)
        self.assertGreaterEqual(len(detail_pages), 4)
        self.assertGreaterEqual(len(stock_pages), 2)
        self.assertIn("统一渲染验证句", coach_html)
        self.assertIn("../assets/site.css", coach_html)
        self.assertEqual(coach_html.count("<h1>"), 1)
        self.assertEqual(rules_html.count("<h1>"), 1)
        self.assertNotIn("coach_note.html", timeline_html)
        self.assertIn('<header class="stock-lifetime">', current_stock_html)
        self.assertIn('class="stock-cycle-layout" data-stock-cycles', current_stock_html)
        self.assertIn('data-cycle-option="', current_stock_html)
        self.assertIn('<dt>当前数量</dt><dd class="mono">60</dd>', current_stock_html)
        self.assertIn('<dt>当前成本</dt><dd class="mono">¥10.02</dd>', current_stock_html)
        self.assertIn('<dt>最新价格</dt><dd class="mono">¥12.00</dd>', current_stock_html)
        self.assertIn('<dt>浮动盈亏</dt><dd class="mono gain">¥119.00</dd>', current_stock_html)
        self.assertIn('<dt>最终平仓</dt><dd class="mono">进行中</dd>', current_stock_html)
        self.assertIn('<dt>最终平仓</dt><dd class="mono">2026-07-09</dd>', closed_stock_html)
        self.assertIn('<dt>持股自然日</dt><dd class="mono">1</dd>', closed_stock_html)
        self.assertIn('<dt>总买入成本</dt><dd class="mono">¥1,001.00</dd>', closed_stock_html)
        self.assertIn('<dt>净卖出收入</dt><dd class="mono">¥1,198.00</dd>', closed_stock_html)
        self.assertNotIn("成交生命周期", current_stock_html)
        self.assertNotIn('href="../stocks/300001.html"', pool_html)
        self.assertIn('<span class="inline-code mono">300001</span>', pool_html)
        self.assertEqual(data["mark_to_market"]["realized_pnl"], 197.00)
        self.assertEqual(data["mark_to_market"]["unrealized_pnl"], 119.00)
        self.assertEqual(data["mark_to_market"]["total_pnl"], 316.00)
        self.assertEqual(data["workbench"]["target_date"], "2026-07-11")
        self.assertFalse(data["workbench"]["trade_plan"]["stale"])
        self.assertEqual(len(data["workbench"]["research_pool"]["candidates"]), 15)
        self.assertEqual(data["workbench"]["research_pool"]["candidates"][0]["stock_code"], "300001")
        self.assertEqual(data["ability"]["closed_cycles"], 2)
        self.assertEqual(len(data["cycles"]), 3)
        self.assertEqual(data["ledger_dataset"]["bounds"], {"minimum": "2026-07-08", "maximum": "2026-07-10"})
        self.assertEqual(len(data["ledger_dataset"]["cycles"]), 3)
        self.assertIn("modes", data["trading_state"])
        self.assertIn("messages", data["discipline_feed"])
        self.assertEqual(
            data["state_source_documents"][f"reports/{run.name}/coach_note.md"],
            f"documents/{coach_detail.name}",
        )
        self.assertNotIn(str(root), json.dumps(data, ensure_ascii=False))
        self.assertNotIn("/Users/", json.dumps(data, ensure_ascii=False))

    def test_mode_archive_empty_state_uses_only_structured_mode_data(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sqlite_path = root / "state" / "ledger.sqlite"
            reports = root / "reports"
            state = root / "state"
            output = reports / "personal_site"
            reports.mkdir(parents=True)
            state.mkdir(parents=True)
            write_sqlite([], sqlite_path)
            (state / "personal_trading_modes.md").write_text(
                "# 不应解析的模式\n\n这里写着三个正式样本，也不能生成结构化模式。\n",
                encoding="utf-8",
            )
            (state / "trading_modes.json").write_text(
                json.dumps(
                    {
                        "version": 1,
                        "coach_gate": gate("pending"),
                        "mode_eligibility": [],
                        "modes": [],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            written = site.write_site(sqlite_path, reports, output, state_dir=state, as_of_date=date(2026, 7, 11))
            modes_html = written["modes"].read_text(encoding="utf-8")

        self.assertIn("尚未建立结构化交易模式", modes_html)
        self.assertIn("0 / 3", modes_html)
        self.assertNotIn("不应解析的模式", modes_html)

    def test_homepage_marks_fallback_plan_with_source_date_and_link(self) -> None:
        data = {
            "summary": {"latest_trade_date": "2026-07-11", "stock_count": 0, "total_fees": 0},
            "mark_to_market": {
                "complete": True,
                "quote_date": "2026-07-11",
                "missing_quote_codes": [],
                "realized_pnl": 0,
                "unrealized_pnl": 0,
                "total_pnl": 0,
            },
            "ability": {
                "closed_cycles": 0,
                "win_rate": None,
                "win_rate_state": "no_samples",
                "average_payoff_ratio": None,
                "average_payoff_ratio_state": "no_samples",
                "profit_factor": None,
                "profit_factor_state": "no_samples",
                "expectancy": None,
                "average_holding_days": None,
                "median_holding_days": None,
            },
            "trading_state": {
                "coach_gate": {
                    "status": "pending",
                    "target_date": None,
                    "reasons": [],
                    "next_check": "",
                    "source_path": "",
                },
                "mode_eligibility": [],
                "error": None,
            },
            "discipline_feed": {"messages": [], "error": None},
            "open_positions": [],
            "documents": [],
            "latest_by_category": {},
            "workbench": {
                "target_date": "2026-07-12",
                "trade_plan": {
                    "target_date": "2026-07-10",
                    "stale": True,
                    "document": {
                        "title": "旧交易预案",
                        "summary": "沿用前次风险边界。",
                        "document_path": "documents/old-plan.html",
                    },
                },
                "research_pool": {"target_date": "", "stale": False, "document": None, "candidates": []},
            },
        }

        index_html = site.render_home(data)

        self.assertIn("2026-07-10", index_html)
        self.assertIn("可能过期", index_html)
        self.assertIn('href="documents/old-plan.html"', index_html)

    def test_story_order_keeps_current_first_and_closed_most_recent_first(self) -> None:
        def cycle(cycle_id: str, code: str, first_buy: str, close_date: str = "", holding_days: int | None = None) -> dict[str, object]:
            status = "closed" if close_date else "open"
            return {
                "cycle_id": cycle_id,
                "status": status,
                "stock_code": code,
                "stock_name": "周期样本" if code == "300260" else f"故事{code}",
                "first_buy_date": first_buy,
                "first_buy_time": "09:30:00",
                "last_buy_date": first_buy,
                "last_buy_time": "10:00:00",
                "close_date": close_date,
                "close_time": "14:50:00" if close_date else "",
                "holding_days": holding_days,
                "buy_quantity": 100,
                "sell_quantity": 100 if close_date else 0,
                "open_quantity": 0 if close_date else 100,
                "buy_cost_after_fees": 1001,
                "sell_proceeds_after_fees": 1098 if close_date else 0,
                "rolling_cost_basis_after_fees": 0 if close_date else 1001,
                "realized_pnl_after_fees": 97 if close_date else None,
                "return_pct": 9.69 if close_date else None,
                "events": [
                    {
                        "trade_date": first_buy,
                        "trade_time": "09:30:00",
                        "side": "BUY",
                        "quantity": 100,
                        "price": 10,
                        "amount": 1000,
                        "net_amount": -1001,
                        "fees": 1,
                    }
                ],
            }

        cycles = [
            cycle("closed-old", "300260", "2026-01-01", "2026-01-03", 2),
            cycle("open-cycle", "300260", "2026-07-01"),
            cycle("closed-new", "300260", "2026-06-01", "2026-06-05", 4),
            cycle("closed-only-old", "000002", "2026-03-01", "2026-03-02", 1),
            cycle("closed-only-new", "000002", "2026-05-01", "2026-05-03", 2),
            cycle("older-stock", "000001", "2026-02-01", "2026-02-02", 1),
        ]
        positions = [
            {
                "stock_code": "300260",
                "stock_name": "周期样本",
                "open_quantity": 100,
                "broker_like_cost_basis_after_fees": 1001,
            }
        ]
        realized_rows = [
            {"stock_code": "300260", "stock_name": "周期样本", "broker_like_total_pnl_after_fees": 194},
            {"stock_code": "000002", "stock_name": "故事000002", "broker_like_total_pnl_after_fees": 194},
            {"stock_code": "000001", "stock_name": "故事000001", "broker_like_total_pnl_after_fees": 97},
        ]
        quotes = {"300260": {"price": 12, "date": "2026-07-12", "source": "run/market_snapshot.md"}}
        documents = [
            {
                "title": "周期证据",
                "category_label": "教练手记",
                "date": "2026-06-03",
                "target_date": "2026-06-03",
                "document_path": "documents/cycle-evidence.html",
                "stock_codes": ["300260"],
                "search_text": "周期样本",
                "summary": "周期内证据。",
            },
            {
                "title": "周期外证据",
                "category_label": "教练手记",
                "date": "2025-12-31",
                "target_date": "2025-12-31",
                "document_path": "documents/outside.html",
                "stock_codes": ["300260"],
                "search_text": "周期样本",
                "summary": "周期外证据。",
            },
        ]
        trading_state = {
            "modes": [
                {
                    "id": "mode-a",
                    "name": "模式 A",
                    "samples": [
                        {
                            "cycle_id": "closed-new",
                            "execution_result": "planned",
                            "evidence_direction": "support",
                            "evidence_type": "formal",
                            "note": "按计划执行",
                            "source_paths": ["reports/run/coach_note.md"],
                        }
                    ],
                }
            ]
        }

        stories = site.build_stories(cycles, positions, realized_rows, quotes, documents, trading_state, "")

        self.assertEqual([story["stock_code"] for story in stories], ["300260", "000002", "000001"])
        story = stories[0]
        self.assertEqual(story["lifetime"]["closed_cycles"], 2)
        self.assertEqual(story["lifetime"]["average_holding_days"], 3.0)
        self.assertEqual(story["default_cycle_id"], "open-cycle")
        self.assertEqual([row["cycle_id"] for row in story["cycles"]], ["open-cycle", "closed-new", "closed-old"])
        self.assertEqual(story["cycles"][1]["linked_modes"][0]["id"], "mode-a")
        self.assertEqual([item["title"] for item in story["cycles"][1]["linked_documents"]], ["周期证据"])
        self.assertEqual(stories[1]["default_cycle_id"], "closed-only-new")

        stock_html = site.render_stock(story, "2026-07-12 12:00:00")
        self.assertIn('<header class="stock-lifetime">', stock_html)
        self.assertIn('class="stock-cycle-layout" data-stock-cycles data-default-cycle="open-cycle"', stock_html)
        self.assertIn('data-cycle-option="open-cycle"', stock_html)
        self.assertEqual(stock_html.count('data-cycle-panel="'), 3)
        self.assertEqual(stock_html.count('class="cycle-detail" data-cycle-panel="open-cycle"'), 1)
        self.assertIn('data-cycle-panel="closed-new" hidden', stock_html)
        for label in ("持股自然日", "财务结果", "周期盈亏", "执行结果", "证据方向", "成交事件", "关联训练记录"):
            self.assertIn(label, stock_html)
        self.assertIn('<span>中位持股自然日</span><strong class="mono">3</strong>', stock_html)
        self.assertIn('href="../modes.html#mode-mode-a"', stock_html)
        self.assertIn('href="../documents/cycle-evidence.html"', stock_html)


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
