import { describe, expect, it } from 'vitest'
import { diffResume } from './resumeDiff'
import { makeResume } from '../../test/factories'

describe('diffResume', () => {
  it('returns nothing when no field changed', () => {
    const resume = makeResume()
    expect(diffResume(resume, { ...resume })).toEqual([])
  })

  it('reports a scalar field change with its label and before/after text', () => {
    const before = makeResume({ headline: 'Engineer' })
    const after = { ...before, headline: 'Senior Engineer' }

    expect(diffResume(before, after)).toEqual([
      { key: 'headline', label: 'headline', before: 'Engineer', after: 'Senior Engineer' },
    ])
  })

  it('formats a skills change as comma-joined lists', () => {
    const before = makeResume({ skills: ['TypeScript'] })
    const after = { ...before, skills: ['TypeScript', 'Rust'] }

    expect(diffResume(before, after)).toEqual([
      { key: 'skills', label: 'skills', before: 'TypeScript', after: 'TypeScript, Rust' },
    ])
  })

  it('formats an experience change as "title @ company" entries', () => {
    const before = makeResume({
      experience: [{ company: 'A', title: 'Engineer', start: '2020', highlights: [] }],
    })
    const after = {
      ...before,
      experience: [{ company: 'A', title: 'Staff Engineer', start: '2020', highlights: [] }],
    }

    expect(diffResume(before, after)).toEqual([
      { key: 'experience', label: 'experience', before: 'Engineer @ A', after: 'Staff Engineer @ A' },
    ])
  })

  it('treats every non-empty section as newly added (before: null) when there is no previous resume', () => {
    const resume = makeResume({ projects: [] })

    const diff = diffResume(null, resume)

    const headline = diff.find((d) => d.key === 'headline')
    expect(headline).toEqual({ key: 'headline', label: 'headline', before: null, after: 'Senior Software Engineer' })
    expect(diff.find((d) => d.key === 'projects')).toBeUndefined()
  })
})
