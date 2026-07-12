import { SessionSidebar } from '../features/chat/components/SessionSidebar'
import { ChatPanel } from '../features/chat/components/ChatPanel'
import { useRestoreActiveSession } from '../features/chat/hooks/useChatSession'
import { PreviewPanel } from '../features/resume/components/PreviewPanel'
import { AppHeader } from './AppHeader'
import { useMobileTabUrl } from './useMobileTabUrl'

function tabButtonClass(selected: boolean): string {
  return `rounded-lg px-3 py-1.5 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-stone-400 dark:focus-visible:ring-zinc-500 ${
    selected
      ? 'bg-stone-900 text-white dark:bg-zinc-100 dark:text-zinc-950'
      : 'text-stone-600 hover:bg-stone-100 dark:text-zinc-400 dark:hover:bg-zinc-800'
  }`
}

export function AppShell() {
  const [mobileTab, setMobileTab] = useMobileTabUrl()
  useRestoreActiveSession()

  return (
    <div className="print-shell flex h-screen flex-col bg-stone-50 text-stone-900 transition-colors duration-200 dark:bg-zinc-950 dark:text-zinc-100">
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-[100] focus:rounded-lg focus:bg-white focus:px-4 focus:py-2 focus:text-sm focus:font-medium focus:text-stone-900 focus:shadow-lg dark:focus:bg-zinc-900 dark:focus:text-zinc-100"
      >
        Skip to main content
      </a>
      <AppHeader />

      <main
        id="main-content"
        className="print-grid mx-auto flex w-full min-h-0 max-w-[1920px] flex-1 flex-col lg:flex-row"
      >
        <div
          role="tablist"
          aria-label="View"
          className="no-print flex gap-1 border-b border-stone-200 bg-white px-4 py-2 dark:border-zinc-800 dark:bg-zinc-950 lg:hidden"
        >
          <button
            type="button"
            role="tab"
            aria-selected={mobileTab === 'sessions'}
            onClick={() => setMobileTab('sessions')}
            className={tabButtonClass(mobileTab === 'sessions')}
          >
            Sessions
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={mobileTab === 'chat'}
            onClick={() => setMobileTab('chat')}
            className={tabButtonClass(mobileTab === 'chat')}
          >
            Chat
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={mobileTab === 'preview'}
            onClick={() => setMobileTab('preview')}
            className={tabButtonClass(mobileTab === 'preview')}
          >
            Preview
          </button>
        </div>

        {/* SessionSidebar hides itself (renders null) when the list can't be
            loaded — no extra conditional needed here for that degradation. */}
        <section
          aria-label="Sessions"
          className={`no-print min-h-0 flex-col border-stone-200 dark:border-zinc-800 lg:flex lg:w-56 lg:border-r ${
            mobileTab === 'sessions' ? 'flex' : 'hidden'
          }`}
        >
          <SessionSidebar />
        </section>

        <section
          aria-label="Chat"
          className={`no-print min-h-0 flex-col border-stone-200 bg-white/60 dark:border-zinc-800 dark:bg-zinc-950/40 lg:flex lg:w-[38%] lg:max-w-[640px] lg:border-r ${
            mobileTab === 'chat' ? 'flex' : 'hidden'
          }`}
        >
          <ChatPanel />
        </section>

        <section
          aria-label="Preview"
          className={`min-h-0 flex-1 flex-col lg:flex ${mobileTab === 'preview' ? 'flex' : 'hidden'}`}
        >
          <PreviewPanel />
        </section>
      </main>
    </div>
  )
}
