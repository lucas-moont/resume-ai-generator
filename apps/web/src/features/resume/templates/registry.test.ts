import { describe, expect, it } from 'vitest'
import { isTemplateId, TEMPLATE_IDS, TEMPLATE_REGISTRY, type TemplateId } from './registry'

// The compile-time-only TemplateId union above can't be derived from the
// manifest JSON import (TS widens JSON string literals to `string`) — this
// list is what proves it hasn't drifted from templates.json. If you add or
// remove a template in the manifest, this literal (and its counterpart in
// apps/api/app/domain/schemas.py's TemplateId Literal) must be updated too.
const ALL_TEMPLATE_IDS: readonly TemplateId[] = [
  'modern',
  'classic',
  'minimal',
  'compact',
  'ats-plain',
  'two-column-ats',
  'executive',
  'tech',
  'latex-ats',
]

describe('TEMPLATE_REGISTRY', () => {
  it('has 9 templates, each with a unique id, label, description, and at least one tag', () => {
    expect(TEMPLATE_REGISTRY).toHaveLength(9)
    const ids = TEMPLATE_REGISTRY.map((t) => t.id)
    expect(new Set(ids).size).toBe(ids.length)
    for (const t of TEMPLATE_REGISTRY) {
      expect(t.label.length).toBeGreaterThan(0)
      expect(t.description.length).toBeGreaterThan(0)
      expect(t.tags.length).toBeGreaterThan(0)
    }
  })

  it('tags the ATS-focused templates as ats-friendly', () => {
    // The tag is what TemplatePicker groups on, so every template whose whole
    // premise is parser compatibility has to carry it.
    for (const id of ['ats-plain', 'two-column-ats', 'latex-ats'] as const) {
      expect(TEMPLATE_REGISTRY.find((t) => t.id === id)?.tags).toContain('ats-friendly')
    }
  })

  it('gives latex-ats the tags its thumbnail reads', () => {
    // TemplateThumbnail derives the miniature entirely from tags — `navy` picks
    // the accent color and `centered` the centered header. Without them the
    // thumbnail would silently render as the generic indigo left-aligned one.
    const latexAts = TEMPLATE_REGISTRY.find((t) => t.id === 'latex-ats')
    expect(latexAts?.tags).toContain('single-column')
    expect(latexAts?.tags).toContain('navy')
    expect(latexAts?.tags).toContain('centered')
  })

  it('matches the compile-time TemplateId union exactly (manifest is the single source)', () => {
    const ids = TEMPLATE_REGISTRY.map((t) => t.id)
    expect(new Set(ids)).toEqual(new Set(ALL_TEMPLATE_IDS))
  })

  it('includes the two new templates added for v3', () => {
    const ids = TEMPLATE_REGISTRY.map((t) => t.id)
    expect(ids).toContain('executive')
    expect(ids).toContain('tech')
  })

  it('TEMPLATE_IDS mirrors the registry order exactly', () => {
    expect(TEMPLATE_IDS).toEqual(TEMPLATE_REGISTRY.map((t) => t.id))
  })
})

describe('isTemplateId', () => {
  it('accepts every registered id', () => {
    for (const id of TEMPLATE_IDS) {
      expect(isTemplateId(id)).toBe(true)
    }
  })

  it('rejects unknown strings', () => {
    expect(isTemplateId('not-a-template')).toBe(false)
    expect(isTemplateId('')).toBe(false)
  })
})
