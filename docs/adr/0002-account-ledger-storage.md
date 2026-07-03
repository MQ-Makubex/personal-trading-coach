# Store the account ledger as CSV, SQLite, and Markdown summaries

The account ledger will keep a transparent `account_ledger.csv` as the canonical cleaned export, a local `account_ledger.sqlite` for repeatable account performance queries, and Markdown summaries for user-facing review. CSV keeps the ledger auditable and portable, SQLite supports fee, turnover, monthly, and per-stock queries that brokers usually do not expose well, and Markdown preserves the coach-readable conclusions.
