import { describe, expect, it } from 'vitest'
import { A4_WIDTH_PX, computeFitScale } from './previewScale'

describe('computeFitScale', () => {
  it('returns 1 (no scaling) when the container is at least as wide as an A4 page', () => {
    expect(computeFitScale(A4_WIDTH_PX)).toBe(1)
    expect(computeFitScale(A4_WIDTH_PX + 500)).toBe(1)
  })

  it('scales down proportionally to fit a narrower container (B3: e.g. a 400px mobile viewport)', () => {
    const containerWidth = 368 // ~400px viewport minus the panel's own padding
    const scale = computeFitScale(containerWidth)

    expect(scale).toBeCloseTo(containerWidth / A4_WIDTH_PX, 5)
    expect(scale).toBeLessThan(1)
    expect(scale * A4_WIDTH_PX).toBeCloseTo(containerWidth, 5)
  })

  it('never scales up beyond 1 even for a very wide container', () => {
    expect(computeFitScale(5000)).toBe(1)
  })

  it('falls back to 1 for a zero or negative width (not yet measured)', () => {
    expect(computeFitScale(0)).toBe(1)
    expect(computeFitScale(-10)).toBe(1)
  })
})
