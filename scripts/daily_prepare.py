#!/usr/bin/env python3
"""One-command local preparation for a daily coaching session."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
PRIVATE_DIR = ROOT / "private"
REPORTS_DIR = ROOT / "reports"
STATE_DIR = ROOT / "state"


def run_id(trade_date: str) -> str:
    return f"run_{trade_date.replace('-', '')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"


def write_input(path: Path, value: str | None) -> Path | None:
    if value is None or value == "":
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")
    return path


def copy_input(source: Path | None, target: Path) -> Path | None:
    if not source:
        return None
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    return target


def run_command(args: list[str]) -> None:
    subprocess.run([sys.executable, *args], cwd=ROOT, check=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="一条命令准备每日交易教练 run 包。")
    parser.add_argument("--trade-date", default=date.today().isoformat())
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--private-dir", type=Path, default=PRIVATE_DIR)
    parser.add_argument("--reports-dir", type=Path, default=REPORTS_DIR)
    parser.add_argument("--state-dir", type=Path, default=STATE_DIR)

    trade_group = parser.add_mutually_exclusive_group()
    trade_group.add_argument("--pasted-trades-text", default=None)
    trade_group.add_argument("--pasted-trades-file", type=Path, default=None)
    trade_group.add_argument("--trades-csv", type=Path, default=None)

    parser.add_argument("--journal-text", default=None)
    parser.add_argument("--journal-file", type=Path, default=None)
    parser.add_argument("--market-view-text", default=None)
    parser.add_argument("--market-view-file", type=Path, default=None)
    parser.add_argument("--positions-text", default=None)
    parser.add_argument("--positions-file", type=Path, default=None)

    parser.add_argument("--article-text", default=None)
    parser.add_argument("--article-file", type=Path, action="append", default=[])
    parser.add_argument("--article-url", action="append", default=[])
    parser.add_argument("--affected-trade", default="")

    parser.add_argument("--candidate-universe", type=Path, default=None)
    parser.add_argument("--offline-market", action="store_true")
    parser.add_argument("--skip-market", action="store_true")
    parser.add_argument("--skip-article", action="store_true")
    parser.add_argument("--skip-research-pool", action="store_true")
    parser.add_argument("--skip-enrichment", action="store_true", help="仅用于诊断；跳过行情与均线增强会导致完整性校验阻断。")
    parser.add_argument("--strict-balance", action="store_true")
    return parser.parse_args()


def prepare_inputs(args: argparse.Namespace, private_run_dir: Path) -> dict[str, Path | None]:
    pasted_trades = None
    trades_csv = None
    if args.pasted_trades_text is not None:
        pasted_trades = write_input(private_run_dir / "raw_pasted_trades.txt", args.pasted_trades_text)
    elif args.pasted_trades_file:
        pasted_trades = copy_input(args.pasted_trades_file, private_run_dir / "raw_pasted_trades.txt")
    elif args.trades_csv:
        trades_csv = args.trades_csv

    journal = write_input(private_run_dir / "journal.txt", args.journal_text)
    if args.journal_file:
        journal = copy_input(args.journal_file, private_run_dir / "journal.txt")

    market_view = write_input(private_run_dir / "market_view.txt", args.market_view_text)
    if args.market_view_file:
        market_view = copy_input(args.market_view_file, private_run_dir / "market_view.txt")

    positions = write_input(private_run_dir / "positions.txt", args.positions_text)
    if args.positions_file:
        positions = copy_input(args.positions_file, private_run_dir / "positions.txt")

    article_files: list[Path] = []
    if args.article_text:
        article_text_path = write_input(private_run_dir / "article_excerpt.txt", args.article_text)
        if article_text_path:
            article_files.append(article_text_path)
    for index, article_file in enumerate(args.article_file, start=1):
        copied = copy_input(article_file, private_run_dir / f"article_{index:03d}.txt")
        if copied:
            article_files.append(copied)

    return {
        "pasted_trades": pasted_trades,
        "trades_csv": trades_csv,
        "journal": journal,
        "market_view": market_view,
        "positions": positions,
        "article_files": article_files,  # type: ignore[dict-item]
    }


def main() -> int:
    args = parse_args()
    rid = args.run_id or run_id(args.trade_date)
    private_run_dir = args.private_dir / "daily_inputs" / rid
    run_dir = args.reports_dir / rid
    private_run_dir.mkdir(parents=True, exist_ok=True)
    run_dir.mkdir(parents=True, exist_ok=True)

    inputs = prepare_inputs(args, private_run_dir)
    market_snapshot = None
    article_digest = None
    research_pool = None

    if not args.skip_market:
        market_snapshot = run_dir / "market_snapshot.md"
        command = [
            str(SCRIPTS / "market_snapshot.py"),
            "--trade-date",
            args.trade_date,
            "--json",
            str(run_dir / "market_snapshot.json"),
            "--md",
            str(market_snapshot),
        ]
        if inputs["market_view"]:
            command.extend(["--user-view", str(inputs["market_view"])])
        if args.offline_market:
            command.append("--offline")
        run_command(command)

    article_files = inputs["article_files"] if isinstance(inputs["article_files"], list) else []
    if not args.skip_article and (article_files or args.article_url):
        article_digest = run_dir / "article_digest.md"
        command = [
            str(SCRIPTS / "article_digest.py"),
            "--trade-date",
            args.trade_date,
            "--json",
            str(run_dir / "article_digest.json"),
            "--md",
            str(article_digest),
            "--affected-trade",
            args.affected_trade,
        ]
        for article_file in article_files:
            command.extend(["--text-file", str(article_file)])
        for url in args.article_url:
            command.extend(["--url", url])
        run_command(command)

    if not args.skip_research_pool and args.candidate_universe:
        enriched_universe = run_dir / "enriched_candidate_universe.csv"
        if not args.skip_enrichment:
            run_command(
                [
                    str(SCRIPTS / "enhance_candidate_universe.py"),
                    str(args.candidate_universe),
                    "--trade-date",
                    args.trade_date,
                    "--provider",
                    "auto",
                    "--output",
                    str(enriched_universe),
                    "--json",
                    str(run_dir / "enriched_candidate_universe.json"),
                ]
            )
        else:
            enriched_universe = args.candidate_universe
        research_pool = run_dir / "research_pool_candidates.md"
        run_command(
            [
                str(SCRIPTS / "research_pool_builder.py"),
                str(enriched_universe),
                "--trade-date",
                args.trade_date,
                "--csv",
                str(run_dir / "research_pool_candidates.csv"),
                "--json",
                str(run_dir / "research_pool_candidates.json"),
                "--md",
                str(research_pool),
            ]
        )

    daily_command = [
        str(SCRIPTS / "daily_session.py"),
        "--trade-date",
        args.trade_date,
        "--run-id",
        rid,
        "--run-dir",
        str(run_dir),
        "--state-dir",
        str(args.state_dir),
    ]
    if inputs["pasted_trades"]:
        daily_command.extend(["--pasted-trades", str(inputs["pasted_trades"])])
    if inputs["trades_csv"]:
        daily_command.extend(["--trades-csv", str(inputs["trades_csv"])])
    if inputs["journal"]:
        daily_command.extend(["--journal", str(inputs["journal"])])
    if inputs["market_view"]:
        daily_command.extend(["--market-view", str(inputs["market_view"])])
    if inputs["positions"]:
        daily_command.extend(["--positions", str(inputs["positions"])])
    if market_snapshot:
        daily_command.extend(["--market-snapshot", str(market_snapshot)])
    if article_digest:
        daily_command.extend(["--article-digest", str(article_digest)])
    if research_pool:
        daily_command.extend(["--research-pool", str(research_pool)])
    if args.strict_balance:
        daily_command.append("--strict-balance")

    run_command(daily_command)

    print(f"run_id: {rid}")
    print(f"private_inputs: {private_run_dir}")
    print(f"run_dir: {run_dir}")
    print(f"index_markdown: {run_dir / 'index.md'}")
    print(f"next_finalize: python3 scripts/finalize_session.py {run_dir} --strict")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
