import { ApiError } from '../../lib/api/client'
import type { ProfileUpdatedCard } from './store/chatStore'

type DocumentStatus = ProfileUpdatedCard['status']

/**
 * Thrown by ChatPanel's settleProfileDocument when approve/reject hits a 409 --
 * the backend's detail always names the document's actual current status (see
 * apps/api's `http_error(409, f"Source Document {id} is '{row.status}', not
 * 'proposed' -- ...")`), so this carries both that status (to resync the card)
 * and a message honest enough to show the user, instead of the generic
 * retry-inviting failure ProfileUpdatedCard otherwise falls back to.
 */
export class ProfileDocumentConflictError extends Error {
  actualStatus: DocumentStatus | null

  constructor(message: string, actualStatus: DocumentStatus | null) {
    super(message)
    this.name = 'ProfileDocumentConflictError'
    this.actualStatus = actualStatus
  }
}

const KNOWN_STATUSES: readonly DocumentStatus[] = [
  'stored',
  'extracted',
  'proposed',
  'applied',
  'rejected',
  'failed',
]

const FRIENDLY_MESSAGE: Record<DocumentStatus, string> = {
  stored: 'This document is still being processed.',
  extracted: 'This document is still being processed.',
  proposed: 'This document is still awaiting review.',
  applied: 'This document was already applied to your profile.',
  rejected: 'This document was already discarded.',
  failed: "This document couldn't be processed.",
}

function parseActualStatus(detail: unknown): DocumentStatus | null {
  if (typeof detail !== 'string') return null
  const match = /is '([a-z]+)'/.exec(detail)
  const status = match?.[1]
  return status && (KNOWN_STATUSES as readonly string[]).includes(status) ? (status as DocumentStatus) : null
}

/**
 * Converts a settle (approve/reject) failure into a ProfileDocumentConflictError
 * when it's a 409 -- the one case where the card's proposed/applied/rejected
 * state disagrees with reality rather than a transient failure worth retrying.
 * Any other error (network, 500, etc.) passes through unchanged.
 */
export function toSettleError(e: unknown): unknown {
  if (!(e instanceof ApiError) || e.status !== 409) return e
  const actualStatus = parseActualStatus(e.detail)
  const message = actualStatus
    ? FRIENDLY_MESSAGE[actualStatus]
    : typeof e.detail === 'string'
      ? e.detail
      : 'This document is no longer awaiting review.'
  return new ProfileDocumentConflictError(message, actualStatus)
}
