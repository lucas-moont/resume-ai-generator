import { useState } from 'react'
import { ApiError, fetchGithubRepos } from '../lib/api/endpoints'
import { ThemeToggle } from './theme/ThemeToggle'

export function AppHeader() {
  const [ghInfo, setGhInfo] = useState<string | null>(null)
  const [checking, setChecking] = useState(false)

  const checkGithub = async () => {
    setChecking(true)
    setGhInfo(null)
    try {
      const data = await fetchGithubRepos()
      if (data.warning) setGhInfo(data.warning)
      else if (!data.repos?.length) setGhInfo('No repositories in response.')
      else setGhInfo(`Loaded ${data.repos.length} repos from GitHub.`)
    } catch (e) {
      setGhInfo(
        e instanceof ApiError
          ? ((e.detail as string | undefined) ?? 'GitHub check failed')
          : 'Could not reach API (is the backend running?)',
      )
    } finally {
      setChecking(false)
    }
  }

  return (
    <header className="no-print border-b border-stone-200/80 bg-white/80 backdrop-blur-md dark:border-zinc-800 dark:bg-zinc-950/80">
      <div className="mx-auto flex max-w-[1600px] flex-wrap items-end justify-between gap-4 px-4 py-5 sm:px-6 lg:px-8">
        <div className="min-w-0">
          <h1 className="font-display text-pretty text-2xl font-semibold tracking-tight text-stone-900 sm:text-3xl dark:text-zinc-50">
            Resume agent
          </h1>
          <p className="mt-1 max-w-xl text-sm leading-relaxed text-stone-600 dark:text-zinc-400">
            Local AI API · FastAPI · ATS-friendly layout
          </p>
        </div>
        <div className="flex items-center gap-2">
          {ghInfo && (
            <p role="status" className="max-w-xs text-xs text-stone-600 dark:text-zinc-400">
              {ghInfo}
            </p>
          )}
          <button
            type="button"
            onClick={() => void checkGithub()}
            disabled={checking}
            aria-label="Check GitHub connection"
            title="Check GitHub connection"
            className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-stone-200 bg-white text-stone-700 shadow-sm transition-[color,background-color,border-color,box-shadow] hover:border-stone-300 hover:bg-stone-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-stone-400 focus-visible:ring-offset-2 focus-visible:ring-offset-stone-100 disabled:opacity-50 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-200 dark:hover:border-zinc-600 dark:hover:bg-zinc-800 dark:focus-visible:ring-zinc-500 dark:focus-visible:ring-offset-zinc-950"
          >
            <svg aria-hidden="true" viewBox="0 0 24 24" width="18" height="18" fill="currentColor">
              <path d="M12 2C6.477 2 2 6.484 2 12.021c0 4.428 2.865 8.184 6.839 9.504.5.092.682-.217.682-.483 0-.237-.009-.868-.014-1.703-2.782.605-3.369-1.343-3.369-1.343-.454-1.158-1.11-1.466-1.11-1.466-.908-.62.069-.608.069-.608 1.003.071 1.531 1.032 1.531 1.032.892 1.53 2.341 1.088 2.91.833.091-.647.35-1.088.636-1.339-2.221-.253-4.556-1.113-4.556-4.951 0-1.093.39-1.988 1.029-2.688-.103-.253-.446-1.272.098-2.65 0 0 .84-.269 2.75 1.026A9.564 9.564 0 0 1 12 6.844c.85.004 1.705.115 2.504.337 1.909-1.295 2.748-1.026 2.748-1.026.546 1.378.202 2.397.1 2.65.64.7 1.028 1.595 1.028 2.688 0 3.848-2.339 4.695-4.566 4.943.359.309.678.919.678 1.852 0 1.336-.012 2.415-.012 2.743 0 .268.18.58.688.482A10.02 10.02 0 0 0 22 12.021C22 6.484 17.522 2 12 2Z" />
            </svg>
          </button>
          <ThemeToggle />
        </div>
      </div>
    </header>
  )
}
