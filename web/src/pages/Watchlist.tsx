import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { api, errorMessage, unwrap } from '../api/client'
import { useInstruments, usePrices } from '../api/queries'
import { AddInstrumentDialog } from '../components/AddInstrumentDialog'
import { TypeBadge } from '../components/AssetType'
import { Delta, EmptyState } from '../components/display'
import { PriceChart } from '../components/PriceChart'
import { PriceAlerts } from '../notify/PriceAlerts'
import { Alert, Button, Card, Field, Input, Select } from '../components/ui'
import { useFormat } from '../lib/useFormat'
import { JobStatus } from '../system/JobStatus'

const KEY = ['watchlists'] as const

/** Instruments the owner follows without holding them (FR-INS-05). They are ordinary
 * instruments, so the nightly jobs price them like holdings. */
export function Watchlist() {
  const { t } = useTranslation()
  const lists = useQuery({
    queryKey: KEY,
    queryFn: () => unwrap(api.GET('/api/v1/watchlists')),
    // while the worker is fetching prices for an item, look again every few seconds
    refetchInterval: (query) =>
      query.state.data?.some((l) => l.items.some((i) => i.fetching)) ? 3000 : false,
  })
  if (lists.isPending) return <p role="status">{t('app.loading')}</p>
  if (lists.isError) return <Alert>{errorMessage(lists.error)}</Alert>
  const list = lists.data[0]
  if (!list)
    return <EmptyState title={t('watchlist.empty.title')} body={t('watchlist.empty.body')} />
  return <WatchlistBody list={list} />
}

type List = {
  id: number
  name: string
  items: {
    id: number
    instrument_id: number
    name: string
    isin: string | null
    asset_class: string
    ticker: string | null
    currency: string | null
    note: string | null
    close: string | null
    close_date: string | null
    previous_close: string | null
    stale: boolean
    fetching: boolean
  }[]
}

function dayChange(close: string | null, previous: string | null): string | null {
  if (close === null || previous === null) return null
  const prev = Number(previous)
  if (!prev) return null
  return String((Number(close) - prev) / prev)
}

