import { useTranslation } from 'react-i18next'
import { Button, Checkbox, Field, Input, Select, Textarea } from '../components/ui'
import type { Definition } from './api'

type Obj = Record<string, unknown>
const SEVERITIES = ['info', 'low', 'medium', 'high', 'critical'] as const
const COMMON = new Set(['id', 'type', 'severity', 'cooldown_days', 'worsen_step', 'enabled'])

/** A starting set of parameters per rule type, so a new rule is valid as soon as it is added. */
export const RULE_TEMPLATES: Record<string, Obj> = {
  drift_band: { applies_to: 'all' },
  trim_threshold: { applies_to: 'all' },
  drawdown: { scope: 'position', threshold_pct: '20' },
  price_move: { applies_to: 'all', pct: '5', sigma: null, window_days: 60 },
  price_level: { instrument: '', above: null, below: null },
  macro_threshold: { series: '', change_bp: '50', window_days: 30, applies_to: [] },
  correlation_shift: { hedge: '', against: [], window_days: 90, above: '0.5' },
  contribution_due: { days_before: 3 },
  cash_buffer: {},
  thesis_review_due: { days_before: 0 },
  stale_data: {},
  concentration_limit: { dimension: 'company', limit_pct: null },
}

const list = (v: unknown) =>
  Array.isArray(v) ? v.join(', ') : v === 'all' ? 'all' : String(v ?? '')
const toList = (text: string): string[] =>
  text
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean)
const text = (v: unknown) => (v === null || v === undefined ? '' : String(v))
const orNull = (s: string) => (s.trim() === '' ? null : s.trim())

/** The strategy as a form: sleeves, rules, principles, theses and the contribution plan. It
 * edits the same definition the YAML view shows; the server turns it into YAML on save. */
