import { useRestoreActiveAnalysisSession } from '../hooks/useAnalysisSessions'
import { AnalysisSessionSidebar } from './AnalysisSessionSidebar'
import { AnalysisPanel } from './AnalysisPanel'

/** v5 ticket f1: the Profile Analysis area's main layout — its own conversation list plus the
 * analysis panel. Text-only (no A4 preview), so it is a two-column shell rather than the
 * resume flow's three. Rendered by AppShell when the app mode is 'analysis'. */
export function AnalysisShell() {
  useRestoreActiveAnalysisSession()

  return (
    <main
      id="main-content"
      className="mx-auto flex w-full min-h-0 max-w-[1920px] flex-1 flex-col lg:flex-row"
    >
      <section
        aria-label="Analysis conversations"
        className="no-print min-h-0 flex-col border-stone-200 dark:border-zinc-800 lg:flex lg:w-56 lg:border-r"
      >
        <AnalysisSessionSidebar />
      </section>
      <section
        aria-label="Profile analysis"
        className="min-h-0 flex-1 flex-col bg-white/60 dark:bg-zinc-950/40 lg:flex"
      >
        <AnalysisPanel />
      </section>
    </main>
  )
}
