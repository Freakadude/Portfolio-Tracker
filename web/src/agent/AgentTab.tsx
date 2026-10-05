import { useTranslation } from 'react-i18next'
import { errorMessage } from '../api/client'
import { SectionForm } from '../components/SectionForm'
import { Alert, Button } from '../components/ui'
import { useAgentBudget, useTestKey } from './api'

/** Settings, Agent: the month's cost against the budget, a test of the saved key, and every
 * agent setting (models per run type, the review time, trusted search domains, the budget, the
 * price table, privacy, and the switch that turns the agent off) (FR-AG-09). With the agent off,
 * rules, alerts and notifications keep working. */
export function AgentTab() {
  const { t } = useTranslation()
  const budget = useAgentBudget()
  const test = useTestKey()
  const b = budget.data
  return (
    <div className="space-y-6">
      <p className="text-sm text-muted">{t('agentSettings.intro')}</p>
      {budget.isError && <Alert>{errorMessage(budget.error)}</Alert>}
      {b && (
        <dl className="grid gap-2 text-sm sm:grid-cols-2">
          <div>
            <dt className="text-muted">{t('agentSettings.month', { month: b.month })}</dt>
            <dd className="tabular-nums">
              {t('agentSettings.spent', {
                spent: Number(b.spent_eur).toFixed(2),
                budget: b.budget_eur,
                left: Number(b.remaining_eur).toFixed(2),
              })}
            </dd>
          </div>
          <div>
            <dt className="text-muted">{t('agentSettings.newsShare')}</dt>
            <dd className="tabular-nums">
              {t('agentSettings.newsSpent', {
                spent: Number(b.news_spent_eur).toFixed(2),
                share: b.news_share_eur,
              })}
            </dd>
          </div>
          <div>
            <dt className="text-muted">{t('agentSettings.runs')}</dt>
            <dd className="tabular-nums">
              {t('agentSettings.runsValue', {
                month: b.runs_this_month,
                today: b.runs_today,
                cap: b.daily_run_cap,
              })}
            </dd>
          </div>
          <div>
            <dt className="text-muted">{t('agentSettings.state')}</dt>
            <dd>
              {!b.enabled
                ? t('agentSettings.off')
                : !b.key_set
                  ? t('agentSettings.noKey')
                  : b.paused
                    ? t('agentSettings.paused')
                    : t('agentSettings.on')}
            </dd>
          </div>
        </dl>
      )}
      <div className="flex flex-wrap items-center gap-2">
        <Button
          variant="secondary"
          onClick={() => test.mutate()}
          disabled={test.isPending || !b?.key_set}
        >
          {t('agentSettings.test')}
        </Button>
        {!b?.key_set && (
          <span className="text-sm text-muted">{t('agentSettings.saveKeyFirst')}</span>
        )}
        {test.isSuccess && (
          <span role="status" className="text-sm text-gain">
            {t('agentSettings.testOk', {
              model: test.data.model,
              cost: Number(test.data.cost_eur).toFixed(5),
            })}
          </span>
        )}
      </div>
      {test.isError && <Alert>{errorMessage(test.error)}</Alert>}
      <SectionForm section="agent" />
      <p className="text-xs text-muted">{t('agentSettings.pricesHint')}</p>
    </div>
  )
}
