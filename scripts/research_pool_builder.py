#!/usr/bin/env python3
"""Build a research-only candidate pool from a local universe CSV."""

from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any


OUTPUT_FIELDS = [
    "stock_code",
    "stock_name",
    "theme",
    "score",
    "status",
    "mode_fit",
    "ma_summary",
    "ma_first_hand_score",
    "reasons",
    "risks",
    "trigger_questions",
    "why_not_plan",
]


@dataclass
class ScoreResult:
    score: int
    mode_fit: str
    reasons: list[str]
    risks: list[str]
    trigger_questions: list[str]
    status: str


def to_float(value: Any) -> float | None:
    try:
        if value in (None, "", "--", "-"):
            return None
        return float(str(value).replace(",", ""))
    except ValueError:
        return None


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def relation(close: float | None, anchor: float | None) -> float | None:
    if close is None or not anchor:
        return None
    return (close - anchor) / anchor * 100


def score_row(row: dict[str, str]) -> ScoreResult:
    score = 0
    reasons: list[str] = []
    risks: list[str] = []
    trigger_questions: list[str] = []

    close = to_float(row.get("close"))
    ma200 = to_float(row.get("ma200"))
    ma5 = to_float(row.get("ma5"))
    ma10 = to_float(row.get("ma10"))
    ma20 = to_float(row.get("ma20"))
    ma50 = to_float(row.get("ma50"))
    volume = to_float(row.get("volume"))
    avg_volume20 = to_float(row.get("avg_volume20"))
    change_pct = to_float(row.get("change_pct"))
    theme_strength = to_float(row.get("theme_strength"))
    amount = to_float(row.get("amount"))
    ma_first_hand = to_float(row.get("ma_first_hand_score"))

    theme = row.get("theme", "").strip()
    notes = row.get("notes", "").strip()

    if theme_strength is not None:
        add = max(0, min(25, int(theme_strength)))
        score += add
        reasons.append(f"题材强度分 {add}/25。")
    elif theme:
        score += 12
        reasons.append("提供题材归属，但强度需要教练校正。")
    else:
        risks.append("缺少题材归属，无法判断是否属于强势方向。")

    ma200_rel = relation(close, ma200)
    if ma200_rel is None:
        risks.append("缺少 close 或 ma200，无法验证 200 日线模式。")
    elif -2 <= ma200_rel <= 6:
        score += 25
        reasons.append(f"价格距 200 日线 {ma200_rel:.2f}%，接近可控验证区。")
        trigger_questions.append("是否放量站回/守住 200 日线，而不是只因便宜感试错？")
    elif 6 < ma200_rel <= 15:
        score += 10
        risks.append(f"价格高于 200 日线 {ma200_rel:.2f}%，追高风险上升。")
    elif ma200_rel < -2:
        risks.append(f"价格低于 200 日线 {ma200_rel:.2f}%，不符合上穿/回踩 200 日线模式。")
    else:
        risks.append(f"价格远离 200 日线 {ma200_rel:.2f}%，不适合作为低风险买点训练。")

    if ma_first_hand is not None:
        add = max(0, min(24, int(ma_first_hand)))
        score += add
        if add:
            reasons.append(f"均线先手分 {add}/24。")
    else:
        ma20_rel = relation(close, ma20)
        ma50_rel = relation(close, ma50)
        if ma20_rel is not None and -2 <= ma20_rel <= 3:
            score += 10
            reasons.append(f"价格距 20 日线 {ma20_rel:.2f}%，接近中短线纪律锚点。")
        if ma50_rel is not None and -2 <= ma50_rel <= 5:
            score += 8
            reasons.append(f"价格距 50 日线 {ma50_rel:.2f}%，趋势修复边界较清楚。")
        if ma20_rel is None or ma50_rel is None:
            risks.append("缺少 ma20/ma50，无法完整验证 5/10/20/50/200 均线结构。")

    if row.get("ma_first_hand_reasons"):
        reasons.append(row["ma_first_hand_reasons"])
    if row.get("ma_first_hand_risks"):
        risks.append(row["ma_first_hand_risks"])

    if volume is not None and avg_volume20:
        volume_ratio = volume / avg_volume20
        if volume_ratio >= 1.8:
            score += 20
            reasons.append(f"量能约为 20 日均量 {volume_ratio:.2f} 倍，有放量特征。")
        elif volume_ratio >= 1.2:
            score += 12
            reasons.append(f"量能约为 20 日均量 {volume_ratio:.2f} 倍，有温和放量。")
        elif volume_ratio < 0.8:
            risks.append(f"量能约为 20 日均量 {volume_ratio:.2f} 倍，承接不足。")
    else:
        risks.append("缺少 volume/avg_volume20，无法验证放量。")

    if amount is not None:
        if amount >= 1_000_000_000:
            score += 8
            reasons.append("成交额达到活跃阈值。")
        elif amount < 200_000_000:
            risks.append("成交额偏低，流动性和资金关注度需要谨慎。")

    if change_pct is not None:
        if 0 <= change_pct <= 7:
            score += 8
            reasons.append("当日涨幅未明显过热。")
        elif change_pct > 9:
            risks.append("当日涨幅过大，容易变成追涨而不是计划内买点。")
        elif change_pct < -5:
            risks.append("当日跌幅较大，需要确认不是破位后的便宜感。")

    if close is not None and ma5 is not None and close < ma5:
        risks.append("收盘低于 5 日线，短线强度不足。")
    if close is not None and ma10 is not None and close < ma10:
        risks.append("收盘低于 10 日线，止损/失效锚点需更严格。")
    ma5_rel = relation(close, ma5)
    ma10_rel = relation(close, ma10)
    if ma5_rel is not None and ma5_rel > 8:
        risks.append(f"价格高于 5 日线 {ma5_rel:.2f}%，不再是均线先手买点。")
    if ma10_rel is not None and ma10_rel > 10:
        risks.append(f"价格高于 10 日线 {ma10_rel:.2f}%，追一致风险上升。")

    if any(token in notes for token in ("红牌", "退潮", "破位", "无计划")):
        score -= 30
        risks.append("备注中出现红牌/退潮/破位/无计划等排除特征。")

    mode_fit = "待验证"
    if score >= 70 and not any("红牌" in risk for risk in risks):
        status = "research_candidate"
        mode_fit = "较匹配"
    elif score >= 45:
        status = "observe"
    else:
        status = "excluded"

    if not trigger_questions:
        trigger_questions.append("明日必须先定义触发条件、失效条件和仓位上限，否则不能进入预案。")
    return ScoreResult(score=max(0, score), mode_fit=mode_fit, reasons=reasons, risks=risks, trigger_questions=trigger_questions, status=status)


