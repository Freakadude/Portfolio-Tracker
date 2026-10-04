import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { useTranslation } from 'react-i18next'
import { Navigate, useNavigate } from 'react-router-dom'
import { z } from 'zod'
import { api, errorMessage, unwrap } from '../api/client'
import { STATUS_KEY, useSetupStatus } from '../api/hooks'
import { Loading } from '../components/Gate'
import { SectionForm } from '../components/SectionForm'
import { Alert, Button, Card, Field, Input, Select } from '../components/ui'

const STEPS = ['owner', 'preferences', 'account', 'providers', 'notifications'] as const

const PROVIDER_FIELDS = ['eodhd_api_key', 'twelvedata_api_key', 'openfigi_api_key', 'fred_api_key']
const NOTIFICATION_FIELDS = [
  'channel',
  'home_assistant_url',
  'home_assistant_service',
  'home_assistant_token',
  'ntfy_url',
  'ntfy_topic',
  'ntfy_token',
]

export function Setup() {
  const status = useSetupStatus()
  if (status.isPending) return <Loading />
  if (status.data?.setup_complete) return <Navigate to="/" replace />
  if (status.data && !status.data.needs_owner && !status.data.authenticated)
    return <Navigate to="/login" replace />
  const start = status.data?.needs_owner ? 0 : status.data?.has_account ? 3 : 1
  return <Wizard start={start} />
}

function Wizard({ start }: { start: number }) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [step, setStep] = useState(start)
  const next = () => setStep((s) => Math.min(s + 1, STEPS.length - 1))

  const finish = useMutation({
    mutationFn: () => unwrap(api.POST('/api/v1/setup/complete')),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: STATUS_KEY })
      navigate('/')
    },
  })

  const name = STEPS[step]
  return (
    <main className="mx-auto max-w-lg space-y-4 p-4 md:py-12">
      <h1 className="text-2xl font-semibold">{t('setup.title')}</h1>
      <p className="text-sm text-muted">
        {t('setup.step', { current: step + 1, total: STEPS.length })} · {t(`setup.steps.${name}`)}
      </p>
      <Card className="space-y-4">
        <h2 className="text-lg font-medium">{t(`setup.steps.${name}`)}</h2>
        <p className="text-muted">{t(`setup.${name}.intro`)}</p>
        {name === 'owner' && <OwnerStep onDone={next} />}
        {name === 'preferences' && (
          <SectionForm section="general" submitLabel={t('app.next')} onSaved={next} />
        )}
        {name === 'account' && <AccountStep onDone={next} />}
        {name === 'providers' && (
          <SectionForm
            section="providers"
            fields={PROVIDER_FIELDS}
            submitLabel={t('app.next')}
            onSaved={next}
            secondary={
              <Button variant="ghost" onClick={next}>
                {t('app.skip')}
              </Button>
            }
          />
        )}
        {name === 'notifications' && (
          <SectionForm
            section="notifications"
            fields={NOTIFICATION_FIELDS}
            submitLabel={t('app.finish')}
            onSaved={() => finish.mutate()}
            secondary={
              <Button variant="ghost" onClick={() => finish.mutate()}>
                {t('app.skip')}
              </Button>
            }
          />
        )}
        {finish.isError && <Alert>{errorMessage(finish.error)}</Alert>}
      </Card>
    </main>
  )
}

function OwnerStep({ onDone }: { onDone: () => void }) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const schema = z
    .object({
      username: z.string().trim().min(1, t('setup.owner.usernameRequired')),
      password: z.string().min(12, t('setup.owner.tooShort')),
      confirm: z.string(),
    })
    .refine((v) => v.password === v.confirm, {
      path: ['confirm'],
      message: t('setup.owner.mismatch'),
    })
  type Values = z.infer<typeof schema>
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<Values>({ resolver: zodResolver(schema) })

  const create = useMutation({
    mutationFn: (v: Values) =>
      unwrap(
        api.POST('/api/v1/setup/owner', { body: { username: v.username, password: v.password } }),
      ),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: STATUS_KEY })
      onDone()
    },
  })

  return (
    <form className="space-y-4" onSubmit={handleSubmit((v) => create.mutate(v))} noValidate>
      <Field label={t('setup.owner.username')} error={errors.username?.message}>
        {(p) => <Input autoComplete="username" autoFocus {...p} {...register('username')} />}
      </Field>
      <Field label={t('setup.owner.password')} error={errors.password?.message}>
        {(p) => (
          <Input type="password" autoComplete="new-password" {...p} {...register('password')} />
        )}
      </Field>
      <Field label={t('setup.owner.confirm')} error={errors.confirm?.message}>
        {(p) => (
          <Input type="password" autoComplete="new-password" {...p} {...register('confirm')} />
        )}
      </Field>
      {create.isError && <Alert>{errorMessage(create.error)}</Alert>}
      <Button type="submit" disabled={create.isPending}>
        {t('app.next')}
      </Button>
    </form>
  )
}

function AccountStep({ onDone }: { onDone: () => void }) {
  const { t } = useTranslation()
  const schema = z.object({
    name: z.string().trim().min(1, t('setup.account.nameRequired')),
    broker: z.string(),
    cost_basis_method: z.enum(['FIFO', 'AVG']),
  })
  type Values = z.infer<typeof schema>
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: { name: '', broker: '', cost_basis_method: 'FIFO' },
  })

  const create = useMutation({
    mutationFn: (v: Values) =>
      unwrap(
        api.POST('/api/v1/setup/account', {
          body: {
            name: v.name,
            broker: v.broker.trim() || null,
            cost_basis_method: v.cost_basis_method,
          },
        }),
      ),
    onSuccess: onDone,
  })

  return (
    <form className="space-y-4" onSubmit={handleSubmit((v) => create.mutate(v))} noValidate>
      <Field label={t('setup.account.name')} error={errors.name?.message}>
        {(p) => <Input autoFocus {...p} {...register('name')} />}
      </Field>
      <Field label={t('setup.account.broker')}>
        {(p) => <Input {...p} {...register('broker')} />}
      </Field>
      <Field label={t('setup.account.method')}>
        {(p) => (
          <Select {...p} {...register('cost_basis_method')}>
            <option value="FIFO">{t('setup.account.fifo')}</option>
            <option value="AVG">{t('setup.account.avg')}</option>
          </Select>
        )}
      </Field>
      {create.isError && <Alert>{errorMessage(create.error)}</Alert>}
      <Button type="submit" disabled={create.isPending}>
        {t('app.next')}
      </Button>
    </form>
  )
}
