import { useEffect, useRef, useState } from 'react'
import { formatRelativeTime } from '../formatRelativeTime'
import { useDeleteSession, useRenameSession, useResumeChatSession, useSessions } from '../hooks/useChatSession'
import { useChatStore } from '../store/chatStore'
import { ConfirmDialog } from '../../../ui/ConfirmDialog'
import { Tooltip } from '../../../ui/Tooltip'

const renameButtonId = (sessionId: number) => `session-rename-button-${sessionId}`

export function SessionSidebar() {
  const { data, isError, isLoading } = useSessions()
  const { resumeSession, startNewChat } = useResumeChatSession()
  const deleteSessionMutation = useDeleteSession()
  const renameSessionMutation = useRenameSession()
  const activeSessionId = useChatStore((s) => s.sessionId)
  const [pendingDelete, setPendingDelete] = useState<{ id: number; title: string | null } | null>(null)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [editValue, setEditValue] = useState('')
  // v4.1-03: which session's pencil button should regain focus once edit mode closes — the
  // button unmounts while editing (input takes its place). Looked up by id (rather than a
  // ref captured on the button) because Tooltip's cloneElement (../../../ui/Tooltip.tsx)
  // unconditionally overwrites the child's `ref` prop to attach its own hover/position
  // tracking, so a ref passed to a Tooltip-wrapped button is silently dropped. Set right
  // before setEditingId(null); an effect keyed on editingId runs after the button remounts.
  const justClosedEditId = useRef<number | null>(null)
  // v4.1-03: Enter/Escape already decide save-vs-cancel explicitly; this suppresses the
  // input's onBlur handler from ALSO acting when the browser fires a blur event as a side
  // effect of the input unmounting right after (which would otherwise double-submit on Enter,
  // or incorrectly save the Escape'd edit).
  const editHandledRef = useRef(false)

  useEffect(() => {
    if (editingId === null && justClosedEditId.current !== null) {
      document.getElementById(renameButtonId(justClosedEditId.current))?.focus()
      justClosedEditId.current = null
    }
  }, [editingId])

  // Graceful degradation: if the list can't be loaded (e.g. this deployment
  // doesn't have the chat backend wired up yet -> 404), hide entirely rather
  // than show a broken panel. Same for the brief initial loading tick — the
  // list usually resolves fast enough that there's nothing worth a skeleton.
  if (isError || isLoading) return null

  const sessions = data?.sessions ?? []

  const handleConfirmDelete = () => {
    if (!pendingDelete) return
    const id = pendingDelete.id
    deleteSessionMutation.mutate(id, {
      onSuccess: () => {
        if (useChatStore.getState().sessionId === id) {
          useChatStore.getState().reset()
        }
      },
    })
    setPendingDelete(null)
  }

  const startEditing = (id: number, title: string | null) => {
    setEditValue(title ?? '')
    setEditingId(id)
  }

  const exitEditing = (id: number) => {
    justClosedEditId.current = id
    setEditingId(null)
  }

  const saveEdit = (id: number, originalTitle: string | null) => {
    const trimmed = editValue.trim()
    if (trimmed && trimmed !== (originalTitle ?? '')) {
      renameSessionMutation.mutate({ sessionId: id, title: trimmed })
    }
    exitEditing(id)
  }

  return (
    <>
      <nav
        aria-label="Chat sessions"
        className="flex h-full flex-col overflow-y-auto border-stone-200 bg-white/60 dark:border-zinc-800 dark:bg-zinc-950/40"
      >
        <div className="p-3">
          <button
            type="button"
            onClick={startNewChat}
            className="w-full rounded-lg border border-stone-200 bg-white px-3 py-2 text-left text-sm font-medium text-stone-800 shadow-sm hover:border-stone-300 hover:bg-stone-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-stone-400 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100 dark:hover:border-zinc-600 dark:hover:bg-zinc-800 dark:focus-visible:ring-zinc-500"
          >
            + New chat
          </button>
        </div>
        <ul className="flex-1 space-y-1 px-2 pb-3">
          {sessions.map((s) => {
            const active = s.id === activeSessionId
            const isEditing = editingId === s.id
            const accessibleName = `Rename ${s.title || 'this chat'}`
            return (
              <li key={s.id} className="group flex items-center gap-1">
                {isEditing ? (
                  <input
                    type="text"
                    autoFocus
                    value={editValue}
                    aria-label={accessibleName}
                    onChange={(e) => setEditValue(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') {
                        e.preventDefault()
                        editHandledRef.current = true
                        saveEdit(s.id, s.title)
                      } else if (e.key === 'Escape') {
                        e.preventDefault()
                        editHandledRef.current = true
                        exitEditing(s.id)
                      }
                    }}
                    onBlur={() => {
                      if (editHandledRef.current) {
                        editHandledRef.current = false
                        return
                      }
                      saveEdit(s.id, s.title)
                    }}
                    className="min-w-0 flex-1 rounded-lg border border-stone-300 bg-white px-3 py-2 text-sm text-stone-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-stone-400 dark:border-zinc-600 dark:bg-zinc-900 dark:text-zinc-100 dark:focus-visible:ring-zinc-500"
                  />
                ) : (
                  <button
                    type="button"
                    onClick={() => void resumeSession(s.id)}
                    aria-current={active ? 'true' : undefined}
                    className={`min-w-0 flex-1 rounded-lg px-3 py-2 text-left text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-stone-400 dark:focus-visible:ring-zinc-500 ${
                      active
                        ? 'bg-stone-900 text-white dark:bg-zinc-100 dark:text-zinc-950'
                        : 'text-stone-700 hover:bg-stone-100 dark:text-zinc-300 dark:hover:bg-zinc-800'
                    }`}
                  >
                    <span className="block truncate">{s.title || 'Untitled chat'}</span>
                    <span
                      className={`block text-xs ${active ? 'text-white/70 dark:text-zinc-950/60' : 'text-stone-500 dark:text-zinc-500'}`}
                    >
                      {formatRelativeTime(s.updatedAt)}
                    </span>
                  </button>
                )}
                {!isEditing && (
                  <Tooltip label="Rename chat" placement="top">
                    <button
                      type="button"
                      id={renameButtonId(s.id)}
                      onClick={() => startEditing(s.id, s.title)}
                      aria-label={accessibleName}
                      className="shrink-0 rounded-lg p-1.5 text-stone-400 opacity-0 hover:bg-stone-100 hover:text-stone-700 focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-stone-400 group-hover:opacity-100 dark:text-zinc-600 dark:hover:bg-zinc-800 dark:hover:text-zinc-300"
                    >
                      <svg aria-hidden="true" viewBox="0 0 20 20" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="1.6">
                        <path
                          d="M13.5 3.5l3 3L7 16H4v-3l9.5-9.5z"
                          strokeLinecap="round"
                          strokeLinejoin="round"
                        />
                      </svg>
                    </button>
                  </Tooltip>
                )}
                {!isEditing && (
                  <Tooltip label="Delete chat" placement="top">
                    <button
                      type="button"
                      onClick={() => setPendingDelete({ id: s.id, title: s.title })}
                      aria-label={`Delete ${s.title || 'this chat'}`}
                      className="shrink-0 rounded-lg p-1.5 text-stone-400 opacity-0 hover:bg-red-50 hover:text-red-600 focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-red-400 group-hover:opacity-100 dark:text-zinc-600 dark:hover:bg-red-950/40 dark:hover:text-red-400"
                    >
                      <svg aria-hidden="true" viewBox="0 0 20 20" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="1.6">
                        <path d="M6 6l8 8M14 6l-8 8" strokeLinecap="round" />
                      </svg>
                    </button>
                  </Tooltip>
                )}
              </li>
            )
          })}
          {sessions.length === 0 && (
            <li className="px-3 py-2 text-xs text-stone-500 dark:text-zinc-500">No conversations yet.</li>
          )}
        </ul>
      </nav>
      <ConfirmDialog
        open={pendingDelete !== null}
        title={`Delete ${pendingDelete?.title || 'this chat'}?`}
        description="This can't be undone."
        confirmLabel="Delete"
        cancelLabel="Cancel"
        destructive
        onConfirm={handleConfirmDelete}
        onCancel={() => setPendingDelete(null)}
      />
    </>
  )
}
