# Folio

Self-hosted, single-user portfolio manager: ledger, EUR valuation, dashboards, strategy rules, news and an advisory AI agent. It advises; it never places trades.

The build brief is [docs/requirements.md](docs/requirements.md). Progress per requirement is in [docs/traceability.md](docs/traceability.md), and what changed in each phase is in [docs/changelog.md](docs/changelog.md).

## Status

Phases 0 to 4 are code complete: foundations, ledger and prices, dashboards and tools, strategies and alerts, and news with the AI agent. Phase 5 (track record, weekly deep review, "Ask the portfolio", event calendar) is next. The owner gate checks for Phases 1 to 4 are still open; the list for each phase is in the changelog.

## Outbound network destinations (NFR-08)

All data stays local. The app only contacts what you configure, and only these:

- Market data: EODHD, Twelve Data, OpenFIGI, FRED (macro series), the ECB (reference rates), and optionally Yahoo Finance through `yfinance` (off by default)
- News feeds from your source list: ready-made are the ECB's and the Federal Reserve's press releases and EODHD's news for your tickers; you add issuer feeds. Folio reads each site's robots.txt, fetches headlines and summaries only, never article pages
- ETF holdings: the download address you give an ETF, and EODHD fundamentals when switched on
- The Anthropic API (news triage and the agent, including web search limited to the sites you list); news text only ever leaves as a short title and summary inside a block marked untrusted, and in privacy mode (default) no euro amounts are sent
- Notification channels: Home Assistant, ntfy

## Local development

```bash
uv run folio init            # generates FOLIO_SECRET_KEY into .env
uv run folio web --reload    # API on :8080
uv run folio worker          # scheduled jobs: prices, rules, news, the agent
cd web && npm run dev        # UI, proxies /api to :8080
```

Web checks (in `web/`): `npm run lint`, `npm run typecheck`, `npm test`, `npm run e2e` (Playwright, needs `npx playwright install chromium` once; the e2e run starts its own server and a local server for recorded news feeds). After changing the API, run `npm run gen:api` and commit `openapi.json` and `src/api/schema.d.ts`.

Operations (the same commands work in the container with `docker compose run --rm web <command>`):

```bash
uv run folio backup [--no-secrets]    # verified backup now (a nightly one also runs at 03:00)
uv run folio restore <file>           # stop web and worker first; the current database is kept
uv run folio run-job fx               # eod, fx, gaps, snapshots, actions, backfill, backup, macro, rules, news, lookthrough, agent_run
uv run folio seed --demo              # fictional data for working on the UI, never real holdings
```

The tests never call a real service: providers, news sites and the Anthropic API are replayed from fixtures in `tests/fixtures/` (several of them were written from the services' documentation and still need a check against a real response; the owner gate lists them).

## Deployment

Deploy as a Portainer stack on the Docker LXC from [docker-compose.yml](docker-compose.yml): a `web` container (it runs the database migrations on start) and a `worker` container, one volume for `/data`, and `.env` for the secret key and `FOLIO_LAN_IP`. CI builds the image; the first real run is the owner's deployment ([ADR 0003](docs/adr/0003-image-built-in-ci.md)). After an update, redeploy both containers: the worker carries the news, look-through and agent jobs.

Not exposed to the public internet: LAN or Tailscale only.
