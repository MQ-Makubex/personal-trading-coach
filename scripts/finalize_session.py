#!/usr/bin/env python3
"""Validate and render a coach session after the LLM writes the notes."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from build_personal_site import write_site as write_personal_site
from evidence_completeness import validate_session_inputs
from xueqiu_watchlist_sync import write_watchlist_manifest


ROOT = Path(__file__).resolve().parents[1]
TEMPLATES_DIR = ROOT / "templates"

REQUIRED_COACH_NOTE_HEADINGS = [
    "今日一句话定性",
    "最重要的一处错误",
    "今日交易事实",
    "交易决策事件复盘",
    "待校正市场判断",
    "持仓故事线更新",
    "个人交易模式更新",
    "明日唯一纪律",
]

PLACEHOLDER_PATTERNS = [
    "一句话判断今天交易行为",
    "先给结论，再给证据",
    "最多一条。必须能在盘中执行。",
    "使用 `templates/research_pool.md` 单独生成。",
    "|  |  |",
]

EMPTY_PLACEHOLDER_LINES = {
    "- 股票:",
    "- 市场状态:",
    "- 做得好的地方:",
    "- 做错的地方:",
    "- 最大教训:",
}

DIRECT_ADVICE_PATTERNS = [
    r"(建议|应该|必须|直接|明天|今日|现在).{0,12}(买入|卖出|清仓|加仓|减仓|满仓|梭哈)",
    r"(买入|卖出|清仓|加仓|减仓).{0,8}(即可|就行|没问题|一定)",
    r"(目标价|必涨|必跌|稳赚|保本|翻倍)",
]

SAFE_NEGATION_TERMS = ["不构成", "不荐股", "不预测", "不提供", "不要", "不能", "不得", "不是", "不作为", "不输出"]


def read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def run_id_from_dir(run_dir: Path) -> str:
    return run_dir.name


def trade_date_from_manifest(run_dir: Path) -> str:
    manifest_path = run_dir / "session_manifest.json"
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            return str(manifest.get("trade_date") or "")
        except json.JSONDecodeError:
            return ""
    return ""


def ensure_state_update_checklist(run_dir: Path, trade_date: str, overwrite: bool = False) -> Path:
    output = run_dir / "state_update_checklist.md"
    if output.exists() and not overwrite:
        return output
    template = (TEMPLATES_DIR / "state_update_checklist.md").read_text(encoding="utf-8")
    text = template.replace("YYYY-MM-DD", trade_date or "YYYY-MM-DD").replace("RUN_ID", run_id_from_dir(run_dir))
    write_text(output, text)
    return output


def line_is_safe_negation(line: str) -> bool:
    return any(term in line for term in SAFE_NEGATION_TERMS)


def scan_direct_advice(path: Path) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    text = read_text(path)
    for line_number, line in enumerate(text.splitlines(), start=1):
        if line_is_safe_negation(line):
            continue
        for pattern in DIRECT_ADVICE_PATTERNS:
            if re.search(pattern, line):
                findings.append(
                    {
                        "file": path.name,
                        "line": line_number,
                        "risk": "direct_trading_instruction",
                        "reason": "疑似直接买卖/仓位指令或收益预测表达。",
                    }
                )
    return findings


def missing_headings(path: Path, headings: list[str]) -> list[str]:
    text = read_text(path)
    return [heading for heading in headings if f"## {heading}" not in text]


def placeholder_hits(path: Path) -> list[str]:
    text = read_text(path)
    hits = [pattern for pattern in PLACEHOLDER_PATTERNS if pattern in text]
    lines = {line.strip() for line in text.splitlines()}
    hits.extend(sorted(EMPTY_PLACEHOLDER_LINES.intersection(lines)))
    return hits


def word_count(path: Path) -> int:
    text = read_text(path)
    chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
    latin_words = len(re.findall(r"[A-Za-z0-9_]+", text))
    return chinese_chars + latin_words


def validate_trade_plan_content(path: Path) -> list[dict[str, Any]]:
    """Require homepage-eligible plans to be stock-specific and actionable."""
    text = read_text(path)
    if not text:
        return []
    if "暂无用户选择" in text or "等待用户选择" in text:
        return []
    findings: list[dict[str, Any]] = []
    if "从 " in text and "中最多选择" in text:
        findings.append(
            {
                "file": path.name,
                "risk": "generic_trade_plan",
                "reason": "交易预案不能继续使用候选篮子，必须先绑定用户选择的具体股票。",
            }
        )
    sections = re.split(r"(?m)^##\s+", text)[1:]
    plan_sections = [section for section in sections if re.match(r"已选个股预案\s*\d+", section.splitlines()[0] if section.splitlines() else "")]
    if not plan_sections and "暂无已选个股预案" not in text:
        findings.append(
            {
                "file": path.name,
                "risk": "missing_stock_specific_plan",
                "reason": "交易预案没有可识别的个股预案章节。",
            }
        )
    stock_pattern = re.compile(r"^\s*-\s*股票\s*[：:]\s*\d{6}\s+.+$", re.MULTILINE)
    summary_pattern = re.compile(r"^\s*-\s*一句话预案\s*[：:]\s*(?!待).+", re.MULTILINE)
    for index, section in enumerate(plan_sections, start=1):
        if not stock_pattern.search(section):
            findings.append({"file": path.name, "risk": "missing_plan_stock", "reason": f"第 {index} 个预案未绑定具体股票。"})
        if not summary_pattern.search(section):
            findings.append({"file": path.name, "risk": "missing_plan_summary", "reason": f"第 {index} 个预案缺少首页一句话预案。"})
        for field in ("触发条件", "操作形式", "失效条件", "止损锚点", "仓位上限"):
            if not re.search(rf"^\s*-\s*{re.escape(field)}\s*[：:]\s*(?!\s*$).+", section, re.MULTILINE):
                findings.append({"file": path.name, "risk": "incomplete_stock_plan", "reason": f"第 {index} 个预案缺少：{field}。"})
    return findings


def validate_session(run_dir: Path) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    required = ["evidence_packet.md", "coach_note.md", "research_pool.md", "xueqiu_post.md"]
    for filename in required:
        if not (run_dir / filename).exists():
            errors.append({"file": filename, "risk": "missing_required_file", "reason": "缺少必要 session 文件。"})

    coach_note = run_dir / "coach_note.md"
    if coach_note.exists():
        for heading in missing_headings(coach_note, REQUIRED_COACH_NOTE_HEADINGS):
            errors.append({"file": "coach_note.md", "risk": "missing_heading", "reason": f"缺少章节：{heading}"})
        hits = placeholder_hits(coach_note)
        if hits:
            warnings.append({"file": "coach_note.md", "risk": "template_placeholder", "reason": "仍包含模板占位内容。", "hits": hits})
        if word_count(coach_note) < 350:
            warnings.append({"file": "coach_note.md", "risk": "too_short", "reason": "手记字数偏少，可能仍未形成有效教练反馈。"})

    for filename in ("coach_note.md", "research_pool.md", "trade_plan.md", "xueqiu_post.md"):
        path = run_dir / filename
        if path.exists():
            errors.extend(scan_direct_advice(path))

    trade_plan = run_dir / "trade_plan.md"
    if trade_plan.exists():
        errors.extend(validate_trade_plan_content(trade_plan))

    research_pool = run_dir / "research_pool.md"
    if research_pool.exists() and "研究池不是买入名单" not in read_text(research_pool):
        warnings.append({"file": "research_pool.md", "risk": "missing_research_boundary", "reason": "建议明确研究池不是买入名单。"})

    xueqiu_post = run_dir / "xueqiu_post.md"
    if xueqiu_post.exists() and "不构成投资建议" not in read_text(xueqiu_post):
        errors.append({"file": "xueqiu_post.md", "risk": "missing_public_boundary", "reason": "雪球草稿缺少不构成投资建议边界。"})

    # Real daily sessions carry a manifest. Their source packet must pass the
    # evidence gate before the coach note can reach the personal site.
    if (run_dir / "session_manifest.json").exists():
        quality = validate_session_inputs(run_dir)
        write_text(run_dir / "data_quality.json", json.dumps(quality, ensure_ascii=False, indent=2))
        errors.extend(
            {
                "file": "data_quality.json",
                "risk": "incomplete_evidence",
                "reason": message,
            }
            for message in quality.get("errors", [])
        )
        warnings.extend(
            {
                "file": "data_quality.json",
                "risk": "evidence_warning",
                "reason": message,
            }
            for message in quality.get("warnings", [])
        )

    return {
        "status": "failed" if errors else "ok",
        "errors": errors,
        "warnings": warnings,
        "checked_at": datetime.now().isoformat(timespec="seconds"),
    }


def finalize(args: argparse.Namespace) -> dict[str, Any]:
    run_dir = args.run_dir.resolve()
    if not run_dir.exists():
        raise SystemExit(f"run dir not found: {run_dir}")

    trade_date = args.trade_date or trade_date_from_manifest(run_dir)
    checklist = ensure_state_update_checklist(run_dir, trade_date, overwrite=args.overwrite_checklist)

    report = validate_session(run_dir)
    research_pool_path = run_dir / "research_pool.md"
    if research_pool_path.exists() and (run_dir / "session_manifest.json").exists():
        sync_manifest_path = run_dir / "xueqiu_watchlist_sync.json"
        sync_manifest = write_watchlist_manifest(
            research_pool_path,
            sync_manifest_path,
            run_id=run_id_from_dir(run_dir),
            trade_date=trade_date,
        )
        report["xueqiu_watchlist_sync_manifest"] = str(sync_manifest_path)
        if sync_manifest["status"] == "blocked_incomplete_pool":
            report["errors"].append(
                {
                    "file": "xueqiu_watchlist_sync.json",
                    "risk": "incomplete_xueqiu_pool",
                    "reason": ", ".join(sync_manifest["errors"]),
                }
            )
            report["status"] = "failed"
    report.update(
        {
            "run_dir": str(run_dir),
            "trade_date": trade_date,
            "state_update_checklist": str(checklist),
            "markdown_outputs": sorted(str(path) for path in run_dir.glob("*.md")),
            "data_quality": str(run_dir / "data_quality.json") if (run_dir / "data_quality.json").exists() else None,
        }
    )
    write_text(run_dir / "finalize_report.json", json.dumps(report, ensure_ascii=False, indent=2))
    if report["status"] == "ok" and not getattr(args, "skip_personal_site", False):
        try:
            personal_site = write_personal_site()
            report["personal_site"] = {key: str(value) for key, value in personal_site.items()}
        except Exception as exc:  # Personal site refresh should not hide the session validation result.
            report["personal_site_error"] = str(exc)
    elif report["status"] != "ok":
        report["personal_site_skipped"] = "session validation failed"
    write_text(run_dir / "finalize_report.json", json.dumps(report, ensure_ascii=False, indent=2))
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="验证一次盘后教练 Markdown session，并刷新个人站。")
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--trade-date", default="")
    parser.add_argument("--overwrite-checklist", action="store_true")
    parser.add_argument("--skip-personal-site", action="store_true", help="不刷新 reports/personal_site。")
    parser.add_argument("--strict", action="store_true", help="warnings 也视为失败。")
    args = parser.parse_args()

    report = finalize(args)
    print(f"finalize_status: {report['status']}")
    print(f"finalize_report: {Path(args.run_dir) / 'finalize_report.json'}")
    print(f"markdown_output_count: {len(report['markdown_outputs'])}")
    if report.get("personal_site"):
        print(f"personal_site: {report['personal_site']['site']}")
    if report.get("personal_site_error"):
        print(f"personal_site_error: {report['personal_site_error']}")
    if report["errors"]:
        print(f"errors: {len(report['errors'])}")
    if report["warnings"]:
        print(f"warnings: {len(report['warnings'])}")
    if report["errors"] or (args.strict and report["warnings"]):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
