import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { Strategies } from './pages/Strategies'
import { GENERAL_US, mockApi, problem, renderAt } from './test-utils'

afterEach(() => vi.unstubAllGlobals())

const YAML = 'strategy:\n  name: Core\n  sleeves:\n    - { id: equity, target_pct: 60 }\n'
const DEFINITION = {
  name: 'Core',
  principles: ['Direct new money first.'],
  sleeves: [
    {
      id: 'equity',
      members: ['IE00B5BMR087'],
      target_pct: '60',
      soft_band_pp: '5',
      hard_band_pp: null,
      trim_threshold_pct: null,
    },
  ],
  rules: [
    {
      id: 'drift',
      type: 'drift_band',
      severity: 'medium',
      cooldown_days: 7,
      worsen_step: null,
      enabled: true,
      applies_to: 'all',
    },
  ],
  theses: [],
  contribution_plan: null,
}
const strategy = (over: Record<string, unknown> = {}) => ({
  id: 1,
  name: 'Core',
  mode: 'off',
  current: {
    version: 2,
    created_at: '2026-10-05T10:00:00Z',
    note: null,
    yaml: YAML,
    definition: DEFINITION,
  },
  versions: [
    { version: 2, created_at: '2026-10-05T10:00:00Z', note: 'tighter band' },
    { version: 1, created_at: '2026-10-04T10:00:00Z', note: null },
  ],
  ...over,
})
const summary = { id: 1, name: 'Core', mode: 'off', version: 2, updated_at: '2026-10-05T10:00:00Z' }

function routes(extra: Record<string, unknown> = {}) {
  return {
    '/api/v1/settings/general': GENERAL_US,
    '/api/v1/strategies': [summary],
    '/api/v1/strategies/1': strategy(),
    ...extra,
  }
}

