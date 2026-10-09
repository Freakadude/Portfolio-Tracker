import { useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, Navigate, useNavigate, useParams } from 'react-router-dom'
import { errorMessage } from '../api/client'
import { Loading } from '../components/Gate'
import { Badge, Dialog, EmptyState } from '../components/display'
import { Alert, Button, Field, Input, Select } from '../components/ui'
import {
  exportDashboard,
  useDashboard,
  useDashboardActions,
  useDashboards,
  useTabDashboard,
  useTemplates,
  type DashboardSummary,
} from '../dashboards/api'
import { LazyDashboardHost as DashboardHost } from '../dashboards/LazyHost'

/** One dashboard by its address; Home shows the default one. */
export function DashboardPage() {
  const { dashboardId } = useParams()
  const dashboard = useDashboard(Number(dashboardId))
  if (dashboard.isError) return <Alert>{errorMessage(dashboard.error)}</Alert>
  if (!dashboard.data) return <Loading />
  return <DashboardHost key={dashboard.data.id} dashboard={dashboard.data} />
}

/** The Dashboards tab: the dashboard the owner chose for it, or else the list. */
export function DashboardsEntry() {
  const list = useDashboards()
  const [tab] = useTabDashboard()
  if (tab !== null) {
    if (list.isPending) return <Loading />
    if (list.data?.some((d) => d.id === tab)) return <Navigate to={`/dashboards/${tab}`} replace />
  }
  return <Dashboards />
}

