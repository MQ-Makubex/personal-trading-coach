# Personal Trading Coach Workflow

This project is the durable local workspace for a personal stock trading coach. The coach trains repeatable, verifiable, risk-controlled trading behavior; it does not recommend stocks, predict prices, or issue direct buy/sell instructions.

## Operating Principle

The main artifact is a coach-written Markdown note. Scripts support the coach by preparing evidence, maintaining the account ledger, running factual queries, and rendering HTML. Scripts must not be the primary source of judgment.

## Daily Inputs

- 今日成交事实: pasted broker table, sanitized statement, or manually entered trades.
- 成交截图: fallback only. If the user explicitly uploads a screenshot to Codex, extract only standard trade facts into an ignored local text/CSV file; do not store the image in the repository.
- 今日交易想法: plan, emotions, mistakes, hesitation, market read, and pain points.
- 待校正市场判断: user observations about indices, sectors, themes, style, and sentiment.
- 当前持仓: position status and unresolved storylines.
- 阅读材料: article URL, excerpts, or distilled external views.

## Post-Market Coach Flow

1. Build or update the evidence packet from sanitized trade facts and user context.
2. Read `CONTEXT.md`, open position storylines, coach memory, personal trading modes, decision events, and the latest research-pool protocol.
3. Write the daily coach note directly in Markdown using `templates/coach_note.md`.
4. Review yesterday's research pool against today's market and user actions.
5. Draft position-storyline updates: identify whether each action continued a plan, corrected an error, increased risk, or showed emotional deformation.
6. Draft personal-trading-mode updates conservatively. A single profitable trade cannot become a reusable mode.
7. Draft coach-memory updates with recurring execution errors, emotional triggers, and training focus.
8. Build tomorrow's research pool using `templates/research_pool.md`.
9. Write a Xueqiu-ready review and tomorrow plan draft using `templates/xueqiu_post.md`.
10. Run the evidence completeness gate, then refresh the multi-page personal site from the canonical Markdown.

### Stock Pool Coupling

The personal-site stock pool is the single source of truth. Whenever the pool is generated or replaced, these actions must complete in the same task:

1. Finalize exactly 15 tradable stock codes in `research_pool.md`, excluding 688 codes that this account cannot trade and excluding any stock whose close is at or below its 200-day moving average.
2. Generate the homepage stock-name links from that same list, pointing to the corresponding Xueqiu quote/K-line pages.
3. Generate `xueqiu_watchlist_sync.json` with the same codes and the requirement to clear the existing watchlist first.
4. Use the logged-in Google Chrome session to clear the existing Xueqiu watchlist and add those 15 stocks.
5. Verify the final Xueqiu code set exactly matches the personal-site list, then mark the manifest `synced`.

The local scripts cannot replace the user's logged-in Chrome session, so step 4 is a browser-side action, but it must not be skipped or deferred to the next pool run. An incomplete, duplicated, or 688-containing pool is marked `blocked_incomplete_pool` and must not be presented as synchronized.

### 交易模式状态联动

教练手记确认当前验证模式后，必须同时维护 `state/trading_modes.json` 的模式定义、模式资格和周期样本关联。进行中的持仓周期也应绑定到验证样本；结果未知时记录为 `indeterminate`，而不是显示为“未绑定”。只有已完成且结果可判定的正式样本才计入 `n / 3`，不得把单个持仓样本直接升级为可复制模式。

```bash
python3 scripts/xueqiu_watchlist_sync.py \
  --mark-synced reports/run_YYYYMMDD_close/xueqiu_watchlist_sync.json \
  --verified-codes CODE1 CODE2 ... CODE15
```

When the user pastes post-market trades, broker tables, or a same-day trading journal, the minimum required output set is:

- today's coach note;
- yesterday research-pool validation;
- tomorrow research pool.

If the user asks a pure intraday discipline question before the close, a short guard response is acceptable. Once final or near-final trade facts are pasted after the session, the full post-market output set is mandatory.

## Pre-Market And Intraday Coach Flow

1. Start from tomorrow's research pool.
2. The user chooses no more than three specific stocks and writes a simple operating plan for each.
3. The coach supplements each selected stock with evidence, trigger, operation form, invalidation, stop anchor, position cap, and forbidden actions.
4. Only then write the stock-specific `明日交易预案`; the homepage shows one sentence per selected stock in the form `触发条件 -> 操作形式；失效条件 -> 风险边界`.
5. During the session, judge every proposed action as one of:
   - 计划内动作
   - 提前动作
   - 加风险动作
   - 红牌动作
