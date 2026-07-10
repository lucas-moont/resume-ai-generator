import { useChatSessionsList, useResumeChatSession } from '../hooks/useChatSession'
import { useChatStore } from '../store/chatStore'

export function SessionSidebar() {
  const { data, isError, isLoading } = useChatSessionsList()
  const { resumeSession, startNewChat } = useResumeChatSession()
  const activeSessionId = useChatStore((s) => s.sessionId)

  // Graceful degradation: if the list can't be loaded (e.g. this deployment
  // doesn't have the chat backend wired up yet -> 404), hide entirely rather
  // than show a broken panel. Same for the brief initial loading tick — the
  // list usually resolves fast enough that there's nothing worth a skeleton.
  if (isError || isLoading) return null

  const sessions = data?.sessions ?? []

  return (
    <nav
      aria-label="Chat sessions"
      className="flex h-full flex-col overflow-y-auto border-stone-200 bg-white/60 dark:border-zinc-800 dark:bg-zinc-950/40"
    >
      <div className="p-3">
        <button
          type="button"
          onClick={startNewChat}
          className="w-full rounded-lg border border-stone-200 bg-white px-3 py-2 text-left text-sm font-medium text-stone-800 shadow-sm hover:border-stone-300 hover:bg-stone-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-stone-400 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100 dark:hover:border-zinc-600 dark:hover:bg-zinc-800"
        >
          + New chat
        </button>
      </div>
      <ul className="flex-1 space-y-1 px-2 pb-3">
        {sessions.map((s) => (
          <li key={s.id}>
            <button
              type="button"
              onClick={() => void resumeSession(s.id)}
              aria-current={s.id === activeSessionId ? 'true' : undefined}
              className={`block w-full truncate rounded-lg px-3 py-2 text-left text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-stone-400 ${
                s.id === activeSessionId
                  ? 'bg-stone-900 text-white dark:bg-zinc-100 dark:text-zinc-950'
                  : 'text-stone-700 hover:bg-stone-100 dark:text-zinc-300 dark:hover:bg-zinc-800'
              }`}
            >
              {s.title || 'Untitled chat'}
            </button>
          </li>
        ))}
        {sessions.length === 0 && (
          <li className="px-3 py-2 text-xs text-stone-500 dark:text-zinc-500">No conversations yet.</li>
        )}
      </ul>
    </nav>
  )
}
