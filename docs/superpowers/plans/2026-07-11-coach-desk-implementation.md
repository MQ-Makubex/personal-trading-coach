# Personal Trading Coach Desk Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a private multi-page trading coach desk whose homepage, ledger filters, stock stories, mode archive, and discipline feed all use one auditable transaction-cycle model.

**Architecture:** Keep `state/account_ledger.sqlite` as the immutable trade-fact source, derive deterministic broker-like position cycles and period metrics in focused Python modules, and compose those results into the existing static-site generator. Keep manually reviewed coaching state in two private JSON files, expose only project-relative references, and use page-specific JavaScript for URL-restorable ledger and cycle interactions.

**Tech Stack:** Python 3 standard library, SQLite, static HTML/CSS/JavaScript, `unittest`, Node.js built-in test runner, Playwright from the bundled Codex runtime.

## Global Constraints

- Do not alter imported trade facts in `state/account_ledger.sqlite`; all new account, cycle, and period values are derived.
- Do not add trading scores, ratings, predictions, automatic buy/sell signals, or automatic mode promotion.
- Current account facts remain fixed when the ledger time filter changes.
- Total P&L including open positions is available only when every open position has a verified quote; otherwise show `待核验` and the missing codes.
- A cycle starts at the first buy from flat, closes when quantity reaches zero, keeps same-day close/re-entry in one cycle, and starts a new cycle after next-day re-entry.
- Cycle IDs are deterministic from the first buy facts and do not include final-close facts.
- Ability metrics use closed cycles only; security cash adjustments affect account and period realized P&L but never cycle ability metrics.
- Holding duration uses calendar days; show both mean and median.
- Coach gate, mode eligibility, mode samples, and discipline messages come only from structured JSON; never infer them from narrative Markdown.
- Missing or malformed private JSON must not stop the rest of the site from building.
- Never fabricate a missing trade plan, research candidate, discipline message, or mode sample.
- The latest valid plan/pool may be used only with its target date, source link, and `可能过期` marker.
- Preserve `state/personal_trading_modes.md` as narrative history; do not migrate it automatically.
- Every path copied from private state into generated data must be project-relative and must not contain `..`.
- The current acceptance numbers in the design spec are snapshot assertions, not constants in production code.
- Do not stage or revert unrelated dirty files. The relevant interrupted baseline is currently untracked/modified, so execution must begin in this workspace and create the scoped baseline commit in Task 0 before any worktree is created.

## File Map

**Existing files to modify**

- `scripts/ledger_analytics.py`: canonical broker-like cycles and compatibility projections.
- `scripts/init_state.py`: initialize the two private JSON state files without overwriting existing state.
- `scripts/build_personal_site.py`: compose site data and render the homepage, ledger, stories, modes, and page shell.
- `templates/personal_site/site.css`: coach-desk layout and responsive states.
- `templates/personal_site/site.js`: existing filters plus stock-cycle and mode-page interactions.
- `.gitignore`: allow public JSON templates while continuing to ignore private/runtime JSON.
- `tests/test_ledger_analytics.py`: cycle boundary and stable-ID regressions.
- `tests/test_personal_site.py`: generator, fallback, page, and link-integrity integration tests.

**Files to create**

- `scripts/personal_site_metrics.py`: ability metrics, date windows, period summaries, and per-stock period results.
- `scripts/personal_site_state.py`: validated private JSON loading and mode-sample enrichment.
- `templates/state/trading_modes.json`: empty public template for gate, eligibility, and modes.
- `templates/state/discipline_feed.json`: empty public discipline-feed template.
- `templates/personal_site/ledger.js`: pure ledger range calculations plus browser rendering.
- `tests/test_personal_site_metrics.py`: metric and time-boundary unit tests.
- `tests/test_personal_site_state.py`: state validation and sample-counting tests.
- `tests/test_ledger_filter.js`: Node tests for browser-side date and period calculations.
- `tests/qa_personal_site.mjs`: Playwright desktop/mobile acceptance script.

---

### Task 0: Capture the Interrupted Personal-Site Baseline

**Files:**
- Stage: `scripts/ledger_analytics.py`
- Stage: `scripts/build_personal_site.py`
- Stage: `templates/personal_site/site.css`
- Stage: `templates/personal_site/site.js`
- Stage: `tests/test_ledger_analytics.py`
- Stage: `tests/test_personal_site.py`

**Interfaces:**
- Consumes: the current workspace state and the 14 passing regression tests.
- Produces: a commit containing only the existing personal-site and corrected cost-basis baseline, so later task commits are reviewable and a worktree can be created if required.

- [ ] **Step 1: Confirm the exact baseline scope**

Run:

```bash
git status --short
git diff -- scripts/ledger_analytics.py
```

Expected: the six listed files are present; unrelated changes such as `README.md`, workflow docs, market scripts, research templates, and `design-previews/` remain outside this task.

- [ ] **Step 2: Run the existing baseline tests**

Run:

```bash
python3 -m unittest discover -s tests -v
```

Expected: `Ran 14 tests` and `OK`.

- [ ] **Step 3: Stage only the baseline files and inspect the index**

Run:

```bash
git add scripts/ledger_analytics.py scripts/build_personal_site.py templates/personal_site/site.css templates/personal_site/site.js tests/test_ledger_analytics.py tests/test_personal_site.py
git diff --cached --stat
git diff --cached --check
```

Expected: only the six listed paths are staged and `git diff --cached --check` prints nothing.

- [ ] **Step 4: Commit the baseline**

Run:

```bash
git commit -m "Baseline personal trading site"
```

Expected: one commit containing the current multi-page site, cost-basis correction, and its 14 tests. All unrelated dirty files remain dirty and unstaged.

---

### Task 1: Canonical Broker-Like Trade Cycles

**Files:**
- Modify: `scripts/ledger_analytics.py`
- Modify: `tests/test_ledger_analytics.py`

**Interfaces:**
- Consumes: `Trade`, `buy_cost_after_fees()`, `sell_proceeds_after_fees()`, `future_same_day_buys()`, and display names.
- Produces: `cycle_id_for_trade(trade: Trade) -> str` and `broker_like_cycles(trades: list[Trade], display_names: dict[str, str]) -> list[dict[str, Any]]`.
- Produces cycle keys: `cycle_id`, `status`, `stock_code`, `stock_name`, `first_buy_date`, `first_buy_time`, `last_buy_date`, `last_buy_time`, `close_date`, `close_time`, `holding_days`, `buy_quantity`, `sell_quantity`, `open_quantity`, `buy_cost_after_fees`, `sell_proceeds_after_fees`, `rolling_cost_basis_after_fees`, `realized_pnl_after_fees`, `return_pct`, close-cost audit fields, and `events`.
- Preserves: `broker_like_realized_lots()` and its current keys as a projection of closed canonical cycles.

- [ ] **Step 1: Add failing cycle-boundary and ID tests**

Add `price` to the test helper as an optional derived value, import the two new functions, and add these tests:

```python
from ledger_analytics import (
    CashAdjustment,
    Trade,
    broker_like_cycles,
    broker_like_realized_by_stock,
    broker_like_realized_lots,
    cycle_id_for_trade,
    rolling_cost_positions,
)


class BrokerLikeCyclesTest(unittest.TestCase):
    def test_same_day_flat_and_reentry_stays_in_one_cycle(self) -> None:
        trades = [
            trade(1, "2026-01-01", "09:30:00", "BUY", 100, 1000),
            trade(2, "2026-01-02", "10:00:00", "SELL", 100, 1200),
            trade(3, "2026-01-02", "14:00:00", "BUY", 100, 1100),
            trade(4, "2026-01-03", "10:00:00", "SELL", 100, 900),
        ]

        cycles = broker_like_cycles(trades, {"000001": "TEST"})

        self.assertEqual(len(cycles), 1)
        self.assertEqual(cycles[0]["status"], "closed")
        self.assertEqual(cycles[0]["first_buy_date"], "2026-01-01")
        self.assertEqual(cycles[0]["close_date"], "2026-01-03")
        self.assertEqual(cycles[0]["holding_days"], 2)
        self.assertEqual(cycles[0]["realized_pnl_after_fees"], 0.0)
        self.assertEqual(len(cycles[0]["events"]), 4)

    def test_next_day_reentry_starts_a_second_cycle(self) -> None:
        trades = [
            trade(1, "2026-01-01", "09:30:00", "BUY", 100, 1000),
            trade(2, "2026-01-02", "10:00:00", "SELL", 100, 1200),
            trade(3, "2026-01-03", "09:30:00", "BUY", 100, 1100),
        ]

        cycles = broker_like_cycles(trades, {"000001": "TEST"})

        self.assertEqual([row["status"] for row in cycles], ["closed", "open"])
        self.assertNotEqual(cycles[0]["cycle_id"], cycles[1]["cycle_id"])

    def test_cycle_id_is_unchanged_when_the_cycle_later_closes(self) -> None:
        first = trade(1, "2026-01-01", "09:30:00", "BUY", 100, 1000, net_amount=-1000)
        open_cycle = broker_like_cycles([first], {"000001": "TEST"})[0]
        closed_cycle = broker_like_cycles(
            [first, trade(2, "2026-01-02", "10:00:00", "SELL", 100, 1200, net_amount=1200)],
            {"000001": "TEST"},
        )[0]

        self.assertEqual(open_cycle["cycle_id"], closed_cycle["cycle_id"])
        self.assertEqual(open_cycle["cycle_id"], cycle_id_for_trade(first))

    def test_broker_cost_regression_is_preserved_in_canonical_cycle(self) -> None:
        trades = [
            trade(1, "2026-06-30", "", "BUY", 400, 40388, 5),
            trade(2, "2026-07-01", "11:14:25", "SELL", 400, 49040, 30.40),
            trade(3, "2026-07-01", "14:39:20", "BUY", 500, 59639, 7.16),
            trade(4, "2026-07-02", "09:37:26", "BUY", 500, 56795, 6.82),
            trade(5, "2026-07-02", "14:52:26", "SELL", 500, 55915, 34.66),
            trade(6, "2026-07-03", "09:54:18", "BUY", 800, 86608, 10.39),
            trade(7, "2026-07-07", "14:56:45", "SELL", 1200, 117516, 72.87),
            trade(8, "2026-07-08", "13:12:00", "BUY", 1500, 151080, 18.13),
            trade(9, "2026-07-09", "10:01:38", "SELL", 1600, 152000, 94.24),
        ]

        cycle = broker_like_cycles(trades, {"000001": "TEST"})[0]

        self.assertEqual(cycle["close_average_cost_before_sell"], 107.64)
        self.assertEqual(cycle["realized_pnl_after_fees"], -20318.67)
```

- [ ] **Step 2: Run the new tests and verify the missing-interface failure**

Run:

```bash
python3 -m unittest tests.test_ledger_analytics.BrokerLikeCyclesTest -v
```

Expected: import failure for `broker_like_cycles` or `cycle_id_for_trade`.

- [ ] **Step 3: Add price to the canonical `Trade` facts and loader**

Modify the dataclass and `load_trades()` query/constructor:

```python
@dataclass
class Trade:
    rowid: int
    trade_date: str
    trade_time: str
    stock_code: str
    stock_name: str
    side: str
    quantity: float
    amount: float
    price: float = 0.0
    net_amount: float = 0.0
    fees: float = 0.0
```

The SQL select must include `coalesce(price, 0) as price`, and the constructor must pass `price=number(row["price"])`.

- [ ] **Step 4: Implement deterministic IDs and the canonical cycle reducer**

Add `hashlib` and `json` imports, then implement these functions. Round stored money only at the output boundary; keep reducer state at full precision.

