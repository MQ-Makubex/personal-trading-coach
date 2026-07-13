# Personal Trading Command Center Design System

## 1. Visual Theme And Atmosphere

This is a private, local-first trading training system for one user. It is not a landing page and not a single scrolling report. The selected direction is `A · 夜间风险指挥台`, with the date-calendar structure from direction B used on the training timeline.

The interface must feel like an evidence desk that blocks impulsive action: risk and discipline appear before opportunity, account facts remain visually separate from coach interpretation, and every document is rendered inside one coherent product instead of opening legacy report HTML.

User-confirmed dials:

- 视觉冒险度: 5/10
- 动效强度: 5/10
- 信息密度: 8/10

Reference DNA:

- IBM Carbon: strict 8px rhythm, 48px command bar, flat rectangular zoning, dark Gray 100/90/80 luminance steps, Blue 40 interaction color, semantic status colors.
- Linear: `#0f1011` and `#191a1b` dark-native surfaces, `rgba(255,255,255,.08)` hairlines, 6px control radius, quiet hover luminance changes, layered shadow only for true overlays.

## 2. Palette And Roles

- Canvas: `#0c0d0f`
- Command bar: `#0f1012`
- Primary surface: `#131518`
- Secondary surface: `#181b1f`
- Elevated surface: `#20242a`
- Border subtle: `rgba(255,255,255,.07)`
- Border strong: `rgba(255,255,255,.14)`
- Primary text: `rgba(255,255,255,.92)`
- Body text: `rgba(255,255,255,.85)`
- Secondary text: `rgba(255,255,255,.66)`
- Muted text: `rgba(255,255,255,.48)`
- Interactive blue: `#4589ff`
- Interactive blue soft: `rgba(69,137,255,.14)`
- Positive: `#42be65`
- Warning: `#f1c21b`
- Negative: `#fa6b6b`
- Risk surface: `rgba(250,107,107,.10)`

Blue means interaction or selection. Red, green, and yellow are reserved for financial or risk semantics. No lime accent, purple, gradient glow, pure black, or decorative color blobs.

## 3. Typography Rules

Chinese UI and prose use the local system stack:

`-apple-system, BlinkMacSystemFont, "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", "Noto Sans SC", sans-serif`

Financial figures, stock codes, timestamps, and compact metadata use:

`"SFMono-Regular", "SF Mono", Menlo, Monaco, Consolas, monospace`

Rules:

- Chinese body text is at least 14px; document prose is 16px with 1.75 line-height.
- Chinese weights are 400, 500, and 600 only.
- Letter spacing is always 0. No italic and no negative tracking.
- Financial figures use tabular numerals and right alignment in comparisons.
- Page headings stay compact: 24-32px desktop, 22-26px mobile. There is no marketing-scale hero heading.
- Long prose is constrained to approximately 36 Chinese characters per line.

## 4. Component Styling

### Command Bar And Navigation

- Height: 48px desktop; wraps into two rows on small screens.
- Background: `#0f1012`; bottom border: `1px solid rgba(255,255,255,.14)`.
- Main pages: 今日、训练时间线、股票故事、交易底账、纪律规则.
- Active page uses blue text and a 2px bottom indicator.
- Global search is always available and routes to the timeline with URL query state.

### Risk Band

- Full-width horizontal band, not a decorative card.
- Left border: 3px negative red when a rule is breached.
- Contains one sentence of current risk judgment, evidence status, and the next required answer.
- Risk language must be blunt and factual. It never predicts prices.

### Metrics

- Metrics are aligned cells separated by hairlines, not floating cards.
- Primary account metric: `总盈亏（含持仓）`.
- Required supporting metrics: `已实现盈亏`, `持仓浮动盈亏`, `总费用`.
- `总费用` is disclosed separately and is never subtracted a second time.
- Unknown market prices render `待核验`, never an estimate or last buy price.

### Tables And Event Rows

- Numeric columns use tabular figures and align right.
- Row height: 44-52px; borders provide grouping.
- Hover adds a subtle surface change and 2px blue left indicator.
- Long copy clamps to two lines in index views and remains complete on detail pages.
- Tables over mobile width use contained horizontal scrolling with a visible edge cue.

