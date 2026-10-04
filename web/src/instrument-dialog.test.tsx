import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AddInstrumentDialog } from './components/AddInstrumentDialog'
import { GENERAL_US, mockApi, problem, renderAt } from './test-utils'

const resolution = {
  isin: 'IE00B5BMR087',
  name: 'iShares Core S&P 500',
  asset_class: 'ETF',
  issuer: 'iShares',
  domicile: 'IE',
  candidates: [
    {
      mic: 'XETR',
      exchange_name: 'Xetra',
      ticker: 'SXR8',
      currency: 'EUR',
      currency_confirmed: true,
      confirmed_by: 'yahoo',
      usable: true,
      warning: null,
    },
    {
      mic: 'XAMS',
      exchange_name: 'Euronext Amsterdam',
      ticker: 'CSPX',
      currency: 'EUR',
      currency_confirmed: false,
      confirmed_by: null,
      usable: true,
      warning:
        'No price provider could confirm the trading currency; EUR is a guess. Check it before choosing this listing.',
    },
    {
      mic: 'XLON',
      exchange_name: 'London Stock Exchange',
      ticker: 'CSP1',
      currency: 'GBX',
      currency_confirmed: true,
      confirmed_by: 'yahoo',
      usable: false,
      warning: 'Quoted in pence, which Folio does not support yet. Pick another listing.',
    },
  ],
}

afterEach(() => vi.unstubAllGlobals())

function open(routes: Record<string, unknown> = {}) {
  const api = mockApi({ '/api/v1/settings/general': GENERAL_US, ...routes })
  const onAdded = vi.fn()
  const onClose = vi.fn()
  renderAt(<AddInstrumentDialog open onClose={onClose} onAdded={onAdded} />)
  return { ...api, onAdded, onClose }
}

async function lookUp(isin = 'IE00B5BMR087') {
  await userEvent.type(screen.getByLabelText('ISIN'), isin)
  await userEvent.click(screen.getByRole('button', { name: 'Look up' }))
}

