import { describe, expect, it } from 'vitest'
import { formatRelativeTime } from './formatRelativeTime'

const NOW = new Date('2026-07-10T12:00:00Z').getTime()

describe('formatRelativeTime', () => {
  it('returns "just now" for anything under a minute', () => {
    expect(formatRelativeTime('2026-07-10T11:59:31Z', NOW)).toBe('just now')
  })

  it('formats minutes', () => {
    expect(formatRelativeTime('2026-07-10T11:55:00Z', NOW)).toBe('5m ago')
  })

  it('formats hours', () => {
    expect(formatRelativeTime('2026-07-10T09:00:00Z', NOW)).toBe('3h ago')
  })

  it('formats days', () => {
    expect(formatRelativeTime('2026-07-08T12:00:00Z', NOW)).toBe('2d ago')
  })
})
