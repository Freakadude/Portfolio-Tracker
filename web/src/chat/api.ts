import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useCallback, useState } from 'react'
import { api, unwrap } from '../api/client'
import { AGENT_KEY } from '../agent/api'

const WORKING = ['queued', 'running']
const OPEN_KEY = 'folio.chat.open'
const THREAD_KEY = 'folio.chat.thread'

function read(key: string): string | null {
  try {
    return window.localStorage.getItem(key)
  } catch {
    return null
  }
}

function write(key: string, value: string | null) {
  try {
    if (value === null) window.localStorage.removeItem(key)
    else window.localStorage.setItem(key, value)
  } catch {
    // private window or blocked storage: the panel simply forgets its state on reload
  }
}

function newThreadId(): string {
  const id = globalThis.crypto?.randomUUID?.()
  return id ?? `chat-${Date.now().toString(36)}${Math.random().toString(36).slice(2, 10)}`
}

/** Whether the side panel is open, remembered in this browser. */
export function useChatOpen(): [boolean, (open: boolean) => void] {
  const [open, setOpen] = useState(() => read(OPEN_KEY) === '1')
  const set = useCallback((value: boolean) => {
    setOpen(value)
    write(OPEN_KEY, value ? '1' : '0')
  }, [])
  return [open, set]
}

/** The id of the current chat, kept in this browser; "new chat" makes another one. */
export function useChatThread(): [string, () => void] {
  const [thread, setThread] = useState(() => {
    const saved = read(THREAD_KEY)
    if (saved && /^[A-Za-z0-9_-]{8,40}$/.test(saved)) return saved
    const fresh = newThreadId()
    write(THREAD_KEY, fresh)
    return fresh
  })
  const fresh = useCallback(() => {
    const id = newThreadId()
    write(THREAD_KEY, id)
    setThread(id)
  }, [])
  return [thread, fresh]
}

const chatKey = (thread: string) => [...AGENT_KEY, 'chat', thread] as const

/** The turns of a chat, refreshed every couple of seconds while the worker is still answering. */
export function useChatTurns(thread: string, enabled: boolean) {
  return useQuery({
    queryKey: chatKey(thread),
    enabled,
    queryFn: () => unwrap(api.GET('/api/v1/agent/chat/{thread}', { params: { path: { thread } } })),
    refetchInterval: (query) =>
      query.state.data?.some((q) => WORKING.includes(q.status)) ? 2000 : false,
  })
}

/** Put the next question of a chat; `page` is the route the owner is on. */
export function useChatSend(thread: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ question, page }: { question: string; page: string }) =>
      unwrap(api.POST('/api/v1/agent/ask', { body: { question, thread, page } })),
    // returned, so the sending state lasts until the new turn is on screen
    onSuccess: () => queryClient.invalidateQueries({ queryKey: chatKey(thread) }),
  })
}

export const isWorking = (status: string) => WORKING.includes(status)
