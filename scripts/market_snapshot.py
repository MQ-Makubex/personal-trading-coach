#!/usr/bin/env python3
"""Collect a lightweight A-share market fact snapshot for coach review."""

from __future__ import annotations

import argparse
import importlib
import json
import math
import re
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path
from typing import Any


SINA_INDEX_SYMBOLS = {
    "sh000001": "上证指数",
    "sz399001": "深证成指",
    "sz399006": "创业板指",
    "sh000688": "科创50",
}

YAHOO_INDEX_SYMBOLS = {
    "%5EGSPC": "标普500",
    "%5EIXIC": "纳斯达克综合",
    "%5ESOX": "费城半导体",
}

EASTMONEY_FIELDS = "f12,f14,f2,f3,f5,f6,f20,f21,f62"
EASTMONEY_UT = "bd1d9ddb04089700cf9c27f6f7426281"
MARKET_CACHE_DIR = Path("reports/market_cache")


def request_text(url: str, encoding: str = "utf-8", timeout: int = 10) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 personal-trading-coach/0.1",
            "Accept": "*/*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
            "Referer": "https://finance.sina.com.cn/",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read(3 * 1024 * 1024)
        charset = response.headers.get_content_charset() or encoding
    return raw.decode(charset, errors="replace")


def request_json(url: str, timeout: int = 10) -> dict[str, Any]:
    return json.loads(request_text(url, timeout=timeout))


def to_float(value: Any) -> float | None:
    try:
        if value in (None, "", "-"):
            return None
        number = float(str(value).replace(",", ""))
        if math.isnan(number):
            return None
        return number
    except (TypeError, ValueError):
        return None


def pct_change(current: float | None, previous: float | None) -> float | None:
    if current is None or previous in (None, 0):
        return None
    return round((current - previous) / previous * 100, 2)


def fetch_indices() -> tuple[list[dict[str, Any]], str]:
    symbols = ",".join(SINA_INDEX_SYMBOLS)
    url = f"https://hq.sinajs.cn/list={symbols}"
    text = request_text(url, encoding="gbk")
    rows: list[dict[str, Any]] = []
    pattern = re.compile(r'var hq_str_([a-z0-9]+)="([^"]*)";')
    for symbol, payload in pattern.findall(text):
        parts = payload.split(",")
        if len(parts) < 32 or not parts[0]:
            continue
        open_price = to_float(parts[1])
        prev_close = to_float(parts[2])
        current = to_float(parts[3])
        rows.append(
            {
                "symbol": symbol,
                "name": SINA_INDEX_SYMBOLS.get(symbol, parts[0]),
                "price": current,
                "change": round(current - prev_close, 3) if current is not None and prev_close is not None else None,
                "change_pct": pct_change(current, prev_close),
                "open": open_price,
                "high": to_float(parts[4]),
                "low": to_float(parts[5]),
                "volume": to_float(parts[8]),
                "amount": to_float(parts[9]),
                "quote_date": parts[30] if len(parts) > 30 else "",
                "quote_time": parts[31] if len(parts) > 31 else "",
                "provider": "sina_hq",
            }
        )
    return rows, url


def fetch_us_indices() -> tuple[list[dict[str, Any]], str]:
    rows: list[dict[str, Any]] = []
    for symbol, name in YAHOO_INDEX_SYMBOLS.items():
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=5d"
        payload = request_json(url)
        result = ((payload.get("chart") or {}).get("result") or [None])[0] or {}
        timestamps = result.get("timestamp") or []
        quotes = ((result.get("indicators") or {}).get("quote") or [{}])[0]
        closes = quotes.get("close") or []
        valid = [(timestamp, close) for timestamp, close in zip(timestamps, closes) if close is not None]
        if len(valid) < 2:
            continue
        _, current = valid[-1]
        _, previous = valid[-2]
        rows.append(
            {
                "symbol": symbol,
                "name": name,
                "price": round(float(current), 4),
                "change_pct": round((float(current) - float(previous)) / float(previous) * 100, 2),
                "provider": "yahoo_chart",
            }
        )
    return rows, "yahoo_chart"


