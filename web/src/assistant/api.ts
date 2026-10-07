import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, unwrap } from '../api/client'
import type { components } from '../api/schema'

type S = components['schemas']
export type Note = S['NoteOut']
export type Notes = S['NotesOut']

export const NOTES_KEY = ['assistant', 'notes'] as const

export function useNotes() {
  return useQuery({
    queryKey: NOTES_KEY,
    queryFn: () => unwrap(api.GET('/api/v1/assistant/notes')),
  })
}

export function useBackgroundRequest() {
  return useQuery({
    queryKey: ['assistant', 'notes', 'request'],
    queryFn: () => unwrap(api.GET('/api/v1/assistant/notes/request')),
    staleTime: Infinity,
  })
}

export function useAddNote() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: {
      title: string
      body: string
      source?: 'written' | 'pasted' | 'chat_export'
    }) =>
      unwrap(
        api.POST('/api/v1/assistant/notes', {
          body: { source: 'written', ...body, use_in_helper: true },
        }),
      ),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: NOTES_KEY }),
  })
}

export function useChangeNote() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({
      id,
      ...body
    }: {
      id: number
      title?: string
      body?: string
      use_in_helper?: boolean
    }) =>
      unwrap(
        api.PATCH('/api/v1/assistant/notes/{note_id}', {
          params: { path: { note_id: id } },
          body,
        }),
      ),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: NOTES_KEY }),
  })
}

export function useDeleteNote() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: number) =>
      unwrap(
        api.DELETE('/api/v1/assistant/notes/{note_id}', { params: { path: { note_id: id } } }),
      ),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: NOTES_KEY }),
  })
}

export type ChatScan = S['ChatScanOut']
export type ChatInfo = S['ChatInfoOut']
export type ChatEstimate = S['ChatEstimateOut']
export type ChatSummaries = S['ChatSummariesOut']

function upload(file: File, ids?: string[]) {
  const form = new FormData()
  form.append('file', file)
  if (ids) form.append('ids', ids.join(','))
  return form
}

export function useScanChats() {
  return useMutation({
    mutationFn: (file: File) =>
      unwrap(
        api.POST('/api/v1/assistant/chats/scan', {
          body: {} as never,
          bodySerializer: () => upload(file),
        }),
      ),
  })
}

export function useEstimateChats() {
  return useMutation({
    mutationFn: ({ file, ids }: { file: File; ids: string[] }) =>
      unwrap(
        api.POST('/api/v1/assistant/chats/estimate', {
          body: {} as never,
          bodySerializer: () => upload(file, ids),
        }),
      ),
  })
}

export function useSummariseChats() {
  return useMutation({
    mutationFn: ({ file, ids }: { file: File; ids: string[] }) =>
      unwrap(
        api.POST('/api/v1/assistant/chats/summarise', {
          body: {} as never,
          bodySerializer: () => upload(file, ids),
        }),
      ),
  })
}

export type HelperPrompt = S['HelperPromptOut']
export type ProposalDiff = S['ProposalDiffOut']

export function useHelperPrompt(mode: 'new' | 'revise', strategy: number | null, draftNow = false) {
  return useQuery({
    queryKey: ['assistant', 'prompt', mode, strategy, draftNow],
    retry: false,
    enabled: mode === 'new' || strategy !== null,
    queryFn: () =>
      unwrap(
        api.GET('/api/v1/assistant/prompt', {
          params: {
            query: { mode, strategy: mode === 'revise' ? strategy : null, draft_now: draftNow },
          },
        }),
      ),
  })
}

export function useProposalDiff() {
  return useMutation({
    mutationFn: (body: { strategy_id: number; yaml: string }) =>
      unwrap(api.POST('/api/v1/assistant/diff', { body })),
  })
}

/** Save a proposed strategy: as a new strategy (always switched off) or as a new version of the
 * one it revises. */
export function useSaveProposal() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ yaml, versionOf }: { yaml: string; versionOf: number | null }) => {
      const body = { yaml, note: 'strategy helper' }
      return versionOf === null
        ? unwrap(api.POST('/api/v1/strategies', { body }))
        : unwrap(
            api.POST('/api/v1/strategies/{strategy_id}/versions', {
              params: { path: { strategy_id: versionOf } },
              body,
            }),
          )
    },
    onSuccess: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: ['strategies'] }),
        queryClient.invalidateQueries({ queryKey: ['sleeves'] }),
      ]),
  })
}

export type HelperSession = S['AssistantSessionOut']

export function useAgentStanding() {
  return useQuery({
    queryKey: ['agent', 'usage'],
    queryFn: () => unwrap(api.GET('/api/v1/agent/usage')),
  })
}

const sessionKey = (id: number | null) => ['assistant', 'session', id] as const

export function useSession(id: number | null) {
  return useQuery({
    queryKey: sessionKey(id),
    enabled: id !== null,
    queryFn: () =>
      unwrap(
        api.GET('/api/v1/assistant/sessions/{session_id}', {
          params: { path: { session_id: id ?? 0 } },
        }),
      ),
  })
}

export function useStartSession() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: {
      mode: 'new' | 'revise'
      strategy_id: number | null
      from_notes?: boolean
    }) => unwrap(api.POST('/api/v1/assistant/sessions', { body: { from_notes: false, ...body } })),
    onSuccess: (session) => {
      queryClient.setQueryData(sessionKey(session.id), session)
      void queryClient.invalidateQueries({ queryKey: ['agent'] })
    },
  })
}

export function useSay(id: number) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (text: string) =>
      unwrap(
        api.POST('/api/v1/assistant/sessions/{session_id}/messages', {
          params: { path: { session_id: id } },
          body: { text },
        }),
      ),
    onSuccess: (session) => {
      queryClient.setQueryData(sessionKey(id), session)
      void queryClient.invalidateQueries({ queryKey: ['agent'] })
    },
  })
}