describe('strategies (FR-ST-01, FR-ST-02)', () => {
  it('starts from the starter when there is none yet', async () => {
    let created = false
    const { calls } = mockApi({
      '/api/v1/settings/general': GENERAL_US,
      'GET /api/v1/strategies': () => (created ? [summary] : []),
      '/api/v1/strategies/starter': { yaml: YAML, definition: DEFINITION },
      'POST /api/v1/strategies': () => {
        created = true
        return strategy()
      },
      '/api/v1/strategies/1': strategy(),
    })
    renderAt(<Strategies />)
    expect(await screen.findByText('No strategy yet')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'New strategy' }))
    expect(await screen.findByRole('heading', { level: 2, name: 'Core' })).toBeInTheDocument()
    expect(calls.find((c) => c.method === 'POST')?.body).toEqual({ yaml: YAML, note: 'starter' })
  })

  it('saves the form as a new version', async () => {
    const { calls } = mockApi(routes({ 'POST /api/v1/strategies/1/versions': strategy() }))
    renderAt(<Strategies />)
    const target = await screen.findByLabelText('Target % of sleeve 1')
    await userEvent.clear(target)
    await userEvent.type(target, '55')
    await userEvent.type(screen.getByLabelText('What changed (optional)'), 'less equity')
    await userEvent.click(screen.getByRole('button', { name: 'Save as a new version' }))
    await waitFor(() => expect(calls.some((c) => c.path.endsWith('/versions'))).toBe(true))
    const body = calls.find((c) => c.path.endsWith('/versions'))?.body as {
      definition: { sleeves: { target_pct: string }[] }
      note: string
    }
    expect(body.definition.sleeves[0].target_pct).toBe('55')
    expect(body.note).toBe('less equity')
  })

  it('shows a YAML problem on its line and refuses to save', async () => {
    mockApi(
      routes({
        'POST /api/v1/strategies/check': {
          ok: true,
          problems: [],
          yaml: YAML,
          definition: DEFINITION,
        },
        'POST /api/v1/strategies/1/versions': () =>
          problem(422, 'Invalid strategy', 'line 4: Input should be less than or equal to 100', {
            problems: [
              {
                line: 4,
                path: 'strategy.sleeves[0].target_pct',
                message: 'Input should be less than or equal to 100',
              },
            ],
          }),
      }),
    )
    renderAt(<Strategies />)
    await userEvent.click(await screen.findByRole('tab', { name: 'YAML' }))
    const editor = await screen.findByLabelText('Strategy as YAML')
    expect(editor).toHaveValue(YAML)
    await userEvent.click(screen.getByRole('button', { name: 'Save as a new version' }))
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Line 4:')
    expect(alert).toHaveTextContent('less than or equal to 100')
    await userEvent.click(within(alert).getByRole('button', { name: 'Line 4:' }))
    expect(editor).toHaveFocus()
  })

  it('keeps you in the YAML view when the YAML does not parse', async () => {
    mockApi(
      routes({
        'POST /api/v1/strategies/check': (request: Request) =>
          request
            .clone()
            .json()
            .then((b: { yaml?: string }) =>
              b.yaml !== undefined
                ? {
                    ok: false,
                    problems: [
                      {
                        line: 2,
                        path: '',
                        message: 'YAML syntax: mapping values are not allowed here',
                      },
                    ],
                    yaml: null,
                    definition: null,
                  }
                : { ok: true, problems: [], yaml: YAML, definition: DEFINITION },
            ),
      }),
    )
    renderAt(<Strategies />)
    await userEvent.click(await screen.findByRole('tab', { name: 'YAML' }))
    await userEvent.type(await screen.findByLabelText('Strategy as YAML'), ': broken')
    await userEvent.click(screen.getByRole('tab', { name: 'Form' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('YAML syntax')
    expect(screen.getByRole('tab', { name: 'YAML' })).toHaveAttribute('aria-selected', 'true')
  })

  it('makes a strategy active and runs the rules on demand', async () => {
    const { calls } = mockApi(
      routes({
        'POST /api/v1/strategies/1/mode': [{ ...summary, mode: 'active' }],
        'POST /api/v1/strategies/run': { status: 'queued' },
      }),
    )
    renderAt(<Strategies />)
    await userEvent.click(await screen.findByRole('button', { name: 'Make active' }))
    await waitFor(() => expect(calls.some((c) => c.path.endsWith('/mode'))).toBe(true))
    expect(calls.find((c) => c.path.endsWith('/mode'))?.body).toEqual({ mode: 'active' })
    await userEvent.click(screen.getByRole('button', { name: 'Run rules now' }))
    expect(await screen.findByText('The rules run within a few seconds.')).toBeInTheDocument()
  })
})

describe('rules, signals and history (FR-ST-02, FR-ST-03)', () => {
  it('says which rules wait for what and marks shadow signals', async () => {
    mockApi(
      routes({
        '/api/v1/strategies/1/status': {
          rules: [
            { rule_id: 'drift', rule_type: 'drift_band', ready: true, reason: null },
            {
              rule_id: 'cc',
              rule_type: 'concentration_limit',
              ready: false,
              reason: 'Needs the holdings inside your ETFs, which arrive in Phase 4.',
            },
          ],
          sleeves: [
            { id: 'equity', weight: '0.7', target: '60', soft_band_pp: '5', hard_band_pp: null },
          ],
          conditions_true: 1,
        },
        '/api/v1/strategies/signals': [
          {
            id: 3,
            strategy_id: 1,
            strategy_name: 'Core',
            version: 2,
            rule_id: 'drift',
            rule_type: 'drift_band',
            subject: 'equity',
            ts: '2026-10-05T10:00:00Z',
            severity: 'medium',
            title: 'equity is 10.0 pp over its target (soft band 5 pp)',
            message: 'Direct new money elsewhere.',
            value: '10',
            state: 'new',
            shadow: true,
          },
        ],
      }),
    )
    renderAt(<Strategies />)
    await userEvent.click(await screen.findByRole('tab', { name: 'Rules and signals' }))
    expect(await screen.findByText(/arrive in Phase 4/)).toBeInTheDocument()
    expect(screen.getByText('Watching')).toBeInTheDocument()
    expect(screen.getByText('1 condition is true right now.')).toBeInTheDocument()
    expect(screen.getByText(/equity is 10.0 pp over/)).toBeInTheDocument()
    expect(screen.getByText('Shadow', { selector: 'span' })).toBeInTheDocument()
  })

  it('compares two versions side by side', async () => {
    mockApi(
      routes({
        '/api/v1/strategies/1/diff': {
          old_version: 1,
          new_version: 2,
          rows: [
            {
              kind: 'same',
              old_line: 1,
              old_text: 'strategy:',
              new_line: 1,
              new_text: 'strategy:',
            },
            {
              kind: 'changed',
              old_line: 2,
              old_text: '  target_pct: 70',
              new_line: 2,
              new_text: '  target_pct: 60',
            },
          ],
        },
      }),
    )
    renderAt(<Strategies />)
    await userEvent.click(await screen.findByRole('tab', { name: 'History' }))
    const table = await screen.findByRole('table', { name: 'Changes from version 1 to version 2' })
    const changed = within(table)
      .getByText(/target_pct: 60/)
      .closest('tr') as HTMLElement
    expect(changed).toHaveAttribute('data-kind', 'changed')
    expect(changed).toHaveTextContent('target_pct: 70')
    expect(screen.getByText(/tighter band/)).toBeInTheDocument()
  })
})

describe('calculators (FR-ST-05)', () => {
  it('shows the orders with the change and copies them into drafts', async () => {
    const { calls } = mockApi(
      routes({
        'POST /api/v1/strategies/1/calculate': {
          orders: [
            {
              side: 'buy',
              sleeve: 'gold',
              instrument_id: 7,
              name: 'Gold ETC',
              quantity: '6',
              price: '50',
              currency: 'EUR',
              price_eur: '50',
              amount_eur: '300',
              account_id: null,
              realized_pnl_eur: null,
            },
          ],
          remainder_eur: '0',
          notes: [],
          before: { equity: '0.7', gold: '0.3' },
          after: { equity: '0.5', gold: '0.5' },
        },
        'POST /api/v1/strategies/orders/to-drafts': { transaction_ids: [41] },
      }),
    )
    renderAt(<Strategies />)
    await userEvent.click(await screen.findByRole('tab', { name: 'Calculators' }))
    await userEvent.type(screen.getByLabelText('New money (EUR)'), '300')
    await userEvent.click(screen.getByRole('button', { name: 'Calculate' }))
    const orders = await screen.findByRole('table', { name: 'Orders' })
    expect(within(orders).getByText('Gold ETC').closest('tr')).toHaveTextContent(
      /Buy.*gold.*Gold ETC.*6/,
    )
    expect(calls.find((c) => c.path.endsWith('/calculate'))?.body).toEqual({
      kind: 'allocator',
      amount_eur: '300',
      sleeve: null,
    })
    expect(screen.getByText(/Left unspent/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Copy to draft transactions' }))
    expect(await screen.findByText('1 draft transaction made.')).toBeInTheDocument()
    const sent = calls.find((c) => c.path.endsWith('/to-drafts'))?.body as { orders: unknown[] }
    expect(sent.orders).toEqual([
      { side: 'buy', instrument_id: 7, quantity: '6', price: '50', account_id: null },
    ])
    expect(screen.getByRole('link', { name: 'Confirm them on Insights' })).toHaveAttribute(
      'href',
      '/insights',
    )
  })
})

describe('orders from a strategy on Insights (FR-ST-05)', () => {
  it('confirms a draft buy with the price actually paid and the fees', async () => {
    const draft = {
      id: 41,
      account_id: 1,
      account_name: 'Degiro',
      instrument_id: 7,
      instrument_name: 'Gold ETC',
      ticker: 'GLD',
      type: 'buy',
      trade_date: '2026-10-05',
      settle_date: null,
      quantity: '6',
      price: '50',
      currency: 'EUR',
      fx_rate_to_eur: '1',
      fees: '0',
      taxes: '0',
      net_amount_eur: null,
      note: 'New money calculator, Core',
      source: 'strategy',
      status: 'draft',
    }
    const { calls } = mockApi({
      '/api/v1/settings/general': GENERAL_US,
      '/api/v1/transactions': (request: Request) =>
        new URL(request.url).searchParams.get('status') === 'draft'
          ? { items: [draft], total: 1, next_offset: null }
          : { items: [], total: 0, next_offset: null },
      '/api/v1/corporate-actions': [],
      'POST /api/v1/transactions/41/confirm': { ...draft, status: 'posted' },
    })
    const { OrderDrafts } = await import('./strategies/OrderDrafts')
    renderAt(<OrderDrafts />)
    const price = await screen.findByLabelText('Price paid for Gold ETC')
    await userEvent.clear(price)
    await userEvent.type(price, '50.4')
    await userEvent.type(screen.getByLabelText('Fees for Gold ETC'), '1')
    await userEvent.click(screen.getByRole('button', { name: 'Confirm the order for Gold ETC' }))
    await waitFor(() => expect(calls.some((c) => c.path.endsWith('/confirm'))).toBe(true))
    expect(calls.find((c) => c.path.endsWith('/confirm'))?.body).toEqual({
      price: '50.4',
      fees: '1',
    })
  })
})

describe('sleeves follow the active strategy', () => {
  it('says which strategy sets the targets and only lets the name change', async () => {
    const { calls } = mockApi({
      '/api/v1/sleeves': [
        {
          id: 1,
          name: 'equity',
          target_pct: '60',
          band_pct: '5',
          sort_order: 1,
          instrument_count: 1,
          managed_by: 'Core',
        },
      ],
      'PATCH /api/v1/sleeves/1': {
        id: 1,
        name: 'Equity',
        target_pct: '60',
        band_pct: '5',
        sort_order: 1,
        instrument_count: 1,
        managed_by: 'Core',
      },
    })
    const { SleevesTab } = await import('./components/SleevesTab')
    renderAt(<SleevesTab />)
    expect(await screen.findByRole('note')).toHaveTextContent('active strategy Core')
    await userEvent.click(screen.getByRole('button', { name: 'Edit' }))
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByLabelText('Target share (%)')).toBeDisabled()
    const name = within(dialog).getByLabelText('Name')
    await userEvent.clear(name)
    await userEvent.type(name, 'Equity')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Save sleeve' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'PATCH')).toBe(true))
    expect(calls.find((c) => c.method === 'PATCH')?.body).toEqual({ name: 'Equity' })
  })
})
