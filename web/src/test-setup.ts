import '@testing-library/jest-dom/vitest'
import './i18n'

// jsdom has no layout: give the grid and the treemap a measurable container.
class FakeResizeObserver {
  constructor(private callback: ResizeObserverCallback) {}
  observe(target: Element) {
    this.callback(
      [{ target, contentRect: { width: 1200, height: 600 } } as ResizeObserverEntry],
      this,
    )
  }
  unobserve() {}
  disconnect() {}
}
globalThis.ResizeObserver ??= FakeResizeObserver as unknown as typeof ResizeObserver
Object.defineProperty(HTMLElement.prototype, 'offsetWidth', { configurable: true, value: 1200 })
