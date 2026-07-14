#!/usr/bin/env python3
"""Hard data-quality gates for a daily coaching session.

The coach may interpret facts, but it must not publish a full review when the
source packet is incomplete or internally inconsistent.
"""

from __future__ import annotations

import argparse
import csv
import json
from datetime import date
from pathlib import Path
from typing import Any


REQUIRED_INDEX_NAMES = {"上证指数", "深证成指", "创业板指", "科创50"}
REQUIRED_MA_FIELDS = ("ma5", "ma10", "ma20", "ma50", "ma200")


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError):
        return None


def _is_number(value: Any) -> bool:
    if value in (None, "", "-", "--"):
        return False
    try:
        float(value)
        return True
    except (TypeError, ValueError):
        return False


def validate_market_snapshot(path: Path) -> list[str]:
    snapshot = _load_json(path)
    if not isinstance(snapshot, dict):
        return ["市场快照 JSON 缺失或格式无效。"]
    errors: list[str] = []
    if snapshot.get("status") != "ok" or snapshot.get("verified") is not True:
        errors.append(f"市场快照未完成联网验证：status={snapshot.get('status')} verified={snapshot.get('verified')}。")

    indices = snapshot.get("major_indices") or []
    index_names = {str(row.get("name") or "") for row in indices if isinstance(row, dict)}
    missing_indices = sorted(REQUIRED_INDEX_NAMES - index_names)
    if missing_indices:
        errors.append(f"缺少主要指数事实：{'、'.join(missing_indices)}。")
    if any(not _is_number(row.get("change_pct")) for row in indices if isinstance(row, dict)):
        errors.append("主要指数存在缺少涨跌幅的记录。")
    us_indices = snapshot.get("us_indices") or []
    if len(us_indices) < 2 or any(not _is_number(row.get("change_pct")) for row in us_indices if isinstance(row, dict)):
        errors.append("美股映射指数不足 2 个或缺少涨跌幅。")

    breadth = snapshot.get("market_breadth") or {}
    total = breadth.get("total")
    up = breadth.get("up")
    down = breadth.get("down")
    flat = breadth.get("flat")
    if not all(_is_number(value) for value in (total, up, down, flat)):
        errors.append("市场宽度缺少总数、上涨、下跌或平盘家数。")
    else:
        total_i, up_i, down_i, flat_i = (int(float(value)) for value in (total, up, down, flat))
        if total_i < 2000:
            errors.append(f"市场宽度样本异常：仅 {total_i} 家，不能代表全市场。")
        if total_i != up_i + down_i + flat_i:
            errors.append("市场宽度总数与涨跌平家数不一致。")
        if not 0 <= up_i <= total_i or not 0 <= down_i <= total_i:
            errors.append("市场宽度家数超出合理范围。")

    return errors


def validate_article_digest(path: Path) -> list[str]:
    report = _load_json(path)
    if not isinstance(report, dict):
        return ["宏观/产业文章摘要缺失或格式无效。"]
    items = report.get("items") or []
    errors: list[str] = []
    if len(items) < 2:
        errors.append("宏观与产业/海外映射来源不足，至少需要 2 条独立来源。")
    if not any(str(item.get("source_type")) == "url" for item in items if isinstance(item, dict)):
        errors.append("文章摘要缺少公开 URL 来源。")
    valid_items = [
        item
        for item in items
        if isinstance(item, dict)
        and item.get("summary")
        and item.get("summary") != "无法抓取 URL 内容。"
        and item.get("source")
    ]
    if len(valid_items) < 2:
        errors.append("文章摘要中可用的事实摘要不足 2 条。")
    text = " ".join(
        f"{item.get('title', '')} {item.get('summary', '')} {item.get('source', '')}"
        for item in valid_items
    )
    if not any(term in text for term in ("美股", "纳斯达克", "标普", "英伟达", "海外", "美联储", "美国")):
        errors.append("文章摘要缺少美股/海外宏观映射事实。")
    if not any(term in text for term in ("政策", "产业", "行业", "财报", "公告", "医药", "半导体", "算力")):
        errors.append("文章摘要缺少产业政策或行业事实。")
    return errors


