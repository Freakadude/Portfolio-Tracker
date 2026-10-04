# Personal Portfolio Manager — Requirements Specification

Oct 4, 2026 · @Snake Plissken

## 1. Purpose and scope

Build a self-hosted, single-user web app that records every holding and transaction, values the portfolio in EUR every trading day, and runs an AI agent that watches positions and news and proposes strategy-aligned adjustments. The app advises; it never places trades.

Working name: **Folio**. This document is the build brief for Claude Code. Requirements carry IDs (`FR-<AREA>-NN` functional, `NFR-NN` non-functional) and a MoSCoW priority (M = must, S = should, C = could). Every requirement marked M is in scope for v1.

### Goals

| ID | Goal | What done looks like |
| --- | --- | --- |
| G1 | Holdings ledger | Add, edit and delete instruments and transactions (buy, sell, dividend, fee, split, transfer) for ETFs, ETCs, equities, bonds, funds and cash; positions, cost basis and realized/unrealized P&L are derived, never typed in |
| G2 | Prices and valuation | Daily close history for every instrument held (plus delayed intraday quotes in market hours); value and change in EUR and % per position and for the whole portfolio, over any period |
| G3 | Dashboards | The user builds and saves dashboards from a widget library by drag and drop, without code |
| G4 | Strategy-aligned monitoring | A deterministic rules engine plus an AI agent check positions and the portfolio against user-defined strategies and propose concrete adjustments |
| G5 | News intelligence | Financial news is collected, linked to holdings (including through ETF look-through), scored for impact and summarised with suggested responses |
| G6 | Notifications | Every recommendation and alert lands in an in-app inbox; important ones also reach the phone |

### Non-goals (v1)

- No order execution and no broker trading API. The user acts manually at the broker.
- No multi-user accounts, sharing or tenancy. One owner, one portfolio set.
- No exposure to the public internet. Access is LAN or Tailscale only.
- No tax filing. The app produces a Box 3 reference snapshot, not a return.
- No tick-level or real-time streaming data. Daily closes plus 15-minute delayed quotes are enough.
- No scraping of paywalled article bodies. News is stored as headline, summary, metadata and link.

### Success criteria

- After a broker import, each position's quantity and cost basis match the broker statement to the cent.
- Closing prices for all held instruments are stored within 2 hours of their exchange close on trading days.
- Every recommendation shows the rule or evidence behind it, its sources, and a confidence level.
- A new dashboard with three widgets can be built in under two minutes without reading help.
- At idle the stack uses under 512 MB RAM and under 2% CPU on the homelab Docker host.
- LLM spend stays inside a user-set monthly budget, with a hard stop at the cap.

## 2. Context and assumptions

The app serves one Netherlands-based investor running a long-term, rules-based EUR portfolio of UCITS ETFs plus a few direct equities, hosted on an existing Proxmox homelab. Claude Code should treat the assumptions below as defaults and flag any it has to break.

| ID | Assumption | Consequence for the build |
| --- | --- | --- |
| A1 | Single owner, no other users | One local account; no roles, no tenancy |
| A2 | Base currency EUR | All totals, P&L and charts in EUR; native-currency values kept alongside; FX from ECB reference rates |
| A3 | Main instruments: Ireland-domiciled UCITS ETFs and a physical gold ETC on Xetra / Euronext Amsterdam, plus directly held equities (largest: ASML on Euronext Amsterdam) | Instrument identity is the ISIN; one ISIN can have several listings (exchange + ticker + currency) |
| A4 | Bonds, funds and cash are rarer but must fit the same model | Asset class is a field, not a separate code path; bonds get optional coupon/maturity fields |
| A5 | Dutch Box 3 taxation; selling does not trigger capital gains tax under current rules | Realized P&L is informational; a 1 January valuation snapshot is kept every year; tax logic sits in a swappable module because the regime is being reformed |
| A6 | Broker not fixed in this spec | Generic CSV import with saved column mappings; broker-specific presets added later (see open questions) |
| A7 | Docker host is a Proxmox LXC managed through Portainer; remote access goes through a Tailscale subnet router; no public ports | Ship a `docker-compose.yml` that Portainer can deploy as a stack; bind to the LAN interface; no TLS termination inside the app |
| A8 | Home Assistant OS runs on a separate VM, with the companion app on the phone | HA's notify service is a ready-made mobile push channel, next to ntfy and Web Push |
| A9 | LLM work runs on the Anthropic Claude API with the owner's key | Model per task is configurable; monthly budget cap enforced in code |
| A10 | Free or low-cost market-data and news tiers are acceptable | Every external source sits behind an adapter with rate limiting, caching and a fallback provider |
| A11 | Investment style: long-horizon, rules-based; rebalance mainly by directing new contributions; pre-committed trim thresholds for thematic positions; no emotional profit-taking | The agent's advice must respect these principles by default and say so when it argues against one |
| A12 | Development runs natively first, containerised once features pass their tests | Code must run with `uv run` / `npm run dev` locally and in containers with the same config |

## 3. Glossary

These terms have one meaning throughout the code, the UI and this document.

| Term | Meaning |
| --- | --- |
| Instrument | A security identified by ISIN: ETF, ETC, equity, bond, fund, or a cash balance |
| Listing | One place an instrument trades: exchange MIC, ticker, trading currency, data-provider symbol |
| Transaction | A dated event that changes holdings or cash: buy, sell, dividend, interest, fee, tax, split, transfer in/out, deposit, withdrawal |
| Lot | The quantity bought in one buy transaction, with its own price and date; sells consume lots |
| Position | Current holding of one instrument in one account, derived from transactions |
| Cost basis | What the open quantity cost including fees; method FIFO (default) or average cost, chosen per account |
| Realized P&L | Proceeds of a sell minus the cost basis of the lots it consumed, minus fees |
| Unrealized P&L | Current market value minus cost basis of the open quantity |
| Total return | Price change plus dividends and interest received, minus fees, over a period |
| TWR | Time-weighted return: performance with the effect of deposits and withdrawals removed |
| MWR / XIRR | Money-weighted return: the annualised internal rate of return of actual cash flows |
| Target allocation | The intended weight of each sleeve (an instrument or group) in the portfolio |
| Drift | Actual weight minus target weight, in percentage points and relative % |
| Rebalance band | The drift range inside which no action is suggested |
| Look-through exposure | What an ETF holds underneath: top constituents, sectors, countries, currencies |
| Strategy | A named, versioned set of targets, bands, thresholds and principles the owner commits to |
| Rule | A deterministic check inside a strategy that emits a signal when its condition holds |
| Signal | A raw rule or news trigger, before the agent has reasoned about it |
| Recommendation | An agent output: a proposed action with rationale, evidence, sources, confidence and expiry |
| Impact score | 0–100 estimate of how much a news item may move a holding, with direction and horizon |
| Peildatum | 1 January reference date whose portfolio value Dutch Box 3 uses |
| Corporate action | Split, reverse split, ISIN change, merger, fund closure or distribution policy change |

## 4. Architecture and tech stack

One Docker image runs as two services: `web` (API plus the built UI) and `worker` (all scheduled jobs, ingestion and AI calls). They share one SQLite database on a volume. An optional `ntfy` container handles phone push. Long LLM calls therefore never block the UI, and the whole stack stays under the 512 MB idle budget.

&#91;embedded content: architecture · 2 app services, 1 database, 4 external source groups\]

The browser only ever talks to `web`; every call to a data provider, news feed, the Claude API or a push channel leaves from `worker`, so rate limits and budgets live in one place.

### Services

| Service | Image | Responsibility | Ports |
| --- | --- | --- | --- |
| `web` | `folio` | REST API, Server-Sent Events for live inbox updates, serves the built React app, auth | 8080 (LAN / tailnet only) |
| `worker` | `folio` (command `worker`) | APScheduler jobs: prices, FX, macro series, news, ETF holdings refresh, rules evaluation, agent runs, notification dispatch, backups | none |
| `ntfy` (optional) | `binwiederhier/ntfy` | Self-hosted push to the ntfy phone app | 8081 (LAN / tailnet only) |

`web` and `worker` talk only through the database. User actions that need the worker (refresh prices now, run the agent now) insert a row into a `job_requests` table, which the worker polls every 5 seconds.

### Tech stack

| Layer | Choice | Why |
| --- | --- | --- |
| Language / runtime | Python 3.12, managed with `uv` | Best finance and data libraries; one language for API, jobs and agent |
| API | FastAPI, Pydantic v2 | Typed request/response models; OpenAPI spec generated for the frontend client |
| Persistence | SQLite in WAL mode via SQLAlchemy 2.0; Alembic migrations | Zero-ops and tiny at this data volume; switching to PostgreSQL is a connection-string change |
| Money and quantities | Python `Decimal`, stored as TEXT through a custom SQLAlchemy type | SQLite numerics are floats; floats are banned for money and quantities |
| Scheduling | APScheduler 3 with SQLAlchemy job store | Cron-style jobs that survive restarts; already proven in a similar homelab app |
| Analytics | pandas + numpy, `pyxirr` for XIRR | Vectorised return and risk maths |
| HTTP clients | `httpx` with `tenacity` retries | Async, timeouts, backoff |
| LLM | Anthropic Python SDK (Claude API) | Tool use and structured JSON output for recommendations |
| Frontend | React 18 + TypeScript + Vite, TanStack Query, React Router | A drag-and-drop dashboard builder needs client-side state; an htmx UI was considered and rejected for this reason |
| UI kit | Tailwind CSS + shadcn/ui (Radix primitives), light and dark theme | Clean, accessible defaults without a heavy design system |
| Charts | Apache ECharts (general charts), TradingView Lightweight Charts (price and candlestick) | ECharts covers treemaps, donuts, heatmaps; Lightweight Charts is fast for long price series |
| Dashboard grid | `react-grid-layout` | Drag, resize, responsive breakpoints, serialisable layouts |
| Forms | react-hook-form + zod | Shared validation, typed |
| PWA | Vite PWA plugin, service worker | Install to phone home screen; Web Push |
| Quality | ruff, mypy (strict on `domain/`), pytest + hypothesis, Vitest, Playwright | Ledger maths is property-tested; key flows are tested end to end |

### Backend module layout

