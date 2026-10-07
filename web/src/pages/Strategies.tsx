import { useMutation } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useSearchParams } from 'react-router-dom'
import { api, errorMessage, unwrap } from '../api/client'
import { useInvalidateLedger } from '../api/queries'
import { Badge, EmptyState } from '../components/display'
import { Alert, Button, Field, Input, Select } from '../components/ui'
import { cn } from '../lib/cn'
import { useFormat } from '../lib/useFormat'
import {
  problemsOf,
  useCheck,
  useDiff,
  useInvalidateStrategies,
  useSignals,
  useStatus,
  useStrategies,
  useStrategy,
  type Definition,
  type Plan,
  type Problem,
  type Strategy,
} from '../strategies/api'
import { Backtest } from '../strategies/Backtest'
import { FormEditor } from '../strategies/FormEditor'
import { Wizard } from '../strategies/Wizard'
import { YamlEditor } from '../strategies/YamlEditor'
import { JobStatus } from '../system/JobStatus'

type Tab = 'editor' | 'rules' | 'calculators' | 'backtest' | 'history'
const TABS: Tab[] = ['editor', 'rules', 'calculators', 'backtest', 'history']

const MODE_TONE = { active: 'good', shadow: 'warn', off: 'neutral' } as const

/** Strategies (FR-ST-01 to FR-ST-05): write them as a form or as YAML, keep every version,
 * make one active (others can shadow it), see what the rules say, and run the calculators. */
export function Strategies() {
  const { t } = useTranslation()
  const [params, setParams] = useSearchParams()
  const list = useStrategies()
  const invalidate = useInvalidateStrategies()
  const guided = params.get('guided') === '1'
  const selected = params.get('id') ? Number(params.get('id')) : (list.data?.[0]?.id ?? null)
  const create = useMutation({
    mutationFn: async () => {
      const starter = await unwrap(api.GET('/api/v1/strategies/starter'))
      return unwrap(
        api.POST('/api/v1/strategies', { body: { yaml: starter.yaml, note: 'starter' } }),
      )
    },
    onSuccess: async (created) => {
      await invalidate()
      setParams({ id: String(created.id) })
    },
  })

  if (list.isPending) return <p role="status">{t('app.loading')}</p>
  if (list.isError) return <Alert>{errorMessage(list.error)}</Alert>

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-2xl font-semibold">{t('nav.strategies')}</h1>
        <div className="flex items-center gap-3">
          <Link to="/strategies/review" className="text-sm hover:underline">
            {t('strategyReview.link')}
          </Link>
          <Link to="/strategies/assistant" className="text-sm hover:underline">
            {t('assistant.link')}
          </Link>
          <Button variant="secondary" onClick={() => setParams({ guided: '1' })} disabled={guided}>
            {t('strategies.wizard.start')}
          </Button>
          <Button onClick={() => create.mutate()} disabled={create.isPending}>
            {t('strategies.new')}
          </Button>
        </div>
      </div>
      {create.isError && <Alert>{errorMessage(create.error)}</Alert>}
      {(params.get('made') === '1' || params.get('made') === 'helper') && (
        <p role="status" className="text-sm text-muted">
          {t(params.get('made') === 'helper' ? 'assistant.madeWith' : 'strategies.wizard.madeWith')}
        </p>
      )}
      {guided ? (
        <Wizard
          onDone={(id) => setParams({ id: String(id), made: '1' })}
          onCancel={() => setParams({})}
        />
      ) : list.data.length === 0 ? (
        <EmptyState title={t('strategies.empty.title')} body={t('strategies.empty.body')} />
      ) : (
        <>
          <nav aria-label={t('strategies.list')} className="flex flex-wrap gap-2">
            {list.data.map((s) => (
              <button
                key={s.id}
                type="button"
                aria-current={s.id === selected ? 'page' : undefined}
                onClick={() => setParams({ id: String(s.id) })}
                className={cn(
                  'flex items-center gap-2 rounded-md border px-3 py-2 text-sm',
                  s.id === selected ? 'border-primary' : 'border-border hover:bg-border/40',
                )}
              >
                {s.name}
                <Badge tone={MODE_TONE[s.mode as keyof typeof MODE_TONE] ?? 'neutral'}>
                  {t(`strategies.modes.${s.mode}`)}
                </Badge>
              </button>
            ))}
          </nav>
          {selected !== null && <StrategyView key={selected} id={selected} />}
        </>
      )}
    </div>
  )
}

