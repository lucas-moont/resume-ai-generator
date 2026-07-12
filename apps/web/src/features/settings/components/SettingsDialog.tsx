import { useState } from 'react'
import { Dialog } from '../../../ui/Dialog'
import { Tooltip } from '../../../ui/Tooltip'
import { ProviderForm } from './ProviderForm'

/**
 * Self-contained gear-button + Dialog (v3 ticket 06), same idiom as
 * ThemeToggle/AppHeader's GitHub-check button — AppHeader just renders
 * `<SettingsDialog />` alongside them, no state lifted.
 */
export function SettingsDialog() {
  const [open, setOpen] = useState(false)

  return (
    <>
      <Tooltip label="Settings" placement="bottom">
        <button
          type="button"
          onClick={() => setOpen(true)}
          aria-label="Settings"
          className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-stone-200 bg-white text-stone-700 shadow-sm transition-[color,background-color,border-color,box-shadow] hover:border-stone-300 hover:bg-stone-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-stone-400 focus-visible:ring-offset-2 focus-visible:ring-offset-stone-100 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-200 dark:hover:border-zinc-600 dark:hover:bg-zinc-800 dark:focus-visible:ring-zinc-500 dark:focus-visible:ring-offset-zinc-950"
        >
          <svg aria-hidden="true" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.75">
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6Z"
            />
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09a1.65 1.65 0 0 0-1.08-1.51 1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1Z"
            />
          </svg>
        </button>
      </Tooltip>

      <Dialog
        open={open}
        onClose={() => setOpen(false)}
        title="Settings"
        description="Choose the active AI provider, its default model, and manage API keys — every change takes effect immediately."
      >
        {/* Dialog's panel is a fixed max-w-sm (ticket 05) — not overridden here via a
            colliding Tailwind width utility (fragile: cascade order, not class-list order,
            decides which wins). No overflow-auto wrapper here (design fix round, P1): the
            ModelPicker's absolutely-positioned Combobox list must never sit inside a
            scroll-clipping ancestor, so ProviderForm renders unclipped and scopes its OWN
            overflow-y-auto to just the API-keys list — the section that actually grows. */}
        <ProviderForm />
        <div className="mt-4 flex justify-end">
          <button
            type="button"
            onClick={() => setOpen(false)}
            aria-label="Close settings"
            className="rounded-lg bg-stone-900 px-3 py-1.5 text-sm font-medium text-white shadow-sm hover:bg-stone-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-stone-500 dark:bg-zinc-100 dark:text-zinc-950 dark:hover:bg-white"
          >
            Done
          </button>
        </div>
      </Dialog>
    </>
  )
}
