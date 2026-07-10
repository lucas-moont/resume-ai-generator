import { act, renderHook } from '@testing-library/react'
import { beforeEach, describe, expect, it } from 'vitest'
import { useResumeStore, useResumeTemporal, useValidationIssues, STORAGE_KEY } from './resumeStore'
import { makeResume } from '../../../test/factories'

function resetStore() {
  useResumeStore.setState({ resume: null, template: 'modern', locale: 'auto', validationIssues: [] })
  useResumeStore.temporal.getState().clear()
  localStorage.clear()
}

describe('resumeStore', () => {
  beforeEach(() => {
    resetStore()
  })

  it('starts with no resume, the modern template, and auto locale', () => {
    const state = useResumeStore.getState()
    expect(state.resume).toBeNull()
    expect(state.template).toBe('modern')
    expect(state.locale).toBe('auto')
  })

  it('setResume/setTemplate/setLocale update state independently', () => {
    const resume = makeResume()

    useResumeStore.getState().setResume(resume)
    useResumeStore.getState().setTemplate('classic')
    useResumeStore.getState().setLocale('pt-BR')

    const state = useResumeStore.getState()
    expect(state.resume).toEqual(resume)
    expect(state.template).toBe('classic')
    expect(state.locale).toBe('pt-BR')
  })

  it('clearResume resets only the resume, keeping template/locale', () => {
    useResumeStore.getState().setResume(makeResume())
    useResumeStore.getState().setTemplate('compact')

    useResumeStore.getState().clearResume()

    const state = useResumeStore.getState()
    expect(state.resume).toBeNull()
    expect(state.template).toBe('compact')
  })

  it('persists resume/template/locale to localStorage', () => {
    const resume = makeResume()

    useResumeStore.getState().setResume(resume)
    useResumeStore.getState().setTemplate('minimal')

    const raw = localStorage.getItem(STORAGE_KEY)
    expect(raw).not.toBeNull()
    const parsed = JSON.parse(raw as string)
    expect(parsed.version).toBe(1)
    expect(parsed.state.resume).toEqual(resume)
    expect(parsed.state.template).toBe('minimal')
  })

  it('rehydrates resume/template/locale from a pre-populated localStorage entry', async () => {
    const resume = makeResume({ fullName: 'Marie Curie' })
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({ state: { resume, template: 'classic', locale: 'en' }, version: 1 }),
    )

    await useResumeStore.persist.rehydrate()

    const state = useResumeStore.getState()
    expect(state.resume).toEqual(resume)
    expect(state.template).toBe('classic')
    expect(state.locale).toBe('en')
  })

  describe('undo/redo via zundo temporal', () => {
    it('undoes and redoes resume changes', () => {
      const first = makeResume({ fullName: 'Ada Lovelace' })
      const second = makeResume({ fullName: 'Grace Hopper' })

      useResumeStore.getState().setResume(first)
      useResumeStore.getState().setResume(second)
      expect(useResumeStore.getState().resume?.fullName).toBe('Grace Hopper')

      useResumeStore.temporal.getState().undo()
      expect(useResumeStore.getState().resume?.fullName).toBe('Ada Lovelace')

      useResumeStore.temporal.getState().redo()
      expect(useResumeStore.getState().resume?.fullName).toBe('Grace Hopper')
    })

    it('does not add template/locale changes to the undo history (only resume is tracked)', () => {
      useResumeStore.getState().setResume(makeResume({ fullName: 'Ada Lovelace' }))
      useResumeStore.getState().setTemplate('compact')
      useResumeStore.getState().setLocale('pt-BR')

      useResumeStore.temporal.getState().undo()

      // Undoing should only ever roll back `resume`; template/locale stay put.
      expect(useResumeStore.getState().template).toBe('compact')
      expect(useResumeStore.getState().locale).toBe('pt-BR')
    })

    it('useResumeTemporal exposes reactive past/future state and undo/redo', () => {
      const { result } = renderHook(() => useResumeTemporal())
      expect(result.current.pastStates).toEqual([])
      expect(result.current.futureStates).toEqual([])

      act(() => {
        useResumeStore.getState().setResume(makeResume({ fullName: 'Ada Lovelace' }))
        useResumeStore.getState().setResume(makeResume({ fullName: 'Grace Hopper' }))
      })

      expect(result.current.pastStates.length).toBeGreaterThan(0)
      expect(result.current.futureStates).toEqual([])

      act(() => {
        result.current.undo()
      })
      expect(useResumeStore.getState().resume?.fullName).toBe('Ada Lovelace')
    })
  })

  describe('validationIssues (zod, non-blocking)', () => {
    it('is empty for a well-formed resume', () => {
      useResumeStore.getState().setResume(makeResume())
      expect(useResumeStore.getState().validationIssues).toEqual([])
    })

    it('is populated (but the resume still commits) for an invalid resume', () => {
      const invalid = makeResume({ fullName: '' })
      useResumeStore.getState().setResume(invalid)

      // Non-blocking: the document is set regardless of validation result.
      expect(useResumeStore.getState().resume).toEqual(invalid)
      expect(useResumeStore.getState().validationIssues.length).toBeGreaterThan(0)
    })

    it('clears back to empty once the resume is fixed', () => {
      useResumeStore.getState().setResume(makeResume({ fullName: '' }))
      expect(useResumeStore.getState().validationIssues.length).toBeGreaterThan(0)

      useResumeStore.getState().setResume(makeResume({ fullName: 'Ada Lovelace' }))
      expect(useResumeStore.getState().validationIssues).toEqual([])
    })

    it('is empty when the resume is cleared to null', () => {
      useResumeStore.getState().setResume(makeResume({ fullName: '' }))
      useResumeStore.getState().clearResume()
      expect(useResumeStore.getState().validationIssues).toEqual([])
    })

    it('useValidationIssues exposes the same array reactively', () => {
      const { result } = renderHook(() => useValidationIssues())
      expect(result.current).toEqual([])

      act(() => {
        useResumeStore.getState().setResume(makeResume({ fullName: '' }))
      })
      expect(result.current.length).toBeGreaterThan(0)
    })
  })
})
