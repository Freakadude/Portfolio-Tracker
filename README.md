# Folio

Self-hosted, single-user portfolio manager: ledger, EUR valuation, dashboards, strategy rules and an advisory AI agent. It advises; it never places trades.

The build brief is [docs/requirements.md](docs/requirements.md). Progress per requirement is in [docs/traceability.md](docs/traceability.md).

## Status

Phase 0 (foundations) is complete and waiting for the owner's gate check; Phase 1 (ledger and prices) is next.

## Outbound network destinations (NFR-08)

All data stays local. The app only contacts what you configure:

- Market-data providers: EODHD, Twelve Data, OpenFIGI, FRED, ECB reference rates (optionally Yahoo Finance via `yfinance`)
- The Anthropic API (agent and news assessment)
- Notification channels: Home Assistant, ntfy, Web Push endpoints
- News feeds and APIs from your source list

## Local development

```bash
uv run folio init            # generates FOLIO_SECRET_KEY into .env
uv run folio web --reload    # API on :8080
cd web && npm run dev        # UI, proxies /api to :8080
```

Web checks (in `web/`): `npm run lint`, `npm run typecheck`, `npm test`, `npm run e2e` (Playwright, needs `npx playwright install chromium` once). After changing the API, run `npm run gen:api` and commit `src/api/schema.d.ts`.

Not exposed to the public internet: LAN or Tailscale only.
