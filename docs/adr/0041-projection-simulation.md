# ADR 0041: The projection is a seeded Monte Carlo, the one place floats are used

Status: accepted (2026-10-06). Covers FR-PF-12.

## Context
FR-PF-12 asks for a Monte Carlo projection of future value with the contribution plan and configurable return and volatility assumptions, shown as a median line with a 10 to 90 percent band, with the assumptions visible on the chart. Folio's rule is Decimal for money and quantities.

## Decision
- A simulation is statistical, not accounting: it draws random numbers and is never stored or reconciled. `folio/analytics/projection.py` therefore uses floats inside the simulation (the random draws, the exponentials and the percentiles), and nothing else; every figure that leaves it is a `Decimal` rounded to cents, and the inputs are Decimals. This is the only module that does so.
- Each simulated month adds the contribution at its start and multiplies by a lognormal growth factor whose log has mean `(ln(1 + r) - s^2/2) / 12` and standard deviation `s / sqrt(12)`, so a year's expected factor is exactly `1 + r`; with `s = 0` the factor is `(1 + r)^(1/12)` and the result is exact compounding, which the tests pin against Decimal arithmetic. Returns in different months are independent; there is no regime change, fat tail or inflation.
- A seed (default 1) makes a run repeatable: the same assumptions give the same chart, which matters for a chart that is shown, compared and printed. 2,000 paths by default (1,000 on a dashboard widget, 5,000 at most); 1 to 40 years.
- The contribution is typed, default zero: there is no contribution plan (owner decision Q4), and the strategy's plan is not read, so the chart never assumes money the owner has not said they will add. The page shows what the portfolio measured over the last year (return and volatility) next to the inputs, as a hint and nothing more.
- The page, the widget and the endpoint call one function (`project_portfolio`). The chart is the shared time chart with two new series kinds (a tinted band and an opaque mask over it), has the usual table view, and writes the assumptions under it.

## Consequences
The band is as wide as the volatility the owner enters says, and the median is below the mean for volatile assumptions (the lognormal effect), which is stated by the chart's wording as "median". The note says it is an illustration, not a forecast.