export function FormEditor({
  value,
  onChange,
}: {
  value: Definition
  onChange: (next: Definition) => void
}) {
  const { t } = useTranslation()
  const set = (key: string, v: unknown) => onChange({ ...value, [key]: v })
  const sleeves = (value.sleeves as Obj[] | undefined) ?? []
  const rules = (value.rules as Obj[] | undefined) ?? []
  const theses = (value.theses as Obj[] | undefined) ?? []
  const plan = (value.contribution_plan as Obj | null | undefined) ?? null
  const principles = (value.principles as string[] | undefined) ?? []

  const setSleeve = (i: number, key: string, v: unknown) =>
    set(
      'sleeves',
      sleeves.map((s, n) => (n === i ? { ...s, [key]: v } : s)),
    )
  const setRule = (i: number, key: string, v: unknown) =>
    set(
      'rules',
      rules.map((r, n) => (n === i ? { ...r, [key]: v } : r)),
    )
  const setThesis = (i: number, key: string, v: unknown) =>
    set(
      'theses',
      theses.map((r, n) => (n === i ? { ...r, [key]: v } : r)),
    )

  return (
    <div className="space-y-6">
      <Field label={t('strategies.form.name')}>
        {(p) => (
          <Input value={text(value.name)} onChange={(e) => set('name', e.target.value)} {...p} />
        )}
      </Field>

      <section className="space-y-2">
        <h3 className="font-medium">{t('strategies.form.sleeves')}</h3>
        <p className="text-sm text-muted">{t('strategies.form.sleevesHint')}</p>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[44rem] text-sm">
            <caption className="sr-only">{t('strategies.form.sleeves')}</caption>
            <thead>
              <tr className="border-b border-border text-left">
                {(['id', 'members', 'target', 'soft', 'hard', 'trim'] as const).map((c) => (
                  <th key={c} scope="col" className="py-1 pr-2 font-medium">
                    {t(`strategies.form.columns.${c}`)}
                  </th>
                ))}
                <th scope="col" className="sr-only">
                  {t('strategies.form.remove')}
                </th>
              </tr>
            </thead>
            <tbody>
              {sleeves.map((s, i) => (
                <tr key={i} className="border-b border-border">
                  <td className="py-1 pr-2">
                    <Input
                      aria-label={t('strategies.form.sleeveId', { n: i + 1 })}
                      value={text(s.id)}
                      onChange={(e) => setSleeve(i, 'id', e.target.value)}
                    />
                  </td>
                  <td className="py-1 pr-2">
                    <Input
                      aria-label={t('strategies.form.sleeveMembers', { n: i + 1 })}
                      value={list(s.members)}
                      onChange={(e) => setSleeve(i, 'members', toList(e.target.value))}
                    />
                  </td>
                  {(
                    ['target_pct', 'soft_band_pp', 'hard_band_pp', 'trim_threshold_pct'] as const
                  ).map((k) => (
                    <td key={k} className="w-24 py-1 pr-2">
                      <Input
                        aria-label={t(`strategies.form.fields.${k}`, { n: i + 1 })}
                        inputMode="decimal"
                        value={text(s[k])}
                        onChange={(e) => setSleeve(i, k, orNull(e.target.value))}
                      />
                    </td>
                  ))}
                  <td className="py-1">
                    <Button
                      type="button"
                      variant="ghost"
                      aria-label={t('strategies.form.removeSleeve', { n: i + 1 })}
                      onClick={() =>
                        set(
                          'sleeves',
                          sleeves.filter((_, n) => n !== i),
                        )
                      }
                    >
                      ✕
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <Button
          type="button"
          variant="ghost"
          onClick={() =>
            set('sleeves', [
              ...sleeves,
              { id: '', members: [], target_pct: null, soft_band_pp: null, hard_band_pp: null },
            ])
          }
        >
          {t('strategies.form.addSleeve')}
        </Button>
      </section>

      <section className="space-y-3">
        <h3 className="font-medium">{t('strategies.form.rules')}</h3>
        {rules.map((r, i) => (
          <div
            key={i}
            role="group"
            aria-label={t('strategies.form.rule', { id: text(r.id) || i + 1 })}
            className="space-y-2 rounded-md border border-border p-3"
          >
            <span className="inline-block rounded bg-border/40 px-2 py-1 text-xs font-medium">
              {t(`strategies.ruleTypes.${text(r.type)}`, { defaultValue: text(r.type) })}
            </span>
            <div className="flex flex-wrap items-end gap-2">
              <Field label={t('strategies.form.ruleId')}>
                {(p) => (
                  <Input
                    className="w-32"
                    value={text(r.id)}
                    onChange={(e) => setRule(i, 'id', e.target.value)}
                    {...p}
                  />
                )}
              </Field>
              <Field label={t('strategies.form.severity')}>
                {(p) => (
                  <Select
                    value={text(r.severity) || 'medium'}
                    onChange={(e) => setRule(i, 'severity', e.target.value)}
                    {...p}
                  >
                    {SEVERITIES.map((s) => (
                      <option key={s} value={s}>
                        {t(`strategies.severity.${s}`)}
                      </option>
                    ))}
                  </Select>
                )}
              </Field>
              <Field label={t('strategies.form.cooldown')}>
                {(p) => (
                  <Input
                    className="w-20"
                    inputMode="numeric"
                    value={text(r.cooldown_days ?? 7)}
                    onChange={(e) => setRule(i, 'cooldown_days', Number(e.target.value) || 0)}
                    {...p}
                  />
                )}
              </Field>
              <Field label={t('strategies.form.worsen')}>
                {(p) => (
                  <Input
                    className="w-20"
                    inputMode="decimal"
                    value={text(r.worsen_step)}
                    onChange={(e) => setRule(i, 'worsen_step', orNull(e.target.value))}
                    {...p}
                  />
                )}
              </Field>
              <Checkbox
                label={t('strategies.form.enabled')}
                checked={r.enabled !== false}
                onChange={(e) => setRule(i, 'enabled', e.target.checked)}
              />
              <Button
                type="button"
                variant="ghost"
                onClick={() =>
                  set(
                    'rules',
                    rules.filter((_, n) => n !== i),
                  )
                }
              >
                {t('strategies.form.remove')}
              </Button>
            </div>
            <div className="flex flex-wrap gap-2">
              {Object.entries(r)
                .filter(([k]) => !COMMON.has(k))
                .map(([k, v]) => (
                  <Field key={k} label={k}>
                    {(p) => (
                      <Input
                        className="w-40"
                        value={Array.isArray(v) ? v.join(', ') : text(v)}
                        onChange={(e) =>
                          setRule(
                            i,
                            k,
                            Array.isArray(v) ? toList(e.target.value) : orNull(e.target.value),
                          )
                        }
                        {...p}
                      />
                    )}
                  </Field>
                ))}
            </div>
          </div>
        ))}
        <AddRule
          onAdd={(type) =>
            set('rules', [
              ...rules,
              {
                id: `${type}_${rules.length + 1}`,
                type,
                severity: 'medium',
                cooldown_days: 7,
                ...RULE_TEMPLATES[type],
              },
            ])
          }
        />
      </section>

      <Field label={t('strategies.form.principles')} hint={t('strategies.form.principlesHint')}>
        {(p) => (
          <Textarea
            rows={4}
            value={principles.join('\n')}
            onChange={(e) =>
              set(
                'principles',
                e.target.value.split('\n').filter((l) => l.trim()),
              )
            }
            {...p}
          />
        )}
      </Field>

      <section className="space-y-2">
        <h3 className="font-medium">{t('strategies.form.theses')}</h3>
        {theses.map((th, i) => (
          <div key={i} className="flex flex-wrap items-end gap-2">
            <Field label={t('strategies.form.thesisSleeve')}>
              {(p) => (
                <Input
                  className="w-32"
                  value={text(th.sleeve)}
                  onChange={(e) => setThesis(i, 'sleeve', orNull(e.target.value))}
                  {...p}
                />
              )}
            </Field>
            <Field label={t('strategies.form.thesisWhy')}>
              {(p) => (
                <Input
                  className="w-72"
                  value={text(th.why)}
                  onChange={(e) => setThesis(i, 'why', orNull(e.target.value))}
                  {...p}
                />
              )}
            </Field>
            <Field label={t('strategies.form.thesisEvery')}>
              {(p) => (
                <Input
                  className="w-24"
                  inputMode="numeric"
                  value={text(th.review_every_days)}
                  onChange={(e) =>
                    setThesis(
                      i,
                      'review_every_days',
                      e.target.value ? Number(e.target.value) : null,
                    )
                  }
                  {...p}
                />
              )}
            </Field>
            <Button
              type="button"
              variant="ghost"
              onClick={() =>
                set(
                  'theses',
                  theses.filter((_, n) => n !== i),
                )
              }
            >
              {t('strategies.form.remove')}
            </Button>
          </div>
        ))}
        <Button
          type="button"
          variant="ghost"
          onClick={() =>
            set('theses', [...theses, { sleeve: null, why: null, review_every_days: 90 }])
          }
        >
          {t('strategies.form.addThesis')}
        </Button>
      </section>

      <section className="space-y-2">
        <h3 className="font-medium">{t('strategies.form.plan')}</h3>
        <div className="flex flex-wrap items-end gap-2">
          <Field label={t('strategies.form.planAmount')}>
            {(p) => (
              <Input
                className="w-32"
                inputMode="decimal"
                value={text(plan?.amount_eur)}
                onChange={(e) =>
                  set('contribution_plan', { ...(plan ?? {}), amount_eur: orNull(e.target.value) })
                }
                {...p}
              />
            )}
          </Field>
          <Field label={t('strategies.form.planCadence')}>
            {(p) => (
              <Select
                value={text(plan?.cadence)}
                onChange={(e) =>
                  set('contribution_plan', { ...(plan ?? {}), cadence: e.target.value || null })
                }
                {...p}
              >
                <option value="">{t('strategies.form.none')}</option>
                {(['weekly', 'monthly', 'quarterly'] as const).map((c) => (
                  <option key={c} value={c}>
                    {t(`strategies.form.cadence.${c}`)}
                  </option>
                ))}
              </Select>
            )}
          </Field>
          <Field label={t('strategies.form.planNext')}>
            {(p) => (
              <Input
                type="date"
                value={text(plan?.next_date)}
                onChange={(e) =>
                  set('contribution_plan', { ...(plan ?? {}), next_date: e.target.value || null })
                }
                {...p}
              />
            )}
          </Field>
        </div>
      </section>
    </div>
  )
}

function AddRule({ onAdd }: { onAdd: (type: string) => void }) {
  const { t } = useTranslation()
  return (
    <form
      className="flex flex-wrap items-end gap-2"
      onSubmit={(e) => {
        e.preventDefault()
        const type = new FormData(e.currentTarget).get('type')
        if (typeof type === 'string' && type) onAdd(type)
      }}
    >
      <Field label={t('strategies.form.ruleType')}>
        {(p) => (
          <Select name="type" defaultValue="drift_band" {...p}>
            {Object.keys(RULE_TEMPLATES).map((type) => (
              <option key={type} value={type}>
                {t(`strategies.ruleTypes.${type}`)}
              </option>
            ))}
          </Select>
        )}
      </Field>
      <Button type="submit" variant="ghost">
        {t('strategies.form.addRule')}
      </Button>
    </form>
  )
}
