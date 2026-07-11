import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { ResumeUpdatedCard } from './ResumeUpdatedCard'
import type { ResumeUpdatedCard as ResumeUpdatedCardData } from '../../store/chatStore'

describe('ResumeUpdatedCard', () => {
  it('falls back to a label-only summary when no diff is available (history reload)', () => {
    const card: ResumeUpdatedCardData = { type: 'resumeUpdated', changedSections: ['headline', 'skills'] }
    render(<ResumeUpdatedCard card={card} />)

    expect(screen.getByText(/resume updated/i)).toBeInTheDocument()
    expect(screen.getByText(/headline, skills/i)).toBeInTheDocument()
  })

  it('renders honest before/after text for each changed field when a diff is available', () => {
    const card: ResumeUpdatedCardData = {
      type: 'resumeUpdated',
      changedSections: ['headline'],
      diff: [{ key: 'headline', label: 'headline', before: 'Engineer', after: 'Senior Engineer' }],
    }
    render(<ResumeUpdatedCard card={card} />)

    expect(screen.getByText('Engineer')).toBeInTheDocument()
    expect(screen.getByText('Senior Engineer')).toBeInTheDocument()
    // no duplicate label-only parenthetical alongside the real diff
    expect(screen.queryByText('(headline)')).not.toBeInTheDocument()
  })

  it('marks a field with no prior value as added rather than showing a false "before"', () => {
    const card: ResumeUpdatedCardData = {
      type: 'resumeUpdated',
      changedSections: ['summary'],
      diff: [{ key: 'summary', label: 'summary', before: null, after: 'A brand new summary.' }],
    }
    render(<ResumeUpdatedCard card={card} />)

    expect(screen.getByText(/added/i)).toBeInTheDocument()
    expect(screen.getByText('A brand new summary.')).toBeInTheDocument()
  })

  it('renders no diff block when changedSections is empty and no diff is present', () => {
    const card: ResumeUpdatedCardData = { type: 'resumeUpdated', changedSections: [] }
    render(<ResumeUpdatedCard card={card} />)

    expect(screen.getByText(/resume updated/i)).toBeInTheDocument()
    expect(screen.queryByRole('list')).not.toBeInTheDocument()
  })
})
