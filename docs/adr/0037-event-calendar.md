# ADR 0037: The event calendar, its three sources and the evening-before notice

Status: accepted (2026-10-06). Covers FR-NW-09.

## Context
The spec asks for earnings dates of direct equities, central bank meetings and owner-added events, with a brief generated the evening before each. Q2 says free data tiers; EODHD's earnings calendar may not be in the owner's plan.

## Decision
- One table, `calendar_event` (migration 0009), with a kind, a date, a title, an optional instrument, a source (`shipped`, `eodhd`, `owner`), an external id and the time the brief or reminder was sent. Rows are soft-deleted: the sync of ready-made and EODHD rows looks up deleted ones too, so a date the owner removed is never brought back.
- Central bank decision days for 2026 and 2027 (ECB Governing Council and FOMC) ship as a JSON data file, because no free machine-readable source is dependable enough to fetch from. They are written by the weekly `calendar` job (and by "Refresh dates"). They come from the banks' published schedules and were not fetched from a live source: the owner gate asks for a check, and the page says so. 2027 dates are not shipped until the banks have published them and they have been verified.
- Earnings dates come from EODHD's `calendar/earnings` for directly held equities (asset class EQUITY priced by EODHD), in one request for all symbols, off by default (`CalendarSettings.earnings_eodhd`). It is charged one call (per the documentation: to be checked on a real key) and skipped when it would eat into the budget reserved for the nightly closes, as the news fetch does. A refusal (a plan without the calendar) is logged as an error on the System page and nothing else stops. A company that moves its report date moves the event and clears its brief.
- The brief is an agent run of type `event_brief` (Sonnet; the task text is in `agent/context.py` like the other run types, so no new prompt file), with the event as its focus. Its digest becomes an Insights item. Any recommendation it makes goes through the same code gate as every other run.
- The notice never depends on the model: from 18:00 local time the job looks for events dated tomorrow without a brief; if the agent is off, has no key, has used its budget, or the run fails, it sends a plain reminder instead. The job is scheduled every 15 minutes from 18:00 to 23:45 and waits for 18:00 itself, so a worker that was down at 18:00 catches up the same evening.
- `get_upcoming_events` returns the real list (dates and titles; it says nothing about outcomes).
- Settings saved before a run type existed have no model for it; `agent_settings` now fills missing models from the defaults.

## Consequences
The calendar is only as complete as its sources: until earnings are switched on and the plan allows it, earnings dates must be typed in. The shipped file needs updating once a year (a line in the Phase 5 gate list and the changelog says so).
