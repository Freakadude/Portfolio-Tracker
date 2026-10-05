import { useMutation } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { api, errorMessage, unwrap } from '../api/client'
import { useAccounts, useInvalidateLedger, type Account } from '../api/queries'
import { Badge, Dialog } from './display'
import { Alert, Button, Checkbox, Field, Input, Select } from './ui'

type Method = 'FIFO' | 'AVG'

export function AccountsTab() {
  const { t } = useTranslation()
  const accounts = useAccounts()
  const invalidate = useInvalidateLedger()
  const [editing, setEditing] = useState<Account | 'new' | null>(null)

  const patch = useMutation({
    mutationFn: ({ id, body }: { id: number; body: { active?: boolean } }) =>
      unwrap(
        api.PATCH('/api/v1/accounts/{account_id}', { params: { path: { account_id: id } }, body }),
      ),
    onSuccess: invalidate,
  })
  const remove = useMutation({
    mutationFn: (id: number) =>
      unwrap(api.DELETE('/api/v1/accounts/{account_id}', { params: { path: { account_id: id } } })),
    onSuccess: invalidate,
  })

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">{t('accounts.title')}</h2>
        <Button onClick={() => setEditing('new')}>{t('accounts.add')}</Button>
      </div>
      {accounts.isError && <Alert>{errorMessage(accounts.error)}</Alert>}
      {patch.isError && <Alert>{errorMessage(patch.error)}</Alert>}
      {remove.isError && <Alert>{errorMessage(remove.error)}</Alert>}
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <caption className="sr-only">{t('accounts.caption')}</caption>
          <thead>
            <tr className="border-b border-border text-left">
              {(['name', 'broker', 'method', 'transactions', 'actions'] as const).map((c) => (
                <th key={c} scope="col" className="py-2 pr-3 font-medium">
                  {t(`accounts.columns.${c}`)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {accounts.data?.map((a) => (
              <tr key={a.id} className="border-b border-border">
                <td className="py-2 pr-3">
                  {a.name} {!a.active && <Badge>{t('accounts.inactive')}</Badge>}
                </td>
                <td className="py-2 pr-3">{a.broker ?? '–'}</td>
                <td className="py-2 pr-3">
                  {t(`accounts.methods.${a.cost_basis_method}`, {
                    defaultValue: a.cost_basis_method,
                  })}
                </td>
                <td className="py-2 pr-3 tabular-nums">{a.transaction_count}</td>
                <td className="py-2 whitespace-nowrap">
                  <Button variant="ghost" onClick={() => setEditing(a)}>
                    {t('accounts.edit')}
                  </Button>
                  <Button
                    variant="ghost"
                    onClick={() => patch.mutate({ id: a.id, body: { active: !a.active } })}
                  >
                    {t(a.active ? 'accounts.archive' : 'accounts.unarchive')}
                  </Button>
                  <Button
                    variant="ghost"
                    onClick={() => {
                      if (window.confirm(t('accounts.deleteConfirm', { name: a.name })))
                        remove.mutate(a.id)
                    }}
                  >
                    {t('accounts.delete')}
                  </Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {editing && (
        <Dialog
          open
          onClose={() => setEditing(null)}
          title={
            editing === 'new'
              ? t('accounts.addTitle')
              : t('accounts.editTitle', { name: editing.name })
          }
        >
          <AccountForm
            account={editing === 'new' ? null : editing}
            onDone={() => setEditing(null)}
          />
        </Dialog>
      )}
    </div>
  )
}

function AccountForm({ account, onDone }: { account: Account | null; onDone: () => void }) {
  const { t } = useTranslation()
  const invalidate = useInvalidateLedger()
  const [name, setName] = useState(account?.name ?? '')
  const [broker, setBroker] = useState(account?.broker ?? '')
  const [method, setMethod] = useState<Method>((account?.cost_basis_method as Method) ?? 'FIFO')
  const [trackCash, setTrackCash] = useState(account?.track_cash ?? false)
  const [nameError, setNameError] = useState<string>()

  const save = useMutation({
    mutationFn: () => {
      if (!account) {
        return unwrap(
          api.POST('/api/v1/accounts', {
            body: {
              name: name.trim(),
              broker: broker.trim() || null,
              cost_basis_method: method,
              track_cash: trackCash,
            },
          }),
        )
      }
      const body: {
        name?: string
        broker?: string | null
        cost_basis_method?: Method
        track_cash?: boolean
      } = {}
      if (name.trim() !== account.name) body.name = name.trim()
      if ((broker.trim() || null) !== account.broker) body.broker = broker.trim() || null
      if (method !== account.cost_basis_method) body.cost_basis_method = method
      if (trackCash !== account.track_cash) body.track_cash = trackCash
      return unwrap(
        api.PATCH('/api/v1/accounts/{account_id}', {
          params: { path: { account_id: account.id } },
          body,
        }),
      )
    },
    onSuccess: async () => {
      await invalidate()
      onDone()
    },
  })

  function submit(e: FormEvent) {
    e.preventDefault()
    if (!name.trim()) return setNameError(t('accounts.required'))
    // a method switch recomputes everything, so the owner confirms it first
    if (account && method !== account.cost_basis_method && account.transaction_count > 0) {
      if (!window.confirm(t('accounts.switchWarning', { method: t(`accounts.methods.${method}`) })))
        return
    }
    if (account && trackCash !== account.track_cash && account.transaction_count > 0) {
      if (!window.confirm(t('accounts.cashWarning'))) return
    }
    save.mutate()
  }

  return (
    <form onSubmit={submit} className="space-y-4" noValidate>
      <Field label={t('accounts.name')} error={nameError}>
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
      <Field label={t('accounts.broker')}>
        {(p) => <Input value={broker} onChange={(e) => setBroker(e.target.value)} {...p} />}
      </Field>
      <Field label={t('accounts.method')} hint={t('accounts.methodHint')}>
        {(p) => (
          <Select value={method} onChange={(e) => setMethod(e.target.value as Method)} {...p}>
            <option value="FIFO">{t('accounts.methods.FIFO')}</option>
            <option value="AVG">{t('accounts.methods.AVG')}</option>
          </Select>
        )}
      </Field>
      <div className="space-y-1">
        <Checkbox
          label={t('accounts.trackCash')}
          checked={trackCash}
          onChange={(e) => setTrackCash(e.target.checked)}
        />
        <p className="text-sm text-muted">{t('accounts.trackCashHint')}</p>
      </div>
      {save.isError && <Alert>{errorMessage(save.error)}</Alert>}
      <Button type="submit" disabled={save.isPending}>
        {t('accounts.save')}
      </Button>
    </form>
  )
}
