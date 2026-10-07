import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { errorMessage } from '../api/client'
import { Badge } from '../components/display'
import { Alert, Button, Checkbox, Textarea } from '../components/ui'
import { useFormat } from '../lib/useFormat'
import { useAddNote, useEstimateChats, useScanChats, useSummariseChats, type ChatInfo } from './api'

const MAX_CHATS = 8

type Draft = { id: string; title: string; text: string | null; keep: boolean }

/** Bring chats from a claude.ai export in as notes: pick the chats, see what it can cost, read
 * and edit the short summaries, and keep the ones you want (ADR 0048). The export file is read
 * in memory by the server and never stored. */
export function ImportChats() {
  const { t } = useTranslation()
  const { eur, num, when } = useFormat()
  const scan = useScanChats()
  const estimate = useEstimateChats()
  const summarise = useSummariseChats()
  const add = useAddNote()
  const [file, setFile] = useState<File | null>(null)
  const [chosen, setChosen] = useState<string[]>([])
  const [drafts, setDrafts] = useState<Draft[] | null>(null)
  const [saved, setSaved] = useState<number | null>(null)

  function pick(f: File | null) {
    setFile(f)
    setDrafts(null)
    setSaved(null)
    estimate.reset()
    summarise.reset()
    if (!f) return
    scan.mutate(f, {
      onSuccess: (out) =>
        setChosen(
          out.chats
            .filter((c) => c.relevant)
            .slice(0, MAX_CHATS)
            .map((c) => c.id),
        ),
    })
  }
  function toggle(id: string, on: boolean) {
    estimate.reset()
    setChosen((now) => (on ? [...now, id] : now.filter((x) => x !== id)))
  }
  function change(index: number, patch: Partial<Draft>) {
    setDrafts((now) => (now ?? []).map((d, i) => (i === index ? { ...d, ...patch } : d)))
  }
  async function keep() {
    const wanted = (drafts ?? []).filter((d) => d.keep && d.text?.trim())
    for (const d of wanted) {
      await add.mutateAsync({ title: d.title, body: d.text ?? '', source: 'chat_export' })
    }
    setSaved(wanted.length)
    setDrafts(null)
  }

  const chats = scan.data?.chats ?? []
  const kept = (drafts ?? []).filter((d) => d.keep && d.text?.trim()).length
  return (
    <div className="space-y-3">
      <ol className="list-decimal space-y-1 pl-5 text-sm text-muted">
        <li>{t('assistant.import.step1')}</li>
        <li>{t('assistant.import.step2')}</li>
        <li>{t('assistant.import.step3')}</li>
      </ol>
      <label className="block space-y-1 text-sm">
        <span className="font-medium">{t('assistant.import.file')}</span>
        <input
          type="file"
          accept=".zip,.json,application/zip,application/json"
          onChange={(e) => pick(e.target.files?.[0] ?? null)}
          className="block text-sm"
        />
      </label>
      {scan.isPending && (
        <p role="status" className="text-sm text-muted">
          {t('assistant.import.reading')}
        </p>
      )}
      {scan.isError && <Alert>{errorMessage(scan.error)}</Alert>}
      {scan.data && (
        <p className="text-sm text-muted">
          {t('assistant.import.found', {
            total: num(scan.data.total, 0),
            relevant: num(scan.data.relevant, 0),
          })}
        </p>
      )}
      {chats.length > 0 && !drafts && (
        <>
          <ul aria-label={t('assistant.import.list')} className="max-h-96 space-y-1 overflow-auto">
            {chats.map((c) => (
              <ChatRow
                key={c.id}
                chat={c}
                on={chosen.includes(c.id)}
                disabled={!chosen.includes(c.id) && chosen.length >= MAX_CHATS}
                onChange={(on) => toggle(c.id, on)}
                date={c.created_at ? when(c.created_at) : ''}
              />
            ))}
          </ul>
          <div className="flex flex-wrap items-center gap-3">
            <Button
              variant="secondary"
              disabled={!file || chosen.length === 0 || estimate.isPending}
              onClick={() => file && estimate.mutate({ file, ids: chosen })}
            >
              {t('assistant.import.check', { n: chosen.length })}
            </Button>
            <span className="text-xs text-muted">
              {t('assistant.import.max', { n: MAX_CHATS })}
            </span>
          </div>
          {estimate.isError && <Alert>{errorMessage(estimate.error)}</Alert>}
          {estimate.data && (
            <div className="space-y-2 rounded-md border border-border p-3 text-sm">
              <p>
                {t('assistant.import.cost', {
                  cost: eur(estimate.data.cost_eur),
                  left: eur(estimate.data.remaining_eur),
                })}
              </p>
              <p className="text-muted">{t('assistant.import.privacy')}</p>
              {!estimate.data.fits && <Alert>{t('assistant.import.noFit')}</Alert>}
              <Button
                disabled={!estimate.data.fits || summarise.isPending}
                onClick={() =>
                  file &&
                  summarise.mutate(
                    { file, ids: chosen },
                    {
                      onSuccess: (out) =>
                        setDrafts(
                          out.summaries.map((s) => ({
                            id: s.id,
                            title: s.title,
                            text: s.text,
                            keep: !!s.text,
                          })),
                        ),
                    },
                  )
                }
              >
                {t('assistant.import.summarise', { n: estimate.data.chats })}
              </Button>
            </div>
          )}
          {summarise.isPending && (
            <p role="status" className="text-sm text-muted">
              {t('assistant.import.working')}
            </p>
          )}
          {summarise.isError && <Alert>{errorMessage(summarise.error)}</Alert>}
        </>
      )}
      {summarise.data?.stopped && <Alert>{summarise.data.stopped}</Alert>}
      {summarise.data?.failed.map((f) => (
        <Alert key={f.id}>
          {t('assistant.import.failed', { title: f.title, reason: f.reason })}
        </Alert>
      ))}
      {drafts && (
        <div className="space-y-3">
          <p className="text-sm text-muted">{t('assistant.import.review')}</p>
          {drafts.length === 0 && <p className="text-sm">{t('assistant.import.noSummaries')}</p>}
          {drafts.map((d, i) => (
            <div key={d.id} className="space-y-1 rounded-md border border-border p-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="font-medium">{d.title}</span>
                {d.text !== null && (
                  <Checkbox
                    label={t('assistant.import.keep')}
                    checked={d.keep}
                    onChange={(e) => change(i, { keep: e.target.checked })}
                  />
                )}
              </div>
              {d.text === null ? (
                <p className="text-sm text-muted">{t('assistant.import.nothing')}</p>
              ) : (
                <Textarea
                  rows={5}
                  aria-label={t('assistant.import.summaryOf', { title: d.title })}
                  value={d.text}
                  onChange={(e) => change(i, { text: e.target.value })}
                />
              )}
            </div>
          ))}
          {summarise.data && (
            <p className="text-xs text-muted">
              {t('assistant.import.spent', { cost: eur(summarise.data.cost_eur) })}
            </p>
          )}
          <Button disabled={add.isPending || kept === 0} onClick={() => void keep()}>
            {t('assistant.import.save', { n: kept })}
          </Button>
          {add.isError && <Alert>{errorMessage(add.error)}</Alert>}
        </div>
      )}
      {saved !== null && (
        <p role="status" className="text-sm">
          {t('assistant.import.saved', { n: saved })}
        </p>
      )}
    </div>
  )
}

function ChatRow({
  chat,
  on,
  disabled,
  onChange,
  date,
}: {
  chat: ChatInfo
  on: boolean
  disabled: boolean
  onChange: (on: boolean) => void
  date: string
}) {
  const { t } = useTranslation()
  return (
    <li className="rounded-md border border-border px-3 py-1">
      <div className="flex flex-wrap items-center gap-2">
        <Checkbox
          label={chat.title}
          checked={on}
          disabled={disabled}
          onChange={(e) => onChange(e.target.checked)}
        />
        {chat.relevant && <Badge tone="good">{t('assistant.import.aboutInvesting')}</Badge>}
        <span className="text-xs text-muted">
          {date} · {t('assistant.import.messages', { n: chat.messages })}
        </span>
      </div>
      <p className="pb-1 pl-6 text-xs text-muted">{chat.opening}</p>
    </li>
  )
}
