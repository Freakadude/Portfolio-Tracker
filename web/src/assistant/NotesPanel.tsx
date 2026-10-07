import { useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { errorMessage } from '../api/client'
import { Badge } from '../components/display'
import { Alert, Button, Checkbox, Field, Help, Input, Textarea } from '../components/ui'
import { useFormat } from '../lib/useFormat'
import { ImportChats } from './ImportChats'
import {
  useAddNote,
  useBackgroundRequest,
  useChangeNote,
  useDeleteNote,
  useNotes,
  type Note,
} from './api'

/** "My investing background": what the strategy helper is told about the owner. A note is written
 * by hand or pasted from a chat with Claude; only the strategy helper reads them (ADR 0048). */
export function NotesPanel() {
  const { t } = useTranslation()
  const { num } = useFormat()
  const notes = useNotes()
  const data = notes.data
  return (
    <section aria-labelledby="notes-h" className="space-y-3">
      <h2 id="notes-h" className="text-lg font-semibold">
        {t('assistant.notes.title')}
      </h2>
      <Help title={t('assistant.notes.helpTitle')}>
        <p>{t('assistant.notes.help1')}</p>
        <p>{t('assistant.notes.help2')}</p>
      </Help>
      {notes.isError && <Alert>{errorMessage(notes.error)}</Alert>}
      {data && data.notes.length === 0 && (
        <p className="text-sm text-muted">{t('assistant.notes.none')}</p>
      )}
      {data && data.notes.length > 0 && (
        <>
          <ul className="space-y-2">
            {data.notes.map((n) => (
              <NoteRow key={n.id} note={n} />
            ))}
          </ul>
          <p className="text-xs text-muted">
            {t('assistant.notes.budget', {
              used: num(data.used, 0),
              limit: num(data.total_limit, 0),
            })}
          </p>
          {data.left_out > 0 && <Alert>{t('assistant.notes.leftOut', { n: data.left_out })}</Alert>}
        </>
      )}
      <AddNote limit={data?.note_limit ?? 6000} />
    </section>
  )
}

function NoteRow({ note }: { note: Note }) {
  const { t } = useTranslation()
  const change = useChangeNote()
  const remove = useDeleteNote()
  const [editing, setEditing] = useState(false)
  const [shown, setShown] = useState(note.use_in_helper) // follows the click at once
  const [title, setTitle] = useState(note.title)
  const [body, setBody] = useState(note.body)

  function save(e: FormEvent) {
    e.preventDefault()
    change.mutate({ id: note.id, title, body }, { onSuccess: () => setEditing(false) })
  }

  return (
    <li className="space-y-2 rounded-md border border-border p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-medium">{note.title}</span>
          <Badge>{t(`assistant.notes.sources.${note.source}`)}</Badge>
          <span className="text-xs text-muted">
            {t('assistant.notes.characters', { n: note.characters })}
          </span>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <Checkbox
            label={t('assistant.notes.use')}
            checked={shown}
            onChange={(e) => {
              setShown(e.target.checked)
              change.mutate(
                { id: note.id, use_in_helper: e.target.checked },
                { onError: () => setShown(note.use_in_helper) },
              )
            }}
          />
          <Button variant="secondary" onClick={() => setEditing(!editing)}>
            {t(editing ? 'assistant.notes.close' : 'assistant.notes.edit')}
          </Button>
          <Button
            variant="ghost"
            onClick={() => {
              if (window.confirm(t('assistant.notes.confirmDelete', { title: note.title })))
                remove.mutate(note.id)
            }}
          >
            {t('assistant.notes.delete')}
          </Button>
        </div>
      </div>
      {(change.isError || remove.isError) && (
        <Alert>{errorMessage(change.error ?? remove.error)}</Alert>
      )}
      {editing ? (
        <form onSubmit={save} className="space-y-2" aria-label={t('assistant.notes.editing')}>
          <Field label={t('assistant.notes.noteTitle')}>
            {(p) => <Input value={title} onChange={(e) => setTitle(e.target.value)} {...p} />}
          </Field>
          <Field label={t('assistant.notes.noteBody')}>
            {(p) => (
              <Textarea rows={8} value={body} onChange={(e) => setBody(e.target.value)} {...p} />
            )}
          </Field>
          <Button type="submit" disabled={change.isPending || !title.trim() || !body.trim()}>
            {t('assistant.notes.save')}
          </Button>
        </form>
      ) : (
        <p className="whitespace-pre-line text-sm text-muted">{preview(note.body)}</p>
      )}
    </li>
  )
}

const PREVIEW = 280
const preview = (text: string) => (text.length > PREVIEW ? `${text.slice(0, PREVIEW)}…` : text)

type Way = 'write' | 'claude' | 'import'

function AddNote({ limit }: { limit: number }) {
  const { t } = useTranslation()
  const [way, setWay] = useState<Way>('write')
  return (
    <div className="space-y-3 rounded-md border border-border p-3">
      <div role="tablist" aria-label={t('assistant.notes.add')} className="flex flex-wrap gap-1">
        {(['write', 'claude', 'import'] as const).map((w) => (
          <button
            key={w}
            type="button"
            role="tab"
            aria-selected={way === w}
            onClick={() => setWay(w)}
            className={
              way === w
                ? 'rounded-md bg-primary px-3 py-1.5 text-sm text-primary-foreground'
                : 'rounded-md px-3 py-1.5 text-sm hover:bg-border/40'
            }
          >
            {t(`assistant.notes.ways.${w}`)}
          </button>
        ))}
      </div>
      <div role="tabpanel">
        {way === 'write' && <WriteNote limit={limit} />}
        {way === 'claude' && <FromClaude limit={limit} />}
        {way === 'import' && <ImportChats />}
      </div>
    </div>
  )
}

function WriteNote({ limit }: { limit: number }) {
  const { t } = useTranslation()
  const add = useAddNote()
  const [title, setTitle] = useState('')
  const [body, setBody] = useState('')
  function submit(e: FormEvent) {
    e.preventDefault()
    add.mutate(
      { title, body, source: 'written' },
      {
        onSuccess: () => {
          setTitle('')
          setBody('')
        },
      },
    )
  }
  return (
    <form onSubmit={submit} className="space-y-2" aria-label={t('assistant.notes.writeForm')}>
      <p className="text-sm text-muted">{t('assistant.notes.writeHint')}</p>
      <Field label={t('assistant.notes.noteTitle')}>
        {(p) => (
          <Input
            value={title}
            maxLength={120}
            onChange={(e) => setTitle(e.target.value)}
            placeholder={t('assistant.notes.titlePlaceholder')}
            {...p}
          />
        )}
      </Field>
      <Field label={t('assistant.notes.noteBody')}>
        {(p) => <Textarea rows={6} value={body} onChange={(e) => setBody(e.target.value)} {...p} />}
      </Field>
      <div className="flex flex-wrap items-center gap-3">
        <Button type="submit" disabled={add.isPending || !title.trim() || !body.trim()}>
          {t('assistant.notes.add')}
        </Button>
        <span className="text-xs text-muted">
          {t('assistant.notes.counter', { n: body.length, limit })}
        </span>
      </div>
      {add.isError && <Alert>{errorMessage(add.error)}</Alert>}
    </form>
  )
}

function FromClaude({ limit }: { limit: number }) {
  const { t } = useTranslation()
  const request = useBackgroundRequest()
  const add = useAddNote()
  const [copied, setCopied] = useState(false)
  const [title, setTitle] = useState(t('assistant.notes.profileTitle'))
  const [body, setBody] = useState('')

  async function copy() {
    try {
      await navigator.clipboard.writeText(request.data?.text ?? '')
      setCopied(true)
    } catch {
      setCopied(false) // the text is on screen: it can be selected and copied by hand
    }
  }
  function submit(e: FormEvent) {
    e.preventDefault()
    add.mutate(
      { title, body, source: 'pasted' },
      {
        onSuccess: () => {
          setBody('')
          setCopied(false)
        },
      },
    )
  }
  return (
    <div className="space-y-3">
      <ol className="list-decimal space-y-1 pl-5 text-sm text-muted">
        <li>{t('assistant.notes.claudeStep1')}</li>
        <li>{t('assistant.notes.claudeStep2')}</li>
        <li>{t('assistant.notes.claudeStep3')}</li>
      </ol>
      {request.isError && <Alert>{errorMessage(request.error)}</Alert>}
      {request.data && (
        <>
          <Textarea
            readOnly
            rows={6}
            value={request.data.text}
            aria-label={t('assistant.notes.requestText')}
          />
          <div className="flex items-center gap-3">
            <Button variant="secondary" onClick={() => void copy()}>
              {t('assistant.notes.copy')}
            </Button>
            {copied && (
              <span role="status" className="text-sm text-muted">
                {t('assistant.notes.copied')}
              </span>
            )}
          </div>
        </>
      )}
      <form onSubmit={submit} className="space-y-2" aria-label={t('assistant.notes.pasteForm')}>
        <Field label={t('assistant.notes.noteTitle')}>
          {(p) => (
            <Input
              value={title}
              maxLength={120}
              onChange={(e) => setTitle(e.target.value)}
              {...p}
            />
          )}
        </Field>
        <Field label={t('assistant.notes.pasteHere')}>
          {(p) => (
            <Textarea rows={8} value={body} onChange={(e) => setBody(e.target.value)} {...p} />
          )}
        </Field>
        <div className="flex flex-wrap items-center gap-3">
          <Button type="submit" disabled={add.isPending || !title.trim() || !body.trim()}>
            {t('assistant.notes.saveAsNote')}
          </Button>
          <span className="text-xs text-muted">
            {t('assistant.notes.counter', { n: body.length, limit })}
          </span>
        </div>
        {add.isError && <Alert>{errorMessage(add.error)}</Alert>}
      </form>
    </div>
  )
}
