import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { BoardStatusBar } from './BoardStatusBar'
import { makeBoardStatus, makeScan } from '../../../test/msw/jobsScenarios'

describe('BoardStatusBar', () => {
  it('flags a blocked board and promises the next Scan (a partial Scan is not a failure)', () => {
    render(<BoardStatusBar boards={makeScan().boards} />)

    expect(
      screen.getByText('LinkedIn: bloqueado, tentamos na próxima varredura'),
    ).toBeInTheDocument()
    // The backend's own reason is shown verbatim beside it.
    expect(screen.getByText('LinkedIn recusou a busca (429).')).toBeInTheDocument()
  })

  it('counts what an ok board contributed', () => {
    render(<BoardStatusBar boards={makeScan().boards} />)

    expect(screen.getByText('Indeed: 14 vagas')).toBeInTheDocument()
    expect(screen.getByText('We Work Remotely: 6 vagas')).toBeInTheDocument()
  })

  it("explains a 'skipped' board by the portal's own minimum interval", () => {
    render(<BoardStatusBar boards={makeScan().boards} />)

    expect(
      screen.getByText('Remotive: pulado, intervalo mínimo do portal ainda não passou'),
    ).toBeInTheDocument()
    expect(screen.getByText('Intervalo mínimo de 6h ainda não passou.')).toBeInTheDocument()
  })

  it('renders an error board with its message', () => {
    render(
      <BoardStatusBar
        boards={[
          makeBoardStatus({
            board: 'glassdoor',
            status: 'error',
            message: 'Timeout ao falar com o portal.',
            count: 0,
          }),
        ]}
      />,
    )

    expect(screen.getByText('Glassdoor: falhou, tentamos na próxima varredura')).toBeInTheDocument()
    expect(screen.getByText('Timeout ao falar com o portal.')).toBeInTheDocument()
  })

  it('renders nothing at all when no Scan has reported yet', () => {
    const { container } = render(<BoardStatusBar boards={[]} />)
    expect(container).toBeEmptyDOMElement()
  })
})
