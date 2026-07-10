import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { ProfileUpdateAppliedCard } from './ProfileUpdateAppliedCard'
import type { ProfileUpdateAppliedCard as ProfileUpdateAppliedCardData } from '../../store/chatStore'

function makeCard(overrides: Partial<ProfileUpdateAppliedCardData> = {}): ProfileUpdateAppliedCardData {
  return {
    type: 'profileUpdateApplied',
    profileVersion: 3,
    summary: 'Updated phone number.',
    ...overrides,
  }
}

describe('ProfileUpdateAppliedCard', () => {
  it('shows the profile version and summary, with no action buttons', () => {
    render(<ProfileUpdateAppliedCard card={makeCard()} />)

    expect(screen.getByText(/version 3/i)).toBeInTheDocument()
    expect(screen.getByText(/updated phone number\./i)).toBeInTheDocument()
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
  })
})
