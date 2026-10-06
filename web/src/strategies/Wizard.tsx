import { useMutation } from '@tanstack/react-query'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api, errorMessage, unwrap } from '../api/client'
import { useInstruments, usePositions } from '../api/queries'
import { Alert, Button, Checkbox, Field, Input, Select, Textarea } from '../components/ui'
import { useSleeves } from '../dashboards/api'
import { problemsOf, useCheck, useInvalidateStrategies, type Problem } from './api'
import {
  PRINCIPLES,
  STRICTNESS,
  blankAnswers,
  buildDefinition,
  currentMix,
  targetTotal,
  targetsAddUp,
  targetsFromMix,
  type Answers,
  type Holding,
  type Strictness,
} from './wizardLogic'

const STEPS = [
  'name',
  'groups',
  'targets',
  'strictness',
  'alerts',
  'plan',
  'principles',
  'review',
] as const
type Step = (typeof STEPS)[number]

const pct = (n: number) => `${Math.round(n * 10) / 10} %`

/** The guided setup (FR-ST-01): a few plain questions that become an ordinary strategy, which
 * then opens in the editor. It only asks; the server checks and stores like any other save. */
export function Wizard({
  onDone,
  onCancel,
}: {
  onDone: (id: number) => void
  onCancel: () => void
}) {
  const { t } = useTranslation()
  const positions = usePositions({ groupByIsin: true })
  const instruments = useInstruments()
  const sleeves = useSleeves()
  const check = useCheck()
  const invalidate = useInvalidateStrategies()
  const [a, setA] = useState<Answers>(blankAnswers)
  const [step, setStep] = useState<Step>('name')
  const [problems, setProblems] = useState<Problem[]>([])
  const [activate, setActivate] = useState(false)
  const seeded = useRef(false)

  const holdings: Holding[] = useMemo(
    () =>
      (positions.data?.positions ?? [])
        .filter((p) => p.isin)
        .map((p) => ({
          key: p.isin as string,
          name: p.name,
          weightPct: Number(p.weight ?? 0) * 100,
        })),
    [positions.data],
  )
  const noIsin = (positions.data?.positions ?? []).filter((p) => !p.isin).length

  // start from the groups (sleeves) already in use
  useEffect(() => {
    if (seeded.current || !positions.data || !instruments.data || !sleeves.data) return
    seeded.current = true
    const names = new Map(sleeves.data.map((s) => [s.id, s.name]))
    const assignment: Record<string, string> = {}
    for (const i of instruments.data) {
      const group = i.sleeve_id ? names.get(i.sleeve_id) : undefined
      if (group && i.isin && holdings.some((h) => h.key === i.isin)) assignment[i.isin] = group
    }
    const groups = [...new Set(Object.values(assignment))].map((name) => ({ name, target: '' }))
    setA((prev) => ({ ...prev, assignment, groups }))
  }, [positions.data, instruments.data, sleeves.data, holdings])

  const set = (patch: Partial<Answers>) => setA((prev) => ({ ...prev, ...patch }))
  const mix = currentMix(holdings, a.assignment)
  const unassigned = holdings.filter((h) => !a.assignment[h.key])
  const definition = useMemo(() => buildDefinition(a), [a])
  const total = targetTotal(a.groups)

  const index = STEPS.indexOf(step)
  const blocked =
    (step === 'name' && !a.name.trim()) ||
    (step === 'groups' && (a.groups.length === 0 || a.groups.some((g) => !g.name.trim()))) ||
    (step === 'targets' && !targetsAddUp(a.groups)) ||
    (step === 'plan' && a.plan !== null && !(Number(a.plan.amount) > 0))

  const go = (to: Step) => {
    setProblems([])
    setStep(to)
    if (to === 'review') {
      check.mutate({ definition }, { onSuccess: (r) => setProblems(r.ok ? [] : r.problems) })
    }
  }

  const save = useMutation({
    mutationFn: async () => {
      const created = await unwrap(
        api.POST('/api/v1/strategies', { body: { definition, note: 'guided setup' } }),
      )
      if (activate) {
        await unwrap(
          api.POST('/api/v1/strategies/{strategy_id}/mode', {
            params: { path: { strategy_id: created.id } },
            body: { mode: 'active' },
          }),
        )
      }
      return created
    },
    onSuccess: async (created) => {
      await invalidate()
      onDone(created.id)
    },
    onError: (error) => setProblems(problemsOf(error)),
  })

  if (positions.isPending || instruments.isPending || sleeves.isPending) {
    return <p role="status">{t('app.loading')}</p>
  }

  const renameGroup = (i: number, name: string) => {
    const old = a.groups[i].name
    set({
      groups: a.groups.map((g, n) => (n === i ? { ...g, name } : g)),
      assignment: Object.fromEntries(
        Object.entries(a.assignment).map(([k, v]) => [k, v === old ? name : v]),
      ),
    })
  }

  return (
    <section aria-label={t('strategies.wizard.title')} className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-xl font-semibold">{t('strategies.wizard.title')}</h2>
        <span className="text-sm text-muted">
          {t('strategies.wizard.step', { n: index + 1, of: STEPS.length })}
        </span>
      </div>
      <h3 className="font-medium">{t(`strategies.wizard.${step}.title`)}</h3>
      <p className="text-sm text-muted">{t(`strategies.wizard.${step}.intro`)}</p>

      {step === 'name' && (
        <Field label={t('strategies.wizard.name.label')}>
          {(p) => <Input value={a.name} onChange={(e) => set({ name: e.target.value })} {...p} />}
        </Field>
      )}

      {step === 'groups' && (
        <div className="space-y-3">
          <div className="space-y-2">
            {a.groups.map((g, i) => (
              <div key={i} className="flex items-end gap-2">
                <Field label={t('strategies.wizard.groups.groupName', { n: i + 1 })}>
                  {(p) => (
                    <Input value={g.name} onChange={(e) => renameGroup(i, e.target.value)} {...p} />
                  )}
                </Field>
                <Button
                  type="button"
                  variant="ghost"
                  onClick={() =>
                    set({
                      groups: a.groups.filter((_, n) => n !== i),
                      assignment: Object.fromEntries(
                        Object.entries(a.assignment).filter(([, v]) => v !== g.name),
                      ),
                    })
                  }
                >
                  {t('strategies.wizard.groups.remove')}
                </Button>
              </div>
            ))}
            <Button
              type="button"
              variant="secondary"
              onClick={() =>
                set({
                  groups: [
                    ...a.groups,
                    {
                      name: t('strategies.wizard.groups.newName', { n: a.groups.length + 1 }),
                      target: '',
                    },
                  ],
                })
              }
            >
              {t('strategies.wizard.groups.add')}
            </Button>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <caption className="sr-only">{t('strategies.wizard.groups.caption')}</caption>
              <thead>
                <tr className="border-b border-border text-left">
                  <th scope="col" className="py-1 pr-3 font-medium">
                    {t('strategies.wizard.groups.holding')}
                  </th>
                  <th scope="col" className="py-1 pr-3 font-medium">
                    {t('strategies.wizard.groups.share')}
                  </th>
                  <th scope="col" className="py-1 font-medium">
                    {t('strategies.wizard.groups.group')}
                  </th>
                </tr>
              </thead>
              <tbody>
                {holdings.map((h) => (
                  <tr key={h.key} className="border-b border-border">
                    <td className="py-1 pr-3">{h.name}</td>
                    <td className="py-1 pr-3 tabular-nums">{pct(h.weightPct)}</td>
                    <td className="py-1">
                      <Select
                        aria-label={t('strategies.wizard.groups.groupOf', { name: h.name })}
                        value={a.assignment[h.key] ?? ''}
                        onChange={(e) => {
                          const next = { ...a.assignment }
                          if (e.target.value) next[h.key] = e.target.value
                          else delete next[h.key]
                          set({ assignment: next })
                        }}
                      >
                        <option value="">{t('strategies.wizard.groups.none')}</option>
                        {a.groups.map((g, i) => (
                          <option key={i} value={g.name}>
                            {g.name}
                          </option>
                        ))}
                      </Select>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {holdings.length === 0 && (
            <p className="text-sm text-muted">{t('strategies.wizard.groups.noHoldings')}</p>
          )}
          {noIsin > 0 && (
            <p className="text-sm text-muted">
              {t('strategies.wizard.groups.noIsin', { count: noIsin })}
            </p>
          )}
          {unassigned.length > 0 && a.groups.length > 0 && (
            <p className="text-sm text-muted">
              {t('strategies.wizard.groups.unassigned', {
                names: unassigned.map((h) => h.name).join(', '),
              })}
            </p>
          )}
        </div>
      )}

      {step === 'targets' && (
        <div className="space-y-3">
          <table className="w-full text-sm">
            <caption className="sr-only">{t('strategies.wizard.targets.title')}</caption>
            <thead>
              <tr className="border-b border-border text-left">
                <th scope="col" className="py-1 pr-3 font-medium">
                  {t('strategies.wizard.targets.group')}
                </th>
                <th scope="col" className="py-1 pr-3 font-medium">
                  {t('strategies.wizard.targets.today')}
                </th>
                <th scope="col" className="py-1 font-medium">
                  {t('strategies.wizard.targets.target')}
                </th>
              </tr>
            </thead>
            <tbody>
              {a.groups.map((g, i) => (
                <tr key={i} className="border-b border-border">
                  <td className="py-1 pr-3">{g.name}</td>
                  <td className="py-1 pr-3 tabular-nums">{pct(mix[g.name] ?? 0)}</td>
                  <td className="py-1">
                    <Input
                      className="w-24"
                      inputMode="decimal"
                      aria-label={t('strategies.wizard.targets.targetOf', { name: g.name })}
                      value={g.target}
                      onChange={(e) =>
                        set({
                          groups: a.groups.map((x, n) =>
                            n === i ? { ...x, target: e.target.value } : x,
                          ),
                        })
                      }
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="flex flex-wrap items-center gap-3">
            <Button
              type="button"
              variant="secondary"
              onClick={() => {
                const next = targetsFromMix(
                  mix,
                  a.groups.map((g) => g.name),
                )
                set({ groups: a.groups.map((g) => ({ ...g, target: next[g.name] ?? g.target })) })
              }}
            >
              {t('strategies.wizard.targets.useToday')}
            </Button>
            <span
              role="status"
              className={targetsAddUp(a.groups) ? 'text-sm' : 'text-sm text-danger'}
            >
              {t('strategies.wizard.targets.total', {
                total: total === null ? '?' : String(total / 100),
              })}
            </span>
          </div>
        </div>
      )}

      {step === 'strictness' && (
        <fieldset className="space-y-2">
          <legend className="sr-only">{t('strategies.wizard.strictness.title')}</legend>
          {(Object.keys(STRICTNESS) as Strictness[]).map((s) => (
            <label key={s} className="flex items-start gap-2 text-sm">
              <input
                type="radio"
                name="strictness"
                className="mt-1"
                checked={a.strictness === s}
                onChange={() => set({ strictness: s })}
              />
              <span>
                <span className="font-medium">{t(`strategies.wizard.strictness.${s}`)}</span>
                <span className="block text-muted">
                  {t('strategies.wizard.strictness.detail', STRICTNESS[s])}
                </span>
              </span>
            </label>
          ))}
        </fieldset>
      )}

      {step === 'alerts' && (
        <div className="space-y-3">
          <Checkbox
            label={t('strategies.wizard.alerts.drift')}
            checked={a.drift}
            onChange={(e) => set({ drift: e.target.checked })}
          />
          <div className="flex flex-wrap items-end gap-3">
            <Checkbox
              label={t('strategies.wizard.alerts.trim')}
              checked={a.trim}
              onChange={(e) => set({ trim: e.target.checked })}
            />
            {a.trim && (
              <Field label={t('strategies.wizard.alerts.trimOver')}>
                {(p) => (
                  <Input
                    className="w-20"
                    inputMode="decimal"
                    value={a.trimOver}
                    onChange={(e) => set({ trimOver: e.target.value })}
                    {...p}
                  />
                )}
              </Field>
            )}
          </div>
          <div className="flex flex-wrap items-end gap-3">
            <Checkbox
              label={t('strategies.wizard.alerts.drawdown')}
              checked={a.drawdown}
              onChange={(e) => set({ drawdown: e.target.checked })}
            />
            {a.drawdown && (
              <Field label={t('strategies.wizard.alerts.drawdownPct')}>
                {(p) => (
                  <Input
                    className="w-20"
                    inputMode="decimal"
                    value={a.drawdownPct}
                    onChange={(e) => set({ drawdownPct: e.target.value })}
                    {...p}
                  />
                )}
              </Field>
            )}
          </div>
          <Checkbox
            label={t('strategies.wizard.alerts.stale')}
            checked={a.stale}
            onChange={(e) => set({ stale: e.target.checked })}
          />
          <div className="flex flex-wrap items-end gap-3">
            <Checkbox
              label={t('strategies.wizard.alerts.concentration')}
              checked={a.concentration}
              onChange={(e) => set({ concentration: e.target.checked })}
            />
            {a.concentration && (
              <Field label={t('strategies.wizard.alerts.concentrationPct')}>
                {(p) => (
                  <Input
                    className="w-20"
                    inputMode="decimal"
                    value={a.concentrationPct}
                    onChange={(e) => set({ concentrationPct: e.target.value })}
                    {...p}
                  />
                )}
              </Field>
            )}
          </div>
          <p className="text-sm text-muted">{t('strategies.wizard.alerts.more')}</p>
        </div>
      )}

      {step === 'plan' && (
        <div className="space-y-3">
          <Checkbox
            label={t('strategies.wizard.plan.use')}
            checked={a.plan !== null}
            onChange={(e) =>
              set({ plan: e.target.checked ? { amount: '', cadence: 'monthly', next: '' } : null })
            }
          />
          {a.plan && (
            <div className="flex flex-wrap items-end gap-2">
              <Field label={t('strategies.wizard.plan.amount')}>
                {(p) => (
                  <Input
                    className="w-32"
                    inputMode="decimal"
                    value={a.plan?.amount ?? ''}
                    onChange={(e) => set({ plan: { ...a.plan!, amount: e.target.value } })}
                    {...p}
                  />
                )}
              </Field>
              <Field label={t('strategies.wizard.plan.cadence')}>
                {(p) => (
                  <Select
                    value={a.plan?.cadence}
                    onChange={(e) =>
                      set({
                        plan: {
                          ...a.plan!,
                          cadence: e.target.value as 'weekly' | 'monthly' | 'quarterly',
                        },
                      })
                    }
                    {...p}
                  >
                    {(['weekly', 'monthly', 'quarterly'] as const).map((c) => (
                      <option key={c} value={c}>
                        {t(`strategies.form.cadence.${c}`)}
                      </option>
                    ))}
                  </Select>
                )}
              </Field>
              <Field label={t('strategies.wizard.plan.next')}>
                {(p) => (
                  <Input
                    type="date"
                    value={a.plan?.next ?? ''}
                    onChange={(e) => set({ plan: { ...a.plan!, next: e.target.value } })}
                    {...p}
                  />
                )}
              </Field>
            </div>
          )}
        </div>
      )}

      {step === 'principles' && (
        <div className="space-y-3">
          {PRINCIPLES.map((text, i) => (
            <Checkbox
              key={i}
              label={text}
              checked={a.principles[i]}
              onChange={(e) =>
                set({ principles: a.principles.map((v, n) => (n === i ? e.target.checked : v)) })
              }
            />
          ))}
          <Field
            label={t('strategies.wizard.principles.own')}
            hint={t('strategies.wizard.principles.ownHint')}
          >
            {(p) => (
              <Textarea
                rows={3}
                value={a.ownPrinciples}
                onChange={(e) => set({ ownPrinciples: e.target.value })}
                {...p}
              />
            )}
          </Field>
        </div>
      )}

      {step === 'review' && (
        <div className="space-y-3">
          <ul className="list-disc space-y-1 pl-5 text-sm">
            {a.groups.map((g) => (
              <li key={g.name}>
                {t('strategies.wizard.review.group', {
                  name: g.name,
                  target: g.target,
                  count: (definition.sleeves as { id: string; members: string[] }[]).find(
                    (s) => s.id === g.name,
                  )?.members.length,
                  soft: STRICTNESS[a.strictness].soft,
                })}
              </li>
            ))}
            {a.drift && (
              <li>
                {t('strategies.wizard.review.drift', { hard: STRICTNESS[a.strictness].hard })}
              </li>
            )}
            {a.trim && <li>{t('strategies.wizard.review.trim', { over: a.trimOver })}</li>}
            {a.drawdown && (
              <li>{t('strategies.wizard.review.drawdown', { pct: a.drawdownPct })}</li>
            )}
            {a.stale && <li>{t('strategies.wizard.review.stale')}</li>}
            {a.concentration && (
              <li>{t('strategies.wizard.review.concentration', { pct: a.concentrationPct })}</li>
            )}
            {a.plan && (
              <li>
                {t('strategies.wizard.review.plan', {
                  amount: a.plan.amount,
                  cadence: t(`strategies.form.cadence.${a.plan.cadence}`).toLowerCase(),
                })}
              </li>
            )}
          </ul>
          {problems.length > 0 && (
            <Alert>
              {problems.map((p) => (p.path ? `${p.path}: ${p.message}` : p.message)).join(' ')}
            </Alert>
          )}
          <fieldset className="space-y-2">
            <legend className="sr-only">{t('strategies.wizard.review.saveAs')}</legend>
            <label className="flex items-start gap-2 text-sm">
              <input
                type="radio"
                name="activate"
                className="mt-1"
                checked={!activate}
                onChange={() => setActivate(false)}
              />
              <span>{t('strategies.wizard.review.off')}</span>
            </label>
            <label className="flex items-start gap-2 text-sm">
              <input
                type="radio"
                name="activate"
                className="mt-1"
                checked={activate}
                onChange={() => setActivate(true)}
              />
              <span>{t('strategies.wizard.review.active')}</span>
            </label>
          </fieldset>
        </div>
      )}

      {save.isError && problems.length === 0 && <Alert>{errorMessage(save.error)}</Alert>}
      <div className="flex flex-wrap gap-2">
        <Button type="button" variant="ghost" onClick={onCancel}>
          {t('strategies.wizard.cancel')}
        </Button>
        {index > 0 && (
          <Button type="button" variant="secondary" onClick={() => go(STEPS[index - 1])}>
            {t('strategies.wizard.back')}
          </Button>
        )}
        {step !== 'review' ? (
          <Button type="button" onClick={() => go(STEPS[index + 1])} disabled={blocked}>
            {step === 'plan' && a.plan === null
              ? t('strategies.wizard.skip')
              : t('strategies.wizard.next')}
          </Button>
        ) : (
          <Button
            type="button"
            onClick={() => save.mutate()}
            disabled={save.isPending || check.isPending || problems.length > 0}
          >
            {t('strategies.wizard.save')}
          </Button>
        )}
      </div>
    </section>
  )
}
