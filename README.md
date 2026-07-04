# Personal Trading Coach

中文股票交易教练本地工作台。它帮助用户把交割单、交易想法、市场判断和阅读材料整理成可复盘、可验证、可沉淀的交易训练记录。

本项目的目标不是预测行情，也不是给出买卖建议，而是训练一套更稳定的个人交易流程：事实先行、计划先行、风险先行、复盘沉淀。

## 它能做什么

- 解析复制粘贴的券商成交表格文本。
- 本地脱敏文字型 PDF 交割单。
- 标准化 CSV/XLSX 历史交割单。
- 检查姓名、身份证、手机号、资金账号、客户号、股东账号、银行卡、地址、资金余额等敏感信息。
- 维护本地历史交易底账。
- 查询手续费、交易频率、日内同票买卖、FIFO 已实现盈亏、剩余仓位成本。
- 生成盘后教练证据包。
- 辅助写每日教练手记、明日研究股票池、交易预案、雪球复盘草稿。
- 做文章观点摘要和叙事污染检查。
- 做盘前/盘中纪律检查。
- 把每日复盘沉淀为持仓故事线、交易模式和教练记忆的待审核更新草稿。

## 它不做什么

- 不荐股。
- 不预测未来涨跌。
- 不输出直接买入、卖出、加仓、减仓、清仓指令。
- 不把用户市场判断直接当成事实。
- 不把单次盈利升级成“可复制模式”。
- 不提交真实交割单、截图、PDF、账户信息或真实输出报告。

## 隐私边界

真实数据只应放在这些被 Git 忽略的目录：

```bash
private/
reports/
state/
```

不要提交：

- 原始 PDF 交割单；
- 原始 CSV/XLSX 交割单；
- 交易截图；
- 原始粘贴文本；
- 生成的报告；
- SQLite 账本；
- 任何姓名、身份证、手机号、资金账号、客户号、股东账号、银行卡、营业部、地址、资金余额。

长期账本只保存标准交易事实：

- 日期、时间；
- 证券代码、证券名称；
- 买卖方向；
- 数量、价格、成交额、净发生额；
- 佣金、印花税、过户费、其他费用。

## 安装为 Codex Skill

当前仓库包含主 Skill：

```bash
codex-skill/SKILL.md
```

本机已安装路径示例：

```bash
/Users/makubex/.codex/skills/personal-trading-coach/SKILL.md
```

兼容旧名称：

```bash
compat/stock-trading-coach-agent/SKILL.md
```

如果你仍然调用 `$stock-trading-coach-agent`，它会转到新的 `personal-trading-coach` 工作流。

## 初始化

```bash
python3 scripts/init_state.py
```

这会创建本地私有连续状态：

```bash
state/coach_memory.md
state/coach_lenses.md
state/position_storylines.md
state/personal_trading_modes.md
state/research_pool_protocol.md
state/decision_events.md
```

这些文件不会进入 Git。

## 每日盘后流程

准备输入文件：

```bash
private/raw_pasted_trades.txt
private/journal.txt
private/market_view.txt
```

生成每日 run 包：

```bash
python3 scripts/daily_prepare.py \
  --trade-date YYYY-MM-DD \
  --pasted-trades-file private/raw_pasted_trades.txt \
  --journal-file private/journal.txt \
  --market-view-file private/market_view.txt
```

如果不想联网抓取市场快照：

```bash
python3 scripts/daily_prepare.py \
  --trade-date YYYY-MM-DD \
  --pasted-trades-file private/raw_pasted_trades.txt \
  --journal-file private/journal.txt \
  --market-view-file private/market_view.txt \
  --offline-market
```

然后由 Codex 根据 `reports/run_*/daily_session_prompt.md` 直接改写：

```bash
reports/run_*/coach_note.md
reports/run_*/research_pool.md
reports/run_*/xueqiu_post.md
```

最后校验并渲染：

```bash
python3 scripts/finalize_session.py reports/run_YYYYMMDD_HHMMSS --strict
python3 scripts/draft_state_updates.py reports/run_YYYYMMDD_HHMMSS --require-finalize-ok
```

