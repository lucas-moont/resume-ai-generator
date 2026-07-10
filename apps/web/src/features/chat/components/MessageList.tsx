import { useEffect, useRef, useState } from 'react'
import { useChatStore } from '../store/chatStore'
import { UserMessage } from './UserMessage'
import { AssistantMessage } from './AssistantMessage'
import { ProgressCard } from './cards/ProgressCard'
import { ChatEmptyState } from './ChatEmptyState'

const BOTTOM_THRESHOLD_PX = 80

export function MessageList({
  onRetry,
  onSuggestion,
  onApproveDocument,
  onRejectDocument,
}: {
  onRetry: (message: string) => void
  onSuggestion: (message: string) => void
  onApproveDocument: (documentId: number, messageId: string) => Promise<void>
  onRejectDocument: (documentId: number, messageId: string) => Promise<void>
}) {
  const messages = useChatStore((s) => s.messages)
  const streaming = useChatStore((s) => s.streaming)
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
          />
        ),
      )}
      {streaming && (
        <div className="flex justify-start">
          <div className="w-full max-w-[85%]">
            <ProgressCard streaming={streaming} />
          </div>
        </div>
      )}
    </div>
  )
}
