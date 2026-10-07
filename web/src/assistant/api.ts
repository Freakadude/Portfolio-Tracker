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
