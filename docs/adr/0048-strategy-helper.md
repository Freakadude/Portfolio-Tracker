# ADR 0048: An AI strategy helper in two modes, with the owner's background notes

Status: accepted (2026-10-07). Extends FR-ST-01 (see ADR 0046) and uses FR-AG-02 and FR-AG-04 (the API client and the budget). It is new scope, beyond the original specification, asked for by the owner.

## Context
The owner wants a helper that interviews them with guided questions and then sets up, and later refines and revises, a strategy, and wants it to start from the investment talks they already had with Claude. They asked whether their Claude subscription could power it.

## Decision
- **The subscription cannot be used by the app.** A Claude Pro or Max login covers the Claude apps and Claude Code; an app talks to the API, which is billed by use. Folio therefore offers two modes that end in the same checked strategy:
  1. **In-app interview** through the API key, the monthly budget and the privacy mode that the agent already uses (every call is metered; a few cents a session).
  2. **"Use my subscription" (free):** Folio builds one ready prompt (the task, the strategy format, the portfolio summary, the background notes); the owner pastes it into claude.ai, talks it through there, and pastes the finished strategy back, which Folio checks like any other.
- **Background notes** (`background_note`, migration 0012) hold what the helper is told about the owner. They are written by hand, pasted from a chat with Claude (the owner pastes a prompt that Folio supplies, so this step also needs no API), or summarised from an export of the owner's chats. Each note is limited to 6,000 characters and the helper reads at most 12,000 characters in all (newest first), so a long history cannot make every turn expensive. The text is always wrapped as data about the owner, never as instructions.
- **Only the strategy helper reads the notes.** The daily agent, the news steps and "Ask the portfolio" do not, so their cost and what they send out stay as they were. The notes are stored locally and are in the backups. They leave the app only inside a helper session that the owner starts with their own key.
- **The helper never changes anything by itself.** Its only product is a draft strategy that the owner saves as a new strategy switched off (the path of the guided setup, ADR 0046) and then opens in the editor. It gives no advice on buying or selling a particular security.

## Consequences
One new table and one router; no change to how strategies are stored, checked or run. The free mode needs nothing from Anthropic's API, so it works with the agent switched off or without a key.

## Addendum: importing the chat export
The export is sent to the server for each step (scan, estimate, summarise) and read in memory; it is never stored, so no staging area is needed. Chats are scored by how many messages mention investing, and the owner picks at most 8 per request. Each summary is its own call with the cheapest model (`news_triage` in the model settings) and its own `agent_run` row of type `chat_summary`. That type is neither a news step nor an agent run, so it counts toward the monthly budget but not toward the daily run cap or the news share. The estimate is the worst case (all input at the full price, the whole output allowance), so the real cost is lower. A chat is cut in the middle above 40,000 characters. The summaries are returned to the owner and become notes only when the owner keeps them.

## Addendum: the free mode
The prompt is built on the server from the same pieces the in-app interview will use (`folio/agent/strategist.py`): the versioned rules of the interview (`strategist.md`), a wrapper for claude.ai (`strategist_paste.md`), and a context block with the format of a strategy, an example from the owner's groups, the holdings as percentages, the switched-on notes and, to revise, the current YAML. The format guide is generated from the pydantic models, and a test fails when a rule type has no plain-words description, so the prompt cannot drift from what the app accepts. The pasted answer is reduced in the browser to its last fenced `strategy:` block and checked by the existing `POST /strategies/check`. A revision is compared with the current version by `POST /assistant/diff`. The owner chooses between a new version (which, for an active strategy, starts working at once, and is said so) and a separate strategy that starts switched off.
