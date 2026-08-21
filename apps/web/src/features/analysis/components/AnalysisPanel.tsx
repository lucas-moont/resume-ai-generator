import { useAnalysisStore } from '../store/analysisStore'
import { AnalysisCard } from './AnalysisCard'
import { AnalysisComposer } from './AnalysisComposer'

function EmptyState() {
  return (
    <div className="flex h-full flex-col items-center justify-center px-6 text-center">
      <h3 className="font-display text-lg font-semibold text-stone-800 dark:text-zinc-100">
        Análise de Perfil do LinkedIn
      </h3>
      <p className="mt-2 max-w-md text-sm leading-relaxed text-stone-600 dark:text-zinc-400">
        Peça ajuda com uma seção — por exemplo:{' '}
        <em>“melhora meu headline, o atual é ‘Dev’, minha área é backend”</em> — ou envie o PDF
        exportado do seu LinkedIn. O agente devolve o que mudar e pergunta quando faltar
        contexto, sem inventar nada.
      </p>
    </div>
  )
}

/** v5 ticket f1: the analysis conversation shell. Renders the turn history; the composer
 * (text + PDF upload) lands in f3 and the rich per-section card in f4 — for now an assistant
 * turn shows its summary/reply text. */
export function AnalysisPanel() {
  const messages = useAnalysisStore((s) => s.messages)
  const streaming = useAnalysisStore((s) => s.streaming)

  return (
    <div className="flex h-full flex-col">
      <div className="min-h-0 flex-1 overflow-y-auto p-4">
        {messages.length === 0 ? (
          <EmptyState />
        ) : (
          <ul className="mx-auto flex max-w-2xl flex-col gap-3">
            {messages.map((m) => (
              <li
                key={m.id}
                className={m.role === 'user' ? 'flex justify-end' : 'flex justify-start'}
              >
                {m.role === 'assistant' && m.analysis ? (
                  <AnalysisCard summary={m.analysis.summary} items={m.analysis.items} />
                ) : (
                  <div
                    className={`max-w-[85%] whitespace-pre-wrap rounded-2xl px-4 py-2 text-sm ${
                      m.role === 'user'
                        ? 'bg-stone-900 text-white dark:bg-zinc-100 dark:text-zinc-950'
                        : 'bg-white text-stone-800 shadow-sm dark:bg-zinc-900 dark:text-zinc-100'
                    }`}
                  >
                    {m.content}
                  </div>
                )}
              </li>
            ))}
            {streaming && (
              <li className="flex justify-start">
                <div
                  role="status"
                  className="rounded-2xl bg-white px-4 py-2 text-sm text-stone-500 shadow-sm dark:bg-zinc-900 dark:text-zinc-400"
                >
                  {streaming.message || 'Analisando…'}
                </div>
              </li>
            )}
          </ul>
        )}
      </div>
      <AnalysisComposer />
    </div>
  )
}