function WatchlistBody({ list }: { list: List }) {
  const { t } = useTranslation()
  const { num } = useFormat()
  const queryClient = useQueryClient()
  const instruments = useInstruments()
  const [choice, setChoice] = useState('')
  const [adding, setAdding] = useState(false)
  const [shown, setShown] = useState<number | null>(null)
  const refresh = () => queryClient.invalidateQueries({ queryKey: KEY })
  const fetching = list.items.some((i) => i.fetching)
  // when the fetching ends the new prices and history are shown
  const wasFetching = useRef(false)
  useEffect(() => {
    if (wasFetching.current && !fetching) {
      void queryClient.invalidateQueries({ queryKey: ['prices'] })
    }
    wasFetching.current = fetching
  }, [fetching, queryClient])
  const fetchNow = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST('/api/v1/watchlists/{watchlist_id}/refresh', {
          params: { path: { watchlist_id: list.id } },
        }),
      ),
    onSuccess: refresh,
  })

  const watched = new Set(list.items.map((i) => i.instrument_id))
  const options = (instruments.data ?? []).filter((i) => !watched.has(i.id))

  const add = useMutation({
    mutationFn: (instrumentId: number) =>
      unwrap(
        api.POST('/api/v1/watchlists/{watchlist_id}/items', {
          params: { path: { watchlist_id: list.id } },
          body: { instrument_id: instrumentId },
        }),
      ),
    onSuccess: async () => {
      setChoice('')
      await refresh()
    },
  })
  const remove = useMutation({
    mutationFn: (itemId: number) =>
      unwrap(
        api.DELETE('/api/v1/watchlists/{watchlist_id}/items/{item_id}', {
          params: { path: { watchlist_id: list.id, item_id: itemId } },
        }),
      ),
    onSuccess: refresh,
  })
  const note = useMutation({
    mutationFn: ({ itemId, text }: { itemId: number; text: string }) =>
      unwrap(
        api.PATCH('/api/v1/watchlists/{watchlist_id}/items/{item_id}', {
          params: { path: { watchlist_id: list.id, item_id: itemId } },
          body: { note: text.trim() || null },
        }),
      ),
    onSuccess: refresh,
  })

  const selected = list.items.find((i) => i.instrument_id === shown)

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <h1 className="text-2xl font-semibold">{t('nav.watchlist')}</h1>
        <form
          className="flex flex-wrap items-end gap-2"
          onSubmit={(e) => {
            e.preventDefault()
            if (choice) add.mutate(Number(choice))
          }}
        >
          <Field label={t('watchlist.pick')}>
            {(p) => (
              <Select value={choice} onChange={(e) => setChoice(e.target.value)} {...p}>
                <option value="">{t('watchlist.pickPlaceholder')}</option>
                {options.map((i) => (
                  <option key={i.id} value={i.id}>
                    {i.name}
                  </option>
                ))}
              </Select>
            )}
          </Field>
          <Button type="submit" disabled={!choice || add.isPending}>
            {t('watchlist.add')}
          </Button>
          <Button type="button" variant="ghost" onClick={() => setAdding(true)}>
            {t('watchlist.newInstrument')}
          </Button>
          <Button
            type="button"
            variant="secondary"
            onClick={() => fetchNow.mutate()}
            disabled={fetchNow.isPending || fetching || list.items.length === 0}
          >
            {t('watchlist.fetchNow')}
          </Button>
        </form>
      </div>
      {fetching && (
        <p role="status" className="text-sm">
          {t('watchlist.fetching')}
        </p>
      )}
      <JobStatus jobs={['refresh', 'backfill']} from={fetchNow} />
      {fetchNow.isError && <Alert>{errorMessage(fetchNow.error)}</Alert>}
      {add.isError && <Alert>{errorMessage(add.error)}</Alert>}
      {remove.isError && <Alert>{errorMessage(remove.error)}</Alert>}
      {note.isError && <Alert>{errorMessage(note.error)}</Alert>}

      {list.items.length === 0 ? (
        <EmptyState title={t('watchlist.empty.title')} body={t('watchlist.empty.body')} />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <caption className="sr-only">{t('watchlist.caption')}</caption>
            <thead>
              <tr className="border-b border-border text-left">
                <th scope="col" className="py-2 pr-3 font-medium">
                  {t('watchlist.columns.name')}
                </th>
                <th scope="col" className="py-2 pr-3 text-right font-medium">
                  {t('watchlist.columns.price')}
                </th>
                <th scope="col" className="py-2 pr-3 text-right font-medium">
                  {t('watchlist.columns.day')}
                </th>
                <th scope="col" className="py-2 pr-3 font-medium">
                  {t('watchlist.columns.note')}
                </th>
                <th scope="col" className="py-2 font-medium">
                  {t('watchlist.columns.actions')}
                </th>
              </tr>
            </thead>
            <tbody>
              {list.items.map((item) => (
                <tr key={item.id} className="border-b border-border align-top">
                  <td className="py-2 pr-3">
                    <Link to={`/holdings/${item.instrument_id}`} className="hover:underline">
                      {item.name}
                    </Link>
                    <div className="mt-0.5 flex flex-wrap items-center gap-2 text-xs text-muted">
                      <TypeBadge assetClass={item.asset_class} />
                      {item.ticker ?? item.isin ?? ''}
                    </div>
                  </td>
                  <td className="py-2 pr-3 text-right tabular-nums">
                    {item.close === null ? (
                      <span className="text-muted">
                        {item.fetching ? t('watchlist.fetchingItem') : t('watchlist.noPrice')}
                      </span>
                    ) : (
                      <>
                        {num(item.close)} {item.currency}
                        <div className="text-xs text-muted">
                          {item.close_date}
                          {item.stale && ` · ${t('watchlist.stale')}`}
                        </div>
                      </>
                    )}
                  </td>
                  <td className="py-2 pr-3 text-right">
                    <Delta value={dayChange(item.close, item.previous_close)} kind="pct" />
                  </td>
                  <td className="py-2 pr-3">
                    <NoteCell
                      key={`${item.id}:${item.note ?? ''}`}
                      name={item.name}
                      value={item.note ?? ''}
                      onSave={(text) => note.mutate({ itemId: item.id, text })}
                    />
                  </td>
                  <td className="py-2 whitespace-nowrap">
                    <Button
                      variant="ghost"
                      aria-pressed={shown === item.instrument_id}
                      onClick={() =>
                        setShown(shown === item.instrument_id ? null : item.instrument_id)
                      }
                    >
                      {t('watchlist.chart')}
                    </Button>
                    <Button
                      variant="ghost"
                      aria-label={t('watchlist.removeLabel', { name: item.name })}
                      onClick={() => remove.mutate(item.id)}
                    >
                      {t('watchlist.remove')}
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {selected && (
        <>
          <WatchChart instrumentId={selected.instrument_id} name={selected.name} />
          <PriceAlerts instrumentId={selected.instrument_id} name={selected.name} />
        </>
      )}
      <p className="text-sm text-muted">{t('watchlist.alertsHint')}</p>
      <AddInstrumentDialog
        open={adding}
        onClose={() => setAdding(false)}
        onAdded={() => void queryClient.invalidateQueries({ queryKey: ['instruments'] })}
      />
    </div>
  )
}

function NoteCell({
  name,
  value,
  onSave,
}: {
  name: string
  value: string
  onSave: (text: string) => void
}) {
  const { t } = useTranslation()
  const [text, setText] = useState(value)
  return (
    <Input
      aria-label={t('watchlist.noteLabel', { name })}
      value={text}
      maxLength={500}
      placeholder={t('watchlist.notePlaceholder')}
      onChange={(e) => setText(e.target.value)}
      onBlur={() => {
        if (text !== value) onSave(text)
      }}
    />
  )
}

function WatchChart({ instrumentId, name }: { instrumentId: number; name: string }) {
  const { t } = useTranslation()
  const prices = usePrices(instrumentId)
  return (
    <section aria-label={name} className="space-y-2">
      <h2 className="text-lg font-medium">{name}</h2>
      {prices.data && prices.data.length > 0 ? (
        <Card>
          <PriceChart prices={prices.data} markers={[]} label={`${t('position.chart')}: ${name}`} />
        </Card>
      ) : (
        !prices.isPending && <p className="text-muted">{t('position.noPrices')}</p>
      )}
    </section>
  )
}
