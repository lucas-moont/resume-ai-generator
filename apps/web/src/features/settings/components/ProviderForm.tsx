import type { ProviderAuthMode, ProviderName } from '../../../lib/api/dto'
import { useKeySettings, useProviderSettings, useUpdateProviderSettings } from '../hooks/useSettings'
import { KeyRow } from './KeyRow'
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

/**
 * Provider/model/key management (v3 ticket 06): active provider (auto or a
 * concrete one) with availability+auth badges, the ModelPicker for whichever
 * provider is currently active, and write-only key rows (KeyRow). Every
 * change has immediate effect via the Settings API (no separate "save" step
 * for the form as a whole) — matches the backend's "efeito imediato, sem
 * restart". Note: an unavailable provider is deliberately still selectable —
 * the badge is informational, not a lock; a real error (if any) surfaces at
 * chat time, not here.
 */
export function ProviderForm() {
  const providersQuery = useProviderSettings()
  const keysQuery = useKeySettings()
  const updateProvider = useUpdateProviderSettings()

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

      {updateProvider.isError && (
        <p role="alert" className="text-xs text-red-600 dark:text-red-400">
          Couldn't update your provider/model settings. Try again.
        </p>
      )}

      <fieldset>
        <legend className={FIELDSET_LEGEND_CLASS}>API keys</legend>
        <div className="space-y-3">
          {keys.map((k) => (
            <KeyRow key={k.name} entry={k} />
          ))}
        </div>
      </fieldset>
    </div>
  )
}
