#!/usr/bin/env python3
"""Optional AKShare/BaoStock market data adapters for local coach scripts."""

from __future__ import annotations

import importlib
import json
import math
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any


MA_WINDOWS = (5, 10, 20, 50, 200)


@dataclass
class DailyBar:
    trade_date: str
    open: float | None
    high: float | None
    low: float | None
    close: float | None
    volume: float | None
    amount: float | None
    turnover: float | None = None
    pct_chg: float | None = None


@dataclass
class DailySeries:
    code: str
    provider: str
    bars: list[DailyBar]
    source: str
    notes: list[str]


def to_float(value: Any) -> float | None:
    try:
        if value in (None, "", "-", "--", "nan"):
            return None
        number = float(str(value).replace(",", ""))
        if math.isnan(number):
            return None
        return number
    except (TypeError, ValueError):
        return None


def normalize_date(value: str | date | None, *, compact: bool = False) -> str:
    if value is None:
        parsed = date.today()
    elif isinstance(value, date):
        parsed = value
    else:
        text = str(value).strip()
        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"):
            try:
                parsed = datetime.strptime(text, fmt).date()
                break
            except ValueError:
                continue
        else:
            raise ValueError(f"unsupported date format: {value}")
    return parsed.strftime("%Y%m%d" if compact else "%Y-%m-%d")


def normalize_stock_code(code: str) -> str:
    digits = "".join(ch for ch in str(code).strip() if ch.isdigit())
    return digits.zfill(6) if digits else ""


def baostock_code(code: str) -> str:
    digits = normalize_stock_code(code)
    if digits.startswith(("5", "6", "9")):
        return f"sh.{digits}"
    return f"sz.{digits}"


def fetch_daily_bars_akshare(code: str, start_date: str, end_date: str, adjust: str) -> DailySeries:
    akshare = importlib.import_module("akshare")
    symbol = normalize_stock_code(code)
    adjust_value = "" if adjust == "none" else adjust
    frame = akshare.stock_zh_a_hist(
        symbol=symbol,
        period="daily",
        start_date=normalize_date(start_date, compact=True),
        end_date=normalize_date(end_date, compact=True),
        adjust=adjust_value,
    )
    bars: list[DailyBar] = []
    for _, row in frame.iterrows():
        bars.append(
            DailyBar(
                trade_date=normalize_date(row.get("日期")),
                open=to_float(row.get("开盘")),
                high=to_float(row.get("最高")),
                low=to_float(row.get("最低")),
                close=to_float(row.get("收盘")),
                volume=to_float(row.get("成交量")),
                amount=to_float(row.get("成交额")),
                turnover=to_float(row.get("换手率")),
                pct_chg=to_float(row.get("涨跌幅")),
            )
        )
    bars.sort(key=lambda item: item.trade_date)
    return DailySeries(code=symbol, provider="akshare", bars=bars, source="akshare.stock_zh_a_hist", notes=[])


def baostock_adjust_flag(adjust: str) -> str:
    mapping = {
        "": "3",
        "none": "3",
        "qfq": "2",
        "hfq": "1",
    }
    return mapping.get(adjust, "2")


def eastmoney_adjust_flag(adjust: str) -> str:
    mapping = {
        "none": "0",
        "qfq": "1",
        "hfq": "2",
    }
    return mapping.get(adjust, "1")


def eastmoney_secid(code: str) -> str:
    symbol = normalize_stock_code(code)
    market = "1" if symbol.startswith(("5", "6", "9")) else "0"
    return f"{market}.{symbol}"


def yahoo_symbol(code: str) -> str:
    symbol = normalize_stock_code(code)
    suffix = "SS" if symbol.startswith(("5", "6", "9")) else "SZ"
    return f"{symbol}.{suffix}"


