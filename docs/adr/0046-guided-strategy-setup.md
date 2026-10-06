# ADR 0046: A guided, step-by-step strategy setup, built in the browser

Status: accepted (2026-10-06). Covers FR-ST-01.

## Context
The strategy form shows every field of the strategy document (sleeves, bands in percentage points, trim thresholds, twelve rule types). A beginner does not know what to fill in. The owner asked for a guided path, and chose a plain wizard before any AI help.

## Decision
- A "Guided setup" button on Strategies opens an eight-step wizard: name, groups (sleeves) for the current holdings, targets, how strictly to watch them (relaxed 5/10, balanced 3/6, tight 2/4 points), which alerts, an optional regular contribution, principles, and a review.
- It only builds an ordinary strategy definition and sends it to the existing `POST /strategies` (the same JSON the form sends; the server checks and stores it as always). No new endpoint, no migration, no new stored shape, so the guided and the full path cannot disagree. The result opens in the editor, where everything can be changed.
- The groups start from the sleeves already in use; the current mix is computed in the browser from the positions. "Use today's mix" gives whole-percent targets that add up to exactly 100.
- The strategy is saved switched off by default, so nothing changes until the owner looks; "make it active" is an explicit choice and says what it does.
- Rules without a simple answer (interest-rate thresholds, correlation shifts, price levels) stay in the full form. An AI-assisted "suggest from my goals" step is left for later; it would produce the same `Answers` and use the same builder.
- A Python test posts a definition shaped exactly like the wizard's output with every option on, so a change in the schema that breaks the wizard fails a test.

## Consequences
Front-end code only, plus tests. The wizard's output is limited to the rule types it knows; owners who want more use the form afterwards.