```python
def cycle_id_for_trade(trade: Trade) -> str:
    price = trade.price if trade.price else (trade.amount / trade.quantity if trade.quantity else 0.0)
    net_amount = trade.net_amount
    if abs(net_amount) <= 1e-9:
        net_amount = -buy_cost_after_fees(trade) if trade.side == "BUY" else sell_proceeds_after_fees(trade)
    facts = {
        "stock_code": trade.stock_code,
        "trade_date": trade.trade_date,
        "trade_time": trade.trade_time,
        "side": trade.side,
        "quantity": round(trade.quantity, 6),
        "price": round(price, 6),
        "net_amount": round(net_amount, 6),
    }
    digest = hashlib.sha1(
        json.dumps(facts, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:8]
    compact_date = re.sub(r"\D", "", trade.trade_date)
    return f"cyc_{trade.stock_code}_{compact_date}_{digest}"


def _cycle_event(trade: Trade) -> dict[str, Any]:
    price = trade.price if trade.price else (trade.amount / trade.quantity if trade.quantity else 0.0)
    return {
        "rowid": trade.rowid,
        "trade_date": trade.trade_date,
        "trade_time": trade.trade_time,
        "side": trade.side,
        "quantity": money(trade.quantity),
        "price": round(price, 4),
        "amount": money(trade.amount),
        "net_amount": money(trade.net_amount),
        "fees": money(trade.fees),
    }


def broker_like_cycles(trades: list[Trade], display_names: dict[str, str]) -> list[dict[str, Any]]:
    ordered = sorted(trades, key=lambda row: (row.trade_date, row.trade_time, row.rowid))
    same_day_reentry_after_sell = future_same_day_buys(ordered)
    active: dict[str, dict[str, Any]] = {}
    completed: list[dict[str, Any]] = []

    for trade in ordered:
        code = trade.stock_code
        if not code or trade.quantity <= 0:
            continue
        state = active.get(code)
        if trade.side == "BUY":
            if state is None:
                state = {
                    "cycle_id": cycle_id_for_trade(trade),
                    "status": "open",
                    "stock_code": code,
                    "stock_name": display_names.get(code, trade.stock_name),
                    "first_buy_date": trade.trade_date,
                    "first_buy_time": trade.trade_time,
                    "last_buy_date": trade.trade_date,
                    "last_buy_time": trade.trade_time,
                    "quantity": 0.0,
                    "rolling_cost": 0.0,
                    "buy_quantity": 0.0,
                    "sell_quantity": 0.0,
                    "buy_cost": 0.0,
                    "sell_proceeds": 0.0,
                    "events": [],
                }
                active[code] = state
            state["last_buy_date"] = trade.trade_date
            state["last_buy_time"] = trade.trade_time
            state["quantity"] += trade.quantity
            state["rolling_cost"] += buy_cost_after_fees(trade)
            state["buy_quantity"] += trade.quantity
            state["buy_cost"] += buy_cost_after_fees(trade)
            state["events"].append(_cycle_event(trade))
            continue

        if state is None:
            continue
        before_quantity = state["quantity"]
        before_cost = state["rolling_cost"]
        proceeds = sell_proceeds_after_fees(trade)
        state["quantity"] = max(before_quantity - trade.quantity, 0.0)
        state["rolling_cost"] -= proceeds
        state["sell_quantity"] += min(trade.quantity, before_quantity)
        state["sell_proceeds"] += proceeds
        state["events"].append(_cycle_event(trade))
        if state["quantity"] > 1e-9 or trade.rowid in same_day_reentry_after_sell:
            continue

        realized = -state["rolling_cost"]
        duration = holding_days(state["first_buy_date"], trade.trade_date)
        completed.append(
            {
                "cycle_id": state["cycle_id"],
                "status": "closed",
                "stock_code": code,
                "stock_name": state["stock_name"],
                "first_buy_date": state["first_buy_date"],
                "first_buy_time": state["first_buy_time"],
                "last_buy_date": state["last_buy_date"],
                "last_buy_time": state["last_buy_time"],
                "close_date": trade.trade_date,
                "close_time": trade.trade_time,
                "holding_days": duration,
                "buy_quantity": money(state["buy_quantity"]),
                "sell_quantity": money(state["sell_quantity"]),
                "open_quantity": 0.0,
                "buy_cost_after_fees": money(state["buy_cost"]),
                "sell_proceeds_after_fees": money(state["sell_proceeds"]),
                "rolling_cost_basis_after_fees": 0.0,
                "realized_pnl_after_fees": money(realized),
                "return_pct": round(realized / state["buy_cost"] * 100, 2) if state["buy_cost"] else None,
                "position_quantity_before_close": money(before_quantity),
                "close_trade_quantity": money(min(trade.quantity, before_quantity)),
                "close_cost_basis_before_sell": money(before_cost),
                "close_average_cost_before_sell": money(before_cost / before_quantity) if before_quantity else None,
                "close_sell_proceeds_after_fees": money(proceeds),
                "events": list(state["events"]),
            }
        )
        del active[code]

    open_cycles = []
    for state in active.values():
        open_cycles.append(
            {
                "cycle_id": state["cycle_id"],
                "status": "open",
                "stock_code": state["stock_code"],
                "stock_name": state["stock_name"],
                "first_buy_date": state["first_buy_date"],
                "first_buy_time": state["first_buy_time"],
                "last_buy_date": state["last_buy_date"],
                "last_buy_time": state["last_buy_time"],
                "close_date": "",
                "close_time": "",
                "holding_days": None,
                "buy_quantity": money(state["buy_quantity"]),
                "sell_quantity": money(state["sell_quantity"]),
                "open_quantity": money(state["quantity"]),
                "buy_cost_after_fees": money(state["buy_cost"]),
                "sell_proceeds_after_fees": money(state["sell_proceeds"]),
                "rolling_cost_basis_after_fees": money(state["rolling_cost"]),
                "realized_pnl_after_fees": None,
                "return_pct": None,
                "position_quantity_before_close": None,
                "close_trade_quantity": None,
                "close_cost_basis_before_sell": None,
                "close_average_cost_before_sell": None,
                "close_sell_proceeds_after_fees": None,
                "events": list(state["events"]),
            }
        )
    return sorted(
        [*completed, *open_cycles],
        key=lambda row: (row["first_buy_date"], row["first_buy_time"], row["stock_code"]),
    )
```

Add `import re` if it is not already present. Convert `broker_like_realized_lots()` into this closed-cycle compatibility projection so existing callers and cost assertions keep their current keys and sort order:

```python
def broker_like_realized_lots(trades: list[Trade], display_names: dict[str, str]) -> list[dict[str, Any]]:
    rows = []
    for cycle in broker_like_cycles(trades, display_names):
        if cycle["status"] != "closed":
            continue
        rows.append(
            {
                "stock_code": cycle["stock_code"],
                "stock_name": cycle["stock_name"],
                "buy_date": cycle["first_buy_date"],
                "last_buy_date": cycle["last_buy_date"],
                "sell_date": cycle["close_date"],
                "sell_time": cycle["close_time"],
                "close_trade_quantity": cycle["close_trade_quantity"],
                "cycle_buy_quantity": cycle["buy_quantity"],
                "cycle_sell_quantity": cycle["sell_quantity"],
                "position_quantity_before_sell": cycle["position_quantity_before_close"],
                "broker_like_average_cost_before_sell": cycle["close_average_cost_before_sell"],
                "broker_like_cost_basis_before_sell": cycle["close_cost_basis_before_sell"],
                "sell_proceeds_after_fees": cycle["close_sell_proceeds_after_fees"],
                "broker_like_realized_pnl_after_fees": cycle["realized_pnl_after_fees"],
                "is_position_close": True,
                "cycle_id": cycle["cycle_id"],
                "holding_days": cycle["holding_days"],
                "return_pct": cycle["return_pct"],
            }
        )
    return sorted(
        rows,
        key=lambda row: (row["sell_date"], row["sell_time"], row["stock_code"]),
        reverse=True,
    )
```

- [ ] **Step 5: Run focused and full ledger tests**

Run:

```bash
python3 -m unittest tests.test_ledger_analytics.BrokerLikeCyclesTest tests.test_ledger_analytics.RollingCostPositionsTest -v
```

Expected: all cycle and existing cost-basis tests pass, including the `-20,318.67` 波长光电 regression.

- [ ] **Step 6: Commit the cycle engine**

Run:

```bash
git add scripts/ledger_analytics.py tests/test_ledger_analytics.py
git diff --cached --check
git commit -m "Add canonical broker-like trade cycles"
```

Expected: only the analytics module and its tests are committed.

---

### Task 2: Ability Metrics and Date-Window Analytics

**Files:**
- Create: `scripts/personal_site_metrics.py`
- Create: `tests/test_personal_site_metrics.py`

**Interfaces:**
- Consumes: canonical cycle dictionaries, trade dictionaries or `Trade` objects, and cash-adjustment dictionaries or `CashAdjustment` objects.
- Produces: `DateWindow`, `resolve_window()`, `shift_period()`, `summarize_cycles()`, `summarize_period()`, and `period_stock_results()`.
- `summarize_cycles()` returns `closed_cycles`, `winning_cycles`, `losing_cycles`, `win_rate`, `average_payoff_ratio`, `average_payoff_ratio_state`, `profit_factor`, `profit_factor_state`, `expectancy`, `average_holding_days`, and `median_holding_days`.

- [ ] **Step 1: Write failing metric and boundary tests**

Create `tests/test_personal_site_metrics.py` with these deterministic fixtures:

```python
#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from personal_site_metrics import (  # noqa: E402
    DateWindow,
    period_stock_results,
    resolve_window,
    shift_period,
    summarize_cycles,
    summarize_period,
)


def cycle(code: str, close_date: str, pnl: float, days: int, status: str = "closed") -> dict:
    return {
        "cycle_id": f"{code}-{close_date}-{pnl}",
        "status": status,
        "stock_code": code,
        "stock_name": code,
        "close_date": close_date if status == "closed" else "",
        "realized_pnl_after_fees": pnl if status == "closed" else None,
        "holding_days": days if status == "closed" else None,
    }


class AbilitySummaryTest(unittest.TestCase):
    def test_closed_cycles_define_all_ability_metrics(self) -> None:
        rows = [
            cycle("000001", "2026-07-01", 100, 2),
            cycle("000002", "2026-07-02", -50, 4),
            cycle("000003", "2026-07-03", 25, 6),
            cycle("000004", "", 0, 0, status="open"),
        ]

        result = summarize_cycles(rows)

        self.assertEqual(result["closed_cycles"], 3)
        self.assertEqual(result["win_rate"], 66.67)
        self.assertEqual(result["average_payoff_ratio"], 1.25)
        self.assertEqual(result["profit_factor"], 2.5)
        self.assertEqual(result["expectancy"], 25.0)
        self.assertEqual(result["average_holding_days"], 4.0)
        self.assertEqual(result["median_holding_days"], 4.0)

    def test_ratio_states_do_not_emit_infinity(self) -> None:
        no_losses = summarize_cycles([cycle("000001", "2026-07-01", 100, 2)])
        no_wins = summarize_cycles([cycle("000001", "2026-07-01", -100, 2)])
        empty = summarize_cycles([])

        self.assertEqual(no_losses["profit_factor_state"], "no_losses")
        self.assertIsNone(no_losses["profit_factor"])
        self.assertEqual(no_wins["average_payoff_ratio_state"], "no_wins")
        self.assertEqual(no_wins["profit_factor"], 0.0)
        self.assertEqual(empty["win_rate_state"], "no_samples")


class DateWindowTest(unittest.TestCase):
    def test_day_week_month_year_and_custom_boundaries(self) -> None:
        minimum = date(2025, 12, 15)
        maximum = date(2026, 7, 10)

        self.assertEqual(resolve_window("day", "2026-07-10", "", "", minimum, maximum).label, "2026-07-10")
        week = resolve_window("week", "2026-07-06", "", "", minimum, maximum)
        self.assertEqual((week.start, week.end), (date(2026, 7, 6), date(2026, 7, 12)))
        month = resolve_window("month", "2026-02", "", "", minimum, maximum)
        self.assertEqual((month.start, month.end), (date(2026, 2, 1), date(2026, 2, 28)))
        year = resolve_window("year", "2026", "", "", minimum, maximum)
        self.assertEqual((year.start, year.end), (date(2026, 1, 1), date(2026, 12, 31)))
        custom = resolve_window("custom", "", "2026-01-01", "2026-07-10", minimum, maximum)
        self.assertEqual(custom.label, "2026-01-01 至 2026-07-10")
        self.assertEqual(shift_period("month", "2026-01", -1), "2025-12")

    def test_invalid_or_out_of_bounds_custom_range_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "结束日期不能早于开始日期"):
            resolve_window("custom", "", "2026-07-10", "2026-07-01", date(2026, 1, 1), date(2026, 7, 10))
        with self.assertRaisesRegex(ValueError, "超出底账日期范围"):
            resolve_window("custom", "", "2025-12-31", "2026-07-01", date(2026, 1, 1), date(2026, 7, 10))


class PeriodSummaryTest(unittest.TestCase):
    def test_cycles_use_close_date_while_trades_adjustments_and_fees_use_event_date(self) -> None:
        cycles = [
            cycle("000001", "2026-07-02", 100, 5),
            cycle("000002", "2026-06-30", -40, 2),
        ]
        trades = [
            {"trade_date": "2026-07-01", "stock_code": "000001", "fees": 2.5},
            {"trade_date": "2026-06-30", "stock_code": "000002", "fees": 3.0},
        ]
        adjustments = [
            {"trade_date": "2026-07-03", "stock_code": "000001", "stock_name": "A", "net_amount": 8.0},
            {"trade_date": "2026-06-30", "stock_code": "000002", "stock_name": "B", "net_amount": 5.0},
        ]
        window = DateWindow("custom", "2026-07-01 至 2026-07-03", date(2026, 7, 1), date(2026, 7, 3), "")

        summary = summarize_period(cycles, trades, adjustments, window)
        stocks = period_stock_results(cycles, adjustments, window)

        self.assertEqual(summary["realized_pnl"], 108.0)
        self.assertEqual(summary["closed_cycles"], 1)
        self.assertEqual(summary["fees"], 2.5)
        self.assertEqual(summary["stock_count"], 1)
        self.assertEqual(stocks[0]["total_pnl"], 108.0)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests and confirm the module is missing**

Run:

```bash
python3 -m unittest tests.test_personal_site_metrics -v
```

Expected: import failure for `personal_site_metrics`.

- [ ] **Step 3: Implement the date window and metric contracts**

Create `scripts/personal_site_metrics.py` around this public contract:

```python
from __future__ import annotations

