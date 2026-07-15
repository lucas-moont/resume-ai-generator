import { useState, type FormEvent } from 'react'
import { useProfile, useUpdateGithubUsername } from '../hooks/useSettings'

const ALERT_CLASS = 'text-xs text-red-600 dark:text-red-400'

/**
 * GitHub username manual config (v4.1 follow-up): unlike KeyRow's write-only
 * secrets, this isn't sensitive — the current value is shown in plain text and
 * directly editable (no "remove then retype" dance), plus a one-click Remove
 * to clear it. Reads/writes via useProfile/useUpdateGithubUsername.
 */
export function GithubUsernameRow() {
  const profileQuery = useProfile()

  if (profileQuery.isLoading) {
    return <p className="text-sm text-stone-500 dark:text-zinc-300">Loading…</p>
  }
  if (profileQuery.isError) {
    return (
      <p role="alert" className="text-sm text-red-600 dark:text-red-400">
        Couldn't load your GitHub username.
      </p>
    )
  }

  return <GithubUsernameForm current={profileQuery.data?.githubUsername ?? null} />
}

interface GithubUsernameFormProps {
  current: string | null
}

/**
 * Mounted only once the profile query has resolved, so `current` is real data
 * by the time this renders — the input's initial state can be derived from it
 * directly instead of synced in via an effect (same pattern as KeyRow's local
 * state).
 */
function GithubUsernameForm({ current }: GithubUsernameFormProps) {
  const updateGithubUsername = useUpdateGithubUsername()
  const [value, setValue] = useState(current ?? '')

  const handleSubmit = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    updateGithubUsername.mutate({ githubUsername: value.trim() || null })
  }

  const handleRemove = () => {
    setValue('')
    updateGithubUsername.mutate({ githubUsername: null })
  }

  return (
    <div className="space-y-1">
      <form onSubmit={handleSubmit} className="flex items-center gap-2 text-sm">
        <label htmlFor="settings-github-username" className="flex-1 text-stone-800 dark:text-zinc-200">
          Username
        </label>
        <input
          id="settings-github-username"
          type="text"
          autoComplete="off"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder="octocat"
          className="w-40 rounded-lg border border-stone-200 bg-white px-2 py-1.5 text-xs text-stone-900 shadow-sm placeholder:text-stone-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-stone-400 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100 dark:placeholder:text-zinc-300"
        />
        <button
          type="submit"
          disabled={updateGithubUsername.isPending}
          aria-label="Save GitHub username"
          className="rounded-md bg-stone-900 px-2.5 py-1.5 text-xs font-medium text-white disabled:opacity-40 dark:bg-zinc-100 dark:text-zinc-950"
        >
          Save
        </button>
        {current && (
          <button
            type="button"
            onClick={handleRemove}
            disabled={updateGithubUsername.isPending}
            aria-label="Remove GitHub username"
            className="rounded-md border border-stone-200 px-2 py-1.5 text-xs font-medium text-stone-600 hover:bg-stone-50 disabled:opacity-40 dark:border-zinc-700 dark:text-zinc-300 dark:hover:bg-zinc-800"
          >
            Remove
          </button>
        )}
      </form>
      {updateGithubUsername.isError && (
        <p role="alert" className={ALERT_CLASS}>
          Couldn't save your GitHub username. Try again.
        </p>
      )}
    </div>
  )
}
