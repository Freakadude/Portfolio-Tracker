import { useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { Button } from '../../components/ui'

/** Every chart can be read as a table (NFR-11): the toggle sits above the chart. */
export function ChartFrame({
  chart,
  table,
  actions,
}: {
  chart: ReactNode
  table: ReactNode
  actions?: ReactNode
}) {
  const { t } = useTranslation()
  const [asTable, setAsTable] = useState(false)
  return (
    <div className="flex min-h-0 flex-1 flex-col gap-2">
      <div className="flex flex-wrap items-center justify-end gap-2">
        {actions}
        <Button
          variant="ghost"
          className="min-h-8 px-2 text-xs"
          onClick={() => setAsTable((v) => !v)}
          aria-pressed={asTable}
        >
          {t(asTable ? 'charts.showChart' : 'charts.showTable')}
        </Button>
      </div>
      <div className="min-h-0 flex-1 overflow-auto">{asTable ? table : chart}</div>
    </div>
  )
}

/** A plain table for the table view of a chart. */
export function DataTable({
  caption,
  head,
  rows,
}: {
  caption: string
  head: string[]
  rows: ReactNode[][]
}) {
  return (
    <div className="max-h-full overflow-auto">
      <table className="w-full text-sm">
        <caption className="sr-only">{caption}</caption>
        <thead>
          <tr className="border-b border-border">
            {head.map((h, i) => (
              <th
                key={i}
                scope="col"
                className={
                  i === 0 ? 'px-2 py-1 text-left font-medium' : 'px-2 py-1 text-right font-medium'
                }
              >
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, r) => (
            <tr key={r} className="border-b border-border">
              {row.map((cell, c) => (
                <td key={c} className={c === 0 ? 'px-2 py-1' : 'px-2 py-1 text-right tabular-nums'}>
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/** Names and colours of the things in a chart: always shown for two or more. */
export function Legend({ items }: { items: { key: string; label: string; color: string }[] }) {
  if (items.length < 2) return null
  return (
    <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted" aria-label="Legend">
      {items.map((item) => (
        <li key={item.key} className="flex items-center gap-1.5">
          <span
            aria-hidden="true"
            className="inline-block h-0.5 w-4"
            style={{ background: item.color, height: 3 }}
          />
          <span>{item.label}</span>
        </li>
      ))}
    </ul>
  )
}