function StrategyView({ id }: { id: number }) {
  const { t } = useTranslation()
  const strategy = useStrategy(id)
  const [tab, setTab] = useState<Tab>('editor')
  const invalidate = useInvalidateStrategies()
  const mode = useMutation({
    mutationFn: (next: 'active' | 'shadow' | 'off') =>
      unwrap(
        api.POST('/api/v1/strategies/{strategy_id}/mode', {
          params: { path: { strategy_id: id } },
          body: { mode: next },
        }),
      ),
    onSuccess: invalidate,
  })
  const run = useMutation({ mutationFn: () => unwrap(api.POST('/api/v1/strategies/run')) })
  const [, setParams] = useSearchParams()
  const remove = useMutation({
    mutationFn: () =>
      unwrap(
        api.DELETE('/api/v1/strategies/{strategy_id}', { params: { path: { strategy_id: id } } }),
      ),
    onSuccess: async () => {
      await invalidate()
      setParams({})
    },
  })

  if (strategy.isPending) return <p role="status">{t('app.loading')}</p>
  if (strategy.isError) return <Alert>{errorMessage(strategy.error)}</Alert>
  const s = strategy.data

  return (
    <section aria-label={s.name} className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="text-xl font-semibold">{s.name}</h2>
        <span className="text-sm text-muted">
          {t('strategies.version', { version: s.current.version })}
        </span>
        <div
          className="ml-auto flex flex-wrap gap-2"
          role="group"
          aria-label={t('strategies.mode')}
        >
          {(['active', 'shadow', 'off'] as const).map((m) => (
            <Button
              key={m}
              variant={s.mode === m ? 'primary' : 'secondary'}
              aria-pressed={s.mode === m}
              onClick={() => mode.mutate(m)}
              disabled={mode.isPending}
            >
              {s.mode === m ? t(`strategies.modes.${m}`) : t(`strategies.setMode.${m}`)}
            </Button>
          ))}
          <Button variant="ghost" onClick={() => run.mutate()} disabled={run.isPending}>
            {t('strategies.runNow')}
          </Button>
          <Button
            variant="ghost"
            disabled={remove.isPending}
            onClick={() => {
              if (window.confirm(t('strategies.deleteConfirm', { name: s.name }))) remove.mutate()
            }}
          >
            {t('strategies.delete')}
          </Button>
        </div>
      </div>
      <p className="text-sm text-muted">{t(`strategies.modeHint.${s.mode}`)}</p>
      <JobStatus jobs={['rules']} from={run} />
      {mode.isError && <Alert>{errorMessage(mode.error)}</Alert>}
      {remove.isError && <Alert>{errorMessage(remove.error)}</Alert>}

      <div role="tablist" aria-label={s.name} className="flex flex-wrap gap-1">
        {TABS.map((x) => (
          <button
            key={x}
            role="tab"
            aria-selected={tab === x}
            onClick={() => setTab(x)}
            className={cn(
              'rounded-md px-3 py-2 text-sm',
              tab === x ? 'bg-primary text-primary-foreground' : 'hover:bg-border/40',
            )}
          >
            {t(`strategies.tabs.${x}`)}
          </button>
        ))}
      </div>
      <div role="tabpanel">
        {tab === 'editor' && <Editor key={s.current.version} strategy={s} />}
        {tab === 'rules' && <RulesPanel id={id} />}
        {tab === 'calculators' && <Calculators strategy={s} />}
        {tab === 'backtest' && (
          <Backtest
            key={s.current.version}
            id={id}
            ruleIds={((s.current.definition.rules as { id: string }[] | undefined) ?? []).map(
              (r) => r.id,
            )}
          />
        )}
        {tab === 'history' && <History strategy={s} />}
      </div>
    </section>
  )
}

// --- the editor ---------------------------------------------------------------------------------