import calendar
import re
import statistics
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any


@dataclass(frozen=True)
class DateWindow:
    grain: str
    label: str
    start: date | None
    end: date | None
    period: str

    def contains(self, value: str) -> bool:
        if self.start is None or self.end is None:
            return True
        try:
            current = date.fromisoformat(value)
        except ValueError:
            return False
        return self.start <= current <= self.end


def _value(record: Any, key: str, default: Any = None) -> Any:
    if isinstance(record, dict):
        return record.get(key, default)
    return getattr(record, key, default)


def _round(value: float) -> float:
    return round(value + 0.0, 2)


def summarize_cycles(cycles: list[dict[str, Any]]) -> dict[str, Any]:
    closed = [row for row in cycles if row.get("status") == "closed"]
    wins = [float(row["realized_pnl_after_fees"]) for row in closed if float(row["realized_pnl_after_fees"]) > 0]
    losses = [float(row["realized_pnl_after_fees"]) for row in closed if float(row["realized_pnl_after_fees"]) < 0]
    durations = [float(row["holding_days"]) for row in closed if row.get("holding_days") is not None]
    no_samples = not closed
    payoff_state = "no_samples" if no_samples else "no_losses" if not losses else "no_wins" if not wins else "value"
    factor_state = "no_samples" if no_samples else "no_losses" if not losses else "value"
    payoff = None if payoff_state != "value" else _round((sum(wins) / len(wins)) / abs(sum(losses) / len(losses)))
    factor = None if factor_state in {"no_samples", "no_losses"} else _round(sum(wins) / abs(sum(losses))) if losses else None
    return {
        "closed_cycles": len(closed),
        "winning_cycles": len(wins),
        "losing_cycles": len(losses),
        "win_rate": None if no_samples else _round(len(wins) / len(closed) * 100),
        "win_rate_state": "no_samples" if no_samples else "value",
        "average_payoff_ratio": payoff,
        "average_payoff_ratio_state": payoff_state,
        "profit_factor": factor,
        "profit_factor_state": factor_state,
        "expectancy": None if no_samples else _round(sum(float(row["realized_pnl_after_fees"]) for row in closed) / len(closed)),
        "expectancy_state": "no_samples" if no_samples else "value",
        "average_holding_days": None if not durations else _round(statistics.fmean(durations)),
        "median_holding_days": None if not durations else _round(float(statistics.median(durations))),
    }
