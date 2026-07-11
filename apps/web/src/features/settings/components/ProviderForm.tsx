import { useState, type FormEvent } from 'react'
import type { ManagedSecretName, ProviderAuthMode, ProviderName, SecretKeyEntry } from '../../../lib/api/dto'
import {
  useDeleteKeySetting,
  useKeySettings,
  useProviderSettings,
  useUpdateProviderSettings,
  useUpsertKeySetting,
} from '../hooks/useSettings'
import { ModelPicker } from './ModelPicker'

const PROVIDER_LABELS: Record<ProviderName, string> = {
  claude: 'Claude (Anthropic)',
  gemini: 'Gemini (Google)',
  ollama: 'Ollama (local)',
}

const AUTH_LABELS: Record<ProviderAuthMode, string> = {
  api_key: 'API key', // pragma: allowlist secret
  cli: 'Claude CLI',
  local: 'Local server',
  none: 'No auth required',
}

const KEY_LABELS: Record<ManagedSecretName, string> = {
  ANTHROPIC_API_KEY: 'Anthropic API key', // pragma: allowlist secret
  GEMINI_API_KEY: 'Gemini API key', // pragma: allowlist secret
  GITHUB_TOKEN: 'GitHub token', // pragma: allowlist secret
}

const FIELDSET_LEGEND_CLASS =
  'mb-2 text-[0.6875rem] font-semibold uppercase tracking-wider text-stone-500 dark:text-zinc-500'

function ProviderOption({
  label,
  checked,
  badge,
  onChange,
}: {
  label: string
  checked: boolean
  badge?: string
  onChange: () => void
}) {
  return (
    <label className="flex items-center justify-between gap-2 rounded-lg border border-stone-200 px-3 py-2 text-sm text-stone-800 has-[:checked]:border-stone-400 dark:border-zinc-700 dark:text-zinc-200 dark:has-[:checked]:border-zinc-500">
      <span className="flex items-center gap-2">
        <input
          type="radio"
          name="provider-mode"
          checked={checked}
          onChange={onChange}
          className="h-3.5 w-3.5"
        />
        {label}
      </span>
      {badge && <span className="text-xs text-stone-500 dark:text-zinc-500">{badge}</span>}
    </label>
  )
}

function KeyRow({
  entry,
  onSave,
  onRemove,
  saving,
}: {
  entry: SecretKeyEntry
  onSave: (value: string) => void
  onRemove: () => void
  saving: boolean
}) {
  const [value, setValue] = useState('')
  const label = KEY_LABELS[entry.name]

  if (entry.source === 'env') {
    return (
      <div className="flex items-center justify-between text-sm">
        <span className="text-stone-800 dark:text-zinc-200">{label}</span>
        <span className="text-xs text-stone-500 dark:text-zinc-500">Configured via environment</span>
      </div>
    )
  }

  if (entry.configured && entry.source === 'keychain') {
    return (
      <div className="flex items-center justify-between text-sm">
        <span className="text-stone-800 dark:text-zinc-200">{label}</span>
        <span className="flex items-center gap-2">
          <span className="text-xs text-stone-500 dark:text-zinc-500">Configured via keychain</span>
          <button
            type="button"
            onClick={onRemove}
            aria-label={`Remove ${label}`}
            className="rounded-md border border-stone-200 px-2 py-1 text-xs font-medium text-stone-600 hover:bg-stone-50 dark:border-zinc-700 dark:text-zinc-400 dark:hover:bg-zinc-800"
          >
            Remove
          </button>
        </span>
      </div>
    )
  }

  const handleSubmit = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    const trimmed = value.trim()
    if (!trimmed) return
    onSave(trimmed)
    // Cleared immediately (not on mutation success): a write-only secret should not linger in
    // component state any longer than the single moment it's handed off to the mutation.
    setValue('')
  }

  return (
    <form onSubmit={handleSubmit} className="flex items-center gap-2 text-sm">
      <label htmlFor={`settings-key-${entry.name}`} className="flex-1 text-stone-800 dark:text-zinc-200">
        {label}
      </label>
      <input
        id={`settings-key-${entry.name}`}
        type="password"
        autoComplete="off"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        placeholder="Paste a new key…"
        className="w-40 rounded-lg border border-stone-200 bg-white px-2 py-1 text-xs text-stone-900 shadow-sm placeholder:text-stone-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-stone-400 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100 dark:placeholder:text-zinc-400"
      />
      <button
        type="submit"
        disabled={!value.trim() || saving}
        aria-label={`Save ${label}`}
        className="rounded-md bg-stone-900 px-2.5 py-1 text-xs font-medium text-white disabled:opacity-40 dark:bg-zinc-100 dark:text-zinc-950"
      >
        Save
      </button>
    </form>
  )
}

/**
 * Provider/model/key management (v3 ticket 06): active provider (auto or a
 * concrete one) with availability+auth badges, the ModelPicker for whichever
 * provider is currently active, and write-only key rows. Every change has
 * immediate effect via the Settings API (no separate "save" step for the
 * form as a whole) — matches the backend's "efeito imediato, sem restart".
 */
export function ProviderForm() {
  const providersQuery = useProviderSettings()
  const keysQuery = useKeySettings()
  const updateProvider = useUpdateProviderSettings()
  const upsertKey = useUpsertKeySetting()
  const deleteKey = useDeleteKeySetting()

  if (providersQuery.isLoading || keysQuery.isLoading) {
    return <p className="text-sm text-stone-500 dark:text-zinc-500">Loading settings…</p>
  }
  if (providersQuery.isError || keysQuery.isError || !providersQuery.data || !keysQuery.data) {
    return (
      <p role="alert" className="text-sm text-red-600 dark:text-red-400">
        Couldn't load settings.
      </p>
    )
  }

  const { active, providers } = providersQuery.data
  const { keys } = keysQuery.data
  const activeEntry = active === 'auto' ? null : (providers.find((p) => p.name === active) ?? null)

  return (
    <div className="space-y-5">
      <fieldset>
        <legend className={FIELDSET_LEGEND_CLASS}>Active provider</legend>
        <div className="space-y-1.5">
          <ProviderOption
            label="Auto (best available)"
            checked={active === 'auto'}
            onChange={() => updateProvider.mutate({ provider: 'auto' })}
          />
          {providers.map((p) => (
            <ProviderOption
              key={p.name}
              label={PROVIDER_LABELS[p.name]}
              checked={active === p.name}
              badge={`${p.available ? 'Available' : 'Unavailable'} · ${AUTH_LABELS[p.auth]}`}
              onChange={() => updateProvider.mutate({ provider: p.name })}
            />
          ))}
        </div>
      </fieldset>

      <ModelPicker
        // Keyed by the active provider: switching providers should reset the picker's local
        // text to THAT provider's own defaultModel, which a remount gives for free (see
        // ModelPicker's own doc comment on why this isn't a setState-in-effect instead).
        key={active}
        id="settings-model-picker"
        provider={active}
        value={activeEntry?.defaultModel ?? ''}
        onSelect={(model) => updateProvider.mutate({ provider: active, defaultModel: model })}
      />

      <fieldset>
        <legend className={FIELDSET_LEGEND_CLASS}>API keys</legend>
        <div className="space-y-3">
          {keys.map((k) => (
            <KeyRow
              key={k.name}
              entry={k}
              saving={upsertKey.isPending || deleteKey.isPending}
              onSave={(value) => upsertKey.mutate({ name: k.name, value })}
              onRemove={() => deleteKey.mutate(k.name)}
            />
          ))}
        </div>
      </fieldset>
    </div>
  )
}
