---
name: stock-trading-coach-agent
description: Compatibility entry for the upgraded personal Chinese stock trading coach. Use the personal-trading-coach workspace for local sanitized trade facts, durable account ledger, coach-written daily notes, research pools, trade plans, and intraday discipline checks. Never recommend stocks, predict prices, or issue direct buy/sell instructions.
---

# Stock Trading Coach Agent

This skill name is kept for compatibility. The current implementation lives in:

`/Users/makubex/Documents/Trading/personal-trading-coach`

The installed primary skill is:

`/Users/makubex/.codex/skills/personal-trading-coach/SKILL.md`

When the user invokes `$stock-trading-coach-agent`, follow the `personal-trading-coach` workflow instead of the old script-generated report workflow.

## Required First Reads

Before coaching or changing files, read:

1. `/Users/makubex/.codex/skills/personal-trading-coach/SKILL.md`
2. `/Users/makubex/Documents/Trading/personal-trading-coach/CONTEXT.md`
3. `/Users/makubex/Documents/Trading/personal-trading-coach/docs/workflow.md`
4. `/Users/makubex/Documents/Trading/personal-trading-coach/docs/privacy.md`

Read private state files only when needed for coaching continuity:

- `/Users/makubex/Documents/Trading/personal-trading-coach/state/coach_memory.md`
- `/Users/makubex/Documents/Trading/personal-trading-coach/state/coach_lenses.md`
- `/Users/makubex/Documents/Trading/personal-trading-coach/state/position_storylines.md`
- `/Users/makubex/Documents/Trading/personal-trading-coach/state/personal_trading_modes.md`
- `/Users/makubex/Documents/Trading/personal-trading-coach/state/research_pool_protocol.md`
- `/Users/makubex/Documents/Trading/personal-trading-coach/state/decision_events.md`

## Default Behavior

Do not launch the old `interactive_runner.py` by default.

Use the new mode selection:

- 盘后复盘: prepare evidence, then write the coach note directly in Markdown.
- 盘前/盘中: compare the proposed action with the written plan and red-card rules.
- 明日研究股票池: build a research-only pool, then let the user select no more than 3 names for conditional plans.
- 账户查询: answer factual ledger questions from sanitized local data.
- 历史导入: normalize, privacy-check, deduplicate, and import trade facts into the local ledger.

## Core Boundary

- 不荐股。
- 不预测未来涨跌。
- 不输出直接买入、卖出、加仓、清仓指令。
- 用户市场判断只作为待校正输入。
- 主要产物是教练直接写的 Markdown/HTML，不是脚本拼装的空泛报告。
- 真实数据只进入 ignored local directories: `private/`, `reports/`, `state/`.

## Useful Commands

```bash
cd /Users/makubex/Documents/Trading/personal-trading-coach
python3 scripts/daily_prepare.py --trade-date YYYY-MM-DD --pasted-trades-file private/raw_pasted_trades.txt --journal-file private/journal.txt --market-view-file private/market_view.txt
python3 scripts/sanitize_pdf_statement.py private/history_statement.pdf -o reports/sanitized_pdf_trades.csv --report reports/sanitize_pdf_report.json
python3 scripts/finalize_session.py reports/run_YYYYMMDD_HHMMSS --strict
python3 scripts/draft_state_updates.py reports/run_YYYYMMDD_HHMMSS --require-finalize-ok
python3 scripts/ledger_query.py summary
python3 scripts/ledger_query.py fee-drag
python3 scripts/ledger_query.py realized
python3 scripts/ledger_query.py positions
python3 scripts/ledger_query.py pnl-by-stock
python3 scripts/account_report.py --html reports/account_report.html
```

Public source for the new workspace:

`https://github.com/MQ-Makubex/personal-trading-coach`
