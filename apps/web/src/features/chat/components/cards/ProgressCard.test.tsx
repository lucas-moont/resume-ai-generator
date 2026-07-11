import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { ProgressCard } from './ProgressCard'
import type { StreamingState } from '../../store/chatStore'

function makeStreaming(overrides: Partial<StreamingState> = {}): StreamingState {
  return { status: 'streaming', step: 'preparing_context', progress: 20, message: '', ...overrides }
}

describe('ProgressCard', () => {
  it('never lists "Analyzing job description" in the checklist (v4, F4: handled by the typing indicator instead)', () => {
    render(<ProgressCard streaming={makeStreaming()} />)
    expect(screen.queryByText(/analyzing job description/i)).not.toBeInTheDocument()
  })

  it('still lists the generation steps and marks the current one', () => {
    render(<ProgressCard streaming={makeStreaming({ step: 'calling_ai' })} />)
    expect(screen.getByText(/preparing context/i)).toBeInTheDocument()
    expect(screen.getByText(/calling ai model/i)).toBeInTheDocument()
    expect(screen.getByText(/finalizing/i)).toBeInTheDocument()
  })

  it('preserves the progressbar ARIA attributes', () => {
    render(<ProgressCard streaming={makeStreaming({ progress: 42 })} />)
    const bar = screen.getByRole('progressbar', { name: /progress/i })
    expect(bar).toHaveAttribute('aria-valuenow', '42')
    expect(bar).toHaveAttribute('aria-valuemin', '0')
    expect(bar).toHaveAttribute('aria-valuemax', '100')
  })

  it('preserves the busy status role', () => {
    render(<ProgressCard streaming={makeStreaming()} />)
    expect(screen.getByRole('status')).toHaveAttribute('aria-busy', 'true')
  })
})
