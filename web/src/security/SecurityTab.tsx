import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { api, errorMessage, unwrap } from '../api/client'
import { Alert, Button, Checkbox, Field, Input } from '../components/ui'

const KEY = ['auth', 'totp'] as const

/** The optional second factor (FR-SY-03): an authenticator app's code at sign-in, with recovery
 * codes for a lost phone. */
export function SecurityTab() {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const status = useQuery({
    queryKey: KEY,
    queryFn: () => unwrap(api.GET('/api/v1/auth/totp')),
  })
  const [codes, setCodes] = useState<string[] | null>(null)
  const refresh = () => queryClient.invalidateQueries({ queryKey: KEY })

  if (status.isPending) return <p role="status">{t('app.loading')}</p>
  if (status.isError) return <Alert>{errorMessage(status.error)}</Alert>

  return (
    <div className="space-y-6">
      <section aria-labelledby="sec-title" className="space-y-2">
        <h2 id="sec-title" className="text-lg font-semibold">
          {t('twofactor.title')}
        </h2>
        <p className="text-sm text-muted">{t('twofactor.intro')}</p>
        <p role="status" className="font-medium">
          {status.data.enabled
            ? t('twofactor.on', { count: status.data.recovery_codes_left })
            : t('twofactor.off')}
        </p>
      </section>
      {codes && <RecoveryCodes codes={codes} onDone={() => setCodes(null)} />}
      {!codes && !status.data.enabled && (
        <Setup
          onEnabled={(made) => {
            setCodes(made)
            void refresh()
          }}
        />
      )}
      {!codes && status.data.enabled && (
        <Manage
          onNewCodes={(made) => {
            setCodes(made)
            void refresh()
          }}
          onOff={() => void refresh()}
        />
      )}
    </div>
  )
}

function Setup({ onEnabled }: { onEnabled: (codes: string[]) => void }) {
  const { t } = useTranslation()
  const [code, setCode] = useState('')
  const start = useMutation({ mutationFn: () => unwrap(api.POST('/api/v1/auth/totp/setup')) })
  const enable = useMutation({
    mutationFn: () => unwrap(api.POST('/api/v1/auth/totp/enable', { body: { code } })),
    onSuccess: (done) => onEnabled(done.recovery_codes),
  })
  const setup = start.data

  function submit(e: FormEvent) {
    e.preventDefault()
    enable.mutate()
  }

  if (!setup)
    return (
      <div className="space-y-2">
        <Button onClick={() => start.mutate()} disabled={start.isPending}>
          {t('twofactor.setUp')}
        </Button>
        {start.isError && <Alert>{errorMessage(start.error)}</Alert>}
      </div>
    )
  return (
    <section aria-labelledby="sec-setup" className="space-y-4">
      <h3 id="sec-setup" className="font-medium">
        {t('twofactor.scan')}
      </h3>
      <img
        alt={t('twofactor.qrAlt')}
        src={`data:image/svg+xml;utf8,${encodeURIComponent(setup.qr_svg)}`}
        className="h-48 w-48 rounded-md border border-border bg-white p-1"
      />
      <p className="text-sm">
        {t('twofactor.orType')} <code className="select-all font-mono">{setup.secret}</code>
      </p>
      <form onSubmit={submit} className="space-y-3" aria-label={t('twofactor.confirm')} noValidate>
        <Field label={t('twofactor.codeFromApp')}>
          {(p) => (
            <Input
              inputMode="numeric"
              autoComplete="one-time-code"
              value={code}
              onChange={(e) => setCode(e.target.value)}
              {...p}
            />
          )}
        </Field>
        {enable.isError && <Alert>{errorMessage(enable.error)}</Alert>}
        <Button type="submit" disabled={enable.isPending || code.trim().length < 6}>
          {t('twofactor.turnOn')}
        </Button>
      </form>
    </section>
  )
}

function Manage({
  onNewCodes,
  onOff,
}: {
  onNewCodes: (codes: string[]) => void
  onOff: () => void
}) {
  const { t } = useTranslation()
  const [password, setPassword] = useState('')
  const [code, setCode] = useState('')
  const body = { password, code }
  const off = useMutation({
    mutationFn: () => unwrap(api.POST('/api/v1/auth/totp/disable', { body })),
    onSuccess: onOff,
  })
  const renew = useMutation({
    mutationFn: () => unwrap(api.POST('/api/v1/auth/totp/recovery-codes', { body })),
    onSuccess: (made) => {
      setCode('')
      onNewCodes(made.recovery_codes)
    },
  })
  const ready = password.length > 0 && code.trim().length >= 6
  return (
    <form
      className="space-y-3"
      aria-label={t('twofactor.manage')}
      onSubmit={(e) => e.preventDefault()}
    >
      <p className="text-sm text-muted">{t('twofactor.manageHelp')}</p>
      <Field label={t('login.password')}>
        {(p) => (
          <Input
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            {...p}
          />
        )}
      </Field>
      <Field label={t('twofactor.codeOrRecovery')}>
        {(p) => <Input value={code} onChange={(e) => setCode(e.target.value)} {...p} />}
      </Field>
      {off.isError && <Alert>{errorMessage(off.error)}</Alert>}
      {renew.isError && <Alert>{errorMessage(renew.error)}</Alert>}
      <div className="flex flex-wrap gap-2">
        <Button
          variant="secondary"
          onClick={() => renew.mutate()}
          disabled={!ready || renew.isPending}
        >
          {t('twofactor.newCodes')}
        </Button>
        <Button variant="secondary" onClick={() => off.mutate()} disabled={!ready || off.isPending}>
          {t('twofactor.turnOff')}
        </Button>
      </div>
    </form>
  )
}

function RecoveryCodes({ codes, onDone }: { codes: string[]; onDone: () => void }) {
  const { t } = useTranslation()
  const [saved, setSaved] = useState(false)
  const file = `data:text/plain;charset=utf-8,${encodeURIComponent(
    `${t('twofactor.fileHeader')}\n\n${codes.join('\n')}\n`,
  )}`
  return (
    <section aria-labelledby="sec-codes" className="space-y-3 rounded-md border border-border p-4">
      <h3 id="sec-codes" className="font-medium">
        {t('twofactor.codesTitle')}
      </h3>
      <p className="text-sm">{t('twofactor.codesHelp')}</p>
      <ul aria-label={t('twofactor.codesTitle')} className="grid grid-cols-2 gap-1 font-mono">
        {codes.map((c) => (
          <li key={c} className="select-all">
            {c}
          </li>
        ))}
      </ul>
      <a
        href={file}
        download="folio-recovery-codes.txt"
        className="inline-flex min-h-10 items-center rounded-md border border-border px-4 text-sm font-medium hover:bg-border/40"
      >
        {t('twofactor.download')}
      </a>
      <Checkbox
        label={t('twofactor.saved')}
        checked={saved}
        onChange={(e) => setSaved(e.target.checked)}
      />
      <div>
        <Button onClick={onDone} disabled={!saved}>
          {t('twofactor.done')}
        </Button>
      </div>
    </section>
  )
}