## 粘贴交割单文本

支持从券商成交页面复制表格文本，例如：

```text
序号  发生日期    发生时间   证券代码  证券名称  交易类别  成交数量  成交均价  成交金额  发生金额  佣金  印花税  过户费
1     2026-07-04  09:31:00  301001    虚构科技  证券买入  500       20.100    10050.00  -10055.00 2.00 0.00   0.00
```

手动解析：

```bash
python3 scripts/parse_pasted_trades.py private/raw_pasted_trades.txt \
  -o reports/pasted_trades_extracted.csv \
  --trade-date YYYY-MM-DD
```

隐私检查：

```bash
python3 scripts/privacy_guard.py reports/pasted_trades_extracted.csv \
  --report reports/privacy_guard_report.json
```

## PDF / CSV / XLSX 历史导入

文字型 PDF：

```bash
python3 scripts/sanitize_pdf_statement.py private/history_statement.pdf \
  -o reports/sanitized_pdf_trades.csv \
  --report reports/sanitize_pdf_report.json
```

如果 PDF 是扫描版，脚本会提示需要本地 OCR；不要把原始 PDF 全文上传给 AI。

CSV/XLSX：

```bash
python3 scripts/normalize_statement.py private/history_statement.csv \
  -o reports/normalized_trades.csv
```

导入账本前必须先隐私检查：

```bash
python3 scripts/privacy_guard.py reports/normalized_trades.csv \
  --report reports/privacy_guard_report.json
```

导入本地历史交易底账：

```bash
python3 scripts/ledger_import.py reports/normalized_trades.csv
```

## 账户查询

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
python3 scripts/ledger_query.py stock --stock-code 301421
```

生成账户事实报告：

```bash
python3 scripts/account_report.py --html reports/account_report.html
```

说明：

- `cash-diff` 是现金流差额，不等于持仓未闭合时的已实现盈亏。
- `realized` 和 `pnl-by-stock` 使用 FIFO 匹配。
- 如果历史数据从已有持仓之后才开始，无法匹配的卖出会标记为 `unmatched_sell_quantity`，不会强行制造虚假盈亏。

## 明日研究股票池

研究池不是推荐名单，只是训练用候选面。

```bash
python3 scripts/research_pool_builder.py private/candidate_universe.csv \
  --trade-date YYYY-MM-DD \
  --md reports/research_pool_candidates.md
```

用户最多从研究池中选 3 支进入明日交易预案。没有触发条件、失效条件、止损锚点和仓位上限，不能从研究池升级为交易预案。

## 盘前 / 盘中纪律检查

```bash
python3 scripts/pre_trade_guard.py \
  --security "301001 虚构科技" \
  --action "拟执行动作" \
  --trigger "触发条件" \
  --invalidation "失效条件" \
  --stop-anchor "止损锚点" \
  --plan reports/run_YYYYMMDD_HHMMSS/trade_plan.md \
  --html reports/pre_trade_guard.html
```

该脚本只输出风控反问，不输出买卖结论。

## 文章叙事污染检查

```bash
python3 scripts/article_digest.py \
  --trade-date YYYY-MM-DD \
  --url "https://example.com/article" \
  --affected-trade "是否影响当天交易动作" \
  --json reports/article_digest.json \
  --md reports/article_digest.md
```

检查重点：

- 是否强化已有持仓偏见；
- 是否诱发追涨；
- 是否提供可验证事实；
- 是否只是情绪安慰；
- 是否影响当天交易动作。

## 输出目录

常见输出：

```bash
reports/run_YYYYMMDD_HHMMSS/
reports/account_report.html
state/account_ledger.sqlite
state/account_ledger.csv
```

这些都是本地私有产物，不进入 Git。

## 开发检查

```bash
python3 -m py_compile scripts/*.py
git status --short
git diff --cached --stat
git diff --cached --name-only
```

提交前确认没有真实交易数据、原始交割单、截图、账户信息或资金余额。

## GitHub

公开仓库：

```text
https://github.com/MQ-Makubex/personal-trading-coach
```

公开仓库只保存源码、模板和文档；真实交易数据只留在本机 ignored 目录。
