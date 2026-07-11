import { describe, expect, it } from 'vitest'
import { applyFieldEdit, addListItem, removeListItem } from './fieldPaths'
import { makeResume } from '../../../test/factories'

describe('applyFieldEdit', () => {
  it('sets a top-level string field', () => {
    const doc = makeResume({ fullName: 'Ada Lovelace' })
    const next = applyFieldEdit(doc, 'fullName', 'Grace Hopper')
    expect(next.fullName).toBe('Grace Hopper')
  })

  it('sets every plain top-level field the preview edits', () => {
    const doc = makeResume()
    expect(applyFieldEdit(doc, 'headline', 'Staff Engineer').headline).toBe('Staff Engineer')
    expect(applyFieldEdit(doc, 'summary', 'New summary').summary).toBe('New summary')
    expect(applyFieldEdit(doc, 'location', 'Berlin').location).toBe('Berlin')
    expect(applyFieldEdit(doc, 'email', 'grace@example.com').email).toBe('grace@example.com')
    expect(applyFieldEdit(doc, 'phone', '+1 555 0199').phone).toBe('+1 555 0199')
  })

  it('does not mutate the original document', () => {
    const doc = makeResume({ fullName: 'Ada Lovelace' })
    const frozen = JSON.parse(JSON.stringify(doc))
    applyFieldEdit(doc, 'fullName', 'Grace Hopper')
    expect(doc).toEqual(frozen)
  })

  it('returns a new top-level object reference', () => {
    const doc = makeResume()
    const next = applyFieldEdit(doc, 'fullName', 'Grace Hopper')
    expect(next).not.toBe(doc)
  })

  it('leaves unrelated top-level arrays referentially unchanged', () => {
    const doc = makeResume()
    const next = applyFieldEdit(doc, 'fullName', 'Grace Hopper')
    expect(next.education).toBe(doc.education)
    expect(next.projects).toBe(doc.projects)
  })

  it('sets a field on a specific experience item by index', () => {
    const doc = makeResume({
      experience: [
        { company: 'A', title: 'Engineer', start: '2020', highlights: [] },
        { company: 'B', title: 'Manager', start: '2022', highlights: [] },
      ],
    })
    const next = applyFieldEdit(doc, 'experience.1.title', 'Senior Manager')
    expect(next.experience[1].title).toBe('Senior Manager')
    expect(next.experience[0]).toBe(doc.experience[0]) // untouched sibling item, same reference
  })

  it('supports every experience field used by the preview (company/location/start/end)', () => {
    const doc = makeResume({
      experience: [{ company: 'A', title: 'Engineer', location: 'NY', start: '2020', end: '2022', highlights: [] }],
    })
    expect(applyFieldEdit(doc, 'experience.0.company', 'Acme').experience[0].company).toBe('Acme')
    expect(applyFieldEdit(doc, 'experience.0.location', 'SF').experience[0].location).toBe('SF')
    expect(applyFieldEdit(doc, 'experience.0.start', '2019').experience[0].start).toBe('2019')
    expect(applyFieldEdit(doc, 'experience.0.end', '2023').experience[0].end).toBe('2023')
  })

  it('sets a highlight inside a specific experience item (nested array)', () => {
    const doc = makeResume({
      experience: [{ company: 'A', title: 'Engineer', start: '2020', highlights: ['first', 'second'] }],
    })
    const next = applyFieldEdit(doc, 'experience.0.highlights.1', 'updated second')
    expect(next.experience[0].highlights).toEqual(['first', 'updated second'])
  })

  it('sets a skill by index', () => {
    const doc = makeResume({ skills: ['TypeScript', 'Python'] })
    const next = applyFieldEdit(doc, 'skills.1', 'Rust')
    expect(next.skills).toEqual(['TypeScript', 'Rust'])
  })

  it('sets project fields by index', () => {
    const doc = makeResume({ projects: [{ name: 'Note G', description: 'Old' }] })
    expect(applyFieldEdit(doc, 'projects.0.name', 'New Name').projects[0].name).toBe('New Name')
    expect(applyFieldEdit(doc, 'projects.0.description', 'New desc').projects[0].description).toBe('New desc')
  })

  it('sets education fields by index', () => {
    const doc = makeResume({
      education: [{ institution: 'MIT', degree: 'B.Sc.', end: '2010', details: 'Old' }],
    })
    expect(applyFieldEdit(doc, 'education.0.institution', 'Stanford').education[0].institution).toBe('Stanford')
    expect(applyFieldEdit(doc, 'education.0.degree', 'M.Sc.').education[0].degree).toBe('M.Sc.')
    expect(applyFieldEdit(doc, 'education.0.end', '2012').education[0].end).toBe('2012')
    expect(applyFieldEdit(doc, 'education.0.details', 'New details').education[0].details).toBe('New details')
  })

  describe('invalid paths are a no-op (return the document unchanged, never throw)', () => {
    it('rejects an unknown top-level key', () => {
      const doc = makeResume()
      expect(applyFieldEdit(doc, 'bogus', 'x')).toBe(doc)
    })

    it('rejects an out-of-range array index', () => {
      const doc = makeResume({ experience: [{ company: 'A', title: 'Engineer', start: '2020', highlights: [] }] })
      expect(applyFieldEdit(doc, 'experience.5.title', 'x')).toBe(doc)
    })

    it('rejects a negative array index', () => {
      const doc = makeResume({ skills: ['TypeScript'] })
      expect(applyFieldEdit(doc, 'skills.-1', 'x')).toBe(doc)
    })

    it('rejects a non-numeric index segment', () => {
      const doc = makeResume({ experience: [{ company: 'A', title: 'Engineer', start: '2020', highlights: [] }] })
      expect(applyFieldEdit(doc, 'experience.abc.title', 'x')).toBe(doc)
    })

    it('rejects an out-of-range nested array index (highlights)', () => {
      const doc = makeResume({
        experience: [{ company: 'A', title: 'Engineer', start: '2020', highlights: ['only one'] }],
      })
      expect(applyFieldEdit(doc, 'experience.0.highlights.9', 'x')).toBe(doc)
    })

    it('rejects a field name that does not exist on the item', () => {
      const doc = makeResume({ experience: [{ company: 'A', title: 'Engineer', start: '2020', highlights: [] }] })
      expect(applyFieldEdit(doc, 'experience.0.nonexistent', 'x')).toBe(doc)
    })

    it('rejects an empty path', () => {
      const doc = makeResume()
      expect(applyFieldEdit(doc, '', 'x')).toBe(doc)
    })
  })
})

