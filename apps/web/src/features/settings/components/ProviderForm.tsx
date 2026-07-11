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
  'mb-2 text-[0.6875rem] font-semibold uppercase tracking-wider text-stone-500 dark:text-zinc-300'

function ProviderOption({
  label,
  checked,
  badge,
  onChange,
  disabled,
}: {
  label: string
  checked: boolean
  badge?: string
  onChange: () => void
  disabled?: boolean
}) {
  return (
    <label className="flex items-center justify-between gap-2 rounded-lg border border-stone-200 px-3 py-2 text-sm text-stone-800 has-[:checked]:border-stone-400 has-[:disabled]:opacity-60 dark:border-zinc-700 dark:text-zinc-200 dark:has-[:checked]:border-zinc-500">
      <span className="flex items-center gap-2">
        <input
          type="radio"
          name="provider-mode"
          checked={checked}
          onChange={onChange}
          disabled={disabled}
          className="h-3.5 w-3.5"
        />
        {label}
      </span>
      {badge && <span className="text-xs text-stone-500 dark:text-zinc-300">{badge}</span>}
    </label>
  )
}

/** v3 ticket 11: the env-lock explanation shared by the active-provider fieldset and the
 * default-model row — same "badge/lock + which var" language in both places. Takes an `id` so
 * the active-provider fieldset can wire `aria-describedby` to it (fix round, standards): a
 * `disabled` radio drops out of the tab order entirely, so a sighted-only badge would never
 * reach a keyboard/screen-reader user who tabs past the whole fieldset without pausing on it. */
function EnvLockNote({ id, envVar }: { id?: string; envVar: string }) {
  return (
    <p id={id} className="mb-2 flex items-center gap-1.5 text-xs text-stone-500 dark:text-zinc-300">
      <span aria-hidden="true">🔒</span>
      Pinned by the <code className="font-mono">{envVar}</code> environment variable — unset it
      to change this here.
    </p>
  )
}

const ACTIVE_PROVIDER_LOCK_NOTE_ID = 'settings-active-provider-lock-note'

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
    return <p className="text-sm text-stone-500 dark:text-zinc-300">Loading settings…</p>
  }
  if (providersQuery.isError || keysQuery.isError || !providersQuery.data || !keysQuery.data) {
    return (
      <p role="alert" className="text-sm text-red-600 dark:text-red-400">
        Couldn't load settings.
      </p>
    )
  }

  const { active, providers, activeLockedByEnv, activeEnvVar } = providersQuery.data
  const { keys } = keysQuery.data
  const activeEntry = active === 'auto' ? null : (providers.find((p) => p.name === active) ?? null)

  return (
    <div className="space-y-5">
      <fieldset aria-describedby={activeLockedByEnv ? ACTIVE_PROVIDER_LOCK_NOTE_ID : undefined}>
        <legend className={FIELDSET_LEGEND_CLASS}>Active provider</legend>
        {activeLockedByEnv && <EnvLockNote id={ACTIVE_PROVIDER_LOCK_NOTE_ID} envVar={activeEnvVar} />}
        <div className="space-y-1.5">
          <ProviderOption
            label="Auto (best available)"
            checked={active === 'auto'}
            disabled={activeLockedByEnv}
            onChange={() => updateProvider.mutate({ provider: 'auto' })}
          />
          {providers.map((p) => (
            <ProviderOption
              key={p.name}
              label={PROVIDER_LABELS[p.name]}
              checked={active === p.name}
              disabled={activeLockedByEnv}
              badge={`${p.available ? 'Available' : 'Unavailable'} · ${AUTH_LABELS[p.auth]}`}
              onChange={() => updateProvider.mutate({ provider: p.name })}
            />
          ))}
        </div>
      </fieldset>

      {activeEntry?.defaultModelLockedByEnv ? (
        // Locked: a static readout instead of the ModelPicker control, same idea as KeyRow's
        // read-only "env" row — no interactive control means no theatrical PUT, and it avoids
        // teaching the shared Combobox primitive (ticket 07) a disabled state it doesn't need
        // anywhere else.
        <div>
          <p className={FIELDSET_LEGEND_CLASS}>Default model</p>
          <EnvLockNote envVar={activeEntry.defaultModelEnvVar} />
          <p className="rounded-lg border border-stone-200 bg-stone-50 px-2.5 py-1.5 text-sm text-stone-600 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-300">
            {activeEntry.defaultModel}
          </p>
        </div>
      ) : (
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
      )}

      {updateProvider.isError && (
        <p role="alert" className="text-xs text-red-600 dark:text-red-400">
          Couldn't update your provider/model settings. Try again.
        </p>
      )}

      <fieldset>
        <legend className={FIELDSET_LEGEND_CLASS}>API keys</legend>
        {/* Design fix round (P1): overflow-y-auto is scoped to JUST this list, not the whole
            dialog — this is the section that actually grows (more managed keys over time), and
            keeping the scroll boundary here means the Default model Combobox above never has a
            scroll-clipping ancestor between it and the dialog panel. */}
        <div className="max-h-56 space-y-3 overflow-y-auto pr-1">
          {keys.map((k) => (
            <KeyRow key={k.name} entry={k} />
          ))}
        </div>
      </fieldset>
    </div>
  )
}
