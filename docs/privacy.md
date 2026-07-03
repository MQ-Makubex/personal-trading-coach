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
- `scripts/privacy_guard.py` must run before trade facts enter the ledger.
- `scripts/ledger_import.py` accepts only standard trade-fact CSV files that have passed privacy checks.
- `scripts/ledger_query.py` answers factual ledger questions only.
- `scripts/build_evidence_packet.py` creates coach-readable evidence; the coach still writes the judgment directly.
- `scripts/daily_session.py` prepares one ignored run directory with evidence, prompts, drafts, and rendered placeholders.
- `scripts/pre_trade_guard.py` creates plan-consistency and red-card questions for pre-trade or intraday use.
- `scripts/init_state.py` creates private continuity files under `state/`; those files are ignored and must not be committed.
