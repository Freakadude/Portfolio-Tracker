import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { api, errorMessage, unwrap } from '../api/client'
import { useInstruments, useInvalidateLedger } from '../api/queries'
import { Link } from 'react-router-dom'
import { useSleeves } from '../dashboards/api'
import { Dialog, EmptyState } from './display'
import { TypeBadge } from './AssetType'
import { Alert, Button, Checkbox, Field, Input } from './ui'

type Sleeve = {
  id: number
  name: string
  target_pct: string | null
  band_pct: string | null
  instrument_count: number
  managed_by?: string | null
}

/** Sleeves group instruments for strategies and drift. A target and a band are optional: until
 * a target is set a sleeve shows no drift (owner decision Q3). */
export function SleevesTab() {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const invalidate = useInvalidateLedger()
  const sleeves = useSleeves()
  const [editing, setEditing] = useState<Sleeve | 'new' | null>(null)
  const refresh = async () => {
    await queryClient.invalidateQueries({ queryKey: ['sleeves'] })
    await invalidate()
  }
  const remove = useMutation({
    mutationFn: (id: number) =>
      unwrap(api.DELETE('/api/v1/sleeves/{sleeve_id}', { params: { path: { sleeve_id: id } } })),
    onSuccess: refresh,
  })
  const move = useMutation({
    mutationFn: (ids: number[]) => unwrap(api.PUT('/api/v1/sleeves/order', { body: { ids } })),
    onSuccess: refresh,
  })
  const rows: Sleeve[] = sleeves.data ?? []
  const managedBy = rows.find((r) => r.managed_by)?.managed_by ?? null
  const total = rows.reduce((sum, s) => sum + (s.target_pct ? Number(s.target_pct) : 0), 0)

  function shift(index: number, step: -1 | 1) {
    const ids = rows.map((r) => r.id)
    const to = index + step
    if (to < 0 || to >= ids.length) return
    const moved = ids[index]
    ids[index] = ids[to]
    ids[to] = moved
    move.mutate(ids)
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">{t('sleeves.title')}</h2>
        <Button onClick={() => setEditing('new')}>{t('sleeves.add')}</Button>
      </div>
      <p className="text-sm text-muted">{t('sleeves.intro')}</p>
      {managedBy && (
        <p role="note" className="rounded-md border border-border p-2 text-sm">
          {t('sleeves.managed', { name: managedBy })}{' '}
          <Link to="/strategies" className="underline">
            {t('sleeves.openStrategy')}
          </Link>
        </p>
      )}
      {sleeves.isError && <Alert>{errorMessage(sleeves.error)}</Alert>}
      {remove.isError && <Alert>{errorMessage(remove.error)}</Alert>}
      {move.isError && <Alert>{errorMessage(move.error)}</Alert>}
      {sleeves.isPending ? (
        <p role="status">{t('app.loading')}</p>
      ) : rows.length === 0 ? (
        <EmptyState title={t('sleeves.empty.title')} body={t('sleeves.empty.body')} />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <caption className="sr-only">{t('sleeves.caption')}</caption>
            <thead>
              <tr className="border-b border-border text-left">
                <th scope="col" className="py-2 pr-3 font-medium">
                  {t('sleeves.name')}
                </th>
                <th scope="col" className="py-2 pr-3 text-right font-medium">
                  {t('sleeves.target')}
                </th>
                <th scope="col" className="py-2 pr-3 text-right font-medium">
                  {t('sleeves.band')}
                </th>
                <th scope="col" className="py-2 pr-3 text-right font-medium">
                  {t('sleeves.instruments')}
                </th>
                <th scope="col" className="py-2 font-medium">
                  {t('sleeves.actions')}
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((s, i) => (
                <tr key={s.id} className="border-b border-border">
                  <td className="py-2 pr-3">{s.name}</td>
                  <td className="py-2 pr-3 text-right tabular-nums">
                    {s.target_pct ? `${s.target_pct} %` : '–'}
                  </td>
                  <td className="py-2 pr-3 text-right tabular-nums">
                    {s.band_pct ? `± ${s.band_pct} pp` : '–'}
                  </td>
                  <td className="py-2 pr-3 text-right tabular-nums">{s.instrument_count}</td>
                  <td className="py-2 whitespace-nowrap">
                    <Button variant="ghost" onClick={() => setEditing(s)}>
                      {t('sleeves.edit')}
                    </Button>
                    <Button
                      variant="ghost"
                      onClick={() => shift(i, -1)}
                      disabled={i === 0}
                      aria-label={t('sleeves.moveUp', { name: s.name })}
                    >
                      ↑
                    </Button>
                    <Button
                      variant="ghost"
                      onClick={() => shift(i, 1)}
                      disabled={i === rows.length - 1}
                      aria-label={t('sleeves.moveDown', { name: s.name })}
                    >
                      ↓
                    </Button>
                    <Button
                      variant="ghost"
                      onClick={() => {
                        if (window.confirm(t('sleeves.deleteConfirm', { name: s.name })))
                          remove.mutate(s.id)
                      }}
                    >
                      {t('sleeves.delete')}
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {total > 100 && <Alert>{t('sleeves.over', { total })}</Alert>}
      {editing && (
        <Dialog
          open
          onClose={() => setEditing(null)}
          title={
            editing === 'new'
              ? t('sleeves.addTitle')
              : t('sleeves.editTitle', { name: editing.name })
          }
        >
          <SleeveForm
            sleeve={editing === 'new' ? null : editing}
            managedBy={managedBy}
            onDone={async () => {
              await refresh()
              setEditing(null)
            }}
          />
        </Dialog>
      )}
    </div>
  )
}

function SleeveForm({
  sleeve,
  onDone,
  managedBy,
}: {
  sleeve: Sleeve | null
  onDone: () => void
  managedBy: string | null
}) {
  const { t } = useTranslation()
  const [name, setName] = useState(sleeve?.name ?? '')
  const [target, setTarget] = useState(sleeve?.target_pct ?? '')
  const [band, setBand] = useState(sleeve?.band_pct ?? '')
  const [nameError, setNameError] = useState<string>()
  const instruments = useInstruments()
  const sleeves = useSleeves()
  const sleeveNames = new Map((sleeves.data ?? []).map((x) => [x.id, x.name]))
  // the instruments in this sleeve; None until the list has loaded so nothing is changed blind
  const [members, setMembers] = useState<Set<number> | null>(null)
  const chosen =
    members ??
    new Set(
      (instruments.data ?? []).filter((i) => sleeve && i.sleeve_id === sleeve.id).map((i) => i.id),
    )
  const save = useMutation({
    mutationFn: async () => {
      // while a strategy is active it sets targets and bands; only the name is ours to change
      const body = managedBy
        ? { name: name.trim() }
        : {
            name: name.trim(),
            target_pct: target.trim() === '' ? null : target.trim(),
            band_pct: band.trim() === '' ? null : band.trim(),
          }
      const saved = sleeve
        ? await unwrap(
            api.PATCH('/api/v1/sleeves/{sleeve_id}', {
              params: { path: { sleeve_id: sleeve.id } },
              body,
            }),
          )
        : await unwrap(api.POST('/api/v1/sleeves', { body }))
      // put the chosen instruments in this sleeve, and take out the ones that were unticked
      for (const i of instruments.data ?? []) {
        const wanted = chosen.has(i.id)
        const now = i.sleeve_id === saved.id
        if (wanted === now) continue
        await unwrap(
          api.PATCH('/api/v1/instruments/{instrument_id}', {
            params: { path: { instrument_id: i.id } },
            body: { sleeve_id: wanted ? saved.id : null },
          }),
        )
      }
      return saved
    },
    onSuccess: onDone,
  })
  function submit(e: FormEvent) {
    e.preventDefault()
    if (!name.trim()) return setNameError(t('sleeves.required'))
    save.mutate()
  }
  return (
    <form onSubmit={submit} className="space-y-4" noValidate>
      <Field label={t('sleeves.name')} error={nameError}>
        {(p) => (
          <Input
            value={name}
            onChange={(e) => {
              setName(e.target.value)
              setNameError(undefined)
            }}
            {...p}
          />
        )}
      </Field>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label={t('sleeves.targetLabel')} hint={t('sleeves.targetHint')}>
          {(p) => (
            <Input
              value={target}
              inputMode="decimal"
              disabled={Boolean(managedBy)}
              onChange={(e) => setTarget(e.target.value)}
              {...p}
            />
          )}
        </Field>
        <Field label={t('sleeves.bandLabel')} hint={t('sleeves.bandHint')}>
          {(p) => (
            <Input
              value={band}
              inputMode="decimal"
              disabled={Boolean(managedBy)}
              onChange={(e) => setBand(e.target.value)}
              {...p}
            />
          )}
        </Field>
      </div>
      <fieldset className="space-y-1">
        <legend className="text-sm font-medium">{t('sleeves.members')}</legend>
        <p className="text-xs text-muted">{t('sleeves.membersHint')}</p>
        <div className="max-h-56 space-y-1 overflow-auto rounded-md border border-border p-2">
          {(instruments.data ?? []).map((i) => {
            const elsewhere =
              i.sleeve_id && i.sleeve_id !== sleeve?.id ? sleeveNames.get(i.sleeve_id) : null
            return (
              <div key={i.id} className="flex flex-wrap items-center gap-2">
                <Checkbox
                  label={i.name}
                  checked={chosen.has(i.id)}
                  onChange={(e) => {
                    const next = new Set(chosen)
                    if (e.target.checked) next.add(i.id)
                    else next.delete(i.id)
                    setMembers(next)
                  }}
                />
                <TypeBadge assetClass={i.asset_class} />
                {elsewhere && chosen.has(i.id) && (
                  <span className="text-xs text-muted">
                    {t('sleeves.moveFrom', { name: elsewhere })}
                  </span>
                )}
                {elsewhere && !chosen.has(i.id) && (
                  <span className="text-xs text-muted">
                    {t('sleeves.inOther', { name: elsewhere })}
                  </span>
                )}
              </div>
            )
          })}
          {instruments.data?.length === 0 && (
            <p className="text-sm text-muted">{t('sleeves.noInstruments')}</p>
          )}
        </div>
        {managedBy && (
          <p className="text-xs text-muted">{t('sleeves.membersManaged', { name: managedBy })}</p>
        )}
      </fieldset>
      {save.isError && <Alert>{errorMessage(save.error)}</Alert>}
      <Button type="submit" disabled={save.isPending}>
        {t('sleeves.save')}
      </Button>
    </form>
  )
}
