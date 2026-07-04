#!/usr/bin/env python3
"""Draft private state-update snippets from a reviewed coach session."""

from __future__ import annotations

import argparse
import json
import re
from datetime import date
from pathlib import Path
from typing import Any


STATE_DRAFTS = {
    "decision_events.md": "state_update_decision_events.md",
    "position_storylines.md": "state_update_position_storylines.md",
    "personal_trading_modes.md": "state_update_personal_trading_modes.md",
    "coach_memory.md": "state_update_coach_memory.md",
    "research_pool_protocol.md": "state_update_research_pool_protocol.md",
    "coach_lenses.md": "state_update_coach_lenses.md",
}


def read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8").strip()


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def section(text: str, heading: str) -> str:
    pattern = re.compile(rf"^##\s+{re.escape(heading)}\s*$", re.MULTILINE)
    match = pattern.search(text)
    if not match:
        return ""
    start = match.end()
    next_match = re.search(r"^##\s+", text[start:], re.MULTILINE)
    end = start + next_match.start() if next_match else len(text)
    return text[start:end].strip()


def compact(*parts: str) -> str:
    return "\n\n".join(part.strip() for part in parts if part and part.strip())


def header(trade_date: str, source: str, target: str) -> str:
    return "\n".join(
        [
            f"# {target} 更新草稿 - {trade_date}",
            "",
            f"Source: `{source}`",
            "",
            "状态：待人工审核",
            "",
            "说明：本文件由已写好的教练手记抽取，不自动代表最终判断。审核后再用 `append_state_update.py` 追加到私有 state。",
            "",
        ]
    )


def draft_decision_events(coach_note: str, trade_date: str, source: str) -> str:
    body = compact(section(coach_note, "今日交易事实"), section(coach_note, "交易决策事件复盘"))
    if not body:
        body = "无法判断：教练手记未提供交易决策事件复盘。"
    return header(trade_date, source, "交易决策事件") + "## 建议追加内容\n\n" + body + "\n"


def draft_storylines(coach_note: str, trade_date: str, source: str) -> str:
    body = section(coach_note, "持仓故事线更新")
    if not body:
        body = "无法判断：教练手记未提供持仓故事线更新。"
    return header(trade_date, source, "持仓故事线") + "## 建议追加内容\n\n" + body + "\n"


def draft_modes(coach_note: str, trade_date: str, source: str) -> str:
    body = section(coach_note, "个人交易模式更新")
    if not body:
        body = "无法判断：教练手记未提供个人交易模式更新。"
    guard = "提醒：单次盈利不得直接升级为可复制；至少 3 次类似证据才允许升级。"
    return header(trade_date, source, "个人交易模式") + "## 建议追加内容\n\n" + body + "\n\n" + guard + "\n"


def draft_memory(coach_note: str, trade_date: str, source: str) -> str:
    body = compact(
        section(coach_note, "今日一句话定性"),
        section(coach_note, "最重要的一处错误"),
        section(coach_note, "明日唯一纪律"),
        section(coach_note, "盘前反问"),
    )
    if not body:
        body = "无法判断：教练手记未提供可沉淀的训练重点。"
    return header(trade_date, source, "教练记忆") + "## 建议追加内容\n\n" + body + "\n"


def draft_research_protocol(research_pool: str, coach_note: str, trade_date: str, source: str) -> str:
    body = compact(
        section(research_pool, "筛选协议版本"),
        section(research_pool, "协议待改进点"),
        section(coach_note, "待校正市场判断"),
        section(coach_note, "明日研究股票池"),
    )
    if not body:
        body = "无法判断：未提供研究池协议或改进点。"
    return header(trade_date, source, "股票池筛选协议") + "## 建议追加内容\n\n" + body + "\n"


def draft_lenses(coach_lens_check: str, article_digest: str, trade_date: str, source: str) -> str:
    body = compact(coach_lens_check, section(article_digest, "叙事污染检查"))
    if not body:
        body = "无法判断：未提供教练镜头检查或文章叙事污染材料。"
    return header(trade_date, source, "教练镜头") + "## 建议追加内容\n\n" + body + "\n"


