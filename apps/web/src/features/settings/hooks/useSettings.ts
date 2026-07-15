import { useMutation, useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query'
import {
  deleteKeySetting,
  fetchKeySettings,
  fetchProfile,
  fetchProviderSettings,
  updateGithubUsername,
  updateProviderSettings,
  upsertKeySetting,
} from '../../../lib/api/endpoints'
import type {
  KeyUpsertRequest,
  ManagedSecretName,
  ProvidersSettingsUpdateRequest,
  UpdateGithubUsernameRequest,
} from '../../../lib/api/dto'

export const PROVIDERS_QUERY_KEY = ['settings', 'providers'] as const
export const KEYS_QUERY_KEY = ['settings', 'keys'] as const
export const PROFILE_QUERY_KEY = ['profile'] as const
// Composer's Combobox (v3 ticket 07) and this feature's ModelPicker share the
// same query key/producer for the model catalog — invalidating it here is
// what makes the Composer's suggestion list (and the ModelPicker's own
// options) reflect a provider/key change without a page reload.
const MODELS_QUERY_KEY = ['models'] as const

export function useProviderSettings() {
  return useQuery({ queryKey: PROVIDERS_QUERY_KEY, queryFn: fetchProviderSettings })
}

export function useKeySettings() {
  return useQuery({ queryKey: KEYS_QUERY_KEY, queryFn: fetchKeySettings })
}

/** Every settings write below touches the model catalog's relevance (a new
 * active provider, a newly-configured/removed key can change availability or
 * unlock a provider's real model list) — invalidate providers + models
 * together so nothing needs a reload to see it. */
function invalidateProvidersAndModels(queryClient: QueryClient): void {
  void queryClient.invalidateQueries({ queryKey: PROVIDERS_QUERY_KEY })
  void queryClient.invalidateQueries({ queryKey: MODELS_QUERY_KEY })
}

export function useUpdateProviderSettings() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: ProvidersSettingsUpdateRequest) => updateProviderSettings(payload),
    onSuccess: () => invalidateProvidersAndModels(queryClient),
  })
}

export function useUpsertKeySetting() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: KeyUpsertRequest) => upsertKeySetting(payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: KEYS_QUERY_KEY })
      invalidateProvidersAndModels(queryClient)
    },
  })
}

export function useDeleteKeySetting() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (name: ManagedSecretName) => deleteKeySetting(name),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: KEYS_QUERY_KEY })
      invalidateProvidersAndModels(queryClient)
    },
  })
}

export function useProfile() {
  return useQuery({ queryKey: PROFILE_QUERY_KEY, queryFn: fetchProfile })
}

export function useUpdateGithubUsername() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: UpdateGithubUsernameRequest) => updateGithubUsername(payload),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: PROFILE_QUERY_KEY }),
  })
}
