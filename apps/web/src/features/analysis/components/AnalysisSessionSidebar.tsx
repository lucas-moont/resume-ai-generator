import { useState } from 'react'
import { formatRelativeTime } from '../../chat/formatRelativeTime'
import {
  useAnalysisSessions,
  useCreateAnalysisSession,
  useDeleteAnalysisSession,
  useResumeAnalysisSession,
} from '../hooks/useAnalysisSessions'
import { useAnalysisStore } from '../store/analysisStore'
import { ConfirmDialog } from '../../../ui/ConfirmDialog'
import { Tooltip } from '../../../ui/Tooltip'

export function AnalysisSessionSidebar() {
  const { data, isError, isLoading } = useAnalysisSessions()
  const { resumeSession, startNewAnalysis } = useResumeAnalysisSession()
  const createMutation = useCreateAnalysisSession()
  const deleteMutation = useDeleteAnalysisSession()
  const activeSessionId = useAnalysisStore((s) => s.sessionId)
  const [pendingDelete, setPendingDelete] = useState<{ id: number; title: string | null } | null>(null)

  if (isError || isLoading) return null

  const sessions = data?.sessions ?? []

  const handleNew = () => {
    startNewAnalysis()
    createMutation.mutate(undefined, {
      onSuccess: (created) => {
        void resumeSession(created.id)
      },
    })
  }

  const handleConfirmDelete = () => {
    if (!pendingDelete) return
    const id = pendingDelete.id
    deleteMutation.mutate(id, {
      onSuccess: () => {
        if (useAnalysisStore.getState().sessionId === id) {
          useAnalysisStore.getState().reset()
        }
      },
    })
    setPendingDelete(null)
  }

  return (
    <>
      <nav
        aria-label="Analysis conversations"
        className="flex h-full flex-col overflow-y-auto border-stone-200 bg-white/60 dark:border-zinc-800 dark:bg-zinc-950/40"
      >
        <div className="p-3">
          <button
            type="button"
            onClick={handleNew}
            className="w-full rounded-lg border border-stone-200 bg-white px-3 py-2 text-left text-sm font-medium text-stone-800 shadow-sm hover:border-stone-300 hover:bg-stone-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-stone-400 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100 dark:hover:border-zinc-600 dark:hover:bg-zinc-800 dark:focus-visible:ring-zinc-500"
          >
            + Nova análise
          </button>
        </div>
        <ul className="flex-1 space-y-1 px-2 pb-3">
          {sessions.map((s) => {
            const active = s.id === activeSessionId
            return (
              <li key={s.id} className="group flex items-center gap-1">
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
                  <span className="block truncate">{s.title || 'Análise sem título'}</span>
                  <span
                    className={`block text-xs ${active ? 'text-white/70 dark:text-zinc-950/60' : 'text-stone-500 dark:text-zinc-500'}`}
                  >
                    {formatRelativeTime(s.updatedAt)}
                  </span>
                </button>
                <Tooltip label="Excluir análise" placement="top">
                  <button
                    type="button"
                    onClick={() => setPendingDelete({ id: s.id, title: s.title })}
                    aria-label={`Excluir ${s.title || 'esta análise'}`}
                    className="shrink-0 rounded-lg p-1.5 text-stone-400 opacity-0 hover:bg-red-50 hover:text-red-600 focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-red-400 group-hover:opacity-100 dark:text-zinc-600 dark:hover:bg-red-950/40 dark:hover:text-red-400"
                  >
                    <svg aria-hidden="true" viewBox="0 0 20 20" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="1.6">
                      <path d="M6 6l8 8M14 6l-8 8" strokeLinecap="round" />
                    </svg>
                  </button>
                </Tooltip>
              </li>
            )
          })}
          {sessions.length === 0 && (
            <li className="px-3 py-2 text-xs text-stone-500 dark:text-zinc-500">
              Nenhuma análise ainda.
            </li>
          )}
        </ul>
      </nav>
      <ConfirmDialog
        open={pendingDelete !== null}
        title={`Excluir ${pendingDelete?.title || 'esta análise'}?`}
        description="Isso não pode ser desfeito."
        confirmLabel="Excluir"
        cancelLabel="Cancelar"
        destructive
        onConfirm={handleConfirmDelete}
        onCancel={() => setPendingDelete(null)}
      />
    </>
  )
}
