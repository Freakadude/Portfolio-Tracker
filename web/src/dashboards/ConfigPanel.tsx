import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Dialog } from '../components/display'
import { Alert, Button, Checkbox, Field, Input, Select, Textarea } from '../components/ui'
import { useAccounts, useInstruments } from '../api/queries'
import { useMacroSeries } from '../notify/api'
import { errorMessage } from '../api/client'
import {
  useSleeves,
  useWidgetData,
  type Box,
  type Config,
  type DashboardWidget,
  type Filters,
} from './api'
import { COLS, WidgetBody, widgetTitle, type Breakpoint } from './DashboardView'
import { widgetDef, type OptionField } from './registry'

const PERIODS = ['1D', '1W', '1M', '3M', 'YTD', '1Y', '3Y', '5Y', 'MAX'] as const

function useDebounced<T>(value: T, ms: number): T {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const id = setTimeout(() => setDebounced(value), ms)
    return () => clearTimeout(id)
  }, [value, ms])
  return debounced
}

/** The typed position, kept inside the grid: a box that is too wide moves left to fit. */
export function fitted(
  place: Box | undefined,
  box: Box | undefined,
  columns: number,
): Box | undefined {
  if (!place || !box) return undefined
  const w = Math.max(1, Math.min(columns, Math.round(place.w)))
  const fit = {
    ...place,
    w,
    h: Math.max(1, Math.round(place.h)),
    x: Math.max(0, Math.min(Math.round(place.x), columns - w)),
    y: Math.max(0, Math.round(place.y)),
  }
  return JSON.stringify(fit) === JSON.stringify(box) ? undefined : fit
}

interface Props {
  widget: DashboardWidget
  breakpoint: Breakpoint
  box: Box | undefined
  filters: Filters
  saving: boolean
  error?: unknown
  onClose: () => void
  /** The new options and, when the owner changed them, the new position for this breakpoint. */
  onSave: (config: Config, box: Box | undefined) => void
}

/** The side panel of one widget (FR-DB-03): scope, period, title and its own options, with a
 * preview that redraws as they change. Position and size can be typed here too, which is the
 * keyboard way to arrange widgets. */
