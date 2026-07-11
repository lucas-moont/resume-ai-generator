import { useEffect, useMemo, useState } from 'react'
import type { ChatMessage } from '../store/chatStore'
import { ResumeUpdatedCard } from './cards/ResumeUpdatedCard'
import { ErrorCard } from './cards/ErrorCard'
import { ProfileUpdatedCard } from './cards/ProfileUpdatedCard'
import { ProfileUpdateAppliedCard } from './cards/ProfileUpdateAppliedCard'
import { ProposalCard } from './cards/ProposalCard'
import { MarkdownContent } from './MarkdownContent'

const REVEAL_INTERVAL_MS = 90

function prefersReducedMotion(): boolean {
  if (typeof window === 'undefined' || !window.matchMedia) return false
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

/** Progressive reveal (v4, F4, spec §5): a freshly streamed bubble (`message.animate`) types
 * itself in by LINE, never by character (spec risk 4 — char-by-char reveal breaks markdown
 * mid-token and reads as noisy). Rehydrated bubbles (no `animate`, F5) and
 * `prefers-reduced-motion` both render the full content on the very first paint — no interval
 * at all in either case. */
function useRevealedContent(content: string, animate: boolean | undefined): string {
  const [reducedMotion] = useState(prefersReducedMotion)
  const shouldAnimate = animate === true && !reducedMotion
  const lines = useMemo(() => content.split('\n'), [content])
  const [revealedCount, setRevealedCount] = useState(() => (shouldAnimate ? 0 : lines.length))

  useEffect(() => {
    if (!shouldAnimate) return
    let idx = 0
    const id = setInterval(() => {
      idx += 1
      setRevealedCount(idx)
      if (idx >= lines.length) clearInterval(id)
    }, REVEAL_INTERVAL_MS)
    return () => clearInterval(id)
    // eslint-disable-next-line react-hooks/exhaustive-deps -- runs once for this bubble's mount; a given ChatMessage's content/animate never change after it's appended
  }, [])

  return lines.slice(0, revealedCount).join('\n')
}

export function AssistantMessage({
  message,
  onRetry,
  onApproveDocument,
  onRejectDocument,
  onApproveProposal,
  isLatestPendingProposal,
}: {
  message: ChatMessage
  onRetry: (retryMessage: string) => void
  onApproveDocument: (documentId: number, messageId: string) => Promise<void>
  onRejectDocument: (documentId: number, messageId: string) => Promise<void>
  onApproveProposal: () => void
  isLatestPendingProposal: boolean
}) {
  const revealedContent = useRevealedContent(message.content, message.animate)

  return (
    <div className="flex justify-start">
      <div className="max-w-[85%]">
        <div className="rounded-2xl rounded-tl-sm border border-stone-200 bg-white px-4 py-2.5 text-sm text-stone-900 shadow-sm dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-100">
          <MarkdownContent content={revealedContent} />
        </div>
        {message.card?.type === 'resumeUpdated' && <ResumeUpdatedCard card={message.card} />}
        {message.card?.type === 'error' && <ErrorCard card={message.card} onRetry={onRetry} />}
        {message.card?.type === 'profileUpdated' && (
          <ProfileUpdatedCard
            card={message.card}
            onApprove={(documentId) => onApproveDocument(documentId, message.id)}
            onReject={(documentId) => onRejectDocument(documentId, message.id)}
          />
        )}
        {message.card?.type === 'profileUpdateApplied' && <ProfileUpdateAppliedCard card={message.card} />}
        {message.card?.type === 'proposal' && (
          <ProposalCard
            card={message.card}
            showApproveButton={isLatestPendingProposal}
            onApprove={onApproveProposal}
          />
        )}
      </div>
    </div>
  )
}
