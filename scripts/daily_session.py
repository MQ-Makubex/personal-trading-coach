#!/usr/bin/env python3
"""Prepare one post-market coaching session from local private inputs."""

from __future__ import annotations

import argparse
import csv
import json
import shutil
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from build_evidence_packet import build_packet
from init_state import DEFAULT_TEMPLATE_DIR, init_state
from ledger_import import import_files
from parse_pasted_trades import parse_text, write_csv
from privacy_guard import scan_csv
from render_markdown import build_html, render_markdown


ROOT = Path(__file__).resolve().parents[1]
REPORTS_DIR = ROOT / "reports"
STATE_DIR = ROOT / "state"
TEMPLATES_DIR = ROOT / "templates"


def now_run_id(trade_date: str) -> str:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_date = trade_date.replace("-", "")
    return f"run_{safe_date}_{stamp}"


def read_optional(path: Path | None) -> str:
    if not path:
        return ""
    return path.read_text(encoding="utf-8").strip()


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def count_csv_rows(path: Path) -> int:
    with path.open(newline="", encoding="utf-8") as handle:
        return sum(1 for _ in csv.DictReader(handle))


def replace_date_and_run(text: str, trade_date: str, run_id: str) -> str:
    return text.replace("YYYY-MM-DD", trade_date).replace("RUN_ID", run_id)


def copy_template(template_name: str, output: Path, trade_date: str, run_id: str) -> None:
    text = (TEMPLATES_DIR / template_name).read_text(encoding="utf-8")
    write_text(output, replace_date_and_run(text, trade_date, run_id))


def render_to_html(markdown_path: Path, html_path: Path, title: str) -> None:
    markdown_text = markdown_path.read_text(encoding="utf-8")
    body = render_markdown(markdown_text)
    write_text(html_path, build_html(title, body))


def build_article_digest(args: argparse.Namespace, run_dir: Path, run_id: str) -> Path:
    template = (TEMPLATES_DIR / "article_digest.md").read_text(encoding="utf-8")
    article_urls = read_optional(args.article_urls)
    article_excerpt = read_optional(args.article_excerpt)
    body = replace_date_and_run(template, args.trade_date, run_id)
    if article_urls or article_excerpt:
        body += "\n## 原始输入摘录\n\n"
        if article_urls:
            body += "### URL\n\n" + article_urls + "\n\n"
        if article_excerpt:
            body += "### 摘录\n\n" + article_excerpt + "\n"
    output = run_dir / "article_digest.md"
    write_text(output, body)
    return output


def build_market_correction(args: argparse.Namespace, run_dir: Path, run_id: str) -> Path:
    template = (TEMPLATES_DIR / "market_correction.md").read_text(encoding="utf-8")
    user_view = read_optional(args.market_view)
    body = replace_date_and_run(template, args.trade_date, run_id)
    if user_view:
        body = body.replace("## 用户原始判断\n\n", "## 用户原始判断\n\n" + user_view + "\n\n")
    output = run_dir / "market_correction.md"
    write_text(output, body)
    return output


def parse_and_check_trades(args: argparse.Namespace, run_dir: Path) -> tuple[Path | None, Path]:
    manifest: dict[str, object] = {"trade_source": None, "privacy_status": "not_run"}
    manifest_path = run_dir / "session_manifest.json"
    if args.pasted_trades and args.trades_csv:
        raise ValueError("只能选择一种交易输入：--pasted-trades 或 --trades-csv。")
    if not args.pasted_trades and not args.trades_csv:
        write_text(manifest_path, json.dumps(manifest, ensure_ascii=False, indent=2))
        return None, manifest_path

    parse_report_path: Path | None = None
    if args.trades_csv:
        trades_csv = run_dir / "input_trades.csv"
        shutil.copyfile(args.trades_csv, trades_csv)
        row_count = count_csv_rows(trades_csv)
        trade_source = "standard_trades_csv"
    else:
        raw_text = args.pasted_trades.read_text(encoding="utf-8")
        rows, parse_report = parse_text(raw_text, args.trade_date)
        trades_csv = run_dir / "pasted_trades_extracted.csv"
        parse_report_path = run_dir / "pasted_trades_parse_report.json"
        write_csv(rows, trades_csv)
        write_text(parse_report_path, json.dumps(parse_report, ensure_ascii=False, indent=2))
        row_count = len(rows)
        trade_source = "pasted_trades"

    privacy_report = scan_csv(trades_csv, strict_balance=args.strict_balance)
    privacy_report_path = run_dir / "privacy_guard_report.json"
    write_text(privacy_report_path, json.dumps(privacy_report, ensure_ascii=False, indent=2))

    manifest.update(
        {
            "trade_source": trade_source,
            "trade_rows": row_count,
            "trades_csv": str(trades_csv),
            "parse_report": str(parse_report_path) if parse_report_path else None,
            "privacy_report": str(privacy_report_path),
            "privacy_status": privacy_report.get("status"),
            "privacy_errors": len(privacy_report.get("errors", [])),
            "privacy_warnings": len(privacy_report.get("warnings", [])),
        }
    )
    write_text(manifest_path, json.dumps(manifest, ensure_ascii=False, indent=2))

    if privacy_report.get("status") != "ok":
        return trades_csv, manifest_path

    import_files([trades_csv], args.state_dir / "account_ledger.csv", args.state_dir / "account_ledger.sqlite", args.state_dir / "account_ledger_summary.md")
    return trades_csv, manifest_path