function Editor({ strategy }: { strategy: Strategy }) {
  const { t } = useTranslation()
  const invalidate = useInvalidateStrategies()
  const check = useCheck()
  const [view, setView] = useState<'form' | 'yaml'>('form')
  const [yaml, setYaml] = useState(strategy.current.yaml)
  const [definition, setDefinition] = useState<Definition>(strategy.current.definition)
  const [problems, setProblems] = useState<Problem[]>([])
  const [note, setNote] = useState('')
  const [dirty, setDirty] = useState(false)
  // the YAML is kept as written (comments, layout) unless the form changed something
  const [formChanged, setFormChanged] = useState(false)

  const save = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST('/api/v1/strategies/{strategy_id}/versions', {
          params: { path: { strategy_id: strategy.id } },
          body:
            view === 'yaml' || !formChanged
              ? { yaml, note: note || null }
              : { definition, note: note || null },
        }),
      ),
    onSuccess: async () => {
      setProblems([])
      setNote('')
      await invalidate()
    },
    onError: (error) => setProblems(problemsOf(error)),
  })

  /** Switching views goes through the server, which validates and converts. */
  async function switchTo(next: 'form' | 'yaml') {
    if (next === view) return
    const result = await check.mutateAsync(view === 'yaml' ? { yaml } : { definition })
    if (!result.ok) {
      setProblems(result.problems)
      return
    }
    setProblems([])
    if (next === 'yaml' && result.yaml && formChanged) setYaml(result.yaml)
    if (next === 'yaml') setFormChanged(false)
    if (next === 'form' && result.definition) setDefinition(result.definition as Definition)
    setView(next)
  }

  return (
    <div className="space-y-4">
      <div role="tablist" aria-label={t('strategies.editor.views')} className="flex gap-1">
        {(['form', 'yaml'] as const).map((v) => (
          <button
            key={v}
            role="tab"
            aria-selected={view === v}
            onClick={() => void switchTo(v)}
            className={cn(
              'rounded-md px-3 py-1 text-sm',
              view === v ? 'bg-border/60 font-medium' : 'hover:bg-border/40',
            )}
          >
            {t(`strategies.editor.${v}View`)}
          </button>
        ))}
      </div>
      {view === 'yaml' ? (
        <YamlEditor
          value={yaml}
          onChange={(text) => {
            setYaml(text)
            setDirty(true)
          }}
          problems={problems}
        />
      ) : (
        <>
          <FormEditor
            value={definition}
            onChange={(next) => {
              setDefinition(next)
              setDirty(true)
              setFormChanged(true)
            }}
          />
          {problems.length > 0 && (
            <ul
              role="alert"
              className="space-y-1 rounded-md border border-danger/50 p-2 text-sm text-danger"
            >
              {problems.map((p, i) => (
                <li key={i}>
                  {p.path && <code className="text-xs">{p.path}</code>} {p.message}
                </li>
              ))}
            </ul>
          )}
        </>
      )}
      <div className="flex flex-wrap items-end gap-2">
        <Field label={t('strategies.editor.note')}>
          {(p) => (
            <Input
              className="w-72"
              value={note}
              maxLength={200}
              onChange={(e) => setNote(e.target.value)}
              {...p}
            />
          )}
        </Field>
        <Button onClick={() => save.mutate()} disabled={save.isPending}>
          {t('strategies.editor.save')}
        </Button>
        {dirty && <span className="text-sm text-muted">{t('strategies.editor.unsaved')}</span>}
        {save.isSuccess && !dirty && (
          <span role="status" className="text-sm">
            {t('strategies.editor.saved')}
          </span>
        )}
      </div>
      {save.isError && problems.length === 0 && <Alert>{errorMessage(save.error)}</Alert>}
    </div>
  )
}

// --- rules and signals --------------------------------------------------------------------------