### Calendar Timeline

- A left date rail exposes available trading days and counts.
- The center column groups coach notes, market snapshots, pools, pool reviews, trade plans, intraday discipline, Xueqiu drafts, and trades by date.
- Type, date, stock, query, and page are reflected in URL parameters.
- Pagination is explicit. No 620px archive-within-a-scrollbox pattern.

### Markdown Documents

- Markdown is parsed locally and rerendered into the shared site shell.
- Legacy report HTML is never used as the primary reading destination.
- Document pages keep breadcrumbs, source type, date, associated stocks, and previous/next navigation.
- Tables, code, quotes, lists, and headings inherit the dark command-center system.

## 5. Layout Principles

The generated site is multi-page:

- `index.html`: current account and risk command center.
- `timeline.html`: searchable, filterable, paginated training timeline with date rail.
- `stories.html`: current holdings and closed historical stock stories.
- `ledger.html`: account metrics, transactions, fees, and per-stock PnL.
- `rules.html`: coach memory, trading modes, research-pool protocol, decision events, and discipline.
- `documents/*.html`: unified Markdown reading pages.
- `stocks/*.html`: one continuous evidence-backed story per stock.

Layout rules:

- Desktop content width: up to 1480px with 20-28px margins.
- Use asymmetric `2fr / 1fr` work areas where the primary decision surface needs an inspector.
- Prefer full-width bands, split panes, hairlines, and whitespace over universal cards.
- Cards are limited to repeated story summaries and true overlays; cards are never nested.
- Mobile becomes one column, but navigation, filters, pagination, and story tabs remain usable.

## 6. Depth And Elevation

- Level 0: canvas `#0c0d0f`.
- Level 1: primary surface `#131518` plus subtle border.
- Level 2: selected or inspector surface `#181b1f` plus strong border.
- Level 3: dropdown, command palette, and modal only; use a restrained multi-layer shadow.
- Regular sections and rows have no drop shadow.
- Radius scale: 0px structural bands, 4px tags, 6px controls, 8px overlays. Pills are limited to status labels.

## 7. Do And Don't

Do:

- Put risk, quote freshness, and evidence status before opportunity.
- Mark facts as account facts, market facts, coach interpretation, or pending review.
- Let users move between date timeline and stock storyline in one click.
- Preserve true links so pages support Cmd+Click and browser history.
- Provide loading, empty, missing-quote, and no-results states.
- Keep generated private output uncommitted.

Don't:

- Do not return to a single long static page.
- Do not open old generated report HTML for Markdown-backed documents.
- Do not use the broker cash balance as total PnL.
- Do not subtract total fees again after using fee-inclusive costs and net sell proceeds.
- Do not present inferred story text as coach-confirmed judgment.
- Do not use marketing heroes, nested cards, decorative gradients, or profile promotion.

## 8. Responsive Behavior

- `>= 1180px`: full command bar, `2fr / 1fr` work areas, date rail visible.
- `768-1179px`: navigation remains horizontal, inspectors move below the primary surface.
- `< 768px`: compact two-row command bar, single-column content, horizontal date strip, tables in bounded scroll containers.
- Interactive targets are at least 40px high; primary mobile controls are 44px.
- Long Chinese titles wrap naturally; codes and money never overlap labels.
- `prefers-reduced-motion` removes movement while retaining state color changes.

## 9. Motion Philosophy

Motion is functional and short:

- Button feedback: 120ms `cubic-bezier(.23,1,.32,1)` with `scale(.98)`.
- Hover and selected-state color transitions: 140ms.
- Modal and mobile drawer: opacity plus `scale(.97)` in 180-220ms.
- Keyboard-triggered navigation and command search have no animation.
- Only `transform` and `opacity` move; no `transition: all`.
- Hover effects run only under `(hover: hover) and (pointer: fine)`.

## Memory Point

The product should be remembered as: `先暴露风险，再允许看机会。`
