import { useEffect, useRef, useState } from 'react'
import { useChatStore, type ChatMessage } from '../store/chatStore'
import { UserMessage } from './UserMessage'
import { AssistantMessage } from './AssistantMessage'
import { ProgressCard } from './cards/ProgressCard'
import { ChatEmptyState } from './ChatEmptyState'

const BOTTOM_THRESHOLD_PX = 80

function prefersReducedMotion(): boolean {
  if (typeof window === 'undefined' || !window.matchMedia) return false
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

/** v4, F4, spec §3.5: the assistant "thinking" indicator during the `analyzing_job` heartbeat
 * (Analysis / Proposal Turn classification) — swapped in for ProgressCard, since there's no
 * multi-step checklist to show for a single LLM call. `prefers-reduced-motion` freezes the
 * dots (still communicates "busy") instead of removing them. */
function TypingIndicator() {
  const [reducedMotion] = useState(prefersReducedMotion)
  return (
    <div
      role="status"
      aria-live="polite"
      aria-label="Assistente está digitando"
      className="inline-flex items-center gap-1.5 rounded-2xl rounded-tl-sm border border-stone-200 bg-white px-4 py-3 shadow-sm dark:border-zinc-800 dark:bg-zinc-900"
    >
      {[0, 1, 2].map((i) => (
        <span
          key={i}
          className={`h-1.5 w-1.5 rounded-full bg-stone-400 dark:bg-zinc-500 ${reducedMotion ? '' : 'animate-bounce'}`}
          style={reducedMotion ? undefined : { animationDelay: `${i * 120}ms` }}
        />
      ))}
    </div>
  )
}

/** v4, F4, spec §5 button rule: "Aprovar e gerar" only appears on the LATEST message whose
 * card is a still-`proposed` proposal matching the session's Pending Proposal id — after an
 * adjust two bubbles share that id (F3 deliberately leaves the older one's status alone), and
 * only the newer bubble should offer the shortcut. */
function findLatestPendingProposalMessageId(
  messages: ChatMessage[],
  pendingProposalId: number | null,
): string | null {
  if (pendingProposalId === null) return null
  let latest: string | null = null
  for (const m of messages) {
    if (m.card?.type === 'proposal' && m.card.proposalId === pendingProposalId && m.card.status === 'proposed') {
      latest = m.id
    }
  }
  return latest
}

export function MessageList({
  onRetry,
  onSuggestion,
  onApproveDocument,
  onRejectDocument,
  onApproveProposal,
}: {
  onRetry: (message: string) => void
  onSuggestion: (message: string) => void
  onApproveDocument: (documentId: number, messageId: string) => Promise<void>
  onRejectDocument: (documentId: number, messageId: string) => Promise<void>
  onApproveProposal: () => void
}) {
  const messages = useChatStore((s) => s.messages)
  const streaming = useChatStore((s) => s.streaming)
  const pendingProposalId = useChatStore((s) => s.pendingProposalId)
  const containerRef = useRef<HTMLDivElement>(null)
  const [pinnedToBottom, setPinnedToBottom] = useState(true)

  // If the user has scrolled up to read earlier messages, new content must
  // NOT yank them back down — only auto-scroll while already near the
  // bottom.
  const handleScroll = () => {
    const el = containerRef.current
    if (!el) return
    const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight
    setPinnedToBottom(distanceFromBottom < BOTTOM_THRESHOLD_PX)
  }

  useEffect(() => {
    const el = containerRef.current
    if (!el || !pinnedToBottom) return
    el.scrollTop = el.scrollHeight
    // eslint-disable-next-line react-hooks/exhaustive-deps -- scroll on any new content while pinned
  }, [messages, streaming])

  if (messages.length === 0 && !streaming) {
    return <ChatEmptyState onSuggestion={onSuggestion} />
  }

  const latestPendingProposalMessageId = findLatestPendingProposalMessageId(messages, pendingProposalId)

  return (
    <div
      ref={containerRef}
      onScroll={handleScroll}
      data-testid="message-list-scroll"
      className="flex-1 space-y-4 overflow-y-auto px-4 py-6 sm:px-6"
      aria-live="polite"
      aria-relevant="additions"
    >
      {messages.map((message) =>
        message.role === 'user' ? (
          <UserMessage key={message.id} message={message} />
        ) : (
          <AssistantMessage
            key={message.id}
            message={message}
            onRetry={onRetry}
            onApproveDocument={onApproveDocument}
            onRejectDocument={onRejectDocument}
            onApproveProposal={onApproveProposal}
            isLatestPendingProposal={message.id === latestPendingProposalMessageId}
          />
        ),
      )}
      {streaming && (
        <div className="flex justify-start">
          <div className="w-full max-w-[85%]">
            {/* `''` is the pre-first-stage window (useChatStream's optimistic update, before
                the server's real first `stage` event lands) — neither turn type has a
                checklist item to show yet, so it gets the same dots as `analyzing_job`
                rather than a ProgressCard asserting `preparing_context` is already underway. */}
            {streaming.step === 'analyzing_job' || streaming.step === '' ? (
              <TypingIndicator />
            ) : (
              <ProgressCard streaming={streaming} />
            )}
          </div>
        </div>
      )}
    </div>
  )
}
