import { useCallback, useState } from 'react'
import { useChatStream } from '../hooks/useChatStream'
import { useChatStore, type ProfileUpdatedCard } from '../store/chatStore'
import { useFileUpload, type SettledUpload } from '../../upload/useFileUpload'
import { applySourceDocument, rejectSourceDocument } from '../../../lib/api/endpoints'
import { MessageList } from './MessageList'
import { Composer } from './Composer'

function profileUpdateMessageText(result: SettledUpload): string {
  if (result.status === 'failed') return `Couldn't process ${result.filename}.`
  if (result.diffSummary.length === 0) return `Checked ${result.filename} — nothing new to merge.`
  return `Reviewed ${result.filename} — here's what I found.`
}

/** Approve and reject are the same shape (call the API, then flip the
 * card's status once it settles) — they only differ in which endpoint they
 * call and which status they land on, so that's the one thing each caller
 * passes in. */
async function settleProfileDocument(
  status: ProfileUpdatedCard['status'],
  apiCall: (documentId: number) => Promise<unknown>,
  documentId: number,
  messageId: string,
): Promise<void> {
  await apiCall(documentId)
  useChatStore.getState().updateMessageCard(messageId, (card) =>
    card.type === 'profileUpdated' ? { ...card, status } : card,
  )
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

  const handleApproveDocument = useCallback(
    (documentId: number, messageId: string) => settleProfileDocument('applied', applySourceDocument, documentId, messageId),
    [],
  )

  const handleRejectDocument = useCallback(
    (documentId: number, messageId: string) => settleProfileDocument('rejected', rejectSourceDocument, documentId, messageId),
    [],
  )

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
