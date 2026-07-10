import type { ChatMessage } from '../store/chatStore'
import { ResumeUpdatedCard } from './cards/ResumeUpdatedCard'
import { ErrorCard } from './cards/ErrorCard'
import { ProfileUpdatedCard } from './cards/ProfileUpdatedCard'
import { ProfileUpdateAppliedCard } from './cards/ProfileUpdateAppliedCard'

export function AssistantMessage({
  message,
  onRetry,
  onApproveDocument,
  onRejectDocument,
}: {
  message: ChatMessage
  onRetry: (retryMessage: string) => void
  onApproveDocument: (documentId: number, messageId: string) => Promise<void>
  onRejectDocument: (documentId: number, messageId: string) => Promise<void>
}) {
  return (
    <div className="flex justify-start">
      <div className="max-w-[85%]">
        <div className="whitespace-pre-wrap rounded-2xl rounded-tl-sm border border-stone-200 bg-white px-4 py-2.5 text-sm text-stone-900 shadow-sm dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-100">
          {message.content}
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
      </div>
    </div>
  )
}
