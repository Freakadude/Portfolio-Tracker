import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { useTranslation } from 'react-i18next'
import { Navigate, useNavigate } from 'react-router-dom'
import { z } from 'zod'
import { ApiProblem, api, errorMessage, unwrap } from '../api/client'
import { STATUS_KEY, useSetupStatus } from '../api/hooks'
import { Loading } from '../components/Gate'
import { Alert, Button, Card, Checkbox, Field, Input } from '../components/ui'

const schema = z.object({
  username: z.string().min(1),
  password: z.string().min(1),
  remember: z.boolean(),
  code: z.string().optional(),
})
type Values = z.infer<typeof schema>

export function Login() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const status = useSetupStatus()
  const { register, handleSubmit } = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: { username: '', password: '', remember: false, code: '' },
  })
  const [needCode, setNeedCode] = useState(false)
  const methods = useQuery({
    queryKey: ['auth', 'methods'],
    queryFn: () => unwrap(api.GET('/api/v1/auth/methods')),
    retry: false,
  })
  const tailnet = useMutation({
    mutationFn: () => unwrap(api.POST('/api/v1/auth/tailscale')),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: STATUS_KEY })
      navigate('/')
    },
  })

  const login = useMutation({
    mutationFn: (body: Values) =>
      unwrap(
        api.POST('/api/v1/auth/login', { body: { ...body, code: body.code?.trim() || null } }),
      ),
    onError: (err) => {
      if (err instanceof ApiProblem && err.extra.code === 'totp_required') setNeedCode(true)
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: STATUS_KEY })
      navigate('/')
    },
  })

  if (status.isPending) return <Loading />
  if (status.data?.needs_owner) return <Navigate to="/setup" replace />
  if (status.data?.authenticated) return <Navigate to="/" replace />

  return (
    <main className="mx-auto flex min-h-screen max-w-sm items-center p-4">
      <Card className="w-full space-y-4">
        <h1 className="text-2xl font-semibold">{t('login.title')}</h1>
        <form className="space-y-4" onSubmit={handleSubmit((v) => login.mutate(v))} noValidate>
          <Field label={t('login.username')}>
            {(p) => <Input autoComplete="username" autoFocus {...p} {...register('username')} />}
          </Field>
          <Field label={t('login.password')}>
            {(p) => (
              <Input
                type="password"
                autoComplete="current-password"
                {...p}
                {...register('password')}
              />
            )}
          </Field>
          {needCode && (
            <Field label={t('login.code')}>
              {(p) => (
                <Input
                  autoComplete="one-time-code"
                  autoFocus
                  inputMode="text"
                  {...p}
                  {...register('code')}
                />
              )}
            </Field>
          )}
          <Checkbox label={t('login.remember')} {...register('remember')} />
          {login.isError && (
            <Alert>
              {login.error instanceof ApiProblem &&
              login.error.extra.code === 'totp_required' &&
              login.error.title === 'Code needed'
                ? t('login.codeNeeded')
                : errorMessage(login.error)}
            </Alert>
          )}
          <Button type="submit" className="w-full" disabled={login.isPending}>
            {t('login.submit')}
          </Button>
        </form>
        {methods.data?.tailscale && (
          <div className="space-y-2 border-t border-border pt-4">
            <Button
              variant="secondary"
              className="w-full"
              onClick={() => tailnet.mutate()}
              disabled={tailnet.isPending}
            >
              {t('login.tailscale')}
            </Button>
            {tailnet.isError && <Alert>{errorMessage(tailnet.error)}</Alert>}
          </div>
        )}
      </Card>
    </main>
  )
}
