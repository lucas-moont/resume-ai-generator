import { describe, expect, it } from 'vitest'
import {
  applicantBandLabel,
  boardLabel,
  formatPlace,
  formatPostedAt,
  listingStatusLabel,
} from './listingFormat'

describe('boardLabel', () => {
  it('names every Job Board of v7', () => {
    expect(boardLabel('linkedin')).toBe('LinkedIn')
    expect(boardLabel('weworkremotely')).toBe('We Work Remotely')
    expect(boardLabel('remoteok')).toBe('Remote OK')
  })
})

describe('applicantBandLabel', () => {
  it('shows the band, never a count', () => {
    expect(applicantBandLabel('<10')).toBe('<10 candidatos')
    expect(applicantBandLabel('100+')).toBe('100+ candidatos')
  })

  it("reads 'unknown' as not reported rather than as zero", () => {
    expect(applicantBandLabel('unknown')).toBe('candidatos: n/d')
  })
})

describe('listingStatusLabel', () => {
  it('translates the four Listing Statuses', () => {
    expect(listingStatusLabel('new')).toBe('Nova')
    expect(listingStatusLabel('seen')).toBe('Vista')
    expect(listingStatusLabel('applied')).toBe('Candidatei-me')
    expect(listingStatusLabel('dismissed')).toBe('Descartada')
  })
})

describe('formatPlace', () => {
  it('does not stutter when the location already says remote', () => {
    expect(formatPlace({ location: 'Remote', isRemote: true })).toBe('Remote')
  })

  it('adds "Remoto" when the location text does not carry it', () => {
    expect(formatPlace({ location: 'São Paulo, SP', isRemote: true })).toBe('São Paulo, SP · Remoto')
  })

  it('keeps an on-site location as is', () => {
    expect(formatPlace({ location: 'São Paulo, SP', isRemote: false })).toBe('São Paulo, SP')
  })

  it('falls back when the board reported no location', () => {
    expect(formatPlace({ location: null, isRemote: true })).toBe('Remoto')
    expect(formatPlace({ location: null, isRemote: false })).toBe('Local não informado')
  })
})

describe('formatPostedAt', () => {
  const now = new Date('2026-08-25T12:00:00Z').getTime()

  it('reports hours within the first day and days after', () => {
    expect(formatPostedAt('2026-08-25T11:40:00Z', now)).toBe('publicada há menos de 1h')
    expect(formatPostedAt('2026-08-25T09:00:00Z', now)).toBe('publicada há 3h')
    expect(formatPostedAt('2026-08-24T09:00:00Z', now)).toBe('publicada há 1 dia')
    expect(formatPostedAt('2026-08-20T09:00:00Z', now)).toBe('publicada há 5 dias')
  })

  it('says so instead of inventing a date when the board reported none', () => {
    expect(formatPostedAt(null, now)).toBe('data não informada')
    expect(formatPostedAt('not a date', now)).toBe('data não informada')
  })
})