def validate_candidate_data(path: Path, trade_date: str, expected_count: int = 15) -> list[str]:
    if not path.exists():
        return ["候选股均线数据文件缺失。"]
    try:
        with path.open(newline="", encoding="utf-8-sig") as handle:
            rows = list(csv.DictReader(handle))
    except (OSError, csv.Error) as exc:
        return [f"候选股均线数据无法读取：{exc.__class__.__name__}。"]

    errors: list[str] = []
    if len(rows) != expected_count:
        errors.append(f"候选池数量不完整：得到 {len(rows)} 支，要求 {expected_count} 支。")
    codes = [str(row.get("stock_code") or row.get("code") or "").zfill(6) for row in rows]
    if len(codes) != len(set(codes)):
        errors.append("候选池存在重复证券代码。")
    excluded = sorted(code for code in codes if code.startswith("688"))
    if excluded:
        errors.append(f"候选池包含账户不可交易的 688 股票：{'、'.join(excluded)}。")

    try:
        target = date.fromisoformat(trade_date)
    except ValueError:
        target = None
    failed: list[str] = []
    missing_ma: list[str] = []
    stale: list[str] = []
    for row in rows:
        code = str(row.get("stock_code") or row.get("code") or "").zfill(6)
        if row.get("data_status") != "ok":
            failed.append(f"{code}({row.get('data_status') or 'unknown'})")
        if any(not _is_number(row.get(field)) for field in REQUIRED_MA_FIELDS):
            missing_ma.append(code)
        latest = str(row.get("latest_trade_date") or "")
        if target and latest:
            try:
                if (target - date.fromisoformat(latest)).days > 5 or date.fromisoformat(latest) > target:
                    stale.append(f"{code}:{latest}")
            except ValueError:
                stale.append(f"{code}:{latest}")
        elif target:
            stale.append(f"{code}:缺少日期")
        try:
            if int(float(row.get("bar_count") or 0)) < 200:
                missing_ma.append(f"{code}(bar_count)")
        except (TypeError, ValueError):
            missing_ma.append(f"{code}(bar_count)")
    if failed:
        errors.append("候选股行情抓取失败：" + "、".join(failed) + "。")
    if missing_ma:
        errors.append("候选股缺少完整 5/10/20/50/200 日线数据：" + "、".join(missing_ma) + "。")
    if stale:
        errors.append("候选股行情日期过旧或无效：" + "、".join(stale) + "。")
    return errors


def validate_session_inputs(run_dir: Path) -> dict[str, Any]:
    manifest_path = run_dir / "session_manifest.json"
    manifest = _load_json(manifest_path) if manifest_path.exists() else {}
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(manifest, dict):
        errors.append("session_manifest.json 缺失或格式无效。")
        manifest = {}

    trade_source = manifest.get("trade_source")
    trade_rows = int(manifest.get("trade_rows") or 0)
    if trade_source and manifest.get("privacy_status") != "ok":
        errors.append("交易事实未通过隐私校验，不能进入教练判断。")
    if trade_source and trade_rows <= 0:
        errors.append("交易输入已声明但没有解析到交易事实。")
    if not (manifest.get("journal_input") or manifest.get("market_view_input")):
        warnings.append("未记录用户交易日志或市场观点输入；交易动机和判断校正会不完整。")

    errors.extend(validate_market_snapshot(run_dir / "market_snapshot.json"))
    errors.extend(validate_article_digest(run_dir / "article_digest.json"))
    candidate_path = run_dir / "enriched_candidate_universe.csv"
    if not candidate_path.exists():
        candidate_path = run_dir / "research_pool_candidates.csv"
    errors.extend(validate_candidate_data(candidate_path, str(manifest.get("trade_date") or "")))
    positions_path = manifest.get("positions_snapshot")
    if not positions_path and not manifest.get("positions_input"):
        warnings.append("未生成持仓事实快照；持仓故事线无法完成核对。")
    return {
        "status": "ok" if not errors else "blocked",
        "errors": errors,
        "warnings": warnings,
        "checked_files": {
            "manifest": str(manifest_path),
            "market_snapshot": str(run_dir / "market_snapshot.json"),
            "article_digest": str(run_dir / "article_digest.json"),
            "candidate_data": str(candidate_path),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="校验盘后教练 session 的证据完整性。")
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--json", type=Path, default=None)
    args = parser.parse_args()
    report = validate_session_inputs(args.run_dir.resolve())
    output = args.json or args.run_dir / "data_quality.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"data_quality_status: {report['status']}")
    print(f"data_quality_report: {output}")
    if report["errors"]:
        print("errors:")
        for error in report["errors"]:
            print(f"- {error}")
    return 0 if report["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