| Package | Contents |
| --- | --- |
| `folio/domain` | Pure ledger and valuation logic: lots, cost basis, P&L, corporate actions. No I/O. |
| `folio/marketdata` | Provider adapters (prices, FX, macro, ETF holdings), symbol resolution, caching |
| `folio/analytics` | Returns (TWR, XIRR), risk, allocation, drift, look-through aggregation |
| `folio/strategies` | Strategy schema, rule types, evaluator |
| `folio/news` | Source adapters, dedup, entity linking, impact scoring |
| `folio/agent` | Agent loop, tool definitions, prompts, recommendation lifecycle, cost tracking |
| `folio/notify` | Channel adapters, routing, quiet hours, digests |
| `folio/dashboards` | Dashboard and widget persistence, widget data endpoints |
| `folio/api` | FastAPI routers, auth, SSE |
| `folio/jobs` | Scheduler setup, job definitions, job-request polling |
| `web/` | React app |

## 5. Data model

Transactions are the only source of truth for holdings; lots, positions and P&L are derived from them and rebuilt whenever a transaction for that account and instrument changes. All tables get `id`, `created_at`, `updated_at`; user-editable records are soft-deleted (`deleted_at`).

### Core ledger

| Entity | Key fields | Notes |
| --- | --- | --- |
| `account` | name, broker, cost\_basis\_method (`FIFO` \| `AVG`), base\_currency, active | One per broker account or depot |
| `instrument` | isin (unique, nullable for cash), name, asset\_class (`ETF`, `ETC`, `EQUITY`, `BOND`, `FUND`, `CASH`, `OTHER`), issuer, domicile, ter\_pct, distribution (`ACC` \| `DIST`), benchmark, tags\[\], bond fields (coupon\_pct, maturity\_date, rating), status | Identity is the ISIN |
| `listing` | instrument\_id, exchange\_mic, ticker, currency, provider\_symbols (JSON per provider), pricing\_primary | One listing per instrument is used for valuation |
| `transaction` | account\_id, instrument\_id, type, trade\_date, settle\_date, quantity, price, currency, fx\_rate\_to\_eur, fees, taxes, net\_amount\_eur, note, source (`manual` \| `import`), import\_batch\_id, external\_ref | `external_ref` + account makes imports idempotent |
| `lot` | buy\_transaction\_id, open\_quantity, cost\_eur | Derived |
| `lot_match` | sell\_transaction\_id, lot\_id, quantity, cost\_eur, proceeds\_eur, realized\_pnl\_eur | Derived; explains every realized P&L number |
| `position` | account\_id, instrument\_id, quantity, cost\_basis\_eur, avg\_cost\_eur | Derived; market value joined at read time |
| `corporate_action` | instrument\_id, type, ex\_date, ratio, new\_isin, applied\_at | Splits adjust lots without changing cost basis |
| `import_batch` | file\_name, preset, rows\_total, rows\_imported, rows\_skipped, status, error\_report |  |
| `contribution_plan` | amount\_eur, cadence, next\_date | Feeds "rebalance with new money" advice |

### Market data

| Entity | Key fields | Notes |
| --- | --- | --- |
| `price_bar` | listing\_id, date, open, high, low, close, adj\_close, volume, source, fetched\_at | Unique (listing\_id, date); daily |
| `quote` | listing\_id, ts, price, source | Delayed intraday; pruned after 7 days |
| `fx_rate` | date, currency, rate\_per\_eur, source | ECB reference rates |
| `macro_series` / `macro_point` | code (e.g. US 10-year real yield, trade-weighted USD), source, date, value | Indicators a strategy can watch |
| `etf_holding_snapshot` | instrument\_id, as\_of, constituent\_name, constituent\_isin, ticker, weight\_pct, sector, country, currency | Look-through data |
| `portfolio_snapshot` | date, total\_value\_eur, net\_contributions\_eur, cash\_eur, positions JSON, is\_peildatum | Written nightly; 1 January flagged |
| `watchlist` / `watchlist_item` | name; instrument\_id, note | Tracked but not held |

### Strategy, agent and news

| Entity | Key fields | Notes |
| --- | --- | --- |
| `strategy` / `strategy_version` | name, active; version, definition (YAML), created\_at | Versions are immutable |
| `signal` | strategy\_version\_id, rule\_id, subject, ts, payload, dedup\_key, state (`new`, `consumed`, `suppressed`) | Raw rule or news trigger |
| `news_source` | name, kind (`rss`, `api`, `web_search`), url, enabled, trust\_weight, poll\_minutes, language | Owner-editable list |
| `news_item` | source\_id, canonical\_url (unique), title, summary, published\_at, language, content\_hash, cluster\_id | Headline, summary and link only |
| `news_link` | news\_item\_id, instrument\_id, link\_type (`direct`, `look_through`, `macro`, `theme`), relevance | Look-through links carry the ETF weight used |
| `news_assessment` | cluster\_id, impact\_score, direction, horizon, affected\_instruments, rationale, model, cost\_eur |  |
| `recommendation` | trigger, action\_type, subjects, proposal (amounts, %), rationale, evidence JSON, sources\[\], confidence, severity, expires\_at, status, user\_note, linked\_transaction\_ids, outcome JSON | See section 11 for the lifecycle |
| `price_alert` | instrument\_id, condition, threshold, active, last\_fired\_at | Simple user alerts |
| `agent_run` | trigger, model, started\_at, finished\_at, input\_tokens, output\_tokens, cost\_eur, tool\_calls JSON, status, error | Full trace of every LLM call |

### UI, delivery and system

| Entity | Key fields | Notes |
| --- | --- | --- |
| `dashboard` | name, layouts JSON (per breakpoint), is\_default, sort\_order |  |
| `widget` | dashboard\_id, type, config JSON, grid (x, y, w, h) |  |
| `notification` | source (recommendation / alert / system), channel, severity, title, body, sent\_at, delivery\_status, read\_at |  |
| `job_request` / `job_run` | job, params; started\_at, finished\_at, status, log |  |
| `setting` | key, value JSON |  |
| `audit_log` | ts, actor (`user`, `worker`, `agent`), entity, entity\_id, action, diff JSON | Append-only |

### Invariants (property-tested)

1. For every position, the sum of open lot quantities equals the position quantity.
2. Per instrument, realized P&L + unrealized P&L equals current market value + net sale proceeds − total purchase cost (trading fees are included in cost and deducted from proceeds).
3. A sell can never consume more than the open quantity; such a transaction is rejected with a clear error.
4. Applying a split changes quantity and per-unit cost but leaves total cost basis and market value unchanged.
5. Rebuilding derived tables from transactions twice gives identical results.

## 6. Instruments and market data

EODHD's EOD All-World plan is the recommended primary price source: it covers European ETF listings with 30+ years of history and 100,000 calls a day for $19.99 a month. Everything else is free. Every source sits behind an adapter, so swapping providers never touches valuation code.

### Data sources

