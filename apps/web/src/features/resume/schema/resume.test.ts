import { describe, expect, it } from 'vitest'
import { validateResumeDocument } from './resume'
import { makeResume } from '../../../test/factories'

describe('validateResumeDocument', () => {
  it('accepts a well-formed ResumeDocument with no issues', () => {
    const result = validateResumeDocument(makeResume())
    expect(result).toEqual({ valid: true, issues: [] })
  })

  it('is non-blocking: it never throws, even for garbage input', () => {
    expect(() => validateResumeDocument(null)).not.toThrow()
    expect(() => validateResumeDocument({})).not.toThrow()
    expect(() => validateResumeDocument('not a resume')).not.toThrow()
  })

  it('flags a missing/blank required field (fullName) with a readable issue', () => {
    const result = validateResumeDocument(makeResume({ fullName: '' }))
    expect(result.valid).toBe(false)
    expect(result.issues.some((i) => i.toLowerCase().includes('fullname'))).toBe(true)
  })

  it('flags an experience item missing its company', () => {
    const doc = makeResume({
      experience: [{ company: '', title: 'Engineer', start: '2020', highlights: [] }],
    })
    const result = validateResumeDocument(doc)
    expect(result.valid).toBe(false)
    expect(result.issues.some((i) => i.includes('experience.0.company'))).toBe(true)
  })

  it('flags a malformed email but does not flag a well-formed one', () => {
    const bad = validateResumeDocument(makeResume({ email: 'not-an-email' }))
    expect(bad.valid).toBe(false)

    const good = validateResumeDocument(makeResume({ email: 'ada@example.com' }))
    expect(good.valid).toBe(true)
  })

  it('does not flag a null/absent email (optional field)', () => {
    const result = validateResumeDocument(makeResume({ email: null }))
    expect(result.valid).toBe(true)
  })

  it('accepts an empty skills/education/projects/experience document (all-optional-content resume)', () => {
    const result = validateResumeDocument(
      makeResume({ skills: [], education: [], projects: [], experience: [] }),
    )
    expect(result).toEqual({ valid: true, issues: [] })
  })
})
