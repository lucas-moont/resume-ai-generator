import { describe, expect, it } from 'vitest'
import { diffResumeSections } from './diffResumeSections'
import { makeResume } from '../../test/factories'

describe('diffResumeSections', () => {
  it('treats every non-empty section as changed when there is no previous resume', () => {
    const resume = makeResume({ projects: [] })

    const changed = diffResumeSections(null, resume)

    expect(changed).toEqual(
      expect.arrayContaining(['fullName', 'headline', 'summary', 'experience', 'skills']),
    )
    expect(changed).not.toContain('projects')
  })

  it('only reports sections whose content actually changed', () => {
    const before = makeResume({ fullName: 'Ada Lovelace', skills: ['TypeScript'] })
    const after = { ...before, skills: ['TypeScript', 'Rust'] }

    expect(diffResumeSections(before, after)).toEqual(['skills'])
  })

  it('reports no sections when nothing changed', () => {
    const resume = makeResume()
    expect(diffResumeSections(resume, { ...resume })).toEqual([])
  })

  it('detects a change to a single scalar field', () => {
    const before = makeResume({ headline: 'Engineer' })
    const after = { ...before, headline: 'Senior Engineer' }

    expect(diffResumeSections(before, after)).toEqual(['headline'])
  })
})
