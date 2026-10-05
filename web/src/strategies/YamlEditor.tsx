import { useRef } from 'react'
import { useTranslation } from 'react-i18next'
import { cn } from '../lib/cn'
import type { Problem } from './api'

/** A monospace editor with line numbers; lines with a problem are marked in the gutter and
 * listed below it, and a click on a problem puts the cursor on its line (FR-ST-01). */
export function YamlEditor({
  value,
  onChange,
  problems,
}: {
  value: string
  onChange: (text: string) => void
  problems: Problem[]
}) {
  const { t } = useTranslation()
  const area = useRef<HTMLTextAreaElement>(null)
  const gutter = useRef<HTMLDivElement>(null)
  const lines = value.split('\n')
  const bad = new Set(problems.map((p) => p.line).filter((l): l is number => l !== null))

  function goTo(line: number) {
    const el = area.current
    if (!el) return
    const start = lines.slice(0, line - 1).reduce((n, l) => n + l.length + 1, 0)
    el.focus()
    el.setSelectionRange(start, start + (lines[line - 1]?.length ?? 0))
    const height = el.scrollHeight / Math.max(lines.length, 1)
    el.scrollTop = Math.max(0, (line - 4) * height)
  }

  return (
    <div className="space-y-2">
      <div className="flex overflow-hidden rounded-md border border-border bg-card font-mono text-sm">
        <div
          ref={gutter}
          aria-hidden="true"
          className="min-w-[3rem] select-none overflow-hidden border-r border-border py-2 text-right text-muted"
        >
          {lines.map((_, i) => (
            <div
              key={i}
              className={cn(
                'px-2 leading-6',
                bad.has(i + 1) && 'bg-danger/15 font-bold text-danger',
              )}
            >
              {i + 1}
            </div>
          ))}
        </div>
        <textarea
          ref={area}
          aria-label={t('strategies.editor.yaml')}
          spellCheck={false}
          value={value}
          rows={Math.min(Math.max(lines.length, 12), 40)}
          onChange={(e) => onChange(e.target.value)}
          onScroll={(e) => {
            if (gutter.current) gutter.current.scrollTop = e.currentTarget.scrollTop
          }}
          className="w-full resize-y whitespace-pre bg-transparent px-3 py-2 leading-6 outline-none"
          wrap="off"
        />
      </div>
      {problems.length > 0 && (
        <ul
          role="alert"
          className="space-y-1 rounded-md border border-danger/50 p-2 text-sm text-danger"
        >
          {problems.map((p, i) => (
            <li key={i}>
              {p.line !== null ? (
                <button type="button" className="underline" onClick={() => goTo(p.line ?? 1)}>
                  {t('strategies.editor.line', { line: p.line })}
                </button>
              ) : null}{' '}
              {p.path && <code className="text-xs">{p.path}</code>} {p.message}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
