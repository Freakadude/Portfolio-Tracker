# ADR 0062: SEC filings, Fed speeches, export controls and per-holding headlines as news sources

Status: accepted (2026-10-10). Extends FR-NW-01, FR-NW-02 and FR-NW-05. Widens owner decision Q12 at the owner's request.

## Context
The owner asked which sources would add the most to the news and impact tracker (analyst institutions, wires, influential people on X, and the companies held, such as ASML's quarterly results), and then to add them. Each candidate was checked on 2026-10-10 against the live site and against Folio's rules for fetching: robots.txt is obeyed under the name "Folio", one request per site every 10 seconds, and only the headline, a short summary and the link are kept (FR-NW-02, FR-NW-03).

## Decision
Added, as ready-made sources (also to installs that already had the first three):
- **SEC filings for your holdings** (new kind `sec`). For each held or watched instrument whose ticker and name match a company in SEC's list (`company_tickers.json`; the first word of both names must agree, so a European ticker that equals an unrelated US one is refused), the filings since the last fetch are read from `data.sec.gov/submissions` (current reports 6-K and 8-K, periodic reports 10-Q, 10-K, 20-F, 40-F, and large-shareholder reports 13D and 13G, with amendments; at most five per company per run). The headline is the press release named on the filing's cover (exhibit 99.1), else the form and its subject (8-K item names). EDGAR's own Atom feed was not used: its titles say only "6-K - Report of foreign issuer". SEC asks every automated reader to identify itself with a contact address, so the owner gives an email (Settings, News) and only SEC requests carry it; until then the source waits, without counting as a failure.
- **Federal Reserve speeches and testimony** (RSS), tied to the same macro series as the Fed's press releases. The ECB needs nothing new: its press feed already carries speeches and interviews.
- **US export controls** (the Bureau of Industry and Security's documents in the Federal Register, RSS). These rarely name a holding; they reach the assessment through the existing allowance for unlinked stories from trusted sources, where the model links them by theme.
- **Nasdaq.com headlines for your shares**: an RSS address with `{symbol}` is read once per followed holding (at most 20). Only symbols SEC confirms are asked, because the site answers an unknown symbol with general market news (checked with `SXR8`: 15 unrelated items). Trust 0.5: these are third-party articles and research summaries.
- Items from the per-holding sources are tagged with their instrument, and the matcher turns the tag into a direct link (`feed:<ticker>`), so the cards of ADR 0061 say "Hits your holding directly".

Left out, with the reason:
- **Google News and Yahoo Finance feeds**: their robots.txt disallows all automated readers. **Reuters and Bloomberg**: no public feeds (Reuters' ended in June 2020).
- **X**: reading costs money per post (the free API closed to new developers in February 2026) and scraping breaks its terms; posts that move markets reach the wires and filings within minutes.
- **Bank research** (Morgan Stanley, Goldman Sachs, JPMorgan): for clients only; what reaches the public, rating changes, arrives through the per-holding headlines.
- **ETF issuers' notices and index providers**: no public feed found. **US and euro-area statistics releases**: BLS refuses automated readers (HTTP 403) and Eurostat's feed lists dataset updates, not releases; the data itself already comes from FRED and the ECB.
- **Dutch government export-control news**: no feed found.

Q12 now reads: central banks, regulators and official company filings, issuers, EODHD and Nasdaq.com headlines.

## Consequences
A news run makes a few more requests: one SEC company list a day, one SEC request per followed US-listed company and one per new filing, and one Nasdaq request per such company; with Folio's pacing a run with five companies takes about two minutes longer. To follow a company that is not held, such as TSMC as ASML's largest customer, the owner adds it to a watchlist. Earnings dates already come from EODHD when the owner switches them on (Settings, News, calendar).
