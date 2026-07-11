import { useState, type FormEvent } from 'react'
import type { ManagedSecretName, SecretKeyEntry } from '../../../lib/api/dto'
import { useDeleteKeySetting, useUpsertKeySetting } from '../hooks/useSettings'

const KEY_LABELS: Record<ManagedSecretName, string> = {
  ANTHROPIC_API_KEY: 'Anthropic API key', // pragma: allowlist secret
  GEMINI_API_KEY: 'Gemini API key', // pragma: allowlist secret
  GITHUB_TOKEN: 'GitHub token', // pragma: allowlist secret
}

const ALERT_CLASS = 'text-xs text-red-600 dark:text-red-400'

export interface KeyRowProps {
  entry: SecretKeyEntry
}

/**
 * One managed API key's row (v3 ticket 06, extracted from ProviderForm in the
 * review's fix round): env-configured is read-only, keychain-configured is
 * removable, unconfigured is a write-only save form. Owns its own
 * upsert/delete mutations — each row's pending/error state is scoped to
 * itself, not shared across every key in the list.
 */
export function KeyRow({ entry }: KeyRowProps) {
  const [value, setValue] = useState('')
  const upsertKey = useUpsertKeySetting()
  const deleteKey = useDeleteKeySetting()
  const label = KEY_LABELS[entry.name]

  if (entry.source === 'env') {
    return (
      <div className="flex items-center justify-between text-sm">
        <span className="text-stone-800 dark:text-zinc-200">{label}</span>
        <span className="text-xs text-stone-500 dark:text-zinc-300">Configured via environment</span>
      </div>
    )
  }

  if (entry.configured && entry.source === 'keychain') {
    return (
      <div className="space-y-1">
        <div className="flex items-center justify-between text-sm">
          <span className="text-stone-800 dark:text-zinc-200">{label}</span>
          <span className="flex items-center gap-2">
            <span className="text-xs text-stone-500 dark:text-zinc-300">Configured via keychain</span>
            <button
              type="button"
              onClick={() => deleteKey.mutate(entry.name)}
              disabled={deleteKey.isPending}
              aria-label={`Remove ${label}`}
              className="rounded-md border border-stone-200 px-2 py-1.5 text-xs font-medium text-stone-600 hover:bg-stone-50 disabled:opacity-40 dark:border-zinc-700 dark:text-zinc-300 dark:hover:bg-zinc-800"
            >
              Remove
            </button>
          </span>
        </div>
        {deleteKey.isError && <p role="alert" className={ALERT_CLASS}>{`Couldn't remove ${label}. Try again.`}</p>}
      </div>
    )
  }

  const handleSubmit = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    const trimmed = value.trim()
    if (!trimmed) return
    upsertKey.mutate(
      { name: entry.name, value: trimmed },
      // Cleared only on success: a failed save must leave the typed value in place (so the
      // user can see the failure and retry) instead of silently discarding it, which would
      // make a failed save look identical to a successful one.
      { onSuccess: () => setValue('') },
    )
  }

  return (
    <div className="space-y-1">
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
          className="w-40 rounded-lg border border-stone-200 bg-white px-2 py-1.5 text-xs text-stone-900 shadow-sm placeholder:text-stone-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-stone-400 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100 dark:placeholder:text-zinc-300"
        />
        <button
          type="submit"
          disabled={!value.trim() || upsertKey.isPending}
          aria-label={`Save ${label}`}
          className="rounded-md bg-stone-900 px-2.5 py-1.5 text-xs font-medium text-white disabled:opacity-40 dark:bg-zinc-100 dark:text-zinc-950"
        >
          Save
        </button>
      </form>
      {upsertKey.isError && <p role="alert" className={ALERT_CLASS}>{`Couldn't save ${label}. Try again.`}</p>}
    </div>
  )
}
