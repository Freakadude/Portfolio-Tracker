import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { Panel } from './components/Panel'

beforeEach(() => localStorage.clear())

const show = (props: Partial<Parameters<typeof Panel>[0]> = {}) =>
  render(
    <Panel id="demo" title="Splits" {...props}>
      <p>the body</p>
    </Panel>,
  )

describe('a section with a header that opens and closes it', () => {
  it('is open at first, closes on the header and remembers it in this browser', async () => {
    const first = show()
    const toggle = screen.getByRole('button', { name: 'Splits' })
    expect(toggle).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByText('the body')).toBeVisible()
    await userEvent.click(toggle)
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    expect(screen.getByText('the body')).not.toBeVisible()
    first.unmount()

    show() // another visit: still closed
    expect(screen.getByRole('button', { name: 'Splits' })).toHaveAttribute('aria-expanded', 'false')
  })

  it('starts closed when nothing is waiting, until the owner has chosen', async () => {
    const first = show({ autoCollapse: true })
    expect(screen.getByRole('button', { name: 'Splits' })).toHaveAttribute('aria-expanded', 'false')
    await userEvent.click(screen.getByRole('button', { name: 'Splits' }))
    expect(screen.getByText('the body')).toBeVisible()
    first.unmount()

    show({ autoCollapse: true }) // their choice wins over the automatic one
    expect(screen.getByText('the body')).toBeVisible()
  })

  it('stays open when a link points into it', async () => {
    show({ forceOpen: true })
    await userEvent.click(screen.getByRole('button', { name: 'Splits' }))
    expect(screen.getByText('the body')).toBeVisible()
  })

  it('shows a count and a status that stay readable when it is closed', async () => {
    show({ count: 3, status: 'Three are waiting' })
    await userEvent.click(screen.getByRole('button', { name: 'Splits' }))
    expect(screen.getByText('3')).toBeVisible()
    expect(screen.getByText('Three are waiting')).toBeVisible()
  })

  it('shows no count of zero', () => {
    show({ count: 0 })
    expect(screen.queryByText('0')).toBeNull()
  })

  it('keeps its actions out of the toggle', async () => {
    const act = vi.fn()
    show({ actions: <button onClick={act}>Run now</button> })
    await userEvent.click(screen.getByRole('button', { name: 'Run now' }))
    expect(act).toHaveBeenCalledTimes(1)
    expect(screen.getByText('the body')).toBeVisible() // it did not close
  })

  it('names its region by its title for assistive technology', () => {
    show()
    expect(screen.getByRole('region', { name: 'Splits' })).toBeInTheDocument()
  })
})
