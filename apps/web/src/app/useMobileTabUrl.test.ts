import { act, renderHook, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { useMobileTabUrl } from './useMobileTabUrl'

afterEach(() => {
  window.history.pushState(null, '', '/')
})

describe('useMobileTabUrl', () => {
  it('defaults to "chat" when the URL has no tab param', () => {
    const { result } = renderHook(() => useMobileTabUrl())
    expect(result.current[0]).toBe('chat')
  })

  it('reads the initial tab from the URL when present and valid', () => {
    window.history.pushState(null, '', '/?tab=preview')
    const { result } = renderHook(() => useMobileTabUrl())
    expect(result.current[0]).toBe('preview')
  })

  it('falls back to the default for an unrecognized tab value in the URL', () => {
    window.history.pushState(null, '', '/?tab=bogus')
    const { result } = renderHook(() => useMobileTabUrl())
    expect(result.current[0]).toBe('chat')
  })

  it('setting a tab updates state and reflects it in the URL', () => {
    const { result } = renderHook(() => useMobileTabUrl())
    act(() => result.current[1]('sessions'))
    expect(result.current[0]).toBe('sessions')
    expect(new URLSearchParams(window.location.search).get('tab')).toBe('sessions')
  })

  it('back navigation (popstate) restores the previous tab', async () => {
    const { result } = renderHook(() => useMobileTabUrl())
    act(() => result.current[1]('sessions'))
    act(() => result.current[1]('preview'))
    expect(result.current[0]).toBe('preview')

    act(() => window.history.back())
    // jsdom fires popstate asynchronously on history.back(); poll for it.
    await waitFor(() => expect(result.current[0]).toBe('sessions'))
  })
})
