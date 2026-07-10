import type { ChatMessage } from '../store/chatStore'
import { ResumeUpdatedCard } from './cards/ResumeUpdatedCard'
import { ErrorCard } from './cards/ErrorCard'

export function AssistantMessage({
  message,
  onRetry,
}: {
  message: ChatMessage
  onRetry: (retryMessage: string) => void
}) {
  return (
    <div className="flex justify-start">
      <div className="max-w-[85%]">
        <div className="whitespace-pre-wrap rounded-2xl rounded-tl-sm border border-stone-200 bg-white px-4 py-2.5 text-sm text-stone-900 shadow-sm dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-100">
          {message.content}
        </div>
        {message.card?.type === 'resumeUpdated' && <ResumeUpdatedCard card={message.card} />}
        {message.card?.type === 'error' && <ErrorCard card={message.card} onRetry={onRetry} />}
      </div>
    </div>
  )
}