def load_manifest(run_dir: Path) -> dict[str, Any]:
    manifest_path = run_dir / "session_manifest.json"
    if not manifest_path.exists():
        return {}
    try:
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def build_drafts(run_dir: Path, trade_date: str) -> dict[str, str]:
    source = str(run_dir / "coach_note.md")
    coach_note = read_text(run_dir / "coach_note.md")
    research_pool = read_text(run_dir / "research_pool.md")
    coach_lens_check = read_text(run_dir / "coach_lens_check.md")
    article_digest = read_text(run_dir / "article_digest.md")

    return {
        "state_update_decision_events.md": draft_decision_events(coach_note, trade_date, source),
        "state_update_position_storylines.md": draft_storylines(coach_note, trade_date, source),
        "state_update_personal_trading_modes.md": draft_modes(coach_note, trade_date, source),
        "state_update_coach_memory.md": draft_memory(coach_note, trade_date, source),
        "state_update_research_pool_protocol.md": draft_research_protocol(research_pool, coach_note, trade_date, source),
        "state_update_coach_lenses.md": draft_lenses(coach_lens_check, article_digest, trade_date, source),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="从已写好的教练 run 生成待审核 state 更新片段。")
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--trade-date", default="")
    parser.add_argument("--require-finalize-ok", action="store_true")
    args = parser.parse_args()

    run_dir = args.run_dir.resolve()
    if not run_dir.exists():
        raise SystemExit(f"run dir not found: {run_dir}")

    finalize_report_path = run_dir / "finalize_report.json"
    if args.require_finalize_ok:
        if not finalize_report_path.exists():
            raise SystemExit("缺少 finalize_report.json，请先运行 finalize_session.py。")
        report = json.loads(finalize_report_path.read_text(encoding="utf-8"))
        if report.get("status") != "ok":
            raise SystemExit("finalize_report.json 状态不是 ok。")

    manifest = load_manifest(run_dir)
    trade_date = args.trade_date or str(manifest.get("trade_date") or date.today().isoformat())
    drafts = build_drafts(run_dir, trade_date)
    written: dict[str, str] = {}
    for filename, text in drafts.items():
        path = run_dir / filename
        write_text(path, text)
        written[filename] = str(path)

    update_manifest = {
        "trade_date": trade_date,
        "run_dir": str(run_dir),
        "drafts": written,
        "append_commands": {
            "decision_events.md": f"python3 scripts/append_state_update.py decision_events.md --update {written['state_update_decision_events.md']} --trade-date {trade_date} --source {run_dir / 'coach_note.md'}",
            "position_storylines.md": f"python3 scripts/append_state_update.py position_storylines.md --update {written['state_update_position_storylines.md']} --trade-date {trade_date} --source {run_dir / 'coach_note.md'}",
            "personal_trading_modes.md": f"python3 scripts/append_state_update.py personal_trading_modes.md --update {written['state_update_personal_trading_modes.md']} --trade-date {trade_date} --source {run_dir / 'coach_note.md'}",
            "coach_memory.md": f"python3 scripts/append_state_update.py coach_memory.md --update {written['state_update_coach_memory.md']} --trade-date {trade_date} --source {run_dir / 'coach_note.md'}",
            "research_pool_protocol.md": f"python3 scripts/append_state_update.py research_pool_protocol.md --update {written['state_update_research_pool_protocol.md']} --trade-date {trade_date} --source {run_dir / 'coach_note.md'}",
            "coach_lenses.md": f"python3 scripts/append_state_update.py coach_lenses.md --update {written['state_update_coach_lenses.md']} --trade-date {trade_date} --source {run_dir / 'coach_note.md'}",
        },
        "note": "这些是待审核草稿；审核后再追加到 state。",
    }
    write_text(run_dir / "draft_state_updates_manifest.json", json.dumps(update_manifest, ensure_ascii=False, indent=2))
    print(f"draft_state_updates: {run_dir}")
    print(f"draft_count: {len(written)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