def fetch_sina_stock_breadth(trade_date: str, batch_size: int = 500) -> tuple[list[dict[str, Any]], str]:
    """Build whole-market breadth from public Sina quotes and BaoStock's symbol list.

    Eastmoney's list endpoint is occasionally capped or disconnected. This
    fallback uses public quote payloads in batches, so a 100-row response can
    never silently masquerade as whole-market breadth.
    """
    baostock = importlib.import_module("baostock")
    login = baostock.login()
    if getattr(login, "error_code", "0") != "0":
        raise RuntimeError(f"baostock login failed: {getattr(login, 'error_msg', '')}")
    try:
        result = baostock.query_all_stock(day=trade_date)
        if getattr(result, "error_code", "0") != "0":
            raise RuntimeError(f"baostock stock list failed: {getattr(result, 'error_msg', '')}")
        symbols: list[str] = []
        while result.next():
            row = dict(zip(result.fields, result.get_row_data()))
            code = str(row.get("code") or "")
            trade_status = str(row.get("tradeStatus") or "1")
            if trade_status != "1":
                continue
            if code.startswith(("sh.6", "sz.0", "sz.3")):
                symbols.append(code.replace(".", ""))
    finally:
        baostock.logout()

    rows: list[dict[str, Any]] = []
    pattern = re.compile(r'var hq_str_([a-z0-9]+)="([^"]*)";')
    for offset in range(0, len(symbols), batch_size):
        batch = symbols[offset : offset + batch_size]
        url = "https://hq.sinajs.cn/list=" + ",".join(batch)
        text = request_text(url, encoding="gbk")
        for symbol, payload in pattern.findall(text):
            parts = payload.split(",")
            if len(parts) < 4 or not parts[0]:
                continue
            previous = to_float(parts[2])
            current = to_float(parts[3])
            if previous in (None, 0) or current is None or current == 0:
                continue
            rows.append(
                {
                    "code": symbol[2:],
                    "name": parts[0],
                    "price": current,
                    "change_pct": round((current - previous) / previous * 100, 2),
                    "provider": "sina_stock_quote",
                }
            )
    return rows, "sina_stock_quote+baostock_stock_list"


def eastmoney_clist(fs: str, fid: str, limit: int) -> tuple[list[dict[str, Any]], str]:
    params = {
        "pn": "1",
        "pz": str(limit),
        "po": "1",
        "np": "1",
        "ut": EASTMONEY_UT,
        "fltt": "2",
        "invt": "2",
        "fid": fid,
        "fs": fs,
        "fields": EASTMONEY_FIELDS,
    }
    url = "https://push2.eastmoney.com/api/qt/clist/get?" + urllib.parse.urlencode(params)
    data = request_json(url)
    diff = (((data or {}).get("data") or {}).get("diff") or [])
    rows = []
    for item in diff:
        rows.append(
            {
                "code": str(item.get("f12") or ""),
                "name": item.get("f14") or "",
                "price": to_float(item.get("f2")),
                "change_pct": to_float(item.get("f3")),
                "volume": to_float(item.get("f5")),
                "amount": to_float(item.get("f6")),
                "total_market_cap": to_float(item.get("f20")),
                "float_market_cap": to_float(item.get("f21")),
                "main_net_inflow": to_float(item.get("f62")),
                "provider": "eastmoney_clist",
            }
        )
    return rows, url


def fetch_ths_industry_summary(limit: int, trade_date: str) -> tuple[list[dict[str, Any]], str]:
    errors: list[str] = []
    for _attempt in range(3):
        try:
            akshare = importlib.import_module("akshare")
            frame = akshare.stock_board_industry_summary_ths()
            rows: list[dict[str, Any]] = []
            for _, item in frame.iterrows():
                rows.append(
                    {
                        "code": "",
                        "name": str(item.get("板块") or ""),
                        "price": to_float(item.get("均价")),
                        "change_pct": to_float(item.get("涨跌幅")),
                        "volume": to_float(item.get("总成交量")),
                        "amount": to_float(item.get("总成交额")),
                        "main_net_inflow": to_float(item.get("净流入")),
                        "up_count": to_float(item.get("上涨家数")),
                        "down_count": to_float(item.get("下跌家数")),
                        "leader": str(item.get("领涨股") or ""),
                        "leader_change_pct": to_float(item.get("领涨股-涨跌幅")),
                        "provider": "akshare_ths_industry_summary",
                    }
                )
            rows.sort(key=lambda row: row.get("change_pct") if row.get("change_pct") is not None else -999, reverse=True)
            MARKET_CACHE_DIR.mkdir(parents=True, exist_ok=True)
            (MARKET_CACHE_DIR / "ths_industry_summary.json").write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
            return rows[:limit], "akshare.stock_board_industry_summary_ths"
        except Exception as exc:  # noqa: BLE001 - retry then cache fallback.
            errors.append(f"{exc.__class__.__name__}: {exc}")

    cache = MARKET_CACHE_DIR / "ths_industry_summary.json"
    cache_date = date.fromtimestamp(cache.stat().st_mtime).isoformat() if cache.exists() else ""
    if cache.exists() and cache_date == trade_date:
        rows = json.loads(cache.read_text(encoding="utf-8"))
        return rows[:limit], "cache.akshare.stock_board_industry_summary_ths"
    if cache.exists():
        errors.append(f"cache is stale: {cache_date} != {trade_date}")
    raise RuntimeError("; ".join(errors))


