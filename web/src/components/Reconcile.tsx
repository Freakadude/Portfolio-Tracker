import { useMutation } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { api, errorMessage, unwrap } from '../api/client'
import { useAccounts } from '../api/queries'
import { Badge, Dialog } from './display'
import { Alert, Button, Field, Input, Select, Textarea } from './ui'
import { useFormat } from '../lib/useFormat'

const ISIN = /^[A-Z]{2}[A-Z0-9]{9}[0-9]$/i

export interface BrokerRow {
  isin: string
  quantity: string
}

/** Read what was pasted from the broker: one holding per line, an ISIN and a quantity separated
 * by a tab, semicolon, comma or spaces. Returns the rows and the lines it could not read. */
export function parseBrokerRows(text: string): { rows: BrokerRow[]; unreadable: string[] } {
  const rows: BrokerRow[] = []
  const unreadable: string[] = []
  for (const raw of text.split(/\r?\n/)) {
    const line = raw.trim()
    if (!line) continue
    const parts = line.split(/[\t;]+|\s{2,}|\s+/).filter(Boolean)
    const isin = parts.find((p) => ISIN.test(p))
    // the quantity is the last field that is a plain number, whatever the broker puts between
    const quantity = [...parts].reverse().find((p) => /^\d+([.,]\d+)?$/.test(p) && p !== isin)
    if (!isin || quantity === undefined) {
      unreadable.push(line)
      continue
    }
    rows.push({ isin: isin.toUpperCase(), quantity: quantity.replace(',', '.') })
  }
  return { rows, unreadable }
}

/** Compare the quantities your broker reports with the ledger (FR-TX-10). Nothing is saved. */
export function Reconcile({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { t } = useTranslation()
  return (
    <Dialog open={open} onClose={onClose} title={t('reconcile.title')} wide>
      <ReconcileForm />
    </Dialog>
  )
}

function ReconcileForm() {
  const { t } = useTranslation()
  const { qty } = useFormat()
  const accounts = useAccounts()
  const [account, setAccount] = useState('')
  const [date, setDate] = useState(() => new Date().toISOString().slice(0, 10))
  const [text, setText] = useState('')
  const [problems, setProblems] = useState<string[]>([])
  const accountId = account || String(accounts.data?.[0]?.id ?? '')

  const run = useMutation({
    mutationFn: (rows: BrokerRow[]) =>
      unwrap(
        api.POST('/api/v1/transactions/reconcile', {
          body: {
            account_id: Number(accountId),
            date,
            rows: rows.map((r) => ({ isin: r.isin, quantity: r.quantity })),
          },
        }),
      ),
  })

  function submit(e: FormEvent) {
    e.preventDefault()
    const { rows, unreadable } = parseBrokerRows(text)
    const found = unreadable.map((line) => t('reconcile.unreadable', { line }))
    if (rows.length === 0) found.unshift(t('reconcile.nothing'))
    setProblems(found)
    if (rows.length > 0 && accountId) run.mutate(rows)
  }

  const result = run.data
  return (
    <div className="space-y-4">
      <form onSubmit={submit} className="space-y-4" noValidate>
        <p className="text-sm text-muted">{t('reconcile.intro')}</p>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label={t('reconcile.account')}>
            {(p) => (
              <Select value={accountId} onChange={(e) => setAccount(e.target.value)} {...p}>
                {accounts.data?.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.name}
                  </option>
                ))}
              </Select>
            )}
          </Field>
          <Field label={t('reconcile.date')}>
            {(p) => (
              <Input type="date" value={date} onChange={(e) => setDate(e.target.value)} {...p} />
            )}
          </Field>
        </div>
        <Field label={t('reconcile.paste')} hint={t('reconcile.pasteHint')}>
          {(p) => (
            <Textarea
              rows={6}
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder={'IE00DEMO0001\t12\nIE00DEMO0002\t5'}
              {...p}
            />
          )}
        </Field>
        {problems.length > 0 && (
          <Alert>
            {problems.map((m) => (
              <span key={m} className="block">
                {m}
              </span>
            ))}
          </Alert>
        )}
        {run.isError && <Alert>{errorMessage(run.error)}</Alert>}
        <Button type="submit" disabled={run.isPending}>
          {t('reconcile.run')}
        </Button>
      </form>

      {result && (
        <section aria-label={t('reconcile.result')} className="space-y-3">
          <p role="status" className="font-medium">
            {result.differences === 0
              ? t('reconcile.allMatch', { count: result.matches })
              : t('reconcile.someDiffer', { count: result.differences, matches: result.matches })}
          </p>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <caption className="sr-only">{t('reconcile.result')}</caption>
              <thead>
                <tr className="border-b border-border text-left">
                  <th scope="col" className="py-2 pr-3 font-medium">
                    {t('reconcile.columns.instrument')}
                  </th>
                  <th scope="col" className="py-2 pr-3 text-right font-medium">
                    {t('reconcile.columns.ours')}
                  </th>
                  <th scope="col" className="py-2 pr-3 text-right font-medium">
                    {t('reconcile.columns.broker')}
                  </th>
                  <th scope="col" className="py-2 pr-3 text-right font-medium">
                    {t('reconcile.columns.difference')}
                  </th>
                  <th scope="col" className="py-2 font-medium">
                    {t('reconcile.columns.status')}
                  </th>
                </tr>
              </thead>
              <tbody>
                {result.lines.map((line) => (
                  <tr
                    key={`${line.instrument_id}:${line.isin}:${line.name}`}
                    className="border-b border-border"
                  >
                    <td className="py-2 pr-3">
                      {line.name}
                      {line.isin && <div className="text-xs text-muted">{line.isin}</div>}
                    </td>
                    <td className="py-2 pr-3 text-right tabular-nums">{qty(line.ours)}</td>
                    <td className="py-2 pr-3 text-right tabular-nums">{qty(line.broker)}</td>
                    <td className="py-2 pr-3 text-right tabular-nums">
                      {line.status === 'match' ? '–' : qty(line.difference)}
                    </td>
                    <td className="py-2">
                      <Badge tone={line.status === 'match' ? 'good' : 'warn'}>
                        {t(`reconcile.status.${line.status}`, { defaultValue: line.status })}
                      </Badge>
                      {line.status === 'difference' && line.instrument_id !== null && (
                        <Link
                          className="ml-2 text-xs underline"
                          to={`/transactions?instrument=${line.instrument_id}`}
                        >
                          {t('reconcile.showTransactions')}
                        </Link>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </div>
  )
}