function download(name: string, document: Record<string, unknown>) {
  const blob = new Blob([JSON.stringify(document, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const link = window.document.createElement('a')
  link.href = url
  link.download = `${name.replace(/[^\w-]+/g, '_')}.folio-dashboard.json`
  link.click()
  URL.revokeObjectURL(url)
}

/** The list of dashboards: create (blank or from a template), rename, duplicate, reorder, set
 * the default, delete, export and import (FR-DB-01, FR-DB-07). */
export function Dashboards() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const list = useDashboards()
  const templates = useTemplates()
  const actions = useDashboardActions()
  const [name, setName] = useState('')
  const [template, setTemplate] = useState('')
  const [renaming, setRenaming] = useState<DashboardSummary | null>(null)
  const [newName, setNewName] = useState('')
  const [importError, setImportError] = useState<string | null>(null)
  const rows = list.data ?? []
  const failure = [
    actions.create,
    actions.rename,
    actions.remove,
    actions.duplicate,
    actions.makeDefault,
    actions.reorder,
  ]
    .map((m) => m.error)
    .find(Boolean)

  function create(e: FormEvent) {
    e.preventDefault()
    const chosen = templates.data?.find((x) => x.key === template)
    const finalName = name.trim() || chosen?.name || ''
    if (!finalName) return
    actions.create.mutate(
      { name: finalName, template: template || null },
      {
        onSuccess: (d) => {
          setName('')
          navigate(`/dashboards/${d.id}`)
        },
      },
    )
  }

  function move(index: number, step: -1 | 1) {
    const ids = rows.map((r) => r.id)
    const target = index + step
    if (target < 0 || target >= ids.length) return
    ;[ids[index], ids[target]] = [ids[target], ids[index]]
    actions.reorder.mutate(ids)
  }

  async function importFile(file: File | undefined) {
    setImportError(null)
    if (!file) return
    try {
      const document = JSON.parse(await file.text()) as Record<string, unknown>
      actions.importDocument.mutate(document, {
        onSuccess: (d) => navigate(`/dashboards/${d.id}`),
        onError: (err) => setImportError(errorMessage(err)),
      })
    } catch {
      setImportError(t('dashboards.notJson'))
    }
  }

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold">{t('dashboards.title')}</h1>
      {failure !== undefined && <Alert>{errorMessage(failure)}</Alert>}

      <form
        onSubmit={create}
        className="grid max-w-3xl gap-3 sm:grid-cols-[1fr_1fr_auto] sm:items-end"
      >
        <Field label={t('dashboards.name')}>
          {(p) => <Input value={name} onChange={(e) => setName(e.target.value)} {...p} />}
        </Field>
        <Field label={t('dashboards.template')}>
          {(p) => (
            <Select value={template} onChange={(e) => setTemplate(e.target.value)} {...p}>
              <option value="">{t('dashboards.blank')}</option>
              {templates.data?.map((x) => (
                <option key={x.key} value={x.key}>
                  {x.name}
                </option>
              ))}
            </Select>
          )}
        </Field>
        <Button type="submit" disabled={actions.create.isPending}>
          {t('dashboards.create')}
        </Button>
      </form>
      {template && (
        <p className="max-w-3xl text-sm text-muted">
          {templates.data?.find((x) => x.key === template)?.description}
        </p>
      )}

      {rows.length === 0 ? (
        <EmptyState title={t('dashboards.empty.title')} body={t('dashboards.empty.body')} />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <caption className="sr-only">{t('dashboards.caption')}</caption>
            <thead>
              <tr className="border-b border-border text-left">
                <th scope="col" className="py-2 pr-3 font-medium">
                  {t('dashboards.name')}
                </th>
                <th scope="col" className="py-2 pr-3 font-medium">
                  {t('dashboards.widgets')}
                </th>
                <th scope="col" className="py-2 font-medium">
                  {t('transactions.columns.actions')}
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((d, i) => (
                <tr key={d.id} className="border-b border-border">
                  <td className="py-2 pr-3">
                    <Link
                      to={`/dashboards/${d.id}`}
                      className="font-medium underline-offset-2 hover:underline"
                    >
                      {d.name}
                    </Link>{' '}
                    {d.is_default && <Badge tone="good">{t('dashboards.default')}</Badge>}
                  </td>
                  <td className="py-2 pr-3 tabular-nums">{d.widget_count}</td>
                  <td className="py-2">
                    <div className="flex flex-wrap gap-1">
                      <Button
                        variant="ghost"
                        onClick={() => {
                          setRenaming(d)
                          setNewName(d.name)
                        }}
                      >
                        {t('dashboards.rename')}
                      </Button>
                      <Button
                        variant="ghost"
                        onClick={() =>
                          actions.duplicate.mutate(d.id, {
                            onSuccess: (copy) => navigate(`/dashboards/${copy.id}`),
                          })
                        }
                      >
                        {t('dashboards.duplicate')}
                      </Button>
                      {!d.is_default && (
                        <Button variant="ghost" onClick={() => actions.makeDefault.mutate(d.id)}>
                          {t('dashboards.makeDefault')}
                        </Button>
                      )}
                      <Button
                        variant="ghost"
                        onClick={() => move(i, -1)}
                        disabled={i === 0}
                        aria-label={t('dashboards.moveUp', { name: d.name })}
                      >
                        ↑
                      </Button>
                      <Button
                        variant="ghost"
                        onClick={() => move(i, 1)}
                        disabled={i === rows.length - 1}
                        aria-label={t('dashboards.moveDown', { name: d.name })}
                      >
                        ↓
                      </Button>
                      <Button
                        variant="ghost"
                        onClick={() =>
                          void exportDashboard(d.id).then((doc) => download(d.name, doc))
                        }
                      >
                        {t('dashboards.export')}
                      </Button>
                      <Button
                        variant="ghost"
                        onClick={() => {
                          if (window.confirm(t('dashboards.deleteConfirm', { name: d.name })))
                            actions.remove.mutate(d.id)
                        }}
                      >
                        {t('dashboards.delete')}
                      </Button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <section className="max-w-xl space-y-2">
        <h2 className="text-lg font-semibold">{t('dashboards.import')}</h2>
        <Field label={t('dashboards.importFile')} hint={t('dashboards.importHint')}>
          {(p) => (
            <Input
              type="file"
              accept=".json,application/json"
              onChange={(e) => void importFile(e.target.files?.[0])}
              {...p}
            />
          )}
        </Field>
        {importError && <Alert>{importError}</Alert>}
      </section>

      {renaming && (
        <Dialog
          open
          onClose={() => setRenaming(null)}
          title={t('dashboards.renameTitle', { name: renaming.name })}
        >
          <form
            className="space-y-3"
            onSubmit={(e) => {
              e.preventDefault()
              actions.rename.mutate(
                { id: renaming.id, name: newName },
                { onSuccess: () => setRenaming(null) },
              )
            }}
          >
            <Field label={t('dashboards.name')}>
              {(p) => <Input value={newName} onChange={(e) => setNewName(e.target.value)} {...p} />}
            </Field>
            <Button type="submit">{t('app.save')}</Button>
          </form>
        </Dialog>
      )}
    </div>
  )
}
