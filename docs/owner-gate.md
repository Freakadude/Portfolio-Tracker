# Owner gate: what is left for you to check

You deferred the phase checks until the last phase was finished. Everything below is built and tested; what is listed here is what only you can check, because it needs your data, your accounts or your phone. Each phase's own list, with more detail, is in [docs/changelog.md](changelog.md). Tick them off in this order: the early ones make the later ones meaningful.

## Deployment (all phases)
- [ ] The stack runs through Portainer and `http://<LAN IP>:8555/healthz` answers (done once; redo after each update: "Update the stack" with "Re-pull image").

## Phase 1 and 2: your real data
- [ ] Import your real Degiro export (Transactions, Import CSV; the wizard should say it recognised Degiro) and check every position's quantity and cost basis against the statement, including AutoFX fees. Never commit the export.
- [ ] Compare the time-weighted return and XIRR for one year with your own spreadsheet; they should agree within 0.01 percentage point.
- [ ] Look up one real ISIN (the providers' live formats were only tested against recorded or documented responses).
- [ ] Build or rearrange a dashboard on your phone.

## Phase 3: alerts and strategy
- [ ] Push to your phone: Settings, Notifications, Home Assistant address, notify service and token; press the test button.
- [ ] Your strategy: Strategies, New strategy, fill in targets and bands, save, make it active.
- [ ] Macro data: the FRED key under Settings, Providers, then Settings, Macro, Fetch now; add a Macro overlay widget.

## Phase 4: news and the agent
- [ ] Anthropic key in Settings, Agent; "Test the key"; check the price table against Anthropic's pricing page.
- [ ] Upload one real ETF holdings file (CSV or Excel; send the first lines of any that is not recognised); the Look-through widget should list the underlying companies.
- [ ] Preview the ECB and Fed feeds; add one issuer feed.
- [ ] Let one daily review run (or "Run a review now"), read its advice and trace, check its cost, accept one piece of advice with drafts.

## Phase 5: the extras
- [x] The ECB and Fed decision days (2026 and 2027) were checked against the banks' own pages on 2026-10-06; nothing left for you here.
- [ ] Two-factor sign-in: set it up, keep the recovery codes, sign out and in.
- [ ] Make a backup, download it, and restore one when you can afford a minute of downtime.
- [ ] Ask the portfolio one question; read the data listed under the answer.
- [ ] Reports: the tax-support report against your own records for one year (print it to PDF), and the export (download the transactions and read the file back in through the import).
- [ ] Optional: EODHD earnings dates (needs a plan with the earnings calendar), Tailscale sign-in (docs/deployment.md).

## Fixtures to confirm against real responses
EODHD (end of day, search, dividends, splits, real-time, fundamentals, news, earnings), Twelve Data, FRED, the ECB and Fed feeds' real layouts, and an issuer's real holdings file were written from documentation or recorded earlier; the checks above are also how they get confirmed. Anything that does not match is a bug to report, not a setting to work around.
