import { describe, expect, it, vi } from 'vitest'
import type { IChartApi } from 'lightweight-charts'
import { keepFitted } from './dashboards/charts/keepFitted'

function fakeChart() {
  let handler: (() => void) | undefined
  const scale = {
    subscribeSizeChange: vi.fn((h: () => void) => {
      handler = h
    }),
    unsubscribeSizeChange: vi.fn(),
  }
  return {
    chart: { timeScale: () => scale } as unknown as IChartApi,
    scale,
    resize: () => handler?.(),
  }
}

describe('keeping a chart fitted to its widget', () => {
  it('fits again each time the chart changes size', () => {
    const { chart, resize } = fakeChart()
    const fit = vi.fn()
    keepFitted(chart, document.createElement('div'), fit)
    resize()
    resize()
    expect(fit).toHaveBeenCalledTimes(2)
  })

  it('leaves a chart as the owner set it once they have zoomed or scrolled it', () => {
    const { chart, resize } = fakeChart()
    const el = document.createElement('div')
    const fit = vi.fn()
    keepFitted(chart, el, fit)
    el.dispatchEvent(new Event('wheel'))
    resize()
    expect(fit).not.toHaveBeenCalled()
  })

  it('stops watching when the chart goes away', () => {
    const { chart, scale, resize } = fakeChart()
    const el = document.createElement('div')
    const fit = vi.fn()
    const stop = keepFitted(chart, el, fit)
    stop()
    expect(scale.unsubscribeSizeChange).toHaveBeenCalledTimes(1)
    el.dispatchEvent(new Event('pointerdown')) // no longer listened to
    resize()
    expect(fit).toHaveBeenCalledTimes(1) // the stand-in still calls its handler; the real one would not
  })

  it('does nothing in a stand-in that has no size event', () => {
    const chart = { timeScale: () => ({}) } as unknown as IChartApi
    expect(() => keepFitted(chart, document.createElement('div'), vi.fn())()).not.toThrow()
  })
})