function RulesPanel({ id }: { id: number }) {
  const { t } = useTranslation()
  const { pct } = useFormat()
  const status = useStatus(id)
  const signals = useSignals(id)
  return (
    <div className="space-y-6">
      {status.isError && <Alert>{errorMessage(status.error)}</Alert>}
      {status.data && (
        <>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <caption className="mb-1 text-left font-medium">
                {t('strategies.rules.sleeves')}
              </caption>
              <thead>
                <tr className="border-b border-border text-left">
                  {(['sleeve', 'weight', 'target', 'soft', 'hard'] as const).map((c) => (
                    <th key={c} scope="col" className="py-1 pr-3 font-medium">
                      {t(`strategies.rules.columns.${c}`)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {status.data.sleeves.map((s) => (
                  <tr key={s.id} className="border-b border-border">
                    <td className="py-1 pr-3">{s.id}</td>
                    <td className="py-1 pr-3 tabular-nums">{pct(s.weight, 1)}</td>
                    <td className="py-1 pr-3 tabular-nums">
                      {s.target === null ? '–' : `${s.target}%`}
                    </td>
                    <td className="py-1 pr-3 tabular-nums">
                      {s.soft_band_pp === null ? '–' : `± ${s.soft_band_pp} pp`}
                    </td>
                    <td className="py-1 pr-3 tabular-nums">
                      {s.hard_band_pp === null ? '–' : `± ${s.hard_band_pp} pp`}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <caption className="mb-1 text-left font-medium">
                {t('strategies.rules.title')}
              </caption>
              <thead>
                <tr className="border-b border-border text-left">
                  {(['rule', 'type', 'state'] as const).map((c) => (
                    <th key={c} scope="col" className="py-1 pr-3 font-medium">
                      {t(`strategies.rules.columns.${c}`)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {status.data.rules.map((r) => (
                  <tr key={r.rule_id} className="border-b border-border">
                    <td className="py-1 pr-3">{r.rule_id}</td>
                    <td className="py-1 pr-3">
                      {t(`strategies.ruleTypes.${r.rule_type}`, { defaultValue: r.rule_type })}
                    </td>
                    <td className="py-1 pr-3">
                      {r.ready ? (
                        <Badge tone="good">{t('strategies.rules.ready')}</Badge>
                      ) : (
                        <span className="text-muted">{r.reason}</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="text-sm">
            {t('strategies.rules.trueNow', { count: status.data.conditions_true })}
          </p>
        </>
      )}

      <section className="space-y-2">
        <h3 className="font-medium">{t('strategies.signals.title')}</h3>
        {signals.data?.length === 0 && (
          <p className="text-sm text-muted">{t('strategies.signals.none')}</p>
        )}
        <ul className="space-y-2">
          {signals.data?.map((s) => (
            <li key={s.id} className="rounded-md border border-border p-2 text-sm">
              <div className="flex flex-wrap items-center gap-2">
                <Badge
                  tone={s.severity === 'high' || s.severity === 'critical' ? 'bad' : 'neutral'}
                >
                  {t(`strategies.severity.${s.severity}`, { defaultValue: s.severity })}
                </Badge>
                {s.shadow && <Badge tone="warn">{t('strategies.signals.shadow')}</Badge>}
                <span className="font-medium">{s.title}</span>
                <span className="ml-auto text-xs text-muted">
                  {new Date(s.ts).toLocaleString()}
                </span>
              </div>
              <p className="mt-1 text-muted">{s.message}</p>
            </li>
          ))}
        </ul>
      </section>
    </div>
  )
}

// --- calculators --------------------------------------------------------------------------------

function Calculators({ strategy }: { strategy: Strategy }) {
  const { t } = useTranslation()
  const { eur, qty, pct } = useFormat()
  const invalidate = useInvalidateLedger()
  const sleeves = ((strategy.current.definition.sleeves as { id: string }[] | undefined) ?? []).map(
    (s) => s.id,
  )
  const [kind, setKind] = useState<'allocator' | 'trim' | 'rebalance'>('allocator')
  const [amount, setAmount] = useState('')
  const [sleeve, setSleeve] = useState('')
  const calc = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST('/api/v1/strategies/{strategy_id}/calculate', {
          params: { path: { strategy_id: strategy.id } },
          body: {
            kind,
            amount_eur: kind !== 'trim' && amount.trim() ? amount.trim().replace(',', '.') : null,
            sleeve: kind === 'trim' && sleeve ? sleeve : null,
          },
        }),
      ),
  })
  const drafts = useMutation({
    mutationFn: (plan: Plan) =>
      unwrap(
        api.POST('/api/v1/strategies/orders/to-drafts', {
          body: {
            orders: plan.orders.map((o) => ({
              side: o.side as 'buy' | 'sell',
              instrument_id: o.instrument_id,
              quantity: o.quantity,
              price: o.price,
              account_id: o.account_id,
            })),
            note: t('strategies.calc.draftNote', {
              kind: t(`strategies.calc.kinds.${kind}`),
              name: strategy.name,
            }),
          },
        }),
      ),
    onSuccess: invalidate,
  })
  const plan = calc.data

  return (
    <div className="space-y-4">
      <p className="max-w-2xl text-sm text-muted">{t(`strategies.calc.hint.${kind}`)}</p>
      <form
        className="flex flex-wrap items-end gap-2"
        onSubmit={(e) => {
          e.preventDefault()
          drafts.reset()
          calc.mutate()
        }}
      >
        <Field label={t('strategies.calc.kind')}>
          {(p) => (
            <Select value={kind} onChange={(e) => setKind(e.target.value as typeof kind)} {...p}>
              {(['allocator', 'trim', 'rebalance'] as const).map((k) => (
                <option key={k} value={k}>
                  {t(`strategies.calc.kinds.${k}`)}
                </option>
              ))}
            </Select>
          )}
        </Field>
        {kind !== 'trim' ? (
          <Field label={t('strategies.calc.amount')}>
            {(p) => (
              <Input
                className="w-36"
                inputMode="decimal"
                value={amount}
                onChange={(e) => setAmount(e.target.value)}
                {...p}
              />
            )}
          </Field>
        ) : (
          <Field label={t('strategies.calc.sleeve')}>
            {(p) => (
              <Select value={sleeve} onChange={(e) => setSleeve(e.target.value)} {...p}>
                <option value="">{t('strategies.calc.breached')}</option>
                {sleeves.map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </Select>
            )}
          </Field>
        )}
        <Button type="submit" disabled={calc.isPending}>
          {t('strategies.calc.run')}
        </Button>
      </form>
      {calc.isError && <Alert>{errorMessage(calc.error)}</Alert>}
      {plan && (
        <section aria-label={t('strategies.calc.result')} className="space-y-3">
          {plan.notes.length > 0 && (
            <ul className="list-disc pl-5 text-sm text-muted">
              {plan.notes.map((n) => (
                <li key={n}>{n}</li>
              ))}
            </ul>
          )}
          {plan.orders.length > 0 && (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <caption className="mb-1 text-left font-medium">
                  {t('strategies.calc.orders')}
                </caption>
                <thead>
                  <tr className="border-b border-border text-left">
                    {(
                      [
                        'side',
                        'sleeve',
                        'instrument',
                        'units',
                        'price',
                        'amount',
                        'realized',
                      ] as const
                    ).map((c) => (
                      <th key={c} scope="col" className="py-1 pr-3 font-medium">
                        {t(`strategies.calc.columns.${c}`)}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {plan.orders.map((o, i) => (
                    <tr key={i} className="border-b border-border">
                      <td className="py-1 pr-3">{t(`strategies.calc.sides.${o.side}`)}</td>
                      <td className="py-1 pr-3">{o.sleeve}</td>
                      <td className="py-1 pr-3">{o.name}</td>
                      <td className="py-1 pr-3 tabular-nums">{qty(o.quantity)}</td>
                      <td className="py-1 pr-3 tabular-nums">
                        {o.price} {o.currency}
                      </td>
                      <td className="py-1 pr-3 tabular-nums">{eur(o.amount_eur)}</td>
                      <td className="py-1 pr-3 tabular-nums">
                        {o.realized_pnl_eur === null ? '–' : eur(o.realized_pnl_eur)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <p className="text-sm" role="status">
            {t(kind === 'allocator' ? 'strategies.calc.remainder' : 'strategies.calc.freed', {
              amount: eur(plan.remainder_eur),
            })}
          </p>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <caption className="mb-1 text-left font-medium">
                {t('strategies.calc.weights')}
              </caption>
              <thead>
                <tr className="border-b border-border text-left">
                  {(['sleeve', 'before', 'after'] as const).map((c) => (
                    <th key={c} scope="col" className="py-1 pr-3 font-medium">
                      {t(`strategies.calc.columns.${c}`)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {Object.keys({ ...plan.before, ...plan.after }).map((k) => (
                  <tr key={k} className="border-b border-border">
                    <td className="py-1 pr-3">{k}</td>
                    <td className="py-1 pr-3 tabular-nums">{pct(plan.before[k] ?? '0', 1)}</td>
                    <td className="py-1 pr-3 tabular-nums">{pct(plan.after[k] ?? '0', 1)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {plan.orders.length > 0 && (
            <div className="flex flex-wrap items-center gap-2">
              <Button
                variant="secondary"
                onClick={() => drafts.mutate(plan)}
                disabled={drafts.isPending || drafts.isSuccess}
              >
                {t('strategies.calc.toDrafts')}
              </Button>
              {drafts.isSuccess && (
                <span role="status" className="text-sm">
                  {t('strategies.calc.drafted', { count: drafts.data.transaction_ids.length })}{' '}
                  <Link to="/insights" className="underline">
                    {t('strategies.calc.openInsights')}
                  </Link>
                </span>
              )}
            </div>
          )}
          {drafts.isError && <Alert>{errorMessage(drafts.error)}</Alert>}
        </section>
      )}
    </div>
  )
}

// --- history ------------------------------------------------------------------------------------

function History({ strategy }: { strategy: Strategy }) {
  const { t } = useTranslation()
  const versions = strategy.versions
  const [newer, setNewer] = useState<number | null>(versions[0]?.version ?? null)
  const [older, setOlder] = useState<number | null>(versions[1]?.version ?? null)
  const diff = useDiff(strategy.id, older, newer)
  return (
    <div className="space-y-4">
      <ol className="space-y-1 text-sm">
        {versions.map((v) => (
          <li key={v.version}>
            <span className="font-medium">{t('strategies.version', { version: v.version })}</span>{' '}
            <span className="text-muted">{new Date(v.created_at).toLocaleString()}</span>
            {v.note && <span> · {v.note}</span>}
          </li>
        ))}
      </ol>
      {versions.length < 2 ? (
        <p className="text-sm text-muted">{t('strategies.history.one')}</p>
      ) : (
        <>
          <div className="flex flex-wrap gap-2">
            {(
              [
                ['older', older, setOlder],
                ['newer', newer, setNewer],
              ] as const
            ).map(([label, value, setter]) => (
              <Field key={label} label={t(`strategies.history.${label}`)}>
                {(p) => (
                  <Select
                    value={value ?? ''}
                    onChange={(e) => setter(Number(e.target.value))}
                    {...p}
                  >
                    {versions.map((v) => (
                      <option key={v.version} value={v.version}>
                        {t('strategies.version', { version: v.version })}
                      </option>
                    ))}
                  </Select>
                )}
              </Field>
            ))}
          </div>
          {diff.data && (
            <div className="overflow-x-auto rounded-md border border-border">
              <table className="w-full font-mono text-xs">
                <caption className="sr-only">
                  {t('strategies.history.caption', { older, newer })}
                </caption>
                <tbody>
                  {diff.data.rows.map((r, i) => (
                    <tr
                      key={i}
                      data-kind={r.kind}
                      className={cn(
                        r.kind === 'changed' && 'bg-[var(--diverge-neg)]/10',
                        r.kind === 'removed' && 'bg-danger/10',
                        r.kind === 'added' && 'bg-gain/10',
                      )}
                    >
                      <td className="w-10 select-none px-1 text-right text-muted">
                        {r.old_line ?? ''}
                      </td>
                      <td className="whitespace-pre px-2">{r.old_text ?? ''}</td>
                      <td className="w-10 select-none border-l border-border px-1 text-right text-muted">
                        {r.new_line ?? ''}
                      </td>
                      <td className="whitespace-pre px-2">
                        {r.kind !== 'same' && (
                          <span className="sr-only">
                            {t(`strategies.history.kinds.${r.kind}`)}{' '}
                          </span>
                        )}
                        {r.new_text ?? ''}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </div>
  )
}
