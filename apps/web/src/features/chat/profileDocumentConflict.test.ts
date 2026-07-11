import { describe, expect, it } from 'vitest'
import { ApiError } from '../../lib/api/client'
import { ProfileDocumentConflictError, toSettleError } from './profileDocumentConflict'

describe('toSettleError', () => {
  it('converts a 409 with a parseable status into a ProfileDocumentConflictError carrying that status', () => {
    const apiError = new ApiError("Source Document 5 is 'applied', not 'proposed' -- nothing to apply", 409)

    const result = toSettleError(apiError)

    expect(result).toBeInstanceOf(ProfileDocumentConflictError)
    const conflict = result as ProfileDocumentConflictError
    expect(conflict.actualStatus).toBe('applied')
    expect(conflict.message).toMatch(/already applied/i)
  })

  it('parses a rejected-status 409 with an honest, distinct message', () => {
    const apiError = new ApiError("Source Document 9 is 'rejected', not 'proposed' -- nothing to reject", 409)

    const conflict = toSettleError(apiError) as ProfileDocumentConflictError

    expect(conflict).toBeInstanceOf(ProfileDocumentConflictError)
    expect(conflict.actualStatus).toBe('rejected')
    expect(conflict.message).toMatch(/already discarded/i)
  })

  it('falls back to the raw detail when the status cannot be parsed, but still flags it as a conflict', () => {
    const apiError = new ApiError('Some other conflict detail', 409)

    const conflict = toSettleError(apiError) as ProfileDocumentConflictError

    expect(conflict).toBeInstanceOf(ProfileDocumentConflictError)
    expect(conflict.actualStatus).toBeNull()
    expect(conflict.message).toBe('Some other conflict detail')
  })

  it('passes through any non-409 error unchanged', () => {
    const networkError = new Error('network down')

    expect(toSettleError(networkError)).toBe(networkError)

    const serverError = new ApiError('boom', 500)
    expect(toSettleError(serverError)).toBe(serverError)
  })
})
