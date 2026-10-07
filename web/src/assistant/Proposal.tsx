import { useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { errorMessage } from '../api/client'
import { Alert, Button } from '../components/ui'
import { useStrategies, type Definition } from '../strategies/api'
import { useProposalDiff, useSaveProposal } from './api'
import { describeDefinition } from './proposalText'

/** A proposed strategy, shown before anything is saved: what it does in plain sentences, for a
 * revision what changes, and the document itself. Saving never switches anything on: a new
 * strategy starts off, and a new version only replaces what is running when the strategy it
 * revises is already active, which the owner is told (ADR 0048). */
export function Proposal({
  yaml,
  definition,
  reviseId,
  onSaved,
}: {
  yaml: string
  definition: Definition
  reviseId: number | null
  onSaved: (id: number) => void
}) {
  const { t } = useTranslation()
  const strategies = useStrategies()
  const diff = useProposalDiff()
  const save = useSaveProposal()
  const revising = reviseId === null ? undefined : strategies.data?.find((s) => s.id === reviseId)

  useEffect(() => {
    if (reviseId !== null) diff.mutate({ strategy_id: reviseId, yaml })
    // the comparison is made once for each proposal
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reviseId, yaml])

  const lines = describeDefinition(definition)
  const saveAs = (versionOf: number | null) =>
    save.mutate({ yaml, versionOf }, { onSuccess: (saved) => onSaved(saved.id) })

  return (
    <section aria-label={t('assistant.proposal.title')} className="space-y-3">
      <h3 className="font-medium">{t('assistant.proposal.title')}</h3>
      <ul className="list-disc space-y-1 pl-5 text-sm">
        {lines.map((l, i) => (
          <li key={i}>{t(`assistant.describe.${l.key}`, l.params)}</li>
        ))}
      </ul>
      {reviseId !== null && (
        <details open className="rounded-md border border-border p-3 text-sm">
          <summary className="cursor-pointer font-medium">
            {t('assistant.proposal.diffTitle')}
          </summary>
          {diff.isError && <Alert>{errorMessage(diff.error)}</Alert>}
          {diff.data && !diff.data.changed && (
            <p className="mt-2 text-muted">{t('assistant.proposal.noChange')}</p>
          )}
          {diff.data?.changed && (
            <table className="mt-2 w-full font-mono text-xs">
              <tbody>
                {diff.data.rows
                  .filter((r) => r.kind !== 'same')
                  .map((r, i) => (
                    <tr key={i} className="align-top">
                      <td className="w-24 pr-2 text-muted">{t(`assistant.proposal.${r.kind}`)}</td>
                      <td className="whitespace-pre-wrap pr-2 text-danger">{r.old_text ?? ''}</td>
                      <td className="whitespace-pre-wrap">{r.new_text ?? ''}</td>
                    </tr>
                  ))}
              </tbody>
            </table>
          )}
        </details>
      )}
      <details className="rounded-md border border-border p-3 text-sm">
        <summary className="cursor-pointer font-medium">
          {t('assistant.proposal.yamlTitle')}
        </summary>
        <pre className="mt-2 max-h-96 overflow-auto whitespace-pre-wrap font-mono text-xs">
          {yaml}
        </pre>
      </details>
      {revising?.mode === 'active' && (
        <Alert>{t('assistant.proposal.activeWarn', { name: revising.name })}</Alert>
      )}
      <p className="text-xs text-muted">{t('assistant.proposal.offNote')}</p>
      <div className="flex flex-wrap items-center gap-3">
        {reviseId !== null && revising && (
          <Button disabled={save.isPending} onClick={() => saveAs(reviseId)}>
            {t('assistant.proposal.saveVersion', { name: revising.name })}
          </Button>
        )}
        <Button
          variant={reviseId !== null ? 'secondary' : 'primary'}
          disabled={save.isPending}
          onClick={() => saveAs(null)}
        >
          {t('assistant.proposal.saveNew')}
        </Button>
      </div>
      {save.isError && <Alert>{errorMessage(save.error)}</Alert>}
    </section>
  )
}
