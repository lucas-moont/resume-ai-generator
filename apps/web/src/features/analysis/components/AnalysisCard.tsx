import { useState } from 'react'
import type { AnalysisItemDto, AnalysisPriority, AnalysisSection } from '../../../lib/api/dto'

const SECTION_LABEL: Record<AnalysisSection, string> = {
  headline: 'Headline',
  about: 'Sobre',
  experience: 'Experiência',
  skills: 'Competências',
  completeness: 'Completude',
}

const PRIORITY_LABEL: Record<AnalysisPriority, string> = {
  alta: 'Alta',
  média: 'Média',
  baixa: 'Baixa',
}

const PRIORITY_CLASS: Record<AnalysisPriority, string> = {
  alta: 'bg-red-100 text-red-800 dark:bg-red-950/50 dark:text-red-300',
  média: 'bg-amber-100 text-amber-800 dark:bg-amber-950/50 dark:text-amber-300',
  baixa: 'bg-stone-100 text-stone-600 dark:bg-zinc-800 dark:text-zinc-400',
}

const HEADLINE_MAX = 220

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false)
  const onCopy = async () => {
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      // Clipboard blocked (e.g. no permission) — leave the label unchanged rather than error.
    }
  }
  return (
    <button
      type="button"
      onClick={() => void onCopy()}
      aria-label="Copiar sugestão"
      className="shrink-0 rounded-lg border border-stone-200 px-2 py-1 text-xs font-medium text-stone-600 hover:bg-stone-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-stone-400 dark:border-zinc-700 dark:text-zinc-300 dark:hover:bg-zinc-800"
    >
      {copied ? 'Copiado!' : 'Copiar'}
    </button>
  )
}

function AnalysisItemRow({ item }: { item: AnalysisItemDto }) {
  const overLimit = item.section === 'headline' && item.suggestion.length > HEADLINE_MAX
  return (
    <li className="rounded-xl border border-stone-200 bg-white p-3 dark:border-zinc-800 dark:bg-zinc-900/60">
      <div className="mb-1.5 flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="text-xs font-semibold uppercase tracking-wide text-stone-500 dark:text-zinc-400">
            {SECTION_LABEL[item.section]}
          </span>
          <span className={`rounded-full px-2 py-0.5 text-[0.6875rem] font-medium ${PRIORITY_CLASS[item.priority]}`}>
            {PRIORITY_LABEL[item.priority]}
          </span>
        </div>
        <CopyButton text={item.suggestion} />
      </div>
      {item.current != null && item.current !== '' && (
        <p className="mb-1 text-xs text-stone-400 line-through dark:text-zinc-600">{item.current}</p>
      )}
      <p className="whitespace-pre-wrap text-sm text-stone-800 dark:text-zinc-100">{item.suggestion}</p>
      {item.section === 'headline' && (
        <p className={`mt-1 text-xs ${overLimit ? 'text-red-600 dark:text-red-400' : 'text-stone-400 dark:text-zinc-500'}`}>
          {item.suggestion.length}/{HEADLINE_MAX} caracteres
        </p>
      )}
      <p className="mt-1.5 text-xs leading-relaxed text-stone-500 dark:text-zinc-400">{item.rationale}</p>
    </li>
  )
}

/** v5 ticket f4: renders a Profile Analysis turn — a short summary plus one card per section
 * (current → suggestion, rationale, priority, copy; headline shows a ≤220-char counter). */
export function AnalysisCard({ summary, items }: { summary: string; items: AnalysisItemDto[] }) {
  return (
    <div className="w-full max-w-[85%] rounded-2xl bg-white p-3 shadow-sm dark:bg-zinc-900">
      {summary && (
        <p className="mb-2 whitespace-pre-wrap px-1 text-sm text-stone-700 dark:text-zinc-200">{summary}</p>
      )}
      <ul className="flex flex-col gap-2">
        {items.map((item, i) => (
          <AnalysisItemRow key={`${item.section}-${i}`} item={item} />
        ))}
      </ul>
    </div>
  )
}
