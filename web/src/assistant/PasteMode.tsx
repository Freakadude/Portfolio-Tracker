import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'
import { errorMessage } from '../api/client'
import { Alert, Button, Field, Select, Textarea } from '../components/ui'
import { useCheck, useStrategies } from '../strategies/api'
import { useHelperPrompt } from './api'
import { Proposal } from './Proposal'
import { extractYaml, problemsText } from './proposalText'

type Mode = 'new' | 'revise'

/** The free way, on the Claude subscription: one prompt to paste into claude.ai, and the finished
 * strategy pasted back to be checked and reviewed here (ADR 0048). Nothing is sent from Folio. */
export function PasteMode() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const strategies = useStrategies()
  const [mode, setMode] = useState<Mode>('new')
  const [strategy, setStrategy] = useState<number | null>(null)
  const prompt = useHelperPrompt(mode, strategy)
  const check = useCheck()
  const [copied, setCopied] = useState<'prompt' | 'problems' | null>(null)
  const [answer, setAnswer] = useState('')

  async function copy(text: string, what: 'prompt' | 'problems') {
    try {
      await navigator.clipboard.writeText(text)
      setCopied(what)
    } catch {
      setCopied(null) // the text is on screen: it can be selected and copied by hand
    }
  }
  const checked = check.data
  const reviseId = mode === 'revise' ? strategy : null

  return (
    <section aria-labelledby="paste-h" className="space-y-4">
      <h2 id="paste-h" className="text-lg font-semibold">
        {t('assistant.paste.title')}
      </h2>
      <p className="text-sm text-muted">{t('assistant.paste.intro')}</p>

      <fieldset className="space-y-2">
        <legend className="text-sm font-medium">{t('assistant.paste.what')}</legend>
        {(['new', 'revise'] as const).map((m) => (
          <label key={m} className="flex items-center gap-2 text-sm">
            <input
              type="radio"
              name="helper-mode"
              checked={mode === m}
              onChange={() => {
                setMode(m)
                check.reset()
              }}
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
              onChange={(e) => {
                setStrategy(e.target.value ? Number(e.target.value) : null)
                check.reset()
              }}
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

      {prompt.isError && <Alert>{errorMessage(prompt.error)}</Alert>}
      {prompt.data && (
        <div className="space-y-2">
          <p className="text-xs text-muted">
            {t('assistant.paste.includes', { n: prompt.data.notes_used })}
          </p>
          <Textarea
            readOnly
            rows={8}
            value={prompt.data.text}
            aria-label={t('assistant.paste.promptText')}
          />
          <div className="flex items-center gap-3">
            <Button variant="secondary" onClick={() => void copy(prompt.data.text, 'prompt')}>
              {t('assistant.paste.copy')}
            </Button>
            {copied === 'prompt' && (
              <span role="status" className="text-sm text-muted">
                {t('assistant.paste.copied')}
              </span>
            )}
          </div>
        </div>
      )}

      <p className="text-sm text-muted">{t('assistant.paste.step2')}</p>
      <Field label={t('assistant.paste.answer')}>
        {(p) => (
          <Textarea
            rows={8}
            value={answer}
            onChange={(e) => {
              setAnswer(e.target.value)
              check.reset()
            }}
            {...p}
          />
        )}
      </Field>
      <Button
        disabled={check.isPending || !answer.trim() || (mode === 'revise' && strategy === null)}
        onClick={() => check.mutate({ yaml: extractYaml(answer) })}
      >
        {t('assistant.paste.check')}
      </Button>
      {check.isError && <Alert>{errorMessage(check.error)}</Alert>}

      {checked && !checked.ok && (
        <div className="space-y-2 rounded-md border border-danger/50 p-3" role="alert">
          <p className="text-sm text-danger">{t('assistant.paste.problems')}</p>
          <ul className="list-disc space-y-1 pl-5 text-sm">
            {checked.problems.map((p, i) => (
              <li key={i}>
                {p.line ? `${t('assistant.paste.line', { n: p.line })}: ` : ''}
                {p.message}
              </li>
            ))}
          </ul>
          <div className="flex items-center gap-3">
            <Button
              variant="secondary"
              onClick={() => void copy(problemsText(checked.problems), 'problems')}
            >
              {t('assistant.paste.copyProblems')}
            </Button>
            {copied === 'problems' && (
              <span role="status" className="text-sm text-muted">
                {t('assistant.paste.copied')}
              </span>
            )}
          </div>
        </div>
      )}
      {checked?.ok && checked.yaml && checked.definition && (
        <Proposal
          yaml={checked.yaml}
          definition={checked.definition}
          reviseId={reviseId}
          onSaved={(id) => navigate(`/strategies?id=${id}&made=helper`)}
        />
      )}
    </section>
  )
}
