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
]

describe('TEMPLATE_REGISTRY', () => {
  it('has 8 templates, each with a unique id, label, description, and at least one tag', () => {
    expect(TEMPLATE_REGISTRY).toHaveLength(8)
    const ids = TEMPLATE_REGISTRY.map((t) => t.id)
    expect(new Set(ids).size).toBe(ids.length)
    for (const t of TEMPLATE_REGISTRY) {
      expect(t.label.length).toBeGreaterThan(0)
      expect(t.description.length).toBeGreaterThan(0)
      expect(t.tags.length).toBeGreaterThan(0)
    }
  })

  it('tags the two ATS-focused templates as ats-friendly', () => {
    const atsPlain = TEMPLATE_REGISTRY.find((t) => t.id === 'ats-plain')
    const twoColumnAts = TEMPLATE_REGISTRY.find((t) => t.id === 'two-column-ats')
    expect(atsPlain?.tags).toContain('ats-friendly')
    expect(twoColumnAts?.tags).toContain('ats-friendly')
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
