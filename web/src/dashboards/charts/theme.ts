import { useEffect, useState } from 'react'

/** The value of a CSS custom property, for libraries that draw to a canvas and cannot use var(). */
export function css(name: string, fallback: string) {
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
  return value || fallback
}

/** The theme can change while the page is open; this changes whenever it does. */
export function useThemeKey() {
  const [key, setKey] = useState(0)
  useEffect(() => {
    const bump = () => setKey((k) => k + 1)
    const observer = new MutationObserver(bump)
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ['data-theme'],
    })
    const media = window.matchMedia?.('(prefers-color-scheme: dark)')
    media?.addEventListener?.('change', bump)
    return () => {
      observer.disconnect()
      media?.removeEventListener?.('change', bump)
    }
  }, [])
  return key
}
