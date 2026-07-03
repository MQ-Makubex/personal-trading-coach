#!/usr/bin/env python3
"""Digest article inputs and flag narrative-pollution risks for coach review."""

from __future__ import annotations

import argparse
import html
import json
import re
import urllib.request
from datetime import date
from pathlib import Path
from typing import Any


KEY_VIEWPOINT_TERMS = ["主线", "题材", "风险", "止损", "仓位", "低吸", "高开", "防守", "科技", "医药", "AI", "政策", "流动性"]


def request_text(url: str, timeout: int = 12) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 personal-trading-coach/0.1",
            "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read(2 * 1024 * 1024)
        charset = response.headers.get_content_charset() or "utf-8"
    return raw.decode(charset, errors="replace")


def html_to_text(raw: str) -> tuple[str, str]:
    title_match = re.search(r"<title[^>]*>(.*?)</title>", raw, re.IGNORECASE | re.DOTALL)
    title = cleanup_text(title_match.group(1)) if title_match else ""
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", raw)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return title, cleanup_text(text)


def cleanup_text(text: str) -> str:
    text = html.unescape(text or "")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[。！？!?；;])\s*", text)
    return [part.strip() for part in parts if len(part.strip()) >= 8]


def summarize(text: str, max_sentences: int) -> str:
    sentences = split_sentences(text)
    selected: list[str] = []
    for sentence in sentences:
        if any(term in sentence for term in KEY_VIEWPOINT_TERMS):
            selected.append(sentence)
        if len(selected) >= max_sentences:
            break
    if not selected:
        selected = sentences[:max_sentences]
    summary = " ".join(selected)
    return summary[:900]


def pollution_check(text: str, affected_trade: str) -> dict[str, Any]:
    return {
        "reinforces_existing_position_bias": {
            "flag": bool(re.search(r"(坚定|拿住|别怕|不用怕|信仰|长期看好|必然|肯定)", text)),
            "reason": "文本出现强化持仓信念或确定性表达。" if re.search(r"(坚定|拿住|别怕|不用怕|信仰|长期看好|必然|肯定)", text) else "未识别到明显强化持仓偏见表达。",
        },
        "may_trigger_chasing": {
            "flag": bool(re.search(r"(追|突破|加速|新高|主升|抢|不等回调)", text)),
            "reason": "文本出现追涨或加速叙事。" if re.search(r"(追|突破|加速|新高|主升|抢|不等回调)", text) else "未识别到明显追涨诱因。",
        },
        "has_verifiable_facts": {
            "flag": bool(re.search(r"(\d{4}|\d+%|公告|财报|成交额|政策|数据|日期|同比|环比)", text)),
            "reason": "文本包含数字、公告、财报、政策或数据类可验证元素。" if re.search(r"(\d{4}|\d+%|公告|财报|成交额|政策|数据|日期|同比|环比)", text) else "缺少明显可验证事实。",
        },
        "may_be_emotional_comfort": {
            "flag": bool(re.search(r"(别慌|不用担心|安慰|情绪|信心|熬过去|拿得住)", text)),
            "reason": "文本可能提供情绪安慰。" if re.search(r"(别慌|不用担心|安慰|情绪|信心|熬过去|拿得住)", text) else "未识别到明显情绪安慰。",
        },
        "affected_today_action": {
            "flag": bool(affected_trade.strip()),
            "reason": affected_trade.strip() or "用户未声明影响当天交易动作。",
        },
    }


def digest_source(label: str, source_type: str, text: str, affected_trade: str, max_sentences: int) -> dict[str, Any]:
    title = ""
    body = text
    if source_type == "url":
        title, body = html_to_text(text)
    cleaned = cleanup_text(body)
    return {
        "source_type": source_type,
        "source": label,
        "title": title or Path(label).stem,
        "summary": summarize(cleaned, max_sentences),
        "pollution_check": pollution_check(cleaned, affected_trade),
        "full_text_saved": False,
        "note": "输出不保存全文，只保存摘要和叙事污染检查。",
    }


def markdown(report: dict[str, Any]) -> str:
    lines = [
        f"# 文章观点与叙事污染检查 - {report.get('trade_date')}",
        "",
        "本文件用于教练校正交易叙事，不替代交易事实，不构成买卖建议。",
        "",
    ]
    for item in report.get("items", []):
        lines.extend(
            [
                f"## {item.get('title') or item.get('source')}",
                "",
                f"- 来源: {item.get('source')}",
                f"- 类型: {item.get('source_type')}",
                f"- 不保存全文: {item.get('full_text_saved') is False}",
                "",
                "### 摘要",
                "",
                item.get("summary") or "无法判断",
                "",
                "### 叙事污染检查",
                "",
                "| 检查项 | 标记 | 原因 |",
                "| --- | --- | --- |",
            ]
        )
        for key, value in (item.get("pollution_check") or {}).items():
            lines.append(f"| {key} | {value.get('flag')} | {value.get('reason')} |")
        lines.append("")
    return "\n".join(lines)


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for url in args.url:
        try:
            raw = request_text(url)
            items.append(digest_source(url, "url", raw, args.affected_trade, args.max_sentences))
        except Exception as exc:  # noqa: BLE001
            items.append(
                {
                    "source_type": "url",
                    "source": url,
                    "title": "",
                    "summary": "无法抓取 URL 内容。",
                    "pollution_check": pollution_check("", args.affected_trade),
                    "full_text_saved": False,
                    "error": exc.__class__.__name__,
                }
            )
    for text_file in args.text_file:
        raw = text_file.read_text(encoding="utf-8")
        items.append(digest_source(str(text_file), "text_file", raw, args.affected_trade, args.max_sentences))
    return {"trade_date": args.trade_date, "items": items, "full_text_saved": False}


def main() -> int:
    parser = argparse.ArgumentParser(description="生成文章观点摘要和叙事污染检查。")
    parser.add_argument("--trade-date", default=date.today().isoformat())
    parser.add_argument("--url", action="append", default=[])
    parser.add_argument("--text-file", action="append", type=Path, default=[])
    parser.add_argument("--affected-trade", default="", help="用户声明文章是否影响当天交易动作。")
    parser.add_argument("--max-sentences", type=int, default=5)
    parser.add_argument("--json", type=Path, default=Path("reports/article_digest.json"))
    parser.add_argument("--md", type=Path, default=Path("reports/article_digest.md"))
    args = parser.parse_args()

    if not args.url and not args.text_file:
        raise SystemExit("请提供至少一个 --url 或 --text-file。")
    report = build_report(args)
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.md.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    args.md.write_text(markdown(report), encoding="utf-8")
    print(f"article_digest_json: {args.json}")
    print(f"article_digest_md: {args.md}")
    print(f"items: {len(report['items'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