export function ConfigPanel({
  widget,
  breakpoint,
  box,
  filters,
  saving,
  error,
  onClose,
  onSave,
}: Props) {
  const { t } = useTranslation()
  const def = widgetDef(widget.type)
  const [draft, setDraft] = useState<Config>(() => ({ ...(widget.config as Config) }))
  const [place, setPlace] = useState<Box | undefined>(box)
  const accounts = useAccounts()
  const sleeves = useSleeves()
  const instruments = useInstruments('active')
  const macro = useMacroSeries()
  const set = (key: string, value: unknown) => setDraft((d) => ({ ...d, [key]: value }))
  const scope = (draft.scope as { kind: string; id: number | null } | undefined) ?? {
    kind: 'portfolio',
    id: null,
  }

  const preview = useDebounced(draft, 150)
  const query = useWidgetData([{ key: 'preview', type: widget.type, config: preview }], filters)
  if (!def) return null

  const field = (f: OptionField) => {
    const label = t(`widgetOptions.${f.key}`)
    const value = draft[f.key]
    switch (f.kind) {
      case 'boolean':
        return (
          <Checkbox
            key={f.key}
            label={label}
            checked={Boolean(value)}
            onChange={(e) => set(f.key, e.target.checked)}
          />
        )
      case 'select':
        return (
          <Field key={f.key} label={label}>
            {(p) => (
              <Select
                value={String(value ?? '')}
                onChange={(e) => set(f.key, e.target.value)}
                {...p}
              >
                {f.options?.map((o) => (
                  <option key={o} value={o}>
                    {t(`${f.labels}.${o}`, { defaultValue: o })}
                  </option>
                ))}
              </Select>
            )}
          </Field>
        )
      case 'multi': {
        const chosen = (value as string[] | undefined) ?? []
        return (
          <fieldset key={f.key} className="space-y-1">
            <legend className="text-sm font-medium">{label}</legend>
            <div className="flex flex-wrap gap-x-4">
              {f.options?.map((o) => (
                <Checkbox
                  key={o}
                  label={t(`${f.labels}.${o}`, { defaultValue: o })}
                  checked={chosen.includes(o)}
                  onChange={(e) =>
                    set(f.key, e.target.checked ? [...chosen, o] : chosen.filter((c) => c !== o))
                  }
                />
              ))}
            </div>
          </fieldset>
        )
      }
      case 'ordered': {
        const chosen = (value as string[] | undefined) ?? [...(f.fallback ?? [])]
        const rest = (f.options ?? []).filter((o) => !chosen.includes(o))
        const move = (i: number, by: number) => {
          const next = [...chosen]
          ;[next[i], next[i + by]] = [next[i + by], next[i]]
          set(f.key, next)
        }
        const name = (o: string) => t(`${f.labels}.${o}`, { defaultValue: o })
        return (
          <fieldset key={f.key} className="space-y-1">
            <legend className="text-sm font-medium">{label}</legend>
            <p className="text-xs text-muted">{t('widgetOptions.orderedHint')}</p>
            <ol className="space-y-1">
              {chosen.map((o, i) => (
                <li key={o} className="flex items-center gap-1 text-sm">
                  <span className="w-6 text-right text-muted">{i + 1}.</span>
                  <span className="flex-1">{name(o)}</span>
                  <Button
                    type="button"
                    variant="ghost"
                    className="min-h-8 px-2"
                    aria-label={t('widgetOptions.moveUp', { name: name(o) })}
                    disabled={i === 0}
                    onClick={() => move(i, -1)}
                  >
                    ↑
                  </Button>
                  <Button
                    type="button"
                    variant="ghost"
                    className="min-h-8 px-2"
                    aria-label={t('widgetOptions.moveDown', { name: name(o) })}
                    disabled={i === chosen.length - 1}
                    onClick={() => move(i, 1)}
                  >
                    ↓
                  </Button>
                  <Button
                    type="button"
                    variant="ghost"
                    className="min-h-8 px-2"
                    aria-label={t('widgetOptions.removeItem', { name: name(o) })}
                    disabled={chosen.length <= 1}
                    onClick={() =>
                      set(
                        f.key,
                        chosen.filter((c) => c !== o),
                      )
                    }
                  >
                    ✕
                  </Button>
                </li>
              ))}
            </ol>
            {rest.length > 0 && (
              <Select
                aria-label={t('widgetOptions.addItem')}
                value=""
                onChange={(e) => e.target.value && set(f.key, [...chosen, e.target.value])}
              >
                <option value="">{t('widgetOptions.addItem')}</option>
                {rest.map((o) => (
                  <option key={o} value={o}>
                    {name(o)}
                  </option>
                ))}
              </Select>
            )}
          </fieldset>
        )
      }
      case 'sortby': {
        const columns = widgetDef(widget.type)?.fields.find((x) => x.key === 'columns')
        const chosen = (draft.columns as string[] | undefined) ?? [...(columns?.fallback ?? [])]
        return (
          <Field key={f.key} label={label}>
            {(p) => (
              <Select
                value={String(value ?? '')}
                onChange={(e) => set(f.key, e.target.value || null)}
                {...p}
              >
                <option value="">{t('widgetOptions.listOrder')}</option>
                {chosen.map((o) => (
                  <option key={o} value={o}>
                    {t(`${f.labels}.${o}`, { defaultValue: o })}
                  </option>
                ))}
              </Select>
            )}
          </Field>
        )
      }
      case 'number':
        return (
          <Field key={f.key} label={label}>
            {(p) => (
              <Input
                type="number"
                value={String(value ?? '')}
                min={f.min}
                max={f.max}
                onChange={(e) => set(f.key, Number(e.target.value))}
                {...p}
              />
            )}
          </Field>
        )
      case 'macro':
        return (
          <Field key={f.key} label={label}>
            {(p) => (
              <Select
                value={String(value ?? '')}
                onChange={(e) => set(f.key, e.target.value || null)}
                {...p}
              >
                <option value="">{t('widgetOptions.macroAuto')}</option>
                {macro.data?.map((m) => (
                  <option key={m.code} value={m.code}>
                    {m.name}
                  </option>
                ))}
              </Select>
            )}
          </Field>
        )
      case 'instruments': {
        const chosen = (value as number[] | undefined) ?? []
        const rest = (instruments.data ?? []).filter((i) => !chosen.includes(i.id))
        const nameOf = (id: number) => instruments.data?.find((i) => i.id === id)?.name ?? `#${id}`
        return (
          <fieldset key={f.key} className="space-y-1">
            <legend className="text-sm font-medium">{label}</legend>
            <p className="text-xs text-muted">{t('widgetOptions.instrumentsHint')}</p>
            <ul className="space-y-1">
              {chosen.map((id) => (
                <li key={id} className="flex items-center gap-1 text-sm">
                  <span className="flex-1">{nameOf(id)}</span>
                  <Button
                    type="button"
                    variant="ghost"
                    className="min-h-8 px-2"
                    aria-label={t('widgetOptions.removeItem', { name: nameOf(id) })}
                    onClick={() =>
                      set(
                        f.key,
                        chosen.filter((c) => c !== id),
                      )
                    }
                  >
                    ✕
                  </Button>
                </li>
              ))}
            </ul>
            {chosen.length < 6 && rest.length > 0 && (
              <Select
                aria-label={t('widgetOptions.addInstrument')}
                value=""
                onChange={(e) => e.target.value && set(f.key, [...chosen, Number(e.target.value)])}
              >
                <option value="">{t('widgetOptions.addInstrument')}</option>
                {rest.map((i) => (
                  <option key={i.id} value={i.id}>
                    {i.name}
                  </option>
                ))}
              </Select>
            )}
          </fieldset>
        )
      }
      case 'longtext':
        return (
          <Field key={f.key} label={label} hint={t('widgetOptions.markdownHint')}>
            {(p) => (
              <Textarea
                rows={6}
                value={String(value ?? '')}
                onChange={(e) => set(f.key, e.target.value)}
                {...p}
              />
            )}
          </Field>
        )
      default:
        return (
          <Field key={f.key} label={label}>
            {(p) => (
              <Select
                value={value === null || value === undefined ? '' : String(value)}
                onChange={(e) => set(f.key, e.target.value ? Number(e.target.value) : null)}
                {...p}
              >
                <option value="">{t('widgetOptions.choose')}</option>
                {instruments.data?.map((i) => (
                  <option key={i.id} value={i.id}>
                    {i.name}
                  </option>
                ))}
              </Select>
            )}
          </Field>
        )
    }
  }

  const numberBox = (key: 'x' | 'y' | 'w' | 'h', label: string) =>
    place && (
      <Field label={label}>
        {(p) => (
          <Input
            type="number"
            min={key === 'w' || key === 'h' ? 1 : 0}
            value={place[key]}
            onChange={(e) => setPlace({ ...place, [key]: Number(e.target.value) })}
            {...p}
          />
        )}
      </Field>
    )

  return (
    <Dialog
      open
      onClose={onClose}
      title={t('dashboard.configureTitle', { name: widgetTitle(t, widget) })}
      wide
    >
      <div className="grid gap-5 lg:grid-cols-[minmax(0,18rem)_minmax(0,1fr)]">
        <form
          className="space-y-3"
          onSubmit={(e) => {
            e.preventDefault()
            onSave(draft, fitted(place, box, COLS[breakpoint]))
          }}
        >
          <Field label={t('widgetOptions.title')}>
            {(p) => (
              <Input
                value={String(draft.title ?? '')}
                placeholder={t(`widgets.${widget.type}`)}
                onChange={(e) => set('title', e.target.value || null)}
                {...p}
              />
            )}
          </Field>
          {def.scopes.length > 1 && (
            <div className="grid grid-cols-2 gap-2">
              <Field label={t('widgetOptions.scope')}>
                {(p) => (
                  <Select
                    value={scope.kind}
                    onChange={(e) => set('scope', { kind: e.target.value, id: null })}
                    {...p}
                  >
                    {def.scopes.map((s) => (
                      <option key={s} value={s}>
                        {t(`widgetOptions.scopes.${s}`)}
                      </option>
                    ))}
                  </Select>
                )}
              </Field>
              {scope.kind !== 'portfolio' && (
                <Field label={t('widgetOptions.which')}>
                  {(p) => (
                    <Select
                      value={scope.id ?? ''}
                      onChange={(e) =>
                        set('scope', {
                          kind: scope.kind,
                          id: e.target.value ? Number(e.target.value) : null,
                        })
                      }
                      {...p}
                    >
                      <option value="">{t('widgetOptions.choose')}</option>
                      {scope.kind === 'account' &&
                        accounts.data?.map((a) => (
                          <option key={a.id} value={a.id}>
                            {a.name}
                          </option>
                        ))}
                      {scope.kind === 'sleeve' &&
                        sleeves.data?.map((s) => (
                          <option key={s.id} value={s.id}>
                            {s.name}
                          </option>
                        ))}
                      {scope.kind === 'instrument' &&
                        instruments.data?.map((i) => (
                          <option key={i.id} value={i.id}>
                            {i.name}
                          </option>
                        ))}
                    </Select>
                  )}
                </Field>
              )}
            </div>
          )}
          {def.period && (
            <Field label={t('widgetOptions.period')}>
              {(p) => (
                <Select
                  value={String(draft.period ?? '')}
                  onChange={(e) => set('period', e.target.value || null)}
                  {...p}
                >
                  <option value="">{t('widgetOptions.followDashboard')}</option>
                  {PERIODS.map((x) => (
                    <option key={x} value={x}>
                      {t(`overview.periods.${x}`)}
                    </option>
                  ))}
                </Select>
              )}
            </Field>
          )}
          <Checkbox
            label={t('widgetOptions.followFilters')}
            checked={draft.follow_filters !== false}
            onChange={(e) => set('follow_filters', e.target.checked)}
          />
          {def.fields.map(field)}
          {place && (
            <fieldset className="space-y-2 rounded border border-border p-2">
              <legend className="px-1 text-sm font-medium">
                {t('widgetOptions.position', {
                  breakpoint: t(`dashboard.breakpoints.${breakpoint}`),
                })}
              </legend>
              <div className="grid grid-cols-2 gap-2">
                {numberBox('x', t('widgetOptions.column'))}
                {numberBox('y', t('widgetOptions.row'))}
                {numberBox('w', t('widgetOptions.width'))}
                {numberBox('h', t('widgetOptions.height'))}
              </div>
            </fieldset>
          )}
          {error !== undefined && error !== null && <Alert>{errorMessage(error)}</Alert>}
          <div className="flex gap-2">
            <Button type="submit" disabled={saving}>
              {t('app.save')}
            </Button>
            <Button variant="secondary" onClick={onClose}>
              {t('app.cancel')}
            </Button>
          </div>
        </form>
        <div
          className="min-h-64 min-w-0 rounded-lg border border-border p-3"
          aria-label={t('widgetOptions.preview')}
        >
          <p className="mb-2 text-xs text-muted">{t('widgetOptions.preview')}</p>
          {/* A chart fills the room its widget has, so the preview needs a height of its own:
              left to size itself it would grow for ever. */}
          <div className={def.chart ? 'h-80 overflow-auto' : undefined} data-testid="preview-body">
            <WidgetBody
              widget={{ id: widget.id, type: widget.type, config: preview }}
              result={query.data?.preview}
              filters={filters}
              loading={query.isLoading}
            />
          </div>
        </div>
      </div>
    </Dialog>
  )
}