5. Do not tell the user to buy or sell. Ask the risk-control question that forces the user to decide against the plan.

Local guard command:

```bash
python3 scripts/pre_trade_guard.py --security "证券代码 证券名称" --action "拟执行动作" --trigger "触发条件" --invalidation "失效条件" --stop-anchor "止损锚点" --plan reports/run_*/trade_plan.md -o reports/intraday_guard.md
```

## Research Pool Evolution

The research pool is not a recommendation list. It is a training surface for pattern selection. Early stage is coach-led: the coach proposes candidate baskets, exclusion rules, and risk filters. Over time the user takes more screening responsibility as evidence accumulates.

Each research-pool iteration should record:

- macro facts and market-impact assumptions;
- industry/policy and US-market mapping;
- index structure and breadth;
- theme strength, rotation, and risk appetite;
- individual-stock evidence;
- buy-point design and invalidation;
- current market regime assumption;
- candidate baskets;
- inclusion rules;
- exclusion rules;
- mode-fit score;
- why the name is not yet a plan;
- post-trade validation result.

Market fact and research-pool commands:

```bash
python3 scripts/market_snapshot.py --trade-date YYYY-MM-DD --user-view private/market_view.txt --json reports/market_snapshot.json --md reports/market_snapshot.md
python3 scripts/article_digest.py --trade-date YYYY-MM-DD --text-file private/article_excerpt.txt --affected-trade "是否影响当天交易动作" --json reports/article_digest.json --md reports/article_digest.md
python3 scripts/enhance_candidate_universe.py private/candidate_universe.csv --trade-date YYYY-MM-DD --provider auto --output reports/enriched_candidate_universe.csv
python3 scripts/research_pool_builder.py reports/enriched_candidate_universe.csv --trade-date YYYY-MM-DD --md reports/research_pool_candidates.md
python3 scripts/daily_session.py --trade-date YYYY-MM-DD --pasted-trades private/raw_pasted_trades.txt --market-snapshot reports/market_snapshot.md --research-pool reports/research_pool_candidates.md --article-digest reports/article_digest.md
```

如果一个公开接口失败，先按 Sina + BaoStock、Yahoo、AKShare/BaoStock/HTTP 兜底链路重试，并记录来源。所有重试仍失败时才标记缺失；教练不得用陈旧缓存或猜测填充市场事实。

## Evidence Completeness Gate

每日复盘不能因为模板文件存在就视为完整。`daily_prepare.py` 会自动对候选池执行行情增强，并由 `finalize_session.py --strict` 调用 `scripts/evidence_completeness.py` 检查：

- A 股四大指数、全市场涨跌家数和涨跌平总数一致；
- 标普、纳斯达克、费城半导体等至少两个美股映射；
- 15 支非 688 候选全部有 5/10/20/50/200 日线和最近交易日期；
- 15 支候选收盘价必须高于 200 日均线；200 日线下方或数据缺失的股票直接剔除，不能为了凑满 15 支回填；
- 至少两条当前公开来源，覆盖海外/美股映射和产业/政策事实；
- 交易事实经过隐私检查，且自动生成当前持仓事实快照。

失败时流程继续尝试备用公开源，但不会把不完整材料标记为高质量复盘。检查报告保存在 run 目录的 `data_quality.json`。

## Account Ledger Flow

Historical broker statements should be sanitized, parsed, deduplicated, and merged into the account ledger. The ledger may answer factual questions such as:

- total commission and fees by period;
- trading frequency by day, week, month, and stock;
- realized PnL by stock and period;
- broker-like rolling-cost realized PnL for user-facing reports;
- FIFO realized PnL by matched lots for audit;
- remaining position quantity and cost basis inferred from trade facts;
- repeated loss patterns;
- holding period distribution;
- T-trade frequency and result;
- largest fee drag;
- whether a claimed personal mode has enough historical evidence.

The ledger must not store identity information, account identifiers, fund balances, branch names, addresses, or raw statement files.

Recommended local commands:

```bash
python3 scripts/daily_prepare.py --trade-date YYYY-MM-DD --pasted-trades-file private/raw_pasted_trades.txt --journal-file private/journal.txt --market-view-file private/market_view.txt --candidate-universe private/candidate_universe.csv
python3 scripts/daily_session.py --trade-date YYYY-MM-DD --pasted-trades private/raw_pasted_trades.txt --journal private/journal.txt --market-view private/market_view.txt
```

Useful factual ledger queries:

