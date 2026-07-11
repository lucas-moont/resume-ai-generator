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

  it('shows a neutral "updated" pill instead of an identical before/after pair (e.g. a highlights-only edit the section-level summary cannot distinguish)', () => {
    const card: ResumeUpdatedCardData = {
      type: 'resumeUpdated',
      changedSections: ['experience'],
      diff: [
        {
          key: 'experience',
          label: 'experience',
          before: 'Senior Software Engineer @ Analytical Engines Inc.',
          after: 'Senior Software Engineer @ Analytical Engines Inc.',
        },
      ],
    }
    render(<ResumeUpdatedCard card={card} />)

    expect(screen.getByText('experience:')).toBeInTheDocument()
    // Exact match: the badge's own "Resume updated · see the preview" text
    // also contains the substring "updated", so a loose /updated/i regex
    // would match both and defeat this assertion.
    expect(screen.getByText('updated', { exact: true })).toBeInTheDocument()
    // The identical text must not render as a struck-through "before" next to
    // itself as "after" — that reads as "nothing changed".
    expect(screen.queryByText('Senior Software Engineer @ Analytical Engines Inc.')).not.toBeInTheDocument()
    expect(document.querySelector('.line-through')).not.toBeInTheDocument()
  })

  it('renders no diff block when changedSections is empty and no diff is present', () => {
    const card: ResumeUpdatedCardData = { type: 'resumeUpdated', changedSections: [] }
    render(<ResumeUpdatedCard card={card} />)

    expect(screen.getByText(/resume updated/i)).toBeInTheDocument()
    expect(screen.queryByRole('list')).not.toBeInTheDocument()
  })
})
