import { describe, expect, it } from 'vitest'
import { isTemplateId, TEMPLATE_IDS, TEMPLATE_REGISTRY } from './registry'

describe('TEMPLATE_REGISTRY', () => {
  it('has 6 templates, each with a unique id, label, and description', () => {
    expect(TEMPLATE_REGISTRY).toHaveLength(6)
    const ids = TEMPLATE_REGISTRY.map((t) => t.id)
    expect(new Set(ids).size).toBe(ids.length)
    for (const t of TEMPLATE_REGISTRY) {
      expect(t.label.length).toBeGreaterThan(0)
      expect(t.description.length).toBeGreaterThan(0)
    }
  })

  it('includes the new ATS-focused templates alongside the original four', () => {
    const ids = TEMPLATE_REGISTRY.map((t) => t.id)
    expect(ids).toEqual([
      'modern',
      'classic',
      'minimal',
      'compact',
      'ats-plain',
      'two-column-ats',
    ])
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
