import { beforeEach, describe, expect, it } from 'vitest'
import { APP_MODE_STORAGE_KEY, isAppMode, useAppModeStore } from './appModeStore'

beforeEach(() => {
  localStorage.clear()
  useAppModeStore.setState({ mode: 'resume' })
})

function persisted(mode: string, version: number) {
  localStorage.setItem(APP_MODE_STORAGE_KEY, JSON.stringify({ state: { mode }, version }))
}

describe('appModeStore', () => {
  it('accepts the Job Monitor as a mode and persists it at the current version', () => {
    useAppModeStore.getState().setMode('jobs')

    expect(useAppModeStore.getState().mode).toBe('jobs')
    const parsed = JSON.parse(localStorage.getItem(APP_MODE_STORAGE_KEY) as string)
    expect(parsed).toEqual({ state: { mode: 'jobs' }, version: 2 })
  })

  it('rehydrates a v2 entry as it is', async () => {
    persisted('jobs', 2)

    await useAppModeStore.persist.rehydrate()

    expect(useAppModeStore.getState().mode).toBe('jobs')
  })

  it('keeps a v1 mode through the migration — adding "jobs" only widened the type', async () => {
    persisted('analysis', 1)

    await useAppModeStore.persist.rehydrate()

    expect(useAppModeStore.getState().mode).toBe('analysis')
  })

  it('falls back to the resume flow when the persisted mode is not a mode any more', async () => {
    persisted('monitor-de-vagas', 1)

    await useAppModeStore.persist.rehydrate()

    expect(useAppModeStore.getState().mode).toBe('resume')
  })

  it('falls back to the resume flow when the persisted state has no mode at all', async () => {
    localStorage.setItem(APP_MODE_STORAGE_KEY, JSON.stringify({ state: {}, version: 1 }))

    await useAppModeStore.persist.rehydrate()

    expect(useAppModeStore.getState().mode).toBe('resume')
  })
})

describe('isAppMode', () => {
  it('recognises exactly the three areas', () => {
    expect(['resume', 'analysis', 'jobs'].every(isAppMode)).toBe(true)
    expect(isAppMode('settings')).toBe(false)
    expect(isAppMode(undefined)).toBe(false)
    expect(isAppMode(2)).toBe(false)
  })
})