def summarize_breadth(rows: list[dict[str, Any]]) -> dict[str, Any]:
    valid = [row for row in rows if row.get("change_pct") is not None]
    up = sum(1 for row in valid if (row.get("change_pct") or 0) > 0)
    down = sum(1 for row in valid if (row.get("change_pct") or 0) < 0)
    flat = len(valid) - up - down
    return {
        "total": len(valid),
        "up": up,
        "down": down,
        "flat": flat,
        "up_ratio": round(up / len(valid) * 100, 2) if valid else None,
    }


def summarize_sector_breadth(rows: list[dict[str, Any]]) -> dict[str, Any]:
    up = sum(int(row.get("up_count") or 0) for row in rows)
    down = sum(int(row.get("down_count") or 0) for row in rows)
    total = up + down
    return {
        "total": total,
        "up": up,
        "down": down,
        "flat": None,
        "up_ratio": round(up / total * 100, 2) if total else None,
        "provider": "sector_constituent_aggregate",
    }


def read_optional(path: Path | None) -> str:
    if not path:
        return ""
    return path.read_text(encoding="utf-8").strip()


def build_snapshot(args: argparse.Namespace) -> dict[str, Any]:
    snapshot: dict[str, Any] = {
        "trade_date": args.trade_date,
        "status": "offline" if args.offline else "ok",
        "verified": not args.offline,
        "data_sources": [],
        "major_indices": [],
        "us_indices": [],
        "market_breadth": {},
        "sector_strength": [],
        "sector_weakness": [],
        "style_bias": "待教练根据数据判断",
        "risk_appetite": "待教练根据数据判断",
        "market_regime": "待教练根据数据判断",
        "coach_view": "待教练独立判断，不能直接使用用户判断。",
        "user_view": read_optional(args.user_view),
        "agreement": "待教练判断",
        "correction": "待教练校正",
        "trading_implication": "待教练连接到具体交易决策事件。",
        "notes": [],
    }
    if args.offline:
        snapshot["notes"].append("市场背景未联网验证。")
        return snapshot

    try:
        indices, source = fetch_indices()
        snapshot["major_indices"] = indices
        snapshot["data_sources"].append(source)
    except Exception as exc:  # noqa: BLE001 - report degraded source, continue.
        snapshot["status"] = "partial"
        snapshot["verified"] = False
        snapshot["notes"].append(f"主要指数抓取失败：{exc.__class__.__name__}")

    try:
        us_indices, source = fetch_us_indices()
        snapshot["us_indices"] = us_indices
        snapshot["data_sources"].append(source)
    except Exception as exc:  # noqa: BLE001
        snapshot["notes"].append(f"美股指数抓取失败：{exc.__class__.__name__}")

    try:
        stocks, source = eastmoney_clist("m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23", "f3", args.breadth_limit)
        breadth = summarize_breadth(stocks)
        if breadth.get("total", 0) < 2000:
            raise RuntimeError(f"Eastmoney breadth sample too small: {breadth.get('total')}")
        snapshot["market_breadth"] = breadth
        snapshot["data_sources"].append(source)
    except Exception as exc:  # noqa: BLE001
        snapshot["status"] = "partial"
        snapshot["verified"] = False
        snapshot["notes"].append(f"Eastmoney 市场宽度不可用：{exc.__class__.__name__}")
        try:
            stocks, source = fetch_sina_stock_breadth(args.trade_date)
            breadth = summarize_breadth(stocks)
            if breadth.get("total", 0) < 2000:
                raise RuntimeError(f"Sina breadth sample too small: {breadth.get('total')}")
            snapshot["market_breadth"] = breadth
            snapshot["data_sources"].append(source)
            snapshot["status"] = "ok" if snapshot["major_indices"] else "partial"
            snapshot["verified"] = bool(snapshot["major_indices"])
            snapshot["notes"].append("市场宽度已切换为 Sina 公共报价 + BaoStock 股票列表兜底。")
        except Exception as fallback_exc:  # noqa: BLE001
            snapshot["notes"].append(f"Sina/BaoStock 市场宽度兜底失败：{fallback_exc.__class__.__name__}")

    try:
        industries, source = eastmoney_clist("m:90+t:2", "f3", args.sector_limit)
        snapshot["sector_strength"] = industries[: min(10, len(industries))]
        snapshot["sector_weakness"] = list(reversed(industries[-min(10, len(industries)) :]))
        snapshot["data_sources"].append(source)
    except Exception as exc:  # noqa: BLE001
        snapshot["notes"].append(f"Eastmoney 行业板块抓取失败：{exc.__class__.__name__}")
        try:
            industries, source = fetch_ths_industry_summary(args.sector_limit, args.trade_date)
            snapshot["sector_strength"] = industries[: min(10, len(industries))]
            snapshot["sector_weakness"] = list(reversed(industries[-min(10, len(industries)) :]))
            if not snapshot.get("market_breadth") and any(row.get("up_count") is not None for row in industries):
                snapshot["market_breadth"] = summarize_sector_breadth(industries)
                snapshot["notes"].append("市场宽度已使用同花顺行业成分涨跌家数聚合近似。")
            snapshot["data_sources"].append(source)
            snapshot["notes"].append("行业板块已使用同花顺行业汇总 fallback。")
        except Exception as fallback_exc:  # noqa: BLE001
            snapshot["status"] = "partial"
            snapshot["verified"] = False
            snapshot["notes"].append(f"行业板块 fallback 抓取失败：{fallback_exc.__class__.__name__}")

    # Indexes and whole-market breadth are the hard market facts. If those
    # are complete, keep the snapshot usable and require the article digest
    # to supply current policy/industry/overseas context instead of silently
    # reusing stale sector cache data.
    if snapshot["major_indices"] and snapshot.get("market_breadth", {}).get("total", 0) >= 2000:
        snapshot["status"] = "ok"
        snapshot["verified"] = True
        if not snapshot["sector_strength"] or not snapshot["sector_weakness"]:
            snapshot["notes"].append("当日行业板块未从行情接口取得；必须由文章摘要补齐产业、政策和海外映射。")

    if snapshot["status"] == "partial":
        snapshot["notes"].append("市场背景部分联网验证；缺失项不得硬编。")
    return snapshot