| Source | Used for | Free tier | Paid tier worth considering | Role |
| --- | --- | --- | --- | --- |
| [EODHD](https://eodhd.com/pricing) | Daily prices, 15-min delayed quotes, dividends and splits, news with sentiment; ETF constituents via its Fundamentals feed | 20 calls/day, 1 year of EOD history, 15-min delayed live data | EOD Historical All-World $19.99/mo (100,000 calls/day, 30+ years); ETF fundamentals need the $59.99 Fundamentals or $99.99 All-in-one plan | Primary prices |
| [Twelve Data](https://twelvedata.com/pricing) | Prices and quotes | 800 requests/day but only 3 markets, all US | Grow (from $29/mo) adds EOD global equities and ETFs | Secondary / fallback |
| Yahoo Finance via `yfinance` | Prices for `.AS` / `.DE` tickers | Free, unofficial, can break without notice | — | Optional fallback, off by default |
| [OpenFIGI](https://www.openfigi.com/api/documentation) | ISIN → listings (exchange, ticker, currency) | Free; mapping 25 requests/min without key, 25 per 6 s with a free key | — | Symbol resolution |
| ECB euro reference rates | Daily FX for EUR conversion | Free, no key | — | FX |
| FRED (St. Louis Fed) | Macro series: US real yields, trade-weighted dollar, policy rates | Free with key | — | Macro indicators |
| Fund issuer holdings files (iShares, VanEck, HANetf, HSBC, SPDR) | ETF look-through | Free downloads; formats differ per issuer | — | Look-through; manual CSV upload as fallback |

The app must work on free tiers alone (a portfolio of about 10 listings needs roughly 10 EOD calls a day), with reduced history and no look-through until the owner adds a paid key.

### Requirements

| ID | Pri | Requirement | Acceptance |
| --- | --- | --- | --- |
| FR-INS-01 | M | Add an instrument by ISIN. The app resolves listings through OpenFIGI, shows candidates (exchange, ticker, currency) and the owner picks the pricing listing. Name, asset class and issuer are prefilled and editable. | Entering IE00B5BMR087 returns its Xetra and Euronext listings; picking one triggers a price backfill |
| FR-INS-02 | M | Create an instrument manually when it cannot be resolved (unlisted bond, fund, private holding) and enter prices by hand. | A manual instrument values correctly from a hand-entered price |
| FR-INS-03 | M | Edit and archive instruments. Delete is blocked while transactions reference the instrument. | Delete attempt on a held instrument shows the blocking transactions |
| FR-INS-04 | S | Classification: asset class, region, sector, theme tags (e.g. defence, semiconductors, gold) and owner-defined sleeves used by strategies. | Allocation charts group by any of these |
| FR-INS-05 | S | Watchlist of instruments not held, priced like holdings. | Watchlist item shows price chart and can carry price alerts |
| FR-MD-01 | M | Provider adapter interface: `search`, `get_eod(listing, from, to)`, `get_quotes(listings)`, `get_dividends`, `get_splits`. Per provider: API key, priority, daily call budget. | A fake adapter in tests drives every job without network |
| FR-MD-02 | M | Nightly EOD job per exchange, 2 hours after its close, skipping exchange holidays via an exchange-calendar library. | No fetch attempts on 25 December; Xetra closes stored by 19:30 CET |
| FR-MD-03 | M | On instrument add, backfill daily history to at least the first transaction date (or as deep as the plan allows). | Chart shows history from first purchase |
| FR-MD-04 | M | Gap detection: missing trading days are flagged and refetched; the owner can enter or override a price, which is audited. | Override shows in the audit log with old and new value |
| FR-MD-05 | S | Delayed quotes every 15 minutes in market hours, for held listings only, only within the call budget; shown with timestamp and a "delayed" label. | Budget exhaustion pauses quotes, never EOD |
| FR-MD-06 | M | FX from ECB reference rates; valuation uses the rate of the valuation date, or the last earlier rate on non-publication days. | A USD listing on a Saturday uses Friday's rate |
| FR-MD-07 | M | Corporate actions: splits are fetched and proposed; on confirmation, lots are adjusted (invariant 4). Dividends for distributing funds are proposed as draft transactions. | Confirmed 1:4 split quadruples quantity and leaves cost basis unchanged |
| FR-MD-08 | S | Macro series from FRED and ECB on a configurable list, stored daily, chartable and usable in rules. | US 10-year real yield and trade-weighted dollar appear on a chart widget |
| FR-MD-09 | S | ETF look-through: holdings snapshots from issuer files, EODHD fundamentals or manual CSV, refreshed monthly; weight, sector, country, currency per constituent. | Look-through widget shows the portfolio's top 20 underlying companies |
| FR-MD-10 | M | Every provider call is counted; the scheduler never exceeds a provider's daily budget and the UI shows today's usage. | Usage page matches provider dashboard within 5% |
| FR-MD-11 | M | Fallback and staleness: after 3 failed attempts the next provider is tried; each bar records its source; a position whose last close is older than 3 trading days is marked stale. | Killing the primary adapter in tests still yields closes from the fallback |
| FR-MD-12 | C | Benchmarks: any listing can be marked as a benchmark for comparison charts. | Portfolio vs. benchmark line chart, both rebased to 100 |

## 7. Transactions, positions and P&L

The owner records what happened at the broker; the app derives everything else and shows the effect of a sell before it is saved. CSV import with saved column mappings is the main way data gets in.

### Position metrics (EUR, per position)

```latex
\begin{aligned}
\text{market value} &= q \cdot p_t \cdot fx_t \\
\text{unrealized P\&L} &= \text{market value} - \text{cost basis}_{open} \\
\text{unrealized \%} &= \text{unrealized P\&L} \,/\, \text{cost basis}_{open} \\
\text{realized P\&L}_{sell} &= (q_{sold} \cdot p_{sell} \cdot fx_{sell} - \text{fees}_{sell}) - \textstyle\sum \text{cost of consumed lots} \\
\text{total return} &= \text{unrealized} + \text{realized} + \text{income} - \text{standalone fees} - \text{taxes} \\
\text{day change} &= q \cdot (p_t \cdot fx_t - p_{t-1} \cdot fx_{t-1})
\end{aligned}
```

Native-currency versions of the same metrics are shown next to EUR for non-EUR listings, so the owner can separate price moves from currency moves.

### Requirements

| ID | Pri | Requirement | Acceptance |
| --- | --- | --- | --- |
| FR-TX-01 | M | Create, edit and delete transactions of every type: buy, sell, dividend, interest, fee, tax, transfer in/out, deposit, withdrawal. The form shows only the fields each type needs. | Each type round-trips through the API with validation errors in plain language |
| FR-TX-02 | M | Fees and taxes per transaction in their own currency; FX rate prefilled from ECB and overridable with the broker's actual rate. | Overridden rate is used in cost basis |
| FR-TX-03 | M | Cost-basis method per account: FIFO (default) or average cost. Switching recomputes all derived data and is audited. | Same transactions give documented expected results under both methods |
| FR-TX-04 | M | Sell preview: before saving, show the lots that will be consumed, proceeds, realized P&L in € and %, and the remaining position. | Preview equals the saved result to the cent |
| FR-TX-05 | M | Position detail: quantity, average cost, cost basis, market value, unrealized P&L €/%, lifetime realized P&L, income received, total return €/%, day change €/%, portfolio weight, first purchase date, lots table, transaction history, price chart with buy/sell markers. | All figures reconcile with invariants in section 5 |
| FR-TX-06 | M | Editing or deleting a past transaction rebuilds derived tables and recomputes portfolio snapshots from that date forward. | Backdated buy changes historical value charts |
| FR-TX-07 | M | CSV import wizard: upload, preview, map columns, set date format and decimal separator (comma decimals are common in NL exports), map instruments by ISIN, dry-run summary (new / duplicate / error rows), commit, and undo the whole batch. Mappings are saved as presets. | Re-importing the same file adds zero rows |
| FR-TX-08 | S | Broker presets for the owner's broker(s), built from a sample export the owner supplies. | Sample export imports with no manual mapping |
| FR-TX-09 | S | Cash tracking per account (opt-in): deposits, withdrawals, trade settlements and income update a cash position. | Cash balance matches broker after a month of activity |
| FR-TX-10 | S | Reconciliation: the owner enters broker-reported quantities at a date; the app lists differences. | Mismatch highlights the instrument and size |
| FR-TX-11 | S | Quick-add grid for several buys at once (e.g. one monthly contribution spread over five ETFs). | Five buys saved in one submit |
| FR-TX-12 | S | Realized P&L and income report per calendar year, per account and instrument. | Export to CSV |
| FR-TX-13 | C | Export all transactions and positions to CSV and JSON. | Export re-imports cleanly through FR-TX-07 |

## 8. Valuation, performance and allocation

The portfolio is revalued every night and shown over any period with both time-weighted and money-weighted returns. Allocation is shown at two levels: what the owner holds, and what the ETFs hold underneath. The second level is where hidden concentration shows up, for example one company held directly and again inside two or three ETFs.

### Requirements

| ID | Pri | Requirement | Acceptance |
| --- | --- | --- | --- |
| FR-PF-01 | M | Overview: total value, net contributions, total P&L €/%, day change €/%, cash, with a period selector (1D, 1W, 1M, 3M, YTD, 1Y, 3Y, 5Y, Max, custom). | Numbers update when the period changes, without reload |
| FR-PF-02 | M | Value history: daily portfolio value against cumulative net contributions; the gap between the lines is the gain. | Chart covers first transaction to today |
| FR-PF-03 | M | Returns per period for portfolio, sleeve and position: TWR (daily linking, cash flows at start of day) and annualised XIRR. | Matches a reference spreadsheet in tests to 0.01 percentage points |
| FR-PF-04 | M | Allocation by instrument, asset class, sleeve, region, sector and currency, with actual vs target and drift. | Drift values equal those used by the rules engine |
| FR-PF-05 | S | Look-through allocation: direct holdings plus ETF constituents × ETF weight, aggregated by company, sector, country and currency. Shows the total exposure to any single company across all wrappers. | A company held directly and inside two ETFs shows one combined exposure figure with its breakdown |
| FR-PF-06 | S | Risk: annualised volatility (1Y), maximum drawdown, current drawdown from peak, Sharpe ratio (risk-free rate configurable, default ECB deposit rate), beta to a chosen benchmark, correlation matrix of holdings over 90 days and 1 year. | Correlation of the gold position to equities is visible at a glance |
| FR-PF-07 | S | Attribution: each position's contribution to period return in € and percentage points. | Contributions sum to the portfolio return |
| FR-PF-08 | S | Benchmark comparison: up to 3 benchmarks rebased to 100 at the start of the period. | Works for any period |
| FR-PF-09 | S | What-if simulator: add hypothetical buys or sells and see the resulting allocation, drift, look-through exposure and cash before acting. Agent recommendations open here with their proposal prefilled. | Simulated state is never written to the ledger |
| FR-PF-10 | M | Nightly snapshot job writes `portfolio_snapshot`; the 1 January snapshot is flagged as peildatum and locked once the year closes. | Re-running the job is idempotent |
| FR-PF-11 | S | Annual tax-support report per calendar year: value on 1 January and 31 December, deposits, withdrawals, income, transaction costs, realized gains (from lot matches) and unrealized change. This covers both the current fictitious-return system and either form of the planned actual-return system. | Report exports to CSV and PDF |
| FR-PF-12 | C | Projection: Monte Carlo of future value with the contribution plan and configurable return/volatility assumptions; shown as a median line with 10–90% band. | Assumptions are visible on the chart |

**Why FR-PF-11 tracks realized gains and annual value change separately.** A bill to tax actual returns in Box 3 from 1 January 2028 [passed the Tweede Kamer and still awaits the Eerste Kamer](https://www.rijksoverheid.nl/themas/werk/inkomstenbelasting/plannen-werkelijk-rendement-box-3). Whether share gains would be taxed yearly on paper or only when sold [is still undecided](https://www.nextens.nl/fiscaal-nieuws/box-3-naar-vermogenswinstbelasting-voor-beleggers-spaarders-en-ondernemers/), and the proposal lets transaction costs be deducted. Keeping lot-level history, fees and yearly values means the app supports whichever version is adopted without a data migration. The report is a reference, not tax advice.

## 9. Web UI and dashboards

The UI is a calm, data-dense single-page app with a left navigation, light and dark themes, and a phone layout good enough to install as a PWA. Dashboards are built in place: switch to edit mode, add widgets from a library, drag and resize on a 12-column grid, save.

### Pages

| Page | Purpose |
| --- | --- |
| Home | The default dashboard |
| Holdings | Sortable table of positions, grouped by account or sleeve, with configurable columns and totals |
| Position detail | Metrics, price chart with buy/sell markers, lots, transactions, related news and recommendations |
| Transactions | Ledger with filters, add/edit forms, CSV import wizard, import history with undo |
| Dashboards | List, create, duplicate, templates, builder |
| Insights | Inbox of recommendations, alerts and digests with status actions (section 11) |
| News | Feed linked to holdings, filterable by instrument, impact and source |
| Strategies | Strategy editor, rule list, backtest of rules against history |
| Watchlist | Tracked instruments with alerts |
| Reports | Annual report, realized P&L, income, tax-support export |
| Settings | Accounts, data providers and keys, notifications, LLM models and budget, backups, appearance, language |
| System | Job runs, provider usage, agent runs with cost, logs |

### Presentation rules

- Numbers use tabular figures and are right-aligned; currency format is selectable (`€ 1.234,56` or `€1,234.56`).
- Gains and losses use green and red plus a sign and arrow, so meaning never depends on colour alone.
- Every figure that depends on a price shows its as-of time on hover; stale prices are marked.
- Every page has an empty state that says what to do next (e.g. "Add your first instrument").
- English UI; all strings go through an i18n layer so Dutch can be added without code changes.

### Dashboard requirements

| ID | Pri | Requirement | Acceptance |
| --- | --- | --- | --- |
| FR-DB-01 | M | Create, rename, duplicate, delete and reorder dashboards; mark one as default. | Default opens on Home |
| FR-DB-02 | M | Edit mode: add a widget from the library, drag, resize on a 12-column grid; layouts saved per breakpoint (desktop, tablet, phone). | Layout survives reload and differs per breakpoint |
| FR-DB-03 | M | Each widget has a side-panel config: scope (portfolio, account, sleeve, instrument, watchlist), period, metric, chart type, title; changes preview live. | Config change re-renders within 300 ms on cached data |
| FR-DB-04 | M | Widgets refresh when new data lands (Server-Sent Events) and on manual refresh. | A new close appears without reload |
| FR-DB-05 | S | Dashboard-level filters (period, account) that widgets can follow or ignore. | Changing the period updates all following widgets |
| FR-DB-06 | S | Clicking a chart element drills down (a donut slice opens the filtered holdings list). | Every chart widget has a drill-down target |
| FR-DB-07 | S | Export and import a dashboard as JSON; ship four templates: Overview, Risk, Income, Signals & news. | A template creates a working dashboard on an empty portfolio |
| FR-DB-08 | M | On phone width (390 px) widgets stack in a single column in the saved phone order. | No horizontal scrolling |
| FR-DB-09 | C | "Ask the portfolio" widget: a question box that runs the agent read-only and renders its answer with the figures it used. | Answers cite the data rows they used |

### Widget library (v1)

| Widget | Shows | Main options |
| --- | --- | --- |
| KPI tile | One metric with sparkline: value, day change, total return, XIRR, cash, largest drift | Metric, scope, period |
| Value history | Value vs net contributions over time | Scope, period, log scale |
| Price chart | Line or candlestick for a listing with buy/sell markers, 50/200-day averages, volume | Listing, period, overlays |
| Performance comparison | Rebased lines for positions, sleeves or benchmarks | Series list, period |
| Allocation | Donut or treemap by any classification, actual vs target toggle | Grouping, look-through on/off |
| Drift bars | Diverging bars of drift per sleeve with the rebalance band shaded | Strategy |
| Holdings table | Configurable columns, sort, conditional colours | Columns, grouping |
| Returns heatmap | Day/week/month return per position | Window |
| Monthly returns grid | Year × month portfolio return table | Scope |
| Look-through exposure | Top N companies, countries or sectors | N, dimension |
| Correlation matrix | Pairwise correlations of holdings | Window |
| Drawdown | Underwater chart from running peak | Scope, period |
| Return bridge | Waterfall from start value to end value: contributions, then each position's gain or loss | Period |
| Income | Dividends and interest by month | Period |
| Macro overlay | A macro series against a position on dual axes (e.g. real yields vs gold) | Series, position |
| News feed | Linked news above an impact threshold | Scope, minimum impact |
| Signals & recommendations | Open items from the Insights inbox | Severity filter |
| Note | Markdown text | — |

## 10. Strategies and rules engine

Deterministic code decides when something needs attention and computes every amount; the AI agent only explains, prioritises and adds context. A strategy is a versioned YAML document (example in the appendix) holding sleeves with targets and bands, risk limits, pre-committed thresholds, and the owner's written principles.

### Strategy contents

| Part | What it holds |
| --- | --- |
| Sleeves | Name, members (ISINs or tags), target weight, soft band and hard band (percentage points), optional trim threshold |
| Risk limits | Maximum look-through exposure to one company, maximum thematic weight, minimum and maximum cash buffer |
| Rules | Typed rules with parameters, severity and cooldown (table below) |
| Principles | Free text the agent must follow, e.g. "rebalance by directing new money first", "no emotional profit-taking" |
| Position theses | Per holding: why it is held, what would invalidate it, indicators to watch, next review date |
| Contribution plan | Amount and cadence used by the allocator |

### Rule types

| Rule | Fires when | Typical output |
| --- | --- | --- |
| `drift_band` | A sleeve's drift exceeds its soft band (advise directing new money) or hard band (advise a trade) | Allocation or trade proposal from the calculators |
| `trim_threshold` | A position or sleeve weight exceeds its pre-committed trim level | Trim proposal back to target, with the threshold quoted |
| `concentration_limit` | Look-through exposure to one company or country exceeds its limit | Warning with the breakdown by wrapper |
| `drawdown` | A position or the portfolio falls a set % from its peak | Review prompt that restates the thesis; never an automatic sell signal |
| `price_move` | Daily move above a % or above N standard deviations | Info signal; agent checks news for a cause |
| `price_level` | Price crosses an owner-set level | Alert |
| `macro_threshold` | A macro series crosses a level or moves a set amount over N days (e.g. real yields, trade-weighted dollar) | Signal linked to the sleeves that list that indicator |
| `correlation_shift` | Rolling correlation between a hedge and the equity sleeves rises above a level | Hedge-effectiveness warning |
| `contribution_due` | A planned contribution is N days away | Allocation plan for the new money |
| `cash_buffer` | Cash leaves its configured range | Alert |
| `thesis_review_due` | A position's review date arrives | Review prompt with a generated position summary |
| `stale_data` | Prices are stale or a provider keeps failing | System alert |

### Calculators

- **Contribution allocator.** Target value per sleeve is `w_i × (T + C)` for portfolio value `T` and new cash `C`. Each sleeve's shortfall is `max(0, target − current)`. New cash goes to shortfalls in proportion to their size; any remainder follows target weights. Orders below a minimum size (default €100) are merged into the next-largest order; whole-share rounding is applied when the account does not allow fractions.
- **Trim calculator.** Sells only the excess above target for the breached sleeve, chooses the listing with lowest fees, and shows the resulting realized P&L from lot matching.
- **Rebalance calculator.** Moves every sleeve back inside its band with the fewest trades, preferring buys over sells when the strategy says so.

### Requirements

| ID | Pri | Requirement | Acceptance |
| --- | --- | --- | --- |
| FR-ST-01 | M | Strategy editor with form view and raw YAML view, JSON-schema validation, a new immutable version on every save, and a diff between versions. | Invalid YAML is rejected with the line number |
| FR-ST-02 | M | One active strategy; others can run in shadow mode (evaluated and logged, never notified). | Shadow signals appear only on the Strategies page |
| FR-ST-03 | M | Rules run after the nightly price job, after every transaction change, after macro updates, and on demand. | A transaction that breaches a band produces a signal within 1 minute |
| FR-ST-04 | M | Signals carry a dedup key and cooldown; a condition that stays true does not re-fire until the cooldown ends or it worsens by a configured step. | A sleeve sitting outside its band produces one signal per cooldown |
| FR-ST-05 | M | Calculators above, with output as an order list that can be copied into draft transactions. | Allocator output sums exactly to the new cash |
| FR-ST-06 | S | Rule backtest: run any rule over history and list when it would have fired. | Backtest of a drift rule shows dates and drift values |
| FR-ST-07 | M | Principles and theses are passed to the agent verbatim; the agent must flag any advice that departs from them. | Recommendation schema has a `departs_from_principles` field |
| FR-ST-08 | S | Quarterly strategy review prompt with a generated summary: drift history, signals fired, recommendations accepted or rejected and their outcomes. | Review creates an Insights item |

## 11. AI monitoring agent

The agent is a Claude tool-use loop with read-only access to the app's data. It turns signals and news into recommendations that follow a strict JSON schema, and every amount it proposes comes from a deterministic calculator, not from the model. It cannot write to the ledger, and the app holds no broker credentials, so it cannot trade.

&#91;embedded content: agent run · 4 steps, 1 code gate, 2 outcomes\]

The model gathers, investigates and composes; code decides whether the result is shown, and the owner's accept or reject decisions flow back into later runs.

### When it runs

| Run | Trigger | Scope | Default model |
| --- | --- | --- | --- |
| Daily review | Weekdays after the EOD job and rules (about 19:30 CET) | New signals, linked news since last run, portfolio state | `claude-sonnet-5-5` |
| Event run | A high or critical signal, or a news cluster with impact ≥ 70 | Affected positions only | `claude-sonnet-5-5` |
| Weekly deep review | Sunday 18:00 | Whole portfolio, macro indicators, theses, events in the coming week | `claude-opus-5-5` (switchable to Sonnet to save cost) |
| Contribution plan | `contribution_due` signal | Allocator output plus context | `claude-sonnet-5-5` |
| On demand | Owner presses "Analyse" or asks a question | As asked | `claude-sonnet-5-5` |
| News triage | Every news batch (section 12) | Classification and linking only | `claude-haiku-4-5-20251001`, via the Batch API when latency does not matter |

Model IDs live in settings, not code.

### How a run works

1. **Gather.** The worker builds a context pack: strategy version, principles, theses, open signals, linked news clusters, recent recommendations on the same subjects.
2. **Investigate.** Claude runs a tool loop with the read-only tools below plus Anthropic's server-side [web search tool](https://platform.claude.com/docs/en/agents-and-tools/tool-use/web-search-tool), restricted with `allowed_domains` to the owner's trusted source list and capped with `max_uses` (default 5 per run). Output is free-text findings with citations.
3. **Compose.** A second call turns the findings into `Recommendation[]` using [structured outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs) (`output_config.format` with a JSON schema, via the Python SDK's `messages.parse` and a Pydantic model). This is a separate call because structured outputs cannot be combined with citations in one request.
4. **Validate.** The app rejects any recommendation whose amounts differ from the referenced calculator result, that cites no evidence, or that reverses a recent recommendation without new evidence (anti-churn).
5. **Deliver.** Valid items go to the Insights inbox and through notification routing (section 13).

### Agent tools (read-only, `strict: true`)

| Tool | Returns |
| --- | --- |
| `get_portfolio_summary(as_of)` | Value, returns, cash, drift per sleeve |
| `get_positions(filter)` | Positions with weights and P&L |
| `get_position_detail(instrument_id)` | Metrics, lots summary, thesis, recent price action |
| `get_price_history(listing_id, from, to)` | Daily bars |
| `get_allocation(grouping, look_through)` | Allocation tables, including look-through |
| `get_strategy()` | Active version: sleeves, limits, rules, principles, theses |
| `get_signals(state, since)` | Open signals with payloads |
| `get_news(instrument_id, since, min_impact)` | Linked news clusters with assessments |
| `get_macro_series(code, from, to)` | Macro indicator values |
| `run_calculator(kind, params)` | Allocator, trim or rebalance result with a `calculation_id` |
| `simulate(trades)` | What-if allocation, drift and exposure |
| `get_recommendation_history(subject, limit)` | Past recommendations, decisions and outcomes |
| `get_upcoming_events(days)` | Known earnings dates and central bank meetings, when a source provides them |

### Guardrails

- **Advisory only.** No write tools; no broker integration; every recommendation carries an "AI-generated, not financial advice" label.
- **Numbers from code.** Any amount, weight or price in a proposal must reference a `calculation_id` or a tool result; the validator recomputes and rejects mismatches.
- **Principles first.** Advice that departs from the owner's principles or a thesis must say so in `departs_from_principles` with a reason; such items are shown with a distinct badge.
- **Anti-churn.** No recommendation opposite to one made on the same subject within 14 days unless severity is critical and there is new evidence.
- **Untrusted content.** News text, web pages and search results are data. They are passed inside clearly delimited blocks, the system prompt forbids following instructions found in them, and the agent has no tool that could act on such instructions.
- **Privacy mode (default on).** The model sees weights, returns and quantities only as needed; absolute euro amounts stay in the app because calculators run locally.
- **Cost control.** Per-run token cap, per-day run cap, monthly budget (default €15) with a hard stop and an in-app notice. Cost per run is computed from reported usage × a price table in settings, and web searches are counted separately. Prompt caching is used for the system prompt, strategy and tool definitions.
- **Traceability.** Every run stores its context pack, tool calls, outputs, tokens and cost (`agent_run`), viewable on the System page and kept 90 days.

### Recommendation lifecycle

`new → seen → accepted | rejected | snoozed | expired`. Accepting links the recommendation to the transactions the owner records (or creates drafts from its order list). Rejecting asks for an optional one-line reason, which later runs can see. Every recommendation stores the subject's price at creation and the app records it again at +7, +30 and +90 days, so the Insights page can show the agent's track record (followed vs not followed, and what happened next).

### Requirements

| ID | Pri | Requirement | Acceptance |
| --- | --- | --- | --- |
| FR-AG-01 | M | Scheduled daily review and event runs as in the table above, each producing zero or more recommendations plus a short digest. | A run with nothing to report says so in the digest and creates no items |
| FR-AG-02 | M | Two-phase run (investigate with tools and web search; compose with structured outputs). | Composed JSON validates against the appendix schema |
| FR-AG-03 | M | Validator: calculation references, evidence present, anti-churn, schema. Rejected items are logged with the reason and never shown as advice. | A test that alters an amount is rejected |
| FR-AG-04 | M | Budget enforcement and cost tracking per run, per day and per month. | Reaching the cap stops runs and shows a system notice |
| FR-AG-05 | M | Recommendation lifecycle with accept, reject (with reason), snooze and expiry. | Expired items leave the open list automatically |
| FR-AG-06 | S | Outcome tracking at +7/+30/+90 days and a track-record view. | Track record lists hit rate by action type |
| FR-AG-07 | S | Weekly deep review and quarterly strategy review summaries. | Weekly digest arrives Sunday evening |
| FR-AG-08 | S | "Analyse this position" and "Ask the portfolio" on demand. | Answer cites the tool data it used |
| FR-AG-09 | M | Settings: models per run type, schedule, web-search domains and cap, budget, privacy mode, disable switch. | Disabling the agent leaves rules and alerts working |
| FR-AG-10 | S | Prompt files live in `folio/agent/prompts/` as versioned text, and each run records the prompt version used. | Changing a prompt changes the recorded version |

## 12. News intelligence

News is collected from an owner-curated list of feeds and APIs, clustered into stories, linked to holdings directly or through ETF look-through, and scored for impact by a cheap model with escalation to a stronger one. Only headline, feed summary, metadata and link are stored, so paywalled content is never reproduced.

### Source types

| Type | Examples to configure (verify each feed URL at setup) | Notes |
| --- | --- | --- |
| Market-data news API | EODHD news endpoint (ticker-tagged, with sentiment) | Costs provider calls; budgeted with prices |
| Central banks and regulators | ECB press releases, Federal Reserve press releases | Drive rates, USD and gold signals |
| Company and issuer releases | Investor-relations news of directly held companies; ETF issuer fund notices (index changes, closures, distribution changes) | Highest trust for direct holdings |
| Financial media RSS | International and Dutch business news sites; per-ticker feeds where offered | Paywalled sites: headline and link only |
| Sector and theme sources | Defence, semiconductors, commodities trade press | Linked by theme tags |
| On-demand web search | Claude web search during agent runs, restricted to trusted domains | Fills gaps for event runs; not stored as news items |

### Pipeline

1. **Fetch.** RSS every 15 minutes from 07:00 to 23:00 CET and hourly overnight; API sources on their budget. Conditional requests (ETag / If-Modified-Since), per-domain rate limits, robots.txt respected.
2. **Normalise.** Canonical URL with tracking parameters removed, language detection, title, feed summary (max 500 characters), published time in UTC.
3. **Cluster.** Items about the same story across sources within 48 hours are grouped (title similarity plus shared entities), so one event produces one assessment.
4. **Link.** Deterministic matching first: ISINs, tickers, company names and owner-defined aliases for holdings, watchlist items and ETF top constituents. Then a Haiku classification for thematic and macro links (for example, export rules on chip-making equipment link to the semiconductor ETF and to directly held chip-equipment shares). Each link records its type: `direct`, `look_through` (with the weight used), `macro` or `theme`.
5. **Score relevance.** Combines link type, look-through weight × portfolio weight, source trust and recency.
6. **Assess impact.** Haiku produces `impact_score` (0–100), direction (positive, negative, mixed, unclear), horizon (intraday, days, weeks, structural), affected instruments, a two-sentence rationale and confidence. Clusters scoring ≥ 60, or touching a position above 10% weight, are re-assessed by Sonnet.
7. **Route.** Impact ≥ 70 triggers an event run of the agent; everything else above the display threshold goes into the daily digest and the News page.
8. **Learn.** The owner can mark an item "useful" or "not relevant"; this adjusts source trust and alias weights.

### Requirements

| ID | Pri | Requirement | Acceptance |
| --- | --- | --- | --- |
| FR-NW-01 | M | Owner-editable source list: name, type, URL, language, trust weight, poll interval, enabled. | Adding a feed shows its last 10 items as a preview |
| FR-NW-02 | M | Fetching with conditional requests, per-domain rate limits and robots.txt compliance; failures back off and surface on the System page. | A feed returning 304 costs no parsing |
| FR-NW-03 | M | Storage limited to title, summary, metadata and link; no full-text storage. Article text fetched for assessment is held in memory only. | Database contains no article bodies |
| FR-NW-04 | M | Deduplication and clustering across sources. | The same story from 4 sources shows as one cluster with 4 links |
| FR-NW-05 | M | Entity linking (deterministic, then LLM) with link types and look-through weights. | A story about a top ETF constituent links to that ETF with the weight shown |
| FR-NW-06 | M | Impact assessment with escalation thresholds and model choice in settings. | Assessment JSON validates against its schema |
| FR-NW-07 | M | News page: filter by holding, impact, direction, source and date; each cluster shows links, assessment and affected positions. | Filter by one ETF shows direct and look-through stories |
| FR-NW-08 | S | Feedback buttons that tune source trust and aliases. | Marking a source "not relevant" 5 times lowers its trust |
| FR-NW-09 | S | Event calendar: earnings dates for direct equities, central bank meetings and owner-added events; a pre-event brief is generated the evening before. | Brief appears in Insights the day before the event |
| FR-NW-10 | S | Macro context: rate decisions and FX moves are linked to the sleeves whose rules list those indicators (e.g. a gold sleeve watching real yields and the dollar). | A Fed decision links to the gold sleeve |

## 13. Notifications

Everything lands in the in-app Insights inbox; severity decides what also reaches the phone, and quiet hours, a daily push cap and merging keep it from becoming noise. Three phone channels are supported because the homelab already offers two of them: ntfy (self-hosted), the Home Assistant companion app, and browser Web Push from the installed PWA.

### Channels

| Channel | Pri | How it works | Notes |
| --- | --- | --- | --- |
| In-app inbox | M | Bell with unread count, live via Server-Sent Events | Source of truth for every item |
| ntfy | S | POST to a topic on the bundled `ntfy` container (or ntfy.sh) with access token, priority and a click URL | Simplest reliable phone push |
| Home Assistant | S | Call HA's `notify.mobile_app_<device>` service through its REST API with a long-lived token | Reuses the existing HA companion app |
| Web Push | S | VAPID keys; service worker in the PWA | Needs HTTPS (e.g. Tailscale Serve); on iOS only for a PWA added to the home screen |
| Email (SMTP) | C | Digest and critical items |  |
| Telegram bot | C | Same payload as ntfy |  |

### Default routing

| Severity | Examples | Inbox | Phone push | Digest | Quiet hours |
| --- | --- | --- | --- | --- | --- |
| Critical | Agent budget exhausted with an open critical signal; position down ≥ 15% in a day; data pipeline down > 24 h | Yes | All enabled channels, immediately | Yes | Bypassed |
| High | Hard-band breach, trim threshold hit, impact ≥ 80 news on a holding | Yes | Immediately | Yes | Respected |
| Medium | Soft-band drift, drawdown review, contribution plan ready | Yes | Batched hourly | Yes | Respected |
| Low | Thesis review due, macro threshold crossed | Yes | No | Yes | — |
| Info | Daily digest itself, system notices | Yes | Digest push only | — | — |

### Requirements

| ID | Pri | Requirement | Acceptance |
| --- | --- | --- | --- |
| FR-NT-01 | M | In-app inbox with filters (type, severity, status, subject), bulk mark-as-read, deep links. | Unread count updates live |
| FR-NT-02 | M | Channel adapters behind one interface; each channel has a "send test" button. | Test push arrives on the phone |
| FR-NT-03 | M | Routing matrix editable in settings (severity × channel). | Changing a cell changes delivery on the next item |
| FR-NT-04 | M | Quiet hours (default 22:00–07:30) and a daily push cap (default 5, critical excluded); held items are delivered in the next allowed window. | No high-severity push at 23:00 |
| FR-NT-05 | M | Merge: several items on the same subject within an hour become one push ("3 updates on …"). | One push for three linked items |
| FR-NT-06 | S | Daily digest after the daily review and a weekly digest on Sunday: portfolio change, top items, upcoming events. | Digest renders in inbox and as push |
| FR-NT-07 | S | Lock-screen privacy: pushes omit euro amounts by default; optional mode omits instrument names too. | Default push text has no € figures |
| FR-NT-08 | M | Delivery log per notification and channel, with retries and failure status. | Failed push shows the channel error |

## 14. Settings, security, backup and audit

One local account with a strong password and optional TOTP protects the app even inside the tailnet. API keys are encrypted at rest, the database is backed up nightly with tested restores, and every change to money-relevant data is written to an append-only audit log.

| ID | Pri | Requirement | Acceptance |
| --- | --- | --- | --- |
| FR-SY-01 | M | First-run setup wizard: create the owner account, set timezone (default Europe/Amsterdam) and number format, add first account, add provider keys (skippable), choose notification channel (skippable). | Fresh install reaches the empty Home in under 5 minutes |
| FR-SY-02 | M | Authentication: password hashed with Argon2id; session cookie HttpOnly, SameSite=Strict, Secure when served over HTTPS; login rate limiting (5 attempts per 15 minutes); "remember this device" for 30 days. | Brute-force test is throttled |
| FR-SY-03 | S | Optional TOTP second factor with recovery codes. | Login requires the code once enabled |
| FR-SY-04 | C | Optional trust of Tailscale Serve identity headers as login, restricted to a configured tailnet user. | Disabled by default |
| FR-SY-05 | M | Secrets (provider keys, Anthropic key, notification tokens) encrypted at rest with a key from `FOLIO_SECRET_KEY`; masked in the UI after save; never logged or sent to the LLM. | Grep of logs and DB finds no plaintext key |
| FR-SY-06 | M | Nightly online backup of SQLite (`VACUUM INTO`) to `/data/backups`, keeping 14 daily and 8 weekly copies; optional copy to a mounted NAS path. | Backup files open and pass `PRAGMA integrity_check` |
| FR-SY-07 | M | Restore from a backup through a CLI command and through the UI (upload, confirm, restart). Secrets are excluded from exports unless explicitly included. | Restore test in CI recreates identical positions |
| FR-SY-08 | M | Append-only audit log for transactions, instruments, prices overridden, strategies, settings and recommendation decisions, with a filterable viewer. | Every edit shows old and new values |
| FR-SY-09 | M | Settings pages for providers (keys, priorities, budgets), schedules (cron overrides per job), agent, notifications, appearance, language and data retention (quotes 7 days, agent runs 90 days, news 365 days by default). | Retention job prunes on schedule |
| FR-SY-10 | S | System page: job runs with duration and status, provider call usage, agent runs and cost this month, disk usage, app version. | A failing job is visible within one run |

## 15. Non-functional requirements

The app must be correct to the cent, light enough to share a homelab host, and keep working when a data provider or the LLM is down.

| ID | Area | Requirement |
| --- | --- | --- |
| NFR-01 | Correctness | Money and quantities use `Decimal` end to end; rounding (half-even) happens only for display. Ledger maths is covered by property tests (hypothesis) and golden fixtures. |
| NFR-02 | Time | Timestamps stored in UTC; UI shows Europe/Amsterdam; trading dates are exchange-local dates. |
| NFR-03 | Performance | Dashboard data endpoints answer in under 300 ms (p95) for 10 years × 50 instruments; first page load under 1.5 s on the LAN; nightly jobs finish in under 10 minutes. |
| NFR-04 | Footprint | Idle under 512 MB RAM and 2% CPU for `web` + `worker`; image under 400 MB; images for amd64 and arm64. |
| NFR-05 | Reliability | Jobs are idempotent and resumable; missed runs catch up once after a restart (coalesced); each external dependency has a timeout, retry with backoff and a circuit breaker. |
| NFR-06 | Degradation | With prices unavailable the app shows last values marked stale; with the LLM unavailable rules, alerts and notifications keep working. |
| NFR-07 | Security | Containers run as non-root with a read-only root filesystem and `no-new-privileges`; CSRF protection on cookie-authenticated writes; strict Content-Security-Policy; `pip-audit` and `npm audit` in CI. |
| NFR-08 | Privacy | All data stays local. Outbound traffic goes only to configured data providers, the Anthropic API and notification channels; the README lists these destinations. |
| NFR-09 | Observability | Structured JSON logs with request and job IDs; `/healthz` and `/readyz`; optional Prometheus `/metrics`. |
| NFR-10 | Maintainability | Typed Python (mypy strict on `domain/` and `analytics/`), ruff clean, ESLint clean; ≥ 85% line coverage on `domain/` and `analytics/`; frontend API client generated from the OpenAPI spec; architecture decisions recorded in `docs/adr/`. |
| NFR-11 | Accessibility | WCAG 2.2 AA contrast and full keyboard navigation; every chart offers a data-table view. |
| NFR-12 | Testing | Unit and property tests for domain; API integration tests on a temporary database; provider adapters tested against recorded fixtures (no live calls in CI); Playwright end-to-end tests for import, add transaction, sell preview, dashboard build, recommendation accept; agent evaluation set of fixed scenarios replayed with recorded model responses. |

## 16. API outline

All endpoints live under `/api/v1`, exchange JSON, and are described by the generated OpenAPI spec at `/api/docs`. Decimals travel as strings, dates as ISO 8601, lists use cursor pagination, and errors follow RFC 9457 (`application/problem+json`).

| Area | Endpoints |
| --- | --- |
| Auth | `POST /auth/login`, `POST /auth/logout`, `GET /auth/me`, `POST /auth/totp/setup` |
| Accounts | `GET` / `POST /accounts`, `PATCH` / `DELETE /accounts/{id}` |
| Instruments | `GET /instruments`, `GET /instruments/resolve?isin=`, `POST /instruments`, `GET` / `PATCH` / `DELETE /instruments/{id}`, `GET /instruments/{id}/prices?from=&to=`, `POST /instruments/{id}/prices` (manual price) |
| Transactions | `GET /transactions?account=&instrument=&type=&from=&to=`, `POST /transactions`, `PATCH` / `DELETE /transactions/{id}`, `POST /transactions/preview-sell` |
| Imports | `POST /imports` (upload, returns preview), `PUT /imports/{id}/mapping`, `POST /imports/{id}/commit`, `DELETE /imports/{id}` (undo batch), `GET` / `POST /import-presets` |
| Positions | `GET /positions?account=&as_of=`, `GET /positions/{instrument_id}` |
| Portfolio | `GET /portfolio/summary?period=`, `GET /portfolio/history?from=&to=`, `GET /portfolio/returns?period=&scope=`, `GET /portfolio/allocation?group_by=&look_through=`, `GET /portfolio/risk`, `POST /portfolio/simulate`, `GET /reports/annual/{year}` |
| Strategies | `GET` / `POST /strategies`, `GET` / `POST /strategies/{id}/versions`, `POST /strategies/{id}/activate`, `POST /strategies/{id}/rules/{rule_id}/backtest`, `POST /calculators/{kind}` |
| Signals and recommendations | `GET /signals`, `GET /recommendations`, `PATCH /recommendations/{id}` (status, note), `GET /recommendations/track-record` |
| News | `GET /news?instrument=&min_impact=&from=`, `GET /news/clusters/{id}`, `POST /news/clusters/{id}/feedback`, CRUD `/news/sources` |
| Dashboards | CRUD `/dashboards`, `PUT /dashboards/{id}/layout`, CRUD `/dashboards/{id}/widgets`, `POST /widgets/data` (batched widget queries) |
| Notifications | `GET /notifications`, `POST /notifications/read`, `POST /notifications/test/{channel}`, `GET` / `PUT /notification-routing` |
| Agent | `POST /agent/runs` (on demand), `GET /agent/runs`, `GET /agent/runs/{id}`, `POST /agent/ask` |
| System | `GET /system/jobs`, `POST /system/jobs/{job}/run`, `GET /system/usage`, `GET /audit`, `GET` / `POST /backups`, `POST /backups/{id}/restore`, `GET /export?format=` |
| Settings | `GET` / `PUT /settings/{section}` |
| Live updates | `GET /events` (Server-Sent Events: `price_update`, `notification`, `job_status`, `recommendation`) |

## 17. Deployment and operations

The app ships as one multi-stage image (Node builds the UI, a slim Python image runs it) and a `docker-compose.yml` that Portainer deploys as a stack on the Docker LXC. It is reached over the LAN or through the existing Tailscale subnet router, and must not be added to any publicly exposed reverse proxy.

### Compose file (target shape)

```yaml
services:
  web:
    image: folio:latest
    command: ["web"]
    env_file: .env
    volumes: ["folio-data:/data"]
    ports: ["${FOLIO_LAN_IP}:8080:8080"]   # LAN interface only
    read_only: true
    tmpfs: ["/tmp"]
    security_opt: ["no-new-privileges:true"]
    user: "10001:10001"
    healthcheck:
      test: ["CMD", "python", "-m", "folio.healthcheck", "http://localhost:8080/healthz"]
      interval: 30s
    restart: unless-stopped
  worker:
    image: folio:latest
    command: ["worker"]
    env_file: .env
    volumes: ["folio-data:/data"]
    read_only: true
    tmpfs: ["/tmp"]
    security_opt: ["no-new-privileges:true"]
    user: "10001:10001"
    depends_on:
      web: { condition: service_healthy }   # web runs migrations on start
    restart: unless-stopped
  ntfy:
    image: binwiederhier/ntfy
    command: ["serve"]
    profiles: ["ntfy"]
    volumes: ["ntfy-data:/var/lib/ntfy"]
    ports: ["${FOLIO_LAN_IP}:8081:80"]
    restart: unless-stopped
volumes:
  folio-data: {}
  ntfy-data: {}
```

### Environment variables

| Variable | Required | Default | Purpose |
| --- | --- | --- | --- |
| `FOLIO_SECRET_KEY` | Yes | — | Encrypts stored secrets and signs sessions; generated by `folio init` |
| `FOLIO_LAN_IP` | Yes (compose) | — | Host interface the ports bind to |
| `FOLIO_DB_URL` | No | `sqlite:////data/folio.db` | Database; a PostgreSQL URL also works |
| `FOLIO_BASE_URL` | No | — | Absolute URL used in notification deep links |
| `FOLIO_TZ` | No | `Europe/Amsterdam` | Display and schedule timezone |
| `FOLIO_LOG_LEVEL` | No | `INFO` | Log level |
| `FOLIO_BACKUP_DIR` | No | `/data/backups` | Local backup target |
| `FOLIO_EXTRA_BACKUP_DIR` | No | — | Second backup copy, e.g. a NAS mount |
| `ANTHROPIC_API_KEY`, `EODHD_API_KEY`, `TWELVEDATA_API_KEY`, `OPENFIGI_API_KEY`, `FRED_API_KEY` | No | — | Optional env overrides; normally entered in Settings and stored encrypted |

### Operations

- **Start-up.** `web` runs Alembic migrations, then serves; `worker` starts once `web` is healthy.
- **Upgrades.** Pull a new image and redeploy the stack; migrations are forward-only and a backup is taken automatically before they run.
- **HTTPS.** Not terminated in the app. When Web Push is wanted, put HTTPS in front from a tailnet node (for example Tailscale Serve proxying to the app's LAN address); everything else works over plain HTTP on the LAN and tailnet.
- **CLI.** `folio init`, `folio migrate`, `folio backup`, `folio restore <file>`, `folio run-job <name>`, `folio create-user`, `folio reset-password`.
- **Local development.** `uv run folio web --reload` and `uv run folio worker` against a local SQLite file, with `npm run dev` for the UI proxying `/api` to port 8080. Containerisation is the last step of each phase, after tests pass natively.

## 18. Delivery phases

Build in six phases, each ending with a working, containerised, deployed app and a gate the owner checks before the next phase starts. The ledger comes first because every later feature trusts its numbers; the AI agent comes last because it depends on everything else.

&#91;embedded content: delivery roadmap · 6 phases, each closed by a gate\]

Phases are sequential and not to scale; the P1 gate matters most, because every later number depends on the ledger being right.

### Requirements per phase

| Phase | Requirement IDs |
| --- | --- |
| P0 Foundations | FR-SY-01, FR-SY-02, FR-SY-05, FR-SY-09 (shell), NFR-07, NFR-09, NFR-10 |
| P1 Ledger and prices | FR-INS-01–03, FR-MD-01–04, FR-MD-06, FR-MD-07, FR-MD-10, FR-MD-11, FR-TX-01–07, FR-PF-01, FR-PF-10, FR-SY-06, FR-SY-07 (CLI restore), FR-SY-08, NFR-01, NFR-02 |
| P2 Analytics and dashboards | FR-INS-04, FR-INS-05, FR-MD-05, FR-MD-12, FR-TX-08–12, FR-PF-02–04, FR-PF-06–09, FR-DB-01–08 |
| P3 Strategies and alerts | FR-ST-01–05, FR-ST-07, FR-MD-08, FR-NT-01–08, FR-SY-10 |
| P4 News and AI agent | FR-MD-09, FR-PF-05, FR-NW-01–08, FR-NW-10, FR-AG-01–05, FR-AG-09, FR-AG-10 |
| P5 Hardening and extras | FR-SY-03, FR-SY-04, FR-SY-07 (UI restore), FR-PF-11, FR-PF-12, FR-ST-06, FR-ST-08, FR-AG-06–08, FR-NW-09, FR-TX-13, FR-DB-09 |

Every phase also meets the NFRs that apply to the code it adds, and ends with: tests green in CI, image built, stack redeployed through Portainer, phase branch pushed and merged into main through a pull request, README and `docs/` updated.

## 19. Working instructions for Claude Code

Work one phase at a time, trace every requirement ID to code and a test, and stop to ask only when a decision is truly the owner's; otherwise take the defaults in section 20 and record the choice.

### Process

1. Save this document in the repo as `docs/requirements.md` and write a short `CLAUDE.md` with the conventions below.
2. Start each phase in plan mode: list the requirement IDs in scope, the files to create or change, and the tests that will prove each acceptance criterion. Wait for the owner's go-ahead on the plan.
3. Build domain logic and its property tests before endpoints, and endpoints before UI.
4. Keep `docs/traceability.md` current: requirement ID → module → test name → status (`todo`, `in progress`, `done`).
5. A requirement is done only when its acceptance criterion is covered by a passing automated test (or, for purely visual items, a Playwright screenshot test).
6. Record every non-obvious decision (library choice, schema change, deviation from this spec) as a short ADR in `docs/adr/`.
7. End each phase by building the image, running the stack locally with compose, and writing release notes in `docs/changelog.md`.

### Rules

- Never commit secrets, real transactions or amounts; ship `.env.example` and a `folio seed --demo` command that creates a fictional portfolio for UI work.
- No live external calls in tests. Provider and LLM adapters are tested against recorded fixtures; if a provider's response format is unclear, build against a recorded real response and flag it, rather than guessing.
- Never use floats for money or quantities.
- Do not build anything listed under non-goals (section 1), in particular order execution or broker log-in.
- Prefer few, well-maintained dependencies; pin versions; justify heavy additions in an ADR.
- Commit messages follow Conventional Commits and cite requirement IDs, e.g. `feat(ledger): FIFO lot matching [FR-TX-03]`.
- Agent prompts live in `folio/agent/prompts/` as versioned files; write the agent evaluation scenarios (section 15, NFR-12) before tuning prompts.

### Standing order: commit and push to GitHub

This order applies in every session for the life of the project: whenever a significant feature is finished or a bug is fixed, Claude Code commits the relevant source files and pushes them to [github.com/Freakadude/Portfolio-Tracker](https://github.com/Freakadude/Portfolio-Tracker). It does this on the owner's behalf with the owner's own Git login on their computer, without being asked each time. In Phase 0, Claude Code copies this order word for word into `CLAUDE.md` so every new session follows it.

1. **When.** After each finished feature (one or more requirement IDs meeting their acceptance tests) and after each bug fix (with a regression test that failed before the fix and passes after it). Work in progress is not committed to the shared branch.
2. **Check first.** At the start of each session, confirm `git remote -v` points to the repository and `git status` is clean. Before each commit, run the full test suite and linters; the pre-commit hooks (ruff, ESLint/Prettier, and a gitleaks secret scan) must pass. If anything fails, fix it first or ask the owner; never commit with `--no-verify`.
3. **Stage deliberately.** Review `git status` and `git diff`, then stage the relevant files by path. Never stage `.env`, API keys, database files, anything under `/data`, backups, imported broker exports, `node_modules`, build output or `.claude/settings.local.json`. The `.gitignore` created in Phase 0 excludes all of these.
4. **Commit.** One logical change per commit, Conventional Commits format with requirement IDs, e.g. `feat(ledger): FIFO lot matching [FR-TX-03]` or `fix(import): parse comma decimals [FR-TX-07]`. Update `docs/traceability.md` and `docs/changelog.md` in the same commit.
5. **Push.** Default branching (see Q13): one branch per phase, e.g. `phase/p1-ledger-and-prices`, pushed after every commit with `git push -u origin <branch>`. At the phase gate, Claude Code opens a pull request into `main` with `gh pr create`, listing the requirement IDs completed and the test evidence; the owner reviews and merges.
6. **Report.** After each push, tell the owner in one line: branch, short commit hash, and what changed.
7. **Never.** Force-push, rewrite pushed history, push straight to `main` (unless the owner chooses that under Q13), put a token in a remote URL or a file, or ask the owner to paste a password or token into the chat.
8. **If a push fails.** Stop, show the exact error, and point the owner to the setup step below that fixes it. Do not try workarounds.

### One-time GitHub setup (owner)

Claude Code in VS Code uses the Git login already on your computer, so you never give Claude a password or token. You set Git up once; after that Claude Code can commit and push by itself. The repository returned "not found" to an anonymous check on 4 October 2026, which is expected for a private repository; if you have not created it yet, step 1 covers that.

1. **Create or confirm the repository.** On github.com: New repository → owner `Freakadude`, name `Portfolio-Tracker`, visibility Private, default branch `main`. If it already exists, just check you can open it while logged in.
2. **Install the tools** on the computer that runs VS Code: Git (git-scm.com) and the GitHub CLI `gh` (cli.github.com).
3. **Tell Git who you are and log in to GitHub** (commands below). To keep your e-mail address private, use the `…@users.noreply.github.com` address shown under GitHub → Settings → Emails.
4. **Clone and open the project** in VS Code, start Claude Code in that folder, and trust the folder when asked.
5. **Let Claude Code run Git without a prompt each time.** In Phase 0 Claude Code creates `.claude/settings.json` with the rules below and commits it; approve it once. Until then, answer "Yes, and don't ask again" on the first Git prompts.
6. **Protect `main` (recommended).** In the repository's Settings → Branches (or Rules): require a pull request before merging and block force pushes.
7. **Tell Claude Code** only two things: that setup is done, and your answer to Q13. Claude Code then runs `gh auth status` and `git ls-remote origin` to confirm access.

```bash
git config --global user.name "Your Name"
git config --global user.email "you@users.noreply.github.com"
gh auth login        # GitHub.com → HTTPS → Login with a web browser
gh auth setup-git    # lets git use the gh login when pushing
gh auth status       # should report: Logged in to github.com
git clone https://github.com/Freakadude/Portfolio-Tracker.git
cd Portfolio-Tracker
```

If a browser login is not possible, use either an SSH key added to your GitHub account (remote `git@github.com:Freakadude/Portfolio-Tracker.git`) or a fine-grained personal access token limited to this one repository with Contents and Pull requests set to read and write. Enter it only in the Git or `gh` login prompt, never in a file or the chat.

**`.claude/settings.json` (committed in Phase 0):**

```json
{
  "$schema": "https://json.schemastore.org/claude-code-settings.json",
  "permissions": {
    "allow": [
      "Bash(git status)",
      "Bash(git remote -v)",
      "Bash(git diff *)",
      "Bash(git log *)",
      "Bash(git branch *)",
      "Bash(git switch *)",
      "Bash(git fetch *)",
      "Bash(git pull --ff-only *)",
      "Bash(git add *)",
      "Bash(git commit *)",
      "Bash(git push origin *)",
      "Bash(git push -u origin *)",
      "Bash(git ls-remote *)",
      "Bash(gh auth status)",
      "Bash(gh pr create *)",
      "Bash(gh pr view *)"
    ],
    "deny": [
      "Bash(git push --force *)",
      "Bash(git push -f *)",
      "Bash(git reset --hard *)",
      "Read(./.env)",
      "Read(./.env.local)"
    ]
  }
}
```

The rule syntax follows [Claude Code's settings documentation](https://code.claude.com/docs/en/settings); allow rules in this shared file take effect once the folder is trusted, and personal approvals land in `.claude/settings.local.json`, which stays out of Git.

### Repository layout

```text
Portfolio-Tracker/          # github.com/Freakadude/Portfolio-Tracker
├── pyproject.toml            # uv-managed
├── folio/
│   ├── domain/               # ledger, lots, P&L, corporate actions (pure)
│   ├── marketdata/           # provider adapters, symbol resolution, FX, macro, ETF holdings
│   ├── analytics/            # returns, risk, allocation, look-through
│   ├── strategies/           # schema, rules, calculators
│   ├── news/                 # sources, pipeline, linking, assessment
│   ├── agent/                # loop, tools, validator, budget, prompts/
│   ├── notify/               # channels, routing, digests
│   ├── dashboards/           # persistence, widget data
│   ├── api/                  # FastAPI routers, auth, SSE
│   ├── jobs/                 # scheduler, job definitions
│   └── cli.py
├── migrations/               # Alembic
├── tests/                    # unit, property, integration, fixtures/, agent_evals/
├── web/                      # React app (src/components, pages, widgets, api, i18n)
├── docker/Dockerfile
├── docker-compose.yml
├── .env.example
├── .gitignore                # secrets, data, backups, exports, build output
├── .pre-commit-config.yaml   # ruff, ESLint/Prettier, gitleaks
├── .claude/settings.json     # shared Git permission rules (section 19)
├── docs/                     # requirements.md, traceability.md, adr/, changelog.md
├── CLAUDE.md                 # conventions + the commit-and-push standing order
└── README.md
```

## 20. Open questions and defaults

Thirteen owner decisions are still open; none blocks Phase 0, and each has a default Claude Code applies until the owner answers.

| # | Question | Default until answered | Affects |
| --- | --- | --- | --- |
| Q1 | Which broker(s), and can you supply a sample transaction export? | Generic CSV import with manual mapping | FR-TX-07, FR-TX-08 |
| Q2 | Take the paid EODHD EOD plan, or stay on free tiers? | Free tiers; `yfinance` fallback available but off; look-through via manual CSV | FR-MD-\*, FR-PF-05 |
| Q3 | Target weight, soft band, hard band and trim threshold per sleeve? | Strategy starts without targets; drift and trim rules stay inactive until targets are set | FR-ST-\*, agent |
| Q4 | Regular contribution amount and cadence? | None; `contribution_due` rule off | FR-ST-05 |
| Q5 | Preferred phone channel: Home Assistant companion app, ntfy, or Web Push? | Home Assistant companion app, ntfy as second option | FR-NT-02 |
| Q6 | Monthly LLM budget? | €15, hard stop | FR-AG-04 |
| Q7 | Track cash balances per account? | Off | FR-TX-09 |
| Q8 | Does the broker allow fractional ETF units? | Whole units only | Calculators |
| Q9 | Benchmark(s) for comparison charts? | None until chosen; the UI suggests adding a broad global equity ETF | FR-PF-08 |
| Q10 | Dutch UI as well as English? | English only, i18n-ready | Section 9 |
| Q11 | Keep React for the UI, or match an htmx stack used in other homelab apps? | React (needed for the dashboard builder) | Section 4 |
| Q12 | Initial trusted news sources beyond central banks, issuers and EODHD news? | Those three only; owner adds media feeds in Settings | FR-NW-01 |
| Q13 | Push to a branch per phase with a pull request into `main` at each gate, or commit straight to `main`? | Branch per phase, pull request at the gate | Section 19 standing order |

## 21. Appendix

The example strategy below uses the instruments currently held, with every target and threshold left empty for the owner to set (Q3). Rule parameters shown are illustrative starting values, not recommendations.

### A. Seed instruments (no amounts)

| Instrument | ISIN | Asset class | Sleeve |
| --- | --- | --- | --- |
| iShares Core S&P 500 | IE00B5BMR087 | ETF | `us_equity` |
| iShares Core MSCI Europe | IE00B4K48X80 | ETF | `europe_equity` |
| HSBC MSCI Emerging Markets | IE000KCS7J59 | ETF | `emerging_markets` |
| HANetf Future of Defence | IE000OJ5TQP4 | ETF | `thematic_defence` |
| VanEck Semiconductor | IE00BMC38736 | ETF | `thematic_semis` |
| SPDR Global Convertible Bond | IE00BDT6FP91 | ETF | `convertibles` |
| iShares Physical Gold | IE00B4ND3602 | ETC | `gold_hedge` |
| ASML Holding | NL0010273215 | Equity | `single_stock` |

### B. Example strategy (`strategy.yaml`)

```yaml
strategy:
  name: Core long-term
  base_currency: EUR
  principles:
    - Rebalance by directing new contributions to underweight sleeves before considering any sale.
    - No emotionally driven profit-taking; trims happen only at pre-committed thresholds.
    - Thematic positions and the single-stock position have pre-committed trim thresholds.
    - Gold is held as a non-correlated hedge; a short-term drawdown alone is not a reason to sell.
  macro_series:
    US_REAL_YIELD_10Y: { source: fred, code: DFII10 }      # 10-year TIPS real yield
    USD_TRADE_WEIGHTED: { source: fred, code: DTWEXBGS }   # broad trade-weighted dollar
    FED_FUNDS: { source: fred, code: DFF }
  sleeves:
    - { id: us_equity,        members: [IE00B5BMR087], target_pct: null, soft_band_pp: null, hard_band_pp: null }
    - { id: europe_equity,    members: [IE00B4K48X80], target_pct: null, soft_band_pp: null, hard_band_pp: null }
    - { id: emerging_markets, members: [IE000KCS7J59], target_pct: null, soft_band_pp: null, hard_band_pp: null }
    - { id: thematic_defence, members: [IE000OJ5TQP4], target_pct: null, trim_threshold_pct: null, tags: [thematic] }
    - { id: thematic_semis,   members: [IE00BMC38736], target_pct: null, trim_threshold_pct: null, tags: [thematic] }
    - { id: single_stock,     members: [NL0010273215], target_pct: null, trim_threshold_pct: null }
    - { id: convertibles,     members: [IE00BDT6FP91], target_pct: null, soft_band_pp: null, hard_band_pp: null }
    - { id: gold_hedge,       members: [IE00B4ND3602], target_pct: null, soft_band_pp: null, hard_band_pp: null,
        watch: [US_REAL_YIELD_10Y, USD_TRADE_WEIGHTED, FED_FUNDS] }
  risk_limits:
    max_single_company_lookthrough_pct: null   # e.g. direct shares plus the same company inside ETFs
    max_thematic_total_pct: null
  rules:
    - { id: drift,        type: drift_band,          applies_to: all,  severity: medium, cooldown_days: 7 }
    - { id: trims,        type: trim_threshold,      applies_to: [thematic_defence, thematic_semis, single_stock], severity: high, cooldown_days: 14 }
    - { id: concentrate,  type: concentration_limit, dimension: company, severity: high, cooldown_days: 30 }
    - { id: real_yield,   type: macro_threshold,     series: US_REAL_YIELD_10Y, change_bp: 50, window_days: 30, applies_to: [gold_hedge], severity: low }
    - { id: dollar,       type: macro_threshold,     series: USD_TRADE_WEIGHTED, change_pct: 3, window_days: 30, applies_to: [gold_hedge], severity: low }
    - { id: hedge_corr,   type: correlation_shift,   hedge: gold_hedge, against: [us_equity, europe_equity], window_days: 90, above: 0.5, severity: low }
    - { id: drawdown,     type: drawdown,            scope: position, threshold_pct: 20, severity: medium, cooldown_days: 14 }
  theses:
    - { sleeve: gold_hedge, why: "Non-correlated hedge", invalidated_if: null, review_every_days: 90 }
```

### C. Recommendation output schema (structured outputs)

The schema avoids numeric bounds and string lengths, which structured outputs do not support, and sets `additionalProperties: false` everywhere. Enum values are compared case-insensitively because capitalisation is not guaranteed.

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": ["digest", "recommendations"],
  "properties": {
    "digest": { "type": "string" },
    "recommendations": { "type": "array", "items": { "$ref": "#/$defs/rec" } }
  },
  "$defs": {
    "rec": {
      "type": "object",
      "additionalProperties": false,
      "required": ["action_type", "severity", "subjects", "title", "summary", "rationale",
                   "calculation_id", "evidence", "sources", "confidence",
                   "departs_from_principles", "what_would_change_this", "expires_in_days"],
      "properties": {
        "action_type": { "type": "string", "enum": ["direct_contribution", "trim", "rebalance", "hold",
                                                    "review_thesis", "watch", "hedge_check", "info"] },
        "severity": { "type": "string", "enum": ["info", "low", "medium", "high", "critical"] },
        "subjects": { "type": "array", "items": { "type": "string" } },
        "title": { "type": "string" },
        "summary": { "type": "string" },
        "rationale": { "type": "string" },
        "calculation_id": { "type": ["string", "null"] },
        "evidence": {
          "type": "array",
          "items": {
            "type": "object",
            "additionalProperties": false,
            "required": ["kind", "ref", "note"],
            "properties": {
              "kind": { "type": "string", "enum": ["signal", "news_cluster", "metric", "macro_series", "web_source"] },
              "ref": { "type": "string" },
              "note": { "type": "string" }
            }
          }
        },
        "sources": { "type": "array", "items": { "type": "string", "format": "uri" } },
        "confidence": { "type": "string", "enum": ["low", "medium", "high"] },
        "departs_from_principles": { "type": ["string", "null"] },
        "what_would_change_this": { "type": "string" },
        "expires_in_days": { "type": "integer" }
      }
    }
  }
}
```

## Sources

- [EODHD pricing](https://eodhd.com/pricing)
- [Twelve Data individual pricing](https://twelvedata.com/pricing)
- [OpenFIGI API documentation](https://www.openfigi.com/api/documentation)
- [Claude API: web search tool](https://platform.claude.com/docs/en/agents-and-tools/tool-use/web-search-tool)
- [Claude API: structured outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs)
- [Claude Code: settings files and permission rules](https://code.claude.com/docs/en/settings)
- [Rijksoverheid: plannen werkelijk rendement box 3](https://www.rijksoverheid.nl/themas/werk/inkomstenbelasting/plannen-werkelijk-rendement-box-3)
- [Nextens: box 3 naar vermogenswinstbelasting (30 Sep 2026)](https://www.nextens.nl/fiscaal-nieuws/box-3-naar-vermogenswinstbelasting-voor-beleggers-spaarders-en-ondernemers/)
