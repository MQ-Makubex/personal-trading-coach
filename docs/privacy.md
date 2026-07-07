# Privacy Boundary

This project is local-first. Real statements, screenshots, raw pasted broker text, generated ledgers, coach notes, and reports belong in ignored private directories.

## Never Commit

- raw PDF statements;
- raw CSV/XLSX broker exports;
- screenshots of trades or accounts;
- raw pasted broker text;
- generated account ledger files;
- generated coach notes and reports;
- files containing name, ID card, phone number, fund account, customer ID, shareholder account, bank card, branch, address, or cash balance.

## Allowed Trade Facts

The long-term ledger may keep only:

- trade date;
- trade time;
- stock code;
- stock name;
- side;
- quantity;
- price;
- amount;
- net amount;
- commission;
- stamp tax;
- transfer fee;
- other fee.

## Forbidden Fields

Remove or reject:

- name;
- ID card;
- phone number;
- fund account;
- customer ID;
- shareholder account;
- bank card;
- broker branch;
- home or contact address;
- cash balance;
- account balance;
- raw remarks that contain account identifiers.

## Git Rule

The repository commits only rules, docs, templates, and scripts. The directories `state/`, `reports/`, and `private/` are ignored except for `.gitkeep` placeholders.

Before any commit, run:

```bash
git status --short
git diff --cached --stat
git diff --cached --name-only
git diff --cached
```

Confirm no real trading data, no raw statement, no account identifier, and no cash-balance field is staged.

## Script Boundary

- `scripts/parse_pasted_trades.py` reads raw pasted text only from an ignored private path and emits standard trade facts.
- `scripts/sanitize_pdf_statement.py` extracts only sanitized trade facts from local text-based PDFs; it does not print PDF text and does not store the raw PDF in the repository.
- `scripts/normalize_statement.py` normalizes broker CSV/XLSX exports into standard trade facts; XLSX support requires optional `openpyxl`.
- `scripts/daily_prepare.py` copies daily user inputs into ignored private run input files and prepares one local session.
- `scripts/privacy_guard.py` must run before trade facts enter the ledger.
- `scripts/ledger_import.py` accepts only standard trade-fact CSV files that have passed privacy checks.
- `scripts/ledger_query.py` answers factual ledger questions only.
- `scripts/ledger_analytics.py` computes FIFO realized PnL, open position cost basis, and matched holding days from sanitized trade facts only.
- `scripts/build_evidence_packet.py` creates coach-readable evidence; the coach still writes the judgment directly.
- `scripts/daily_session.py` prepares one ignored run directory with evidence, prompts, drafts, and rendered placeholders.
- `scripts/pre_trade_guard.py` creates plan-consistency and red-card questions for pre-trade or intraday use.
- `scripts/article_digest.py` stores article URL/title/summary and narrative-pollution checks, not full article text.
- `scripts/market_snapshot.py` collects public market facts or explicit offline placeholders; it must not store private account data.
- `scripts/market_data.py` reads public daily A-share bars through optional AKShare/BaoStock adapters only.
- `scripts/enhance_candidate_universe.py` enriches a private candidate CSV with public price, volume, MA, and MA-position fields; generated outputs remain ignored under `reports/`.
- `scripts/research_pool_builder.py` builds a research-only candidate pool from local market/universe CSV; it must not label output as recommendations.
- `scripts/finalize_session.py` validates local session notes and renders HTML; outputs remain under ignored `reports/`.
- `scripts/append_state_update.py` appends reviewed Markdown snippets to ignored private state files only.
- `scripts/draft_state_updates.py` extracts draft state snippets from a reviewed run; outputs remain under ignored `reports/`.
- `scripts/account_report.py` generates local account fact reports from ignored ledger SQLite.
- `scripts/init_state.py` creates private continuity files under `state/`; those files are ignored and must not be committed.
