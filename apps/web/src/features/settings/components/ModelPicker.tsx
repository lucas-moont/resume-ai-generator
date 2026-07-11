import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { fetchModels } from '../../../lib/api/endpoints'
import type { ProviderMode } from '../../../lib/api/dto'
import { Combobox, type ComboboxOption } from '../../../ui/Combobox'
import { zIndex } from '../../../ui/zIndex'

export interface ModelPickerProps {
  id: string
  /** Which provider's models to offer — 'auto' offers the full aggregate catalog (there is no
   * single provider to scope to when the active mode is auto). */
  provider: ProviderMode
  value: string
  /** Fired only when the user actually picks a suggestion (click or Enter) — this is a picker
   * over the server's dynamic catalog, not a free-typed field like the Composer's model input. */
  onSelect: (value: string) => void
}

/**
 * Dynamic, per-provider model picker (v3 ticket 06) built on the Combobox
 * primitive (ticket 07) — reuses the SAME `['models']` query the Composer
 * reads, filtered client-side by the `provider` field GET /api/models
 * additively carries per item (ticket 03). One producer for model
 * suggestions app-wide, per ticket 07's "catálogo único" decision.
 */
export function ModelPicker({ id, provider, value, onSelect }: ModelPickerProps) {
  const modelsQuery = useQuery({ queryKey: ['models'], queryFn: fetchModels })
  const allModels = modelsQuery.data?.models ?? []
  const options = (
    provider === 'auto' ? allModels : allModels.filter((m) => m.provider === provider)
  ) satisfies ComboboxOption[]
  const emptyState = modelsQuery.isLoading
    ? 'Loading models…'
    : modelsQuery.isError
      ? "Couldn't load models."
      : 'No models available.'

  // Local display text, resynced from `value` whenever the persisted default (or the provider
  // being edited) changes. Typing updates this freely — the field must not feel frozen — but
  // only an explicit selection (click/Enter) calls onSelect, so a still-loading network write
  // isn't triggered by every keystroke.
  const [text, setText] = useState(value)
  useEffect(() => setText(value), [value, provider])

  return (
    <div>
      <label
        htmlFor={id}
        className="mb-1 block text-[0.6875rem] font-semibold uppercase tracking-wider text-stone-500 dark:text-zinc-500"
      >
        Default model
      </label>
      <Combobox
        id={id}
        aria-label="Default model"
        value={text}
        onChange={setText}
        onSelect={(opt) => onSelect(opt.value)}
        options={options}
        emptyState={emptyState}
        placeholder="Choose a model…"
        className="w-full rounded-lg border border-stone-200 bg-white px-2.5 py-1.5 text-sm text-stone-900 shadow-sm placeholder:text-stone-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-stone-400 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100 dark:placeholder:text-zinc-400 dark:focus-visible:ring-zinc-500"
        listClassName={`absolute ${zIndex.dropdown} mt-1 max-h-60 w-full overflow-auto rounded-lg border border-stone-200 bg-white py-1 shadow-lg dark:border-zinc-700 dark:bg-zinc-900`}
      />
    </div>
  )
}
