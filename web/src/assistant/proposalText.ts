import type { Definition, Problem } from '../strategies/api'

/** The strategy YAML in what Claude answered: the last fenced block that holds a `strategy:`
 * document (a chat may show an early draft and then the final one), else the only fenced block,
 * else the whole text as pasted. */
export function extractYaml(text: string): string {
  const blocks = [...text.matchAll(/```(?:ya?ml)?[ \t]*\r?\n([\s\S]*?)```/gi)].map((m) => m[1])
  const documents = blocks.filter((b) => /^\s*strategy\s*:/m.test(b))
  if (documents.length > 0) return documents[documents.length - 1].trim()
  if (blocks.length === 1) return blocks[0].trim()
  return text.trim()
}

/** What to paste back to Claude when Folio found problems in its document. */
export function problemsText(problems: Problem[]): string {
  const lines = problems.map(
    (p) =>
      `- ${p.line ? `line ${p.line}` : 'the document'}${p.path ? ` (${p.path})` : ''}: ${p.message}`,
  )
  return (
    'Folio checked the strategy and found these problems:\n' +
    `${lines.join('\n')}\n` +
    'Please fix them and give the whole document again in one yaml code block.'
  )
}

export type Line = { key: string; params?: Record<string, string | number> }

type Obj = Record<string, unknown>
const obj = (v: unknown): Obj => (v && typeof v === 'object' && !Array.isArray(v) ? (v as Obj) : {})
const list = (v: unknown): unknown[] => (Array.isArray(v) ? v : [])
const text = (v: unknown): string | null =>
  v === null || v === undefined || v === '' ? null : String(v)
const pct = (v: unknown): string | null => {
  const s = text(v)
  if (s === null) return null
  const n = Number(s)
  return Number.isFinite(n) ? String(Number(n.toFixed(2))) : s
}

/** A strategy in plain sentences, as translation keys with their values, so the owner can see
 * what a proposal means before saving it. */
export function describeDefinition(definition: Definition): Line[] {
  const strategy = obj(definition.strategy ?? definition)
  const out: Line[] = [{ key: 'name', params: { name: text(strategy.name) ?? '' } }]
  const sleeves = list(strategy.sleeves).map(obj)
  for (const s of sleeves) {
    const target = pct(s.target_pct)
    const soft = pct(s.soft_band_pp)
    const hard = pct(s.hard_band_pp)
    const trim = pct(s.trim_threshold_pct)
    out.push({
      key: target === null ? 'sleeveNoTarget' : 'sleeve',
      params: { name: text(s.id) ?? '', target: target ?? '', n: list(s.members).length },
    })
    if (soft !== null || hard !== null) {
      out.push({
        key: 'bands',
        params: { name: text(s.id) ?? '', soft: soft ?? '–', hard: hard ?? '–' },
      })
    }
    if (trim !== null) out.push({ key: 'trim', params: { name: text(s.id) ?? '', trim } })
  }
  const company = pct(obj(strategy.risk_limits).max_single_company_lookthrough_pct)
  if (company !== null) out.push({ key: 'company', params: { pct: company } })
  for (const r of list(strategy.rules).map(obj)) {
    if (r.enabled === false) continue
    const type = text(r.type) ?? 'unknown'
    const kind = type === 'drawdown' ? `drawdown_${text(r.scope) ?? 'position'}` : type
    out.push({
      key: `rule.${kind}`,
      params: {
        threshold: pct(r.threshold_pct) ?? '',
        series: text(r.series) ?? '',
        type,
        limit: pct(r.limit_pct) ?? '',
        days: text(r.days_before) ?? '',
      },
    })
  }
  const plan = obj(strategy.contribution_plan)
  if (text(plan.amount_eur) !== null) {
    out.push({
      key: 'plan',
      params: {
        amount: text(plan.amount_eur) ?? '',
        cadence: text(plan.cadence) ?? '',
        next: text(plan.next_date) ?? '–',
      },
    })
  }
  const principles = list(strategy.principles).length
  if (principles > 0) out.push({ key: 'principles', params: { n: principles } })
  const theses = list(strategy.theses).length
  if (theses > 0) out.push({ key: 'theses', params: { n: theses } })
  return out
}
