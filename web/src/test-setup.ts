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
// The grid measures its container with clientWidth. Without this it first reads 0 (a phone-sized
// layout) and then 1200 from the observer above, and with the data arriving in between the two
// layouts kept replacing each other: the test never finished, on slower machines every time.
Object.defineProperty(HTMLElement.prototype, 'clientWidth', { configurable: true, value: 1200 })