def build_session_index(run_dir: Path, run_id: str, trade_date: str, trades_csv: Path | None) -> Path:
    lines = [
        f"# 盘后教练 Session - {trade_date}",
        "",
        "## 路径",
        "",
        f"- Run ID: `{run_id}`",
        f"- Run dir: `{run_dir}`",
        f"- 交易事实: `{trades_csv}`" if trades_csv else "- 交易事实: 未提供",
        "- 原始输入不进入 Git；`reports/`、`private/`、`state/` 均被忽略。",
        "",
        "## 已生成文件",
        "",
        "- `evidence_packet.md`",
        "- `article_digest.md`",
        "- `market_correction.md`",
        "- `coach_note.md`",
        "- `research_pool.md`",
        "- `trade_plan.md`",
        "- `daily_session_prompt.md`",
        "",
        "## 下一步",
        "",
        "1. 教练读取 `daily_session_prompt.md` 和证据文件。",
        "2. 直接改写 `coach_note.md`，不要让脚本生成判断。",
        "3. 改写 `research_pool.md`，用户从中选不超过 3 支进入预案。",
        "4. 更新 `state/` 下的连续性文件。",
        "5. 渲染 Markdown 为 HTML。",
    ]
    output = run_dir / "index.md"
    write_text(output, "\n".join(lines) + "\n")
    return output


def prepare_session(args: argparse.Namespace) -> Path:
    run_id = args.run_id or now_run_id(args.trade_date)
    run_dir = args.run_dir or REPORTS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    init_state(DEFAULT_TEMPLATE_DIR, args.state_dir, force=False)
    trades_csv, manifest_path = parse_and_check_trades(args, run_dir)

    article_digest = build_article_digest(args, run_dir, run_id)
    market_correction = build_market_correction(args, run_dir, run_id)

    evidence_args = SimpleNamespace(
        trades=trades_csv,
        trade_date=args.trade_date,
        journal=args.journal,
        market_view=args.market_view,
        articles=article_digest,
        positions=args.positions,
        output=run_dir / "evidence_packet.md",
    )
    write_text(evidence_args.output, build_packet(evidence_args))

    copy_template("coach_note.md", run_dir / "coach_note.md", args.trade_date, run_id)
    copy_template("research_pool.md", run_dir / "research_pool.md", args.trade_date, run_id)
    copy_template("trade_plan.md", run_dir / "trade_plan.md", args.trade_date, run_id)
    copy_template("daily_session_prompt.md", run_dir / "daily_session_prompt.md", args.trade_date, run_id)

    index_md = build_session_index(run_dir, run_id, args.trade_date, trades_csv)
    render_to_html(index_md, run_dir / "index.html", "盘后教练 Session")
    render_to_html(run_dir / "coach_note.md", run_dir / "coach_note.html", "每日教练手记")
    render_to_html(run_dir / "research_pool.md", run_dir / "research_pool.html", "明日研究股票池")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.update(
        {
            "run_id": run_id,
            "run_dir": str(run_dir),
            "trade_date": args.trade_date,
            "evidence_packet": str(evidence_args.output),
            "article_digest": str(article_digest),
            "market_correction": str(market_correction),
            "coach_note": str(run_dir / "coach_note.md"),
            "research_pool": str(run_dir / "research_pool.md"),
            "trade_plan": str(run_dir / "trade_plan.md"),
            "index_html": str(run_dir / "index.html"),
        }
    )
    write_text(manifest_path, json.dumps(manifest, ensure_ascii=False, indent=2))
    return run_dir


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="准备一次盘后教练 session。输出在 reports/run_*，不会进入 Git。")
    parser.add_argument("--trade-date", required=True)
    parser.add_argument("--pasted-trades", type=Path, default=None, help="粘贴交割单文本文件，建议放在 private/。")
    parser.add_argument("--trades-csv", type=Path, default=None, help="已标准化的交易事实 CSV。")
    parser.add_argument("--journal", type=Path, default=None)
    parser.add_argument("--market-view", type=Path, default=None)
    parser.add_argument("--article-urls", type=Path, default=None)
    parser.add_argument("--article-excerpt", type=Path, default=None)
    parser.add_argument("--positions", type=Path, default=None)
    parser.add_argument("--strict-balance", action="store_true")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--run-dir", type=Path, default=None)
    parser.add_argument("--state-dir", type=Path, default=STATE_DIR)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    run_dir = prepare_session(args)
    manifest_path = run_dir / "session_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    print(f"session: {run_dir}")
    print(f"privacy_status: {manifest.get('privacy_status')}")
    print(f"index_html: {run_dir / 'index.html'}")
    print(f"coach_note: {run_dir / 'coach_note.md'}")
    if manifest.get("privacy_status") == "failed":
        print("隐私检查失败：已停止底账导入。详情见 privacy_guard_report.json。")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
