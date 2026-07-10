import { useCallback, useState } from 'react'
import { useChatStream } from '../hooks/useChatStream'
import { useChatStore } from '../store/chatStore'
import { useFileUpload, type SettledUpload } from '../../upload/useFileUpload'
import { applySourceDocument, rejectSourceDocument } from '../../../lib/api/endpoints'
import { MessageList } from './MessageList'
import { Composer } from './Composer'

function profileUpdateMessageText(result: SettledUpload): string {
  if (result.status === 'failed') return `Couldn't process ${result.filename}.`
  if (result.diffSummary.length === 0) return `Checked ${result.filename} — nothing new to merge.`
  return `Reviewed ${result.filename} — here's what I found.`
}

export function ChatPanel() {
  const { send, retry, stop } = useChatStream()
  const [draft, setDraft] = useState('')
  const [focusSignal, setFocusSignal] = useState(0)

  const handleSettledUpload = useCallback((result: SettledUpload) => {
    useChatStore.getState().appendAssistantMessage(profileUpdateMessageText(result), {
      type: 'profileUpdated',
      documentId: result.documentId,
      filename: result.filename,
      status: result.status,
      diffSummary: result.diffSummary,
      opsCount: result.opsCount,
      error: result.error,
    })
  }, [])

  const { attachments, validationError, addFiles, removeAttachment, retryAttachment } = useFileUpload({
    onSettled: handleSettledUpload,
  })

  const handleSuggestion = (text: string) => {
    setDraft(text)
    setFocusSignal((n) => n + 1)
  }

  const handleApproveDocument = useCallback(async (documentId: number, messageId: string) => {
    await applySourceDocument(documentId)
    useChatStore.getState().updateMessageCard(messageId, (card) =>
      card.type === 'profileUpdated' ? { ...card, status: 'applied' } : card,
    )
  }, [])

  const handleRejectDocument = useCallback(async (documentId: number, messageId: string) => {
    await rejectSourceDocument(documentId)
    useChatStore.getState().updateMessageCard(messageId, (card) =>
      card.type === 'profileUpdated' ? { ...card, status: 'rejected' } : card,
    )
  }, [])

  return (
    <div className="flex h-full min-h-0 flex-col">
      <MessageList
        onRetry={(message) => void retry(message)}
        onSuggestion={handleSuggestion}
        onApproveDocument={handleApproveDocument}
        onRejectDocument={handleRejectDocument}
      />
      <Composer
        draft={draft}
        onDraftChange={setDraft}
        focusSignal={focusSignal}
        onSend={(message, options) => void send(message, options)}
        onStop={stop}
        attachments={attachments}
        validationError={validationError}
        onAddFiles={addFiles}
        onRemoveAttachment={removeAttachment}
        onRetryAttachment={retryAttachment}
      />
    </div>
  )
}
