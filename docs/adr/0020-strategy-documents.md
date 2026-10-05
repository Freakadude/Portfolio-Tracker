# ADR 0020: Strategy documents, versions, and the sleeves they own

Status: accepted (2026-10-05)

## Decisions
- **The strategy is a YAML document checked by Pydantic models.** `folio/strategies/schema.py` describes spec appendix B: sleeves with targets and bands, risk limits, typed rules (a tagged union on `type`), principles, theses and the contribution plan. The JSON Schema the editor uses comes from the same models, so the two cannot drift apart. Every target and threshold is optional (Q3); a rule that needs a missing number does nothing.
- **Every problem has a line number.** The text is read twice with PyYAML: once into values, once into the node tree that remembers positions. A validation error's path (`strategy.sleeves[2].target_pct`) is walked through that tree to find the line; a missing field points at the item that lacks it, a syntax error at the mark PyYAML reports. Numbers are read as exact decimals, never through binary floats. PyYAML moves from a test-only to a runtime dependency; it is small, mature, and already in the lock file.
- **Versions are immutable.** A save always adds a `strategy_version` row with the YAML as written (comments kept) and its parsed form. The form view sends JSON, which is written out as canonical YAML. Two versions are compared line by line with `difflib`, side by side.
- **One active strategy; others can shadow it.** Activating a strategy turns the previously active one into a shadow. Shadow strategies are evaluated and their signals stored, but they never reach the inbox or the phone (FR-ST-02). Mode changes are audited.
- **The active strategy owns the sleeve targets.** On activation, and on every save of the active strategy, its sleeves are synced into the `sleeve` table from Phase 2: created if missing, target and soft band copied, members (ISINs, or instrument tags) assigned. Sleeves the strategy does not mention keep their instruments but lose their targets, so no stale drift is shown. While a strategy is active the Sleeves settings refuse target and band edits and say where to change them; with no active strategy they are editable again. Every allocation, drift widget and What-if from Phase 2 keeps working unchanged, because they read the `sleeve` table.
- **The contribution plan lives in the strategy**, not in a table of its own: it is one amount, a cadence and a date, versioned with the rest. With no plan (Q4) the `contribution_due` rule has nothing to do.

## Consequences
The hard band, trim threshold and member list exist only in the strategy; the `sleeve` table carries the target and the soft band that the dashboards show. Changing targets means saving a new strategy version, which leaves a history of every target ever set.
