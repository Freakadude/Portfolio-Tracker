# Folio — conventions for Claude Code

Folio is a self-hosted, single-user portfolio manager. The full build brief is `docs/requirements.md`; requirement IDs (`FR-<AREA>-NN`, `NFR-NN`) are traced in `docs/traceability.md`.

## Working conventions

- Work one phase at a time (spec section 18). Start each phase in plan mode and wait for the owner's go-ahead. Tell the owner right before entering plan mode and right after leaving it, so they can change model and effort.
- Build domain logic and its property tests before endpoints, and endpoints before UI.
- A requirement is done only when its acceptance criterion is covered by a passing automated test (or a Playwright screenshot test for purely visual items).
- Keep `docs/traceability.md` (ID → module → test → status) and `docs/changelog.md` current in the same commit as the change.
- Record every non-obvious decision (library choice, schema change, deviation from the spec) as a short ADR in `docs/adr/`.
- Never use floats for money or quantities. `Decimal` end to end, stored as TEXT.
- No live external calls in tests. Provider and LLM adapters are tested against recorded fixtures.
- Never commit secrets, real transactions or amounts. Ship `.env.example` and `folio seed --demo` for fictional data.
- Do not build anything listed under non-goals (spec section 1), in particular order execution or broker log-in.
- Prefer few, well-maintained, pinned dependencies; justify heavy additions in an ADR.
- Commit messages follow Conventional Commits and cite requirement IDs, e.g. `feat(ledger): FIFO lot matching [FR-TX-03]`.
- Agent prompts live in `folio/agent/prompts/` as versioned files; write the agent evaluation scenarios before tuning prompts.
- Local dev: `uv run folio web --reload`, `uv run folio worker`, `npm run dev` in `web/`.

## Standing order: commit and push to GitHub

This order applies in every session for the life of the project: whenever a significant feature is finished or a bug is fixed, Claude Code commits the relevant source files and pushes them to [github.com/Freakadude/Portfolio-Tracker](https://github.com/Freakadude/Portfolio-Tracker). It does this on the owner's behalf with the owner's own Git login on their computer, without being asked each time.

1. **When.** After each finished feature (one or more requirement IDs meeting their acceptance tests) and after each bug fix (with a regression test that failed before the fix and passes after it). Work in progress is not committed to the shared branch.
2. **Check first.** At the start of each session, confirm `git remote -v` points to the repository and `git status` is clean. Before each commit, run the full test suite and linters; the pre-commit hooks (ruff, ESLint/Prettier, and a gitleaks secret scan) must pass. If anything fails, fix it first or ask the owner; never commit with `--no-verify`.
3. **Stage deliberately.** Review `git status` and `git diff`, then stage the relevant files by path. Never stage `.env`, API keys, database files, anything under `/data`, backups, imported broker exports, `node_modules`, build output or `.claude/settings.local.json`. The `.gitignore` created in Phase 0 excludes all of these.
4. **Commit.** One logical change per commit, Conventional Commits format with requirement IDs, e.g. `feat(ledger): FIFO lot matching [FR-TX-03]` or `fix(import): parse comma decimals [FR-TX-07]`. Update `docs/traceability.md` and `docs/changelog.md` in the same commit.
5. **Push.** Default branching (see Q13): one branch per phase, e.g. `phase/p1-ledger-and-prices`, pushed after every commit with `git push -u origin <branch>`. At the phase gate, Claude Code opens a pull request into `main` with `gh pr create`, listing the requirement IDs completed and the test evidence; the owner reviews and merges.
6. **Report.** After each push, tell the owner in one line: branch, short commit hash, and what changed.
7. **Never.** Force-push, rewrite pushed history, push straight to `main` (unless the owner chooses that under Q13), put a token in a remote URL or a file, or ask the owner to paste a password or token into the chat.
8. **If a push fails.** Stop, show the exact error, and point the owner to the setup step in `docs/requirements.md` (section 19, "One-time GitHub setup") that fixes it. Do not try workarounds.

### Owner decision on Q13 (2026-10-04): commit straight to `main`

The owner chose to commit and push directly to `main`. This overrides the default in step 5 (branch per phase and PR) and satisfies the "unless the owner chooses that under Q13" clause in step 7. Everything else in the order still applies: tests and hooks pass first, never `--no-verify`, never force-push, never rewrite pushed history. See `docs/adr/0002-commit-to-main.md`.

## Owner decisions (spec section 20, answered 2026-10-04)

| # | Decision |
| --- | --- |
| Q1 | Broker is Degiro. No sample export yet; generic CSV import with manual mapping until one is supplied (FR-TX-08 preset later). |
| Q2 | Free data tiers; `yfinance` fallback available but off; look-through via manual CSV. |
| Q3 | Sleeve targets, bands and trim thresholds are set later; drift and trim rules stay inactive until then. |
| Q4 | No contribution plan; `contribution_due` rule off. |
| Q5 | Home Assistant companion app for phone push; ntfy as second option. |
| Q6 | Monthly LLM budget **€5** (spec default was €15), hard stop. |
| Q7 | Cash tracking off. |
| Q8 | Whole units only (no fractional ETF units). |
| Q9 | No benchmark chosen yet. |
| Q10 | English only, i18n-ready. |
| Q11 | React for the UI. |
| Q12 | Trusted news sources: central banks, issuers and EODHD news only. |
| Q13 | Commit straight to `main`. |
