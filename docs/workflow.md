# Personal Trading Coach Workflow

This project is the durable local workspace for a personal stock trading coach. The coach trains repeatable, verifiable, risk-controlled trading behavior; it does not recommend stocks, predict prices, or issue direct buy/sell instructions.

## Operating Principle

The main artifact is a coach-written Markdown note. Scripts support the coach by preparing evidence, maintaining the account ledger, running factual queries, and rendering HTML. Scripts must not be the primary source of judgment.

## Daily Inputs

- 今日成交事实: pasted broker table, sanitized statement, or manually entered trades.
- 今日交易想法: plan, emotions, mistakes, hesitation, market read, and pain points.
- 待校正市场判断: user observations about indices, sectors, themes, style, and sentiment.
- 当前持仓: position status and unresolved storylines.
- 阅读材料: article URL, excerpts, or distilled external views.

## Post-Market Coach Flow

1. Build or update the evidence packet from sanitized trade facts and user context.
2. Read `CONTEXT.md`, open position storylines, coach memory, personal trading modes, decision events, and the latest research-pool protocol.
3. Write the daily coach note directly in Markdown using `templates/coach_note.md`.
4. Update position storylines: identify whether each action continued a plan, corrected an error, increased risk, or showed emotional deformation.
5. Update personal trading modes conservatively. A single profitable trade cannot become a reusable mode.
6. Update coach memory with recurring execution errors, emotional triggers, and training focus.
7. Build tomorrow's research pool using `templates/research_pool.md`.
8. Render the coach note to HTML for reading.

## Pre-Market And Intraday Coach Flow

1. Start from tomorrow's research pool.
2. The user chooses no more than three names for conditional planning.
3. For each name, write a `明日交易预案` with trigger, invalidation, stop anchor, position cap, and forbidden actions.
4. During the session, judge every proposed action as one of:
   - 计划内动作
   - 提前动作
   - 加风险动作
   - 红牌动作
5. Do not tell the user to buy or sell. Ask the risk-control question that forces the user to decide against the plan.

Local guard command:

```bash
python3 scripts/pre_trade_guard.py --security "证券代码 证券名称" --action "拟执行动作" --trigger "触发条件" --invalidation "失效条件" --stop-anchor "止损锚点" --plan reports/run_*/trade_plan.md --html reports/pre_trade_guard.html
```

## Research Pool Evolution

The research pool is not a recommendation list. It is a training surface for pattern selection. Early stage is coach-led: the coach proposes candidate baskets, exclusion rules, and risk filters. Over time the user takes more screening responsibility as evidence accumulates.

Each research-pool iteration should record:

- current market regime assumption;
- candidate baskets;
- inclusion rules;
- exclusion rules;
- mode-fit score;
- why the name is not yet a plan;
- post-trade validation result.

## Account Ledger Flow

Historical broker statements should be sanitized, parsed, deduplicated, and merged into the account ledger. The ledger may answer factual questions such as:

- total commission and fees by period;
- trading frequency by day, week, month, and stock;
- realized PnL by stock and period;
- repeated loss patterns;
- holding period distribution;
- T-trade frequency and result;
- largest fee drag;
- whether a claimed personal mode has enough historical evidence.

The ledger must not store identity information, account identifiers, fund balances, branch names, addresses, or raw statement files.

Recommended local commands:

```bash
python3 scripts/daily_session.py --trade-date YYYY-MM-DD --pasted-trades private/raw_pasted_trades.txt --journal private/journal.txt --market-view private/market_view.txt
```

For historical CSV/XLSX exports:

```bash
python3 scripts/normalize_statement.py private/history_statement.csv -o reports/normalized_trades.csv
python3 scripts/privacy_guard.py reports/normalized_trades.csv --report reports/privacy_guard_report.json
python3 scripts/daily_session.py --trade-date YYYY-MM-DD --trades-csv reports/normalized_trades.csv --journal private/journal.txt --market-view private/market_view.txt
```

Manual lower-level commands:

```bash
python3 scripts/parse_pasted_trades.py private/raw_pasted_trades.txt -o reports/pasted_trades_extracted.csv --trade-date YYYY-MM-DD
python3 scripts/privacy_guard.py reports/pasted_trades_extracted.csv --report reports/privacy_guard_report.json
python3 scripts/ledger_import.py reports/pasted_trades_extracted.csv
python3 scripts/ledger_query.py summary
python3 scripts/build_evidence_packet.py --trades reports/pasted_trades_extracted.csv --trade-date YYYY-MM-DD --journal private/journal.txt --market-view private/market_view.txt -o reports/evidence_packet.md
```

All command outputs above are ignored by Git except the scripts themselves.

## Private State Files

Initialize private state once:

```bash
python3 scripts/init_state.py
```

This creates ignored files under `state/`:

- `state/coach_memory.md`
- `state/position_storylines.md`
- `state/personal_trading_modes.md`
- `state/research_pool_protocol.md`
- `state/decision_events.md`

During coaching, read these files before judgment and update them after the coach note. Do not commit them.

## Output Discipline

Coach notes should lead with judgment, then evidence. Avoid generic "无法判断" blocks. Use `无法判断` only when a specific conclusion truly lacks evidence.

For severe rule violations, use the `教练语气级别` from `CONTEXT.md`: normal review, discipline reminder, red-card warning, or trading pause.
