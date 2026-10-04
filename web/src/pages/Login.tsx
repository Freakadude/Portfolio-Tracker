import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useForm } from 'react-hook-form'
import { useTranslation } from 'react-i18next'
import { Navigate, useNavigate } from 'react-router-dom'
import { z } from 'zod'
import { api, errorMessage, unwrap } from '../api/client'
import { STATUS_KEY, useSetupStatus } from '../api/hooks'
import { Loading } from '../components/Gate'
import { Alert, Button, Card, Checkbox, Field, Input } from '../components/ui'

const schema = z.object({
  username: z.string().min(1),
  password: z.string().min(1),
  remember: z.boolean(),
})
type Values = z.infer<typeof schema>

export function Login() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const status = useSetupStatus()
  const { register, handleSubmit } = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: { username: '', password: '', remember: false },
  })

  const login = useMutation({
    mutationFn: (body: Values) => unwrap(api.POST('/api/v1/auth/login', { body })),
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
          <Checkbox label={t('login.remember')} {...register('remember')} />
          {login.isError && <Alert>{errorMessage(login.error)}</Alert>}
          <Button type="submit" className="w-full" disabled={login.isPending}>
            {t('login.submit')}
          </Button>
        </form>
      </Card>
    </main>
  )
}