describe('adding an instrument by ISIN', () => {
  it('lists the listings, flags unconfirmed currencies and disables unusable ones', async () => {
    open({ '/api/v1/instruments/resolve': resolution })
    await lookUp()
    const radios = await screen.findAllByRole('radio')
    expect(radios).toHaveLength(3)
    expect(radios[0]).toBeChecked() // the first usable listing is preselected
    expect(radios[2]).toBeDisabled()
    expect(screen.getByText('Xetra · SXR8 · EUR')).toBeInTheDocument()
    expect(screen.getAllByText('Currency confirmed by yahoo')).toHaveLength(2) // Xetra and London
    expect(screen.getByText('Currency not confirmed')).toBeInTheDocument()
    expect(screen.getByText(/EUR is a guess/)).toBeInTheDocument()
    expect(screen.getByText(/Quoted in pence/)).toBeInTheDocument()
    expect(screen.getByLabelText('Name')).toHaveValue('iShares Core S&P 500') // prefilled, editable
    expect(screen.getByLabelText('Issuer')).toHaveValue('iShares')
  })

  it('sends the chosen listing and the edited details', async () => {
    const { calls, onAdded, onClose } = open({
      '/api/v1/instruments/resolve': resolution,
      'POST /api/v1/instruments': { id: 5 },
    })
    await lookUp()
    const radios = await screen.findAllByRole('radio')
    await userEvent.click(radios[1]) // Euronext Amsterdam, currency guessed
    const currency = screen.getByLabelText(/^Currency/)
    await userEvent.clear(currency)
    await userEvent.type(currency, 'usd') // the owner knows better
    await userEvent.selectOptions(screen.getByLabelText('Distribution'), 'ACC')
    await userEvent.click(screen.getByRole('button', { name: 'Add instrument' }))
    await waitFor(() => expect(onAdded).toHaveBeenCalled())
    expect(onClose).toHaveBeenCalled()
    const post = calls.find((c) => c.method === 'POST')!
    expect(post.path).toBe('/api/v1/instruments')
    expect(post.body).toEqual({
      isin: 'IE00B5BMR087',
      manual: false,
      name: 'iShares Core S&P 500',
      asset_class: 'ETF',
      issuer: 'iShares',
      domicile: 'IE',
      distribution: 'ACC',
      listing: { mic: 'XAMS', ticker: 'CSPX', currency: 'USD' },
    })
  })

  it('explains an invalid ISIN in plain language', async () => {
    open({
      '/api/v1/instruments/resolve': problem(
        422,
        'Invalid ISIN',
        'IE00B5BMR088 has a wrong check digit. Check it for typing mistakes.',
      ),
    })
    await lookUp('IE00B5BMR088')
    expect(await screen.findByRole('alert')).toHaveTextContent('wrong check digit')
  })

  it('offers adding by hand when no listing is found', async () => {
    open({ '/api/v1/instruments/resolve': { ...resolution, name: '', candidates: [] } })
    await lookUp('US0378331005')
    expect(await screen.findByText(/No listing was found for this ISIN/)).toBeInTheDocument()
    expect(screen.queryByRole('radio')).toBeNull()
    expect(screen.getByRole('tab', { name: 'By hand' })).toBeInTheDocument()
  })

  it('does not submit without a name', async () => {
    const { calls } = open({ '/api/v1/instruments/resolve': resolution })
    await lookUp()
    await userEvent.clear(await screen.findByLabelText('Name'))
    await userEvent.click(screen.getByRole('button', { name: 'Add instrument' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Give the instrument a name.')
    expect(calls.some((c) => c.method === 'POST')).toBe(false)
  })
})

describe('adding an instrument by hand', () => {
  async function byHand() {
    await userEvent.click(screen.getByRole('tab', { name: 'By hand' }))
  }

  it('checks the fields before sending anything', async () => {
    const { calls } = open()
    await byHand()
    await userEvent.click(screen.getByRole('button', { name: 'Add instrument' }))
    expect(screen.getByText('Give the instrument a name.')).toBeInTheDocument()
    await userEvent.type(screen.getByLabelText('Name'), 'Private bond')
    const currency = screen.getByLabelText(/^Currency/)
    await userEvent.clear(currency)
    await userEvent.type(currency, 'eu')
    await userEvent.click(screen.getByRole('button', { name: 'Add instrument' }))
    expect(screen.getByText('Enter a currency such as EUR.')).toBeInTheDocument()
    expect(calls.some((c) => c.method === 'POST')).toBe(false)
  })

  it('creates a hand-priced instrument', async () => {
    const { calls, onAdded } = open({ 'POST /api/v1/instruments': { id: 9 } })
    await byHand()
    await userEvent.type(screen.getByLabelText('Name'), 'Private bond')
    await userEvent.selectOptions(screen.getByLabelText('Asset class'), 'BOND')
    await userEvent.click(screen.getByRole('button', { name: 'Add instrument' }))
    await waitFor(() => expect(onAdded).toHaveBeenCalled())
    expect(calls.find((c) => c.method === 'POST')!.body).toEqual({
      name: 'Private bond',
      asset_class: 'BOND',
      manual: true,
      currency: 'EUR',
      isin: null,
    })
  })

  it('shows what the server refuses, such as a duplicate ISIN', async () => {
    open({
      'POST /api/v1/instruments': problem(
        409,
        'Cannot change instrument',
        'IE00B5BMR087 is already added as iShares. Edit that instrument instead.',
      ),
    })
    await byHand()
    await userEvent.type(screen.getByLabelText('Name'), 'Again')
    await userEvent.click(screen.getByRole('button', { name: 'Add instrument' }))
    const alert = await screen.findByRole('alert')
    expect(within(alert.parentElement!).getByText(/already added/)).toBeInTheDocument()
  })
})