def markdown(snapshot: dict[str, Any]) -> str:
    lines = [
        f"# 市场事实快照 - {snapshot.get('trade_date')}",
        "",
        f"- 状态: {snapshot.get('status')}",
        f"- 是否联网验证: {snapshot.get('verified')}",
        "",
        "## 主要指数",
        "",
        "| 指数 | 最新 | 涨跌幅 | 时间 |",
        "| --- | ---: | ---: | --- |",
    ]
    for row in snapshot.get("major_indices", []):
        lines.append(f"| {row.get('name','')} | {row.get('price','')} | {row.get('change_pct','')} | {row.get('quote_time','')} |")
    lines.extend(["", "## 美股映射", "", "| 指数 | 最新 | 涨跌幅 |", "| --- | ---: | ---: |"])
    for row in snapshot.get("us_indices", []):
        lines.append(f"| {row.get('name','')} | {row.get('price','')} | {row.get('change_pct','')}% |")
    lines.extend(["", "## 市场宽度", "", json.dumps(snapshot.get("market_breadth", {}), ensure_ascii=False, indent=2), "", "## 强势板块", ""])
    for row in snapshot.get("sector_strength", [])[:10]:
        extra = ""
        if row.get("main_net_inflow") is not None:
            extra += f"，净流入 {row.get('main_net_inflow')}"
        if row.get("leader"):
            extra += f"，领涨 {row.get('leader')}"
        lines.append(f"- {row.get('name')}：{row.get('change_pct')}%{extra}")
    lines.extend(["", "## 弱势板块", ""])
    for row in snapshot.get("sector_weakness", [])[:10]:
        lines.append(f"- {row.get('name')}：{row.get('change_pct')}%")
    lines.extend(
        [
            "",
            "## 用户待校正判断",
            "",
            str(snapshot.get("user_view") or "未提供。"),
            "",
            "## 教练待判断项",
            "",
            "- 风格偏向:",
            "- 风险偏好:",
            "- 市场状态:",
            "- 对今日交易复盘的影响:",
            "",
            "## 注意",
            "",
            "本文件只提供市场事实，不提供买卖建议，不预测未来涨跌。",
        ]
    )
    if snapshot.get("notes"):
        lines.extend(["", "## 数据问题", ""])
        lines.extend(f"- {note}" for note in snapshot["notes"])
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="生成 A 股市场事实快照，供教练校正用户市场判断。")
    parser.add_argument("--trade-date", default=date.today().isoformat())
    parser.add_argument("--user-view", type=Path, default=None)
    parser.add_argument("--offline", action="store_true", help="不联网，输出未验证占位快照。")
    parser.add_argument("--breadth-limit", type=int, default=5000)
    parser.add_argument("--sector-limit", type=int, default=80)
    parser.add_argument("--json", type=Path, default=Path("reports/market_snapshot.json"))
    parser.add_argument("--md", type=Path, default=Path("reports/market_snapshot.md"))
    args = parser.parse_args()

    snapshot = build_snapshot(args)
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.md.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    args.md.write_text(markdown(snapshot), encoding="utf-8")
    print(f"market_snapshot: {args.json}")
    print(f"market_snapshot_md: {args.md}")
    print(f"status: {snapshot.get('status')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
