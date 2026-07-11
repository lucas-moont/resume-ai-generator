import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import type { ReactNode } from 'react'
import {
  useDeleteKeySetting,
  useKeySettings,
  useProviderSettings,
  useUpdateProviderSettings,
  useUpsertKeySetting,
} from './useSettings'
import { fetchModels } from '../../../lib/api/endpoints'
import { server } from '../../../test/setup'
import { DEFAULT_KEYS_SETTINGS, DEFAULT_PROVIDERS_SETTINGS } from '../../../test/msw/handlers'

function wrapper({ children }: { children: ReactNode }) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
}

describe('useProviderSettings', () => {
  it('resolves the default (unconfigured) providers response', async () => {
    const { result } = renderHook(() => useProviderSettings(), { wrapper })

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data).toEqual(DEFAULT_PROVIDERS_SETTINGS)
  })
})

describe('useKeySettings', () => {
  it('resolves the default (all unconfigured) keys response', async () => {
    const { result } = renderHook(() => useKeySettings(), { wrapper })

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data).toEqual(DEFAULT_KEYS_SETTINGS)
  })
})

describe('useUpdateProviderSettings', () => {
  it('invalidates the providers AND models queries on success, so both refetch without a reload', async () => {
    let providersRefetches = 0
    let modelsRefetches = 0
    server.use(
      http.get('/api/settings/providers', () => {
        providersRefetches += 1
        return HttpResponse.json(DEFAULT_PROVIDERS_SETTINGS)
      }),
      http.get('/api/models', () => {
        modelsRefetches += 1
        return HttpResponse.json({ default: 'x', models: [] })
      }),
      http.put('/api/settings/providers', () =>
        HttpResponse.json({ active: 'claude', providers: DEFAULT_PROVIDERS_SETTINGS.providers }),
      ),
    )
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    function localWrapper({ children }: { children: ReactNode }) {
      return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    }

    // Both queries must be actively observed for invalidateQueries to trigger
    // a real refetch (an inactive/unobserved query is only marked stale) —
    // mirrors SettingsDialog (providers) + Composer (models) both mounted at once.
    const { result } = renderHook(
      () => ({
        providers: useProviderSettings(),
        models: useQuery({ queryKey: ['models'], queryFn: fetchModels }),
        mutation: useUpdateProviderSettings(),
      }),
      { wrapper: localWrapper },
    )
    await waitFor(() => expect(result.current.providers.isSuccess).toBe(true))
    await waitFor(() => expect(result.current.models.isSuccess).toBe(true))
    const providersBefore = providersRefetches
    const modelsBefore = modelsRefetches

    result.current.mutation.mutate({ provider: 'claude' })

    await waitFor(() => expect(result.current.mutation.isSuccess).toBe(true))
    await waitFor(() => expect(providersRefetches).toBeGreaterThan(providersBefore))
    await waitFor(() => expect(modelsRefetches).toBeGreaterThan(modelsBefore))
  })
})

describe('useUpsertKeySetting', () => {
  it('invalidates keys, providers, AND models queries on success, so all three refetch without a reload', async () => {
    let keysRefetches = 0
    let providersRefetches = 0
    let modelsRefetches = 0
    server.use(
      http.get('/api/settings/keys', () => {
        keysRefetches += 1
        return HttpResponse.json(DEFAULT_KEYS_SETTINGS)
      }),
      http.get('/api/settings/providers', () => {
        providersRefetches += 1
        return HttpResponse.json(DEFAULT_PROVIDERS_SETTINGS)
      }),
      http.get('/api/models', () => {
        modelsRefetches += 1
        return HttpResponse.json({ default: 'x', models: [] })
      }),
      http.put('/api/settings/keys', () =>
        HttpResponse.json({ name: 'GEMINI_API_KEY', configured: true, source: 'keychain' }),
      ),
    )
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    function localWrapper({ children }: { children: ReactNode }) {
      return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    }

    // All three must be actively observed for invalidateQueries to trigger a real refetch —
    // mirrors useUpdateProviderSettings's test above.
    const { result } = renderHook(
      () => ({
        keys: useKeySettings(),
        providers: useProviderSettings(),
        models: useQuery({ queryKey: ['models'], queryFn: fetchModels }),
        mutation: useUpsertKeySetting(),
      }),
      { wrapper: localWrapper },
    )
    await waitFor(() => expect(result.current.keys.isSuccess).toBe(true))
    await waitFor(() => expect(result.current.providers.isSuccess).toBe(true))
    await waitFor(() => expect(result.current.models.isSuccess).toBe(true))
    const keysBefore = keysRefetches
    const providersBefore = providersRefetches
    const modelsBefore = modelsRefetches

    result.current.mutation.mutate({ name: 'GEMINI_API_KEY', value: 'new-secret-value' })

    await waitFor(() => expect(result.current.mutation.isSuccess).toBe(true))
    await waitFor(() => expect(keysRefetches).toBeGreaterThan(keysBefore))
    await waitFor(() => expect(providersRefetches).toBeGreaterThan(providersBefore))
    await waitFor(() => expect(modelsRefetches).toBeGreaterThan(modelsBefore))
  })
})

describe('useDeleteKeySetting', () => {
  it('invalidates keys, providers, AND models queries on success, so all three refetch without a reload', async () => {
    let keysRefetches = 0
    let providersRefetches = 0
    let modelsRefetches = 0
    server.use(
      http.get('/api/settings/keys', () => {
        keysRefetches += 1
        return HttpResponse.json(DEFAULT_KEYS_SETTINGS)
      }),
      http.get('/api/settings/providers', () => {
        providersRefetches += 1
        return HttpResponse.json(DEFAULT_PROVIDERS_SETTINGS)
      }),
      http.get('/api/models', () => {
        modelsRefetches += 1
        return HttpResponse.json({ default: 'x', models: [] })
      }),
      http.delete('/api/settings/keys/GEMINI_API_KEY', () => new HttpResponse(null, { status: 204 })),
    )
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    function localWrapper({ children }: { children: ReactNode }) {
      return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    }

    const { result } = renderHook(
      () => ({
        keys: useKeySettings(),
        providers: useProviderSettings(),
        models: useQuery({ queryKey: ['models'], queryFn: fetchModels }),
        mutation: useDeleteKeySetting(),
      }),
      { wrapper: localWrapper },
    )
    await waitFor(() => expect(result.current.keys.isSuccess).toBe(true))
    await waitFor(() => expect(result.current.providers.isSuccess).toBe(true))
    await waitFor(() => expect(result.current.models.isSuccess).toBe(true))
    const keysBefore = keysRefetches
    const providersBefore = providersRefetches
    const modelsBefore = modelsRefetches

    result.current.mutation.mutate('GEMINI_API_KEY')

    await waitFor(() => expect(result.current.mutation.isSuccess).toBe(true))
    await waitFor(() => expect(keysRefetches).toBeGreaterThan(keysBefore))
    await waitFor(() => expect(providersRefetches).toBeGreaterThan(providersBefore))
    await waitFor(() => expect(modelsRefetches).toBeGreaterThan(modelsBefore))
  })
})
