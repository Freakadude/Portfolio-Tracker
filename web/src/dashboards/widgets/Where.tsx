import { useTranslation } from 'react-i18next'
import { useFormat } from '../../lib/useFormat'
import type { ExposurePart } from '../types'

/** Where a look-through exposure sits: held directly, or inside which ETF and at what weight
 * (FR-PF-05). */
export function Where({ parts }: { parts?: ExposurePart[] }) {
  const { t } = useTranslation()
  const { eur, num } = useFormat()
  if (!parts || parts.length === 0) return <span className="text-muted">–</span>
  return (
    <ul className="space-y-0.5">
      {parts.map((p) => (
        <li key={`${p.instrument_id}-${p.kind}`}>
          {t(`lookThrough.part.${p.kind}`, {
            source: p.source,
            value: eur(p.value_eur, 0),
            weight: p.weight_pct === null ? '' : num(Number(p.weight_pct), 1),
          })}
        </li>
      ))}
    </ul>
  )
}
