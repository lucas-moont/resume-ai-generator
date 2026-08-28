import { useCallback, useEffect, useState } from 'react'
import { useChatStream } from '../hooks/useChatStream'
import { useChatStore, type ProfileUpdatedCard } from '../store/chatStore'
import { translateInstruction } from '../translateInstruction'
import { useFileUpload, type SettledUpload } from '../../upload/useFileUpload'
import { applySourceDocument, rejectSourceDocument } from '../../../lib/api/endpoints'
import { ProfileDocumentConflictError, toSettleError } from '../profileDocumentConflict'
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
 * passes in.
 *
 * A 409 means the document was already settled elsewhere (the other stale
 * duplicate card, a concurrent tab, ...) -- the card is synced to the REAL
 * status the backend reports rather than left showing "proposed" with live
 * buttons (ticket 12's safety net). */
async function settleProfileDocument(
  status: ProfileUpdatedCard['status'],
  apiCall: (documentId: number) => Promise<unknown>,
  documentId: number,
  messageId: string,
): Promise<void> {
  try {
    await apiCall(documentId)
  } catch (e) {
    const settleError = toSettleError(e)
    if (settleError instanceof ProfileDocumentConflictError && settleError.actualStatus) {
      const actualStatus = settleError.actualStatus
      useChatStore.getState().updateMessageCard(messageId, (card) =>
        card.type === 'profileUpdated' ? { ...card, status: actualStatus } : card,
      )
    }
    throw settleError
  }
  useChatStore.getState().updateMessageCard(messageId, (card) =>
    card.type === 'profileUpdated' ? { ...card, status } : card,
  )
}

export function ChatPanel() {
  const { send, retry, stop } = useChatStream()
  const [draft, setDraft] = useState('')
  const [focusSignal, setFocusSignal] = useState(0)

  // Ticket 12 (QA gate v2): the backend dedupes uploads by sha256 and hands back the SAME
  // documentId for bytes it already has -- re-attaching that file (accidental double-drop, a
  // retry, whatever) must update the existing card in place, not append a second live
  // Approve/Reject pair for one Source Document.
  const handleSettledUpload = useCallback((result: SettledUpload) => {
    const { messages, updateMessageCard, appendAssistantMessage } = useChatStore.getState()
    const existing = messages.find(
      (m) => m.card?.type === 'profileUpdated' && m.card.documentId === result.documentId,
    )
    if (existing) {
      updateMessageCard(existing.id, (card) =>
        card.type === 'profileUpdated'
          ? {
              ...card,
              status: result.status,
              diffSummary: result.diffSummary,
              opsCount: result.opsCount,
              error: result.error,
            }
          : card,
      )
      return
    }
    appendAssistantMessage(profileUpdateMessageText(result), {
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

  // v4, F4: the "Aprovar e gerar" button shortcut (spec §5) — same turn as free-text approval,
  // just with the deterministic `proposalAction` flag so the backend skips LLM classification.
  const handleApproveProposal = useCallback(() => {
    void send('Aprovar e gerar', { proposalAction: 'approve' })
  }, [send])

  // The resume-screen language picker sets `pendingTranslation` (it cannot call `send`
  // itself — only this panel owns it). Consume it into a translate turn, once, when nothing is
  // already streaming, then clear it so it never re-fires.
  const pendingTranslation = useChatStore((s) => s.pendingTranslation)
  const isStreaming = useChatStore((s) => s.streaming !== null)
  const clearPendingTranslation = useChatStore((s) => s.clearPendingTranslation)
  useEffect(() => {
    if (!pendingTranslation || isStreaming) return
    const target = pendingTranslation
    clearPendingTranslation()
    void send(translateInstruction(target))
  }, [pendingTranslation, isStreaming, clearPendingTranslation, send])

  return (
    <div className="flex h-full min-h-0 flex-col">
      <MessageList
        onRetry={(message) => void retry(message)}
        onSuggestion={handleSuggestion}
        onApproveDocument={handleApproveDocument}
        onRejectDocument={handleRejectDocument}
        onApproveProposal={handleApproveProposal}
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
