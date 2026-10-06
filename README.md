# Folio

Self-hosted, single-user portfolio manager: ledger, EUR valuation, dashboards, strategy rules, news and an advisory AI agent. It advises; it never places trades.

The build brief is [docs/requirements.md](docs/requirements.md). Progress per requirement is in [docs/traceability.md](docs/traceability.md), and what changed in each phase is in [docs/changelog.md](docs/changelog.md).

## Status

All six phases are code complete: foundations, ledger and prices, dashboards and tools, strategies and alerts, news with the AI agent, and the extras of Phase 5 (track record, weekly and quarterly reviews, event calendar, "Ask the portfolio", tax-support report and export, rule backtest, projection, two-factor sign-in, optional Tailscale sign-in, restore from the app). The owner gate checks for every phase are still open; the short list for the whole project is in [docs/owner-gate.md](docs/owner-gate.md), and each phase's own list is in the changelog.

## Outbound network destinations (NFR-08)

All data stays local. The app only contacts what you configure, and only these:

- Market data: EODHD, Twelve Data, OpenFIGI, FRED (macro series), the ECB (reference rates), and optionally Yahoo Finance through `yfinance` (off by default)
- News feeds from your source list: ready-made are the ECB's and the Federal Reserve's press releases and EODHD's news for your tickers; you add issuer feeds. Folio reads each site's robots.txt, fetches headlines and summaries only, never article pages
- ETF holdings: the download address you give an ETF, and EODHD fundamentals when switched on
- Earnings dates: EODHD's earnings calendar, only when you switch it on (the ECB and Fed decision days ship with Folio and need no call)
- The Anthropic API (news triage, the agent's reviews, event briefs and your questions, including web search limited to the sites you list); news text only ever leaves as a short title and summary inside a block marked untrusted, and in privacy mode (default) no euro amounts are sent
- Notification channels: Home Assistant, ntfy

Links on a fund's page (justETF, the issuer's site, a web search) open in your browser when you click them; Folio itself makes no call there.

Nothing is sent anywhere by the backups, the exports, the reports or the sign-in; they stay on the server and in your browser.

## Local development

```bash
uv run folio init            # generates FOLIO_SECRET_KEY into .env
uv run folio web --reload    # API on :8080
uv run folio worker          # scheduled jobs: prices, rules, news, the agent, the calendar
cd web && npm run dev        # UI, proxies /api to :8080
```

Web checks (in `web/`): `npm run lint`, `npm run typecheck`, `npm test`, `npm run e2e` (Playwright, needs `npx playwright install chromium` once; the e2e run starts its own server and a local server for recorded news feeds). After changing the API, run `npm run gen:api` and commit `openapi.json` and `src/api/schema.d.ts`.

Operations (the same commands work in the container with `docker compose run --rm web <command>`):

```bash
uv run folio backup [--no-secrets]    # verified backup now (a nightly one also runs at 03:00)
uv run folio restore <file>           # stop web and worker first; the current database is kept
uv run folio run-job fx               # eod, fx, gaps, backup, macro, rules, news, lookthrough, outcomes, calendar, agent_run, ...
uv run folio seed --demo              # fictional data for working on the UI, never real holdings
```

A backup can also be made, downloaded, uploaded and restored from the System page (a restore restarts the containers and keeps what was there as a "before a restore" backup).

The tests never call a real service: providers, news sites and the Anthropic API are replayed from fixtures in `tests/fixtures/` (several of them were written from the services' documentation and still need a check against a real response; the owner gate lists them).

## Deployment

CI builds the image on every green push to `main` and publishes it to `ghcr.io/freakadude/portfolio-tracker` ([ADR 0033](docs/adr/0033-publish-image-to-ghcr.md)); the package is public. Deploy [docker-compose.yml](docker-compose.yml) as a Portainer stack on the Docker LXC (a `web` container that runs the database migrations on start, and a `worker`; one volume for `/data`), with `FOLIO_SECRET_KEY` and `FOLIO_LAN_IP` set as stack environment variables; Folio is then at `http://<FOLIO_LAN_IP>:8555`. To update, press "Update the stack" with "Re-pull image" in Portainer; both containers restart, and the worker carries the news, look-through, calendar, outcome and agent jobs. The one-time setup, the optional Tailscale sign-in settings and rollback are in [docs/deployment.md](docs/deployment.md).

Not exposed to the public internet: LAN or Tailscale only.
