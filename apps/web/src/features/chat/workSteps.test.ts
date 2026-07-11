import { describe, expect, it } from 'vitest'
import { WORK_STEPS } from './workSteps'

describe('WORK_STEPS', () => {
  it('includes the analyzing_job step (v4, F3) with a human label', () => {
    expect(WORK_STEPS.find((s) => s.id === 'analyzing_job')).toEqual({
      id: 'analyzing_job',
      label: 'Analyzing job description',
    })
  })
})
