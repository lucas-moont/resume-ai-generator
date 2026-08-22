import { describe, expect, it } from 'vitest'
import { contactGapLabels, contactGaps } from './contactGaps'
import { makeResume } from '../../test/factories'

describe('contactGaps', () => {
  it('reports nothing for a resume with every contact detail', () => {
    expect(contactGaps(makeResume())).toEqual([])
  })

  it('reports a missing phone — the case that went unnoticed for 21 profile versions', () => {
    expect(contactGaps(makeResume({ phone: null }))).toEqual(['phone'])
  })

  it('treats whitespace as missing, not as a value', () => {
    expect(contactGaps(makeResume({ phone: '   ' }))).toEqual(['phone'])
  })

  it('orders gaps by how much a recruiter misses them', () => {
    const gaps = contactGaps(makeResume({ location: null, phone: null, email: null, links: [] }))
    expect(gaps).toEqual(['phone', 'email', 'location', 'profileLink'])
  })

  it('accepts a single link as enough of a profile link', () => {
    const one = makeResume({ links: [{ label: 'LinkedIn', url: 'https://linkedin.com/in/x' }] })
    expect(contactGaps(one)).not.toContain('profileLink')
  })

  it('does not count a link that has no url or no label', () => {
    expect(contactGaps(makeResume({ links: [{ label: 'GitHub', url: '' }] }))).toContain(
      'profileLink',
    )
    expect(contactGaps(makeResume({ links: [{ label: '', url: 'https://x.dev' }] }))).toContain(
      'profileLink',
    )
  })

  it('reports nothing when there is no resume at all', () => {
    // The panel renders an empty state in that case; a notice would be noise.
    expect(contactGaps(null)).toEqual([])
    expect(contactGaps(undefined)).toEqual([])
  })
})

describe('contactGapLabels', () => {
  it('labels gaps in Portuguese for a pt locale', () => {
    expect(contactGapLabels(['phone', 'email'], 'pt-BR')).toEqual(['telefone', 'e-mail'])
  })

  it('matches the preview loose pt detection rather than an exact pt-BR match', () => {
    // ResumePreview uses (locale||'').toLowerCase().startsWith('pt'), so these must agree —
    // otherwise the notice speaks English beside a Portuguese document.
    expect(contactGapLabels(['phone'], 'pt')).toEqual(['telefone'])
    expect(contactGapLabels(['phone'], 'PT-BR')).toEqual(['telefone'])
    expect(contactGapLabels(['phone'], 'pt_BR')).toEqual(['telefone'])
  })

  it('falls back to English for any other locale, including a missing one', () => {
    expect(contactGapLabels(['phone'], 'en')).toEqual(['phone'])
    expect(contactGapLabels(['phone'], undefined)).toEqual(['phone'])
  })
})
