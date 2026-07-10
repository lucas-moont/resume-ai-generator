const EXAMPLE_JOB_DESCRIPTION =
  'Senior Backend Engineer — distributed systems team. Own service reliability, design APIs used by ' +
  'millions of requests/day, and mentor mid-level engineers. Strong Python/Go, Kubernetes, and ' +
  'PostgreSQL experience required.'

export function ChatEmptyState({
  onSuggestion,
}: {
  onSuggestion: (message: string) => void
}) {
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-6 px-6 py-12 text-center">
      <div>
        <h2 className="font-display text-xl font-semibold text-stone-900 dark:text-zinc-50">
          Let's build your resume
        </h2>
        <p className="mx-auto mt-2 max-w-sm text-sm leading-relaxed text-stone-600 dark:text-zinc-400">
          Paste a job description to generate a tailored, ATS-friendly resume — or just start typing
          and I'll figure out what you need.
        </p>
      </div>
      <div className="flex flex-wrap justify-center gap-2">
        <button
          type="button"
          onClick={() => onSuggestion('')}
          className="rounded-xl border border-stone-200 bg-white px-3.5 py-2 text-sm font-medium text-stone-800 shadow-sm hover:border-stone-300 hover:bg-stone-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-stone-400 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100 dark:hover:border-zinc-600 dark:hover:bg-zinc-800 dark:focus-visible:ring-zinc-500"
        >
          Paste a job description
        </button>
        <button
          type="button"
          onClick={() => onSuggestion(EXAMPLE_JOB_DESCRIPTION)}
          className="rounded-xl border border-stone-200 bg-white px-3.5 py-2 text-sm font-medium text-stone-800 shadow-sm hover:border-stone-300 hover:bg-stone-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-stone-400 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100 dark:hover:border-zinc-600 dark:hover:bg-zinc-800 dark:focus-visible:ring-zinc-500"
        >
          Generate with an example
        </button>
      </div>
    </div>
  )
}