describe('addListItem', () => {
  it('appends an empty string to the top-level skills list', () => {
    const doc = makeResume({ skills: ['TypeScript'] })
    const next = addListItem(doc, 'skills')
    expect(next.skills).toEqual(['TypeScript', ''])
  })

  it('appends an empty string to a nested highlights list', () => {
    const doc = makeResume({
      experience: [{ company: 'A', title: 'Engineer', start: '2020', highlights: ['first'] }],
    })
    const next = addListItem(doc, 'experience.0.highlights')
    expect(next.experience[0].highlights).toEqual(['first', ''])
  })

  it('appends a blank education entry to the top-level education list', () => {
    const doc = makeResume({ education: [] })
    const next = addListItem(doc, 'education')
    expect(next.education).toHaveLength(1)
    expect(next.education[0]).toMatchObject({ institution: '', degree: '' })
  })

  it('is a no-op for an unknown/invalid list path', () => {
    const doc = makeResume()
    expect(addListItem(doc, 'bogus')).toBe(doc)
  })
})

describe('removeListItem', () => {
  it('removes a skill by index', () => {
    const doc = makeResume({ skills: ['TypeScript', 'Python', 'Rust'] })
    const next = removeListItem(doc, 'skills', 1)
    expect(next.skills).toEqual(['TypeScript', 'Rust'])
  })

  it('removes a highlight from a specific experience item', () => {
    const doc = makeResume({
      experience: [{ company: 'A', title: 'Engineer', start: '2020', highlights: ['a', 'b', 'c'] }],
    })
    const next = removeListItem(doc, 'experience.0.highlights', 0)
    expect(next.experience[0].highlights).toEqual(['b', 'c'])
  })

  it('removes an education entry by index', () => {
    const doc = makeResume({
      education: [
        { institution: 'MIT', degree: 'B.Sc.' },
        { institution: 'Stanford', degree: 'M.Sc.' },
      ],
    })
    const next = removeListItem(doc, 'education', 0)
    expect(next.education).toEqual([{ institution: 'Stanford', degree: 'M.Sc.' }])
  })

  it('is a no-op for an out-of-range index', () => {
    const doc = makeResume({ skills: ['TypeScript'] })
    expect(removeListItem(doc, 'skills', 9)).toBe(doc)
  })

  it('is a no-op for an unknown list path', () => {
    const doc = makeResume()
    expect(removeListItem(doc, 'bogus', 0)).toBe(doc)
  })
})
