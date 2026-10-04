import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { api, errorMessage, unwrap } from '../api/client'
import { Alert, Button, Checkbox, Field, Input, Select, Textarea } from './ui'

type Values = Record<string, unknown>

// Write-only fields: the API never returns them, only a masked form.
const SECRETS: Record<string, string[]> = {
  providers: ['eodhd_api_key', 'twelvedata_api_key', 'openfigi_api_key', 'fred_api_key'],
  agent: ['anthropic_api_key'],
  notifications: ['home_assistant_token', 'ntfy_token'],
}

const ENUMS: Record<string, string[]> = {
  number_format: ['eu', 'us'],
  theme: ['system', 'light', 'dark'],
  channel: ['home_assistant', 'ntfy', 'web_push', 'none'],
  language: ['en'],
}

export const sectionKey = (section: string) => ['settings', section] as const

function timezones(): string[] {
  try {
    return (Intl as unknown as { supportedValuesOf(k: string): string[] }).supportedValuesOf(
      'timeZone',
    )
  } catch {
    return ['Europe/Amsterdam', 'UTC']
  }
}

function isJsonField(value: unknown) {
  return typeof value === 'object' && value !== null
}

interface Props {
  section: string
  /** Show only these fields (the wizard shows a subset). All other values are kept as they are. */
  fields?: string[]
  submitLabel?: string
  onSaved?: () => void
  secondary?: ReactNode
}

export function SectionForm({ section, ...rest }: Props) {
  const { t } = useTranslation()
  // Lives here, not in Editor: Editor remounts when saved data comes back.
  const [saved, setSaved] = useState(false)
  const query = useQuery({
    queryKey: sectionKey(section),
    queryFn: () =>
      unwrap(
        api.GET('/api/v1/settings/{section}', { params: { path: { section } } }),
      ) as Promise<Values>,
  })
  if (query.isPending) return <p role="status">{t('app.loading')}</p>
  if (query.isError) return <Alert>{errorMessage(query.error)}</Alert>
  return (
    <Editor
      key={query.dataUpdatedAt}
      section={section}
      data={query.data}
      saved={saved}
      setSaved={setSaved}
      {...rest}
    />
  )
}

function Editor({
  section,
  data,
  fields,
  submitLabel,
  onSaved,
  secondary,
  saved,
  setSaved,
}: Props & { data: Values; saved: boolean; setSaved: (v: boolean) => void }) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const secrets = SECRETS[section] ?? []

  const [values, setValues] = useState<Record<string, string | boolean>>(() => {
    const init: Record<string, string | boolean> = {}
    for (const [key, value] of Object.entries(data)) {
      if (secrets.includes(key)) init[key] = ''
      else if (typeof value === 'boolean') init[key] = value
      else if (isJsonField(value)) init[key] = JSON.stringify(value, null, 2)
      else init[key] = value === null ? '' : String(value)
    }
    return init
  })
  const [cleared, setCleared] = useState<Set<string>>(new Set())
  const [jsonErrors, setJsonErrors] = useState<Record<string, string>>({})

  const save = useMutation({
    mutationFn: (body: Values) =>
      unwrap(api.PUT('/api/v1/settings/{section}', { params: { path: { section } }, body })),
    onSuccess: async () => {
      setSaved(true)
      await queryClient.invalidateQueries({ queryKey: sectionKey(section) })
      onSaved?.()
    },
  })

  const keys = Object.keys(data).filter((k) => !fields || fields.includes(k))

  function submit(event: FormEvent) {
    event.preventDefault()
    setSaved(false)
    const body: Values = {}
    const errors: Record<string, string> = {}
    for (const [key, original] of Object.entries(data)) {
      const value = values[key]
      if (secrets.includes(key)) {
        if (cleared.has(key)) body[key] = ''
        else if (typeof value === 'string' && value !== '') body[key] = value
        continue // otherwise omitted: the saved secret stays
      }
      if (isJsonField(original)) {
        try {
          body[key] = JSON.parse(String(value))
        } catch {
          errors[key] = t('settings.invalidJson')
        }
      } else if (typeof original === 'boolean') body[key] = Boolean(value)
      else if (typeof original === 'number') body[key] = Number(value)
      else body[key] = value === '' && original === null ? null : value
    }
    setJsonErrors(errors)
    if (Object.keys(errors).length === 0) save.mutate(body)
  }

  const problemFor = (key: string) =>
    (save.error as { errors?: { field: string; message: string }[] } | null)?.errors?.find(
      (e) => e.field === key || e.field.startsWith(`${key}.`),
    )?.message

  return (
    <form onSubmit={submit} className="space-y-4" noValidate>
      {keys.map((key) => {
        const label = t(`fields.${key}`, { defaultValue: key })
        const error = jsonErrors[key] ?? problemFor(key)
        const value = values[key]
        const set = (v: string | boolean) => {
          setSaved(false)
          setValues((prev) => ({ ...prev, [key]: v }))
        }

        if (secrets.includes(key)) {
          const masked = data[key] as string | null
          return (
            <Field
              key={key}
              label={label}
              error={error}
              hint={
                masked && !cleared.has(key)
                  ? `${masked} · ${t('settings.secretSet')}`
                  : t('settings.secretUnset')
              }
            >
              {(p) => (
                <div className="flex gap-2">
                  <Input
                    type="password"
                    autoComplete="new-password"
                    value={String(value)}
                    onChange={(e) => set(e.target.value)}
                    {...p}
                  />
                  {masked && (
                    <Button
                      variant="secondary"
                      onClick={() => setCleared((prev) => new Set(prev).add(key))}
                      disabled={cleared.has(key)}
                    >
                      {t('settings.clear')}
                    </Button>
                  )}
                </div>
              )}
            </Field>
          )
        }
        if (typeof value === 'boolean')
          return (
            <Checkbox
              key={key}
              label={label}
              checked={value}
              onChange={(e) => set(e.target.checked)}
            />
          )
        return (
          <Field key={key} label={label} error={error}>
            {(p) =>
              key in ENUMS ? (
                <Select value={String(value)} onChange={(e) => set(e.target.value)} {...p}>
                  {ENUMS[key].map((opt) => (
                    <option key={opt} value={opt}>
                      {t(`options.${key}.${opt}`, { defaultValue: opt })}
                    </option>
                  ))}
                </Select>
              ) : isJsonField(data[key]) ? (
                <Textarea
                  rows={6}
                  value={String(value)}
                  onChange={(e) => set(e.target.value)}
                  {...p}
                />
              ) : key === 'timezone' ? (
                <>
                  <Input
                    list="timezones"
                    value={String(value)}
                    onChange={(e) => set(e.target.value)}
                    {...p}
                  />
                  <datalist id="timezones">
                    {timezones().map((tz) => (
                      <option key={tz} value={tz} />
                    ))}
                  </datalist>
                </>
              ) : (
                <Input
                  type={typeof data[key] === 'number' ? 'number' : 'text'}
                  value={String(value)}
                  onChange={(e) => set(e.target.value)}
                  {...p}
                />
              )
            }
          </Field>
        )
      })}
      {save.isError && !problemFor('') && <Alert>{errorMessage(save.error)}</Alert>}
      <div className="flex flex-wrap items-center gap-3">
        <Button type="submit" disabled={save.isPending}>
          {submitLabel ?? t('app.save')}
        </Button>
        {secondary}
        {saved && (
          <span role="status" className="text-sm text-gain">
            {t('settings.saved')}
          </span>
        )}
      </div>
    </form>
  )
}