```

Add these strict date helpers. A named period may extend beyond the first/last transaction date as long as it overlaps the ledger; a custom range must be fully inside the ledger bounds.

```python
def _iso(value: str, message: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(message) from exc


def _month_period(anchor: date) -> str:
    return f"{anchor.year:04d}-{anchor.month:02d}"


def _period_window(grain: str, period: str) -> DateWindow:
    if grain == "day":
        current = _iso(period, "日期格式无效")
        return DateWindow(grain, current.isoformat(), current, current, current.isoformat())
    if grain == "week":
        current = _iso(period, "周起始日期格式无效")
        start = current - timedelta(days=current.weekday())
        end = start + timedelta(days=6)
        return DateWindow(grain, f"{start.isoformat()} 至 {end.isoformat()}", start, end, start.isoformat())
    if grain == "month":
        if not re.fullmatch(r"\d{4}-\d{2}", period):
            raise ValueError("月份格式无效")
        year, month = (int(value) for value in period.split("-"))
        start = date(year, month, 1)
        end = date(year, month, calendar.monthrange(year, month)[1])
        return DateWindow(grain, period, start, end, period)
    if grain == "year":
        if not re.fullmatch(r"\d{4}", period):
            raise ValueError("年份格式无效")
        year = int(period)
        return DateWindow(grain, period, date(year, 1, 1), date(year, 12, 31), period)
    raise ValueError("不支持的时间粒度")


def resolve_window(
    grain: str,
    period: str,
    start_text: str,
    end_text: str,
    ledger_min: date,
    ledger_max: date,
) -> DateWindow:
    if grain == "all":
        return DateWindow("all", "全部历史", None, None, "")
    if grain == "custom":
        if not start_text or not end_text:
            raise ValueError("请输入完整的开始和结束日期")
        start = _iso(start_text, "开始日期格式无效")
        end = _iso(end_text, "结束日期格式无效")
        if end < start:
            raise ValueError("结束日期不能早于开始日期")
        if start < ledger_min or end > ledger_max:
            raise ValueError("所选日期超出底账日期范围")
        return DateWindow(grain, f"{start.isoformat()} 至 {end.isoformat()}", start, end, "")
    anchor = period
    if not anchor:
        anchor = (
            ledger_max.isoformat()
            if grain in {"day", "week"}
            else _month_period(ledger_max)
            if grain == "month"
            else str(ledger_max.year)
        )
    window = _period_window(grain, anchor)
    if window.end is not None and window.start is not None and (window.end < ledger_min or window.start > ledger_max):
        raise ValueError("所选周期超出底账日期范围")
    return window


def shift_period(grain: str, period: str, delta: int) -> str:
    if grain in {"day", "week"}:
        current = _iso(period, "日期格式无效")
        days = delta if grain == "day" else delta * 7
        return (current + timedelta(days=days)).isoformat()
    if grain == "month":
        if not re.fullmatch(r"\d{4}-\d{2}", period):
            raise ValueError("月份格式无效")
        year, month = (int(value) for value in period.split("-"))
        index = year * 12 + month - 1 + delta
        return f"{index // 12:04d}-{index % 12 + 1:02d}"
    if grain == "year":
        if not re.fullmatch(r"\d{4}", period):
            raise ValueError("年份格式无效")
        return str(int(period) + delta)
    raise ValueError("当前粒度不支持前后导航")
```

Implement period aggregation with this exact inclusion rule:

```python
def summarize_period(
    cycles: list[dict[str, Any]],
    trades: list[Any],
    adjustments: list[Any],
    window: DateWindow,
) -> dict[str, Any]:
    closed = [row for row in cycles if row.get("status") == "closed" and window.contains(str(row.get("close_date") or ""))]
    event_trades = [row for row in trades if window.contains(str(_value(row, "trade_date", "")))]
    event_adjustments = [row for row in adjustments if window.contains(str(_value(row, "trade_date", "")))]
    ability = summarize_cycles(closed)
    cycle_pnl = sum(float(row.get("realized_pnl_after_fees") or 0) for row in closed)
    adjustment_pnl = sum(float(_value(row, "net_amount", 0) or 0) for row in event_adjustments)
    codes = {
        str(_value(row, "stock_code", ""))
        for row in event_trades
        if re.fullmatch(r"\d{6}", str(_value(row, "stock_code", "")))
    }
    return {
        "label": window.label,
        "realized_pnl": _round(cycle_pnl + adjustment_pnl),
        "closed_cycles": ability["closed_cycles"],
        "win_rate": ability["win_rate"],
        "win_rate_state": ability["win_rate_state"],
        "profit_factor": ability["profit_factor"],
        "profit_factor_state": ability["profit_factor_state"],
        "fees": _round(sum(float(_value(row, "fees", 0) or 0) for row in event_trades)),
        "stock_count": len(codes),
    }
```

Add the per-stock aggregation using the same window:

```python
def period_stock_results(
    cycles: list[dict[str, Any]],
    adjustments: list[Any],
    window: DateWindow,
) -> list[dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}

    def ensure(code: str, name: str) -> dict[str, Any]:
        return rows.setdefault(
            code,
            {
                "stock_code": code,
                "stock_name": name,
                "cycle_pnl": 0.0,
                "cash_adjustments": 0.0,
                "total_pnl": 0.0,
                "closed_cycles": 0,
            },
        )

    for cycle in cycles:
        if cycle.get("status") != "closed" or not window.contains(str(cycle.get("close_date") or "")):
            continue
        item = ensure(str(cycle.get("stock_code") or ""), str(cycle.get("stock_name") or ""))
        item["cycle_pnl"] += float(cycle.get("realized_pnl_after_fees") or 0)
        item["closed_cycles"] += 1
    for adjustment in adjustments:
        if not window.contains(str(_value(adjustment, "trade_date", ""))):
            continue
        item = ensure(
            str(_value(adjustment, "stock_code", "")),
            str(_value(adjustment, "stock_name", "")),
        )
        item["cash_adjustments"] += float(_value(adjustment, "net_amount", 0) or 0)
    for item in rows.values():
        item["cycle_pnl"] = _round(item["cycle_pnl"])
        item["cash_adjustments"] = _round(item["cash_adjustments"])
        item["total_pnl"] = _round(item["cycle_pnl"] + item["cash_adjustments"])
    return sorted(rows.values(), key=lambda row: (-abs(row["total_pnl"]), row["stock_code"]))
```

- [ ] **Step 4: Run the focused tests**

Run:

```bash
python3 -m unittest tests.test_personal_site_metrics -v
```

Expected: all ability, boundary, and assignment tests pass.

- [ ] **Step 5: Commit the analytics layer**

Run:

```bash
git add scripts/personal_site_metrics.py tests/test_personal_site_metrics.py
git diff --cached --check
git commit -m "Add coach desk period analytics"
```

Expected: one self-contained analytics commit.

---

### Task 3: Validated Private State for Gate, Modes, and Discipline

**Files:**
- Modify: `.gitignore`
- Modify: `scripts/init_state.py`
- Create: `scripts/personal_site_state.py`
- Create: `templates/state/trading_modes.json`
- Create: `templates/state/discipline_feed.json`
- Create: `tests/test_personal_site_state.py`

**Interfaces:**
- Consumes: `state/trading_modes.json`, `state/discipline_feed.json`, and `cycles_by_id: dict[str, dict[str, Any]]`.
- Produces: `load_trading_modes(path: Path, cycles_by_id: dict[str, dict[str, Any]]) -> dict[str, Any]` and `load_discipline_feed(path: Path, now: datetime | None = None) -> dict[str, Any]`.
- Both loaders return an `error` key; malformed input returns a safe empty/default value and `状态数据待修复` text instead of raising through the site build.

- [ ] **Step 1: Write failing state tests**

Create tests covering missing, valid, malformed, and unsafe state:

```python
#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from init_state import init_state  # noqa: E402
from personal_site_state import load_discipline_feed, load_trading_modes  # noqa: E402


class TradingModeStateTest(unittest.TestCase):
    def test_missing_mode_file_returns_pending_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = load_trading_modes(Path(tmp) / "missing.json", {})
        self.assertIsNone(result["error"])
        self.assertEqual(result["coach_gate"]["status"], "pending")
        self.assertEqual(result["modes"], [])

    def test_three_valid_formal_samples_only_make_mode_review_ready(self) -> None:
        cycles = {
            f"cycle-{index}": {
                "cycle_id": f"cycle-{index}",
                "status": "closed",
                "stock_code": "000001",
                "realized_pnl_after_fees": index * 10,
                "return_pct": index,
                "holding_days": index,
            }
            for index in range(1, 5)
        }
        samples = [
            {
                "cycle_id": f"cycle-{index}",
                "evidence_type": "formal",
                "execution_result": "planned",
                "evidence_direction": "support",
                "note": "盘前绑定",
                "source_paths": [f"reports/run-{index}/coach_note.md"],
            }
            for index in range(1, 4)
        ]
        samples.append(
            {
                "cycle_id": "cycle-4",
                "evidence_type": "historical_reference",
                "execution_result": "insufficient",
                "evidence_direction": "indeterminate",
                "note": "旧周期",
                "source_paths": [],
            }
        )
        payload = {
            "version": 1,
            "coach_gate": {"status": "observe", "target_date": "2026-07-11", "reasons": [], "next_check": "等待模式触发", "source_path": ""},
            "mode_eligibility": [],
            "modes": [
                {
                    "id": "mode-a",
                    "name": "模式 A",
                    "status": "validating",
                    "version": "0.1",
                    "applicable_environment": ["环境"],
                    "trigger_conditions": ["触发"],
                    "execution_boundaries": ["边界"],
                    "invalidation_conditions": ["失效"],
                    "max_risk": "一单位",
                    "next_validation_requirement": "盘前绑定",
                    "samples": samples,
                }
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "trading_modes.json"
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            result = load_trading_modes(path, cycles)

        mode = result["modes"][0]
        self.assertTrue(mode["review_ready"])
        self.assertEqual(mode["status"], "validating")
        self.assertEqual(mode["valid_formal_sample_count"], 3)
        self.assertEqual(mode["historical_reference_count"], 1)

    def test_unsafe_source_path_returns_repair_state(self) -> None:
        payload = {
            "version": 1,
            "coach_gate": {"status": "pending", "target_date": None, "reasons": [], "next_check": "", "source_path": "/Users/private.md"},
            "mode_eligibility": [],
            "modes": [],
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "trading_modes.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            result = load_trading_modes(path, {})
        self.assertIn("状态数据待修复", result["error"])
        self.assertEqual(result["coach_gate"]["status"], "pending")


class DisciplineStateTest(unittest.TestCase):
    def test_only_current_active_messages_are_returned(self) -> None:
        payload = {
            "version": 1,
            "messages": [
                {"id": "live", "status": "active", "level": "reminder", "scope": "global", "stock_code": "", "mode_id": "", "message": "先核验风险锚", "source_path": "reports/a.md", "effective_at": "2026-07-01T00:00:00+00:00", "expires_at": "2026-08-01T00:00:00+00:00", "created_at": "2026-07-01T00:00:00+00:00"},
                {"id": "draft", "status": "draft", "level": "reminder", "scope": "global", "stock_code": "", "mode_id": "", "message": "草稿", "source_path": "", "effective_at": "", "expires_at": "", "created_at": "2026-07-01T00:00:00+00:00"},
                {"id": "expired", "status": "active", "level": "red_card", "scope": "global", "stock_code": "", "mode_id": "", "message": "已过期", "source_path": "", "effective_at": "2026-06-01T00:00:00+00:00", "expires_at": "2026-06-30T00:00:00+00:00", "created_at": "2026-06-01T00:00:00+00:00"},
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "discipline_feed.json"
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            result = load_discipline_feed(path, datetime(2026, 7, 11, tzinfo=timezone.utc))
        self.assertEqual([row["id"] for row in result["messages"]], ["live"])


class StateInitializationTest(unittest.TestCase):
    def test_json_templates_are_initialized_without_overwriting_existing_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state"
            first = init_state(ROOT / "templates" / "state", state)
            second = init_state(ROOT / "templates" / "state", state)
        self.assertIn(("trading_modes.json", "created"), first)
        self.assertIn(("discipline_feed.json", "created"), first)
        self.assertIn(("trading_modes.json", "kept"), second)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run state tests and verify the missing module/templates failure**

Run:

```bash
python3 -m unittest tests.test_personal_site_state -v
```

Expected: import failure for `personal_site_state`.

- [ ] **Step 3: Add public empty templates and keep private JSON ignored**

Append these exceptions after the global `*.json` rule in `.gitignore`:

```gitignore
!templates/state/trading_modes.json
!templates/state/discipline_feed.json
```

Create `templates/state/trading_modes.json`:

```json
{
  "version": 1,
  "coach_gate": {
    "status": "pending",
    "target_date": null,
    "reasons": [],
    "next_check": "",
    "source_path": ""
  },
  "mode_eligibility": [],
  "modes": []
}
```

Create `templates/state/discipline_feed.json`:

```json
{
  "version": 1,
  "messages": []
}
```

Add both filenames to `STATE_FILES` in `scripts/init_state.py`. Do not use `--force` when initializing the real private state.

- [ ] **Step 4: Implement strict state loading and enrichment**

Create `scripts/personal_site_state.py` with these constants and fallback contracts:

```python
GATE_STATUSES = {"pending", "locked", "observe", "eligible"}
MODE_STATUSES = {"validating", "review", "replicable", "avoid"}
EXECUTION_RESULTS = {"planned", "violated", "insufficient"}
EVIDENCE_DIRECTIONS = {"support", "oppose", "indeterminate"}
EVIDENCE_TYPES = {"formal", "historical_reference"}


def default_trading_modes() -> dict[str, Any]:
    return {
        "version": 1,
        "coach_gate": {"status": "pending", "target_date": None, "reasons": [], "next_check": "", "source_path": ""},
        "mode_eligibility": [],
        "modes": [],
        "error": None,
    }


def default_discipline_feed() -> dict[str, Any]:
    return {"version": 1, "messages": [], "error": None}


def _is_project_relative(value: str) -> bool:
    candidate = Path(value)
    return not candidate.is_absolute() and ".." not in candidate.parts
```

`load_trading_modes()` must validate the allowed status sets, required list/string shapes, unique mode IDs, unique sample cycle IDs inside each mode, and every `source_path`/`source_paths` entry. Enrich each sample with `cycle_found` and `cycle`, then derive counts with this rule:

```python
valid_formal = [
    sample
    for sample in samples
    if sample["evidence_type"] == "formal"
    and sample["execution_result"] == "planned"
    and sample["evidence_direction"] in {"support", "oppose"}
    and sample["cycle_found"]
]
mode["valid_formal_sample_count"] = len(valid_formal)
mode["historical_reference_count"] = sum(
    sample["evidence_type"] == "historical_reference" for sample in samples
)
mode["review_ready"] = len(valid_formal) >= 3
```

Never mutate `mode["status"]` from a derived count. On `OSError`, `json.JSONDecodeError`, `TypeError`, or `ValueError`, return the corresponding default with `error` set to `状态数据待修复：<concise reason>`.

`load_discipline_feed()` must validate message enums and paths, keep only `status == "active"`, apply inclusive `effective_at` and exclusive `expires_at` bounds when present, and sort red cards before reminders, newest first inside each level.

- [ ] **Step 5: Run focused tests and initialize local private files**

Run:

```bash
python3 -m unittest tests.test_personal_site_state -v
python3 scripts/init_state.py
git status --short state
```

Expected: tests pass; the initializer reports the two JSON files as `created` or `kept`; `git status --short state` shows no private JSON because `state/**` remains ignored.

- [ ] **Step 6: Commit the structured-state layer**

Run:

```bash
git add .gitignore scripts/init_state.py scripts/personal_site_state.py templates/state/trading_modes.json templates/state/discipline_feed.json tests/test_personal_site_state.py
git diff --cached --check
git commit -m "Add structured trading coach state"
```

Expected: templates and loaders are committed; private `state/*.json` files are not staged.

---

### Task 4: Workbench Artifact Selection and Site-Data Composition

**Files:**
- Modify: `scripts/build_personal_site.py`
- Modify: `tests/test_personal_site.py`

**Interfaces:**
- Consumes: canonical cycles, metric functions, validated state loaders, timeline documents, and latest verified quotes.
- Produces: `infer_document_target_date()`, `resolve_workbench_target_date()`, `select_daily_document()`, and `extract_research_pool_candidates()`.
- Extends `build_data()` with `cycles`, `ability`, `ledger_dataset`, `trading_state`, `discipline_feed`, `workbench`, and cycle-first `stories` inputs.

- [ ] **Step 1: Write failing artifact-selection tests**

Add these tests to `tests/test_personal_site.py`:

```python
class WorkbenchArtifactTest(unittest.TestCase):
    def test_explicit_target_date_beats_run_directory_date(self) -> None:
        markdown = "# 2026-07-13 明日交易预案\n\n目标交易日：2026-07-13\n"
        result = site.infer_document_target_date("2026-07-13 明日交易预案", markdown, "2026-07-11")
        self.assertEqual(result, "2026-07-13")

    def test_missing_target_document_falls_back_and_marks_stale(self) -> None:
        documents = [
            {"category": "trade_plan", "target_date": "2026-07-10", "date": "2026-07-10", "mtime": "2026-07-10 18:00", "title": "旧预案"}
        ]
        selected = site.select_daily_document(documents, "trade_plan", "2026-07-11")
        self.assertEqual(selected["document"]["title"], "旧预案")
        self.assertTrue(selected["stale"])
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

    def test_short_pool_stays_short_instead_of_inventing_candidates(self) -> None:
        markdown = "| 代码 | 名称 | 题材 | 买点 |\n| --- | --- | --- | --- |\n| 300001 | 候选1 | 先进封装 | 20日线 |"
        self.assertEqual(len(site.extract_research_pool_candidates(markdown)), 1)
```

- [ ] **Step 2: Run the focused tests and verify missing helpers**

Run:

```bash
python3 -m unittest tests.test_personal_site.WorkbenchArtifactTest -v
```

Expected: attribute failures for the four new helper functions.

- [ ] **Step 3: Implement target-date and fallback selection**

Add `csv`, `date`, and the new local-module imports. Use explicit labeled dates first, then title dates, then path dates:

```python
def infer_document_target_date(title: str, markdown_text: str, fallback_date: str) -> str:
    normalized = markdown_text[:4000]
    labeled = re.search(r"(?:目标交易日|交易日期|适用日期)\s*[：:]\s*(20\d{2})[-年/](\d{1,2})[-月/](\d{1,2})日?", normalized)
    if labeled:
        year, month, day = (int(value) for value in labeled.groups())
        return date(year, month, day).isoformat()
    for source in (title, normalized[:800]):
        expanded = re.search(r"(20\d{2})[-年/](\d{1,2})[-月/](\d{1,2})日?", source)
        if expanded:
            year, month, day = (int(value) for value in expanded.groups())
            return date(year, month, day).isoformat()
        compact = re.search(r"(?<!\d)(20\d{6})(?!\d)", source)
        if compact:
            value = compact.group(1)
            return date(int(value[:4]), int(value[4:6]), int(value[6:])).isoformat()
    return fallback_date


def resolve_workbench_target_date(documents: list[dict[str, Any]], as_of_date: date) -> str:
    explicit = [
        date.fromisoformat(item["target_date"])
        for item in documents
        if item.get("category") in {"trade_plan", "research_pool"} and item.get("target_date")
    ]
    return max([as_of_date, *explicit]).isoformat()


def select_daily_document(documents: list[dict[str, Any]], category: str, target_date: str) -> dict[str, Any]:
    candidates = [item for item in documents if item.get("category") == category]
    exact = next((item for item in candidates if item.get("target_date") == target_date), None)
    selected = exact or (candidates[0] if candidates else None)
    return {
        "document": selected,
        "target_date": str((selected or {}).get("target_date") or ""),
        "stale": bool(selected and selected.get("target_date") != target_date),
    }
```

Update `collect_timeline_documents()` to store `target_date` for every document. Preserve `date` as the artifact/run date for timeline ordering.

- [ ] **Step 4: Parse research-pool tables structurally**

Use `csv.reader([raw_line], delimiter="|")`, normalize header labels, and require both stock code and name columns. Map accepted synonyms exactly:

```python
POOL_COLUMNS = {
    "stock_code": {"代码", "证券代码", "股票代码"},
    "stock_name": {"名称", "证券名称", "股票名称"},
    "theme": {"题材", "题材篮子", "产业方向", "方向"},
    "buy_point": {"买点", "买点类型", "触发", "触发条件"},
}


def extract_research_pool_candidates(markdown_text: str) -> list[dict[str, str]]:
    parsed = []
    for raw_line in markdown_text.splitlines():
        if raw_line.count("|") < 2:
            continue
        row = next(csv.reader([raw_line.strip().strip("|")], delimiter="|"))
        parsed.append([cell.strip() for cell in row])
    for header_index, header in enumerate(parsed):
        columns = {}
        for field, aliases in POOL_COLUMNS.items():
            columns[field] = next((index for index, cell in enumerate(header) if cell in aliases), None)
        if columns["stock_code"] is None or columns["stock_name"] is None:
            continue
        output = []
        for row in parsed[header_index + 2 :]:
            if len(row) <= max(index for index in columns.values() if index is not None):
                continue
            code = row[columns["stock_code"]]
            name = row[columns["stock_name"]]
            if not re.fullmatch(r"\d{6}", code) or not name:
                continue
            output.append(
                {
                    "stock_code": code,
                    "stock_name": name,
                    "theme": row[columns["theme"]] if columns["theme"] is not None else "待核验",
                    "buy_point": row[columns["buy_point"]] if columns["buy_point"] is not None else "待核验",
                }
            )
        return output
    return []
```

- [ ] **Step 5: Compose one shared site-data graph**

Extend the existing `build_data(sqlite_path, reports_dir, output_dir, state_dir=DEFAULT_STATE)` and `write_site(sqlite_path=DEFAULT_SQLITE, reports_dir=DEFAULT_REPORTS, output_dir=DEFAULT_OUTPUT, state_dir=DEFAULT_STATE)` declarations with the final parameter `as_of_date: date | None = None`. `write_site()` passes it as the fifth argument to `build_data()`; no wrapper function is introduced.

Add `from dataclasses import asdict`, then load canonical facts before closing SQLite and compose these exact keys:

```python
canonical_trades = load_trades(conn)
cash_adjustments = load_cash_adjustments(conn)
display_names = display_names_by_code(canonical_trades, cash_adjustments)
cycles = broker_like_cycles(canonical_trades, display_names)
ability = summarize_cycles(cycles)
trading_state = load_trading_modes(state_dir / "trading_modes.json", {row["cycle_id"]: row for row in cycles})
discipline_feed = load_discipline_feed(state_dir / "discipline_feed.json")
target_date = resolve_workbench_target_date(documents, as_of_date or datetime.now().date())
selected_plan = select_daily_document(documents, "trade_plan", target_date)
selected_pool = select_daily_document(documents, "research_pool", target_date)
pool_document = selected_pool["document"]
selected_pool["candidates"] = extract_research_pool_candidates(
    str((pool_document or {}).get("markdown") or "")
)
ledger_dataset = {
    "bounds": {
        "minimum": str(summary.get("first_trade_date") or ""),
        "maximum": str(summary.get("latest_trade_date") or ""),
    },
    "cycles": cycles,
    "trades": trades,
    "adjustments": [asdict(row) for row in cash_adjustments],
}
```

Return `workbench={"target_date": target_date, "trade_plan": selected_plan, "research_pool": selected_pool}`. Keep current `mark_to_market` calculation and current broker-like realized totals intact. Build stories from this same `cycles` list in Task 7 rather than re-running cycle logic.

- [ ] **Step 6: Run focused and existing integration tests**

Run:

```bash
python3 -m unittest tests.test_personal_site.WorkbenchArtifactTest tests.test_personal_site.SiteGenerationTests -v
```

Expected: artifact tests pass and existing site generation remains green.

- [ ] **Step 7: Commit site-data composition**

Run:

```bash
git add scripts/build_personal_site.py tests/test_personal_site.py
git diff --cached --check
git commit -m "Compose coach desk workbench data"
```

Expected: only generator composition and its tests are committed.

---

### Task 5: Redesign the Homepage as the Coach Desk

**Files:**
- Modify: `scripts/build_personal_site.py`
- Modify: `templates/personal_site/site.css`
- Modify: `tests/test_personal_site.py`

**Interfaces:**
- Consumes: `mark_to_market`, `summary`, `ability`, `trading_state`, `discipline_feed`, `workbench`, and `open_positions` from Task 4.
- Produces: a homepage with account facts, an inline ability rail, gate/eligibility states, plan, all parsed pool candidates, holdings, and discipline feed.
- DOM contracts used by browser QA: `[data-account-total]`, `[data-ability-rail]`, `[data-coach-gate]`, `[data-mode-eligibility]`, `[data-pool-scroll]`, `[data-pool-row]`, and `[data-discipline-feed]`.

- [ ] **Step 1: Add failing homepage acceptance assertions**

Extend the generator fixture with a 15-row pool and empty discipline state, then assert:

```python
index_html = (output / "index.html").read_text(encoding="utf-8")
self.assertIn('data-account-total', index_html)
self.assertIn('data-ability-rail', index_html)
self.assertIn('data-coach-gate', index_html)
self.assertIn('data-mode-eligibility', index_html)
self.assertEqual(index_html.count('data-pool-row'), 15)
self.assertIn('data-pool-scroll', index_html)
self.assertIn('data-discipline-feed', index_html)
self.assertIn("暂无已发布纪律消息", index_html)
self.assertIn("交易股票数", index_html)
self.assertIn("完整周期", index_html)
self.assertIn("平均持股自然日", index_html)
self.assertNotIn("最近训练日", index_html)
```

Add a second fixture with a stale plan and assert that its source date, `可能过期`, and document link are all present.

- [ ] **Step 2: Run the homepage integration test and confirm it fails**

Run:

```bash
python3 -m unittest tests.test_personal_site.SiteGenerationTests.test_write_site_generates_multiple_pages_and_unified_markdown_details -v
```

Expected: failure because the old homepage still contains `最近训练日` and lacks the new DOM contracts.

- [ ] **Step 3: Replace the equal metric boxes with an asymmetric fact band**

Replace `metrics_html()` with `render_account_facts()` and a value-state formatter. The markup must have one dominant total and no separate boxed ability section:

```python
def ability_value(value: Any, state: str, suffix: str = "") -> str:
    if state == "no_samples":
        return "待积累"
    if state == "no_losses":
        return "无亏损样本"
    if state == "no_wins":
        return "无盈利样本"
    if value is None:
        return "待积累"
    return f"{number(value):.2f}{suffix}"


def render_account_facts(data: dict[str, Any]) -> str:
    mark = data["mark_to_market"]
    ability = data["ability"]
    quote_note = (
        f"行情截至 {mark['quote_date']}，费用已进入成本口径"
        if mark["complete"] and mark.get("quote_date")
        else f"缺少行情：{', '.join(mark['missing_quote_codes']) or '待核验'}"
    )
    return f"""<section class="account-facts" aria-label="账户事实与交易能力">
      <div class="account-total"><span>总盈亏（含持仓）</span><strong data-account-total class="mono {value_class(mark['total_pnl'])}">{money(mark['total_pnl'])}</strong><small>{esc(quote_note)}</small></div>
      <div class="account-fact-grid">
        <div><span>已实现盈亏</span><strong class="mono {value_class(mark['realized_pnl'])}">{money(mark['realized_pnl'])}</strong></div>
        <div><span>持仓浮动盈亏</span><strong class="mono {value_class(mark['unrealized_pnl'])}">{money(mark['unrealized_pnl'])}</strong></div>
        <div><span>总费用</span><strong class="mono">{money(data['summary'].get('total_fees'))}</strong></div>
        <div><span>交易股票数</span><strong class="mono">{int(number(data['summary'].get('stock_count')))}</strong></div>
      </div>
      <div class="ability-rail" data-ability-rail>
        <div><span>样本与赢面</span><strong class="mono">{ability['closed_cycles']} 周期 · {ability_value(ability['win_rate'], ability['win_rate_state'], '%')}</strong></div>
        <div><span>盈利质量</span><strong class="mono">盈亏比 {ability_value(ability['average_payoff_ratio'], ability['average_payoff_ratio_state'])} · 利润因子 {ability_value(ability['profit_factor'], ability['profit_factor_state'])}</strong></div>
        <div><span>周期与持有</span><strong class="mono">期望 {money(ability['expectancy']) if ability['expectancy'] is not None else '待积累'} · 平均 {ability_value(ability['average_holding_days'], 'value' if ability['average_holding_days'] is not None else 'no_samples')} 天 · 中位 {ability_value(ability['median_holding_days'], 'value' if ability['median_holding_days'] is not None else 'no_samples')} 天</strong></div>
      </div>
    </section>"""
```

- [ ] **Step 4: Render structured coach gate and mode eligibility**

Map statuses only through this copy table:

```python
GATE_COPY = {
    "pending": "待核验",
    "locked": "风险锁定",
    "observe": "仅观察",
    "eligible": "可进入验证",
}
```

Render gate reasons, `next_check`, target date, and relative source link. Render mode eligibility independently; an empty eligibility list displays `当前没有已发布的模式资格判断`. If `trading_state["error"]` is set, show `状态数据待修复` inside this section while leaving account facts and workbench visible.

- [ ] **Step 5: Render the three-column workbench and discipline feed**

The workbench must follow this structure:

```html
<section class="today-workbench" aria-labelledby="today-workbench-title">
  <div class="plan-pane" data-trade-plan></div>
  <div class="pool-pane"><div class="pool-scroll" data-pool-scroll></div></div>
  <div class="position-pane"><div class="position-list"></div><div class="discipline-feed" data-discipline-feed aria-live="polite"></div></div>
</section>
```

Plan and pool headings must display the workbench target date. A fallback displays the selected document target date and `可能过期`. Every candidate row includes name, code, theme, and buy-point type and links the row to the selected research document. Render all parsed candidates; never slice to 15 and never pad to 15. Discipline messages use chat rows with source/time metadata; empty input renders exactly `暂无已发布纪律消息`.

- [ ] **Step 6: Add the homepage layout styles**

Add an asymmetric grid with stable dimensions and internal scroll:

```css
.account-facts { display: grid; grid-template-columns: minmax(280px, .9fr) minmax(0, 2.1fr); border: 1px solid var(--line-strong); background: var(--surface); }
.account-total { grid-row: 1 / span 2; min-width: 0; display: grid; align-content: center; gap: 8px; padding: 22px; border-right: 1px solid var(--line-strong); }
.account-total strong { white-space: nowrap; font-size: 34px; line-height: 1.1; }
.account-fact-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); border-bottom: 1px solid var(--line); }
.account-fact-grid > div { min-width: 0; display: grid; gap: 6px; padding: 14px 16px; border-left: 1px solid var(--line); }
.account-fact-grid > div:first-child { border-left: 0; }
.account-fact-grid strong { white-space: nowrap; font-size: 18px; }
.ability-rail { display: grid; grid-template-columns: 1fr 1.2fr 1.4fr; }
.ability-rail > div { min-width: 0; display: grid; gap: 4px; padding: 12px 16px; border-left: 1px solid var(--line); }
.ability-rail > div:first-child { border-left: 0; }
.today-workbench { display: grid; grid-template-columns: minmax(260px, .9fr) minmax(390px, 1.35fr) minmax(300px, 1fr); gap: 14px; align-items: stretch; }
.pool-scroll { height: 480px; overflow: auto; scrollbar-gutter: stable; }
.discipline-feed { max-height: 240px; overflow: auto; scrollbar-gutter: stable; }
.discipline-message { max-width: 92%; padding: 9px 11px; border-left: 2px solid var(--blue); background: var(--surface-2); }
```

At `max-width: 980px`, stack the account total above facts and use two workbench columns; at `max-width: 680px`, use one column, two account facts per row, and a fixed `24px` `h1`. Do not use viewport-scaled font sizes.

- [ ] **Step 7: Run homepage and full Python tests**

Run:

```bash
python3 -m unittest tests.test_personal_site -v
python3 -m unittest discover -s tests -v
```

Expected: homepage assertions pass and no existing timeline/rules behavior regresses.

- [ ] **Step 8: Commit the coach desk homepage**

Run:

```bash
git add scripts/build_personal_site.py templates/personal_site/site.css tests/test_personal_site.py
git diff --cached --check
git commit -m "Redesign homepage as trading coach desk"
```

Expected: the homepage is independently testable before ledger and story interactions are added.

---

### Task 6: URL-Restorable Ledger Time Filtering

**Files:**
- Modify: `scripts/build_personal_site.py`
- Create: `templates/personal_site/ledger.js`
- Create: `tests/test_ledger_filter.js`
- Modify: `tests/test_personal_site.py`

**Interfaces:**
- Consumes: `ledger_dataset` from Task 4 and Python period semantics from Task 2.
- Produces browser API: `resolveWindow(params, bounds)`, `shiftPeriod(grain, period, delta)`, `summarizePeriod(dataset, window)`, and `stockResults(dataset, window)` on `globalThis.PersonalSiteLedger` and `module.exports`.
- Query keys: `grain`, `period`, `from`, `to`, `side`, `q`, `page`, `pnlq`, and `pnlpage`.
- DOM contracts: `[data-ledger-grain]`, `[data-ledger-prev]`, `[data-ledger-next]`, `[data-ledger-period-label]`, `#ledgerFrom`, `#ledgerTo`, `[data-ledger-apply-custom]`, `[data-period-realized]`, `[data-period-cycles]`, `[data-period-win-rate]`, `[data-period-profit-factor]`, `[data-period-fees]`, `[data-period-stocks]`, and `#ledgerData`.

- [ ] **Step 1: Write failing browser-calculation tests**

Create `tests/test_ledger_filter.js` using the Node test runner:

```javascript
const test = require('node:test');
const assert = require('node:assert/strict');
const ledger = require('../templates/personal_site/ledger.js');

const dataset = {
  bounds: {minimum: '2026-06-01', maximum: '2026-07-10'},
  cycles: [
    {cycle_id: 'june', status: 'closed', stock_code: '000001', stock_name: '六月', close_date: '2026-06-30', realized_pnl_after_fees: -40, holding_days: 2},
    {cycle_id: 'july', status: 'closed', stock_code: '300260', stock_name: '新莱应材', close_date: '2026-07-10', realized_pnl_after_fees: 100, holding_days: 5},
    {cycle_id: 'open', status: 'open', stock_code: '301421', stock_name: '波长光电', close_date: '', realized_pnl_after_fees: null, holding_days: null}
  ],
  trades: [
    {trade_date: '2026-07-01', trade_time: '09:30:00', stock_code: '300260', stock_name: '新莱应材', side: 'BUY', quantity: 100, price: 10, amount: 1000, net_amount: -1002.5, fees: 2.5},
    {trade_date: '2026-06-30', trade_time: '10:00:00', stock_code: '000001', stock_name: '六月', side: 'SELL', quantity: 100, price: 9, amount: 900, net_amount: 897, fees: 3}
  ],
  adjustments: [
    {trade_date: '2026-07-03', stock_code: '300260', stock_name: '新莱应材', net_amount: 8}
  ]
};

test('month range uses cycle close dates and event dates', () => {
  const window = ledger.resolveWindow(new URLSearchParams('grain=month&period=2026-07'), dataset.bounds);
  const summary = ledger.summarizePeriod(dataset, window);
  assert.deepEqual([window.start, window.end], ['2026-07-01', '2026-07-31']);
  assert.equal(summary.realized_pnl, 108);
  assert.equal(summary.closed_cycles, 1);
  assert.equal(summary.fees, 2.5);
  assert.equal(summary.stock_count, 1);
});

test('week starts Monday and custom includes both endpoints', () => {
  const week = ledger.resolveWindow(new URLSearchParams('grain=week&period=2026-07-06'), dataset.bounds);
  assert.deepEqual([week.start, week.end], ['2026-07-06', '2026-07-12']);
  const custom = ledger.resolveWindow(new URLSearchParams('grain=custom&from=2026-07-01&to=2026-07-10'), dataset.bounds);
  assert.equal(ledger.summarizePeriod(dataset, custom).realized_pnl, 108);
});

test('invalid custom range reports a field error', () => {
  assert.throws(
    () => ledger.resolveWindow(new URLSearchParams('grain=custom&from=2026-07-10&to=2026-07-01'), dataset.bounds),
    /结束日期不能早于开始日期/
  );
});

test('stock results add in-range adjustments to in-range closed cycles', () => {
  const window = ledger.resolveWindow(new URLSearchParams('grain=month&period=2026-07'), dataset.bounds);
  const rows = ledger.stockResults(dataset, window);
  assert.equal(rows[0].stock_code, '300260');
  assert.equal(rows[0].total_pnl, 108);
});
```

- [ ] **Step 2: Run Node tests and confirm the missing module failure**

Run:

```bash
node --test tests/test_ledger_filter.js
```

Expected: module-not-found error for `templates/personal_site/ledger.js`.

- [ ] **Step 3: Implement pure date and summary functions in `ledger.js`**

Use an IIFE that exports the same API in Node and browsers:

```javascript
(function (global) {
  'use strict';

  const round2 = value => Math.round((Number(value || 0) + Number.EPSILON) * 100) / 100;
  const inRange = (value, window) => !window.start || (value >= window.start && value <= window.end);
  const iso = value => new Date(`${value}T00:00:00Z`);
  const isoText = value => value.toISOString().slice(0, 10);

  function defaultPeriod(grain, maximum) {
    if (grain === 'day') return maximum;
    if (grain === 'week') {
      const current = iso(maximum);
      const weekday = (current.getUTCDay() + 6) % 7;
      current.setUTCDate(current.getUTCDate() - weekday);
      return isoText(current);
    }
    if (grain === 'month') return maximum.slice(0, 7);
    if (grain === 'year') return maximum.slice(0, 4);
    throw new Error('不支持的时间粒度');
  }

  function rangeForPeriod(grain, period) {
    if (grain === 'day') return {grain, period, label: period, start: period, end: period};
    if (grain === 'week') {
      const startDate = iso(period);
      const weekday = (startDate.getUTCDay() + 6) % 7;
      startDate.setUTCDate(startDate.getUTCDate() - weekday);
      const endDate = new Date(startDate);
      endDate.setUTCDate(endDate.getUTCDate() + 6);
      const start = isoText(startDate);
      const end = isoText(endDate);
      return {grain, period: start, label: `${start} 至 ${end}`, start, end};
    }
    if (grain === 'month') {
      if (!/^\d{4}-\d{2}$/.test(period)) throw new Error('月份格式无效');
      const [year, month] = period.split('-').map(Number);
      const end = new Date(Date.UTC(year, month, 0));
      return {grain, period, label: period, start: `${period}-01`, end: isoText(end)};
    }
    if (grain === 'year') {
      if (!/^\d{4}$/.test(period)) throw new Error('年份格式无效');
      return {grain, period, label: period, start: `${period}-01-01`, end: `${period}-12-31`};
    }
    throw new Error('不支持的时间粒度');
  }

  function shiftPeriod(grain, period, delta) {
    if (grain === 'day' || grain === 'week') {
      const current = iso(period);
      current.setUTCDate(current.getUTCDate() + delta * (grain === 'week' ? 7 : 1));
      return isoText(current);
    }
    if (grain === 'month') {
      const [year, month] = period.split('-').map(Number);
      const current = new Date(Date.UTC(year, month - 1 + delta, 1));
      return `${current.getUTCFullYear()}-${String(current.getUTCMonth() + 1).padStart(2, '0')}`;
    }
    if (grain === 'year') return String(Number(period) + delta);
    throw new Error('当前粒度不支持前后导航');
  }

  function resolveWindow(params, bounds) {
    const grain = params.get('grain') || 'all';
    if (grain === 'all') return {grain, period: '', label: '全部历史', start: null, end: null};
    const maximum = bounds.maximum;
    if (grain === 'custom') {
      const start = params.get('from') || '';
      const end = params.get('to') || '';
      if (!/^\d{4}-\d{2}-\d{2}$/.test(start) || !/^\d{4}-\d{2}-\d{2}$/.test(end)) throw new Error('请输入完整的开始和结束日期');
      if (end < start) throw new Error('结束日期不能早于开始日期');
      if (start < bounds.minimum || end > bounds.maximum) throw new Error('所选日期超出底账日期范围');
      return {grain, period: '', label: `${start} 至 ${end}`, start, end};
    }
    const period = params.get('period') || defaultPeriod(grain, maximum);
    const window = rangeForPeriod(grain, period);
    if (window.end < bounds.minimum || window.start > bounds.maximum) throw new Error('所选周期超出底账日期范围');
    return window;
  }

  function summarizePeriod(dataset, window) {
    const cycles = dataset.cycles.filter(row => row.status === 'closed' && inRange(row.close_date, window));
    const trades = dataset.trades.filter(row => inRange(row.trade_date, window));
    const adjustments = dataset.adjustments.filter(row => inRange(row.trade_date, window));
    const wins = cycles.filter(row => Number(row.realized_pnl_after_fees) > 0);
    const losses = cycles.filter(row => Number(row.realized_pnl_after_fees) < 0);
    const grossWins = wins.reduce((sum, row) => sum + Number(row.realized_pnl_after_fees), 0);
    const grossLosses = Math.abs(losses.reduce((sum, row) => sum + Number(row.realized_pnl_after_fees), 0));
    return {
      realized_pnl: round2(cycles.reduce((sum, row) => sum + Number(row.realized_pnl_after_fees || 0), 0) + adjustments.reduce((sum, row) => sum + Number(row.net_amount || 0), 0)),
      closed_cycles: cycles.length,
      win_rate: cycles.length ? round2(wins.length / cycles.length * 100) : null,
      win_rate_state: cycles.length ? 'value' : 'no_samples',
      profit_factor: losses.length ? round2(grossWins / grossLosses) : null,
      profit_factor_state: !cycles.length ? 'no_samples' : !losses.length ? 'no_losses' : 'value',
      fees: round2(trades.reduce((sum, row) => sum + Number(row.fees || 0), 0)),
      stock_count: new Set(trades.map(row => row.stock_code).filter(code => /^\d{6}$/.test(code))).size
    };
  }

  function stockResults(dataset, window) {
    const rows = new Map();
    const ensure = (code, name) => {
      if (!rows.has(code)) rows.set(code, {stock_code: code, stock_name: name || '', cycle_pnl: 0, cash_adjustments: 0, total_pnl: 0, closed_cycles: 0});
      return rows.get(code);
    };
    dataset.cycles.filter(row => row.status === 'closed' && inRange(row.close_date, window)).forEach(row => {
      const item = ensure(row.stock_code, row.stock_name);
      item.cycle_pnl += Number(row.realized_pnl_after_fees || 0);
      item.closed_cycles += 1;
    });
    dataset.adjustments.filter(row => inRange(row.trade_date, window)).forEach(row => {
      ensure(row.stock_code, row.stock_name).cash_adjustments += Number(row.net_amount || 0);
    });
    return Array.from(rows.values()).map(row => Object.assign({}, row, {cycle_pnl: round2(row.cycle_pnl), cash_adjustments: round2(row.cash_adjustments), total_pnl: round2(row.cycle_pnl + row.cash_adjustments)})).sort((left, right) => Math.abs(right.total_pnl) - Math.abs(left.total_pnl) || left.stock_code.localeCompare(right.stock_code));
  }

  const api = {resolveWindow, shiftPeriod, summarizePeriod, stockResults};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  global.PersonalSiteLedger = api;
  if (typeof document !== 'undefined') document.addEventListener('DOMContentLoaded', initLedgerPage);
})(globalThis);
```

The definitions above keep browser timezone out of range boundaries. Add `initLedgerPage()` only after the pure Node tests pass so DOM work cannot mask formula failures.

- [ ] **Step 4: Render a fixed account header and dynamic period workspace**

Import `Sequence` from `typing`, change `page_shell()` to accept `extra_scripts: Sequence[str] = ()`, and append each escaped script path after `site.js`. Call it for ledger with `("assets/ledger.js",)` and copy `ledger.js` in `write_site()`.

Replace the ledger body with:

```html
<section data-current-account-facts></section>
<section class="ledger-controls" data-ledger-app>
  <div class="segmented" aria-label="时间粒度"></div>
  <div class="period-navigation"><button data-ledger-prev aria-label="上一周期">←</button><strong data-ledger-period-label></strong><button data-ledger-next aria-label="下一周期">→</button></div>
  <div class="custom-range" data-ledger-custom hidden>
    <label for="ledgerFrom">开始日期</label><input id="ledgerFrom" type="date">
    <label for="ledgerTo">结束日期</label><input id="ledgerTo" type="date">
    <button type="button" data-ledger-apply-custom>应用区间</button>
  </div>
  <p class="field-error" data-ledger-error role="alert" hidden></p>
</section>
<section class="period-metrics" data-period-metrics></section>
<section data-ledger-trades></section>
<section data-ledger-stocks></section>
<script type="application/json" id="ledgerData"></script>
```

Serialize data with `json.dumps(data["ledger_dataset"], ensure_ascii=False, separators=(",", ":"))`, then replace `<` with `\u003c` and `&` with `\u0026` before embedding. The current account facts stay outside every element updated by `ledger.js`.

- [ ] **Step 5: Implement browser rendering, URL restoration, and validation**

`initLedgerPage()` must:

1. Parse `#ledgerData` once.
2. Restore grain, period, custom range, side, search, and both page numbers from `location.search`.
3. Keep `lastValidWindow`; failed custom validation displays the exact error and leaves metrics/tables unchanged.
4. Update all six period metrics, then apply the same window to trade rows and per-stock rows.
5. Use `history.pushState` for explicit filter/navigation actions, `history.replaceState` for normalization, and re-render on `popstate`.
6. Disable previous/next if the shifted period has no overlap with ledger bounds.
7. Keep transaction-side/search filters and pagination inside the current date window.

Use arrow glyphs only in the icon buttons and include `aria-label`; do not add text-filled previous/next pills.

- [ ] **Step 6: Add integration assertions**

In `tests/test_personal_site.py`, assert that generated `ledger.html` contains all six grain buttons, `#ledgerData`, `assets/ledger.js`, fixed account facts, and dynamic period targets. Assert `site_data.json` contains no absolute `/Users/` paths.

- [ ] **Step 7: Run JavaScript and Python tests**

Run:

```bash
node --test tests/test_ledger_filter.js
python3 -m unittest tests.test_personal_site -v
python3 -m unittest discover -s tests -v
```

Expected: Node period formulas match Python fixture expectations and all Python tests pass.

- [ ] **Step 8: Commit ledger filtering**

Run:

```bash
git add scripts/build_personal_site.py templates/personal_site/ledger.js tests/test_ledger_filter.js tests/test_personal_site.py
git diff --cached --check
git commit -m "Add ledger time range controls"
```

Expected: one commit with the ledger page, pure JS calculations, and cross-language fixtures.

---

### Task 7: Cycle-First Stock Stories

**Files:**
- Modify: `scripts/build_personal_site.py`
- Modify: `templates/personal_site/site.js`
- Modify: `templates/personal_site/site.css`
- Modify: `tests/test_personal_site.py`

**Interfaces:**
- Consumes: canonical cycles, quotes, stock-level broker totals, documents, mode-enriched samples, and storyline narrative.
- Produces: `build_stories(cycles, positions, realized_rows, quotes, documents, trading_state, storyline_markdown) -> list[dict[str, Any]]`.
- Each story contains `lifetime`, `cycles`, and `default_cycle_id`; each cycle contains `linked_documents`, `linked_modes`, and market-to-market fields for an open cycle.
- URL key for cycle switching: `cycle=<stable-cycle-id>`.

- [ ] **Step 1: Replace the flat-story test with cycle-first assertions**

Add a fixture with two closed cycles and one open cycle for the same stock, then assert:

```python
story = site.build_stories(cycles, positions, realized_rows, quotes, documents, trading_state, "")[0]
self.assertEqual(story["lifetime"]["closed_cycles"], 2)
self.assertEqual(story["lifetime"]["average_holding_days"], 3.0)
self.assertEqual(story["default_cycle_id"], "open-cycle")
self.assertEqual([row["cycle_id"] for row in story["cycles"]], ["open-cycle", "closed-new", "closed-old"])
self.assertEqual(story["cycles"][1]["linked_modes"][0]["id"], "mode-a")
```

Add a closed-only stock and assert its default is the latest `close_date`. In the generated stock HTML, assert one visible default cycle panel, cycle switch controls, holding days, cycle P&L, execution result, evidence direction, mode anchor, event rows, and linked documents.

- [ ] **Step 2: Run story tests and verify the old signature fails**

Run:

```bash
python3 -m unittest tests.test_personal_site.SiteGenerationTests.test_story_order_keeps_current_first_and_closed_most_recent_first -v
```

Expected: failure until the fixture and `build_stories()` use canonical cycles.

- [ ] **Step 3: Build lifetime and per-cycle story data**

For every stock code present in cycles, positions, or realized totals:

- Sort open cycles first, then closed cycles by `(close_date, close_time)` descending.
- Use `summarize_cycles(stock_cycles)` for lifetime count, win rate, and holding durations.
- Use broker-like realized totals including cash adjustments for lifetime realized P&L.
- Add open-cycle unrealized P&L only when that stock has a verified quote; otherwise lifetime total is `None` while the position is open.
- Link a mode sample by exact `cycle_id`; do not infer mode links by stock code.
- Link narrative documents when the stock code/name is present and the document target/run date falls from `first_buy_date` through `close_date`, or through the workbench/as-of date for an open cycle.
- Keep the existing current-first stock index ordering.

- [ ] **Step 4: Render one focused cycle at a time**

Render the stock page with these stable elements:

```html
<header class="stock-lifetime"></header>
<div class="stock-cycle-layout" data-stock-cycles data-default-cycle="cyc_id">
  <nav class="cycle-list" aria-label="交易周期"></nav>
  <section class="cycle-detail"></section>
</div>
```

Each cycle button uses `data-cycle-option="<cycle_id>"`; each panel uses `data-cycle-panel="<cycle_id>"`. An open cycle shows `进行中` for final close and financial result, plus current quantity/cost/latest price/floating P&L. A closed cycle shows first buy, last add, final close, calendar holding days, total buy cost, net sell proceeds, realized P&L, return percentage, event table, linked mode/sample execution/evidence, and linked documents.

Do not render the old all-history flat trade table above the cycle selector.

- [ ] **Step 5: Add stock-cycle URL interaction**

Add this initializer to `site.js` and call it after existing page initializers:

```javascript
function initStockCycles() {
  const root = document.querySelector('[data-stock-cycles]');
  if (!root) return;
  const buttons = Array.from(root.querySelectorAll('[data-cycle-option]'));
  const panels = Array.from(root.querySelectorAll('[data-cycle-panel]'));
  const available = new Set(buttons.map(button => button.dataset.cycleOption));
  let selected = params.get('cycle') || root.dataset.defaultCycle;
  if (!available.has(selected)) selected = root.dataset.defaultCycle;

  function render(push = false) {
    buttons.forEach(button => button.setAttribute('aria-pressed', String(button.dataset.cycleOption === selected)));
    panels.forEach(panel => { panel.hidden = panel.dataset.cyclePanel !== selected; });
    const next = new URLSearchParams(location.search);
    next.set('cycle', selected);
    const url = `${location.pathname}?${next.toString()}`;
    try {
      history[push ? 'pushState' : 'replaceState'](null, '', url);
    } catch (_) {
      return;
    }
  }

  buttons.forEach(button => button.addEventListener('click', () => {
    selected = button.dataset.cycleOption;
    render(true);
  }));
  window.addEventListener('popstate', () => {
    const candidate = new URLSearchParams(location.search).get('cycle');
    selected = available.has(candidate) ? candidate : root.dataset.defaultCycle;
    render(false);
  });
  render(false);
}
```

- [ ] **Step 6: Style cycle navigation without nested cards**

Use an unframed two-column detail layout with a border divider, fixed button dimensions, and a one-column mobile breakpoint. Cycle options may have a compact selected background but must not be rounded text chips. Ensure long cycle IDs and amounts wrap or remain in stable numeric columns without changing control dimensions.

- [ ] **Step 7: Run story and full tests**

Run:

```bash
python3 -m unittest tests.test_personal_site -v
python3 -m unittest discover -s tests -v
```

Expected: story index ordering, open/latest defaults, cycle links, and legacy pages all pass.

- [ ] **Step 8: Commit cycle-first stories**

Run:

```bash
git add scripts/build_personal_site.py templates/personal_site/site.js templates/personal_site/site.css tests/test_personal_site.py
git diff --cached --check
git commit -m "Make stock stories cycle first"
```

Expected: one reviewable story-page commit.

---

### Task 8: Trading Mode Archive and Mode Links

**Files:**
- Modify: `scripts/build_personal_site.py`
- Modify: `templates/personal_site/site.js`
- Modify: `templates/personal_site/site.css`
- Modify: `tests/test_personal_site.py`

**Interfaces:**
- Consumes: enriched `trading_state["modes"]`, eligibility, and cycle links.
- Produces: `render_modes(data: dict[str, Any]) -> str`, `modes.html`, nav key `modes`, and anchors `modes.html#mode-<id>`.
- Mode filter URL keys: `status=all|validating|review|replicable|avoid` and `q=<search>`.

- [ ] **Step 1: Add failing mode-page integration assertions**

Write a valid mode JSON in the site-generation fixture and assert:

```python
self.assertIn("modes", written)
modes_html = written["modes"].read_text(encoding="utf-8")
self.assertIn("交易模式", modes_html)
self.assertIn('data-mode-app', modes_html)
self.assertIn('data-mode-filter="validating"', modes_html)
self.assertIn('id="mode-mode-a"', modes_html)
self.assertIn("3 / 3", modes_html)
self.assertIn("已达人工评审门槛", modes_html)
self.assertIn("历史参考", modes_html)
self.assertIn('href="stocks/000001.html?cycle=cycle-1"', modes_html)
self.assertNotIn("自动升级", modes_html)
self.assertIn('href="modes.html"', (output / "index.html").read_text(encoding="utf-8"))
```

Add an empty-state fixture and assert `尚未建立结构化交易模式` and `0 / 3` without attempting to parse `personal_trading_modes.md`.

- [ ] **Step 2: Run mode-page tests and verify page absence**

Run:

```bash
python3 -m unittest tests.test_personal_site.SiteGenerationTests -v
```

Expected: failure because `modes.html` and its navigation item do not exist.

- [ ] **Step 3: Add mode navigation and rendering**

Insert `("modes", "交易模式", "modes.html")` between stories and ledger in `NAV_ITEMS`. Render:

- Status counts and text-only segmented filters.
- Search over mode name, ID, environment, triggers, and invalidation conditions.
- Mode name/version/status and `valid_formal_sample_count / 3`.
- `review_ready` as `已达人工评审门槛`; never mutate or relabel `validating` as `review`.
- Definition sections for environment, trigger conditions, execution boundaries, invalidation conditions, maximum risk, and next validation requirement.
- Formal samples and historical references in separate tables.
- Each resolved sample links to `stocks/<code>.html?cycle=<cycle_id>` and displays execution result, P&L, return, holding days, and evidence direction.
- Missing cycle IDs display `周期关联待修复` without dropping the sample.

Add `modes` to `write_site()` and `public_site_data()` without including narrative Markdown or absolute paths.

- [ ] **Step 4: Add mode-page filtering**

Add `initModes()` to `site.js` using the existing `paginate()`, `setPressed()`, and `updateUrl()` helpers. Default to `all`, preserve `status` and `q` in the URL, and render the empty result state without hiding controls.

- [ ] **Step 5: Style definitions as an operational archive**

Use dense full-width definition rows and tables, not decorative cards. Status text uses neutral semantic copy; do not use red/yellow/green traffic-light dots. On mobile, keep definition labels above values and allow sample tables to scroll inside their own region.

- [ ] **Step 6: Run integration and full tests**

Run:

```bash
python3 -m unittest tests.test_personal_site -v
python3 -m unittest discover -s tests -v
```

Expected: `modes.html`, homepage mode links, stock-cycle mode links, empty state, and all existing pages pass.

- [ ] **Step 7: Commit the mode archive**

Run:

```bash
git add scripts/build_personal_site.py templates/personal_site/site.js templates/personal_site/site.css tests/test_personal_site.py
git diff --cached --check
git commit -m "Add trading mode archive"
```

Expected: the mode archive is complete without changing private mode content.

---

### Task 9: Responsive Browser QA, Link Integrity, and Real-Ledger Acceptance

**Files:**
- Modify: `templates/personal_site/site.css`
- Modify: `tests/test_personal_site.py`
- Create: `tests/qa_personal_site.mjs`

**Interfaces:**
- Consumes: the fully generated site and bundled Playwright module path supplied through `CODEX_PLAYWRIGHT_MJS`.
- Produces: desktop/mobile screenshots under ignored `reports/personal_site/qa/` and a JSON QA report with pass/fail booleans.

- [ ] **Step 1: Add generated-link integrity coverage**

Add an HTML parser helper in `tests/test_personal_site.py` that gathers local `href` values from every generated HTML file. Strip query strings/fragments, skip `http:`, `https:`, `mailto:`, and empty anchors, resolve the remaining path from the source page, and assert the target exists. The test must also assert that no generated HTML or `site_data.json` contains `file://` or `/Users/`.

- [ ] **Step 2: Run the link test and fix only genuine broken links**

Run:

```bash
python3 -m unittest tests.test_personal_site.SiteGenerationTests -v
```

Expected: all generated local links resolve. Any failure names both source page and missing target.

- [ ] **Step 3: Finish responsive and accessibility CSS**

Audit and enforce these exact rules:

```css
.mono, .account-total strong, .account-fact-grid strong, [data-period-metrics] strong { font-variant-numeric: tabular-nums; }
.account-total strong, .account-fact-grid strong, .period-metric strong { white-space: nowrap; }
.pool-scroll, .discipline-feed, .table-scroll { overscroll-behavior: contain; }
@media (max-width: 980px) {
  .account-facts { grid-template-columns: 1fr; }
  .account-total { grid-row: auto; border-right: 0; border-bottom: 1px solid var(--line-strong); }
  .today-workbench { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .position-pane { grid-column: 1 / -1; }
}
@media (max-width: 680px) {
  .page-shell { width: min(100% - 24px, 1480px); padding-top: 16px; }
  h1 { font-size: 24px; }
  .account-fact-grid, .ability-rail, .today-workbench { grid-template-columns: 1fr; }
  .account-fact-grid > div, .ability-rail > div { border-left: 0; border-top: 1px solid var(--line); }
  .position-pane { grid-column: auto; }
  .pool-scroll { height: 440px; }
}
```

Remove any `vw`-based font sizing. Verify every icon-only previous/next control has a tooltip via `title` and an accessible name via `aria-label`.

- [ ] **Step 4: Create the Playwright acceptance script**

Create `tests/qa_personal_site.mjs`:

```javascript
import fs from 'node:fs';
import path from 'node:path';
import {pathToFileURL} from 'node:url';

const playwrightPath = process.env.CODEX_PLAYWRIGHT_MJS;
if (!playwrightPath) throw new Error('CODEX_PLAYWRIGHT_MJS is required');
const {chromium} = await import(pathToFileURL(playwrightPath).href);
const baseUrl = process.argv[2] || 'http://127.0.0.1:8765';
const outputDir = process.argv[3] || 'reports/personal_site/qa';
fs.mkdirSync(outputDir, {recursive: true});
const browser = await chromium.launch({headless: true});

async function inspect(name, viewport) {
  const page = await browser.newPage({viewport});
  await page.goto(`${baseUrl}/index.html`, {waitUntil: 'networkidle'});
  const totalBefore = await page.locator('[data-account-total]').textContent();
  const home = await page.evaluate(() => {
    const root = document.documentElement;
    const pool = document.querySelector('[data-pool-scroll]');
    const discipline = document.querySelector('[data-discipline-feed]');
    return {
      noHorizontalScroll: root.scrollWidth <= root.clientWidth + 1,
      poolRows: document.querySelectorAll('[data-pool-row]').length,
      poolInternalScroll: pool ? pool.scrollHeight >= pool.clientHeight : false,
      disciplineContained: discipline ? discipline.scrollHeight >= discipline.clientHeight : false,
      headingsDoNotOverlap: Array.from(document.querySelectorAll('h1,h2,h3')).every(node => node.scrollWidth <= node.parentElement.scrollWidth + 1)
    };
  });
  await page.screenshot({path: path.join(outputDir, `home-${name}.png`), fullPage: true});

  await page.goto(`${baseUrl}/ledger.html?grain=month&period=2026-07`, {waitUntil: 'networkidle'});
  const ledgerTotal = await page.locator('[data-account-total]').textContent();
  await page.locator('[data-ledger-grain="custom"]').click();
  await page.locator('#ledgerFrom').fill('2026-07-01');
  await page.locator('#ledgerTo').fill('2026-07-10');
  await page.locator('[data-ledger-apply-custom]').click();
  const customUrlUpdated = page.url().includes('grain=custom') && page.url().includes('from=2026-07-01') && page.url().includes('to=2026-07-10');
  await page.reload({waitUntil: 'networkidle'});
  const customRestored = (await page.locator('#ledgerFrom').inputValue()) === '2026-07-01' && (await page.locator('#ledgerTo').inputValue()) === '2026-07-10';
  await page.goto(`${baseUrl}/ledger.html?grain=month&period=2026-07`, {waitUntil: 'networkidle'});
  const monthLabel = await page.locator('[data-ledger-period-label]').textContent();
  await page.locator('[data-ledger-prev]').click();
  const urlChanged = page.url().includes('grain=month') && !page.url().includes('period=2026-07');
  await page.goBack();
  const historyRestored = (await page.locator('[data-ledger-period-label]').textContent()) === monthLabel;
  await page.locator('#ledgerSearch').fill('300260');
  await page.waitForFunction(() => new URLSearchParams(location.search).get('q') === '300260');
  const searchUrlUpdated = page.url().includes('q=300260');
  await page.screenshot({path: path.join(outputDir, `ledger-${name}.png`), fullPage: true});

  await page.goto(`${baseUrl}/stories.html?status=all`, {waitUntil: 'networkidle'});
  const storyLink = page.locator('a[href^="stocks/"]').first();
  const storyExists = await storyLink.count() > 0;
  let cycleUrlUpdated = false;
  if (storyExists) {
    await storyLink.click();
    const cycleButtons = page.locator('[data-cycle-option]');
    const cycleCount = await cycleButtons.count();
    if (cycleCount > 1) {
      await cycleButtons.nth(1).click();
      cycleUrlUpdated = page.url().includes('cycle=');
    } else {
      cycleUrlUpdated = cycleCount === 1;
    }
  }
  await page.goto(`${baseUrl}/modes.html`, {waitUntil: 'networkidle'});
  await page.locator('[data-mode-filter="validating"]').click();
  const modeUrlUpdated = page.url().includes('status=validating');
  return Object.assign({}, home, {
    accountFactsFixed: totalBefore === ledgerTotal,
    customUrlUpdated,
    customRestored,
    urlChanged,
    historyRestored,
    searchUrlUpdated,
    storyExists,
    cycleUrlUpdated,
    modeUrlUpdated
  });
}

const results = {
  desktop: await inspect('desktop', {width: 1440, height: 1080}),
  mobile: await inspect('mobile', {width: 390, height: 844})
};
await browser.close();
console.log(JSON.stringify(results, null, 2));
const failures = Object.entries(results).flatMap(([viewport, report]) =>
  Object.entries(report).filter(([, value]) => value !== true && value !== 15).map(([key]) => `${viewport}.${key}`)
);
if (results.desktop.poolRows !== 15 || results.mobile.poolRows !== 15) failures.push('poolRows');
if (failures.length) {
  console.error(`QA_FAILED: ${failures.join(', ')}`);
  process.exitCode = 1;
}
```

The generated real pool is expected to contain 15 candidates for this acceptance run. Unit tests already cover the valid shorter-pool state.

- [ ] **Step 5: Build the real site and verify snapshot account facts**

Run:

```bash
python3 scripts/build_personal_site.py
python3 -c "import json,pathlib; d=json.loads(pathlib.Path('reports/personal_site/site_data.json').read_text()); m=d['mark_to_market']; s=d['summary']; a=d['ability']; assert m['total_pnl']==-58618.30; assert m['realized_pnl']==-45430.00; assert m['unrealized_pnl']==-13188.30; assert s['total_fees']==9670.61; assert s['stock_count']==118; assert a['closed_cycles']==204; assert a['win_rate']==43.14; assert a['average_payoff_ratio']==1.03; assert a['profit_factor']==0.78; assert a['expectancy']==-229.92; assert a['average_holding_days']==13.75; assert a['median_holding_days']==3.0"
```

Expected: the site builds and the command exits with status 0. If the private ledger or latest quote inputs changed after the design snapshot, reconcile the new source facts and update the acceptance assertion in the design spec; never hard-code the old values into production.

- [ ] **Step 6: Run Playwright at desktop and mobile widths**

Start the local server in a persistent terminal session:

```bash
python3 -m http.server 8765 --bind 127.0.0.1 --directory reports/personal_site
```

In a second terminal, run:

```bash
CODEX_PLAYWRIGHT_MJS=/Users/makubex/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.mjs node tests/qa_personal_site.mjs http://127.0.0.1:8765 reports/personal_site/qa
```

Expected: JSON reports true for horizontal fit, internal scroll, heading fit, fixed account facts, custom-range restore, period navigation, search URL state, story cycle switching, mode filtering, and history restoration; pool count is 15 at both viewports. Inspect `home-desktop.png`, `home-mobile.png`, `ledger-desktop.png`, and `ledger-mobile.png` for clipping, overlap, weak hierarchy, and nested-card appearance. Stop the server after QA.

- [ ] **Step 7: Run the complete verification suite**

Run:

```bash
python3 -m unittest discover -s tests -v
node --test tests/test_ledger_filter.js
git diff --check
git status --short
```

Expected: all Python and Node tests pass, `git diff --check` prints nothing, and only the three Task 9 files plus pre-existing unrelated user changes are dirty.

- [ ] **Step 8: Commit final QA and responsive fixes**

Run:

```bash
git add templates/personal_site/site.css tests/test_personal_site.py tests/qa_personal_site.mjs
git diff --cached --check
git commit -m "Verify coach desk across desktop and mobile"
```

Expected: final implementation commit contains only responsive styling and durable QA coverage. Generated reports and screenshots remain ignored.

---

## Completion Checklist

- [ ] Every page derives cycle facts from `broker_like_cycles()`; no page carries a second cycle algorithm.
- [ ] Homepage contains one dominant total, four account facts, seven ability facts, structured gate/eligibility, plan, full parsed pool, holdings, and discipline feed.
- [ ] Ledger account facts remain fixed while one shared date window drives period metrics, trades, and per-stock results.
- [ ] Story defaults are open cycle for current positions and latest closed cycle otherwise.
- [ ] Formal and historical mode samples remain separate; `review_ready` never changes status automatically.
- [ ] Missing/malformed JSON, missing quotes, missing artifacts, short pools, no holdings, no messages, and empty filters all have explicit non-fabricated states.
- [ ] All local links resolve and generated files expose no absolute private paths.
- [ ] Python tests, Node tests, real-ledger snapshot checks, and desktop/mobile Playwright QA pass.
- [ ] Unrelated dirty files are still present and unchanged.
