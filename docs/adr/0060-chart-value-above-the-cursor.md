# ADR 0060: The value under the pointer is written above the cursor, in colours that stand out

Status: accepted (2026-10-10). Extends FR-DB-03 (dashboard charts) and the position page's price chart; new scope, asked for by the owner.

## Context
Over a line chart the value at the pointer was read from two places that are both away from where the eye is: the label the chart library draws on the price axis at the right edge, and on dashboards a small box fixed in the top-left corner. The position page's price chart had only the axis label. Both used the series colours or the plain card colours, so the number was hard to pick out from the chart under it.

## Decision
- **One chip that follows the pointer** (`web/src/dashboards/charts/cursorTip.ts`), used by the dashboard time charts (`TimeChart`) and the position price chart (`PriceChart`). It shows the time and the value of each series at that time, centred above the cursor; where there is no room above it goes below, and it never leaves the chart sideways. It disappears when the pointer leaves the chart.
- **The crosshair no longer writes the value on the price axis** (the horizontal line's label is off); the vertical line keeps its time label. The value is in one place.
- **Distinct colours.** The chip uses the page's own text and card colours swapped (dark chip with light text on a light page, light chip with dark text on a dark page), so it is a neutral that none of the series colours resembles in either theme. The point marked on the line is filled in the same neutral instead of the line's colour, with a card-coloured ring.
- The chart is drawn on a canvas, so the chip is a small DOM element laid over it, as the old box was; it has `pointer-events: none` so it never takes the hover from the chart.

## Consequences
The values still come from the chart's own data, so the two-decimal rule (ADR 0052) holds as before: the chip uses the same formatters as the axis. Pointer-less (touch) use is unchanged: the library shows the crosshair on touch and the chip appears with it.