def fetch_daily_bars_yahoo(code: str, start_date: str, end_date: str, adjust: str) -> DailySeries:
    """Use Yahoo Chart as a final public fallback for A-share daily bars."""
    start = datetime.strptime(normalize_date(start_date), "%Y-%m-%d").replace(tzinfo=timezone.utc)
    end = datetime.strptime(normalize_date(end_date), "%Y-%m-%d").replace(tzinfo=timezone.utc) + timedelta(days=1)
    symbol = yahoo_symbol(code)
    params = {
        "period1": str(int(start.timestamp())),
        "period2": str(int(end.timestamp())),
        "interval": "1d",
        "events": "history",
        "includeAdjustedClose": "true",
    }
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 personal-trading-coach/0.1",
            "Accept": "application/json,text/plain,*/*",
        },
    )
    with urllib.request.urlopen(request, timeout=12) as response:
        payload = json.loads(response.read(4 * 1024 * 1024).decode("utf-8", errors="replace"))
    chart = (payload or {}).get("chart") or {}
    if chart.get("error"):
        raise RuntimeError(f"yahoo: {chart['error']}")
    results = chart.get("result") or []
    if not results:
        raise RuntimeError("yahoo: empty daily series")
    result = results[0]
    timestamps = result.get("timestamp") or []
    indicators = result.get("indicators") or {}
    quotes = indicators.get("quote") or []
    quote = quotes[0] if quotes else {}
    adjusted_sets = indicators.get("adjclose") or []
    adjusted = adjusted_sets[0].get("adjclose", []) if adjusted_sets else []
    raw_closes = quote.get("close") or []
    bars: list[DailyBar] = []
    for index, timestamp in enumerate(timestamps):
        raw_close = raw_closes[index] if index < len(raw_closes) else None
        adjusted_close = adjusted[index] if index < len(adjusted) else None
        close = adjusted_close if adjust != "none" and adjusted_close is not None else raw_close
        if close is None:
            continue
        bars.append(
            DailyBar(
                trade_date=datetime.fromtimestamp(timestamp, timezone.utc).date().isoformat(),
                open=to_float((quote.get("open") or [])[index]) if index < len(quote.get("open") or []) else None,
                high=to_float((quote.get("high") or [])[index]) if index < len(quote.get("high") or []) else None,
                low=to_float((quote.get("low") or [])[index]) if index < len(quote.get("low") or []) else None,
                close=to_float(close),
                volume=to_float((quote.get("volume") or [])[index]) if index < len(quote.get("volume") or []) else None,
                amount=None,
            )
        )
    if not bars:
        raise RuntimeError("yahoo: empty daily series")
    bars.sort(key=lambda item: item.trade_date)
    return DailySeries(
        code=normalize_stock_code(code),
        provider="yahoo_chart",
        bars=bars,
        source="query1.finance.yahoo.com/v8/finance/chart",
        notes=["Yahoo Chart 为 AKShare、BaoStock 与东方财富失败后的公开日线兜底。"],
    )


def fetch_daily_bars_eastmoney(code: str, start_date: str, end_date: str, adjust: str) -> DailySeries:
    """Use Eastmoney's public kline endpoint when optional Python adapters are unavailable."""
    params = {
        "secid": eastmoney_secid(code),
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        "klt": "101",
        "fqt": eastmoney_adjust_flag(adjust),
        "beg": normalize_date(start_date, compact=True),
        "end": normalize_date(end_date, compact=True),
    }
    url = "https://push2his.eastmoney.com/api/qt/stock/kline/get?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 personal-trading-coach/0.1",
            "Accept": "application/json,text/plain,*/*",
            "Referer": "https://quote.eastmoney.com/",
        },
    )
    with urllib.request.urlopen(request, timeout=12) as response:
        payload = json.loads(response.read(4 * 1024 * 1024).decode("utf-8", errors="replace"))
    data = (payload or {}).get("data") or {}
    klines = data.get("klines") or []
    if not klines:
        raise RuntimeError("eastmoney: empty daily series")
    bars: list[DailyBar] = []
    for line in klines:
        parts = str(line).split(",")
        if len(parts) < 11:
            continue
        bars.append(
            DailyBar(
                trade_date=normalize_date(parts[0]),
                open=to_float(parts[1]),
                close=to_float(parts[2]),
                high=to_float(parts[3]),
                low=to_float(parts[4]),
                volume=to_float(parts[5]),
                amount=to_float(parts[6]),
                pct_chg=to_float(parts[8]),
                turnover=to_float(parts[10]),
            )
        )
    bars.sort(key=lambda item: item.trade_date)
    return DailySeries(
        code=normalize_stock_code(code),
        provider="eastmoney_http",
        bars=bars,
        source="eastmoney.push2his.stock.kline",
        notes=["AKShare/BaoStock 不可用时的 HTTP 兜底数据源。"],
    )