def excluded_by_prefix(row: dict[str, str], prefixes: list[str]) -> bool:
    code = (row.get("stock_code") or row.get("code") or "").strip()
    return any(code.startswith(prefix) for prefix in prefixes)


def build_pool(rows: list[dict[str, str]], limit: int, exclude_prefixes: list[str]) -> list[dict[str, str]]:
    output = []
    for row in rows:
        if excluded_by_prefix(row, exclude_prefixes):
            continue
        result = score_row(row)
        output.append(
            {
                "stock_code": row.get("stock_code") or row.get("code") or "",
                "stock_name": row.get("stock_name") or row.get("name") or "",
                "theme": row.get("theme", ""),
                "score": str(result.score),
                "status": result.status,
                "mode_fit": result.mode_fit,
                "ma_summary": row.get("ma_summary", ""),
                "ma_first_hand_score": row.get("ma_first_hand_score", ""),
                "reasons": "；".join(result.reasons),
                "risks": "；".join(result.risks),
                "trigger_questions": "；".join(result.trigger_questions),
                "why_not_plan": "研究池不是交易预案；用户需从中选择不超过 3 支，再定义触发、失效、止损和仓位。",
            }
        )
    output.sort(key=lambda item: int(item["score"]), reverse=True)
    return output[:limit]


def write_csv(rows: list[dict[str, str]], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def markdown(rows: list[dict[str, str]], trade_date: str) -> str:
    lines = [
        f"# 明日研究股票池 - {trade_date}",
        "",
        "本股票池用于研究预案训练，不是推荐名单，不构成买入或卖出建议。",
        "",
        "| 股票 | 题材 | 分数 | 状态 | 契合度 | 理由 | 风险 | 进入预案前必须回答 |",
        "| --- | --- | ---: | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        label = f"{row.get('stock_code','')} {row.get('stock_name','')}".strip()
        lines.append(
            "| "
            + " | ".join(
                [
                    label,
                    row.get("theme", ""),
                    row.get("score", ""),
                    row.get("status", ""),
                    row.get("mode_fit", ""),
                    f"{row.get('ma_summary', '')}；{row.get('reasons', '')}".strip("；"),
                    row.get("risks", ""),
                    row.get("trigger_questions", ""),
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## 使用规则",
            "",
            "- 用户最多选择 3 支进入明日交易预案。",
            "- 没有明确触发条件、失效条件、止损锚点和仓位上限，不能从研究池升级为预案。",
            "- 默认剔除 688 科创板股票；如需观察，只能作为板块温度计，不进入候选池。",
            "- 研究池结果需要次日复盘验证，并反馈到 `state/research_pool_protocol.md`。",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="基于本地行情/候选 CSV 生成研究股票池。")
    parser.add_argument("universe_csv", type=Path)
    parser.add_argument("--trade-date", default=date.today().isoformat())
    parser.add_argument("--limit", type=int, default=15)
    parser.add_argument("--exclude-prefix", action="append", default=["688"], help="默认剔除无法交易的代码前缀，可重复传入。")
    parser.add_argument("--include-688", action="store_true", help="允许 688 进入研究池，仅在账户可交易时使用。")
    parser.add_argument("--csv", type=Path, default=Path("reports/research_pool_candidates.csv"))
    parser.add_argument("--json", type=Path, default=Path("reports/research_pool_candidates.json"))
    parser.add_argument("--md", type=Path, default=Path("reports/research_pool_candidates.md"))
    args = parser.parse_args()

    exclude_prefixes = [] if args.include_688 else args.exclude_prefix
    rows = build_pool(read_rows(args.universe_csv), args.limit, exclude_prefixes)
    write_csv(rows, args.csv)
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.md.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps({"trade_date": args.trade_date, "rows": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    args.md.write_text(markdown(rows, args.trade_date), encoding="utf-8")
    print(f"research_pool_csv: {args.csv}")
    print(f"research_pool_md: {args.md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