```bash
python3 scripts/ledger_query.py summary
python3 scripts/ledger_query.py fee-drag
python3 scripts/ledger_query.py activity
python3 scripts/ledger_query.py recent --limit 20
python3 scripts/ledger_query.py t-candidates
python3 scripts/ledger_query.py cash-diff
python3 scripts/ledger_query.py realized
python3 scripts/ledger_query.py positions
python3 scripts/ledger_query.py pnl-by-stock
python3 scripts/ledger_query.py fifo-realized
python3 scripts/ledger_query.py fifo-pnl-by-stock
python3 scripts/ledger_query.py stock --stock-code 301421
python3 scripts/account_report.py --json reports/account_report.json --md reports/account_report.md
```

`cash-diff` is a cash-flow view, not realized PnL when positions remain open.
`realized` and `pnl-by-stock` use the broker-like rolling-cost basis for user-facing coach notes, account reports, and the personal cockpit: buys add cost, sells deduct net proceeds, same-day re-entry carries the closed-position residual into display cost, and next-day re-entry resets after a flat close.
Security-level cash adjustments such as dividends and dividend-tax adjustments are added to stock total PnL. Account-level flows such as bank/security transfers and interest capitalization are excluded from stock PnL.
`fifo-realized` and `fifo-pnl-by-stock` are audit views: buy cost includes buy-side fees, and sell proceeds deduct sell-side fees. If historical data starts after a position was already opened, unmatched sells are flagged instead of being forced into false PnL.

For historical CSV/XLSX exports:

```bash
python3 scripts/normalize_statement.py private/history_statement.csv -o reports/normalized_trades.csv
python3 scripts/privacy_guard.py reports/normalized_trades.csv --report reports/privacy_guard_report.json
python3 scripts/daily_session.py --trade-date YYYY-MM-DD --trades-csv reports/normalized_trades.csv --journal private/journal.txt --market-view private/market_view.txt
```

For text-based PDF statements:

```bash
python3 scripts/sanitize_pdf_statement.py private/history_statement.pdf -o reports/sanitized_pdf_trades.csv --report reports/sanitize_pdf_report.json
python3 scripts/privacy_guard.py reports/sanitized_pdf_trades.csv --report reports/privacy_guard_report.json
python3 scripts/daily_session.py --trade-date YYYY-MM-DD --trades-csv reports/sanitized_pdf_trades.csv --journal private/journal.txt --market-view private/market_view.txt
```

If no table can be extracted, the PDF is probably scanned. Use local OCR first; do not upload raw PDF text to the coach.

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
- `state/coach_lenses.md`
- `state/position_storylines.md`
- `state/personal_trading_modes.md`
- `state/research_pool_protocol.md`
- `state/decision_events.md`

During coaching, read these files before judgment. After the coach note passes `finalize_session.py --strict`, generate state-update drafts and append only reviewed snippets. Do not commit them.

## Output Discipline

Coach notes should lead with judgment, then evidence. Avoid generic "无法判断" blocks. Use `无法判断` only when a specific conclusion truly lacks evidence.

For severe rule violations, use the `教练语气级别` from `CONTEXT.md`: normal review, discipline reminder, red-card warning, or trading pause.

## Finalize Session

After the coach has rewritten `coach_note.md`, `research_pool.md`, and `xueqiu_post.md`, run:

```bash
python3 scripts/finalize_session.py reports/run_YYYYMMDD_HHMMSS --strict
python3 scripts/evidence_completeness.py reports/run_YYYYMMDD_HHMMSS
```

The session keeps Markdown as its canonical output. `finalize_session.py` does
not create per-document HTML files; after validation it refreshes
`reports/personal_site/`. Read the handoff from the personal site: the latest
coach note, trade plan, and research pool appear on the coach desk, while all
other Markdown artifacts are available in the training timeline and linked
stock stories.

The finalizer:

- validates Markdown and refreshes the personal site only when validation passes;
- creates `state_update_checklist.md`;
- checks required coach-note sections;
- warns if template placeholders remain;
- fails if direct buy/sell/position instructions or price predictions appear.

Warnings mean the coach note may still be too generic. Errors must be fixed before treating the session as complete.

After review, append approved state snippets with:

```bash
python3 scripts/draft_state_updates.py reports/run_YYYYMMDD_HHMMSS --require-finalize-ok
python3 scripts/append_state_update.py decision_events.md --update reports/run_YYYYMMDD_HHMMSS/state_update_decision_events.md --trade-date YYYY-MM-DD --source reports/run_YYYYMMDD_HHMMSS/coach_note.md
```

Only append reviewed snippets. Do not use this script to generate judgment.