def fetch_daily_bars_baostock(code: str, start_date: str, end_date: str, adjust: str) -> DailySeries:
    baostock = importlib.import_module("baostock")
    lg = baostock.login()
    if getattr(lg, "error_code", "0") != "0":
        raise RuntimeError(f"baostock login failed: {getattr(lg, 'error_msg', '')}")
    try:
        fields = "date,code,open,high,low,close,preclose,volume,amount,turn,pctChg"
        result = baostock.query_history_k_data_plus(
            baostock_code(code),
            fields,
            start_date=normalize_date(start_date),
            end_date=normalize_date(end_date),
            frequency="d",
            adjustflag=baostock_adjust_flag(adjust),
        )
        if getattr(result, "error_code", "0") != "0":
            raise RuntimeError(f"baostock query failed: {getattr(result, 'error_msg', '')}")
        bars: list[DailyBar] = []
        while result.next():
            row = dict(zip(result.fields, result.get_row_data()))
            bars.append(
                DailyBar(
                    trade_date=normalize_date(row.get("date")),
                    open=to_float(row.get("open")),
                    high=to_float(row.get("high")),
                    low=to_float(row.get("low")),
                    close=to_float(row.get("close")),
                    volume=to_float(row.get("volume")),
                    amount=to_float(row.get("amount")),
                    turnover=to_float(row.get("turn")),
                    pct_chg=to_float(row.get("pctChg")),
                )
            )
        bars.sort(key=lambda item: item.trade_date)
        return DailySeries(
            code=normalize_stock_code(code),
            provider="baostock",
            bars=bars,
            source="baostock.query_history_k_data_plus",
            notes=[],
        )
    finally:
        baostock.logout()


def fetch_daily_bars(
    code: str,
    start_date: str,
    end_date: str,
    *,
    provider: str = "auto",
    adjust: str = "qfq",
) -> DailySeries:
    providers = ["akshare", "baostock", "eastmoney", "yahoo"] if provider == "auto" else [provider]
    errors: list[str] = []
    for item in providers:
        try:
            if item == "akshare":
                series = fetch_daily_bars_akshare(code, start_date, end_date, adjust)
            elif item == "baostock":
                series = fetch_daily_bars_baostock(code, start_date, end_date, adjust)
            elif item == "eastmoney":
                series = fetch_daily_bars_eastmoney(code, start_date, end_date, adjust)
            elif item == "yahoo":
                series = fetch_daily_bars_yahoo(code, start_date, end_date, adjust)
            else:
                raise ValueError(f"unknown provider: {item}")
            if series.bars:
                if errors:
                    series.notes.extend(errors)
                return series
            errors.append(f"{item}: empty daily series")
        except Exception as exc:  # noqa: BLE001 - caller needs degraded source notes.
            errors.append(f"{item}: {exc.__class__.__name__}: {exc}")
    raise RuntimeError("; ".join(errors) if errors else "no provider attempted")


def moving_average(values: list[float], window: int) -> float | None:
    if len(values) < window:
        return None
    subset = values[-window:]
    return round(sum(subset) / window, 4)


def relation_pct(close: float | None, anchor: float | None) -> float | None:
    if close is None or not anchor:
        return None
    return round((close - anchor) / anchor * 100, 2)


def ma_state(rel: float | None) -> str:
    if rel is None:
        return "无法判断"
    if -1.5 <= rel <= 2.5:
        return "贴近"
    if rel > 8:
        return "远离上方"
    if rel > 2.5:
        return "上方"
    if rel < -5:
        return "跌破较远"
    return "下方"


def summarize_daily_series(series: DailySeries) -> dict[str, Any]:
    bars = [bar for bar in series.bars if bar.close is not None]
    latest = bars[-1] if bars else None
    closes = [bar.close for bar in bars if bar.close is not None]
    volumes = [bar.volume for bar in bars if bar.volume is not None]
    metrics: dict[str, Any] = {
        "stock_code": series.code,
        "data_provider": series.provider,
        "data_source": series.source,
        "bar_count": len(series.bars),
        "latest_trade_date": latest.trade_date if latest else "",
        "close": latest.close if latest else None,
        "volume": latest.volume if latest else None,
        "amount": latest.amount if latest else None,
        "turnover": latest.turnover if latest else None,
        "change_pct": latest.pct_chg if latest else None,
        "data_notes": "；".join(series.notes),
    }
    if latest and latest.pct_chg is None and len(bars) >= 2 and bars[-2].close:
        metrics["change_pct"] = round((latest.close - bars[-2].close) / bars[-2].close * 100, 2)
    if len(volumes) >= 20:
        metrics["avg_volume20"] = round(sum(volumes[-20:]) / 20, 2)
    else:
        metrics["avg_volume20"] = None
    for window in MA_WINDOWS:
        metrics[f"ma{window}"] = moving_average(closes, window)
        metrics[f"ma{window}_relation_pct"] = relation_pct(metrics.get("close"), metrics.get(f"ma{window}"))
        metrics[f"ma{window}_state"] = ma_state(metrics.get(f"ma{window}_relation_pct"))
    metrics["ma_summary"] = "；".join(
        f"{window}日:{metrics.get(f'ma{window}_state')}" for window in MA_WINDOWS
    )
    return metrics
