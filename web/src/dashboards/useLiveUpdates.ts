import { useQueryClient } from '@tanstack/react-query'
import { useEffect } from 'react'

/** Listens for the worker's news (new closes, quotes, finished jobs) and refreshes what depends
 * on it, so a widget shows a new close without a reload (FR-DB-04). The browser reconnects and
 * resumes by itself if the connection drops. */
export function useLiveUpdates() {
  const queryClient = useQueryClient()
  useEffect(() => {
    if (typeof EventSource === 'undefined') return
    const source = new EventSource('/api/v1/events')
    const prices = () => {
      for (const key of ['widget-data', 'positions', 'portfolio', 'instruments'])
        void queryClient.invalidateQueries({ queryKey: [key] })
    }
    const jobs = () => void queryClient.invalidateQueries({ queryKey: ['system'] })
    source.addEventListener('price_update', prices)
    source.addEventListener('job_status', jobs)
    // a new inbox item: the bell's count and the inbox (FR-NT-01)
    const inbox = () => {
      void queryClient.invalidateQueries({ queryKey: ['notifications'] })
      void queryClient.invalidateQueries({ queryKey: ['drafts'] })
    }
    source.addEventListener('notification', inbox)
    // the agent made or changed a recommendation: Insights, the widgets and the run list
    const recommendation = () => {
      for (const key of ['recommendations', 'agent', 'widget-data'])
        void queryClient.invalidateQueries({ queryKey: [key] })
    }
    source.addEventListener('recommendation', recommendation)
    return () => source.close()
  }, [queryClient])
}
