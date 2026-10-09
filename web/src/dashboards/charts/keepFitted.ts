import type { IChartApi } from 'lightweight-charts'

/** Keeps a chart fitted to its box when the box changes size.
 *
 * A chart sized to its widget is first drawn when the widget may still be hidden, or narrower or
 * wider than it ends up (the dashboard grid measures itself a moment after it appears). The
 * library then keeps the width of a bar and the right edge of the chart, so a chart that became
 * wider is left with an empty stretch on its left and starts toward the middle. Calling `fit`
 * again on every size change puts the first point on the left edge and the last on the right.
 * Once the owner zooms or scrolls the chart (wheel or pointer on it) it is left as they set it.
 * Returns the function that stops watching. */
export function keepFitted(chart: IChartApi, el: HTMLElement, fit: () => void): () => void {
  let touched = false
  const touch = () => {
    touched = true
  }
  const refit = () => {
    if (!touched) fit()
  }
  el.addEventListener('wheel', touch, { passive: true })
  el.addEventListener('pointerdown', touch)
  const scale = chart.timeScale()
  // the chart library is replaced by a stand-in in some tests, which has no such event
  const watching = typeof scale.subscribeSizeChange === 'function'
  if (watching) scale.subscribeSizeChange(refit)
  return () => {
    el.removeEventListener('wheel', touch)
    el.removeEventListener('pointerdown', touch)
    if (watching) scale.unsubscribeSizeChange(refit)
  }
}
