import { useEffect, useRef, useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { errorMessage } from '../api/client'
import { Alert, Button, Field, Select, Textarea } from '../components/ui'
import { cn } from '../lib/cn'
import { useFormat } from '../lib/useFormat'
import { useStrategies } from '../strategies/api'
import { useAgentStanding, useSay, useSession, useStartSession, type HelperSession } from './api'
import { Proposal } from './Proposal'

/** The interview in the app (ADR 0048): the helper asks guided questions, the owner answers (or
 * picks a suggested answer), and when it has enough it drafts a strategy that is shown before
 * anything is saved. It uses the Anthropic API key and the monthly AI budget. */
export function Interview() {
  const { t } = useTranslation()
  const [params, setParams] = useSearchParams()
  const id = params.get('session') ? Number(params.get('session')) : null
  const session = useSession(id)
  if (id !== null && session.data) {
    return <Talk key={id} session={session.data} onNew={() => setParams({})} />
  }
  return (
    <div className="space-y-3">
      {id !== null && session.isPending && (
        <p role="status" className="text-sm text-muted">
          {t('assistant.interview.loading')}
        </p>
      )}
      {id !== null && session.isError && <Alert>{errorMessage(session.error)}</Alert>}
      <Start onStarted={(started) => setParams({ session: String(started) })} />
    </div>
  )
}

function Start({ onStarted }: { onStarted: (id: number) => void }) {
  const { t } = useTranslation()
  const { eur } = useFormat()
  const standing = useAgentStanding()
  const strategies = useStrategies()
  const start = useStartSession()
  const [mode, setMode] = useState<'new' | 'revise'>('new')
  const [strategy, setStrategy] = useState<number | null>(null)
  const ready = standing.data?.enabled && standing.data.key_set
  const paused = standing.data?.paused

  return (
    <section aria-labelledby="interview-h" className="space-y-4">
      <h2 id="interview-h" className="text-lg font-semibold">
        {t('assistant.interview.title')}
      </h2>
      <p className="text-sm text-muted">{t('assistant.interview.intro')}</p>
      {standing.data && !ready && (
        <Alert>
          {t('assistant.interview.notReady')}{' '}
          <Link to="/settings" className="underline">
            {t('assistant.interview.toSettings')}
          </Link>
        </Alert>
      )}
      {standing.data && ready && (
        <p className="text-xs text-muted">
          {t('assistant.interview.budget', { left: eur(standing.data.remaining_eur) })}
        </p>
      )}
      {paused && <Alert>{t('assistant.interview.paused')}</Alert>}
      <fieldset className="space-y-2">
        <legend className="text-sm font-medium">{t('assistant.paste.what')}</legend>
        {(['new', 'revise'] as const).map((m) => (
          <label key={m} className="flex items-center gap-2 text-sm">
            <input
              type="radio"
              name="interview-mode"
              checked={mode === m}
              onChange={() => setMode(m)}
            />
            {t(`assistant.paste.${m}`)}
          </label>
        ))}
      </fieldset>
      {mode === 'revise' && (
        <Field label={t('assistant.paste.which')}>
          {(p) => (
            <Select
              value={strategy ?? ''}
              onChange={(e) => setStrategy(e.target.value ? Number(e.target.value) : null)}
              {...p}
            >
              <option value="">{t('assistant.paste.pick')}</option>
              {(strategies.data ?? []).map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </Select>
          )}
        </Field>
      )}
      <Button
        disabled={!ready || paused || start.isPending || (mode === 'revise' && strategy === null)}
        onClick={() =>
          start.mutate(
            { mode, strategy_id: mode === 'revise' ? strategy : null },
            { onSuccess: (s) => onStarted(s.id) },
          )
        }
      >
        {t('assistant.interview.start')}
      </Button>
      {start.isPending && (
        <p role="status" className="text-sm text-muted">
          {t('assistant.interview.thinking')}
        </p>
      )}
      {start.isError && <Alert>{errorMessage(start.error)}</Alert>}
    </section>
  )
}

function Talk({ session, onNew }: { session: HelperSession; onNew: () => void }) {
  const { t } = useTranslation()
  const { eur } = useFormat()
  const navigate = useNavigate()
  const say = useSay(session.id)
  const [text, setText] = useState('')
  const end = useRef<HTMLDivElement>(null)
  const last = session.messages[session.messages.length - 1]

  useEffect(() => {
    end.current?.scrollIntoView?.({ block: 'nearest' })
  }, [session.messages.length, say.isPending])

  function send(value: string) {
    const clean = value.trim()
    if (!clean || say.isPending) return
    say.mutate(clean, { onSuccess: () => setText('') })
  }
  function submit(e: FormEvent) {
    e.preventDefault()
    send(text)
  }
  const full = session.answers >= session.max_answers

  return (
    <section aria-labelledby="talk-h" className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id="talk-h" className="text-lg font-semibold">
          {session.mode === 'revise'
            ? t('assistant.interview.revising', { name: session.strategy_name ?? '' })
            : t('assistant.interview.titleNew')}
        </h2>
        <Button variant="ghost" onClick={onNew}>
          {t('assistant.interview.newTalk')}
        </Button>
      </div>
      <ul
        role="log"
        aria-label={t('assistant.interview.log')}
        className="max-h-[28rem] space-y-2 overflow-auto rounded-md border border-border p-3"
      >
        {session.messages.map((m, i) => (
          <li
            key={i}
            className={cn(
              'max-w-[85%] whitespace-pre-line rounded-lg px-3 py-2 text-sm',
              m.role === 'user' ? 'ml-auto bg-primary text-primary-foreground' : 'bg-border/40',
            )}
          >
            <span className="sr-only">
              {t(m.role === 'user' ? 'assistant.interview.you' : 'assistant.interview.helper')}
              :{' '}
            </span>
            {m.text}
          </li>
        ))}
        {say.isPending && (
          <li role="status" className="text-sm text-muted">
            {t('assistant.interview.thinking')}
          </li>
        )}
        <div ref={end} />
      </ul>
      {last?.role === 'assistant' && last.choices.length > 0 && !say.isPending && !full && (
        <div className="flex flex-wrap gap-2" aria-label={t('assistant.interview.suggested')}>
          {last.choices.map((c) => (
            <Button key={c} variant="secondary" onClick={() => send(c)}>
              {c}
            </Button>
          ))}
        </div>
      )}
      <form onSubmit={submit} className="space-y-2" aria-label={t('assistant.interview.reply')}>
        <Field label={t('assistant.interview.yourAnswer')}>
          {(p) => (
            <Textarea
              rows={3}
              maxLength={2000}
              value={text}
              disabled={full}
              onChange={(e) => setText(e.target.value)}
              {...p}
            />
          )}
        </Field>
        <Button type="submit" disabled={!text.trim() || say.isPending || full}>
          {t('assistant.interview.send')}
        </Button>
      </form>
      {full && <Alert>{t('assistant.interview.full', { n: session.max_answers })}</Alert>}
      {say.isError && <Alert>{errorMessage(say.error)}</Alert>}
      <p className="text-xs text-muted">
        {t('assistant.interview.cost', {
          spent: eur(session.spent_eur),
          n: session.answers,
          max: session.max_answers,
          left: eur(session.remaining_eur),
        })}
      </p>
      {session.draft && (
        <div className="space-y-2 rounded-md border border-primary/50 p-3">
          <p className="text-sm font-medium">{t('assistant.interview.draft')}</p>
          <Proposal
            yaml={session.draft.yaml}
            definition={session.draft.definition}
            reviseId={session.mode === 'revise' ? session.strategy_id : null}
            onSaved={(id) => navigate(`/strategies?id=${id}&made=helper`)}
          />
        </div>
      )}
    </section>
  )
}
