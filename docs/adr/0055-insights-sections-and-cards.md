# ADR 0055: Insights as collapsible sections, with advice and inbox items as cards

Status: accepted (2026-10-09). Concerns FR-NT-01 (the inbox) and FR-AG-05 (the advice); new scope, asked for by the owner.

## Context
Insights stacked seven parts under identical small headings, and its advice cards and inbox items were bordered boxes with a row of tiny badges and a block of muted text. Nothing stood out, and what needed a decision could not be told from what was only for reference.

## Decision
- **A section component** (`components/Panel.tsx`): a header that stands out (a gradient band with a primary accent, a larger title, a count badge, a status line that stays readable when the section is closed) over a body. The header toggles the section; its action buttons sit beside it and do not. The open or closed state is remembered per section in this browser; before the owner has chosen, a section starts closed when nothing is waiting in it or when it is reference material (the track record), and a link that points into a section keeps it open.
- **Order by what needs the owner first:** advice, order drafts, the inbox, proposed splits, proposed dividends, then the track record. The "Ask the portfolio" box is gone from this page: the chat panel answers from any page and knows which page the owner is on (ADR 0049); position pages and the dashboard widget keep their own.
- **Cards have four parts:** a header (the title, then severity, kind and source as quiet badges, and when), a summary (the one thing to take in), details (the reasoning, the orders and evidence; for the inbox the rest of the text and the delivery notes) behind a clear "Show details", and a row of action buttons. A stripe in the severity colour runs down the left of a card, and an unread inbox item is tinted. The inbox shows the first line of an item's text as its summary and the rest as details; the main button says where it goes ("Open position", "Open story", "Review advice").
- The inbox's status filter is a switch (All, Unread, Read); severity, type and subject are folded under "More filters".

## Consequences
The text of a notification is still one string; the split into summary and details is by the first line, so a notification whose first line is not a good summary shows it anyway. If the server ever sends a separate summary, the card takes it with no change to the layout.
