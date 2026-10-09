import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useLocation } from 'react-router-dom'
import { useAgentBudget } from '../agent/api'
import { AnswerBody } from '../agent/AnswerBody'
import { errorMessage } from '../api/client'
import { Alert, Button, Textarea } from '../components/ui'
import { cn } from '../lib/cn'
import { isWorking, useChatOpen, useChatSend, useChatThread, useChatTurns } from './api'

const SUGGESTIONS = ['howIsIt', 'news', 'bands'] as const

function ChatIcon() {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 24 24"
      className="h-5 w-5"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12Z" />
    </svg>
  )
}

/** The chat side panel (ADR 0049): a button on every page opens a full-height panel on the right
 * where the owner can ask the agent about the portfolio. It is the same read-only engine as "Ask
 * the portfolio", so each reply only carries figures its tools returned. `Ctrl+/` toggles it. */
export function ChatDock() {
  const { t } = useTranslation()
  const [open, setOpen] = useChatOpen()
  const [draft, setDraft] = useState('')
  const launcher = useRef<HTMLButtonElement>(null)
  const wasOpen = useRef(open)

  useEffect(() => {
    const onKey = (e: globalThis.KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === '/') {
        e.preventDefault()
        setOpen(!open)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, setOpen])

  useEffect(() => {
    if (wasOpen.current && !open) launcher.current?.focus()
    wasOpen.current = open
  }, [open])

  return (
    <>
      {!open && (
        <button
          ref={launcher}
          type="button"
          onClick={() => setOpen(true)}
          aria-keyshortcuts="Control+/"
          title={t('chat.shortcut')}
          className="fixed bottom-4 right-4 z-30 inline-flex min-h-11 items-center gap-2 rounded-full bg-primary px-4 text-sm font-medium text-primary-foreground shadow-lg hover:opacity-90 print:hidden"
        >
          <ChatIcon />
          <span className="max-sm:sr-only">{t('chat.open')}</span>
        </button>
      )}
      {open && (
        <>
          <div
            aria-hidden="true"
            onClick={() => setOpen(false)}
            className="fixed inset-0 z-30 bg-black/30 lg:hidden print:hidden"
          />
          <aside
            aria-label={t('chat.title')}
            onKeyDown={(e: KeyboardEvent) => {
              if (e.key === 'Escape') setOpen(false)
            }}
            className={cn(
              'fixed inset-y-0 right-0 z-40 flex w-full flex-col border-l border-border bg-card shadow-xl sm:w-96',
              'lg:sticky lg:inset-auto lg:top-0 lg:z-auto lg:h-screen lg:shrink-0 lg:shadow-none',
              'print:hidden',
            )}
          >
            <ChatBody draft={draft} setDraft={setDraft} close={() => setOpen(false)} />
          </aside>
        </>
      )}
    </>
  )
}

function ChatBody({
  draft,
  setDraft,
  close,
}: {
  draft: string
  setDraft: (text: string) => void
  close: () => void
}) {
  const { t } = useTranslation()
  const { pathname } = useLocation()
  const [thread, newChat] = useChatThread()
  const turns = useChatTurns(thread, true)
  const send = useChatSend(thread)
  const standing = useAgentBudget()
  const input = useRef<HTMLTextAreaElement>(null)
  const end = useRef<HTMLLIElement>(null)

  const list = turns.data ?? []
  const ready = !!standing.data?.enabled && !!standing.data.key_set
  const paused = !!standing.data?.paused
  const working = send.isPending || list.some((q) => isWorking(q.status))
  const canAsk = ready && !paused && !working

  useEffect(() => {
    if (ready) input.current?.focus()
  }, [ready])
  useEffect(() => end.current?.scrollIntoView?.({ block: 'end' }), [list.length, working])

  function ask(text: string) {
    const question = text.trim()
    if (question.length < 3 || !canAsk) return
    send.mutate({ question, page: pathname }, { onSuccess: () => setDraft('') })
  }

  function submit(e: FormEvent) {
    e.preventDefault()
    ask(draft)
  }

  return (
    <>
      <header className="flex items-center justify-between gap-2 border-b border-border px-4 py-3">
        <h2 className="text-base font-semibold">{t('chat.title')}</h2>
        <div className="flex items-center gap-1">
          <Button
            variant="ghost"
            className="min-h-9 px-2"
            disabled={list.length === 0 || working}
            onClick={newChat}
          >
            {t('chat.new')}
          </Button>
          <Button
            variant="ghost"
            className="min-h-9 px-3"
            aria-label={t('chat.close')}
            onClick={close}
          >
            <span aria-hidden="true">×</span>
          </Button>
        </div>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-3">
        {standing.data && !ready && (
          <Alert>
            {t('chat.notReady')}{' '}
            <Link to="/settings" className="underline">
              {t('chat.toSettings')}
            </Link>
          </Alert>
        )}
        {paused && <Alert>{t('chat.paused')}</Alert>}
        {list.length === 0 && !working ? (
          <div className="space-y-3 text-sm">
            <p>{t('chat.intro')}</p>
            <ul className="space-y-2">
              {SUGGESTIONS.map((key) => (
                <li key={key}>
                  <Button
                    variant="secondary"
                    className="h-auto min-h-10 w-full justify-start whitespace-normal py-2 text-left"
                    disabled={!canAsk}
                    onClick={() => ask(t(`chat.suggest.${key}`))}
                  >
                    {t(`chat.suggest.${key}`)}
                  </Button>
                </li>
              ))}
            </ul>
            <p>
              <Link to="/strategies/assistant" className="underline">
                {t('chat.strategyHelper')}
              </Link>
            </p>
          </div>
        ) : (
          <ol role="log" aria-label={t('chat.log')} className="space-y-4">
            {list.map((q) => (
              <li key={q.id} className="space-y-2">
                <p className="ml-auto w-fit max-w-[85%] whitespace-pre-line rounded-lg bg-primary px-3 py-2 text-sm text-primary-foreground">
                  <span className="sr-only">{t('chat.you')} </span>
                  {q.question}
                </p>
                {isWorking(q.status) ? (
                  <p role="status" className="text-sm text-muted">
                    {t('chat.working')}
                  </p>
                ) : (
                  <div className="max-w-[95%] space-y-2 rounded-lg bg-border/40 px-3 py-2">
                    <span className="sr-only">{t('chat.helper')} </span>
                    <AnswerBody q={q} compact />
                  </div>
                )}
              </li>
            ))}
            <li ref={end} aria-hidden="true" />
          </ol>
        )}
        {send.isPending && list.length === 0 && (
          <p role="status" className="mt-3 text-sm text-muted">
            {t('chat.working')}
          </p>
        )}
        {send.isError && <Alert>{errorMessage(send.error)}</Alert>}
        {turns.isError && <Alert>{errorMessage(turns.error)}</Alert>}
      </div>

      <form
        onSubmit={submit}
        aria-label={t('chat.form')}
        className="space-y-2 border-t border-border p-3"
      >
        <Textarea
          ref={input}
          rows={2}
          maxLength={500}
          value={draft}
          disabled={!ready || paused}
          aria-label={t('chat.message')}
          placeholder={t('chat.placeholder')}
          className="resize-none font-sans"
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault()
              ask(draft)
            }
          }}
        />
        <div className="flex items-center justify-between gap-2">
          <span className="text-xs text-muted">{t('chat.readOnly')}</span>
          <Button type="submit" disabled={!canAsk || draft.trim().length < 3}>
            {t('chat.send')}
          </Button>
        </div>
      </form>
    </>
  )
}
